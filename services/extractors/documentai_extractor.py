"""
Google Cloud Document AI Extractor — Production-grade document extraction.

Uses Google Cloud Document AI processors for high-accuracy extraction
with confidence scores, bounding boxes, and native table support.

Best for: Aadhaar cards, policy cards, estimate proformas, lab reports.

Setup:
    1. Enable Document AI API in Google Cloud Console
    2. Create a Form Parser processor (or specialized processors)
    3. Set environment variables:
       - GOOGLE_CLOUD_PROJECT=your-project-id
       - DOCUMENT_AI_LOCATION=us  (or eu)
       - DOCUMENT_AI_FORM_PROCESSOR_ID=abc123
       - GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
"""

import json
import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractedField,
    ExtractionConfidence,
)

load_dotenv()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Processor routing: which processor type to use per document type
# ---------------------------------------------------------------------------
# Maps document types to preferred processor env vars.
# Falls back to DOCUMENT_AI_FORM_PROCESSOR_ID automatically if the
# specialized processor ID is empty/unset.
PROCESSOR_ENV_MAP = {
    "aadhaar": "DOCUMENT_AI_ID_PROCESSOR_ID",         # Identity Document processor
    "pan": "DOCUMENT_AI_ID_PROCESSOR_ID",
    "attendant_id": "DOCUMENT_AI_ID_PROCESSOR_ID",
    "policy_card": "DOCUMENT_AI_FORM_PROCESSOR_ID",   # Form Parser
    "estimate": "DOCUMENT_AI_FORM_PROCESSOR_ID",       # Form Parser (tables)
    "clinical_notes": "DOCUMENT_AI_OCR_PROCESSOR_ID",  # OCR processor
    "discharge_summary": "DOCUMENT_AI_OCR_PROCESSOR_ID",
    "lab_report": "DOCUMENT_AI_FORM_PROCESSOR_ID",
    "generic": "DOCUMENT_AI_FORM_PROCESSOR_ID",
}


