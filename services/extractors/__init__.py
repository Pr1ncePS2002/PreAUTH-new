"""
Extractors package — Pluggable document extraction backends.

Available extractors:
  - GeminiVisionExtractor: Uses Gemini Vision API (current default)
  - DocumentAIExtractor: Uses Google Cloud Document AI (production)
  - HybridExtractor: Routes documents to the best extractor per type

Usage:
    from services.extractors.factory import create_extractor

    extractor = create_extractor("gemini")       # or "documentai" or "hybrid"
    result = extractor.extract("path/to/doc.pdf", "aadhaar")
    print(result.to_dict())  # backward-compatible flat dict
"""

from .base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractedField,
    ExtractionConfidence,
)
from .factory import create_extractor

__all__ = [
    "DocumentExtractor",
    "ExtractedDocument",
    "ExtractedField",
    "ExtractionConfidence",
    "create_extractor",
]
