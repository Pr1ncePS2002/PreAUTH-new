# TPA Pre-Authorization Form Automation

Automated filling of TPA (Third Party Administrator) pre-authorization forms for health insurance. Uses Gemini AI for form analysis + coordinate-based PDF overlay for precise filling.

## What It Does

1. **Analyzes** blank TPA form PDFs — extracts field coordinates using Gemini Vision + pdfplumber
2. **Maps** patient/doctor/insurance data to form fields (exact, alias, fuzzy, or Gemini matching)
3. **Fills** the PDF at precise coordinates using ReportLab overlay
4. **Serves** everything via a FastAPI REST API (14 endpoints)

## Supported Forms

Currently calibrated:
- **Ericson TPA Preauth** — 90 fields, 6 pages (fully tested)
- **Bajaj Allianz TPA Preauth** — 110 fields, 3 pages (calibrated)

33 more blank templates available in `templates/` ready for analysis.

## Project Structure

```
PreAUTH new/
│
├── app.py                      # FastAPI backend (14 REST endpoints)
├── tpa_form_filler.py          # Core PDF form filler (TPAFormFiller class)
├── gemini_analyzer.py          # Gemini Vision + pdfplumber form analyzer
├── requirements.txt            # Python dependencies
├── .env                        # API keys (GEMINI_API_KEY, etc.)
│
├── services/                   # Service layer (used by FastAPI)
│   ├── form_engine.py          #   PDF filling orchestrator
│   ├── mapping_engine.py       #   OCR key → schema field mapping (4-tier)
│   ├── ocr_service.py          #   Document AI / Gemini Vision OCR
│   └── his_service.py          #   Hospital Information System stub
│
├── config/                     # Configuration files
│   └── field_mapping.json      #   90 field IDs with 460+ aliases for mapping
│
├── templates/                  # Blank TPA form PDFs (33 forms)
│   ├── Ericson TPA Preauth.pdf
│   ├── BAJAJ ALLIANZ TPA PREAUTH FORM.pdf
│   └── ... (31 more)
│
├── analyzed/                   # Generated form schemas (field coordinates)
│   ├── Ericson TPA Preauth.json
│   ├── BAJAJ ALLIANZ TPA PREAUTH FORM.json
│   └── *_gemini_raw.json       #   Raw Gemini analysis output
│
├── test_data/                  # Test data per form
│   ├── ericson_test_data.json  #   78 fields for Ericson form
│   └── bajaj_test_data.json    #   76 fields for Bajaj form
│
├── scripts/                    # Utility & maintenance scripts
│   ├── quick_test.py           #   End-to-end Ericson form fill test
│   ├── analyze_pdf.py          #   Legacy PDF analyzer (no Gemini)
│   ├── fix_bajaj_coords.py     #   Coordinate fix script for Bajaj
│   ├── extract_bajaj_coords.py #   pdfplumber ground truth extractor
│   ├── verify_output.py        #   Overlay text position verifier
│   └── list_fields.py          #   Dump all field IDs from a schema
│
├── output/                     # Generated filled PDFs
├── uploads/                    # Uploaded documents (for OCR)
└── docs/                       # Documentation
    ├── COPILOT_SETUP_GUIDE.md
    ├── EXPECTED_OUTPUT.md
    ├── PROJECT_SUMMARY.md
    ├── PROJECT_CONTEXT.md
    └── MASTER_BUILD_PROMPT.md
```

## Quick Start

```bash
# 1. Create & activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up API keys
echo GEMINI_API_KEY=your_key > .env

# 4. Run a test fill (Ericson form)
python scripts/quick_test.py

# 5. Start the API server
python -m uvicorn app:app --reload --port 8000
```

## Usage

### Fill a Form Programmatically

```python
from tpa_form_filler import TPAFormFiller
import json

# Load schema and test data
with open('analyzed/Ericson TPA Preauth.json') as f:
    schema = json.load(f)
with open('test_data/ericson_test_data.json') as f:
    data = json.load(f)

# Fill the form
filler = TPAFormFiller('templates/Ericson TPA Preauth.pdf', schema)
filler.fill_form(data, 'output/filled.pdf')
```

### Analyze a New Form

```python
from gemini_analyzer import GeminiFormAnalyzer

analyzer = GeminiFormAnalyzer('templates/NEW_FORM.pdf')
schema = analyzer.analyze()
# Schema saved to analyzed/NEW_FORM.json
```

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Staff authentication (JWT) |
| GET | `/patient/{mrd}` | Patient demographics from HIS |
| POST | `/documents/upload` | Upload pre-auth documents |
| POST | `/documents/ocr` | Run OCR on uploaded docs |
| POST | `/forms/populate` | Map data + fill TPA form |
| GET | `/forms/preview/{id}` | Download populated PDF |
| GET | `/forms/templates` | List available templates |
| GET | `/forms/schemas` | List analyzed schemas |
| POST | `/forms/submit` | Final submission |
| GET | `/mapping/review` | Review unconfirmed mappings |
| POST | `/mapping/confirm` | Confirm/override a mapping |

## How It Works

### Form Analysis (one-time per form)
`gemini_analyzer.py` uses a hybrid approach:
1. **pdfplumber** extracts exact text positions (ground truth)
2. **Gemini Vision** identifies fillable fields on each page
3. Fields are snapped to ground-truth coordinates
4. Output: JSON schema with `field_id`, `type`, `page`, `coordinates`, `font_size`

### Field Mapping (runtime)
`services/mapping_engine.py` uses a 4-tier strategy:
1. **Exact match** — OCR key matches `field_id` directly
2. **Alias match** — OCR key matches aliases in `config/field_mapping.json`
3. **Fuzzy match** — `rapidfuzz` token_sort_ratio > 70%
4. **Gemini fallback** — LLM suggests mapping for remaining keys

### PDF Filling
`tpa_form_filler.py` creates a transparent ReportLab overlay per page, writes text/checkmarks at exact coordinates, then merges with the template PDF using PyPDF2.

## Adding a New TPA Form

1. Place the blank PDF in `templates/`
2. Run analysis: `python gemini_analyzer.py` (select the form)
3. Review/fix coordinates in `analyzed/<form_name>.json`
4. Create test data in `test_data/<form_name>_test_data.json`
5. Test fill and verify output

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| PyPDF2 | 3.0.1 | PDF reading/merging |
| reportlab | latest | PDF overlay generation |
| pdfplumber | latest | PDF text extraction |
| google-genai | 1.63.0 | Gemini Vision API |
| rapidfuzz | 3.14.3 | Fuzzy string matching |
| fastapi | 0.129.0 | REST API framework |
| uvicorn | 0.41.0 | ASGI server |
| python-dotenv | latest | Environment variables |
| pyjwt | 2.11.0 | JWT authentication |