class DocumentAIExtractor(DocumentExtractor):
    """
    Google Cloud Document AI extraction with full layout analysis.

    Features:
      - Per-field confidence scores (0.0–1.0)
      - Bounding box coordinates for every extracted entity
      - Native table extraction (cost breakdowns, lab results)
      - Specialized processors for ID cards vs forms vs OCR
    """

    def __init__(self):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")  # Can be project ID or number
        self.location = os.getenv("DOCUMENT_AI_LOCATION", "asia-southeast1")

        # Processor IDs (set via environment variables)
        self.processors = {
            "form": os.getenv("DOCUMENT_AI_FORM_PROCESSOR_ID", ""),
            "ocr": os.getenv("DOCUMENT_AI_OCR_PROCESSOR_ID", ""),
            "id": os.getenv("DOCUMENT_AI_ID_PROCESSOR_ID", ""),
        }

        self._client_cache = None  # Cached DocumentProcessorServiceClient

        if not self.project_id:
            logger.warning("GOOGLE_CLOUD_PROJECT not set — Document AI will fail at runtime")
        else:
            logger.info(
                "Document AI configured: project=%s, location=%s, form_processor=%s",
                self.project_id, self.location, self.processors.get('form', '(none)')
            )

    def _get_processor_name(self, document_type: str) -> str:
        """Get the fully-qualified processor resource name for a document type."""
        env_key = PROCESSOR_ENV_MAP.get(document_type, "DOCUMENT_AI_FORM_PROCESSOR_ID")
        processor_id = os.getenv(env_key, "")

        # Fallback chain: specialized → form parser → error
        if not processor_id:
            processor_id = self.processors.get("form", "")
            if processor_id:
                logger.info(
                    "No %s set for '%s', falling back to Form Parser (%s)",
                    env_key, document_type, processor_id
                )
        if not processor_id:
            raise ValueError(
                f"No Document AI processor configured for '{document_type}'. "
                f"Set {env_key} or DOCUMENT_AI_FORM_PROCESSOR_ID in your .env file."
            )

        resource = f"projects/{self.project_id}/locations/{self.location}/processors/{processor_id}"
        logger.debug("Processor resource: %s", resource)
        return resource

    def _get_client(self, documentai):
        """Return a cached DocumentProcessorServiceClient (built once per extractor instance)."""
        if self._client_cache is None:
            client_options = None
            if self.location not in ("us", "eu"):
                from google.api_core.client_options import ClientOptions
                api_endpoint = f"{self.location}-documentai.googleapis.com"
                client_options = ClientOptions(api_endpoint=api_endpoint)
                logger.info("Using regional endpoint: %s", api_endpoint)
            self._client_cache = documentai.DocumentProcessorServiceClient(
                client_options=client_options
            )
        return self._client_cache

    def extract(self, file_path: str, document_type: str = "generic") -> ExtractedDocument:
        """Extract key-value fields using Google Cloud Document AI."""
        try:
            from google.cloud import documentai_v1 as documentai
        except ImportError:
            raise ImportError(
                "google-cloud-documentai not installed. "
                "Run: pip install google-cloud-documentai"
            )

        if not self.project_id:
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT must be set in .env for Document AI mode"
            )

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        start = time.monotonic()

        # Get processor for this document type
        processor_name = self._get_processor_name(document_type)
        logger.info(
            "Document AI extracting '%s' (type=%s, processor=%s)",
            file_path.name, document_type, processor_name.split("/")[-1]
        )

        # Read document
        file_bytes = file_path.read_bytes()
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/pdf"

        # Get or create client (cached per extractor instance — avoids reconnect overhead)
        client = self._get_client(documentai)
        raw_document = documentai.RawDocument(content=file_bytes, mime_type=mime_type)
        request = documentai.ProcessRequest(
            name=processor_name,
            raw_document=raw_document,
        )

        result = client.process_document(request=request)
        document = result.document

        elapsed = int((time.monotonic() - start) * 1000)

        # Extract entities as fields
        fields = self._extract_entities(document, file_path.name, document_type)

        # Extract form fields (key-value pairs from Form Parser)
        form_fields = self._extract_form_fields(document, file_path.name, document_type)
        fields.extend(form_fields)

        # Deduplicate: if same key from both entities and form fields, keep higher confidence
        fields = self._deduplicate_fields(fields)

        # Extract tables
        tables = self._extract_tables(document)

        logger.info(
            "Document AI extracted %d fields + %d tables in %dms (avg confidence: %.2f)",
            len(fields), len(tables), elapsed,
            sum(f.confidence for f in fields) / max(len(fields), 1)
        )

        return ExtractedDocument(
            source_file=str(file_path),
            document_type=document_type,
            fields=fields,
            raw_text=document.text or "",
            page_count=len(document.pages),
            tables=tables,
            extraction_method="documentai",
            processing_time_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # Entity extraction (from document.entities)
    # ------------------------------------------------------------------
    def _extract_entities(
        self, document, source_filename: str, document_type: str
    ) -> list[ExtractedField]:
        """Extract structured entities from Document AI response."""
        fields = []

        for entity in document.entities:
            key = entity.type_ or ""
            if not key:
                continue

            # Get the value — prefer normalized_value if available
            value = entity.mention_text or ""
            if entity.normalized_value and entity.normalized_value.text:
                value = entity.normalized_value.text

            confidence = entity.confidence if entity.confidence else 0.0

            # Build bounding box from page_anchor
            bbox = None
            if entity.page_anchor and entity.page_anchor.page_refs:
                ref = entity.page_anchor.page_refs[0]
                if hasattr(ref, 'bounding_poly') and ref.bounding_poly:
                    verts = ref.bounding_poly.normalized_vertices
                    if len(verts) >= 2:
                        bbox = {
                            "x0": verts[0].x, "y0": verts[0].y,
                            "x1": verts[2].x if len(verts) > 2 else verts[1].x,
                            "y1": verts[2].y if len(verts) > 2 else verts[1].y,
                            "page": int(ref.page) + 1 if ref.page else 1,
                        }

            fields.append(ExtractedField(
                key=self._clean_key(key),
                value=value.strip(),
                confidence=confidence,
                confidence_level=self.confidence_level(confidence),
                source_document=source_filename,
                document_type=document_type,
                bounding_box=bbox,
                extraction_method="documentai",
            ))

        return fields

    # ------------------------------------------------------------------
    # Form field extraction (from document.pages[].form_fields)
    # ------------------------------------------------------------------
    def _extract_form_fields(
        self, document, source_filename: str, document_type: str
    ) -> list[ExtractedField]:
        """Extract key-value pairs from Form Parser's form_fields."""
        fields = []

        for page_num, page in enumerate(document.pages, start=1):
            if not hasattr(page, 'form_fields') or not page.form_fields:
                continue

            for form_field in page.form_fields:
                # Get the field name (key)
                key_text = self._get_text_from_layout(
                    form_field.field_name, document.text
                ) if form_field.field_name else ""

                # Get the field value
                value_text = self._get_text_from_layout(
                    form_field.field_value, document.text
                ) if form_field.field_value else ""

                if not key_text.strip():
                    continue

                # Confidence — use the average of key and value confidence
                key_conf = form_field.field_name.confidence if form_field.field_name and form_field.field_name.confidence else 0.0
                val_conf = form_field.field_value.confidence if form_field.field_value and form_field.field_value.confidence else 0.0
                confidence = (key_conf + val_conf) / 2 if (key_conf + val_conf) > 0 else 0.0

                # Bounding box for the value
                bbox = None
                if form_field.field_value and hasattr(form_field.field_value, 'bounding_poly'):
                    bp = form_field.field_value.bounding_poly
                    if bp and bp.normalized_vertices and len(bp.normalized_vertices) >= 2:
                        verts = bp.normalized_vertices
                        bbox = {
                            "x0": verts[0].x, "y0": verts[0].y,
                            "x1": verts[2].x if len(verts) > 2 else verts[1].x,
                            "y1": verts[2].y if len(verts) > 2 else verts[1].y,
                            "page": page_num,
                        }

                fields.append(ExtractedField(
                    key=self._clean_key(key_text.strip()),
                    value=value_text.strip(),
                    confidence=confidence,
                    confidence_level=self.confidence_level(confidence),
                    source_document=source_filename,
                    document_type=document_type,
                    bounding_box=bbox,
                    extraction_method="documentai",
                ))

        return fields

    # ------------------------------------------------------------------
    # Table extraction
    # ------------------------------------------------------------------
    def _extract_tables(self, document) -> list[dict]:
        """Extract table structures from Document AI output."""
        tables = []

        for page_num, page in enumerate(document.pages, start=1):
            if not hasattr(page, 'tables') or not page.tables:
                continue

            for table_idx, table in enumerate(page.tables):
                rows = []
                header_row = []

                # Header rows
                if hasattr(table, 'header_rows') and table.header_rows:
                    for row in table.header_rows:
                        cells = []
                        for cell in row.cells:
                            text = self._get_text_from_layout(cell.layout, document.text)
                            cells.append(text.strip())
                        header_row = cells

                # Body rows
                if hasattr(table, 'body_rows') and table.body_rows:
                    for row in table.body_rows:
                        cells = []
                        for cell in row.cells:
                            text = self._get_text_from_layout(cell.layout, document.text)
                            cells.append(text.strip())
                        rows.append(cells)

                tables.append({
                    "page": page_num,
                    "table_index": table_idx,
                    "headers": header_row,
                    "rows": rows,
                    "row_count": len(rows),
                })

        return tables

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_text_from_layout(layout, full_text: str) -> str:
        """Extract text from layout's text_anchor segments."""
        if not layout or not hasattr(layout, 'text_anchor') or not layout.text_anchor:
            return ""
        text = ""
        for segment in layout.text_anchor.text_segments:
            start = int(segment.start_index) if segment.start_index else 0
            end = int(segment.end_index) if segment.end_index else 0
            text += full_text[start:end]
        return text

    @staticmethod
    def _clean_key(key: str) -> str:
        """Clean up extracted key text."""
        # Remove trailing colons, dots, pipes
        key = key.strip().rstrip(":").rstrip(".").rstrip("|").strip()
        # Remove excessive whitespace
        key = " ".join(key.split())
        return key

    @staticmethod
    def _deduplicate_fields(fields: list[ExtractedField]) -> list[ExtractedField]:
        """Remove duplicate fields, keeping the one with higher confidence."""
        seen = {}
        for f in fields:
            key_lower = f.key.lower().strip()
            if key_lower not in seen or f.confidence > seen[key_lower].confidence:
                seen[key_lower] = f
        return list(seen.values())

    def extract_batch(self, files: list[tuple[str, str]]) -> list[ExtractedDocument]:
        """Extract from multiple documents sequentially."""
        results = []
        for file_path, doc_type in files:
            try:
                result = self.extract(file_path, doc_type)
                results.append(result)
            except Exception as e:
                logger.error("Document AI extraction failed for '%s': %s", file_path, e)
                results.append(ExtractedDocument(
                    source_file=str(file_path),
                    document_type=doc_type,
                    extraction_method="documentai",
                    error=str(e),
                ))
        return results

    def supports_tables(self) -> bool:
        return True

    def supports_handwriting(self) -> bool:
        return True  # With specialized OCR processors
