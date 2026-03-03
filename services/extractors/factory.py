"""
Extractor Factory — Creates the appropriate extraction backend.

Supports:
  - "gemini"     → GeminiVisionExtractor (default, development/fallback)
  - "documentai" → DocumentAIExtractor (production, Google Cloud)
  - "hybrid"     → HybridExtractor (routes per document type)
"""

import logging
import os

from .base import DocumentExtractor

logger = logging.getLogger(__name__)


def create_extractor(mode: str = None) -> DocumentExtractor:
    """
    Factory function to create the appropriate extractor.

    Args:
        mode: "gemini", "documentai", or "hybrid".
              If None, reads from EXTRACTION_MODE env var (default: "gemini").

    Returns:
        A DocumentExtractor instance.
    """
    if mode is None:
        mode = os.getenv("EXTRACTION_MODE", "gemini").lower().strip()

    if mode == "gemini":
        from .gemini_extractor import GeminiVisionExtractor
        logger.info("Using Gemini Vision extractor")
        return GeminiVisionExtractor()

    elif mode == "documentai":
        from .documentai_extractor import DocumentAIExtractor
        logger.info("Using Google Document AI extractor")
        return DocumentAIExtractor()

    elif mode == "hybrid":
        from .hybrid_extractor import HybridExtractor
        logger.info("Using Hybrid extractor (routes per document type)")
        return HybridExtractor()

    else:
        raise ValueError(
            f"Unknown extraction mode: '{mode}'. "
            f"Valid modes: gemini, documentai, hybrid"
        )
