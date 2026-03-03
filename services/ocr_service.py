#!/usr/bin/env python3
"""
OCR Service — Backward-compatible wrapper over the new extractors framework.

Now delegates to pluggable extractors:
  - GeminiVisionExtractor (default)
  - DocumentAIExtractor (production)
  - HybridExtractor (routes per document type)

The public API (.extract() returning a flat dict) is unchanged so existing
code in app.py and mapping_engine.py continues to work without modification.

Usage:
    from services.ocr_service import OCRService

    # Flat dict (backward compatible)
    ocr = OCRService(mode="gemini")
    result = ocr.extract("path/to/document.pdf", document_type="aadhaar")

    # Rich result with confidence scores (new API)
    result = ocr.extract_rich("path/to/document.pdf", document_type="aadhaar")
    print(result.avg_confidence, result.to_dict_with_confidence())
"""

import json
import os
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from services.extractors.factory import create_extractor
from services.extractors.base import ExtractedDocument

load_dotenv()

logger = logging.getLogger(__name__)

# Re-export DOCUMENT_TYPES for backward compatibility with any code that imports it
from services.extractors.gemini_extractor import DOCUMENT_TYPES  # noqa: F401


# ---------------------------------------------------------------------------
# OCR Service (thin wrapper)
# ---------------------------------------------------------------------------
class OCRService:
    """
    Extracts key-value pairs from documents using pluggable backends.

    Wraps the new extractors framework while preserving the original API
    so app.py and other callers don't need to change.
    """

    def __init__(self, mode: str = None):
        """
        Args:
            mode: "gemini" (default), "documentai", or "hybrid".
                  If None, reads EXTRACTION_MODE from .env.
        """
        self.mode = mode or os.getenv("EXTRACTION_MODE", "gemini")
        self._extractor = create_extractor(self.mode)
        logger.info("OCRService initialized with mode='%s'", self.mode)

    # ------------------------------------------------------------------
    # Public API — backward compatible (returns flat dict)
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
        result = self._extractor.extract(str(file_path), document_type)
        if result.error:
            logger.error("Extraction error for '%s': %s", file_path, result.error)
            return {}
        return result.to_dict()

    # ------------------------------------------------------------------
    # New API — returns rich ExtractedDocument with confidence
    # ------------------------------------------------------------------
    def extract_rich(
        self,
        file_path: str,
        document_type: str = "generic",
    ) -> ExtractedDocument:
        """
        Extract with full metadata (confidence scores, bounding boxes, etc.).

        Args:
            file_path: Path to the document (PDF, JPEG, PNG)
            document_type: One of the DOCUMENT_TYPES keys

        Returns:
            ExtractedDocument with fields, confidence, tables, etc.
        """
        return self._extractor.extract(str(file_path), document_type)

    # ------------------------------------------------------------------
    # Batch extraction — backward compatible
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

    # ------------------------------------------------------------------
    # Batch extraction — rich (new API)
    # ------------------------------------------------------------------
    def extract_batch_rich(
        self,
        files: list[tuple[str, str]],
    ) -> list[ExtractedDocument]:
        """
        Extract from multiple documents with full metadata.

        Args:
            files: List of (file_path, document_type) tuples

        Returns:
            List of ExtractedDocument results
        """
        return self._extractor.extract_batch(files)


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
def main():
    """Quick test of the OCR service."""
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m services.ocr_service <file_path> [document_type] [mode]")
        print(f"Document types: {', '.join(DOCUMENT_TYPES.keys())}")
        print("Modes: gemini (default), documentai, hybrid")
        print("\nExample: python -m services.ocr_service uploads/aadhaar.jpg aadhaar")
        print("Example: python -m services.ocr_service uploads/estimate.pdf estimate documentai")
        return

    file_path = sys.argv[1]
    doc_type = sys.argv[2] if len(sys.argv) > 2 else "generic"
    mode = sys.argv[3] if len(sys.argv) > 3 else "gemini"

    ocr = OCRService(mode=mode)

    # Use rich extraction to show confidence
    result = ocr.extract_rich(file_path, doc_type)

    print(f"\n{'='*60}")
    print(f"OCR EXTRACTION RESULT — {doc_type} (mode={mode})")
    print(f"{'='*60}")
    print(f"Extraction method: {result.extraction_method}")
    print(f"Processing time: {result.processing_time_ms}ms")
    print(f"Fields extracted: {result.field_count}")
    print(f"Average confidence: {result.avg_confidence:.2f}")

    if result.tables:
        print(f"Tables found: {len(result.tables)}")

    if result.low_confidence_fields:
        print(f"\n⚠ Low confidence fields ({len(result.low_confidence_fields)}):")
        for f in result.low_confidence_fields:
            print(f"  - {f.key}: {f.value} (confidence: {f.confidence:.2f})")

    print(f"\n{'─'*60}")
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    if result.error:
        print(f"\n❌ Error: {result.error}")


if __name__ == "__main__":
    main()
