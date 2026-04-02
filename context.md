# Copilot Context — TPA Pre-Authorization System (Comprehensive)

Purpose: single, detailed context map for future tasks.  
Use this as the first read before modifying code, then jump to the exact source sections listed below.

---

## 1) Repository snapshot

- Stack: `FastAPI` backend + static frontend (`frontend/index.html`, `frontend/mobile-upload.html`).
- Primary runtime entrypoint: `app.py`.
- Key pipeline: upload -> OCR extraction -> merge -> map to schema -> staff review -> PDF generation -> claim package merge.
- Extraction abstraction exists (`services/extractors/*`) with modes:
  - `gemini`
  - `documentai`
  - `hybrid`
- State storage:
  - In-memory dicts in `app.py` for active process state.
  - Session persistence to disk (`sessions/*.json`) via `_save_session` and `_load_session`.
- Available tracked artifacts:
  - schemas in `analyzed/*.json`
  - mapping config in `config/field_mapping.json` (`"aliases"` appears 100 times)
  - helper scripts in `scripts/*.py`
  - plan docs: `FLAWS_AND_IMPLEMENTATION_PLAN.md`, `ARCHITECTURE_ANALYSIS.md`, `PRODUCTION_PLAN.md`

---

## 2) Canonical source-of-truth order

When details conflict:

1. Runtime behavior in `app.py` and service modules (actual behavior).
2. Frontend behavior in `frontend/index.html` and `frontend/mobile-upload.html`.
3. Planning docs (design intent, may lag implementation).

Important current drift:

- `ARCHITECTURE_ANALYSIS.md` references `POST /mobile/initiate-upload`; code uses `POST /mobile/create-session`.
- `ARCHITECTURE_ANALYSIS.md` references `GET /mobile/ws/{upload_token}`; code uses WebSocket route `/ws/upload/{upload_token}`.

---

## 3) End-to-end runtime flow (actual implementation)

### A. Desktop + mobile upload handshake

- Desktop enters MRD in `frontend/index.html`.
- Desktop calls `POST /mobile/create-session`:
  - creates token (`_generate_upload_token`)
  - returns QR code as base64 PNG
  - stores `_upload_sessions[token] = {mrd_number, created, expires_at, files[]}`
- Phone opens `frontend/mobile-upload.html` via `/mobile-upload?session=<token>`.
- Phone validates token via `GET /mobile/session/{session_token}`.
- Desktop subscribes to `/ws/upload/{upload_token}`; mobile uploads trigger `_ws_broadcast`.
- Mobile uploads via `POST /mobile/upload` (supports multiple files, per-file type, extension/size checks).

### B. OCR + merge + mapping

- Desktop "Extract Data" -> `POST /workflow/start`.
- Backend combines desktop files + token-linked mobile files.
- OCR runs in parallel (`asyncio.gather`) using `ocr_service.extract(path, doc_type)`.
- Raw merge is first-win (`if key not in all_extracted`).
- TPA detection:
  - by substring/fuzzy against `TPA_TEMPLATE_MAP`.
  - fuzzy threshold for TPA detection is 60 in `detect_tpa_template`.
- Mapping:
  1. `MappingEngine.map_ocr_to_schema` (exact/alias/fuzzy over canonical mapping)
  2. `MappingEngine.handle_gender`
  3. pass-2 label-based matching against selected schema labels in `app.py`
  4. inject hardcoded hospital fields
  5. calculate age from DOB variants
- MRD validation compares entered MRD against OCR candidate keys and stores `mrd_validation`.
- session persisted with:
  - `raw_extractions`
  - `raw_ocr_merged`
  - `mapped_data`
  - `tpa_detection`
  - MRD info

### C. Staff review + generate

