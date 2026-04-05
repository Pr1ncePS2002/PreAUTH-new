# FLAWS AND IMPLEMENTATION PLAN — TPA Pre-Authorization System

**Generated:** 2026-03-12 | **Last updated:** 2026-04-04  
**Scope:** Production flaws audit, edge-case analysis, mobile phone-scan implementation plan, schema-first prompts, AI suggestions, validation layer, on-premise deployment, architecture refactoring, advanced features  
**Codebase Snapshot:** app.py (~1410 lines), frontend/index.html (~1470 lines), frontend/mobile-upload.html (crop + rotate), 6 service modules, 3 analyzed schemas  
**Deployment target:** On-premise server (hospital IT team) — no cloud services (GCP/Cloud Run/Firestore/Cloud Storage are NOT used)

## SECTION INDEX

| Section | Topic | Priority |
|---------|-------|----------|
| Section 1 | Critical Production Flaws (Security, Data, Reliability, PDF, UX) | CRITICAL — fix before go-live |
| Section 2 | Edge Cases to Handle | HIGH |
| Section 3 | Mobile Phone Scan Implementation Plan | HIGH |
| Section 4 | Quick Win Fixes (< 2 hours each) | HIGH |
| Section 5 | Revised Implementation Timeline | Reference |
| Section 6 | Schema-First Prompt Engine | HIGH — +40% extraction accuracy |
| Section 7 | AI Suggestion Engine | HIGH — core UX differentiator |
| Section 8 | Validation & Cross-Check Layer | HIGH — catch errors before submission |
| Section 9 | On-Premise Production Deployment | CRITICAL — replaces all cloud deployment plans |
| Section 10 | Architecture Refactoring Debt | MEDIUM — maintainability |
| Section 11 | Advanced Features (post-stabilisation) | LOW |

---

**Recently implemented (as of 2026-04-02):**
- Mobile crop screen with 4-handle perspective corner selection + magnifier loupe (complete)
- Crop screen image rotation button (90° CW, fixes inverted captures) (complete)
- `POST /mobile/scan-upload` endpoint for base64 + corners delivery (complete)
- QR session flow with WebSocket live-sync to desktop (complete)

---

## SECTION 1 — CRITICAL PRODUCTION FLAWS (fix before go-live)

### 1.1 Security Flaws

#### F-001 — Hardcoded Staff Credentials
> **STATUS: BLOCKED** — No login system exists yet. Revisit when authentication is implemented.

| | |
|---|---|
| **Severity** | CRITICAL |
| **File + Line** | `app.py` lines 347–351 |
| **What is broken** | Three username/password pairs (`admin:admin123`, `reception:reception123`, `doctor:doctor123`) are committed in source code inside the `STAFF_USERS` dict. Any developer, auditor, or attacker with repo access can log in as any staff role. Credentials survive in Git history even if deleted later. |
| **Fix** | Move credentials to environment variables. Hash passwords with `bcrypt`. |

```python
# .env
STAFF_ADMIN_HASH=$2b$12$... (output of bcrypt.hashpw)
STAFF_RECEPTION_HASH=$2b$12$...

# app.py — replace STAFF_USERS block
import bcrypt

_STAFF_HASHES = {
    "admin": os.getenv("STAFF_ADMIN_HASH", ""),
    "reception": os.getenv("STAFF_RECEPTION_HASH", ""),
    "doctor": os.getenv("STAFF_DOCTOR_HASH", ""),
}

def _verify_password(username: str, password: str) -> bool:
    stored = _STAFF_HASHES.get(username)
    if not stored:
        return False
    return bcrypt.checkpw(password.encode(), stored.encode())
```

---

#### F-002 — JWT Secret is a Hardcoded Default
> **STATUS: BLOCKED** — No login system exists yet. Revisit alongside F-001 when authentication is implemented.

| | |
|---|---|
| **Severity** | CRITICAL |
| **File + Line** | `app.py` line 65 |
| **What is broken** | `JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")`. If `.env` does not set `JWT_SECRET`, every token is signed with a publicly known string. An attacker can forge valid JWTs for any staff user. |
| **Fix** | Fail fast at startup if `JWT_SECRET` is missing or is the default value. |

```python
JWT_SECRET = os.getenv("JWT_SECRET", "")
if not JWT_SECRET or JWT_SECRET == "dev-secret-change-in-production":
    raise RuntimeError(
        "FATAL: JWT_SECRET must be set to a random 256-bit value in .env. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
```

---

#### F-003 — Session Files Contain PHI Stored as Plain-Text JSON
> **STATUS: FIXED** — Fernet encryption applied in `_save_session` / `_load_session`. Key stored in `.env` as `SESSION_ENCRYPTION_KEY`. `cryptography` added to `requirements.txt`.

| | |
|---|---|
| **Severity** | CRITICAL |
| **File + Line** | `app.py` lines 170–174 (`_save_session`) |
| **What is broken** | Session JSON files written to `sessions/` contain patient names, Aadhaar numbers, DOB, policy numbers, clinical diagnosis — all in clear text. Any OS-level file access (another process, backup agent, misconfigured SMB share) exposes PHI. Violates DPDP Act 2023 Section 8 (obligation to protect personal data). |
| **Fix** | Encrypt session files at rest using Fernet symmetric encryption. Key read from the environment. |

```python
from cryptography.fernet import Fernet

SESSION_KEY = os.getenv("SESSION_ENCRYPTION_KEY", "")
if not SESSION_KEY:
    raise RuntimeError("SESSION_ENCRYPTION_KEY must be set (use Fernet.generate_key())")
_fernet = Fernet(SESSION_KEY.encode())

def _save_session(session_id: str):
    if session_id in _sessions:
        path = SESSIONS_DIR / f"{session_id}.enc"
        payload = json.dumps(_sessions[session_id]).encode()
        path.write_bytes(_fernet.encrypt(payload))

def _load_session(session_id: str) -> dict | None:
    if session_id in _sessions:
        return _sessions[session_id]
    path = SESSIONS_DIR / f"{session_id}.enc"
    if path.exists():
        data = json.loads(_fernet.decrypt(path.read_bytes()))
        _sessions[session_id] = data
        return data
    return None
```

---

#### F-004 — MRD Number Used Unsanitised in File Paths
> **STATUS: FIXED** — `sanitize_mrd()` added to `app.py`. Applied at all 4 input boundaries: `upload_document`, `workflow_start`, `workflow_update_mrd`, `mobile_qr_create`.

| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `app.py` lines 1159–1166 (MRD used in `claim_package_MRD_{mrd_number}.pdf`) |
| **What is broken** | `mrd_number` comes from user form input and is interpolated directly into a filename. A crafted MRD like `../../etc/passwd` or `..\..\windows\system32\config` causes path traversal. On Windows, characters like `<>:"/\|?*` in filenames crash `PdfWriter.write()`. |
| **Fix** | Sanitise MRD at input boundary — strip everything non-alphanumeric, enforce max length. |

```python
import re

def sanitize_mrd(mrd: str) -> str:
    """Strip to alphanumeric + hyphen, max 20 chars."""
    cleaned = re.sub(r'[^a-zA-Z0-9\-]', '', mrd.strip())
    return cleaned[:20]

# Apply at every entry point: workflow_start, workflow_update_mrd
mrd_number = sanitize_mrd(mrd_number)
```

---

#### F-005 — No HTTPS Enforcement
| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `app.py` lines 142–149 (CORS middleware) |
| **What is broken** | The app runs on plain HTTP. JWT tokens, patient PHI, and Aadhaar numbers are transmitted in cleartext over hospital WiFi. Any device on the same network can sniff the traffic with Wireshark. The CORS `allow_origins=["*"]` compounds this — any origin can call API endpoints. |
| **Fix** | In production, deploy behind a reverse proxy (Nginx/Caddy) with TLS termination. Add HTTPS redirect middleware. Restrict CORS origins. |

```python
# Production CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://preauth.amritahospital.in").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# HTTPS redirect middleware (add before CORS)
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
if os.getenv("ENFORCE_HTTPS", "false").lower() == "true":
    app.add_middleware(HTTPSRedirectMiddleware)
```

---

#### F-006 — File Upload Has No MIME Validation, No Size Limit, No Malware Hook
| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `app.py` lines 465–480 (`upload_document`), lines 774–795 (`workflow_start` file save loop) |
| **What is broken** | Any file of any size with any extension is accepted and written to disk. An attacker can upload a 2 GB file to exhaust disk, upload a `.exe` disguised as `.pdf`, or upload a zip bomb. There is no check on `content_type` or magic bytes. |
| **Fix** | Validate MIME type via magic bytes (python-magic), enforce max 8 MB per file, whitelist extensions. |

```python
import magic  # python-magic-bin on Windows

ALLOWED_MIME_TYPES = {
    "application/pdf", "image/jpeg", "image/png", "image/tiff",
    "image/heic", "image/heif", "image/webp",
}
MAX_FILE_SIZE = 8 * 1024 * 1024  # 8 MB

async def _validate_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large ({len(content)} bytes). Max {MAX_FILE_SIZE}.")
    mime = magic.from_buffer(content[:2048], mime=True)
    if mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"Unsupported file type: {mime}")
    await file.seek(0)
    return content
```

---

### 1.2 Data Integrity Flaws

#### F-007 — First-Win KV Merge Discards Better Data
| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `app.py` lines 811–813 (merge loop inside `workflow_start`) |
| **What is broken** | `for k, v in result.items(): if k not in all_extracted: all_extracted[k] = v`. If the Aadhaar scan returns `"Name": "R K SHARMA"` (truncated) and the policy card returns `"Name": "RAJESH KUMAR SHARMA"` (full name), the truncated version wins because Aadhaar was processed first. This silently degrades data quality for every multi-document session. |
| **Fix** | Replace first-win with confidence-weighted merge. Track per-key source. See Section 3.4, step M-014. |

---

#### F-008 — No Source Tracking After Merge
| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `app.py` lines 800–815 (merge into `all_extracted`) |
| **What is broken** | After merge, it is impossible to know which document produced which key-value pair. When a staff member questions a pre-filled value ("Where did this diagnosis come from?"), there is no answer. DPDP Act requires audit-trail for PHI processing. |
| **Fix** | Store merge provenance. Each key in `all_extracted` becomes `{value, source_file, confidence}`. See Section 3.4, step M-015. |

---

#### F-009 — Fuzzy Threshold 70 Produces False Matches
| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `services/mapping_engine.py` line 37 (`FUZZY_THRESHOLD = 70`) |
| **What is broken** | `rapidfuzz.token_sort_ratio("ot charges", "icu charges")` returns ~73 — above threshold. OCR key "OT Charges" gets mapped to `icu_charges` field_id if the correct `ot_charges` field_id was already claimed. Similarly, "Room Rent" (77 score) can match "Room Type". These silent mis-mappings put wrong costs on TPA forms — a compliance and financial risk. |
| **Fix** | Raise threshold to 80. Add a known-confusion blocklist. |

```python
FUZZY_THRESHOLD = 80

# Pairs that frequently false-match — never allow fuzzy between these
FUZZY_BLOCKLIST = {
    ("ot charges", "icu charges"),
    ("room rent", "room type"),
    ("date of admission", "date of discharge"),
    ("patient name", "doctor name"),
    ("mobile number", "policy number"),
}

def _fuzzy_match(self, normalised_key, valid_fields):
    result = process.extractOne(normalised_key, list(candidates.keys()),
                                scorer=fuzz.token_sort_ratio, score_cutoff=FUZZY_THRESHOLD)
    if result:
        matched_alias, score, _ = result
        field_id = candidates[matched_alias]
        if (normalised_key, matched_alias) in FUZZY_BLOCKLIST or \
           (matched_alias, normalised_key) in FUZZY_BLOCKLIST:
            return None
        return field_id
    return None
```

---

#### F-010 — Alias Collisions Without Schema-Context Disambiguation
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `config/field_mapping.json` (multiple entries), `services/mapping_engine.py` lines 81–95 (`_build_alias_index`) |
| **What is broken** | Several common OCR keys map to multiple field_ids: |

| Alias | Colliding field_ids |
|-------|-------------------|
| `"Date of Birth"` | `date_of_birth`, `patient_dob`, `dob` |
| `"Contact Number"` | `patient_contact_no`, `doctor_contact_no` |
| `"Policy Number"` | `tpa_card_number`, `policy_number_corporate_name` |
| `"Hospital Name"` | `hospital_name`, `provider_hospital_name` |

The alias index stores `[field_id_1, field_id_2, ...]` and picks the first one found in `valid_fields`. If schema field order changes, a different field_id gets selected. **Fix:** Add `document_type` context to disambiguation — "Contact Number" from `policy_card` → `patient_contact_no`; from `clinical_notes` → `doctor_contact_no`.

---

#### F-011 — Age Calculation Writes to All Schema Variants Without DOB Format Validation
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `app.py` lines 235–256 (`calculate_age_from_dob`) |
| **What is broken** | `dateparser.parse(dob_str, dayfirst=True)` accepts almost any string. A DOB of `"15"` (just a day, no month/year) parses to the 15th of the current month of the current year, producing age = 0. The function then sets `patient_age_years = "0"` across all schema variants. No validation that the parsed date is in the past or is a plausible human DOB (1900–2025). |
| **Fix** | Validate parsed DOB is a realistic date before writing age fields. |

```python
dob = dateparser.parse(dob_str, dayfirst=True)
if dob is None:
    return mapped_data
if dob.year < 1900 or dob > datetime.utcnow():
    logger.warning("DOB '%s' parsed to implausible date %s — skipping age calc", dob_str, dob)
    return mapped_data
```

---

#### F-012 — Gender Normalisation Duplicated in Two Places
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `services/mapping_engine.py` lines 421–457 (`handle_gender`), `services/form_engine.py` lines 257–266 (`_handle_gender`) |
| **What is broken** | Two independent gender-to-checkbox converters exist. `MappingEngine.handle_gender()` sets `gender_male`, `gender_female`, `patient_gender_male`, `patient_gender_female`, `gender_third_gender`. `FormEngine._handle_gender()` sets `gender_male`, `gender_female`, `gender_third_gender` — but NOT the `patient_gender_*` variants. If `FormEngine._handle_gender()` runs after `MappingEngine.handle_gender()`, it `pop()`s the `"gender"` key and re-applies a subset, potentially losing the Bajaj-style fields. |
| **Fix** | Remove `FormEngine._handle_gender()`. Let `MappingEngine.handle_gender()` be the single source of truth. Ensure it runs exactly once before `form_engine.populate()`. |

