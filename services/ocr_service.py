#!/usr/bin/env python3
"""
OCR Service — Wraps Google Document AI for extracting key-value pairs from documents.

Supports:
  - Aadhaar cards
  - PAN cards
  - Insurance policy cards
  - Clinical notes / discharge summaries
  - Estimate performa
  - Lab reports

Can operate in two modes:
  1. Document AI mode (production): Uses Google Cloud Document AI processors
  2. Gemini Vision mode (development/fallback): Uses Gemini to OCR and extract KV pairs

Usage:
    from services.ocr_service import OCRService

    ocr = OCRService()
    result = ocr.extract("path/to/document.pdf", document_type="aadhaar")
"""

import json
import os
import logging
import base64
import mimetypes
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

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


# ---------------------------------------------------------------------------
# OCR Service
# ---------------------------------------------------------------------------
class OCRService:
    """Extracts key-value pairs from documents using Gemini Vision or Document AI."""

    def __init__(self, mode: str = "gemini"):
        """
        Args:
            mode: "gemini" (default, uses Gemini Vision) or "documentai" (Google Cloud Document AI)
        """
        self.mode = mode
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        if mode == "documentai":
            self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
            self.processor_id = os.getenv("DOCUMENT_AI_PROCESSOR_ID")
            self.location = os.getenv("DOCUMENT_AI_LOCATION", "us")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def extract(
        self,
        file_path: str,
        document_type: str = "generic",
    ) -> dict:
        """
        Extract key-value pairs from a document.

        Args:
            file_path: Path to the document (PDF, JPEG, PNG)
            document_type: One of the DOCUMENT_TYPES keys

        Returns:
            Dict of {key: value} extracted from the document
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        if document_type not in DOCUMENT_TYPES:
            logger.warning("Unknown document_type '%s', using 'generic'", document_type)
            document_type = "generic"

        logger.info("Extracting from '%s' (type=%s, mode=%s)", file_path.name, document_type, self.mode)

        if self.mode == "gemini":
            return self._extract_with_gemini(file_path, document_type)
        elif self.mode == "documentai":
            return self._extract_with_documentai(file_path, document_type)
        else:
            raise ValueError(f"Unknown OCR mode: {self.mode}")

    # ------------------------------------------------------------------
    # Gemini Vision extraction
    # ------------------------------------------------------------------
    def _extract_with_gemini(self, file_path: Path, document_type: str) -> dict:
        """Extract using Gemini Vision API."""
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("google-genai not installed. Run: pip install google-genai")

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set in .env")

        # Read file
        file_bytes = file_path.read_bytes()
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/pdf"

        # Build prompt
        prompt = _build_gemini_prompt(document_type)

        # Call Gemini
        client = genai.Client(api_key=self.api_key)
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
        return self._parse_json_response(text)

    # ------------------------------------------------------------------
    # Document AI extraction (production mode)
    # ------------------------------------------------------------------
    def _extract_with_documentai(self, file_path: Path, document_type: str) -> dict:
        """Extract using Google Cloud Document AI."""
        try:
            from google.cloud import documentai_v1 as documentai
        except ImportError:
            raise ImportError(
                "google-cloud-documentai not installed. "
                "Run: pip install google-cloud-documentai"
            )

        if not self.project_id or not self.processor_id:
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT and DOCUMENT_AI_PROCESSOR_ID must be set in .env"
            )

        # Read document
        file_bytes = file_path.read_bytes()
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/pdf"

        # Configure processor
        name = f"projects/{self.project_id}/locations/{self.location}/processors/{self.processor_id}"

        client = documentai.DocumentProcessorServiceClient()
        raw_document = documentai.RawDocument(content=file_bytes, mime_type=mime_type)
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)

        # Process
        result = client.process_document(request=request)
        document = result.document

        # Extract key-value entities
        extracted = {}
        for entity in document.entities:
            key = entity.type_ or entity.mention_text
            value = entity.mention_text
            if entity.normalized_value and entity.normalized_value.text:
                value = entity.normalized_value.text
            extracted[key] = value

        logger.info("Document AI extracted %d entities", len(extracted))
        return extracted

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

    # ------------------------------------------------------------------
    # Batch extraction
    # ------------------------------------------------------------------
    def extract_batch(
        self,
        files: list[tuple[str, str]],
    ) -> list[dict]:
        """
        Extract from multiple documents.

        Args:
            files: List of (file_path, document_type) tuples

        Returns:
            List of extraction dicts in same order
        """
        results = []
        for file_path, doc_type in files:
            try:
                result = self.extract(file_path, doc_type)
                results.append({"file": file_path, "type": doc_type, "data": result, "error": None})
            except Exception as e:
                logger.error("Failed to extract '%s': %s", file_path, e)
                results.append({"file": file_path, "type": doc_type, "data": {}, "error": str(e)})
        return results


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
def main():
    """Quick test of the OCR service."""
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m services.ocr_service <file_path> [document_type]")
        print(f"Document types: {', '.join(DOCUMENT_TYPES.keys())}")
        print("\nExample: python -m services.ocr_service uploads/aadhaar.jpg aadhaar")
        return

    file_path = sys.argv[1]
    doc_type = sys.argv[2] if len(sys.argv) > 2 else "generic"

    ocr = OCRService(mode="gemini")
    result = ocr.extract(file_path, doc_type)

    print(f"\n{'='*60}")
    print(f"OCR EXTRACTION RESULT — {doc_type}")
    print(f"{'='*60}")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nTotal fields extracted: {len(result)}")


if __name__ == "__main__":
    main()
