# TPA Pre-Authorization Form Automation

## Description

**PreAUTH** is an AI-powered web application that streamlines the hospital pre-authorization workflow by automating the extraction, mapping, and submission of patient data into Third Party Administrator (TPA) insurance forms.

Healthcare providers typically spend significant time manually transcribing patient information from documents such as Aadhaar cards, insurance policy cards, doctor's notes, and medical estimates into TPA pre-authorization forms. PreAUTH eliminates this manual effort by:

1. **Accepting multiple patient documents** (policy card, Aadhaar, cost estimates, clinical notes, etc.) through a simple web interface.
2. **Running OCR and structured data extraction** powered by Google Gemini Vision, converting scanned or photographed documents into structured key-value data.
3. **Auto-detecting the correct TPA form** based on the insurance company identified in the documents.
4. **Intelligently mapping** the extracted fields to the target form's schema using exact matching, alias lookup, fuzzy matching (RapidFuzz), and an optional Gemini-assisted fallback.
5. **Generating a filled, print-ready PDF** by overlaying the extracted data onto the blank TPA form template using coordinate-based rendering.

The result is a significant reduction in data entry time, fewer transcription errors, and a faster pre-authorization turnaround for patients.

## Key Features

- Upload multiple documents per category (policy card, Aadhaar, estimates, notes, etc.)
- OCR using Gemini (`gemini-2.5-flash` by default)
- Auto-detect TPA template from OCR results
- Review/edit mapped fields in a single-page UI
- Generate and download the filled PDF
- Sessions persist to disk (survive `--reload`)

## Supported Forms (Schemas Present)

- Ericson TPA Preauth
- Bajaj Allianz TPA Preauth
- Heritage Health Pre-Auth

## Requirements

- Windows + Python 3.10+ (recommended)
- A Gemini API key with access to the Generative Language API

## Setup

```powershell
cd "path\to\repo"

# Create venv (first time only)
python -m venv venv

# Activate
.\venv\Scripts\Activate.ps1

# Install deps
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
```

## Run

Start the backend (it also serves the UI):

```powershell
cd "path\to\repo"
.\venv\Scripts\uvicorn.exe app:app --reload --port 8001
```

Open the UI:

- http://localhost:8001/ui

## How To Use

1. Upload documents in Step 1 (each section supports multiple files).
2. Click **Run OCR**.
3. Step 2 shows:
   - OCR extracted data (left)
   - Mapped form fields (right)
   - Auto-detected TPA form (with manual override + re-map)
4. Review/edit fields.
5. Click **Generate PDF**.

Generated PDFs are written to `output/`.

## Repository Layout

```text
.
|-- app.py                  (FastAPI backend + serves UI at /ui)
|-- frontend/               (single-page UI)
|-- services/               (OCR + mapping + PDF generation helpers)
|-- templates/              (blank PDF templates)
|-- analyzed/               (form schema JSON: field IDs + coordinates)
|-- config/                 (field alias mapping and config)
|-- scripts/                (optional helper scripts)
|-- gemini_analyzer.py      (optional: analyze new templates)
|-- tpa_form_filler.py      (PDF filling utilities)
|-- requirements.txt
|-- uploads/                (ignored: temporary uploaded docs)
|-- output/                 (ignored: generated PDFs)
`-- sessions/               (ignored: workflow state; may contain PHI)
```

## Notes

- Don't commit `.env`, `sessions/`, `uploads/`, or `output/` (they are ignored in `.gitignore`).
- Sessions persist to disk, so `uvicorn --reload` won't wipe in-progress work.
- For package versions, see `requirements.txt`.