---

### 1.3 Reliability / Error Handling Flaws

#### F-013 — No Retry Logic on Gemini API Calls
| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `services/extractors/gemini_extractor.py` lines 224–237 (API call block) |
| **What is broken** | A single `client.models.generate_content()` call is made with no retry. Gemini returns HTTP 503 (overloaded) approximately 2–5% of the time during peak hours. When this happens, the exception propagates to `OCRService.extract()` which catches it and returns `{}`. The staff sees zero extracted fields for that document with no explanation. |
| **Fix** | Add exponential backoff retry with `tenacity`. |

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_gemini(self, client, genai, types, prompt, file_bytes, mime_type):
    response = client.models.generate_content(
        model=self.model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                    types.Part.from_text(text=prompt),
                ],
            )
        ],
    )
    return response
```

---

#### F-014 — No Rate Limiting on `/workflow/start`
| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `app.py` lines 761–768 (endpoint definition) |
| **What is broken** | Each call to `/workflow/start` fires parallel Gemini API calls (one per uploaded file). A staff member clicking "Extract Data" repeatedly — or a script hitting the endpoint — can exhaust the Gemini API quota in minutes. Google will throttle or bill aggressively. There is no per-IP or per-session rate limit. |
| **Fix** | Add rate limiting with `slowapi`. |

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/workflow/start")
@limiter.limit("10/hour")
async def workflow_start(request: Request, ...):
    ...
```

---

#### F-015 — JSON Parse Failure Returns Empty Dict Silently
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `services/extractors/gemini_extractor.py` lines 299–305 (`_parse_json_response`) |
| **What is broken** | When Gemini returns malformed JSON (happens with complex handwritten docs), `json.JSONDecodeError` is caught and an empty `{}` is returned. No user-facing error. The staff sees 0 fields extracted and assumes OCR failed entirely, with no prompt to retake. The error is only logged server-side at DEBUG level. |
| **Fix** | Propagate a structured error to the caller. Set `ExtractedDocument.error` to the parse failure message so the frontend can display "OCR returned unparseable output — please retake photo". |

---

#### F-016 — TPA Detection Relies 100% on OCR Accuracy
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `app.py` lines 721–740 (`detect_tpa_template`), lines 824–828 (used in `workflow_start`) |
| **What is broken** | If Gemini misreads the insurance company name (e.g., "HDFC Ergo" → "HOFC Ergo"), `detect_tpa_template()` either selects the wrong template or returns `None`. The fuzzy fallback threshold of 60 is too low — "HOFC Ergo" scores ~75 against "hdfc ergo" (correct) but also ~62 against "fhpl" (wrong). Wrong template → all field coordinates are wrong → garbled PDF. |
| **Fix** | Raise fuzzy threshold to 75. Add a confirmation step: show the detected TPA to the staff in Phase 1 UI with option to override. (Already partially exists in TPA selector dropdown.) |

---

#### F-017 — Session Files Grow Unbounded
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `app.py` lines 80–104 (`_purge_old_phi`) |
| **What is broken** | The PHI cleanup scheduler runs in a daemon thread that calls `threading.Event().wait(interval_hours * 3600)` BEFORE the first purge — meaning the first scheduled purge runs 6 hours after startup. The startup purge runs once, but if the server runs for days without restart, sessions from hours 1–6 remain on disk. Additionally, the purge only deletes files by mtime — it does not clean up the in-memory `_sessions` dict, which leaks memory. |
| **Fix** | Run purge immediately AND periodically. Also evict from in-memory dict. |

```python
def _purge_old_phi() -> None:
    cutoff = datetime.utcnow() - timedelta(hours=DATA_RETENTION_HOURS)
    # ... existing file deletion ...
    # Also evict from in-memory dict
    stale = [sid for sid, s in _sessions.items()
             if datetime.fromisoformat(s.get("created", "2000-01-01")) < cutoff]
    for sid in stale:
        del _sessions[sid]
    if stale:
        logger.info("Evicted %d stale sessions from memory", len(stale))
```

---

#### F-018 — PDF Merge Does Not Validate Attachments Before Merging
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `services/pdf/merge_claim_documents.py` lines 57–80 (merge loop) |
| **What is broken** | `PdfReader(attachment_path)` is called without try/except per attachment. If one uploaded attachment is a corrupted PDF or a renamed `.docx`, the entire merge crashes with `PdfReadError`, and the staff gets a 500 error with no claim package generated — even though the TPA form itself was fine. |
| **Fix** | Wrap each attachment read in try/except. Skip corrupted files. Log a warning. |

```python
for att_path in attachments:
    try:
        if Path(att_path).suffix.lower() in IMAGE_EXTENSIONS:
            pdf_bytes = _image_to_pdf_bytes(att_path)
            reader = PdfReader(io.BytesIO(pdf_bytes))
        else:
            reader = PdfReader(att_path)
        for page in reader.pages:
            writer.add_page(page)
    except Exception as e:
        logger.warning("Skipping corrupt attachment '%s': %s", att_path, e)
```

---

### 1.4 PDF Generation Flaws

#### F-019 — No Text Wrapping — Long Values Overflow Fields
| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `services/form_engine.py` lines 227–236 (`_draw_text`) |
| **What is broken** | `can.drawString(x, y, str(value))` draws a single line of text starting at `(x, y)`. If `value` is "LAPAROSCOPIC CHOLECYSTECTOMY WITH COMMON BILE DUCT EXPLORATION" (56 chars), the text extends past the right edge of the field box and overlaps adjacent fields or runs off the page. This happens frequently for diagnosis, procedure name, and address fields. |
| **Fix** | Measure text width. If it exceeds field width, reduce font size or wrap into multiple lines. |

```python
def _draw_text(self, can, field, value, page_height):
    x = field["coordinates"]["x"]
    y = page_height - field["coordinates"]["y"]
    font_size = field.get("font_size", 10)
    max_width = field.get("width", 200)
    text = str(value)

    if text.strip().upper() == "ESTIMATE ATTACHED":
        can.setFont("Helvetica-Bold", max(font_size, 11))
    else:
        can.setFont("Helvetica", font_size)

    # Auto-shrink font if text overflows
    text_width = can.stringWidth(text, can._fontname, font_size)
    while text_width > max_width and font_size > 5:
        font_size -= 0.5
        can.setFont(can._fontname, font_size)
        text_width = can.stringWidth(text, can._fontname, font_size)

    can.drawString(x, y, text)
```

---

#### F-020 — No Unicode / Devanagari Support
| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `services/form_engine.py` lines 205–206 (`can.setFont("Helvetica", 10)`) |
| **What is broken** | Helvetica cannot render Devanagari, Gurmukhi, or Bengali glyphs. Patient names like "राजेश कुमार" or addresses from Aadhaar in Hindi are silently dropped — ReportLab substitutes missing glyphs with empty space. The PDF field appears blank. |
| **Fix** | Register a Unicode-capable font (e.g., Noto Sans Devanagari). Fall back to Helvetica for Latin-only text. |

```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register at module level
NOTO_FONT_PATH = BASE_DIR / "fonts" / "NotoSansDevanagari-Regular.ttf"
if NOTO_FONT_PATH.exists():
    pdfmetrics.registerFont(TTFont("NotoSans", str(NOTO_FONT_PATH)))

def _choose_font(self, text: str) -> str:
    # If text contains non-ASCII, use Noto Sans; otherwise Helvetica
    if any(ord(c) > 127 for c in str(text)):
        return "NotoSans"
    return "Helvetica"
```

---

#### F-021 — Y-Coordinate Mismatch Between Schema and Template
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `services/form_engine.py` lines 179–181 (`_get_page_height`), line 230 (`y = page_height - field["coordinates"]["y"]`) |
| **What is broken** | `_get_page_height()` reads from `schema["page_heights"]` with a fallback of 842 (A4). If the actual template PDF has a MediaBox height of 792 (US Letter) or 756 (custom), there is a 50–86 point vertical offset. Every field shifts up or down by ~18–30mm. Fields land on wrong lines. |
| **Fix** | Read the actual page height from the template PDF's MediaBox at render time. |

```python
def _fill_pdf(self, template_path, schema, data, output_path):
    template = PdfReader(str(template_path))
    output = PdfWriter()
    for page_num in range(len(template.pages)):
        page = template.pages[page_num]
        # Use actual template page height, not schema assumption
        media_box = page.mediabox
        actual_height = float(media_box.height)
        ...
```

---

#### F-022 — "ESTIMATE ATTACHED" Written to Wrong Field If Schema Order Changes
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `services/form_engine.py` lines 232–234 (check for "ESTIMATE ATTACHED") |
| **What is broken** | The "ESTIMATE ATTACHED" bold styling is applied based on string matching (`value.strip().upper() == "ESTIMATE ATTACHED"`). The issue is upstream: `app.py` puts this text into the first cost line-item field it encounters. If the schema `fields` array is reordered (e.g., during re-analysis), the label ends up in "ICU Charges" instead of "Room Rent (per day)". |
| **Fix** | Use an explicit "ESTIMATE ATTACHED" target field_id per schema. Add a `cost_estimate_label_field` to each schema JSON, or always target the first cost field by a well-defined sort (page then y-coordinate). |

---

### 1.5 Frontend / UX Flaws

#### F-023 — No Required-Field Validation Before PDF Generation
| | |
|---|---|
| **Severity** | HIGH |
| **File + Line** | `frontend/index.html` — the Generate PDF tab |
| **What is broken** | Staff can click "Generate Final PDF" with `patient_name`, `policy_number`, `date_of_admission` all blank. The backend generates a mostly-empty PDF that will be rejected by the TPA, wasting a claims cycle. There is no client-side check for required fields. |
| **Fix** | Define a `REQUIRED_FIELDS` set per schema. Block generation and show a list of missing fields. |

```javascript
const REQUIRED_FIELDS = [
    'patient_name', 'date_of_birth', 'policy_number',
    'date_of_admission', 'nature_of_illness_complaint',
    'sum_total_expected_cost_of_hospitalization'
];

function validateBeforeGenerate() {
    const missing = REQUIRED_FIELDS.filter(f => {
        const el = document.querySelector(`[data-field-id="${f}"]`);
        return !el || !el.value.trim();
    });
    if (missing.length > 0) {
        alert(`Missing required fields:\n${missing.map(f => f.replace(/_/g, ' ')).join('\n')}`);
        return false;
    }
    return true;
}
```

---

#### F-024 — No Session Timeout Warning
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `frontend/index.html` — JavaScript state management, `app.py` line 66 (`JWT_EXPIRY_HOURS = 8`) |
| **What is broken** | JWT expires after 8 hours with no client-side countdown. If a staff member spends 30 minutes editing fields and the token expires mid-session, the next API call returns 401 and unsaved edits are lost silently. |
| **Fix** | Store token expiry in localStorage. Show a warning banner 15 minutes before expiry. Offer re-login without losing form state. |

---

#### F-025 — No Per-Document Loading Indicator During Parallel OCR
| | |
|---|---|
| **Severity** | MEDIUM |
| **File + Line** | `frontend/index.html` — upload/extract flow JS |
| **What is broken** | During OCR, a single global loading overlay appears ("Extracting data from your documents…"). Staff cannot tell which of 5 uploaded documents is done and which is still processing. If one document takes 30 seconds (complex clinical notes), the staff thinks the system is frozen. |
| **Fix** | Return a streaming response or poll per-document status. Simpler: after `/workflow/start` returns, show per-document extraction results (field count or error) inline on each upload card. |

---

#### F-026 — GIPSA Auto-Detection Not Surfaced Prominently
| | |
|---|---|
| **Severity** | LOW |
| **File + Line** | `app.py` lines 305–312 (`GIPSA_TPA_LIST`), `frontend/index.html` — GIPSA toggle |
| **What is broken** | The backend has a 26-entry GIPSA TPA list, but the frontend requires manual GIPSA toggle. Auto-detection fires server-side but the result is buried in `tpa_detection` — the GIPSA toggle on the Insurance & TPA tab is not auto-set from this detection. Staff can forget to enable it, skipping the PPN declaration. |
| **Fix** | When `tpa_detection` returns an insurance company that matches `GIPSA_TPA_LIST`, auto-set the GIPSA radio to "Yes" and show a visible badge: "GIPSA case detected — PPN will be generated." |

---

## SECTION 2 — EDGE CASES TO HANDLE

### 2.1 Phone Camera / Image Quality Edge Cases

#### EC-001 — Photo Taken at an Angle (Keystone Distortion)
| | |
|---|---|
| **Trigger** | Staff holds phone at 30°+ angle to a document on a desk |
| **Current behaviour** | Gemini receives a skewed image. Fields near the edges are truncated or misread. Partial JSON returned. |
| **Required behaviour** | Detect low field-fill and prompt retake. Gemini handles moderate skew well (< 15°), so the main fix is user guidance + quality feedback. |
| **Implementation note** | Add a capture overlay guide ("Align document within frame") using CSS. Server-side: if field fill rate < 50% for the document type, flag quality issue in response. |

---

#### EC-002 — Photo in Low Light
| | |
|---|---|
| **Trigger** | Staff photographs a document in a dimly lit ward or corridor |
| **Current behaviour** | Gemini returns partial/empty JSON. `OCRService.extract()` returns `{}`. Zero fields shown. |
| **Required behaviour** | Show "Low quality scan" warning with confidence badge. Prompt retake with message "Try again with better lighting." |
| **Implementation note** | Use the fill-rate confidence score (Section 3.3). If < 30% fill, show a red badge + retake prompt. Client-side: use `imagecapture` API `getPhotoSettings()` to check if torch is available and suggest flash. |

---

#### EC-003 — EXIF Orientation Causes Rotated Image
| | |
|---|---|
| **Trigger** | iPhone/Android camera encodes rotation in EXIF tag 0x0112 instead of rotating pixels. Backend receives a visually-rotated image. |
| **Current behaviour** | Gemini processes the image as-is. If rotated 90°, OCR reads columns as rows, producing garbled key-value pairs. |
| **Required behaviour** | Image arrives at Gemini with correct pixel orientation regardless of EXIF metadata. |
| **Partially addressed** | The crop screen now has a **Rotate button** (90° CW per tap) so staff can manually fix obviously inverted/sideways photos before sending. This handles visible orientation errors but does NOT auto-correct EXIF-silent rotation (where the photo appears correct on the phone screen but arrives rotated at the server). |
| **Remaining fix needed** | Client-side: use `createImageBitmap()` (auto-applies EXIF on Chrome 80+/Safari 13.4+) when drawing to the pre-crop canvas. Server-side safety net: `Pillow.ImageOps.exif_transpose()` after save. See Section 3.2, steps M-005 and M-009. |