- Staff edits fields in 6-tab UI in `frontend/index.html`.
- Save verified data: `PUT /workflow/{session_id}/data`.
- Optional MRD edit: `PUT /workflow/{session_id}/mrd`.
- Optional GIPSA/PPN flags: `POST /workflow/{session_id}/gipsa`.
- Generate package: `POST /workflow/{session_id}/generate`.
  - fills TPA form via `FormEngine.populate`
  - optionally generates PPN (`generate_ppn_pdf`)
  - merges PDFs/images (`merge_claim_documents`)
  - names output using MRD if available: `claim_package_MRD_{mrd}.pdf`
- Download: `GET /forms/export/{form_id}`.

---

## 4) Frontend behavior map

### `frontend/index.html` (desktop SPA)

- Two-phase UX:
  - Phase 1: MRD + upload + QR/live sync + extract
  - Phase 2: tabbed review/edit + generate
- Tabs:
  - Patient
  - Insurance & TPA
  - Clinical
  - Cost & Declarations
  - Attachments
  - Generate PDF
- Cost logic in UI:
  - tracks known sum-total field IDs across schemas
  - line-item cost fields are not individually sent as amounts
  - first cost line item forced to `"ESTIMATE ATTACHED"` at generation time
- Mobile sync:
  - QR created on MRD entry/debounce
  - live status dot for WebSocket
  - mobile uploads shown as badges by document type
- MRD card in phase 2:
  - inline validation banner with states: verified/mismatch/not found.

### `frontend/mobile-upload.html`

- Session token-driven page with expiry timer.
- Per-document-type card UI.
- Modal supports:
  - camera capture
  - gallery/PDF upload
- Images route through the crop screen (corner selection) before upload; PDFs bypass to modal queue directly.
- Crop screen features:
  - 4-handle perspective corner selection with magnifier loupe.
  - **Rotate button** (90° CW per tap) to fix inverted/sideways captures before sending.
  - Skip option to send without cropping.
- Client-side image resize to max 3000px before crop screen; JPEG 0.88 quality.
- Upload endpoint for cropped images: `POST /mobile/scan-upload` (base64 + corners JSON).
- Upload endpoint for PDFs: `POST /mobile/upload` (multipart FormData).

---

## 5) Backend module map (what each file owns)

- `app.py`
  - all API routes
  - session persistence helpers
  - MRD validation, TPA detection
  - workflow orchestration
  - mobile upload/session + websocket sync
  - claim package generation and export

- `services/ocr_service.py`
  - thin compatibility layer over extractor factory.
  - public API stays flat dict compatible (`extract`) + rich metadata API (`extract_rich`).

- `services/extractors/base.py`
  - extraction interface + dataclasses (`ExtractedField`, `ExtractedDocument`).

- `services/extractors/factory.py`
  - `create_extractor(mode)` mode switch.

- `services/extractors/gemini_extractor.py`
  - prompt-based Gemini Vision extraction.
  - supports consumer API or Vertex path via env.
  - baseline confidence values assigned (Gemini does not provide per-field confidence here).

- `services/extractors/documentai_extractor.py`
  - Document AI extraction with entities, form_fields, tables.
  - per-document-type processor routing + fallback to form processor.
  - confidence + bounding boxes preserved.

- `services/extractors/hybrid_extractor.py`
  - route by doc type to docai or gemini.
  - can force ID docs to gemini if no ID processor configured.
  - fallback to alternate extractor on failures.

- `services/mapping_engine.py`
  - exact/alias/fuzzy mapping against `config/field_mapping.json`
  - ignored OCR noise keys
  - unmatched logging
  - optional Gemini fallback mapping
  - gender normalization helper

- `services/form_engine.py`
  - coordinate-based PDF overlay fill
  - text, text_box, checkbox rendering
  - coordinate conversion top-left -> PDF bottom-left
  - bold rendering for value `"ESTIMATE ATTACHED"`

- `services/pdf/generate_ppn_pdf.py`
  - fills PPN declaration template
  - hardcoded hospital fields + multi-schema alias map + computed fields.

- `services/pdf/merge_claim_documents.py`
  - merge order: TPA -> PPN -> attachments
  - converts image attachments to PDF pages.

- `services/his_service.py`
  - explicit stub mode with mock patient/admission/doc data.
  - `build_preauth_data` prepares preauth-shaped data.

