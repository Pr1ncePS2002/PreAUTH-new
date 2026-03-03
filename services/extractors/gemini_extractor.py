"""
Gemini Vision Extractor — Refactored from the original OCRService Gemini mode.

Uses Google Gemini Vision API to extract key-value pairs from document images.
Best for: clinical notes, discharge summaries, unstructured documents.
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
# Document type definitions & extraction prompts
# ---------------------------------------------------------------------------
DOCUMENT_TYPES = {
    "aadhaar": {
        "label": "Aadhaar Card",
        "expected_fields": [
            "Name", "Date of Birth", "Gender", "Aadhaar Number", "Address",
            "Father's Name", "VID"
        ],
    },
    "pan": {
        "label": "PAN Card",
        "expected_fields": [
            "Name", "Father's Name", "Date of Birth", "PAN Number",
            "Permanent Account Number"
        ],
    },
    "policy_card": {
        "label": "Insurance Policy Card",
        "expected_fields": [
            "Policy Number", "Insured Name", "Sum Insured", "Policy Start Date",
            "Policy End Date", "TPA Name", "Insurance Company", "Card ID",
            "Employee ID", "Corporate Name", "Date of Birth", "Gender",
            "Relationship", "Member ID"
        ],
    },
    "clinical_notes": {
        "label": "Clinical Notes",
        "expected_fields": [
            "Patient Name", "Doctor Name", "Date", "Diagnosis", "Chief Complaint",
            "History of Present Illness", "Past Medical History", "Medications",
            "Allergies", "Vital Signs", "Plan", "ICD Code"
        ],
    },
    "discharge_summary": {
        "label": "Discharge Summary",
        "expected_fields": [
            "Patient Name", "MRD Number", "Date of Admission", "Date of Discharge",
            "Treating Doctor", "Diagnosis", "Procedure", "Condition at Discharge",
            "Medications at Discharge", "Follow Up", "ICD Code"
        ],
    },
    "estimate": {
        "label": "Estimate / Performa",
        "expected_fields": [
            "Room Rent", "ICU Charges", "OT Charges", "Investigation Cost",
            "Professional Fees", "Medicine Cost", "Consumables", "Implant Cost",
            "Other Charges", "Package Charges", "Total Estimate",
            "Expected Days", "ICU Days", "Room Type", "Surgery Name"
        ],
    },
    "lab_report": {
        "label": "Lab Report",
        "expected_fields": [
            "Patient Name", "Test Name", "Result", "Normal Range", "Date",
            "Doctor Name", "Lab Name"
        ],
    },
    "attendant_id": {
        "label": "Attendant ID Card (Aadhaar/PAN/Voter ID)",
        "expected_fields": [
            "Attendant Name", "Date of Birth", "Gender", "Aadhaar Number",
            "Address", "Father's Name", "Relationship to Patient",
            "Contact Number"
        ],
    },
    "generic": {
        "label": "Generic Document",
        "expected_fields": [],
    },
}


def _build_gemini_prompt(document_type: str) -> str:
    """Build extraction prompt for Gemini Vision."""
    doc_info = DOCUMENT_TYPES.get(document_type, DOCUMENT_TYPES["generic"])
    expected = doc_info.get("expected_fields", [])

    hint = ""
    if expected:
        hint = f"""
Expected fields for this document type ({doc_info['label']}):
{json.dumps(expected, indent=2)}

Extract at minimum these fields if they are visible.
"""

    return f"""You are an expert OCR and document data extraction system for Indian healthcare documents.

Analyze this document image and extract ALL key-value pairs visible on it.
{hint}
Rules:
1. Extract every piece of text that represents a field label and its value.
2. Return dates in DD/MM/YYYY format.
3. Return phone numbers as digits only (no spaces or dashes).
4. For checkboxes, return true/false.
5. If a field is empty or not visible, omit it.
6. Keep the original language for names and addresses.