---

#### EC-004 — iPhone HEIC Format Upload
| | |
|---|---|
| **Trigger** | iPhone with "High Efficiency" photo setting uploads .heic file |
| **Current behaviour** | Backend receives a file with MIME type `image/heic`. `mimetypes.guess_type()` returns `None`. Gemini API may reject it (not in supported MIME list). Upload likely fails silently or Gemini returns empty response. |
| **Required behaviour** | HEIC is converted to JPEG before OCR. User sees no difference. |
| **Implementation note** | Client-side: detect `.heic` extension, convert using `heic2any` JS library (CDN). Server-side fallback: use `pillow-heif` to convert HEIC → JPEG. |

---

#### EC-005 — Large Camera Photo (5–12 MB)
| | |
|---|---|
| **Trigger** | Modern phone camera produces 4032×3024 JPEG at 5–12 MB. Hospital WiFi bandwidth is often 2–5 Mbps shared. |
| **Current behaviour** | Upload stalls. `/workflow/start` has no timeout; the request blocks until all bytes arrive. Staff perceives hang. |
| **Required behaviour** | Image is compressed to < 1 MB client-side before upload. Upload completes in < 3 seconds on 2 Mbps. |
| **Implementation note** | Client-side Canvas resize to max 1200px longest edge, JPEG quality 0.82. See Section 3.2, step M-007. |

---

#### EC-006 — Wrong Document Uploaded in Wrong Category
| | |
|---|---|
| **Trigger** | Staff accidentally uploads clinical notes as "Policy Card", or vice versa |
| **Current behaviour** | OCR runs with the wrong `document_type` prompt. Gemini receives mismatched extraction hints. Extracted keys are wrong for the target category. Mapping engine maps them to incorrect schema fields. Staff does not know unless they check every field. |
| **Required behaviour** | Document classification validation: after OCR, check if extracted keys match expected keys for the declared `document_type`. If mismatch > 50%, show a warning: "This document looks like clinical_notes but was uploaded as policy_card. Switch?" |
| **Implementation note** | Compare extracted key set against `DOCUMENT_TYPES[doc_type]["expected_fields"]`. Compute Jaccard similarity. Below 0.3 → flag mismatch. |

---

#### EC-007 — Multi-Page Document Photographed as Separate Images
| | |
|---|---|
| **Trigger** | Staff photographs page 1, page 2, page 3 of a discharge summary as three separate uploads |
| **Current behaviour** | Each page is OCR'd independently. Diagnosis on page 1, treatment on page 2, signature on page 3. Cross-page context is lost. Duplicate keys from different pages may conflict in KV merge. |
| **Required behaviour** | Staff can mark multiple images as belonging to the same document. OCR merges them into a single context before extraction. |
| **Implementation note** | Add a "multi-page" mode in the upload UI: "Add another page to this document". Concatenate pages into a single multi-part Gemini request or a combined PDF before extraction. |

---

#### EC-008 — Glare on Laminated Documents
| | |
|---|---|
| **Trigger** | Aadhaar card and insurance policy card are laminated. Flash or ambient light creates a bright glare spot obscuring text. |
| **Current behaviour** | Gemini returns partial data. Fields under glare are missing. No warning to staff. |
| **Required behaviour** | Low fill-rate triggers a retake prompt with specific guidance: "Glare detected — try photographing at an angle without flash." |
| **Implementation note** | Handled by the confidence feedback loop (Section 3.3). If `Name` or `Aadhaar Number` missing from an Aadhaar scan, flag as incomplete. |

---

### 2.2 Data / Field Edge Cases

#### EC-009 — MRD Number With Special Characters
| | |
|---|---|
| **Trigger** | Staff enters MRD like `AMR/2024/001234` or `MRD 5678 (old)` |
| **Current behaviour** | MRD is used directly in filename: `claim_package_MRD_AMR/2024/001234.pdf` — crashes on Windows (`/` is a path separator). Session filename `sessions/AMR/2024/001234.json` creates nested directories. |
| **Required behaviour** | MRD is sanitised to alphanumeric characters only. Original value kept for display, sanitised value used for filenames. |
| **Implementation note** | Apply `sanitize_mrd()` from F-004 fix. Store both `mrd_number` (display) and `mrd_number_safe` (filesystem). |

---

#### EC-010 — Date of Birth in Multiple Formats
| | |
|---|---|
| **Trigger** | Aadhaar shows `15/03/1979`, policy card shows `1979-03-15`, clinical notes say `15 Mar 1979` |
| **Current behaviour** | `dateutil.parser.parse(dayfirst=True)` handles most formats. But `03/06/1990` is ambiguous: dayfirst=True → June 3, but American format means March 6. If policy card uses MM/DD/YYYY and Aadhaar uses DD/MM/YYYY, the first-win merge picks one at random. |
| **Required behaviour** | Normalise all dates to DD/MM/YYYY at extraction time. For ambiguous dates, prefer dayfirst (Indian standard). Staff can verify/correct in the form. |
| **Implementation note** | Add a `_normalise_date(raw: str) -> str` helper that parses with `dayfirst=True` and outputs `DD/MM/YYYY`. Apply to all date fields post-extraction. |

---

#### EC-011 — Policy Number With Slashes
| | |
|---|---|
| **Trigger** | Policy number like `POL/2024/001234` or `SHI-HDF/24-25/123456` |
| **Current behaviour** | The value is stored and rendered correctly in the PDF. No actual bug in current code path — slashes are not used in routing or filenames for policy numbers. However, if policy number is ever used in a URL path segment or filename, breakage will occur. |
| **Required behaviour** | Policy number is treated as opaque string, never used in URL paths or filenames. |
| **Implementation note** | No code change needed currently, but add a defensive note: never use `policy_number` in filesystem paths or URL path segments. URL-encode if included in query parameters. |

---

#### EC-012 — Cost Total With Indian Currency Formatting
| | |
|---|---|
| **Trigger** | Estimate document shows "₹ 1,25,000" or "Rs. 2,50,000/-" |
| **Current behaviour** | The value is stored as the string `"₹ 1,25,000"`. If any downstream code tries `float(value)`, it throws `ValueError`. The PDF renders the full string, which is fine for display but wrong if sum calculations are needed. |
| **Required behaviour** | Strip currency symbols, commas, and trailing `/-`. Store as plain integer string: `"125000"`. |
| **Implementation note** | Add a cost-field normaliser. |

```python
import re

def normalise_cost(raw: str) -> str:
    """Strip ₹, Rs., commas, /-. Return plain integer string."""
    cleaned = re.sub(r'[₹Rs.\s,/\-]', '', str(raw).strip())
    cleaned = cleaned.strip('.')
    if cleaned.isdigit():
        return cleaned
    return str(raw)  # Return original if not parseable
```

---

#### EC-013 — Same MRD Re-Uploaded in Same Session
| | |
|---|---|
| **Trigger** | Staff starts a workflow, uploads docs, then clicks "Extract Data" again for the same MRD (perhaps they forgot to add a document) |
| **Current behaviour** | A new `session_id` is created. The old session remains on disk with stale data. If the staff switches between browser tabs, they may end up working with the old stale session. |
| **Required behaviour** | Detect existing session for the same MRD. Offer to resume or start fresh. |
| **Implementation note** | Before creating a new session in `/workflow/start`, check `_sessions` for an existing session with the same `mrd_number` and `status != "generated"`. If found, return a `409 Conflict` with the existing `session_id` and let the frontend ask: "Resume existing session or start new?" |

---

#### EC-014 — Aadhaar Number Partially Masked
| | |
|---|---|
| **Trigger** | Government-issued masked Aadhaar copies show `XXXX-XXXX-1234` (only last 4 digits visible) |
| **Current behaviour** | OCR extracts `"XXXX XXXX 1234"` and stores it as the Aadhaar number. This masked value gets written to the TPA form. |
| **Required behaviour** | Detect masked Aadhaar (contains X). Show a warning: "Aadhaar is masked — TPA may require full number." Let staff manually enter full number or proceed with masked value. |
| **Implementation note** | Post-extraction check: `if "X" in aadhaar_value.upper() or len(digits_only) < 12: flag_warning("masked_aadhaar")`. |

---

#### EC-015 — GIPSA False Positive From Partial Name Match
| | |
|---|---|
| **Trigger** | Insurance company is "Heritage Pharma Insurance" (not a TPA). `GIPSA_TPA_LIST` contains `"heritage health"`. Substring match logic: `"heritage" in "heritage pharma insurance"` → True. |
| **Current behaviour** | GIPSA is falsely detected. PPN Declaration is generated with irrelevant data. |
| **Required behaviour** | GIPSA match requires full TPA name match, not substring. |
| **Implementation note** | Use exact match against the full set entry, not substring containment. |

```python
def is_gipsa_case(insurance_name: str) -> bool:
    name_lower = insurance_name.lower().strip()
    # Exact match first
    if name_lower in GIPSA_TPA_LIST:
        return True
    # Token-overlap match (all tokens of a GIPSA entry must appear)
    for gipsa_name in GIPSA_TPA_LIST:
        gipsa_tokens = set(gipsa_name.split())
        input_tokens = set(name_lower.split())
        if gipsa_tokens.issubset(input_tokens):
            return True
    return False
```

---

### 2.3 TPA / PDF Generation Edge Cases

#### EC-016 — Schema JSON Missing or Corrupted
| | |
|---|---|
| **Trigger** | A new TPA template was added to `templates/` but never analyzed. `analyzed/NewTPA.json` does not exist. Or the JSON was hand-edited and has a syntax error. |
| **Current behaviour** | `form_engine.populate()` raises `FileNotFoundError` or `json.JSONDecodeError`. Returns a 500 to the frontend. |
| **Required behaviour** | Clear user-facing error: "Schema for [TPA name] has not been analyzed. Please run analysis first or select a different form." |
| **Implementation note** | Already handled by `app.py` line 1143 (`if not schema_path.exists(): err(…, 404)`). Add a JSON parse try/except around `json.load(f)` in `form_engine.populate()` to catch corruption. |

---

#### EC-017 — PDF Template Missing
| | |
|---|---|
| **Trigger** | Schema exists in `analyzed/` but the corresponding PDF was deleted from `templates/` |
| **Current behaviour** | `form_engine.populate()` raises `FileNotFoundError`. 500 error. |
| **Required behaviour** | Pre-check at schema list time: mark schemas without templates as unavailable. Block selection in frontend. |
| **Implementation note** | `list_schemas()` already returns `has_template: bool`. Frontend should disable selection for schemas where `has_template == false`. |

---

#### EC-018 — Sum Total Field ID Differs Across Schemas
| | |
|---|---|
| **Trigger** | Session starts with Bajaj schema (`cost_total_expected_hospitalization`), staff switches to Ericson (`sum_total_expected_cost_of_hospitalization`). |
| **Current behaviour** | `mapped_data` still has the Bajaj field_id key. The Ericson schema does not have that field_id, so total is not rendered. |
| **Required behaviour** | Re-mapping via `/workflow/{session_id}/remap` should translate field_ids. |
| **Implementation note** | The `remap` endpoint already re-runs mapping from `raw_ocr_merged`. Ensure the cost total aliases in `field_mapping.json` cover all three schema variants. Verify: `sum_total_expected_cost_of_hospitalization`, `cost_total_expected_hospitalization`, and `sum_total_expected_cost_hospitalization` must all be aliases of each other. |

---

#### EC-019 — PPN Declaration With Empty Data
| | |
|---|---|
| **Trigger** | All OCR calls failed (Gemini down). `raw_ocr_merged` is `{}`. GIPSA toggle is on. |
| **Current behaviour** | `generate_ppn_pdf({})` runs. Only hardcoded fields are filled (hospital name, address). A nearly-blank PPN declaration is merged into the claim package. |
| **Required behaviour** | Warn staff: "PPN Declaration has insufficient data. At minimum, patient name and policy number are required." Block PPN generation if critical fields are empty. |
| **Implementation note** | In `generate_ppn_pdf()`, after `_build_ppn_data()`, check that `ppn_patient_name` and `ppn_policy_number` are non-empty. If not, raise a clear exception that the caller surfaces to the frontend. |

---

#### EC-020 — Merged Claim Package Exceeds 10 MB
| | |
|---|---|
| **Trigger** | 5 high-resolution photo attachments + multi-page TPA form + PPN → 12 MB merged PDF |
| **Current behaviour** | PDF is generated successfully but may fail when uploaded to TPA portals (many cap at 5–10 MB) or emailed (25 MB limit). |
| **Required behaviour** | After merge, check file size. If > 5 MB, compress images in the PDF. Warn staff if final size > 10 MB. |
| **Implementation note** | Use `PIL.Image.open().resize()` to cap attachment images at 1200px longest edge before conversion to PDF. After merge, check `Path(output_path).stat().st_size`. |

---

#### EC-021 — Crop Corner Coordinates Not Validated Against Image Bounds
| | |
|---|---|
| **Trigger** | A browser bug or malicious client sends corner coordinates outside the natural image dimensions (e.g., `x=-50` or `x > image_width`). |
| **Current behaviour** | `POST /mobile/scan-upload` calls `_four_point_perspective_crop(image_bytes, corners)`. If corners are out-of-bounds, OpenCV `getPerspectiveTransform` / `warpPerspective` may produce a black or garbage output image without raising an exception. |
| **Required behaviour** | Clamp each corner coordinate to `[0, image_width]` / `[0, image_height]` before passing to the perspective transform. Return HTTP 422 if all 4 corners collapse to a degenerate quadrilateral (zero area). |
| **Implementation note** | In `_four_point_perspective_crop` in `app.py`, after decoding the image to get `h, w`, clamp: `x = max(0, min(x, w)); y = max(0, min(y, h))`. Then check that the area of the quadrilateral is > 0. |

---