- `tpa_form_filler.py`
  - legacy/manual fill utility and analyzer classes used by helper scripts.

- `gemini_analyzer.py`
  - schema generation utility using pdfplumber + Gemini + coordinate calibration.

---

## 6) Data contracts and key structures

- Session object (`_sessions[session_id]`) typically contains:
  - `uploaded_files`
  - `raw_extractions`
  - `raw_ocr_merged`
  - `mapped_data`
  - `tpa_detection`
  - `mrd_number`
  - `mrd_validation`
  - `attachments`
  - `is_gipsa_case`, `generate_ppn`
  - status timestamps (`created`, `verified_at`)

- Mapping output shape:
  - final key space is schema `field_id` values from selected `analyzed/*.json`.

- Cost behavior:
  - line-item fields mostly replaced by banner strategy.
  - sum total field retains numeric estimate.

- PPN generation data:
  - built from merged `raw_ocr_merged` + `mapped_data` (mapped values win).

---

## 7) API inventory (current implementation)

### Auth

- `POST /auth/login`

### HIS

- `GET /patient/search`
- `GET /patient/{mrd}`
- `GET /patient/{mrd}/preauth-data`

### Documents

- `POST /documents/upload`
- `POST /documents/ocr`
- `POST /documents/ocr-and-map`

### Forms/Mapping

- `GET /forms/templates`
- `GET /forms/schemas`
- `GET /forms/schema/{schema_name}/fields`
- `POST /forms/populate`
- `GET /forms/preview/{form_id}`
- `POST /forms/populate-from-his`
- `POST /forms/submit`
- `GET /forms/export/{form_id}`
- `GET /mapping/review`
- `POST /mapping/confirm`
- `GET /mapping/fields`
- `GET /tpa/detect`

### Workflow

- `POST /workflow/start`
- `GET /workflow/{session_id}`
- `POST /workflow/{session_id}/remap`
- `PUT /workflow/{session_id}/data`
- `PUT /workflow/{session_id}/mrd`
- `POST /workflow/{session_id}/generate`
- `POST /workflow/{session_id}/attachments`
- `GET /workflow/{session_id}/attachments`
- `DELETE /workflow/{session_id}/attachments/{file_id}`
- `POST /workflow/{session_id}/gipsa`
- `GET /workflow/{session_id}/schema-fields`

### Mobile upload + realtime

- `POST /mobile/create-session`
- `GET /mobile/session/{session_token}`
- `POST /mobile/upload` (PDFs + non-crop images, multipart FormData)
- `POST /mobile/scan-upload` (images from crop screen — base64 + 4 corner coords; applies server-side perspective warp before saving)
- `GET /mobile/uploads/{session_token}`
- `WS /ws/upload/{upload_token}`
- `GET /mobile-upload` (serves mobile page)

### System/UI

- `GET /ui`
- `GET /ui/{rest_of_path}`
- `GET /`
- `GET /health`

---

## 8) Environment/config knobs (observed)

- extraction:
  - `EXTRACTION_MODE=gemini|documentai|hybrid`
  - `GEMINI_API_KEY`, `GEMINI_MODEL`
  - `GEMINI_USE_VERTEX`, `GOOGLE_CLOUD_PROJECT`, `GEMINI_VERTEX_LOCATION`
  - Document AI: `DOCUMENT_AI_LOCATION`, `DOCUMENT_AI_*_PROCESSOR_ID`

- auth/session/runtime:
  - `JWT_SECRET`
  - `SESSION_EXPIRY_MINUTES`
  - `MAX_UPLOAD_SIZE_MB`
  - `DATA_RETENTION_HOURS`
  - `APP_BASE_URL`

- production notes:
  - CORS currently `allow_origins=["*"]` in code.
  - session files currently JSON plaintext in `sessions/`.

---

## 9) Documentation jump map (exact section names)

Use these exact headings for fast lookup.

### `FLAWS_AND_IMPLEMENTATION_PLAN.md`

