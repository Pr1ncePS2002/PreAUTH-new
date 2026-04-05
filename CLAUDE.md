# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TPA Pre-Authorization Form Automation system that extracts data from patient documents via OCR (Gemini Vision), validates MRD numbers, auto-detects target TPA forms, maps fields to schemas, and generates filled PDF claim packages for Indian insurance TPAs.

## Commands

### Run Development Server (Desktop Only)
```powershell
.\venv\Scripts\uvicorn.exe app:app --reload --port 8001
```

### Run with Mobile QR Upload (LAN Access)
```powershell
.\venv\Scripts\uvicorn.exe app:app --reload --host 0.0.0.0 --port 8001
```
Requires `APP_BASE_URL` in `.env` set to machine's LAN IP.

### Add New TPA Form Template
```powershell
# 1. Analyze PDF template → generates schema JSON
python gemini_analyzer.py "templates/NewForm.pdf"

# 2. Generate test data from schema
python scripts/generate_test_data.py "analyzed/NewForm.json"

# 3. Visual QA - fill PDF with test data
python scripts/test_fill.py --template "templates/NewForm.pdf" --schema "analyzed/NewForm.json" --data "test_data/NewForm_test_data.json" --output "output/NewForm_filled.pdf"
```

## Architecture

### Two-Phase UI Flow
**Phase 1** (Upload & Extract): MRD entry → document upload → parallel OCR → TPA auto-detection → field mapping
**Phase 2** (Review & Generate): 6-tab form review/edit → PDF generation → claim package download

### Backend Pipeline (app.py ~1900 lines)
```
Document Upload → OCR Extraction → Raw Merge → TPA Detection → Field Mapping → Session Storage → PDF Generation
```

### Extraction Layer (services/extractors/)
- `gemini_extractor.py` - Gemini Vision (default, consumer API)
- `documentai_extractor.py` - Google Document AI (production)
- `hybrid_extractor.py` - Routes by document type
- Mode selected via `EXTRACTION_MODE` env var: `gemini` | `documentai` | `hybrid`

### Key Services
| File | Purpose |
|------|---------|
| `services/ocr_service.py` | OCR orchestration wrapper |
| `services/mapping_engine.py` | OCR keys → schema fields (exact → alias → fuzzy → Gemini fallback) |
| `services/form_engine.py` | PDF population via coordinate overlay (reportlab) |
| `services/pdf/generate_ppn_pdf.py` | GIPSA PPN Declaration generator |
| `services/pdf/merge_claim_documents.py` | Multi-PDF merge for claim package |

### Data Flow
- Schemas: `analyzed/{TPA_NAME}.json` - field IDs, coordinates, page numbers
- Templates: `templates/{TPA_NAME}.pdf` - blank PDF forms
- Mappings: `config/field_mapping.json` - OCR key aliases (100+ entries)
- Sessions: `sessions/{id}.enc` - Fernet-encrypted PHI at rest

## Key Technical Details

### TPA Template Detection
Fuzzy match (60% threshold via rapidfuzz) on insurance company name from OCR. 35+ templates supported.

### Field Mapping Priority
1. Exact match (field_id == OCR key)
2. Alias match (config/field_mapping.json)
3. Fuzzy match (70% threshold)
4. Gemini LLM fallback

### Cost Section Behavior
Line items show "ESTIMATE ATTACHED" (bold); only sum-total field gets actual amount. Sum-total field ID varies per schema.

### GIPSA Detection
26 known GIPSA TPAs trigger automatic PPN Declaration PDF generation, merged into claim package.

### Session Persistence
In-memory dict + disk persistence (`sessions/{id}.enc`). Survives `--reload`. Encrypted via `SESSION_ENCRYPTION_KEY` env var.

### MRD Validation States
`verified` (match found) | `mismatch` (conflict) | `not_found_in_docs`

## Environment Variables

Required in `.env`:
```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
SESSION_ENCRYPTION_KEY=<Fernet key>
```

For mobile upload:
```env
APP_BASE_URL=http://<LAN_IP>:8001
```

For Document AI:
```env
EXTRACTION_MODE=documentai
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
GOOGLE_CLOUD_PROJECT=project-id
```

## Important Files

| File | Content |
|------|---------|
| `FLAWS_AND_IMPLEMENTATION_PLAN.md` | Security audit (F-001 to F-015+), edge cases, fixes, on-premise deployment |
| `ARCHITECTURE_ANALYSIS.md` | Deep technical analysis, migration plan |
| `PRODUCTION_PLAN.md` | Phase-by-phase implementation roadmap |
| `WORKFLOW.md` | PDF analysis & form onboarding workflow |
| `context.md` | API endpoint drift notes |

## API Endpoint Notes

Actual endpoints (not always matching docs):
- `POST /mobile/create-session` - Creates mobile upload session
- `/ws/upload/{upload_token}` - WebSocket for upload progress
- `POST /workflow/start` - Starts extraction workflow
- `POST /workflow/{session_id}/generate` - Generates final PDF

## Coordinate System

PDF coordinates use reportlab defaults: origin at top-left, y increases downward.
