# TPA Pre-Authorization System — Deep Architecture Analysis & Migration Plan

**Generated:** 2026-03-01
**Last Updated:** 2026-03-05
**Scope:** Full pipeline audit, Document AI migration analysis, field-wise evaluation, quality framework, implementation plan

---

## RECENT CHANGES (March 2026)

### Two-Phase UI Redesign
- Frontend rebuilt as two-phase wizard: Phase 1 (MRD + upload + OCR) → Phase 2 (6-tab form).
- MRD number is required before extraction; validated against OCR-extracted MRD from documents.
- MRD validation states: `verified`, `mismatch`, `not_found_in_docs`.

### Cost Section — "ESTIMATE ATTACHED"
- Individual cost line items (room rent, ICU, OT, etc.) are NOT populated with amounts on the TPA form.
- First cost line-item field gets `"ESTIMATE ATTACHED"` text (rendered in bold via `FormEngine._draw_text()`).
- Only the sum total field gets the actual amount.
- Sum total field IDs: `cost_total_expected_hospitalization` (Bajaj), `sum_total_expected_cost_of_hospitalization` (Ericson), `sum_total_expected_cost_hospitalization` (Heritage).

### GIPSA / PPN Declaration
- Auto-detection of GIPSA cases from 26 known TPA names.
- PPN Declaration PDF generated for GIPSA cases with expanded field map (50+ aliases covering all 3 schemas + raw OCR keys).
- PPN generator receives merged `raw_ocr_merged` + `mapped_data` for maximum field coverage.

### MRD-Based Filename
- Claim packages named `claim_package_MRD_{mrd_number}.pdf` using staff-entered MRD.
- Staff-entered MRD stored in session; takes priority for filename over OCR-extracted MRD.

### Generate Tab Layout
- Card 1: Pre-generation checklist + summary (summary appears after generation).
- Card 2: Generate button + Go Back & Edit.
- Download/preview appears below after generation.

### Upload Duplicate Fix
- `handleFileSelect()` now replaces files per category instead of appending.

### PDF Merge with Deduplication
- Attachment paths are deduplicated before merge to prevent duplicate pages.

---

## TABLE OF CONTENTS