- `SECTION 1 — CRITICAL PRODUCTION FLAWS (fix before go-live)`
  - `1.1 Security Flaws` (`F-001` to `F-006`)
  - `1.2 Data Integrity Flaws` (`F-007` to `F-012`)
  - `1.3 Reliability / Error Handling Flaws` (`F-013` onward)
  - `1.4 PDF Generation Flaws`
  - `1.5 Frontend / UX Flaws`
- `SECTION 2 — EDGE CASES TO HANDLE`
  - `2.1 Phone Camera / Image Quality Edge Cases`
  - `2.2 Data / Field Edge Cases`
  - `2.3 TPA / PDF Generation Edge Cases`
- `SECTION 3 — MOBILE PHONE SCAN IMPLEMENTATION PLAN`
  - `3.1 — Camera Input (Frontend)`
  - `3.2 — Image Pre-Processing Before Upload`
  - `3.3 — OCR Quality Feedback Loop`
  - `3.4 — Master Form Population from Phone Scan`
  - `3.5 — PWA + Responsive UI`
  - `3.6 — Security Hardening for Mobile`

### `ARCHITECTURE_ANALYSIS.md`

- `RECENT CHANGES (March 2026)`
- `PART 1 — CURRENT IMPLEMENTATION AUDIT`
  - `1.1 Full Pipeline Architecture`
  - `1.2 Files Involved Per Stage`
  - `1.3 Data Structures`
  - `1.4 Identified Weaknesses`
  - `1.5 Architecture Flow Summary`
- `PART 2 — DOCUMENT AI MIGRATION ANALYSIS`
- `PART 3 — FIELD-WISE PERFORMANCE CHECK`
- `PART 4 — QUALITY EVALUATION FRAMEWORK`
- `PART 5 — IMPLEMENTATION PLAN`

### `PRODUCTION_PLAN.md`

- `Executive Summary`
- `Current Architecture (As-Is)`
- `Target Architecture (To-Be)`
- `Phase 1 — Schema-First Prompt Engine (Week 1)`
- `Phase 2 — Inline AI Suggestions in the Editor (Week 2)`
- `Phase 3 — Validation & Cross-Check Layer (Week 2-3)`
- `Phase 4 — Production Stack & Deployment (Week 3-4)`
- `Phase 5 — Mobile-First Experience (PWA) (Week 4)`
- `Phase 6 — Advanced Features (Week 5+)`
- `Implementation Priority & Timeline`

---

## 10) Scripts/tooling map (`scripts/`)

- `analyze_pdf.py` — 3-layer PDF analyzer (AcroForm, text, structure).
- `extract_bajaj_coords.py` — pdfplumber coordinate dump for Bajaj.
- `extract_heritage.py` — quick extraction for Heritage.
- `fix_bajaj_coords.py` — large targeted coordinate corrections for Bajaj schema.
- `fix_coords_batch.py` — batch tweak utility for Bajaj fields.
- `fix_heritage_coords.py` — targeted fixes for Heritage schema.
- `list_fields.py` — prints Ericson fields by page.
- `test_documentai.py` — Document AI config/auth/extraction/compare test.
- `test_fill.py` — template/schema/test_data fill tester.
- `verify_output.py` — compare overlay text against template.

---

## 11) Known risk areas (current)

- hardcoded fallback JWT secret in code path.
- hardcoded staff credentials in `app.py`.
- plaintext PHI session persistence.
- first-win merge without provenance weighting.
- fuzzy mapping threshold/alias collisions can mis-map costs/IDs.
- broad CORS in backend.

Use `FLAWS_AND_IMPLEMENTATION_PLAN.md` Section 1 for mitigation plans.

---

## 12) Fast orientation prompts for future sessions

- "Trace MRD lifecycle from phase 1 input to final filename."
- "Show all paths that can mutate `mapped_data` before generation."
- "Explain TPA detection fallback order and failure behavior."
- "List where cost fields are transformed to `ESTIMATE ATTACHED`."
- "Compare planned architecture vs current implementation drift."
