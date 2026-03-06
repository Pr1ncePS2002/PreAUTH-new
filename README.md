# TPA Pre-Authorization Form Automation

Web app that extracts data from patient documents (Gemini Vision OCR), validates MRD numbers, auto-detects the target TPA form, maps extracted fields to the form schema, and generates a filled PDF claim package.

## Key Features

- **MRD-first workflow** — staff enters MRD number before uploading; validated against OCR-extracted data
- **Multi-document upload** per category (policy card, Aadhaar, estimates, clinical notes, etc.)
- **OCR** using Gemini Vision (`gemini-2.5-flash` by default) with parallel extraction
- **Auto-detect TPA template** from OCR results (insurance company name matching)
- **Two-phase UI** — Phase 1: MRD + upload + OCR → Phase 2: 6-tab review/edit form
- **Cost section**: "ESTIMATE ATTACHED" on PDF — only sum total amount populated
- **GIPSA detection** with automatic PPN Declaration generation (26 known TPAs)
- **Merged claim package** — TPA form + PPN + attachments in a single PDF
- **MRD-based filename** — `claim_package_MRD_{number}.pdf`
- **Sessions persist to disk** (survive `--reload`)

## Supported Forms (Schemas)

- Bajaj Allianz TPA Preauth (110 fields)
- Ericson TPA Preauth
- Heritage Health Pre-Auth

## Requirements

- Windows + Python 3.10+
- A Gemini API key with access to the Generative Language API

## Setup

```powershell
cd "path\to\repo"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
```

## Run

```powershell
.\venv\Scripts\uvicorn.exe app:app --reload --port 8001
```

Open the UI: http://localhost:8001/ui

## How To Use

### Phase 1: Upload & Extract
1. Enter the patient's **MRD Number** (required).
2. Upload documents in each category section (supports multiple files per category).
3. Optionally pre-select a TPA form (or let auto-detection handle it).
4. Click **Extract Data** — OCR runs on all documents in parallel.
5. MRD is validated against numbers found in clinical docs and estimates.

### Phase 2: Review & Generate
6. Review auto-filled fields across 6 tabs:
   - **Patient Details** — demographics, hospital info
   - **Insurance & TPA** — policy, GIPSA toggle
   - **Clinical Details** — diagnosis, treatment, hospitalization
   - **Cost & Declarations** — only total amount editable ("ESTIMATE ATTACHED" for line items)
   - **Attachments** — upload additional supporting documents
   - **Generate PDF** — checklist, generate, preview, download
7. Edit any field as needed.
8. Click **Generate Final PDF** — creates the claim package.
9. Preview and download.

## Repository Layout

```text
.
├── app.py                  (FastAPI backend + serves UI at /ui)
├── frontend/               (single-page two-phase UI)
├── services/
│   ├── ocr_service.py      (Gemini Vision OCR)
│   ├── mapping_engine.py   (OCR key → schema field mapping)
│   ├── form_engine.py      (PDF overlay filling)
│   ├── his_service.py      (stub HIS integration)
│   ├── pdf/
│   │   ├── generate_ppn_pdf.py  (PPN Declaration generator)
│   │   └── merge_documents.py   (multi-PDF merge)
│   └── extractors/         (extraction abstraction layer)
├── templates/              (blank PDF templates)
├── analyzed/               (form schema JSON: field IDs + coordinates)
├── config/
│   ├── field_mapping.json  (field alias mapping)
│   └── tpa-sepl-sa-key.json
├── scripts/                (optional helper scripts)
├── test_data/              (sample test data per schema)
├── gemini_analyzer.py      (analyze new PDF templates)
├── tpa_form_filler.py      (PDF filling utilities)
├── requirements.txt
├── COPILOT_CONTEXT.md      (detailed project context for Copilot)
├── ARCHITECTURE_ANALYSIS.md (deep architecture analysis + migration plan)
├── PRODUCTION_PLAN.md
├── uploads/                (ignored: temporary uploaded docs)
├── output/                 (ignored: generated PDFs)
└── sessions/               (ignored: workflow state; may contain PHI)
```

## Notes

- Don't commit `.env`, `sessions/`, `uploads/`, or `output/`.
- Sessions persist to disk — `uvicorn --reload` won't wipe in-progress work.
- Cost section writes "ESTIMATE ATTACHED" in bold on the first cost line item; only sum total gets the actual amount.
- GIPSA cases get an auto-generated PPN Declaration merged into the claim package.
- Final claim package is named by MRD number for easy identification.