1. [Part 1 — Current Implementation Audit](#part-1--current-implementation-audit)
2. [Part 2 — Document AI Migration Analysis](#part-2--document-ai-migration-analysis)
3. [Part 3 — Field-Wise Performance Check](#part-3--field-wise-performance-check)
4. [Part 4 — Quality Evaluation Framework](#part-4--quality-evaluation-framework)
5. [Part 5 — Implementation Plan](#part-5--implementation-plan)

---

# PART 1 — CURRENT IMPLEMENTATION AUDIT

## 1.1 Full Pipeline Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  User Uploads │────▶│  OCR Service │────▶│  Raw KV Merge    │────▶│  Mapping Engine   │────▶│  Form Engine     │
│  (multi-file) │     │  (Gemini)    │     │  (first-win)     │     │  (alias+fuzzy)    │     │  (PDF overlay)   │
└──────────────┘     └──────────────┘     └──────────────────┘     └──────────────────┘     └──────────────────┘
         │                  │                      │                        │                        │
         │                  │                      │                        │                        │
    files saved to     Gemini Vision        all_extracted dict       mapped_data dict         Filled PDF
    uploads/           returns JSON KV      (merged across docs)    (field_id → value)       output/*.pdf
```

### Detailed Stage-by-Stage Trace

#### Stage 1: Document Upload (`app.py` — `workflow_start`)
- **File:** `app.py`, lines 680–750
- **Data Structure:** `UploadFile[]` → saved to `uploads/{uuid}_{filename}`
- **Document types:** comma-separated string aligned with file order
- **Tracking:** Each file gets a `file_id` (8-char UUID), stored in `uploaded[]` list
- **Assumption:** Document types are correctly provided by the user in the UI; no server-side classification

#### Stage 2: OCR Extraction (`services/ocr_service.py`)
- **File:** `services/ocr_service.py`, lines 148–230
- **Mode:** `gemini` (default) — uses `google.genai.Client`
- **Process:**
  1. Read file bytes + detect MIME type
  2. Build type-specific prompt via `_build_gemini_prompt()` (lines 109–140)
  3. Send image bytes + prompt to Gemini Vision as multipart content
  4. Parse JSON response, stripping markdown fences
- **Data Structure:** Returns `dict[str, str|bool]` — flat key-value pairs
- **Document AI mode:** Skeleton exists (lines 248–290) but is **commented out in requirements.txt** and untested

**Key observations:**
- No confidence scoring from Gemini extraction
- No retry logic on API failure
- No rate limiting
- JSON parsing has single fallback (returns `{}` on failure)
- No image preprocessing (rotation, DPI normalization, contrast enhancement)
- Prompt is static per document type; no adaptive re-prompting
- Expected fields in prompt are hints only, not enforced

#### Stage 3: Raw KV Merge (`app.py` — `workflow_start`)
- **File:** `app.py`, lines 750–760
- **Strategy:** First-win merge — later documents do NOT overwrite earlier keys
- **Problem:** If Aadhaar extracts a weak "Name" and policy card extracts a better "Name", the first one wins regardless of quality
- **No deduplication or conflict resolution**
- **No source tracking** — impossible to know which document a value came from after merge

#### Stage 4: TPA Detection (`app.py` — `detect_tpa_template`)
- **File:** `app.py`, lines 590–640
- **Strategy:**
  1. Look for `Insurance Company`, `TPA Name`, or `insurance_company` in OCR results
  2. Substring match against `TPA_TEMPLATE_MAP` (40+ entries, lines 190–240)
  3. Fuzzy fallback using `rapidfuzz.partial_ratio` with threshold 60
- **Weakness:** Detection relies on OCR accurately extracting insurance company name — if Gemini misreads it, wrong template is selected
- **Hardcoded:** Entire `TPA_TEMPLATE_MAP` is in `app.py` — should be externalized

#### Stage 5: Mapping Engine (`services/mapping_engine.py`)
- **File:** `services/mapping_engine.py`, lines 96–165
- **Strategy (4 layers):**

| Priority | Layer | File Location | Mechanism |
|----------|-------|---------------|-----------|
| 1 | Exact match | `_resolve_key_exact()` lines 165–180 | `ocr_key in valid_fields` |
| 2 | Alias match | `_resolve_key_exact()` lines 180–190 | Normalized alias → field_id via `_alias_index` |
| 3 | Fuzzy match | `_fuzzy_match()` lines 215–245 | `rapidfuzz.token_sort_ratio` > 70 threshold |
| 4 | Gemini fallback | `gemini_suggest_mappings()` lines 250–320 | LLM-based mapping (not called in main workflow) |

- **Post-mapping in app.py** (lines 770–810):
  - Pass 2: Schema-label fuzzy matching (threshold 65) — matches remaining OCR keys directly against schema field `label` strings
  - `inject_hospital_data()` — hardcoded "Amrita Hospital" values
  - `calculate_age_from_dob()` — computes age from DOB and writes to ALL schema variant field names

**Key observations:**
- `_alias_index` supports multiple field_ids per alias (multi-schema), picks first match in current schema
- Fuzzy threshold of 70 is aggressive — can cause false matches (e.g., "OT Charges" matching "ICU Charges")
- No confidence score returned with mappings
- `claimed_fields` set prevents duplicate mapping but may silently drop valid data
- Gender handling is duplicated in both `MappingEngine.handle_gender()` and `FormEngine._handle_gender()`

#### Stage 6: PDF Generation (`services/form_engine.py`)
- **File:** `services/form_engine.py`, lines 145–240
- **Strategy:** ReportLab overlay on blank PDF template
  1. Load schema JSON (coordinate-based field definitions)
  2. For each page, create a transparent overlay canvas
  3. Draw text/checkboxes at converted coordinates: `y_pdf = page_height - y_schema`
  4. Merge overlay onto template page using PyPDF2
- **Field types supported:** `text_line`, `text_box`, `checkbox`, `date_field`
- **Font:** Hardcoded `Helvetica` / `Helvetica-Bold`
- **No text wrapping** for long values
- **No Unicode/Devanagari support** — will fail for Hindi names/addresses

---

## 1.2 Files Involved Per Stage

| Stage | Primary File | Supporting Files |
|-------|-------------|-----------------|
| Upload | `app.py` | — |
| OCR | `services/ocr_service.py` | `.env` (API key, model) |
| Merge | `app.py` (inline) | — |
| TPA Detection | `app.py` (inline) | — |
| Mapping | `services/mapping_engine.py` | `config/field_mapping.json` |
| Schema Label Match | `app.py` (inline) | `analyzed/*.json` |
| Hospital Injection | `app.py` (inline) | — |
| Age Calculation | `app.py` (inline) | — |
| PDF Fill | `services/form_engine.py` | `templates/*.pdf`, `analyzed/*.json` |
| Session Persist | `app.py` (inline) | `sessions/*.json` |

---

## 1.3 Data Structures

### OCR Output (per document)
```json
{
  "Patient Name": "RAJESH KUMAR SHARMA",
  "Date of Birth": "15/03/1979",
  "Gender": "Male",
  "Policy Number": "POL-2024-567890"
}
```
- Flat dict, string keys from document labels, string/bool values
- Key names depend entirely on what Gemini extracts — **non-deterministic**

### Merged OCR (`raw_ocr_merged`)
```json
{
  "Patient Name": "RAJESH KUMAR SHARMA",
  "Date of Birth": "15/03/1979",
  "Gender": "Male",
  "Policy Number": "POL-2024-567890",
  "Room Rent": "3500",
  "Total Estimate": "95000"
}
```
- Union of all document extractions, first-win on conflicts

### Mapped Data (`mapped_data`)
```json
{
  "patient_name": "RAJESH KUMAR SHARMA",
  "date_of_birth": "15/03/1979",
  "gender_male": true,
  "gender_female": false,
  "policy_number_corporate_name": "POL-2024-567890",
  "hospital_name": "Amrita Hospital"
}
```
- Keys are schema `field_id`s, values are strings/bools

### Schema JSON (`analyzed/*.json`)
```json
{
  "form_title": "...",
  "total_pages": 6,
  "page_heights": {"1": 854.64},
  "fields": [
    {
      "field_id": "patient_name",
      "label": "Name of the Patient:",
      "type": "text_line",
      "page": 1,
      "coordinates": {"x": 250, "y": 359.3},
      "font_size": 9,
      "max_width": 345
    }
  ]
}
```

### Field Mapping Config (`config/field_mapping.json`)
```json
{
  "patient_name": {
    "aliases": ["Patient Name", "Name of Patient", "Insured Name", ...],
    "document_types": ["aadhaar", "policy_card", "preauth_form"],
    "gemini_description": "Full name of the patient or insured person"
  }
}
```
- 1607 lines, ~80+ canonical field_ids
- Each has aliases, document_types, gemini_description
- Some have `field_type` and `group` metadata

---

## 1.4 Identified Weaknesses

### Critical Issues

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| C1 | **No confidence scoring** | `ocr_service.py` | Cannot flag low-confidence extractions for human review |
| C2 | **First-win merge with no source tracking** | `app.py:750–760` | Wrong value may persist if first doc has lower quality extraction |
| C3 | **No retry/fallback on Gemini API failure** | `ocr_service.py:210` | Single API call; empty dict on ANY failure |
| C4 | **Gender handling duplicated** | `mapping_engine.py:430` + `form_engine.py:275` | Inconsistent behavior; double-processing possible |
| C5 | **Hospital data hardcoded** | `app.py:120–135` | "Amrita Hospital" is injected for ALL schemas — no multi-hospital support |
| C6 | **Age calculation uses UTC time** | `app.py:155` | `datetime.utcnow()` instead of local timezone — off by 1 day possible |
| C7 | **No text overflow handling** | `form_engine.py:235` | Long values bleed past `max_width` |
| C8 | **No Unicode font support** | `form_engine.py:230` | Hindi names/addresses will render as blanks or boxes |

### Architectural Issues

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| A1 | **Business logic in app.py** | `app.py:730–810` | Schema-label matching, hospital injection, age calc — all inline in endpoint handlers |
| A2 | **Duplicated mapping logic** | `workflow_start` + `workflow_remap` | Identical 2-pass mapping code duplicated in two endpoints |
| A3 | **TPA_TEMPLATE_MAP hardcoded** | `app.py:190–240` | Should be externalized to config file |
| A4 | **No extraction interface/abstraction** | `ocr_service.py` | Gemini and DocumentAI modes are if/else branches — not pluggable |
| A5 | **No validation layer** | Entire pipeline | No schema validation of OCR output, no type checking of mapped values |
| A6 | **In-memory stores** | `app.py:92–95` | `_populated_forms`, `_ocr_results` lost on restart |
| A7 | **No logging structure** | All files | Uses basic `logging.info/warning` with no structured fields or traceability |

### Mapping-Specific Issues

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| M1 | **Alias collision** | `field_mapping.json` | "Contact Number" aliases exist under both `patient_contact_number` AND `patient_contact_no` — first-match wins based on schema |
| M2 | **Fuzzy threshold too low** | `mapping_engine.py:43` | 70 threshold causes false positives; "OT Charges" may match "Other Charges" |
| M3 | **Schema field_id inconsistency** | `analyzed/*.json` | Ericson uses `treating_doctor_name`, Bajaj uses `doctor_name`, Heritage uses `treating_doctor_name` — mapping must handle all variants |
| M4 | **Gemini fallback not integrated** | `mapping_engine.py:340` | `map_with_gemini_fallback()` exists but is NEVER called in the actual workflow |
| M5 | **Pass 2 label matching re-implements fuzzy** | `app.py:780–810` | Duplicates MappingEngine's fuzzy logic with a different threshold (65 vs 70) |

### Regex / Pattern-Based Extraction Issues

| # | Issue | Details |
|---|-------|---------|
| R1 | **No regex extraction** | System relies entirely on Gemini's prompt-guided extraction; no post-processing regex for dates, phone numbers, Aadhaar numbers |
| R2 | **Date format inconsistency** | Prompt requests DD/MM/YYYY but Gemini may return other formats; `dateutil.parser` is only used in `calculate_age_from_dob()`, not universally |
| R3 | **Phone number normalization missing** | Prompt says "digits only" but no server-side enforcement |

---

## 1.5 Architecture Flow Summary

```
User (browser)
  │
  ├─ Step 1: POST /workflow/start
  │   ├─ Save files to uploads/
  │   ├─ For each file: OCRService.extract(path, doc_type)
  │   │   └─ Gemini Vision → JSON KV dict
  │   ├─ Merge all extractions (first-win)
  │   ├─ Detect TPA: detect_tpa_template(insurance_company)
  │   │   └─ Substring + fuzzy against TPA_TEMPLATE_MAP
  │   ├─ Pass 1: MappingEngine.map_ocr_to_schema(merged, schema_fields)
  │   │   └─ Exact → Alias → Fuzzy (threshold 70)
  │   ├─ MappingEngine.handle_gender(mapped)
  │   ├─ Pass 2: Schema-label fuzzy match (threshold 65) for remaining
  │   ├─ inject_hospital_data(mapped, schema_fields)
  │   ├─ calculate_age_from_dob(mapped)
  │   └─ Save session to sessions/{id}.json
  │
  ├─ Step 2: POST /workflow/{id}/remap  (same logic as above, different schema)
  │   └─ Staff edits in browser → PUT /workflow/{id}/data
  │
  └─ Step 3: POST /workflow/{id}/generate
      ├─ FormEngine.populate(template_pdf, schema_json, data, output_path)
      │   ├─ Load schema JSON
      │   ├─ For each page: create ReportLab overlay
      │   │   ├─ text_line/date_field → drawString(x, page_height - y)
      │   │   ├─ text_box → drawString(x+2, adjusted_y)
      │   │   └─ checkbox (value=True) → drawString("X")
      │   └─ Merge overlay onto template page
      └─ Return form_id for preview/download
```

---

# PART 2 — DOCUMENT AI MIGRATION ANALYSIS

## 2.1 What Changes Are Needed

### Extraction Layer (`services/ocr_service.py`)

| Component | Current State | Required Change |
|-----------|--------------|-----------------|
| `_extract_with_gemini()` | Working, prompt-based | Retain as `VisionExtractor` |
| `_extract_with_documentai()` | Skeleton, entity-based | Complete as `DocumentAIExtractor` |
| Response parsing | Gemini-specific JSON parse | Needs extractor-agnostic output format |
| Confidence scores | Not available | Document AI provides per-entity confidence |
| Layout analysis | Not available | Document AI provides bounding boxes + page structure |

### Modules That Must Be Refactored

1. **`services/ocr_service.py`** — Extract into interface + two implementations
2. **`app.py` workflow endpoints** — Must accept structured extraction output (with confidence, source tracking)
3. **`services/mapping_engine.py`** — Needs to consume structured `ExtractedDocument` instead of raw dict

### What Can Remain Unchanged

1. **`services/form_engine.py`** — PDF generation is downstream; no OCR dependency
2. **`config/field_mapping.json`** — Alias mapping is extraction-agnostic
3. **`analyzed/*.json`** — Schema definitions are independent
4. **`frontend/index.html`** — API contract stays the same
5. **`services/his_service.py`** — No OCR involvement

## 2.2 Proposed Abstraction Layer

### New Module Structure

```
services/
├── __init__.py
├── extractors/
│   ├── __init__.py
│   ├── base.py              # Abstract base + data models
│   ├── gemini_extractor.py  # Current Gemini Vision logic
│   ├── documentai_extractor.py  # New Document AI logic
│   └── factory.py           # Factory to create extractors
├── mapping_engine.py        # Unchanged core, updated input type
├── form_engine.py           # Unchanged
├── his_service.py           # Unchanged
├── validation/
│   ├── __init__.py
│   ├── field_validator.py   # Field-level validation
│   └── schema_validator.py  # Schema conformance checks
└── postprocessing/
    ├── __init__.py
    ├── normalizer.py        # Date, phone, name normalization
    ├── merge_strategy.py    # Smart multi-doc merge
    └── confidence_scorer.py # Field confidence computation
```

### Interface Design

```python
# services/extractors/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExtractionConfidence(Enum):
    HIGH = "high"       # > 0.90
    MEDIUM = "medium"   # 0.70 – 0.90
    LOW = "low"         # 0.50 – 0.70
    UNCERTAIN = "uncertain"  # < 0.50


@dataclass
class ExtractedField:
    """A single extracted key-value pair with metadata."""
    key: str                          # Original label from document
    value: str                        # Extracted value
    confidence: float = 1.0           # 0.0–1.0 confidence score
    confidence_level: ExtractionConfidence = ExtractionConfidence.HIGH
    source_document: str = ""         # Source filename
    document_type: str = "generic"    # Document category
    bounding_box: Optional[dict] = None  # {x0, y0, x1, y1, page}
    normalized_value: Optional[str] = None  # Post-processed value
    extraction_method: str = ""       # "gemini" | "documentai" | "tesseract"


@dataclass
class ExtractedDocument:
    """Complete extraction result from one document."""
    source_file: str
    document_type: str
    fields: list[ExtractedField] = field(default_factory=list)
    raw_text: str = ""                # Full OCR text (for fallback)
    page_count: int = 0
    tables: list[dict] = field(default_factory=list)  # Table structures
    extraction_method: str = ""
    processing_time_ms: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to flat key-value dict (backward compatible)."""
        return {f.key: f.value for f in self.fields}

    def to_dict_with_confidence(self) -> dict:
        """Return {key: {value, confidence, source}} dict."""
        return {
            f.key: {
                "value": f.value,
                "confidence": f.confidence,
                "source": f.source_document,
                "bounding_box": f.bounding_box,
            }
            for f in self.fields
        }


class DocumentExtractor(ABC):
    """Abstract interface for document extraction backends."""

    @abstractmethod
    def extract(self, file_path: str, document_type: str = "generic") -> ExtractedDocument:
        """Extract key-value fields from a document."""
        ...

    @abstractmethod
    def extract_batch(self, files: list[tuple[str, str]]) -> list[ExtractedDocument]:
        """Extract from multiple documents."""
        ...

    @abstractmethod
    def supports_tables(self) -> bool:
        """Whether this extractor can detect table structures."""
        ...

    @abstractmethod
    def supports_handwriting(self) -> bool:
        """Whether this extractor handles handwritten text."""
        ...
```

### VisionExtractor (Refactored Current)

```python
# services/extractors/gemini_extractor.py

import time
from .base import DocumentExtractor, ExtractedDocument, ExtractedField, ExtractionConfidence

class GeminiVisionExtractor(DocumentExtractor):
    """Gemini Vision-based extraction (current implementation, refactored)."""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def extract(self, file_path: str, document_type: str = "generic") -> ExtractedDocument:
        start = time.monotonic()
        # ... existing Gemini Vision logic ...
        raw_dict = self._call_gemini(file_path, document_type)

        fields = []
        for key, value in raw_dict.items():
            fields.append(ExtractedField(
                key=key,
                value=str(value) if not isinstance(value, bool) else value,
                confidence=0.85,  # Gemini doesn't provide per-field confidence
                confidence_level=ExtractionConfidence.MEDIUM,
                source_document=Path(file_path).name,
                document_type=document_type,
                extraction_method="gemini",
            ))

        elapsed = int((time.monotonic() - start) * 1000)
        return ExtractedDocument(
            source_file=file_path,
            document_type=document_type,
            fields=fields,
            extraction_method="gemini",
            processing_time_ms=elapsed,
        )

    def extract_batch(self, files):
        return [self.extract(fp, dt) for fp, dt in files]

    def supports_tables(self) -> bool:
        return False  # Gemini Vision doesn't reliably extract table structure

    def supports_handwriting(self) -> bool:
        return True  # Gemini can handle handwriting via vision
```

### DocumentAIExtractor (New)

```python
# services/extractors/documentai_extractor.py

import time
from .base import DocumentExtractor, ExtractedDocument, ExtractedField, ExtractionConfidence

class DocumentAIExtractor(DocumentExtractor):
    """Google Cloud Document AI extraction with full layout analysis."""

    def __init__(self):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = os.getenv("DOCUMENT_AI_LOCATION", "us")
        # Processor IDs for different document types
        self.processors = {
            "generic": os.getenv("DOCUMENT_AI_FORM_PROCESSOR_ID"),
            "aadhaar": os.getenv("DOCUMENT_AI_ID_PROCESSOR_ID"),
            "policy_card": os.getenv("DOCUMENT_AI_FORM_PROCESSOR_ID"),
            "estimate": os.getenv("DOCUMENT_AI_FORM_PROCESSOR_ID"),
            "clinical_notes": os.getenv("DOCUMENT_AI_OCR_PROCESSOR_ID"),
        }

    def extract(self, file_path: str, document_type: str = "generic") -> ExtractedDocument:
        from google.cloud import documentai_v1 as documentai

        start = time.monotonic()
        processor_id = self.processors.get(document_type, self.processors["generic"])

        name = f"projects/{self.project_id}/locations/{self.location}/processors/{processor_id}"
        client = documentai.DocumentProcessorServiceClient()

        file_bytes = Path(file_path).read_bytes()
        mime_type = mimetypes.guess_type(file_path)[0] or "application/pdf"

        raw_document = documentai.RawDocument(content=file_bytes, mime_type=mime_type)
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)

        result = client.process_document(request=request)
        document = result.document

        fields = []
        for entity in document.entities:
            confidence = entity.confidence if entity.confidence else 0.0
            conf_level = self._confidence_level(confidence)

            # Get bounding box from first page anchor
            bbox = None
            if entity.page_anchor and entity.page_anchor.page_refs:
                ref = entity.page_anchor.page_refs[0]
                if ref.bounding_poly and ref.bounding_poly.normalized_vertices:
                    verts = ref.bounding_poly.normalized_vertices
                    bbox = {
                        "x0": verts[0].x, "y0": verts[0].y,
                        "x1": verts[2].x, "y1": verts[2].y,
                        "page": ref.page + 1,
                    }

            value = entity.mention_text
            normalized = None
            if entity.normalized_value and entity.normalized_value.text:
                normalized = entity.normalized_value.text

            fields.append(ExtractedField(
                key=entity.type_ or entity.mention_text,
                value=value,
                confidence=confidence,
                confidence_level=conf_level,
                source_document=Path(file_path).name,
                document_type=document_type,
                bounding_box=bbox,
                normalized_value=normalized,
                extraction_method="documentai",
            ))

        # Extract tables
        tables = self._extract_tables(document)

        elapsed = int((time.monotonic() - start) * 1000)
        return ExtractedDocument(
            source_file=file_path,
            document_type=document_type,
            fields=fields,
            raw_text=document.text,
            page_count=len(document.pages),
            tables=tables,
            extraction_method="documentai",
            processing_time_ms=elapsed,
        )

    def _extract_tables(self, document) -> list[dict]:
        """Extract table structures from Document AI output."""
        tables = []
        for page in document.pages:
            for table in page.tables:
                rows = []
                for row in table.body_rows:
                    cells = []
                    for cell in row.cells:
                        text = self._get_text_from_layout(cell.layout, document.text)
                        cells.append(text.strip())
                    rows.append(cells)

                headers = []
                for row in table.header_rows:
                    for cell in row.cells:
                        text = self._get_text_from_layout(cell.layout, document.text)
                        headers.append(text.strip())

                tables.append({"headers": headers, "rows": rows})
        return tables

    @staticmethod
    def _get_text_from_layout(layout, full_text: str) -> str:
        """Extract text from layout's text_anchor segments."""
        text = ""
        for segment in layout.text_anchor.text_segments:
            start = int(segment.start_index) if segment.start_index else 0
            end = int(segment.end_index)
            text += full_text[start:end]
        return text

    @staticmethod
    def _confidence_level(score: float) -> ExtractionConfidence:
        if score >= 0.90:
            return ExtractionConfidence.HIGH
        elif score >= 0.70:
            return ExtractionConfidence.MEDIUM
        elif score >= 0.50:
            return ExtractionConfidence.LOW
        return ExtractionConfidence.UNCERTAIN

    def extract_batch(self, files):
        return [self.extract(fp, dt) for fp, dt in files]

    def supports_tables(self) -> bool:
        return True

    def supports_handwriting(self) -> bool:
        return True  # With specialized processors
```

### Factory

```python
# services/extractors/factory.py

from .base import DocumentExtractor
from .gemini_extractor import GeminiVisionExtractor
from .documentai_extractor import DocumentAIExtractor

def create_extractor(mode: str = "gemini") -> DocumentExtractor:
    """Factory function to create the appropriate extractor."""
    if mode == "gemini":
        return GeminiVisionExtractor()
    elif mode == "documentai":
        return DocumentAIExtractor()
    else:
        raise ValueError(f"Unknown extraction mode: {mode}")
```

---

# PART 3 — FIELD-WISE PERFORMANCE CHECK

## 3.1 Document Type Analysis

### 1. Estimate Proforma

**Current extraction flow:**
- `ocr_service.py` → Gemini prompt includes expected fields: `Room Rent`, `ICU Charges`, `OT Charges`, `Total Estimate`, etc.
- Gemini Vision receives the full PDF image and returns flat KV pairs
- Maps to schema via `field_mapping.json` aliases (e.g., "Room Rent" → `per_day_room_rent_nursing_service_charges_patient_diet`)

**Current weaknesses:**
- Estimates are typically **tabular** — Gemini Vision struggles with structured tables
- Multi-row cost breakdowns are collapsed into single values or missed entirely
- No table detection → line items are lost
- Currency formatting not normalized (e.g., "₹3,500" vs "3500")

**Document AI improvement:**
- **Table extraction** natively identifies rows/columns in cost breakdowns
- **Key-value pair detection** matches cost labels to their amounts
- Layout-aware processing correctly links "Room Rent: ___" to its blank value even across complex layouts

### 2. Aadhaar Card

**Current extraction flow:**
- Gemini prompt expects: `Name`, `Date of Birth`, `Gender`, `Aadhaar Number`, `Address`
- Gemini Vision typically handles Aadhaar well (standardized layout)
- Maps to: `patient_name`, `date_of_birth`, `gender_male`/`gender_female`, etc.

**Current weaknesses:**
- **Address parsing unreliable** — multi-line addresses may be concatenated or split
- **Masked Aadhaar** (XXXX-XXXX-1234) — Gemini sometimes OCRs the masked digits incorrectly
- **Regional language text** (Hindi, Tamil) may not be extracted if card is bilingual
- No separate extraction of state, city, PIN from address

**Document AI improvement:**
- Google's **Identity Document processor** is purpose-built for Indian ID cards
- Pre-trained on Aadhaar layout → deterministic field extraction
- Handles bilingual text (English + regional)
- Returns structured address components

### 3. Clinical Notes

**Current extraction flow:**
- Gemini prompt expects: `Diagnosis`, `Doctor Name`, `ICD Code`, `Medications`, etc.
- Clinical notes are typically **unstructured** or semi-structured
- Maps to: `nature_of_illness_complaint`, `treating_doctor_name`, etc.

**Current weaknesses:**
- **Handwriting** is common in clinical notes — Gemini Vision's handwriting accuracy varies
- **Medical abbreviations** (SOB, Hx, Rx, Dx) not expanded or normalized
- **Multi-diagnosis** scenarios lose structure (only one diagnosis field mapped)
- Free-text "plan" or "notes" fields are not extractable to specific schema fields

**Document AI improvement:**
- **Healthcare-specific processors** understand medical terminology
- **Handwriting recognition** is significantly better with specialized training
- Entity extraction can identify medical entities (drugs, diagnoses, codes)
- However, highly unstructured notes remain challenging for any OCR

### 4. Policy Card

**Current extraction flow:**
- Gemini prompt expects: `Policy Number`, `TPA Name`, `Insurance Company`, `Sum Insured`, etc.
- This is the most critical extraction — **drives TPA auto-detection**
- Maps to: `insured_card_id_number`, `tpa_insurance_company_name`, `policy_number_corporate_name`

**Current weaknesses:**
- Policy cards have **highly variable layouts** across insurers
- Logo/watermark text may interfere with value extraction
- Barcode/QR data is not extracted
- "Sum Insured" may be in a table cell that Gemini misreads

**Document AI improvement:**
- Form parser handles variable layouts better
- Can extract structured data from printed cards
- Barcode/QR processing available via specialized processors
- Higher accuracy on dense, small-font text common in insurance cards

## 3.2 Comparison Table

| Field | Document Type | Vision Accuracy | Doc AI Expected | Risk | Required Refactor |
|-------|--------------|----------------|-----------------|------|-------------------|
| Patient Name | Aadhaar | ~95% | ~99% | Low | Extractor swap |
| Date of Birth | Aadhaar | ~90% (format varies) | ~98% (normalized) | Medium | Add date normalization post-proc |
| Gender | Aadhaar | ~98% | ~99% | Low | None |
| Aadhaar Number | Aadhaar | ~85% (masked digits) | ~97% (ID processor) | Medium | Use Identity Document processor |
| Address | Aadhaar | ~75% (multi-line) | ~92% (structured) | High | Add address parser |
| Policy Number | Policy Card | ~88% | ~95% | Medium | Extractor swap |
| Insurance Company | Policy Card | ~85% | ~93% | High (drives TPA detect) | Add validation fallback |
| TPA Name | Policy Card | ~82% | ~91% | High | Add synonym expansion |
| Sum Insured | Policy Card | ~80% (table) | ~94% (layout-aware) | Medium | Extractor swap |
| Room Rent | Estimate | ~70% (tabular) | ~92% (table extraction) | **High** | Table parser needed |
| ICU Charges | Estimate | ~70% (tabular) | ~92% | **High** | Table parser needed |
| OT Charges | Estimate | ~70% (tabular) | ~92% | **High** | Table parser needed |
| Total Estimate | Estimate | ~75% | ~95% | High | Table parser + sum validation |
| Professional Fees | Estimate | ~68% (long label) | ~90% | **High** | Table parser needed |
| Medicine Cost | Estimate | ~70% | ~90% | High | Table parser needed |
| Diagnosis | Clinical Notes | ~80% (printed) / ~55% (handwritten) | ~88% / ~72% | **High** | Handwriting processor |
| ICD Code | Clinical Notes | ~75% | ~88% | High | Medical entity extraction |
| Surgery Name | Clinical Notes | ~78% | ~85% | Medium | Extractor + alias expansion |
| Doctor Name | Clinical Notes | ~85% | ~92% | Medium | Extractor swap |
| Duration of Ailment | Clinical Notes | ~72% | ~85% | Medium | NLU post-processing |
| Past Medical History | Clinical Notes | ~60% (free text) | ~75% | **High** | Structured entity extraction |
| Treating Doctor Name | Various | ~87% | ~94% | Low | Extractor swap |
| Admission Date | Various | ~88% | ~96% (normalized) | Medium | Date normalization |
| Emergency/Planned | Various | ~90% (checkbox) | ~95% | Low | None |

---

# PART 4 — QUALITY EVALUATION FRAMEWORK

## 4.1 Testing Strategy

### Layer 1: Raw Extraction Quality

```python
# tests/test_extraction_quality.py

class ExtractionQualityTest:
    """Evaluate OCR extraction accuracy against ground truth."""

    def __init__(self, ground_truth_dir: str):
        self.ground_truth = self._load_ground_truth(ground_truth_dir)

    def evaluate(self, extractor: DocumentExtractor, test_docs: list) -> ExtractionReport:
        results = []
        for doc_path, doc_type, expected in test_docs:
            extracted = extractor.extract(doc_path, doc_type)
            actual = extracted.to_dict()

            field_results = []
            for key, expected_value in expected.items():
                actual_value = actual.get(key)
                match_score = self._compare_values(expected_value, actual_value)
                field_results.append({
                    "field": key,
                    "expected": expected_value,
                    "actual": actual_value,
                    "score": match_score,
                    "exact_match": expected_value == actual_value,
                })

            results.append({
                "document": doc_path,
                "type": doc_type,
                "field_results": field_results,
                "total_fields": len(expected),
                "matched": sum(1 for r in field_results if r["score"] >= 0.9),
                "accuracy": sum(r["score"] for r in field_results) / len(expected),
            })

        return ExtractionReport(results)

    @staticmethod
    def _compare_values(expected: str, actual: str | None) -> float:
        """Fuzzy comparison returning 0.0–1.0 score."""
        if actual is None:
            return 0.0
        if str(expected).strip().lower() == str(actual).strip().lower():
            return 1.0
        from rapidfuzz import fuzz
        return fuzz.ratio(str(expected).lower(), str(actual).lower()) / 100.0
```

### Layer 2: Mapping Accuracy

```python
# tests/test_mapping_accuracy.py

class MappingAccuracyTest:
    """Evaluate mapping engine accuracy against expected field_id assignments."""

    def evaluate(self, engine: MappingEngine, test_cases: list) -> MappingReport:
        results = []
        for ocr_input, schema_fields, expected_mapping in test_cases:
            actual = engine.map_ocr_to_schema(ocr_input, schema_fields)

            correct = 0
            incorrect = 0
            missing = 0
            extra = 0

            for field_id, expected_value in expected_mapping.items():
                if field_id in actual:
                    if str(actual[field_id]) == str(expected_value):
                        correct += 1
                    else:
                        incorrect += 1
                else:
                    missing += 1

            for field_id in actual:
                if field_id not in expected_mapping:
                    extra += 1

            results.append({
                "correct": correct,
                "incorrect": incorrect,
                "missing": missing,
                "extra": extra,
                "precision": correct / max(correct + incorrect + extra, 1),
                "recall": correct / max(correct + missing, 1),
            })

        return MappingReport(results)
```

### Layer 3: TPA Form Auto-Fill Success Rate

```python
# tests/test_form_fill_rate.py

class FormFillRateTest:
    """Measure what percentage of schema fields get populated."""

    def evaluate(self, schema_path: str, mapped_data: dict) -> FillReport:
        with open(schema_path) as f:
            schema = json.load(f)

        total = len(schema["fields"])
        filled = 0
        empty = 0
        field_status = []

        for field in schema["fields"]:
            fid = field["field_id"]
            value = mapped_data.get(fid)
            is_filled = value is not None and value != ""

            if is_filled:
                filled += 1
            else:
                empty += 1

            field_status.append({
                "field_id": fid,
                "label": field["label"],
                "type": field["type"],
                "page": field["page"],
                "filled": is_filled,
                "value": value,
            })

        return FillReport(
            total_fields=total,
            filled_fields=filled,
            empty_fields=empty,
            fill_rate=filled / max(total, 1),
            field_status=field_status,
        )
```

### Layer 4: Confidence Scoring

```python
# services/postprocessing/confidence_scorer.py

class ConfidenceScorer:
    """Compute field-level confidence scores for the complete pipeline."""

    # Weights for different confidence signals
    WEIGHTS = {
        "extraction_confidence": 0.40,  # From OCR engine
        "mapping_confidence": 0.30,     # Exact=1.0, Alias=0.9, Fuzzy=score/100
        "validation_confidence": 0.20,  # Format/regex validation
        "source_reliability": 0.10,     # Document type reliability
    }

    # Source reliability scores by document type
    SOURCE_RELIABILITY = {
        "aadhaar": 0.95,        # Government ID, highly reliable
        "policy_card": 0.90,    # Printed, standardized
        "estimate": 0.75,       # Hospital-generated, format varies
        "clinical_notes": 0.60, # Often handwritten, subjective
        "discharge_summary": 0.85,
        "lab_report": 0.80,
        "generic": 0.50,
    }

    def score_field(
        self,
        extraction_confidence: float,
        mapping_method: str,  # "exact", "alias", "fuzzy", "label", "gemini"
        fuzzy_score: float,
        validation_passed: bool,
        document_type: str,
    ) -> float:
        """Compute overall confidence for a single mapped field."""

        # Mapping confidence based on method
        mapping_scores = {
            "exact": 1.0,
            "alias": 0.90,
            "fuzzy": fuzzy_score / 100.0,
            "label": fuzzy_score / 100.0 * 0.85,
            "gemini": 0.70,
            "hardcoded": 1.0,  # Hospital data injection
        }
        mapping_conf = mapping_scores.get(mapping_method, 0.5)

        # Validation confidence
        validation_conf = 1.0 if validation_passed else 0.4

        # Source reliability
        source_rel = self.SOURCE_RELIABILITY.get(document_type, 0.5)

        # Weighted average
        score = (
            self.WEIGHTS["extraction_confidence"] * extraction_confidence +
            self.WEIGHTS["mapping_confidence"] * mapping_conf +
            self.WEIGHTS["validation_confidence"] * validation_conf +
            self.WEIGHTS["source_reliability"] * source_rel
        )
        return round(min(max(score, 0.0), 1.0), 3)
```

### Layer 5: Mismatch Detection

```python
# services/validation/field_validator.py

import re
from datetime import datetime

class FieldValidator:
    """Validate extracted and mapped field values against expected formats."""

    VALIDATION_RULES = {
        "date_of_birth": {
            "type": "date",
            "format": r"^\d{2}/\d{2}/\d{4}$",
            "description": "DD/MM/YYYY",
        },
        "patient_contact_number": {
            "type": "phone",
            "format": r"^\d{10}$",
            "description": "10-digit number",
        },
        "admission_date": {
            "type": "date",
            "format": r"^\d{2}/\d{2}/\d{4}$",
        },
        "admission_time": {
            "type": "time",
            "format": r"^\d{2}:\d{2}$",
        },
        "policy_number_corporate_name": {
            "type": "text",
            "min_length": 3,
        },
        "patient_name": {
            "type": "text",
            "format": r"^[A-Z\s.']+$",  # Uppercase names
            "min_length": 2,
        },
        "provisional_diagnosis_icd10_code": {
            "type": "icd10",
            "format": r"^[A-Z]\d{2}(\.\d{1,2})?$",
        },
        # Cost fields
        "per_day_room_rent_nursing_service_charges_patient_diet": {"type": "currency"},
        "icu_charges": {"type": "currency"},
        "ot_charges": {"type": "currency"},
        "professional_fees_surgeon_anesthetist_consultation": {"type": "currency"},
        "sum_total_expected_cost_of_hospitalization": {"type": "currency"},
    }

    def validate_field(self, field_id: str, value) -> dict:
        """Validate a single field value.

        Returns:
            {"valid": bool, "issues": [str], "normalized": str|None}
        """
        rule = self.VALIDATION_RULES.get(field_id)
        if not rule:
            return {"valid": True, "issues": [], "normalized": None}

        issues = []
        normalized = None

        if rule["type"] == "date":
            fmt = rule.get("format")
            if fmt and not re.match(fmt, str(value)):
                issues.append(f"Expected format: {rule.get('description', fmt)}")
                # Attempt normalization
                try:
                    from dateutil import parser
                    dt = parser.parse(str(value), dayfirst=True)
                    normalized = dt.strftime("%d/%m/%Y")
                except Exception:
                    issues.append("Could not parse date")

        elif rule["type"] == "phone":
            digits = re.sub(r"\D", "", str(value))
            if len(digits) == 10:
                normalized = digits
            elif len(digits) == 12 and digits.startswith("91"):
                normalized = digits[2:]
            else:
                issues.append(f"Expected 10-digit phone number, got {len(digits)} digits")

        elif rule["type"] == "currency":
            clean = re.sub(r"[₹,\s]", "", str(value))
            try:
                float(clean)
                normalized = clean
            except ValueError:
                issues.append(f"Could not parse currency value: {value}")

        elif rule["type"] == "icd10":
            if not re.match(rule["format"], str(value)):
                issues.append(f"Invalid ICD-10 code format: {value}")

        elif rule["type"] == "text":
            if rule.get("min_length") and len(str(value)) < rule["min_length"]:
                issues.append(f"Value too short (min {rule['min_length']} chars)")
            if rule.get("format") and not re.match(rule["format"], str(value)):
                issues.append(f"Value does not match expected pattern")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "normalized": normalized,
        }

    def validate_all(self, mapped_data: dict) -> dict:
        """Validate all fields in a mapped data dict.

        Returns:
            {field_id: {"valid": bool, "issues": [], "normalized": str|None}}
        """
        report = {}
        for field_id, value in mapped_data.items():
            if value is not None and value != "" and not isinstance(value, bool):
                report[field_id] = self.validate_field(field_id, value)
        return report
```

## 4.2 Confidence Thresholds

| Level | Score Range | Action | UI Indicator |
|-------|-----------|--------|--------------|
| **High** | ≥ 0.85 | Auto-accept | Green border |
| **Medium** | 0.65 – 0.84 | Flag for review | Orange border |
| **Low** | 0.45 – 0.64 | Require manual verification | Red border |
| **Reject** | < 0.45 | Do not auto-fill; show warning | Red + warning icon |

## 4.3 Logging Improvements

```python
# Structured logging format for the pipeline

import structlog

logger = structlog.get_logger()

# Example structured log entries:

# OCR extraction
logger.info("ocr.extraction.complete",
    session_id=session_id,
    file=filename,
    document_type=doc_type,
    fields_extracted=len(fields),
    extractor="gemini",
    processing_time_ms=elapsed,
    confidence_avg=avg_confidence,
)

# Mapping result
logger.info("mapping.complete",
    session_id=session_id,
    schema=schema_name,
    total_ocr_keys=len(ocr_output),
    exact_matches=exact_count,
    alias_matches=alias_count,
    fuzzy_matches=fuzzy_count,
    unmatched=unmatched_count,
    fill_rate=f"{filled}/{total_schema_fields}",
)

# Field validation
logger.warning("validation.field.failed",
    session_id=session_id,
    field_id=field_id,
    value=value,
    issues=issues,
    confidence=confidence,
)

# PDF generation
logger.info("pdf.generated",
    session_id=session_id,
    form_id=form_id,
    template=template_name,
    schema=schema_name,
    fields_written=fields_written,
    output_path=output_path,
)
```

## 4.4 Error Reporting Structure

```python
@dataclass
class PipelineError:
    """Structured error report for the pipeline."""
    stage: str          # "ocr", "merge", "mapping", "validation", "generation"
    severity: str       # "critical", "warning", "info"
    field_id: str       # Affected field (if applicable)
    message: str
    context: dict       # Additional context (document, value, etc.)
    timestamp: str
    session_id: str
    recoverable: bool   # Whether the pipeline can continue

class ErrorCollector:
    """Collect and report pipeline errors per session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.errors: list[PipelineError] = []

    def add(self, stage: str, severity: str, message: str, **kwargs):
        self.errors.append(PipelineError(
            stage=stage,
            severity=severity,
            field_id=kwargs.get("field_id", ""),
            message=message,
            context=kwargs,
            timestamp=datetime.utcnow().isoformat(),
            session_id=self.session_id,
            recoverable=kwargs.get("recoverable", True),
        ))

    def get_critical(self) -> list[PipelineError]:
        return [e for e in self.errors if e.severity == "critical"]

    def get_by_stage(self, stage: str) -> list[PipelineError]:
        return [e for e in self.errors if e.stage == stage]

    def to_report(self) -> dict:
        return {
            "session_id": self.session_id,
            "total_errors": len(self.errors),
            "critical": len(self.get_critical()),
            "by_stage": {stage: len(self.get_by_stage(stage))
                         for stage in ("ocr", "merge", "mapping", "validation", "generation")},
            "errors": [asdict(e) for e in self.errors],
        }
```

---

# PART 5 — IMPLEMENTATION PLAN

## 5.1 Step-by-Step Migration Plan

### Phase 1: Foundation (Week 1–2) — No Breaking Changes

| Step | Task | Files | Risk |
|------|------|-------|------|
| 1.1 | Create `services/extractors/` package with `base.py` data models | New files | Zero — additive only |
| 1.2 | Refactor current Gemini logic into `GeminiVisionExtractor` class | `ocr_service.py` → `gemini_extractor.py` | Low — internal refactor |
| 1.3 | Add backward-compatible `to_dict()` on `ExtractedDocument` | `base.py` | Zero |
| 1.4 | Update `OCRService` to be a thin wrapper using factory pattern | `ocr_service.py` | Low — API contract unchanged |
| 1.5 | Add `services/validation/field_validator.py` | New file | Zero |
| 1.6 | Add `services/postprocessing/normalizer.py` | New file | Zero |
| 1.7 | Write unit tests for existing mapping engine | New test files | Zero |

### Phase 2: Document AI Integration (Week 3–4)

| Step | Task | Files | Risk |
|------|------|-------|------|
| 2.1 | Install `google-cloud-documentai` | `requirements.txt` | Low |
| 2.2 | Implement `DocumentAIExtractor` class | New file | Zero |
| 2.3 | Add processor configuration to `.env` | `.env.example` | Low |
| 2.4 | Add `EXTRACTION_MODE` env var toggle | `app.py`, `.env` | Low |
| 2.5 | Implement table extraction for estimates | `documentai_extractor.py` | Medium |
| 2.6 | Test Document AI with each document type | Test scripts | Medium |
| 2.7 | Add confidence scoring to extraction output | `extractors/`, `app.py` | Medium |

### Phase 3: Pipeline Improvements (Week 5–6)

| Step | Task | Files | Risk |
|------|------|-------|------|
| 3.1 | Implement smart merge strategy with confidence weighting | `merge_strategy.py` | Medium |
| 3.2 | Add source tracking to merged data | `app.py` | Medium |
| 3.3 | Refactor inline mapping logic from `app.py` into `mapping_engine.py` | Both files | Medium |
| 3.4 | Add field validation to mapping pipeline | `mapping_engine.py`, `field_validator.py` | Low |
| 3.5 | Externalize `TPA_TEMPLATE_MAP` to config file | `app.py` → `config/tpa_templates.json` | Low |
| 3.6 | Externalize `HOSPITAL_INFO` to config file | `app.py` → `config/hospital.json` | Low |
| 3.7 | Add structured logging throughout pipeline | All service files | Low |

### Phase 4: Quality & Testing (Week 7–8)

| Step | Task | Files | Risk |
|------|------|-------|------|
| 4.1 | Build ground truth test dataset (10+ documents per type) | `tests/fixtures/` | Zero |
| 4.2 | Implement extraction quality benchmarks | `tests/test_extraction.py` | Zero |
| 4.3 | Implement mapping accuracy benchmarks | `tests/test_mapping.py` | Zero |
| 4.4 | Implement fill rate benchmarks per schema | `tests/test_fill_rate.py` | Zero |
| 4.5 | A/B test Gemini vs Document AI per document type | `tests/benchmark.py` | Zero |
| 4.6 | Add confidence indicators to frontend UI | `frontend/index.html` | Low |
| 4.7 | Add validation warnings to frontend UI | `frontend/index.html` | Low |

## 5.2 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Document AI costs exceed budget | Medium | High | Set up cost monitoring; use Gemini for low-complexity docs |
| Document AI processor accuracy < Gemini for some doc types | Medium | Medium | Keep both extractors; route documents to best extractor |
| Refactoring breaks existing workflow | Low | High | Full backward compatibility via `to_dict()`; feature flags |
| Google Cloud auth complexity | Medium | Medium | Use service account key; document setup clearly |
| Table extraction quality | Medium | Medium | Add manual override for table values in UI |
| Multi-page document handling | Low | Medium | Document AI handles natively; test with multi-page PDFs |

## 5.3 Backward Compatibility Strategy

1. **Feature flag approach:**
   ```env
   EXTRACTION_MODE=gemini       # "gemini" (default) | "documentai" | "hybrid"
   ENABLE_CONFIDENCE=false      # Show confidence scores in UI
   ENABLE_VALIDATION=false      # Run field validation
   ```

2. **`ExtractedDocument.to_dict()`** ensures downstream code (mapping engine, app.py) continues to receive `dict[str, str]` — zero changes needed initially.

3. **Gradual migration path:**
   - Week 1–2: Same behavior, new structure
   - Week 3–4: Document AI available behind flag
   - Week 5–6: Confidence + validation available behind flag
   - Week 7–8: Flip flags in staging → production

4. **Schema contract preserved:**
   - `analyzed/*.json` format unchanged
   - `config/field_mapping.json` format unchanged
   - API response shapes unchanged

## 5.4 Suggested Folder Structure (Final)

```
PreAUTH new/
├── app.py                          # Slimmed down — delegates to services
├── config/
│   ├── field_mapping.json          # Unchanged
│   ├── hospital.json               # NEW: Externalized hospital info
│   ├── tpa_templates.json          # NEW: Externalized TPA_TEMPLATE_MAP
│   └── extraction_config.json      # NEW: Per-doc-type extractor routing
├── services/
│   ├── __init__.py
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── base.py                 # ExtractedDocument, DocumentExtractor ABC
│   │   ├── gemini_extractor.py     # Refactored from ocr_service.py
│   │   ├── documentai_extractor.py # NEW
│   │   └── factory.py              # NEW
│   ├── postprocessing/
│   │   ├── __init__.py
│   │   ├── normalizer.py           # NEW: Date, phone, currency normalization
│   │   ├── merge_strategy.py       # NEW: Smart multi-doc merge
│   │   └── confidence_scorer.py    # NEW: Pipeline confidence
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── field_validator.py      # NEW: Format validation per field
│   │   └── schema_validator.py     # NEW: Schema conformance
│   ├── mapping_engine.py           # Enhanced with confidence tracking
│   ├── form_engine.py              # Unchanged
│   ├── his_service.py              # Unchanged
│   └── pipeline.py                 # NEW: Orchestrates extract→merge→map→validate
├── tests/
│   ├── fixtures/                   # Ground truth test data
│   ├── test_extraction.py
│   ├── test_mapping.py
│   ├── test_fill_rate.py
│   ├── test_validation.py
│   └── benchmark.py                # A/B comparison
├── analyzed/                       # Unchanged
├── templates/                      # Unchanged
├── frontend/
│   └── index.html                  # Enhanced with confidence UI
├── gemini_analyzer.py              # Unchanged
├── requirements.txt                # Add google-cloud-documentai
└── .env
```

## 5.5 Example Document AI Integration Code

### Environment Configuration

```env
# .env additions for Document AI
EXTRACTION_MODE=gemini              # "gemini" | "documentai" | "hybrid"
GOOGLE_CLOUD_PROJECT=my-project-id
DOCUMENT_AI_LOCATION=us
DOCUMENT_AI_FORM_PROCESSOR_ID=abc123def456
DOCUMENT_AI_OCR_PROCESSOR_ID=ghi789jkl012
DOCUMENT_AI_ID_PROCESSOR_ID=mno345pqr678   # For Aadhaar/PAN
```

### Hybrid Extractor (Smart Routing)

```python
# services/extractors/hybrid_extractor.py

class HybridExtractor(DocumentExtractor):
    """Routes documents to the best available extractor based on type."""

    # Document type → preferred extractor
    ROUTING = {
        "aadhaar": "documentai",      # ID processor excels
        "pan": "documentai",
        "policy_card": "documentai",  # Form parser excels
        "estimate": "documentai",     # Table extraction needed
        "clinical_notes": "gemini",   # Free-text understanding better
        "discharge_summary": "gemini",
        "lab_report": "documentai",   # Structured data
        "generic": "gemini",          # Flexible
    }

    def __init__(self):
        self.gemini = GeminiVisionExtractor()
        self.docai = DocumentAIExtractor()

    def extract(self, file_path: str, document_type: str = "generic") -> ExtractedDocument:
        preferred = self.ROUTING.get(document_type, "gemini")
        try:
            if preferred == "documentai":
                return self.docai.extract(file_path, document_type)
            return self.gemini.extract(file_path, document_type)
        except Exception as e:
            # Fallback to the other extractor
            logger.warning("Primary extractor failed, using fallback: %s", e)
            if preferred == "documentai":
                return self.gemini.extract(file_path, document_type)
            return self.docai.extract(file_path, document_type)
```

### Updated OCR Service (Thin Wrapper for Backward Compatibility)

```python
# services/ocr_service.py (updated)

from services.extractors.factory import create_extractor

class OCRService:
    """Backward-compatible wrapper around the new extractor framework."""

    def __init__(self, mode: str = "gemini"):
        self.extractor = create_extractor(mode)

    def extract(self, file_path: str, document_type: str = "generic") -> dict:
        """Extract key-value pairs (backward compatible — returns flat dict)."""
        result = self.extractor.extract(file_path, document_type)
        return result.to_dict()

    def extract_with_metadata(self, file_path: str, document_type: str = "generic"):
        """Extract with full metadata (new API)."""
        return self.extractor.extract(file_path, document_type)
```

## 5.6 Suggested Improvements to Schema Mapping

### 1. Add Mapping Method Tracking

```python
# Enhanced map_ocr_to_schema return
def map_ocr_to_schema(self, ocr_output, schema_fields, ...) -> MappingResult:
    """Returns MappingResult with method tracking per field."""
    # ... existing logic ...
    return MappingResult(
        mapped={field_id: value, ...},
        methods={field_id: "exact|alias|fuzzy|label", ...},
        scores={field_id: 0.0–1.0, ...},
        unmatched={ocr_key: value, ...},
    )
```

### 2. Improve Fuzzy Threshold Strategy

```python
# Dynamic thresholds based on field importance
CRITICAL_FIELDS = {"patient_name", "date_of_birth", "policy_number_corporate_name"}
FUZZY_THRESHOLD_CRITICAL = 80  # Higher bar for important fields
FUZZY_THRESHOLD_DEFAULT = 70
```

### 3. Add Cost Field Summation Validation

```python
def validate_cost_fields(mapped_data: dict) -> list[str]:
    """Check if cost breakdowns sum to total."""
    cost_fields = [
        "per_day_room_rent_nursing_service_charges_patient_diet",
        "expected_cost_investigation_diagnostic",
        "icu_charges", "ot_charges",
        "professional_fees_surgeon_anesthetist_consultation",
        "medicines_consumables_cost_of_implants",
        "other_hospital_expenses",
    ]
    total_field = "sum_total_expected_cost_of_hospitalization"

    breakdown_sum = 0
    for f in cost_fields:
        val = mapped_data.get(f, "0")
        try:
            breakdown_sum += float(re.sub(r"[₹,\s]", "", str(val)))
        except ValueError:
            pass

    declared_total = mapped_data.get(total_field, "0")
    try:
        total = float(re.sub(r"[₹,\s]", "", str(declared_total)))
    except ValueError:
        return [f"Cannot parse total: {declared_total}"]

    if abs(breakdown_sum - total) > total * 0.05:  # 5% tolerance
        return [f"Cost mismatch: breakdown sum={breakdown_sum}, declared total={total}"]
    return []
```

### 4. Date Normalization Post-Processor

```python
def normalize_dates(mapped_data: dict) -> dict:
    """Normalize all date fields to DD/MM/YYYY."""
    DATE_FIELDS = {
        "date_of_birth", "admission_date", "date_of_first_consultation",
        "accident_date_of_injury", "maternity_expected_date_of_delivery",
        "patient_dob", "patient_representative_date",
        "hospital_declaration_date",
    }
    from dateutil import parser
    for field_id in DATE_FIELDS:
        raw = mapped_data.get(field_id)
        if raw and isinstance(raw, str):
            try:
                dt = parser.parse(raw, dayfirst=True)
                mapped_data[field_id] = dt.strftime("%d/%m/%Y")
            except Exception:
                pass
    return mapped_data
```

---

## APPENDIX A — Summary of All Hardcoded Values

| Value | Location | Recommended Action |
|-------|----------|-------------------|
| "Amrita Hospital" + address | `app.py:120–135` | Move to `config/hospital.json` |
| `TPA_TEMPLATE_MAP` (40+ entries) | `app.py:190–240` | Move to `config/tpa_templates.json` |
| Staff credentials | `app.py:260–265` | Move to env vars or DB |
| `FUZZY_THRESHOLD = 70` | `mapping_engine.py:43` | Move to config; make per-field |
| `GEMINI_THRESHOLD = 0.8` | `mapping_engine.py:44` | Move to config |
| Fuzzy threshold 65 in Pass 2 | `app.py:800` | Consolidate with mapping engine threshold |
| Fuzzy threshold 60 in TPA detect | `app.py:635` | Move to config |
| "Helvetica" font | `form_engine.py:230` | Make configurable per schema |

## APPENDIX B — Known Field Mapping Collisions

These aliases appear under MULTIPLE field_ids in `config/field_mapping.json`:

| Alias | Field IDs | Resolution |
|-------|-----------|------------|
| "Date of Birth" / "DOB" | `date_of_birth`, `patient_dob` | Resolved by schema — picks first valid. Works correctly but confusing. |
| "Contact Number" | `patient_contact_number`, `patient_contact_no` | Schema-dependent. May cause wrong mapping if both exist. |
| "Policy Number" | `policy_number_corporate_name`, `patient_policy_corporate_name` | Same issue. |
| "Hospital Name" | `hospital_name`, `provider_hospital_name` | Schema-dependent. Works but fragile. |
| "Age Years" | `age_years_duration`, `patient_age_years` | Fixed by `calculate_age_from_dob()` writing both. |
| "Room Rent" | `per_day_room_rent_...`, `cost_room_nursing_diet` | Schema-dependent. |
| "Total Estimate" / "Total Cost" | `sum_total_expected_cost_of_hospitalization`, `cost_total_expected_hospitalization` | Schema-dependent. |

**Recommendation:** Add a `schema_scope` field to `field_mapping.json` entries that have collisions, explicitly declaring which schema each applies to. Update the alias index to use schema context for disambiguation.
