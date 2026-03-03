"""
Hybrid Extractor — Routes documents to the best backend per document type.

Uses Document AI for structured documents (IDs, forms, estimates) and
Gemini Vision for unstructured documents (clinical notes, discharge summaries).

Falls back to the alternate extractor on failure.
"""

import logging
from typing import Optional

from .base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractedField,
)

logger = logging.getLogger(__name__)


class HybridExtractor(DocumentExtractor):
    """
    Routes documents to the best available extractor based on type.

    Routing logic:
      - aadhaar, pan, attendant_id → Document AI (Identity processor)
      - policy_card, estimate, lab_report → Document AI (Form parser)
      - clinical_notes, discharge_summary → Gemini Vision (free-text understanding)
      - generic → Gemini Vision (flexible)

    On failure, automatically falls back to the other extractor.
    """

    # Document AI Form Parser works well for policy cards and estimates.
    # For ID cards (Aadhaar/PAN), an Identity Document processor is needed.
    # If DOCUMENT_AI_ID_PROCESSOR_ID is not set, fall back to Gemini for those types.
    _DOCAI_ROUTING = {
        "aadhaar", "pan", "attendant_id",
        "policy_card", "estimate", "lab_report",
    }
    _GEMINI_ROUTING = {
        "clinical_notes", "discharge_summary", "generic",
    }

    def __init__(self):
        import os
        from .gemini_extractor import GeminiVisionExtractor
        from .documentai_extractor import DocumentAIExtractor

        self.gemini = GeminiVisionExtractor()
        self.docai = DocumentAIExtractor()

        # If no identity processor is configured, redirect ID card types to Gemini.
        # Gemini Vision is much better at Indian ID cards (Aadhaar/PAN with Hindi text).
        has_id_processor = bool(os.getenv("DOCUMENT_AI_ID_PROCESSOR_ID", "").strip())
        self._id_types = {"aadhaar", "pan", "attendant_id"}
        self._use_gemini_for_ids = not has_id_processor
        if self._use_gemini_for_ids:
            logger.info(
                "No DOCUMENT_AI_ID_PROCESSOR_ID set — routing aadhaar/pan/attendant_id to Gemini"
            )

    @property
    def ROUTING(self) -> dict:
        """Dynamic routing based on configured processors."""
        routing = {
            "policy_card": "documentai",
            "estimate": "documentai",
            "lab_report": "documentai",
            "clinical_notes": "gemini",
            "discharge_summary": "gemini",
            "generic": "gemini",
        }
        if self._use_gemini_for_ids:
            routing["aadhaar"] = "gemini"
            routing["pan"] = "gemini"
            routing["attendant_id"] = "gemini"
        else:
            routing["aadhaar"] = "documentai"
            routing["pan"] = "documentai"
            routing["attendant_id"] = "documentai"
        return routing

    def extract(self, file_path: str, document_type: str = "generic") -> ExtractedDocument:
        """Extract using the best extractor for this document type, with fallback."""
        preferred = self.ROUTING.get(document_type, "gemini")
        primary = self.docai if preferred == "documentai" else self.gemini
        fallback = self.gemini if preferred == "documentai" else self.docai

        try:
            logger.info(
                "Hybrid: routing '%s' (type=%s) to %s",
                file_path, document_type, preferred
            )
            result = primary.extract(file_path, document_type)

            # If primary returned very few fields, try fallback too
            if result.field_count == 0 and not result.error:
                logger.warning(
                    "Primary extractor returned 0 fields, trying fallback"
                )
                return fallback.extract(file_path, document_type)

            return result

        except Exception as e:
            logger.warning(
                "Primary extractor (%s) failed for '%s': %s — trying fallback",
                preferred, file_path, e
            )
            try:
                return fallback.extract(file_path, document_type)
            except Exception as e2:
                logger.error("Both extractors failed for '%s': %s", file_path, e2)
                return ExtractedDocument(
                    source_file=str(file_path),
                    document_type=document_type,
                    extraction_method="hybrid",
                    error=f"Both extractors failed. Primary ({preferred}): {e}. Fallback: {e2}",
                )

    def extract_batch(self, files: list[tuple[str, str]]) -> list[ExtractedDocument]:
        """Extract from multiple documents, routing each to the best extractor."""
        results = []
        for file_path, doc_type in files:
            result = self.extract(file_path, doc_type)
            results.append(result)
        return results

    def supports_tables(self) -> bool:
        return True  # Document AI path supports tables

    def supports_handwriting(self) -> bool:
        return True  # Both backends support handwriting to some degree