Return ONLY a valid JSON object with string keys and string/boolean values.
Do NOT include markdown formatting, code fences, or explanations.
Example: {{"Patient Name": "John Doe", "Date of Birth": "01/01/1990"}}
"""


class GeminiVisionExtractor(DocumentExtractor):
    """
    Gemini Vision-based extraction.

    Sends document image + prompt to Gemini and parses the returned JSON.
    Best for unstructured and handwritten documents.

    Two backend modes (controlled by GEMINI_USE_VERTEX in .env):
      GEMINI_USE_VERTEX=false (default) — Consumer Gemini API.
          Requires GEMINI_API_KEY. Data MAY be used for model training.
      GEMINI_USE_VERTEX=true (recommended for PHI/patient data) — Vertex AI.
          Uses GOOGLE_APPLICATION_CREDENTIALS + GOOGLE_CLOUD_PROJECT.
          Data is NEVER used for training (GCP Data Processing Agreement).
          Same model weights, identical response quality.
    """

    def __init__(self):
        self.use_vertex = os.getenv("GEMINI_USE_VERTEX", "false").strip().lower() == "true"
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        if self.use_vertex:
            self.project = os.getenv("GOOGLE_CLOUD_PROJECT")
            self.location = os.getenv("GEMINI_VERTEX_LOCATION", "us-central1")
            self.api_key = None
            logger.info(
                "GeminiVisionExtractor using Vertex AI (project=%s, location=%s) "
                "— patient data NOT used for training",
                self.project, self.location
            )
        else:
            self.api_key = os.getenv("GEMINI_API_KEY")
            self.project = None
            self.location = None
            logger.warning(
                "GeminiVisionExtractor using consumer Gemini API "
                "— set GEMINI_USE_VERTEX=true to protect patient data privacy"
            )

    def _build_client(self, genai):
        """Build the appropriate genai.Client for the configured backend."""
        if self.use_vertex:
            if not self.project:
                raise ValueError(
                    "GOOGLE_CLOUD_PROJECT must be set when GEMINI_USE_VERTEX=true"
                )
            return genai.Client(
                vertexai=True,
                project=self.project,
                location=self.location,
            )
        else:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY not set in .env")
            return genai.Client(api_key=self.api_key)

    def extract(self, file_path: str, document_type: str = "generic") -> ExtractedDocument:
        """Extract key-value fields using Gemini Vision API."""
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("google-genai not installed. Run: pip install google-genai")

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        if document_type not in DOCUMENT_TYPES:
            logger.warning("Unknown document_type '%s', using 'generic'", document_type)
            document_type = "generic"

        start = time.monotonic()

        # Read file
        file_bytes = file_path.read_bytes()
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/pdf"

        # Build prompt
        prompt = _build_gemini_prompt(document_type)

        # Build client (Vertex AI or consumer API)
        client = self._build_client(genai)
        backend = "vertexai" if self.use_vertex else "consumer-api"
        logger.info(
            "Gemini extracting '%s' (type=%s, model=%s, backend=%s)",
            file_path.name, document_type, self.model, backend
        )
        response = client.models.generate_content(
            model=self.model,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                        types.Part.from_text(text=prompt),
                    ],
                )
            ],
        )

        # Parse response
        text = response.text.strip()
        raw_dict = self._parse_json_response(text)

        elapsed = int((time.monotonic() - start) * 1000)

        # Convert flat dict to ExtractedField list
        fields = []
        for key, value in raw_dict.items():
            fields.append(ExtractedField(
                key=key,
                value=str(value) if not isinstance(value, bool) else value,
                confidence=0.85,  # Gemini doesn't return per-field confidence; use a baseline
                confidence_level=ExtractionConfidence.MEDIUM,
                source_document=file_path.name,
                document_type=document_type,
                extraction_method="gemini",
            ))

        logger.info("Gemini extracted %d fields in %dms", len(fields), elapsed)

        return ExtractedDocument(
            source_file=str(file_path),
            document_type=document_type,
            fields=fields,
            extraction_method="gemini",
            processing_time_ms=elapsed,
        )

    def extract_batch(self, files: list[tuple[str, str]]) -> list[ExtractedDocument]:
        """Extract from multiple documents sequentially."""
        results = []
        for file_path, doc_type in files:
            try:
                result = self.extract(file_path, doc_type)
                results.append(result)
            except Exception as e:
                logger.error("Gemini extraction failed for '%s': %s", file_path, e)
                results.append(ExtractedDocument(
                    source_file=str(file_path),
                    document_type=doc_type,
                    extraction_method="gemini",
                    error=str(e),
                ))
        return results

    def supports_tables(self) -> bool:
        return False  # Gemini Vision doesn't reliably extract table structure

    def supports_handwriting(self) -> bool:
        return True  # Gemini handles handwriting via vision

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_json_response(text: str) -> dict:
        """Parse JSON from Gemini response, handling markdown fences."""
        # Strip markdown code fences
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            logger.warning("Gemini returned non-dict JSON: %s", type(result))
            return {}
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Gemini response as JSON: %s", e)
            logger.debug("Raw response: %s", text[:500])
            return {}