#### EC-022 — Perspective Crop Falls Back to Full Image Without Warning
| | |
|---|---|
| **Trigger** | Staff taps "Send to Desktop" without adjusting the corner handles — all 4 corners are at the default inset positions (8% margin). |
| **Current behaviour** | The full-frame image (minus 8% margin) is sent. If the document is not perfectly filling the frame, OCR may receive significant background area. No indication to staff that the crop was not adjusted. |
| **Required behaviour** | If the crop quadrilateral covers more than 85% of the image area AND the default corner positions were never moved, show a subtle prompt: "Crop not adjusted — drag corners to document edges for better OCR." (Non-blocking: staff can still send.) |
| **Implementation note** | Track whether any handle was dragged via a `cropHandlesMoved` boolean flag set in `onCropDown`. If false when `sendCroppedImage()` is called and quad area > 85% of image, show the hint. |

---

#### EC-023 — Crop Screen Rotation State Not Preserved Across Queue Items
| | |
|---|---|
| **Trigger** | Staff selects 3 images. Image 1 is sideways — they tap Rotate once. They send image 1. Images 2 and 3 load with fresh default orientation (correct behaviour). However, if the user accidentally taps "Skip" on image 1 after rotating and then re-encounters it somehow, the rotation is lost. |
| **Current behaviour** | `rotateCropImage()` updates `currentCropImageB64` in-place and re-renders the crop screen. The rotation is permanent for the current crop item — once rotated, the base64 is replaced. This is correct behaviour. |
| **Status** | No bug — documenting for clarity. The rotate button permanently mutates `currentCropImageB64`, so rotation is preserved until the item is sent or skipped. |

---

## SECTION 3 — MOBILE PHONE SCAN IMPLEMENTATION PLAN

### 3.1 — Camera Input (Frontend)

#### M-001 — Replace File Input With Camera-First Input
| | |
|---|---|
| **What to do** | Add `accept="image/*" capture="environment"` to each upload card's `<input type="file">` element to open the rear camera directly on mobile. |
| **Why** | Mobile devices with `capture="environment"` skip the file picker and open the camera immediately, reducing taps from 3 to 1. |
| **File** | `frontend/index.html` — upload card input elements |
| **Acceptance criteria** | On Android/iOS, tapping an upload card opens the camera. On desktop, the file picker still opens. |

```html
<!-- Before -->
<input type="file" accept=".pdf,.jpg,.jpeg,.png" onchange="handleFileSelect(this, 'aadhaar')">

<!-- After -->
<input type="file" accept="image/*,.pdf" capture="environment"
       onchange="handleFileSelect(this, 'aadhaar')">
```

---

#### M-002 — Add Desktop/Mobile Dual-Mode Detection
| | |
|---|---|
| **What to do** | Detect mobile via `navigator.maxTouchPoints > 0` or viewport width. On mobile, set `capture="environment"`. On desktop, omit `capture` to preserve file-picker behaviour. |
| **Why** | Desktop users need to select PDFs from disk, not open a webcam. The `capture` attribute must be conditional. |
| **File** | `frontend/index.html` — JavaScript init section |
| **Acceptance criteria** | Desktop: file picker opens as before. Mobile: camera opens directly. |

```javascript
function isMobile() {
    return navigator.maxTouchPoints > 0 && window.innerWidth < 1024;
}

function initUploadCards() {
    document.querySelectorAll('.upload-card input[type="file"]').forEach(input => {
        if (isMobile()) {
            input.setAttribute('capture', 'environment');
            input.setAttribute('accept', 'image/*');
        }
    });
}
document.addEventListener('DOMContentLoaded', initUploadCards);
```

---

#### M-003 — Show Live Preview Thumbnail After Capture
| | |
|---|---|
| **What to do** | After a photo is captured, display a 120×80 thumbnail preview inside the upload card using `URL.createObjectURL()`. |
| **Why** | Staff need visual confirmation that they captured the right document and that the photo is sharp — before uploading starts. |
| **File** | `frontend/index.html` — `handleFileSelect()` function |
| **Acceptance criteria** | After capture, the upload card shows a thumbnail of the photo with filename and file size. |

```javascript
function showThumbnail(card, file) {
    let preview = card.querySelector('.preview-img');
    if (!preview) {
        preview = document.createElement('img');
        preview.className = 'preview-img';
        preview.style.cssText = 'max-width:120px;max-height:80px;border-radius:4px;margin-top:6px;';
        card.appendChild(preview);
    }
    if (file.type.startsWith('image/')) {
        preview.src = URL.createObjectURL(file);
        preview.style.display = 'block';
    } else {
        preview.style.display = 'none';
    }
}
```

---

#### M-004 — Add "Retake" Button on Each Upload Card
| | |
|---|---|
| **What to do** | Show a "Retake" button alongside the existing "×" remove button on cards that have a captured photo. Clicking it clears the current file and re-opens the camera. |
| **Why** | If the preview looks blurry or wrong, staff should be able to re-capture without first removing the file and then tapping the card again. |
| **File** | `frontend/index.html` — upload card template + CSS |
| **Acceptance criteria** | "Retake" button visible on filled upload cards. Clicking it opens camera and replaces the file. |

```html
<button class="retake-btn" onclick="retakePhoto(this)" style="display:none;">&#128247; Retake</button>
```

```javascript
function retakePhoto(btn) {
    const card = btn.closest('.upload-card');
    const input = card.querySelector('input[type="file"]');
    input.value = '';
    input.click();
}
```

---

### 3.2 — Image Pre-Processing Before Upload (Frontend + Backend)

#### M-005 — Client-Side EXIF Orientation Fix (Canvas API)
| | |
|---|---|
| **What to do** | Before uploading, read the image into a Canvas element using `createImageBitmap()` which auto-applies EXIF orientation in modern browsers (Chrome 80+, Safari 13.4+, Firefox 98+). Draw to canvas, export as JPEG. |
| **Why** | iPhones encode rotation in EXIF metadata. Without this fix, the image arrives rotated for Gemini OCR. |
| **File** | `frontend/index.html` — new `preprocessImage()` function |
| **Acceptance criteria** | A portrait Aadhaar photo taken on iPhone always arrives server-side with correct orientation. |

```javascript
async function fixOrientation(file) {
    if (!file.type.startsWith('image/')) return file;
    const bitmap = await createImageBitmap(file);
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(bitmap, 0, 0);
    return new Promise(resolve => {
        canvas.toBlob(blob => {
            resolve(new File([blob], file.name.replace(/\.\w+$/, '.jpg'), {type: 'image/jpeg'}));
        }, 'image/jpeg', 0.92);
    });
}
```

---

#### M-006 — Client-Side HEIC → JPEG Conversion
| | |
|---|---|
| **What to do** | Import `heic2any` from CDN. Before upload, detect `.heic`/`.heif` files and convert to JPEG. |
| **Why** | iPhones with "High Efficiency" setting capture HEIC. Gemini API does not reliably process HEIC. Most backends reject it. |
| **File** | `frontend/index.html` — `<script>` tag + conversion function |
| **Acceptance criteria** | HEIC file from iPhone is silently converted to JPEG. Upload proceeds normally. |

```html
<script src="https://cdn.jsdelivr.net/npm/heic2any@0.0.4/dist/heic2any.min.js"></script>
```

```javascript
async function convertHeicIfNeeded(file) {
    const isHeic = file.name.toLowerCase().endsWith('.heic') ||
                   file.name.toLowerCase().endsWith('.heif') ||
                   file.type === 'image/heic' || file.type === 'image/heif';
    if (!isHeic) return file;
    const blob = await heic2any({ blob: file, toType: 'image/jpeg', quality: 0.85 });
    return new File([blob], file.name.replace(/\.hei[cf]$/i, '.jpg'), { type: 'image/jpeg' });
}
```

---

#### M-007 — Client-Side Image Resize and Compress
| | |
|---|---|
| **What to do** | Resize captured photos to max 1200px on the longest edge, JPEG quality 0.82, before uploading. |
| **Why** | Camera photos are 5–12 MB. Hospital WiFi is slow. Gemini Vision works well with 1200px images — higher resolution provides no OCR benefit. Target: < 300 KB per document. |
| **File** | `frontend/index.html` — `compressImage()` function |
| **Acceptance criteria** | A 4032×3024 / 8 MB photo becomes ~1200×900 / 200 KB JPEG before upload. |

```javascript
async function compressImage(file, maxDim = 1200, quality = 0.82) {
    if (!file.type.startsWith('image/')) return file;
    const bitmap = await createImageBitmap(file);
    let w = bitmap.width, h = bitmap.height;
    if (Math.max(w, h) > maxDim) {
        const scale = maxDim / Math.max(w, h);
        w = Math.round(w * scale);
        h = Math.round(h * scale);
    }
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d').drawImage(bitmap, 0, 0, w, h);
    return new Promise(resolve => {
        canvas.toBlob(blob => {
            resolve(new File([blob], file.name.replace(/\.\w+$/, '.jpg'), {type: 'image/jpeg'}));
        }, 'image/jpeg', quality);
    });
}
```

---

#### M-008 — Server-Side: Accept HEIC/HEIF MIME Types
| | |
|---|---|
| **What to do** | Add `image/heic` and `image/heif` to the accepted MIME types whitelist in the upload validator (F-006 fix). |
| **Why** | Even with client-side conversion, some browsers may pass through HEIC on older iOS webviews. The server must not reject them. |
| **File** | `app.py` — upload validation function |
| **Acceptance criteria** | Uploading a `.heic` file does not return a 400 error. |

```python
ALLOWED_MIME_TYPES = {
    "application/pdf", "image/jpeg", "image/png", "image/tiff",
    "image/heic", "image/heif", "image/webp", "image/bmp",
}
```

---

#### M-009 — Server-Side: Pillow EXIF Orientation Safety Net
| | |
|---|---|
| **What to do** | After saving an uploaded image, apply `ImageOps.exif_transpose()` to ensure correct orientation, overwriting the file. |
| **Why** | Fallback for cases where client-side EXIF fix fails (older browser, JavaScript disabled, non-standard EXIF). |
| **File** | `app.py` — after file save in `workflow_start` |
| **Acceptance criteria** | An image with EXIF orientation tag 6 (rotated 90° CW) is saved with correct pixel orientation. |

```python
from PIL import Image, ImageOps

def fix_image_orientation(file_path: str) -> None:
    """Apply EXIF orientation and overwrite file."""
    try:
        with Image.open(file_path) as img:
            fixed = ImageOps.exif_transpose(img)
            if fixed is not img:
                fixed.save(file_path)
    except Exception:
        pass  # Not an image or no EXIF — skip silently
```

---

#### M-010 — Server-Side: Enforce 8 MB File Size Limit
| | |
|---|---|
| **What to do** | After reading file bytes in `workflow_start`, reject files exceeding 8 MB with a clear error. |
| **Why** | Even with client-side compression, a fallback guard prevents disk exhaustion from direct API calls or buggy clients. |
| **File** | `app.py` — `workflow_start` file save loop |
| **Acceptance criteria** | Uploading a 15 MB file returns HTTP 400 with message "File exceeds 8 MB limit." |

```python
MAX_UPLOAD_SIZE = 8 * 1024 * 1024

content = await file.read()
if len(content) > MAX_UPLOAD_SIZE:
    err(f"File '{file.filename}' exceeds 8 MB limit ({len(content) // 1024 // 1024} MB)", 400)
```

---

### 3.3 — OCR Quality Feedback Loop (Backend + Frontend)

#### M-011 — Add Per-Document Confidence Score to OCR Response
| | |
|---|---|
| **What to do** | Compute confidence as `filled_fields / expected_fields_for_doc_type` after extraction. Return it in the `/workflow/start` response alongside each document's extraction result. |
| **Why** | Gemini does not return per-field confidence natively. Field fill rate is a reliable proxy: if 3/12 expected fields are populated, the scan quality was poor. |
| **File** | `app.py` — `workflow_start` extraction loop, `services/extractors/gemini_extractor.py` |
| **Acceptance criteria** | Response includes `"confidence": 0.75` per document. |

```python
# In workflow_start, after OCR for each file
expected_count = len(DOCUMENT_TYPES.get(fi["document_type"], {}).get("expected_fields", []))
if expected_count > 0:
    fill_rate = len([v for v in result.values() if v]) / expected_count
else:
    fill_rate = 1.0 if result else 0.0

raw_extractions.append({
    "file": fi["filename"],
    "type": fi["document_type"],
    "fields": result,
    "confidence": round(min(fill_rate, 1.0), 2),
    "filled_count": len(result),
    "expected_count": expected_count,
})
```

---

#### M-012 — Show Confidence Badge Per Document in Phase 1 UI
| | |
|---|---|
| **What to do** | After extraction, display a colour-coded badge on each upload card: green (≥ 80%), amber (50–79%), red (< 50%). |
| **Why** | Staff immediately see which scans are good and which need retaking, without checking every field manually. |
| **File** | `frontend/index.html` — extraction result handler |
| **Acceptance criteria** | Each upload card shows "87% ✓" in green or "32% ⚠" in red after extraction. |

```javascript
function showConfidenceBadge(card, confidence) {
    let badge = card.querySelector('.confidence-badge');
    if (!badge) {
        badge = document.createElement('span');
        badge.className = 'confidence-badge';
        badge.style.cssText = 'display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;margin-top:4px;';
        card.appendChild(badge);
    }
    const pct = Math.round(confidence * 100);
    badge.textContent = `${pct}%`;
    if (pct >= 80) {
        badge.style.background = '#e8f5e9'; badge.style.color = '#2e7d32';
    } else if (pct >= 50) {
        badge.style.background = '#fff8e1'; badge.style.color = '#f57f17';
    } else {
        badge.style.background = '#ffebee'; badge.style.color = '#c62828';
    }
}
```

---

#### M-013 — Low-Confidence Retake Prompt
| | |
|---|---|
| **What to do** | If a document's confidence < 50%, show an inline alert below the upload card: "Low quality scan — please retake this photo" with a prominent "Retake" button. |
| **Why** | A 30% fill rate means 70% of expected data is missing. It is faster to retake than to manually type every field. |
| **File** | `frontend/index.html` — extraction result handler |
| **Acceptance criteria** | Red alert appears automatically for low-confidence scans. Retake button opens camera and replaces the file. |

