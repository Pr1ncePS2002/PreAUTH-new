"""
Base classes and data models for document extraction.

Defines the abstract DocumentExtractor interface and standardized
data models (ExtractedField, ExtractedDocument) used by all backends.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExtractionConfidence(Enum):
    """Confidence level for an extracted field."""
    HIGH = "high"           # > 0.90
    MEDIUM = "medium"       # 0.70 – 0.90
    LOW = "low"             # 0.50 – 0.70
    UNCERTAIN = "uncertain" # < 0.50


@dataclass
class ExtractedField:
    """A single extracted key-value pair with metadata."""

    key: str                            # Original label from document
    value: str                          # Extracted value
    confidence: float = 1.0             # 0.0–1.0 confidence score
    confidence_level: ExtractionConfidence = ExtractionConfidence.HIGH
    source_document: str = ""           # Source filename
    document_type: str = "generic"      # Document category
    bounding_box: Optional[dict] = None # {x0, y0, x1, y1, page}
    normalized_value: Optional[str] = None  # Post-processed value
    extraction_method: str = ""         # "gemini" | "documentai" | "tesseract"

    def to_dict_entry(self) -> dict:
        """Return a rich representation of this field."""
        return {
            "value": self.value,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level.value,
            "source_document": self.source_document,
            "document_type": self.document_type,
            "extraction_method": self.extraction_method,
            "normalized_value": self.normalized_value,
        }


@dataclass
class ExtractedDocument:
    """Complete extraction result from one document."""

    source_file: str
    document_type: str
    fields: list[ExtractedField] = field(default_factory=list)
    raw_text: str = ""                  # Full OCR text (for fallback)
    page_count: int = 0
    tables: list[dict] = field(default_factory=list)  # Table structures
    extraction_method: str = ""
    processing_time_ms: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to flat key-value dict (backward compatible with existing pipeline)."""
        return {f.key: f.value for f in self.fields}

    def to_dict_with_confidence(self) -> dict:
        """Return {key: {value, confidence, source, ...}} dict."""
        return {f.key: f.to_dict_entry() for f in self.fields}

    def get_field(self, key: str) -> Optional[ExtractedField]:
        """Lookup a field by key (case-insensitive)."""
        key_lower = key.lower()
        for f in self.fields:
            if f.key.lower() == key_lower:
                return f
        return None

    @property
    def field_count(self) -> int:
        return len(self.fields)

    @property
    def avg_confidence(self) -> float:
        if not self.fields:
            return 0.0
        return sum(f.confidence for f in self.fields) / len(self.fields)

    @property
    def low_confidence_fields(self) -> list[ExtractedField]:
        """Fields with confidence < 0.70."""
        return [f for f in self.fields if f.confidence < 0.70]


class DocumentExtractor(ABC):
    """Abstract interface for document extraction backends."""

    @abstractmethod
    def extract(self, file_path: str, document_type: str = "generic") -> ExtractedDocument:
        """
        Extract key-value fields from a document.

        Args:
            file_path: Path to the document file (PDF, JPEG, PNG)
            document_type: Category of document (aadhaar, policy_card, estimate, etc.)

        Returns:
            ExtractedDocument with all fields and metadata
        """
        ...

    @abstractmethod
    def extract_batch(self, files: list[tuple[str, str]]) -> list[ExtractedDocument]:
        """
        Extract from multiple documents.

        Args:
            files: List of (file_path, document_type) tuples

        Returns:
            List of ExtractedDocument results in same order
        """
        ...

    @abstractmethod
    def supports_tables(self) -> bool:
        """Whether this extractor can detect table structures."""
        ...

    @abstractmethod
    def supports_handwriting(self) -> bool:
        """Whether this extractor handles handwritten text."""
        ...

    @staticmethod
    def confidence_level(score: float) -> ExtractionConfidence:
        """Map numeric confidence to a level."""
        if score >= 0.90:
            return ExtractionConfidence.HIGH
        elif score >= 0.70:
            return ExtractionConfidence.MEDIUM
        elif score >= 0.50:
            return ExtractionConfidence.LOW
        return ExtractionConfidence.UNCERTAIN