```javascript
function promptRetakeIfNeeded(card, confidence, docType) {
    const existing = card.querySelector('.retake-alert');
    if (existing) existing.remove();
    if (confidence < 0.5) {
        const alert = document.createElement('div');
        alert.className = 'retake-alert';
        alert.style.cssText = 'background:#ffebee;color:#c62828;padding:6px 10px;border-radius:4px;font-size:12px;margin-top:8px;';
        alert.innerHTML = `⚠ Low quality scan (${Math.round(confidence*100)}%) — <button class="btn btn-sm btn-danger" onclick="retakePhoto(this)">Retake</button>`;
        card.appendChild(alert);
    }
}
```

---

#### M-014-A — Retake & Re-extract for Single Document
| | |
|---|---|
| **What to do** | Add a `POST /workflow/{session_id}/retake` endpoint that accepts a new file for a specific `document_type`, re-runs OCR, and replaces only that document's contribution to `raw_ocr_merged` (not all documents). |
| **Why** | Staff should not wait for all 5 documents to re-extract when only 1 had a bad scan. The retaken photo's keys should overwrite the old photo's keys. |
| **File** | `app.py` — new endpoint |
| **Acceptance criteria** | After retaking Aadhaar, only Aadhaar fields are updated. Policy card data is preserved. |

```python
@app.post("/workflow/{session_id}/retake")
async def workflow_retake(
    session_id: str,
    file: UploadFile = File(...),
    document_type: str = Form("generic"),
):
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)

    # Save new file
    file_id = str(uuid.uuid4())[:8]
    safe_name = f"{file_id}_{file.filename}"
    save_path = UPLOADS_DIR / safe_name
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    # Extract
    extracted = ocr_service.extract(str(save_path), document_type)

    # Remove old keys from this doc type, add new ones
    old_keys = set()
    for ext in session["raw_extractions"]:
        if ext.get("type") == document_type and "fields" in ext:
            old_keys.update(ext["fields"].keys())

    merged = session["raw_ocr_merged"]
    for k in old_keys:
        merged.pop(k, None)
    merged.update(extracted)

    session["raw_ocr_merged"] = merged
    _save_session(session_id)

    return ok({"replaced": document_type, "new_fields": len(extracted)})
```

---

### 3.4 — Master Form Population from Phone Scan (Backend)

#### M-014 — Confidence-Weighted KV Merge
| | |
|---|---|
| **What to do** | Replace the first-win merge loop with a confidence-weighted strategy: each key stores `{value, confidence, source_file}`. Later extractions overwrite if their key count (proxy for confidence) is higher for that document type. |
| **Why** | First-win merge causes data quality loss (F-007). A policy card's "Patient Name" is more reliable than an Aadhaar's OCR of a faded card. |
| **File** | `app.py` — `workflow_start` merge loop |
| **Acceptance criteria** | If Aadhaar returns `"Name": "R K"` (2 chars → low confidence) and policy card returns `"Name": "RAJESH KUMAR"` (12 chars → higher confidence), the final merged value is "RAJESH KUMAR". |

```python
# Replace first-win merge with confidence-weighted merge
all_extracted_rich: dict[str, dict] = {}  # key -> {value, confidence, source_file}

for fi, result in zip(file_info, ocr_results):
    if isinstance(result, Exception):
        continue
    expected = len(DOCUMENT_TYPES.get(fi["document_type"], {}).get("expected_fields", []))
    fill_rate = len(result) / max(expected, 1)
    for k, v in result.items():
        val_conf = min(fill_rate, 1.0)
        if k not in all_extracted_rich or val_conf > all_extracted_rich[k]["confidence"]:
            all_extracted_rich[k] = {
                "value": v,
                "confidence": round(val_conf, 2),
                "source_file": fi["filename"],
            }

# Flatten for backward compat
all_extracted = {k: v["value"] for k, v in all_extracted_rich.items()}
```

---

#### M-015 — Source Tracking Per Mapped Field
| | |
|---|---|
| **What to do** | Store `_source_map` in session: `{field_id: {source_doc, confidence, extraction_method}}` alongside `mapped_data`. |
| **Why** | Staff and auditors need to know where each value came from (F-008, DPDP Act audit trail). |
| **File** | `app.py` — `workflow_start`, after mapping |
| **Acceptance criteria** | Session JSON includes `source_map` with per-field provenance. |

```python
source_map = {}
for field_id, value in mapped_data.items():
    # Find which OCR key produced this value
    for k, rich in all_extracted_rich.items():
        if str(rich["value"]) == str(value):
            source_map[field_id] = {
                "source_doc": rich["source_file"],
                "confidence": rich["confidence"],
                "ocr_key": k,
            }
            break

session["source_map"] = source_map
```

---

#### M-016 — Source Tooltip on Each Field in Phase 2 Form
| | |
|---|---|
| **What to do** | In the Phase 2 form renderer, add a tooltip on each field showing "Extracted from: clinical_notes.jpg, confidence: 87%". |
| **Why** | Staff can immediately see the provenance of each pre-filled value and decide whether to trust or override it. |
| **File** | `frontend/index.html` — field rendering function |
| **Acceptance criteria** | Hovering over a pre-filled field shows source document name and confidence percentage. |

```javascript
function renderFieldWithSource(field, value, sourceMap) {
    const wrapper = document.createElement('div');
    wrapper.className = 'field-group';
    const label = document.createElement('label');
    label.textContent = field.label;
    const input = document.createElement('input');
    input.value = value || '';
    input.dataset.fieldId = field.field_id;
    if (value) input.classList.add('ocr-filled');

    const source = sourceMap[field.field_id];
    if (source) {
        input.title = `Extracted from: ${source.source_doc}, confidence: ${Math.round(source.confidence * 100)}%`;
    }
    wrapper.appendChild(label);
    wrapper.appendChild(input);
    return wrapper;
}
```

---

### 3.5 — PWA + Responsive UI (Frontend)

#### M-017 — Create manifest.json
| | |
|---|---|
| **What to do** | Create `frontend/manifest.json` with app name, icons, theme colour, and `display: standalone` so the app can be installed as a PWA on mobile home screens. |
| **Why** | PWA enables full-screen experience on mobile, eliminates browser chrome, and allows the "Add to Home Screen" flow. |
| **File** | `frontend/manifest.json` (new file) |
| **Acceptance criteria** | Chrome DevTools > Application > Manifest shows valid manifest with installability check passing. |

```json
{
  "name": "TPA Pre-Authorization System",
  "short_name": "PreAuth",
  "description": "Hospital pre-authorization form automation",
  "start_url": "/ui",
  "display": "standalone",
  "background_color": "#f0f2f5",
  "theme_color": "#1a237e",
  "icons": [
    { "src": "/ui/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/ui/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

---

#### M-018 — Create service-worker.js
| | |
|---|---|
| **What to do** | Create a service worker with cache-first strategy for static assets (HTML, CSS, JS, icons) and network-first for API calls (`/workflow/*`, `/forms/*`). |
| **Why** | Caches the UI shell for instant load on hospital WiFi. API calls always go to the network first to get fresh data. |
| **File** | `frontend/service-worker.js` (new file) |
| **Acceptance criteria** | After first load, the UI shell loads instantly even on slow network. API errors show "Network error" rather than a blank page. |

```javascript
const CACHE_NAME = 'preauth-v1';
const STATIC_ASSETS = ['/ui', '/ui/manifest.json'];

self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)));
});

self.addEventListener('fetch', e => {
    if (e.request.url.includes('/workflow/') || e.request.url.includes('/forms/') ||
        e.request.url.includes('/auth/')) {
        // Network-first for API calls
        e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    } else {
        // Cache-first for static assets
        e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
    }
});
```

---

#### M-019 — Link manifest.json and service-worker.js in index.html
| | |
|---|---|
| **What to do** | Add `<link rel="manifest">` and service worker registration script to the `<head>` of `frontend/index.html`. |
| **Why** | The manifest and service worker are only active when linked from the HTML document. |
| **File** | `frontend/index.html` — `<head>` section |
| **Acceptance criteria** | Browser detects PWA. "Install app" prompt appears on Android Chrome. |

```html
<link rel="manifest" href="/ui/manifest.json">
<meta name="theme-color" content="#1a237e">
<script>
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/ui/service-worker.js')
        .then(r => console.log('SW registered:', r.scope))
        .catch(e => console.warn('SW registration failed:', e));
}
</script>
```

---

#### M-020 — Mobile-First CSS Media Queries
| | |
|---|---|
| **What to do** | Add responsive CSS: stack two-column layouts into single column below 768px, increase tap targets to min 44×44px, increase form field font size to 16px (prevents iOS zoom on focus). |
| **Why** | Current layout breaks on mobile — two-column field rows overflow. Tap targets are too small at 32px. iOS auto-zooms on `<input>` with `font-size < 16px`. |
| **File** | `frontend/index.html` — `<style>` section |
| **Acceptance criteria** | On a 375px-wide iPhone screen: all content fits, no horizontal scroll, all buttons are easily tappable, inputs do not zoom. |

```css
@media (max-width: 768px) {
    .container { padding: 12px; }
    .field-row { grid-template-columns: 1fr; }
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
    .upload-grid { grid-template-columns: 1fr 1fr; gap: 10px; }
    .btn { min-height: 44px; min-width: 44px; font-size: 15px; }
    .field-group input, .field-group select, .field-group textarea {
        font-size: 16px; padding: 10px 12px; min-height: 44px;
    }
    .mrd-input-group { flex-direction: column; }
    .mrd-input-group .form-control { font-size: 20px; }
    .tab-bar { padding: 0 4px; }
    .tab-item { padding: 10px 8px; font-size: 11px; }
    .tpa-selector { flex-direction: column; align-items: stretch; }
    .tpa-selector select { min-width: auto; width: 100%; }
    .navbar { padding: 0 12px; height: 48px; }
    .navbar-brand { font-size: 15px; }
}
```

---

#### M-021 — "Add to Home Screen" Nudge Banner
| | |
|---|---|
| **What to do** | Show a dismissible banner on mobile browsers: "Install this app for a better experience" with an "Install" button that triggers the `beforeinstallprompt` event. |
| **Why** | Staff may not know they can install the PWA. The nudge increases adoption of standalone mode which removes browser chrome and enables full-screen camera access. |
| **File** | `frontend/index.html` — JavaScript + CSS |
| **Acceptance criteria** | Banner appears on first visit on mobile. After dismissal or install, it does not reappear (stored in localStorage). |

```javascript
let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', e => {
    e.preventDefault();
    deferredPrompt = e;
    if (!localStorage.getItem('pwa-dismissed')) {
        document.getElementById('installBanner').classList.remove('hidden');
    }
});

function installPWA() {
    if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(choice => {
            if (choice.outcome === 'accepted') localStorage.setItem('pwa-dismissed', '1');
            deferredPrompt = null;
            document.getElementById('installBanner').classList.add('hidden');
        });
    }
}

function dismissInstall() {
    localStorage.setItem('pwa-dismissed', '1');
    document.getElementById('installBanner').classList.add('hidden');
}
```

---

### 3.6 — Security Hardening for Mobile (Backend)

#### M-022 — Move Staff Credentials to Environment Variables
| | |
|---|---|
| **What to do** | Remove `STAFF_USERS` dict from `app.py`. Store bcrypt-hashed passwords in `.env` file. Validate at login against hashes. |
| **Why** | Hardcoded credentials in source code (F-001) are the #1 security finding in any audit. Mobile deployment increases exposure since the app is accessed over WiFi. |
| **File** | `app.py` lines 347–351, `.env` |
| **Acceptance criteria** | No plaintext passwords in `app.py`. Login works against `STAFF_ADMIN_HASH` from `.env`. |

```python
import bcrypt

def _load_staff_hashes() -> dict[str, str]:
    users = {}
    for key, val in os.environ.items():
        if key.startswith("STAFF_") and key.endswith("_HASH"):
            username = key.replace("STAFF_", "").replace("_HASH", "").lower()
            users[username] = val
    return users

STAFF_HASHES = _load_staff_hashes()

@app.post("/auth/login")
def login(req: LoginRequest):
    stored_hash = STAFF_HASHES.get(req.username)
    if not stored_hash or not bcrypt.checkpw(req.password.encode(), stored_hash.encode()):
        err("Invalid credentials", 401)
    token = create_token(req.username)
    return ok({"token": token, "username": req.username, "expires_in": JWT_EXPIRY_HOURS * 3600})
```

---

#### M-023 — Per-Session Rate Limiting on /workflow/start
| | |
|---|---|
| **What to do** | Install `slowapi` and apply a rate limit of 10 requests/hour per IP on `/workflow/start` and `/documents/ocr`. |
| **Why** | Each OCR call costs Gemini API credits. Without rate limiting, a misconfigured client or malicious actor can exhaust the quota. Mobile users on shared hospital WiFi share the same network IP, so per-IP limits need to be reasonably high. |
| **File** | `app.py` — middleware setup, endpoint decorators |
| **Acceptance criteria** | After 10 `/workflow/start` calls from the same IP within 1 hour, the 11th returns HTTP 429 "Rate limit exceeded". |

```python
# requirements.txt: add slowapi
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

---

#### M-024 — Encrypt Session Files at Rest With Fernet
| | |
|---|---|
| **What to do** | Use `cryptography.Fernet` to encrypt session JSON before writing to disk and decrypt on read. Key stored in `SESSION_ENCRYPTION_KEY` env var. |
| **Why** | Session files contain full patient PHI (F-003). Mobile deployment means the server may run on a shared machine. At-rest encryption is a DPDP Act requirement for personal data. |
| **File** | `app.py` — `_save_session()`, `_load_session()` |
| **Acceptance criteria** | Session files on disk are binary (encrypted). `cat sessions/*.enc` shows ciphertext. Correct key decrypts to valid JSON. |

(Code provided in F-003 fix above.)

---

#### M-025 — MRD Input Sanitisation
| | |
|---|---|
| **What to do** | Add regex validation to MRD number: alphanumeric + hyphens only, max 20 characters. Apply at both frontend (HTML `pattern` attribute) and backend (F-004 `sanitize_mrd()` function). |
| **Why** | MRD is used in filenames and session IDs. Unsanitised input causes path traversal (F-004). On mobile, staff may copy-paste MRD from SMS, which can include invisible Unicode characters. |
| **File** | `app.py` — `workflow_start`, `workflow_update_mrd`; `frontend/index.html` — MRD input field |
| **Acceptance criteria** | MRD `"AMR/2024/001"` is sanitised to `"AMR2024001"`. MRD with `../` is rejected. |

```html
<!-- Frontend validation -->
<input type="text" id="mrdInput" class="form-control"
       pattern="[a-zA-Z0-9\-]{1,20}" maxlength="20"
       title="Alphanumeric characters and hyphens only, max 20 characters"
       placeholder="Enter MRD Number">
```

---

## SECTION 4 — QUICK WIN FIXES (< 2 hours each)

### QW-001 — Gemini API Retry Logic
| | |
|---|---|
| **What** | Add 3-attempt exponential backoff to Gemini `generate_content()` call |
| **File + Line** | `services/extractors/gemini_extractor.py` lines 224–237 |
| **Fix** | Install `tenacity`. Wrap API call with `@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))` |

```python
# pip install tenacity
from tenacity import retry, stop_after_attempt, wait_exponential
# Apply decorator to the API call method — see F-013 for full code
```

---

### QW-002 — Rate Limiting With slowapi
| | |
|---|---|
| **What** | Add per-IP rate limit (10/hour) to `/workflow/start` |
| **File + Line** | `app.py` line 761 |
| **Fix** | `pip install slowapi`. Add `@limiter.limit("10/hour")` to `workflow_start` |

---

### QW-003 — Date Normalisation Helper
| | |
|---|---|
| **What** | Normalise all date fields to DD/MM/YYYY after extraction and before mapping |
| **File + Line** | `app.py` — after merge loop (line ~815) |
| **Fix** | |

```python
from dateutil import parser as dateparser

DATE_FIELD_KEYWORDS = {"date", "dob", "birth", "admission", "discharge", "consultation"}

def normalise_dates(data: dict) -> dict:
    for key, value in data.items():
        if not isinstance(value, str) or not any(kw in key.lower() for kw in DATE_FIELD_KEYWORDS):
            continue
        try:
            parsed = dateparser.parse(value, dayfirst=True)
            if parsed and 1900 < parsed.year <= 2030:
                data[key] = parsed.strftime("%d/%m/%Y")
        except (ValueError, OverflowError):
            pass
    return data
```

---

### QW-004 — Cost Field ₹ Parsing
| | |
|---|---|
| **What** | Strip ₹, Rs., commas, `/-` from all cost fields after extraction |
| **File + Line** | `app.py` — after merge loop (line ~815) |
| **Fix** | |

```python
import re

COST_FIELD_KEYWORDS = {"cost", "charges", "rent", "fees", "expense", "total", "amount", "estimate"}

def normalise_costs(data: dict) -> dict:
    for key, value in data.items():
        if not isinstance(value, str) or not any(kw in key.lower() for kw in COST_FIELD_KEYWORDS):
            continue
        cleaned = re.sub(r'[₹Rs.\s,/\-]', '', value.strip()).strip('.')
        if cleaned.isdigit():
            data[key] = cleaned
    return data
```

---

### QW-005 — GIPSA False-Positive Fix
| | |
|---|---|
| **What** | Replace substring `in` check with token-overlap matching for GIPSA detection |
| **File + Line** | `app.py` — wherever GIPSA detection is applied against `GIPSA_TPA_LIST` |
| **Fix** | See EC-015 implementation note above for `is_gipsa_case()` function |

---

### QW-006 — Session TTL + In-Memory Eviction
| | |
|---|---|
| **What** | Evict stale sessions from `_sessions` dict during PHI purge to prevent memory leak |
| **File + Line** | `app.py` lines 80–104 (`_purge_old_phi`) |
| **Fix** | Add in-memory eviction — see F-017 fix above (5 lines of code) |

---

### QW-007 — Required-Field Validation Before PDF Generation
| | |
|---|---|
| **What** | Add a `POST /workflow/{session_id}/validate` endpoint that checks required fields and returns missing ones |
| **File + Line** | `app.py` — new endpoint before `workflow_generate` |
| **Fix** | |

```python
REQUIRED_FIELDS = {"patient_name", "date_of_birth", "policy_number", "date_of_admission"}

@app.post("/workflow/{session_id}/validate")
def workflow_validate(session_id: str):
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)
    data = session.get("mapped_data", {})
    missing = [f for f in REQUIRED_FIELDS if not data.get(f, "").strip()]
    return ok({"valid": len(missing) == 0, "missing_fields": missing})
```

---

### QW-008 — Propagate JSON Parse Failure to Frontend
| | |
|---|---|
| **What** | When Gemini JSON parse fails, set `ExtractedDocument.error` instead of returning empty `{}` silently |
| **File + Line** | `services/extractors/gemini_extractor.py` lines 299–305 |
| **Fix** | |

```python
@staticmethod
def _parse_json_response(text: str) -> dict:
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
        return {}
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Gemini JSON: %s\nRaw (first 500 chars): %s", e, text[:500])
        raise ValueError(f"Gemini returned unparseable response: {e}")
```

Then in `extract()`, catch `ValueError` and set `ExtractedDocument.error`:

```python
try:
    raw_dict = self._parse_json_response(text)
except ValueError as e:
    return ExtractedDocument(
        source_file=str(file_path), document_type=document_type,
        extraction_method="gemini", error=str(e),
    )
```

---

## SECTION 5 — REVISED IMPLEMENTATION TIMELINE

> **Deployment target: On-premise server provided by hospital IT team.**  
> All cloud references in earlier planning docs (Cloud Run, Firestore, Cloud Storage, Google Identity Platform, Secret Manager) are **not applicable**. Replace with on-premise equivalents listed in Section 9.

| Week | Phase | Steps Covered | Deliverable | Risk if Skipped |
|------|-------|---------------|-------------|-----------------|
| **1** | Security + Quick Wins | F-001, F-002, F-003, F-004, F-005, F-006, QW-001 through QW-008 | Credentials in env vars, JWT validation, encrypted sessions, MRD sanitisation, retry logic, rate limiting, date/cost normalisation, GIPSA fix, field validation endpoint, JSON parse error surfacing | PHI breach (DPDP Act violation), credential leak, Gemini quota exhaustion, garbled data on TPA forms — any of these blocks production deployment |
| **2** | Phone Camera Input + Image Pre-Processing | M-001 through M-010 (Sections 3.1 + 3.2) | Camera-first upload on mobile, EXIF fix, HEIC conversion, client-side compression, server-side size guard, Pillow orientation safety net | Mobile users cannot capture documents → feature is unusable. Without compression, uploads stall on hospital WiFi |
| **3** | Confidence Scoring + Source Tracking + Master Form Upgrade | M-011 through M-016 (Sections 3.3 + 3.4) | Per-document confidence badges, retake prompts, confidence-weighted merge replacing first-win, source provenance tracking with tooltips, retake-and-replace endpoint | Staff cannot tell which scans are poor (wasted time editing empty fields). No audit trail for PHI values. Inferior data quality from first-win merge |
| **4** | PWA + Responsive UI | M-017 through M-021 (Section 3.5) | manifest.json, service-worker.js, mobile CSS, "Add to Home Screen" nudge, full-screen standalone mode | App feels like a website, not a tool. Slow loads on hospital WiFi. Poor mobile UX discourages adoption by ward staff |
| **5** | On-Premise Production Hardening | M-022 through M-025 (Section 3.6), HTTPS (F-005), PDF fixes (F-019, F-020, F-021), Section 9 | bcrypt auth, rate limiting, Fernet session encryption, MRD sanitisation, Nginx TLS, text wrapping, Unicode font support, correct page heights, systemd service, log rotation | Security audit fails. Hindi patient names blank on PDFs. Text overflows on TPA forms. Production is not deployable without TLS |
| **6** | Schema-First Prompts + Confidence Scoring | Section 6 (P-001 through P-004) | Per-doc-type Gemini prompts, dynamic schema injection, real Gemini confidence, ExtractedField update | Extraction accuracy stays at ~45%. Fuzzy mapping drift continues. Staff manually correct most fields |
| **7** | AI Suggestion Engine | Section 7 (S-001 through S-004) | `/ai/suggest-batch` endpoint, ghost-text UI, confidence colour indicators, hospital defaults config | Staff spend 8–10 min per form. Empty fields after OCR failure require full manual entry |
| **8** | Validation + Cross-Check Layer | Section 8 (V-001 through V-003) | `services/validators.py`, cross-doc consistency checks, `/workflow/{id}/warnings`, warning banner in UI | Invalid dates/policies submitted to TPA. Name mismatches not caught before PDF generation |
| **9** | Architecture Refactoring | Section 10 (AR-001 through AR-007) | Extract inline business logic from `app.py`, deduplicate mapping code, structured logging, externalize TPA template map | Codebase becomes unmaintainable. New TPA forms require changes in 4 places. Debugging without trace IDs is blind |
| **10+** | Advanced Features | Section 11 (AF-001 through AF-004) | Per-TPA validation rules, learning from corrections, multi-page context, HIS integration | Accuracy plateau at ~70%. No continuous improvement loop |

---

## SECTION 6 — SCHEMA-FIRST PROMPT ENGINE

> **Gap identified:** This entire area is missing from earlier sections. It is the highest-ROI improvement — estimated +40% extraction accuracy. Corresponds to PRODUCTION_PLAN Phase 1.

### P-001 — Rewrite Gemini Prompts Per Document Type
| | |
|---|---|
| **Priority** | HIGH |
| **File** | `services/extractors/gemini_extractor.py` — `_build_gemini_prompt()` |
| **What is broken** | The current prompt is generic. Gemini extracts arbitrary key names ("Pt Name", "H/o Present Illness") that the MappingEngine must fuzzy-match. This indirect pipeline loses accuracy at every hop. |
| **Fix** | Replace single generic prompt with 4 specialised prompts by document type, each with a fixed output schema using real `field_id` keys. |

**Document types to handle:**

| Document Type | Key Prompt Additions |
|---|---|
| `clinical_notes` | Full Indian medical abbreviation glossary (C/o, H/o, K/c/o, T2DM, HTN, etc.). Output keys match clinical field_ids. |
| `estimate` | Cost breakdown extraction, all amounts as plain integers (no ₹/commas). `_line_items` array. |
| `aadhaar` / `id_card` | Aadhaar/PAN/Voter ID format specifics. UID must be 12 digits. Ignore Hindi unless English missing. |
| `policy_card` | TPA/insurer name disambiguation. Sum insured as plain number. Both TPA and insurance company captured. |

**New function signature:**
```python
def _build_gemini_prompt(document_type: str, target_field_ids: list[str] = None) -> str:
    """
    Build a document-type-specific extraction prompt.
    If target_field_ids provided, instructs Gemini to use those exact keys.
    """
```

**Rules common to all prompts:**
1. Expand all abbreviations.
2. Omit keys with no data (never return null/None).
3. Dates → DD/MM/YYYY format.
4. Return ONLY valid JSON — no markdown fences, no prose.

---

### P-002 — Dynamic Schema Injection Into Prompt
| | |
|---|---|
| **Priority** | HIGH |
| **File** | `app.py` — `workflow_start()`, `services/extractors/gemini_extractor.py` |
| **What is broken** | Prompt output keys are hardcoded. When a new TPA schema has different `field_id`s, the prompt must be manually updated. |
| **Fix** | Pass the selected schema's `field_id` list into the extractor. Append to prompt: |

```python
# In workflow_start, after TPA detection, before OCR:
schema_field_ids = [f["field_id"] for f in selected_schema.get("fields", [])]

# Pass into extractor:
result = ocr_service.extract(path, doc_type, target_field_ids=schema_field_ids)
```

```
# Appended to prompt when target_field_ids provided:
IMPORTANT: Map your output keys to these EXACT field IDs where applicable:
["patient_name", "date_of_birth", "policy_number", ...]
Use these as your output keys instead of free-form names.
```

**Impact:** New TPA forms auto-adapt without any prompt code change — just re-analyse the PDF and the schema JSON drives the extraction.

---

### P-003 — Gemini Per-Field Confidence Scoring
| | |
|---|---|
| **Priority** | HIGH |
| **File** | `services/extractors/gemini_extractor.py` |
| **What is broken** | All fields get a hardcoded `confidence=0.85`. The UI cannot distinguish a clearly printed Aadhaar number (should be 0.97) from illegible handwritten diagnosis (should be 0.40). |
| **Fix** | Ask Gemini to return a `_confidence` object alongside the data: |

```
Additionally, return a "_confidence" object where keys are field_ids and
values are your confidence (0.0 to 1.0) that the extraction is correct.
Mark < 0.5 for handwritten/illegible text, 0.5-0.8 for partially visible,
0.8-1.0 for clearly printed text.
```

**Response shape Gemini should return:**
```json
{
  "patient_name": "Rajesh Kumar",
  "provisional_diagnosis": "T2DM with HTN",
  "_confidence": {
    "patient_name": 0.95,
    "provisional_diagnosis": 0.62
  }
}
```

---

### P-004 — Update ExtractedField to Parse Gemini Confidence
| | |
|---|---|
| **Priority** | HIGH |
| **File** | `services/extractors/gemini_extractor.py` — field construction loop |
| **What is broken** | `confidence=0.85` is hardcoded for every field. |
| **Fix** | |

```python
# After parsing Gemini JSON response:
confidence_map = raw_dict.pop("_confidence", {})
for key, value in raw_dict.items():
    if key.startswith("_"):  # skip meta fields like _raw_vitals, _line_items
        continue
    conf = float(confidence_map.get(key, 0.75))
    fields.append(ExtractedField(
        key=key,
        value=str(value) if not isinstance(value, bool) else value,
        confidence=conf,
        confidence_level=ExtractionConfidence.from_score(conf),
        source_document=Path(file_path).name,
        document_type=document_type,
        extraction_method="gemini",
    ))
```

**Note:** Add `from_score()` classmethod to `ExtractionConfidence`:
```python
@classmethod
def from_score(cls, score: float) -> "ExtractionConfidence":
    if score >= 0.90: return cls.HIGH
    if score >= 0.70: return cls.MEDIUM
    if score >= 0.50: return cls.LOW
    return cls.UNCERTAIN
```

---

## SECTION 7 — AI SUGGESTION ENGINE

> **Gap identified:** Entirely absent from earlier sections. Corresponds to PRODUCTION_PLAN Phase 2. Fills fields that OCR couldn't extract by using clinical context inference.

### S-001 — New Endpoint: `POST /ai/suggest-batch`
| | |
|---|---|
| **Priority** | HIGH |
| **File** | `app.py` — new endpoint |
| **Purpose** | Called once after OCR mapping completes. Sends all filled fields to Gemini and asks it to infer values for empty fields. Returns suggestions as ghost text, not auto-accepted values. |

```python
@app.post("/ai/suggest-batch")
async def ai_suggest_batch(
    session_id: str = Form(...),
    token: str = Depends(require_auth),
):
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)

    filled = {k: v for k, v in session.get("mapped_data", {}).items() if v}
    empty_fields = [
        f["field_id"] for f in session.get("schema_fields", [])
        if not session.get("mapped_data", {}).get(f["field_id"])
    ]

    if not empty_fields:
        return ok({"suggestions": {}})

    prompt = f"""
Given this patient context extracted from documents:
{json.dumps(filled, indent=2)}

Suggest the most likely values for these empty form fields: {empty_fields}

Use clinical knowledge for Indian hospital pre-authorization contexts.
Examples of inference:
- If surgical_name_of_surgery is filled → treatment_type = "Surgical"
- If diagnosis is "Dengue Fever" → expected_days_in_hospital = "5", icd_code = "A90"
- If room_type is missing → default "Semi-Private" for corporate policies

Return JSON: {{"field_id": {{"value": "suggested_value", "confidence": 0.0-1.0, "reason": "brief reason"}}}}
Return ONLY valid JSON. Omit fields you cannot confidently suggest.
"""
    # Call Gemini with prompt only (no image)
    suggestions = _call_gemini_text(prompt)
    return ok({"suggestions": suggestions})
```

---

### S-002 — New Endpoint: `POST /ai/suggest` (Single Field)
| | |
|---|---|
| **Priority** | MEDIUM |
| **File** | `app.py` — new endpoint |
| **Purpose** | Called when staff clicks an empty field. Returns a focused suggestion using surrounding context. |

```python
@app.post("/ai/suggest")
async def ai_suggest_field(
    session_id: str = Form(...),
    field_id: str = Form(...),
    context_fields: str = Form("{}"),
    token: str = Depends(require_auth),
):
    """AI suggestion for a single field using filled context."""
    context = json.loads(context_fields)
    prompt = f"""
Context: {json.dumps(context)}
Suggest value for field: "{field_id}"
Return JSON: {{"value": "...", "confidence": 0.0-1.0}}
"""
    suggestion = _call_gemini_text(prompt)
    return ok(suggestion)
```

---

### S-003 — Frontend: Ghost-Text Suggestion UI
| | |
|---|---|
| **Priority** | HIGH |
| **File** | `frontend/index.html` |
| **What to add** | After batch suggest response, show suggestions as dismissible ghost text alongside empty input fields. Staff can click to accept. |

**CSS — confidence indicators + ghost text:**
```css
.field-group input.confidence-high   { border-left: 3px solid #2e7d32; } /* green */
.field-group input.confidence-medium { border-left: 3px solid #f57f17; } /* amber */
.field-group input.confidence-low    { border-left: 3px solid #c62828; } /* red */
.field-group input.ai-suggested      { border-left: 3px solid #7c4dff; } /* purple */

.ai-suggestion {
    font-size: 12px; color: #7c4dff; cursor: pointer;
    margin-left: 6px; font-style: italic;
}
.ai-suggestion:hover { text-decoration: underline; }
```

**JS — accept/reject flow:**
```javascript
async function suggestAllEmpty() {
    showLoading('AI is analysing context...');
    const fd = new FormData();
    fd.append('session_id', currentSessionId);
    const res = await fetch(API + '/ai/suggest-batch', { method: 'POST', body: fd, headers: authHeader() });
    const json = await res.json();
    hideLoading();
    for (const [fieldId, suggestion] of Object.entries(json.data.suggestions)) {
        const input = document.getElementById('f_' + fieldId);
        if (!input || input.value.trim()) continue;
        const span = document.createElement('span');
        span.className = 'ai-suggestion';
        span.textContent = suggestion.value + ' ✨';
        span.title = `AI (${Math.round(suggestion.confidence * 100)}%): ${suggestion.reason}`;
        span.onclick = () => acceptSuggestion(fieldId, suggestion.value, span);
        input.parentElement.appendChild(span);
    }
}

function acceptSuggestion(fieldId, value, span) {
    const input = document.getElementById('f_' + fieldId);
    input.value = value;
    input.classList.add('ai-suggested');
    updateFieldValue(fieldId, value);
    span.remove();
}
```

**Button in Generate tab (or top of Phase 2):**
```html
<button class="btn btn-accent" onclick="suggestAllEmpty()">
    ✨ AI Auto-fill Empty Fields
</button>
```

---

### S-004 — Hospital Defaults Config
| | |
|---|---|
| **Priority** | MEDIUM |
| **File** | `config/hospital_defaults.json` (new file) |
| **Purpose** | Provides Gemini with realistic Indian hospital context for suggestion inference. Also used to inject hospital fields without hardcoding in `app.py`. |

```json
{
  "hospital_name": "Amrita Hospital",
  "hospital_address": "Sector 88, Faridabad, Haryana",
  "hospital_registration_number": "HR/FAR/2023/001234",
  "hospital_phone": "0129-XXXXXXX",
  "hospital_email": "preauth@amritahospital.org",
  "common_diagnoses": {
    "Appendicitis":   { "icd": "K35.80", "typical_los": 3, "treatment": "Surgical" },
    "Cholecystitis":  { "icd": "K81.0",  "typical_los": 3, "treatment": "Surgical" },
    "Dengue Fever":   { "icd": "A90",    "typical_los": 5, "treatment": "Medical"  },
    "Pneumonia":      { "icd": "J18.9",  "typical_los": 5, "treatment": "Medical"  },
    "AMI":            { "icd": "I21.9",  "typical_los": 7, "treatment": "Surgical" },
    "TKR":            { "icd": "M17.11", "typical_los": 7, "treatment": "Surgical" },
    "LSCS":           { "icd": "O82",    "typical_los": 5, "treatment": "Surgical" },
    "Cataract":       { "icd": "H25.9",  "typical_los": 1, "treatment": "Daycare"  }
  },
  "room_rates": {
    "General": 2500, "Semi-Private": 4500,
    "Private": 8000, "Deluxe": 12000, "ICU": 15000
  }
}
```

**Migration note:** Replace the hardcoded hospital data block in `app.py` (currently around lines 120–135) with a loader that reads this file. This also fixes architecture issue AR-005 (hardcoded for a single hospital).

---

## SECTION 8 — VALIDATION & CROSS-CHECK LAYER

> **Gap identified:** QW-007 only checks 4 required fields. This section implements a full validator and cross-document consistency checks. Corresponds to PRODUCTION_PLAN Phase 3.

### V-001 — Field-Level Validation Rules
| | |
|---|---|
| **Priority** | HIGH |
| **File** | `services/validators.py` (new file) |

```python
import re
from datetime import datetime
from dateutil import parser as dateparser

VALIDATION_RULES = {
    "patient_name": {
        "min_length": 2, "max_length": 100,
        "pattern": r"^[A-Za-z\s\.]+$",
        "error": "Name should contain only letters",
    },
    "date_of_admission": {
        "format": "DD/MM/YYYY",
        "must_be_past_or_today": True,
        "must_be_after_field": "date_of_birth",
    },
    "policy_end_date": {
        "format": "DD/MM/YYYY",
        "must_be_future_or_today": True,
        "error": "Policy appears expired",
    },
    "sum_total_expected_cost_of_hospitalization": {
        "type": "number", "min": 1000, "max": 50_000_000,
    },
    "expected_days_in_hospital": {
        "type": "integer", "min": 1, "max": 365,
    },
    "policy_number": { "min_length": 5 },
    "id_number": {
        "patterns": {
            "aadhaar": r"^\d{12}$",
            "pan":     r"^[A-Z]{5}\d{4}[A-Z]$",
        }
    },
}

def validate_field(field_id: str, value: str, all_data: dict) -> list[str]:
    """Returns list of error strings for a field. Empty list = valid."""
    errors = []
    rules = VALIDATION_RULES.get(field_id)
    if not rules or not value:
        return errors
    # ... apply each rule type ...
    return errors
```

---

### V-002 — Cross-Document Consistency Checks
| | |
|---|---|
| **Priority** | HIGH |
| **File** | `services/validators.py` — `cross_check()` function |

```python
COST_FIELDS = [
    "per_day_room_rent_nursing_service_charges_patient_diet",
    "icu_charges", "ot_charges", "professional_fees_surgeon",
    "professional_fees_anesthetist", "medicines_consumables_cost",
    "cost_of_implant", "investigation_diagnostic_cost",
]

def cross_check(data: dict) -> list[dict]:
    """Returns list of {type, message, fields} warning dicts."""
    warnings = []

    # Patient name consistency
    names = [data.get(f) for f in ["patient_name", "insured_name"] if data.get(f)]
    if len(set(n.lower().strip() for n in names)) > 1:
        warnings.append({"type": "mismatch", "message": "Patient name differs across documents", "fields": ["patient_name", "insured_name"]})

    # DOB consistency
    dobs = [data.get(f) for f in ["date_of_birth", "patient_dob"] if data.get(f)]
    if len(set(dobs)) > 1:
        warnings.append({"type": "mismatch", "message": "Date of birth differs across documents", "fields": ["date_of_birth"]})

    # Policy expiry vs admission date
    policy_end = _parse_date(data.get("policy_end_date"))
    admission = _parse_date(data.get("date_of_admission"))
    if policy_end and admission and admission > policy_end:
        warnings.append({"type": "critical", "message": "Admission date is AFTER policy expiry — TPA will reject", "fields": ["policy_end_date", "date_of_admission"]})

    # Cost total sanity
    total = _parse_number(data.get("sum_total_expected_cost_of_hospitalization", "0"))
    components = sum(_parse_number(data.get(f, "0")) for f in COST_FIELDS)
    if total > 0 and components > 0 and abs(total - components) > total * 0.15:
        warnings.append({"type": "warning", "message": f"Cost total ({total:,}) doesn't match sum of components ({components:,})", "fields": ["sum_total_expected_cost_of_hospitalization"]})

    # Masked Aadhaar
    aadhaar = data.get("id_number", "")
    if "X" in aadhaar.upper() or (aadhaar and len(re.sub(r'\D', '', aadhaar)) < 12):
        warnings.append({"type": "warning", "message": "Aadhaar appears masked — TPA may require full number", "fields": ["id_number"]})

    return warnings
```

---

### V-003 — Expose Warnings in API + UI
| | |
|---|---|
| **Priority** | HIGH |
| **File** | `app.py` — new endpoint; `frontend/index.html` — warning banner |

**New endpoint:**
```python
@app.get("/workflow/{session_id}/warnings")
def workflow_warnings(session_id: str, token: str = Depends(require_auth)):
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)
    from services.validators import cross_check, validate_field
    data = session.get("mapped_data", {})
    warnings = cross_check(data)
    # Also run per-field validation
    for field_id, value in data.items():
        field_errors = validate_field(field_id, value, data)
        for e in field_errors:
            warnings.append({"type": "field_error", "message": e, "fields": [field_id]})
    return ok({"warnings": warnings, "critical_count": sum(1 for w in warnings if w["type"] == "critical")})
```

**Frontend — warning banner (top of Phase 2 form):**
```javascript
async function loadWarnings() {
    const res = await fetch(`${API}/workflow/${currentSessionId}/warnings`, { headers: authHeader() });
    const json = await res.json();
    const banner = document.getElementById('warningBanner');
    if (!json.data.warnings.length) { banner.classList.add('hidden'); return; }
    const criticals = json.data.warnings.filter(w => w.type === 'critical');
    banner.innerHTML = criticals.length
        ? `<b>⚠ ${criticals.length} critical issue(s) found — TPA will likely reject this claim</b>`
        : `<b>⚠ ${json.data.warnings.length} warning(s) — please review before generating</b>`;
    banner.className = criticals.length ? 'alert alert-danger' : 'alert alert-warning';
    // List each warning with a dismiss button
    json.data.warnings.forEach(w => {
        const item = document.createElement('div');
        item.textContent = w.message;
        item.style.marginTop = '4px';
        banner.appendChild(item);
    });
}
// Call after extraction + after each save
```

---

## SECTION 9 — ON-PREMISE PRODUCTION DEPLOYMENT

> **Deployment context:** The system runs on a **dedicated server provided by the hospital IT team**, on the hospital's internal network. No cloud services. Internet access may be limited or proxied. All data stays on-site (DPDP Act compliance through physical data custody).

### D-001 — Application Server Setup (Uvicorn + Gunicorn)
| | |
|---|---|
| **Priority** | CRITICAL |
| **What** | Run the FastAPI app with Gunicorn managing Uvicorn workers for production reliability. |

```bash
# Install
pip install gunicorn uvicorn[standard]

# Start command (add to systemd service)
gunicorn app:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 127.0.0.1:8000 \
  --timeout 120 \
  --keep-alive 5 \
  --log-level info \
  --access-logfile /var/log/preauth/access.log \
  --error-logfile /var/log/preauth/error.log
```

**Workers = 4** is safe for a 4-core server. Adjust to `(2 × cores) + 1`.

---

### D-002 — Nginx Reverse Proxy + TLS
| | |
|---|---|
| **Priority** | CRITICAL |
| **File** | `/etc/nginx/sites-available/preauth` (new file, configured by IT) |
| **Why** | Uvicorn should not be exposed directly. Nginx handles TLS termination, request buffering, static file serving, and protects against slow-client attacks. HTTPS is required to protect PHI (DPDP Act, F-005). |

```nginx
server {
    listen 443 ssl;
    server_name preauth.hospital.local;  # IT team sets up local DNS

    ssl_certificate     /etc/ssl/preauth/cert.pem;   # IT team generates internal CA cert
    ssl_certificate_key /etc/ssl/preauth/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    client_max_body_size 20M;  # Allow up to 20 MB uploads
    proxy_read_timeout 180s;   # Gemini OCR can take up to 2 min for 5 docs

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_read_timeout 3600s;  # WebSocket: keep alive for 1 hour
    }
}

server {
    listen 80;
    server_name preauth.hospital.local;
    return 301 https://$host$request_uri;
}
```

**Action for IT team:**
1. Generate a self-signed cert or issue from internal CA: `openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout key.pem -out cert.pem`
2. Install Nginx, enable the site, install the cert
3. Add `preauth.hospital.local` to hospital DNS or `/etc/hosts` on staff computers

---

### D-003 — Systemd Service for Auto-Start
| | |
|---|---|
| **Priority** | CRITICAL |
| **File** | `/etc/systemd/system/preauth.service` (new file) |
| **Why** | App must restart automatically after server reboot or crash — cannot require manual start. |

```ini
[Unit]
Description=TPA Pre-Authorization System
After=network.target
Wants=network.target

[Service]
Type=exec
User=preauth
Group=preauth
WorkingDirectory=/opt/preauth
EnvironmentFile=/opt/preauth/.env
ExecStart=/opt/preauth/venv/bin/gunicorn app:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 4 \
    --bind 127.0.0.1:8000 \
    --timeout 120 \
    --access-logfile /var/log/preauth/access.log \
    --error-logfile /var/log/preauth/error.log
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=preauth

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable preauth
sudo systemctl start preauth
sudo systemctl status preauth
```

---

### D-004 — Directory Structure + Permissions
| | |
|---|---|
| **Priority** | CRITICAL |
| **Why** | PHI files (sessions, uploads, outputs) must be owned by a dedicated service user and not readable by other OS users. |

```bash
# Create dedicated service user (no login shell)
sudo useradd -r -s /sbin/nologin -d /opt/preauth preauth

# Application directory layout
/opt/preauth/
├── app.py
├── services/
├── frontend/
├── config/
├── templates/
├── analyzed/
├── .env                    # Secrets — mode 600, owned by preauth
├── venv/                   # Python virtual environment
├── uploads/                # Uploaded documents — mode 700
├── sessions/               # Encrypted session files — mode 700
├── output/                 # Generated PDFs — mode 700
└── fonts/                  # NotoSans fonts for Unicode support

/var/log/preauth/            # Log directory — mode 750

# Set ownership
sudo chown -R preauth:preauth /opt/preauth
sudo chmod 600 /opt/preauth/.env
sudo chmod 700 /opt/preauth/uploads /opt/preauth/sessions /opt/preauth/output
sudo mkdir -p /var/log/preauth && sudo chown preauth:preauth /var/log/preauth
```

---

### D-005 — Log Rotation
| | |
|---|---|
| **Priority** | HIGH |
| **File** | `/etc/logrotate.d/preauth` (new file, configured by IT) |
| **Why** | Unrotated logs exhaust disk on a server with no cloud storage. |

```
/var/log/preauth/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl reload preauth
    endscript
}
```

---

### D-006 — .env File Template for On-Premise
| | |
|---|---|
| **Priority** | CRITICAL |
| **File** | `.env.example` in repo root — IT fills in actual values |

```bash
# === SECURITY (MANDATORY — must change before first run) ===
JWT_SECRET=<generate: python -c "import secrets; print(secrets.token_hex(32))">
SESSION_ENCRYPTION_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# === STAFF CREDENTIALS (bcrypt hashes — never plaintext) ===
# Generate: python -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"
STAFF_ADMIN_HASH=$2b$12$...
STAFF_RECEPTION_HASH=$2b$12$...
STAFF_DOCTOR_HASH=$2b$12$...

# === GEMINI API ===
GEMINI_API_KEY=your-api-key-here
GEMINI_MODEL=gemini-2.5-flash
EXTRACTION_MODE=gemini

# === RUNTIME ===
JWT_EXPIRY_HOURS=8
SESSION_EXPIRY_MINUTES=480
DATA_RETENTION_HOURS=24
MAX_UPLOAD_SIZE_MB=8

# === NETWORK (on-premise) ===
APP_BASE_URL=https://preauth.hospital.local
ALLOWED_ORIGINS=https://preauth.hospital.local
ENFORCE_HTTPS=true

# === PATHS (defaults work if app runs from /opt/preauth) ===
# SESSIONS_DIR=sessions
# UPLOADS_DIR=uploads
# OUTPUT_DIR=output
```

---

### D-007 — On-Premise Backup Strategy
| | |
|---|---|
| **Priority** | HIGH |
| **What** | `sessions/`, `uploads/`, `output/` directories contain PHI. Must be backed up to hospital NAS/backup server. |
| **Implementation note (for IT team)** | |

```bash
# Example: daily rsync to NAS (add to cron as root)
# crontab -e
0 2 * * * rsync -az --delete /opt/preauth/sessions/ /mnt/nas/preauth-backup/sessions/
0 2 * * * rsync -az --delete /opt/preauth/output/ /mnt/nas/preauth-backup/output/
```

**Note:** Session files are Fernet-encrypted (F-003/M-024) so backup files are safe even if NAS is compromised.  
**Note:** `uploads/` can be skipped from backup if PHI retention policy allows — original documents are not needed after PDF generation.

---

### D-008 — Internet Access Requirement (Gemini API)
| | |
|---|---|
| **Priority** | CRITICAL — flag to IT team |
| **What** | Gemini Vision is a cloud API. The on-premise server must have outbound internet access to `generativelanguage.googleapis.com:443`. |
| **Action** | Coordinate with hospital IT to whitelist this endpoint in the firewall/proxy. |

```bash
# Test connectivity from the server:
curl -s -o /dev/null -w "%{http_code}" \
  "https://generativelanguage.googleapis.com" \
  -H "x-goog-api-key: ${GEMINI_API_KEY}"
# Expected: 200 or 404 (not a connection error)
```

**Fallback if internet is completely blocked:** Switch `EXTRACTION_MODE=documentai` and configure a Document AI on-premise processor (requires Google Distributed Cloud), OR switch to a locally-hosted OCR model (Tesseract + layout parser — significant accuracy reduction).

---

### D-009 — Structured Application Logging
| | |
|---|---|
| **Priority** | MEDIUM |
| **File** | `app.py` — logging configuration |
| **Why** | `print()` statements and basic `logging` without structure make it impossible to trace a specific patient's request chain through logs. On-premise, logs are the only observability tool. |

```python
import logging
import json as _json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "session_id"):
            log["session_id"] = record.session_id
        if hasattr(record, "mrd"):
            log["mrd"] = record.mrd
        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)
        return _json.dumps(log)

# Apply at startup
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
```

**Usage throughout code:**
```python
logger.info("OCR complete", extra={"session_id": session_id, "mrd": mrd_number, "fields_extracted": len(result)})
```

---

## SECTION 10 — ARCHITECTURE REFACTORING DEBT

> **Gap identified:** These issues exist in ARCHITECTURE_ANALYSIS.md but have no fix plan in earlier sections. They don't block the first deployment but will make the codebase unmaintainable as new TPAs are added.

### AR-001 — Extract Inline Business Logic From `app.py`
| | |
|---|---|
| **Severity** | MEDIUM |
| **Location** | `app.py` lines ~780–850 (schema-label matching, hospital injection, age calculation — all inline inside `workflow_start` endpoint handler) |
| **Fix** | Move to `services/workflow_service.py` |

```python
# New: services/workflow_service.py
class WorkflowService:
    def run_mapping_pipeline(self, raw_ocr: dict, schema_fields: list, schema_name: str) -> dict:
        """Single entry point for the full mapping pipeline."""
        mapped = self.mapping_engine.map_ocr_to_schema(raw_ocr, schema_fields)
        mapped = self.mapping_engine.handle_gender(mapped)
        mapped = self._pass2_label_match(raw_ocr, mapped, schema_fields)
        mapped = self._inject_hospital_data(mapped, schema_fields)
        mapped = self._calculate_age(mapped)
        return mapped
```

---

### AR-002 — Deduplicate Mapping Code in `workflow_start` and `workflow_remap`
| | |
|---|---|
| **Severity** | MEDIUM |
| **Location** | Both endpoints run identical 2-pass mapping logic (~80 lines each) |
| **Fix** | Both call `WorkflowService.run_mapping_pipeline()` from AR-001. Zero duplication. |

---

### AR-003 — Externalize `TPA_TEMPLATE_MAP` to Config File
| | |
|---|---|
| **Severity** | MEDIUM |
| **Location** | `app.py` lines ~190–240 |
| **Fix** | Move to `config/tpa_templates.json`. Load at startup. Adding a new TPA requires only a JSON edit, not a code change + redeploy. |

```json
{
  "medi assist":    { "schema": "Ericson.json",  "template": "Ericson_TPA.pdf"  },
  "ericson":        { "schema": "Ericson.json",  "template": "Ericson_TPA.pdf"  },
  "heritage":       { "schema": "Heritage.json", "template": "Heritage_TPA.pdf" },
  "bajaj allianz":  { "schema": "Bajaj.json",    "template": "Bajaj_TPA.pdf"    }
}
```

---

### AR-004 — Fix Duplicated Gender Normalisation
| | |
|---|---|
| **Severity** | MEDIUM |
| **Location** | `services/mapping_engine.py` `handle_gender()` + `services/form_engine.py` `_handle_gender()` |
| **Fix** | Remove `FormEngine._handle_gender()`. `MappingEngine.handle_gender()` is the single source of truth. Ensure it runs once before `form_engine.populate()`. (Already documented as F-012 — adding here as an architecture tracker.) |

---

### AR-005 — Replace Hardcoded Hospital Data With Config Loader
| | |
|---|---|
| **Severity** | MEDIUM |
| **Location** | `app.py` lines ~120–135 (hospital name, address, registration number hardcoded for "Amrita Hospital") |
| **Fix** | Load from `config/hospital_defaults.json` (created in S-004). This also enables the system to be reused at another hospital without code changes. |

```python
# At startup
with open("config/hospital_defaults.json") as f:
    HOSPITAL_CONFIG = json.load(f)

HOSPITAL_FIELDS = {
    "hospital_name":                HOSPITAL_CONFIG["hospital_name"],
    "hospital_address":             HOSPITAL_CONFIG["hospital_address"],
    "hospital_registration_number": HOSPITAL_CONFIG["hospital_registration_number"],
}
```

---

### AR-006 — Fix Gemini Fallback Mapping Never Being Called
| | |
|---|---|
| **Severity** | LOW |
| **Location** | `services/mapping_engine.py` — `map_with_gemini_fallback()` exists but is never invoked |
| **Fix** | In `WorkflowService.run_mapping_pipeline()`, after pass-2 label matching, check if there are still unmapped OCR keys with meaningful values. If > 5 unmatched keys remain, call `map_with_gemini_fallback()` for those keys only. |

---

### AR-007 — Deduplicate Pass-2 Fuzzy Threshold (65 vs 70)
| | |
|---|---|
| **Severity** | LOW |
| **Location** | `app.py` pass-2 label match uses threshold 65. `services/mapping_engine.py` uses threshold 70 (FUZZY_THRESHOLD). |
| **Fix** | Pass-2 in `app.py` should import and use `FUZZY_THRESHOLD` from `mapping_engine.py`. Single constant, no drift. |

---

## SECTION 11 — ADVANCED FEATURES (POST-STABILISATION)

> Implement only after Sections 6–10 are complete. These provide continuous improvement, not baseline functionality.

### AF-001 — Per-TPA Validation Rules
| | |
|---|---|
| **Priority** | MEDIUM |
| **File** | `config/tpa_rules.json` (new file) |
| **Purpose** | Different TPAs have different mandatory fields and formats. Catches TPA-specific rejections before submission. |

```json
{
  "bajaj_allianz": {
    "required_fields": ["icd_code", "patient_name", "policy_number", "date_of_admission"],
    "notes": "ICD-10 code is mandatory for Bajaj Allianz"
  },
  "ericson_medi_assist": {
    "required_fields": ["patient_name", "policy_number", "plan_type"],
    "notes": "Type of Policy field must be filled"
  },
  "heritage": {
    "required_fields": ["patient_name", "policy_number"],
    "pediatric_requires_attendant": true,
    "notes": "Attendant details required for patients under 12"
  }
}
```

---

### AF-002 — Learning From Staff Corrections
| | |
|---|---|
| **Priority** | LOW |
| **File** | `app.py` — `PUT /workflow/{session_id}/data` handler + `services/audit_log.py` (new) |
| **Purpose** | Track when staff override OCR values. After 100+ corrections, use data to tune prompts. |

```python
# When staff save verified data, compare with OCR values:
def log_corrections(session_id: str, ocr_data: dict, staff_data: dict):
    corrections = []
    for field_id, staff_val in staff_data.items():
        ocr_val = ocr_data.get(field_id, "")
        if ocr_val and staff_val != ocr_val:
            corrections.append({
                "field_id": field_id,
                "ocr_value": ocr_val,
                "staff_value": staff_val,
                "timestamp": datetime.utcnow().isoformat(),
            })
    # Append to corrections log file
    with open("logs/corrections.jsonl", "a") as f:
        for c in corrections:
            f.write(json.dumps(c) + "\n")
```

**Usage:** After accumulating corrections, run analysis to find fields with high correction rates → those fields need prompt improvement.

---

### AF-003 — Multi-Page Document Context Extraction
| | |
|---|---|
| **Priority** | LOW |
| **File** | `services/extractors/gemini_extractor.py` |
| **Purpose** | Multi-page clinical notes currently lose cross-page context. Send all pages in one Gemini call. |

```python
# For documents > 1 page, send all pages together:
def extract_multipage(self, file_paths: list[str], document_type: str) -> ExtractedDocument:
    """Send multiple pages (same document) in one Gemini call."""
    parts = []
    for path in file_paths:
        file_bytes = Path(path).read_bytes()
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime))
    parts.append(types.Part.from_text(text=self._build_gemini_prompt(document_type)))
    # Single API call with all pages
    response = self._call_gemini_multipart(parts)
    return self._parse_response(response, source_file=file_paths[0], document_type=document_type)
```

---

### AF-004 — Medical Abbreviations Config (Externalized)
| | |
|---|---|
| **Priority** | LOW |
| **File** | `config/medical_abbreviations.json` (new file) |
| **Purpose** | The abbreviation glossary in prompts is currently hardcoded in Python strings. Externalizing it allows hospital staff (with guidance) to add hospital-specific abbreviations without a code change. |

```json
{
  "C/o":   "Complaint of",
  "H/o":   "History of",
  "K/c/o": "Known case of",
  "T2DM":  "Type 2 Diabetes Mellitus",
  "HTN":   "Hypertension",
  "LSCS":  "Lower Segment Caesarean Section"
}
```

The prompt builder reads this file and injects the glossary dynamically.
