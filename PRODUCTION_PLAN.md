# Production Plan — TPA Pre-Authorization System

**Created:** 2026-03-02  
**Author:** Copilot + Prince  
**Scope:** Gemini-first extraction, inline suggestions UI, production hardening

---

## Executive Summary

Switch to **Gemini Vision as the primary extraction engine** across all document types, with schema-aware prompts that eliminate the need for fuzzy mapping. Add **inline AI suggestions** in the staff form editor so empty/low-confidence fields get smart auto-complete. Harden the full stack for production deployment.

---

## Current Architecture (As-Is)

```
  Upload → classify doc → hybrid router → { Gemini | Document AI Form Parser }
       → raw key-value pairs (random OCR key names)
       → MappingEngine (exact → alias → fuzzy → Gemini fallback)
       → mapped {field_id: value}
       → Staff reviews in master form (Step 2)
       → FormEngine writes onto PDF coordinates
```

**Key weakness:** Gemini extracts arbitrary key names ("Pt Name", "H/o Present Illness") that the MappingEngine must fuzzy-match to schema field_ids. This indirect pipeline loses accuracy at every hop.

---

## Target Architecture (To-Be)

```
  Upload → classify doc → Gemini Vision (schema-first prompt per doc type)
       → DIRECT {field_id: value, _confidence: {}, _flags: {}}
       → Light validation pass (format, range, cross-check)
       → Staff edits in master form with inline AI suggestions
       → FormEngine writes onto PDF coordinates
```

**Key change:** Give Gemini the exact target field_ids. It returns data pre-mapped. The MappingEngine becomes a safety net, not the primary mapper.

---

## Phase 1 — Schema-First Prompt Engine (Week 1)

### 1.1 Rewrite `_build_gemini_prompt()` → per-doc-type prompt templates

Replace the current generic prompt in `services/extractors/gemini_extractor.py` with specialized prompts.

#### Clinical Notes Prompt

```
ROLE: You are a senior Medical Coder and TPA Pre-Authorization specialist 
at an Indian multi-specialty hospital. You read clinical notes daily.

TASK: Extract structured clinical data from this document image.

CONTEXT: This is a clinical note / OPD slip / doctor's referral letter from 
an Indian hospital. It may contain:
 - Handwritten text in English (sometimes mixed Hindi)
 - Standard Indian medical abbreviations
 - Vitals in metric units (BP in mmHg, Temp in °F or °C, SpO2 in %)

ABBREVIATION GLOSSARY (expand these in your output):
  C/o    → Complaint of
  H/o    → History of  
  K/c/o  → Known case of
  O/e    → On examination
  s/p    → Status post
  R/o    → Rule out
  Rx     → Treatment / Prescription
  Dx     → Diagnosis
  Hx     → History
  Ix     → Investigation
  T2DM   → Type 2 Diabetes Mellitus
  HTN    → Hypertension
  IHD    → Ischemic Heart Disease
  COPD   → Chronic Obstructive Pulmonary Disease
  CKD    → Chronic Kidney Disease
  CAD    → Coronary Artery Disease
  CVA    → Cerebrovascular Accident (Stroke)
  LSCS   → Lower Segment Caesarean Section
  TURP   → Transurethral Resection of Prostate
  TKR    → Total Knee Replacement
  THR    → Total Hip Replacement
  CABG   → Coronary Artery Bypass Grafting
  PCI    → Percutaneous Coronary Intervention
  PTCA   → Percutaneous Transluminal Coronary Angioplasty
  APD    → Acid Peptic Disease
  AKI    → Acute Kidney Injury
  AGE    → Acute Gastroenteritis
  URTI   → Upper Respiratory Tract Infection
  UTI    → Urinary Tract Infection
  SOB    → Shortness of Breath
  DOE    → Dyspnea on Exertion
  BPH    → Benign Prostatic Hyperplasia
  OA     → Osteoarthritis
  RA     → Rheumatoid Arthritis
  DM     → Diabetes Mellitus
  AF     → Atrial Fibrillation

OUTPUT SCHEMA — return these exact keys:
{
  "nature_of_illness_complaint": "<chief complaint + HPI expanded>",
  "relevant_critical_findings": "<vitals + examination findings>",
  "provisional_diagnosis": "<primary diagnosis>",
  "icd_code": "<ICD-10 code if mentioned or inferable>",
  "past_history_chronic_illness": "<past medical/surgical history>",
  "treating_doctor_name": "<doctor name>",
  "treating_doctor_registration_number": "<registration number if visible>",
  "treating_doctor_qualification": "<qualification like MBBS, MS, MD etc>",
  "treating_doctor_speciality": "<speciality>",
  "first_consultation_date": "<DD/MM/YYYY>",
  "date_of_admission": "<DD/MM/YYYY if mentioned>",
  "duration_of_present_ailment": "<e.g. '5 days', '2 months'>",
  "investigation_or_medical_findings": "<lab/imaging findings mentioned>",
  "route_of_drug_administration": "<oral/IV/IM etc>",
  "surgical_name_of_surgery": "<if surgery mentioned>",
  "treatment_type": "<medical/surgical/daycare/maternity>",
  "_raw_vitals": {
    "bp": "<systolic/diastolic>",
    "pulse": "<rate>",
    "spo2": "<percentage>",
    "temp": "<value with unit>",
    "rr": "<respiratory rate>"
  },
  "_medications": ["<med1 + dose>", "<med2 + dose>"],
  "_allergies": "<known allergies or 'NKDA'>"
}

RULES:
1. EXPAND all abbreviations using the glossary above.
2. If a field is not present in the document, OMIT that key entirely.
3. Dates → DD/MM/YYYY format.
4. For _raw_vitals, only include vitals that are explicitly written.
5. If there are multiple diagnoses, separate with " | " (pipe).
6. Return ONLY valid JSON. No markdown fences, no explanations.
```

#### Estimate / Performa Prompt

```
ROLE: You are a hospital billing expert specializing in TPA pre-authorization 
cost estimates for Indian hospitals.

TASK: Extract the itemized cost breakdown from this hospital estimate document.

CONTEXT: This is a cost estimate / proforma for a planned hospitalization.
It typically has a table of line items (room rent, OT charges, etc.) 
and a grand total. Values are in Indian Rupees (₹ or Rs.).

OUTPUT SCHEMA — return these exact keys:
{
  "per_day_room_rent": "<daily room rate>",
  "expected_days_in_hospital": "<number of days>",
  "expected_cost_room_rent": "<total room rent = rate × days>",
  "icu_charges": "<ICU per day or total>",
  "days_in_icu": "<number of ICU days>",
  "ot_charges": "<operation theatre charges>",
  "professional_fees_surgeon": "<surgeon fees>",
  "professional_fees_anesthetist": "<anesthetist fees>",
  "medicines_consumables_cost": "<medicines + consumables>",
  "cost_of_implant": "<implant cost if any>",
  "investigation_diagnostic_cost": "<lab + imaging cost>",
  "other_hospital_charges": "<misc charges>",
  "all_inclusive_package_charges": "<if package deal>",
  "sum_total_expected_cost_hospitalization": "<grand total>",
  "room_type": "<General/Semi-Private/Private/Deluxe/ICU>",
  "surgical_name_of_surgery": "<procedure name if listed>",
  "_line_items": [
    {"item": "<description>", "qty": "<count>", "rate": "<unit rate>", "amount": "<total>"}
  ]
}

RULES:
1. All monetary values as PLAIN NUMBERS (no ₹, Rs., commas). Example: "150000".
2. If a line item total is missing but qty × rate is calculable, compute it.
3. If only a grand total is visible (no breakdown), put it in 
   sum_total_expected_cost_hospitalization and omit the line items.
4. expected_days_in_hospital must be a number.
5. _line_items is optional — include only if a clear table is visible.
6. Return ONLY valid JSON.
```

#### Identity Cards (Aadhaar / PAN / Attendant ID) Prompt

```
ROLE: You are an Indian government ID document reader with expertise in 
Aadhaar, PAN, Voter ID, and Driving License formats.

TASK: Extract identity information from this Indian ID card image.

CONTEXT: This may be:
 - Aadhaar card (UID, 12-digit number, bilingual Hindi+English)
 - PAN card (10-char alphanumeric, INCOME TAX DEPARTMENT header)
 - Voter ID (EPIC number)
 - Driving License

AADHAAR SPECIFICS:
 - Two layouts: old (landscape) and new (portrait letter format)
 - Front side has photo, name, DOB, gender, UID number
 - Back side has address and QR code
 - UID number is 12 digits, often printed as "XXXX XXXX XXXX"
 - VID (Virtual ID) is 16 digits, may or may not be present
 - Ignore Hindi text UNLESS the English equivalent is missing

OUTPUT SCHEMA:
{
  "id_type": "<aadhaar|pan|voter_id|driving_license>",
  "full_name": "<name in English>",
  "father_name": "<father/husband name if visible>",
  "date_of_birth": "<DD/MM/YYYY>",
  "gender": "<Male|Female|Other>",
  "id_number": "<the primary ID number>",
  "vid": "<VID if Aadhaar and visible>",
  "address": "<full address if back side visible>",
  "pin_code": "<6-digit pin from address>"
}

RULES:
1. Aadhaar number MUST be exactly 12 digits (no spaces).
2. PAN MUST be exactly 10 characters (5 alpha + 4 digit + 1 alpha).
3. Dates → DD/MM/YYYY. If only year of birth shown, return "01/01/YYYY".
4. Omit keys with no data.
5. Return ONLY valid JSON.
```

#### Insurance Policy Card Prompt

```
ROLE: You are an Indian health insurance policy document specialist familiar
with all major TPAs (Medi Assist, Health India, Ericson, Paramount, FHPL,
Raksha, Vidal, MDIndia, Heritage, Bajaj Allianz, ICICI Lombard, etc.).

TASK: Extract all policy/member details from this insurance card image.

OUTPUT SCHEMA:
{
  "tpa_insurance_company_name": "<TPA or insurer name>",
  "policy_number": "<policy/certificate number>",
  "insured_member_id": "<member/card ID>",
  "patient_name": "<insured member name>",
  "employee_id": "<employee/staff ID if corporate>",
  "corporate_name": "<employer/corporate if group policy>",
  "sum_insured": "<sum insured amount, plain number>",
  "policy_start_date": "<DD/MM/YYYY>",
  "policy_end_date": "<DD/MM/YYYY>",
  "date_of_birth": "<DD/MM/YYYY>",
  "gender": "<Male|Female>",
  "relationship": "<Self|Spouse|Son|Daughter|Father|Mother>",
  "plan_type": "<plan/product name>",
  "toll_free_phone_number": "<helpline number>",
  "toll_free_fax": "<fax if visible>",
  "tpa_email_id": "<email if visible>"
}

RULES:
1. Sum insured as PLAIN NUMBER (no commas, no ₹).
2. Dates → DD/MM/YYYY.
3. If both TPA and Insurance Company names are visible, put TPA in 
   tpa_insurance_company_name and add "insurance_company": "<name>".
4. Omit keys with no data.
5. Return ONLY valid JSON.
```

### 1.2 Schema injection into prompt

Instead of hardcoded output schemas above, **dynamically inject the target schema field_ids** from the loaded JSON schema file. This way, if a new TPA form is analyzed with different field_ids, the prompt auto-adapts.

**New function signature:**
```python
def _build_gemini_prompt(document_type: str, target_field_ids: list[str] = None) -> str:
```

When `target_field_ids` is provided (from the session's selected schema), append:
```
IMPORTANT: Map your output keys to these EXACT field IDs where applicable:
{json.dumps(target_field_ids)}
Use these as your output keys instead of free-form names.
```

**Where to inject:** In `app.py` → `workflow_start()`, pass the selected schema's field_ids through to the extractor.

### 1.3 Confidence scoring from Gemini

Ask Gemini to return a `_confidence` object alongside the data:

```
Additionally, return a "_confidence" object where keys are field_ids and 
values are your confidence (0.0 to 1.0) that the extraction is correct.
Mark < 0.5 for handwritten/illegible text, 0.5-0.8 for partially visible, 
0.8-1.0 for clearly printed text.

Example:
{
  "patient_name": "Rajesh Kumar",
  "provisional_diagnosis": "K/c/o T2DM with HTN presenting with chest pain",
  "_confidence": {
    "patient_name": 0.95,
    "provisional_diagnosis": 0.70
  }
}
```

**Impact:** The UI can highlight low-confidence fields in amber/red for staff review.

### 1.4 Update `ExtractedField` to use Gemini's confidence

In `gemini_extractor.py`, replace the hardcoded `confidence=0.85`:

```python
# After parsing
confidence_map = raw_dict.pop("_confidence", {})
for key, value in raw_dict.items():
    if key.startswith("_"):  # skip meta-fields like _raw_vitals, _line_items
        continue
    conf = float(confidence_map.get(key, 0.75))
    fields.append(ExtractedField(
        key=key,
        value=str(value),
        confidence=conf,
        confidence_level=ExtractionConfidence.from_score(conf),
        ...
    ))
```

---

## Phase 2 — Inline AI Suggestions in the Editor (Week 2)

### 2.1 New API endpoint: `POST /ai/suggest`

Add to `app.py`:

```python
@app.post("/ai/suggest")
async def ai_suggest_field(
    session_id: str = Form(...),
    field_id: str = Form(...),
    current_value: str = Form(""),
    context_fields: str = Form("{}"),  # JSON string of nearby filled fields
):
    """
    AI-powered inline suggestion for a single form field.
    Uses surrounding context (other filled fields) to infer the best value.
    """
```

**How it works:**
1. Staff clicks an empty/low-confidence field → frontend calls `/ai/suggest`
2. Backend sends a focused Gemini prompt:
   ```
   Given this patient context:
   - Patient Name: Rajesh Kumar
   - Diagnosis: Type 2 Diabetes Mellitus with Hypertension
   - Date of Admission: 15/03/2026
   
   Suggest the most likely value for field: "expected_days_in_hospital"
   Also suggest for: "treatment_type"
   
   Respond with JSON: {"field_id": "suggested_value", ...}
   ```
3. Returns suggestions with confidence scores
4. Staff sees it as a ghost-text suggestion (like GitHub Copilot inline)

### 2.2 Batch suggest for all empty fields

```python
@app.post("/ai/suggest-batch")
async def ai_suggest_batch(
    session_id: str = Form(...),
):
    """Suggest values for ALL empty fields based on the filled ones."""
```

This is called once after OCR mapping, to fill in fields that weren't extracted but can be **inferred**:
- `treatment_type` = "Surgical" (when `surgical_name_of_surgery` is filled)
- `expected_days_in_hospital` = "3" (when diagnosis is "Appendicitis" — Gemini knows typical LOS)
- `room_type` = "Semi-Private" (default for most corporate policies)
- `icd_code` = "K35.80" (from diagnosis "Acute Appendicitis")

### 2.3 Frontend: Inline suggestion UI

**Changes to `frontend/index.html`:**

#### A. Suggestion ghost text in input fields
```html
<div class="field-group suggestion-enabled">
  <label>Expected Days in Hospital</label>
  <div class="input-wrapper">
    <input type="text" id="f_expected_days" value="" placeholder="Expected Days">
    <span class="ai-suggestion" id="sug_expected_days" 
          onclick="acceptSuggestion('expected_days', this)">
      3 days ✨
    </span>
  </div>
</div>
```

#### B. Confidence indicator per field
```css
.field-group input.confidence-high   { border-left: 3px solid #2e7d32; } /* green */
.field-group input.confidence-medium { border-left: 3px solid #f57f17; } /* amber */
.field-group input.confidence-low    { border-left: 3px solid #c62828; } /* red */
.field-group input.ai-suggested      { border-left: 3px solid #7c4dff; } /* purple */
```

#### C. "Auto-fill remaining" button
```html
<button class="btn btn-accent" onclick="suggestAllEmpty()">
  ✨ AI Auto-fill Empty Fields
</button>
```

#### D. Suggestion acceptance flow
```javascript
async function suggestAllEmpty() {
  showLoading('AI is analyzing context...');
  const res = await fetch(API + '/ai/suggest-batch', {
    method: 'POST',
    body: new FormData(/* session_id */)
  });
  const json = await res.json();
  
  // Show suggestions as ghost text (not auto-accepted)
  for (const [fieldId, suggestion] of Object.entries(json.data.suggestions)) {
    const input = document.getElementById('f_' + fieldId);
    if (!input || input.value.trim()) continue; // skip already-filled
    
    const sugSpan = document.createElement('span');
    sugSpan.className = 'ai-suggestion';
    sugSpan.textContent = suggestion.value + ' ✨';
    sugSpan.title = `AI confidence: ${(suggestion.confidence * 100).toFixed(0)}%`;
    sugSpan.onclick = () => acceptSuggestion(fieldId, suggestion.value);
    input.parentElement.appendChild(sugSpan);
  }
  hideLoading();
}

function acceptSuggestion(fieldId, value) {
  const input = document.getElementById('f_' + fieldId);
  input.value = value;
  input.classList.add('ai-suggested');
  updateFieldValue(fieldId, value);
  // Remove the suggestion ghost
  const sug = input.parentElement.querySelector('.ai-suggestion');
  if (sug) sug.remove();
}
```

### 2.4 Smart defaults from hospital knowledge

Create `config/hospital_defaults.json`:
```json
{
  "hospital_name": "Amrita Hospital",
  "hospital_address": "Sector 88, Faridabad, Haryana",
  "hospital_registration_number": "HR/FAR/2023/001234",
  "hospital_phone": "0129-XXXXXXX",
  "hospital_email": "preauth@amritahospital.org",
  
  "common_diagnoses": {
    "Appendicitis": { "icd": "K35.80", "typical_los": 3, "treatment": "Surgical" },
    "Cholecystitis": { "icd": "K81.0", "typical_los": 3, "treatment": "Surgical" },
    "Dengue Fever": { "icd": "A90", "typical_los": 5, "treatment": "Medical" },
    "Pneumonia": { "icd": "J18.9", "typical_los": 5, "treatment": "Medical" },
    "AMI": { "icd": "I21.9", "typical_los": 7, "treatment": "Surgical" },
    "TKR": { "icd": "M17.11", "typical_los": 7, "treatment": "Surgical" },
    "LSCS": { "icd": "O82", "typical_los": 5, "treatment": "Surgical" },
    "Cataract": { "icd": "H25.9", "typical_los": 1, "treatment": "Daycare" }
  },
  
  "room_rates": {
    "General": 2500,
    "Semi-Private": 4500,
    "Private": 8000,
    "Deluxe": 12000,
    "ICU": 15000
  }
}
```

Gemini can reference this to suggest realistic cost estimates when only diagnosis + room type are known.

---

## Phase 3 — Validation & Cross-Check Layer (Week 2-3)

### 3.1 Post-extraction validation rules

Create `services/validators.py`:

```python
VALIDATION_RULES = {
    "patient_name": {
        "min_length": 2,
        "max_length": 100,
        "pattern": r"^[A-Za-z\s\.]+$",
        "error": "Name should contain only letters"
    },
    "date_of_admission": {
        "format": "DD/MM/YYYY",
        "must_be_past_or_today": True,
        "must_be_after": "date_of_birth",
    },
    "policy_end_date": {
        "format": "DD/MM/YYYY",
        "must_be_future_or_today": True,
        "error": "Policy appears expired"
    },
    "sum_total_expected_cost_hospitalization": {
        "type": "number",
        "min": 1000,
        "max": 50000000,
        "cross_check": "sum of individual cost fields"
    },
    "expected_days_in_hospital": {
        "type": "integer",
        "min": 1,
        "max": 365,
    },
    "policy_number": {
        "min_length": 5,
    },
    "id_number": {
        "aadhaar_pattern": r"^\d{12}$",
        "pan_pattern": r"^[A-Z]{5}\d{4}[A-Z]$",
    }
}
```

### 3.2 Cross-document consistency checks

After all documents are extracted, run:

```python
def cross_check(extracted_data: dict) -> list[Warning]:
    warnings = []
    
    # Patient name consistency across documents
    names = [extracted_data.get(f) for f in ["patient_name", "insured_name"] if extracted_data.get(f)]
    if len(set(names)) > 1:
        warnings.append("Patient name mismatch across documents")
    
    # Date of birth consistency
    dobs = [extracted_data.get(f) for f in ["date_of_birth", "patient_dob"] if extracted_data.get(f)]
    if len(set(dobs)) > 1:
        warnings.append("Date of birth mismatch across documents")
    
    # Cost sanity
    total = parse_number(extracted_data.get("sum_total_expected_cost_hospitalization", "0"))
    components = sum(parse_number(extracted_data.get(f, "0")) for f in COST_FIELDS)
    if total > 0 and components > 0 and abs(total - components) > total * 0.1:
        warnings.append(f"Cost total ({total}) doesn't match sum of components ({components})")
    
    # Policy validity
    policy_end = parse_date(extracted_data.get("policy_end_date"))
    admission = parse_date(extracted_data.get("date_of_admission"))
    if policy_end and admission and admission > policy_end:
        warnings.append("Admission date is after policy expiry!")
    
    return warnings
```

### 3.3 Expose warnings in API + UI

- `GET /workflow/{session_id}/warnings` → returns validation warnings
- UI shows a yellow alert banner at top of form editor with actionable warnings
- Staff can dismiss individual warnings or fix the flagged fields

---

## Phase 4 — Production Hardening (Week 3-4)

### 4.1 Database migration (SQLite → PostgreSQL)

Replace in-memory dicts with persistent storage:

| Current | Production |
|---|---|
| `_sessions` dict | `sessions` table (PostgreSQL) |
| `_populated_forms` dict | `forms` table |
| `_ocr_results` dict | `ocr_results` table |
| JSON files in `sessions/` | DB rows with JSONB columns |

**Schema:**
```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    mrd_number VARCHAR(50),
    patient_name VARCHAR(200),
    status VARCHAR(20) DEFAULT 'active',   -- active, completed, expired
    mapped_data JSONB,
    ocr_raw JSONB,
    warnings JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ  -- DATA_RETENTION_HOURS from now
);

CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    action VARCHAR(50),      -- 'field_edited', 'suggestion_accepted', 'form_generated'
    field_id VARCHAR(100),
    old_value TEXT,
    new_value TEXT,
    actor VARCHAR(100),      -- staff username from JWT
    timestamp TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.2 Authentication hardening

- Replace `JWT_SECRET = "dev-secret-change-in-production"` with env-only secret
- Add role-based access: `staff`, `supervisor`, `admin`
- Supervisor can review/approve pre-auth before submission
- Audit log captures every field edit with username + timestamp

### 4.3 Rate limiting & error handling

```python
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)

@app.post("/ai/suggest")
@limiter.limit("30/minute")   # prevent abuse of Gemini API
async def ai_suggest_field(...):
```

### 4.4 Deployment architecture

```
                    ┌─────────────────┐
  Internet ────────▶│  Nginx / Caddy  │ (SSL, rate limit, static files)
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Gunicorn + Uvicorn│  (2-4 workers)
                    │   FastAPI app    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐
     │  PostgreSQL   │ │  Redis   │ │ File Store  │
     │  (sessions,   │ │ (cache,  │ │ (uploads,   │
     │   audit log)  │ │  queues) │ │  output)    │
     └───────────────┘ └──────────┘ └─────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐
     │  Vertex AI    │ │Document  │ │   HIS API   │
     │  Gemini 2.5   │ │  AI      │ │   (future)  │
     │  Flash        │ │(fallback)│ │             │
     └───────────────┘ └──────────┘ └─────────────┘
```

### 4.5 Caching layer (Redis)

- Cache identical document extractions (hash of file bytes → result)
- Cache Gemini suggestions for common diagnoses (e.g., "Appendicitis" → standard fields)
- Session data in Redis for multi-worker consistency
- TTL = DATA_RETENTION_HOURS for PHI compliance

### 4.6 Monitoring & observability

- **Structured logging** (JSON format) → ELK / CloudWatch
- **Metrics:** extraction_time_ms, confidence_avg, unmatched_key_count, suggestion_acceptance_rate
- **Alerts:** Gemini API errors > 5/min, avg confidence < 0.5, PHI cleanup failures

---

## Phase 5 — Advanced Features (Week 4+)

### 5.1 Learning from staff corrections

Track what staff changes after OCR + AI suggestion:

```python
# In updateFieldValue / audit_log:
{
    "field_id": "patient_name",
    "ocr_value": "Rajesh Kumer",      # what Gemini extracted
    "staff_value": "Rajesh Kumar",     # what staff corrected to
    "edit_type": "spelling_correction"
}
```

After 100+ corrections, use this data to:
1. Add common misspellings to the prompt ("Note: OCR often reads 'Kumar' as 'Kumer'")
2. Build a hospital-specific dictionary for doctor names, department names, etc.
3. Track which fields need the most corrections → prioritize prompt tuning

### 5.2 Multi-page context extraction

For documents > 1 page, current code extracts each page independently. Upgrade to:
- Send ALL pages of a single document in one Gemini call (Gemini supports multi-image)
- Explicitly instruct: "Pages 1-3 are a single clinical note. Extract one unified JSON."

### 5.3 TPA-specific form logic

Different TPAs have different rules:
- **Bajaj Allianz:** Requires ICD-10 code mandatory
- **Ericson (Medi Assist):** Needs "Type of Policy" explicitly
- **Heritage:** Requires attendant details for pediatric cases

Create `config/tpa_rules.json` with per-TPA validation and auto-fill rules.

### 5.4 Real HIS integration

Replace `HISService` stub with actual hospital HIS API:
- Pull patient demographics, policy details, past admission history
- Pre-populate 30-40% of fields before any document is uploaded
- Cross-validate OCR results against HIS master data

---

## Implementation Priority & Timeline

| Week | Phase | Deliverable | Impact |
|------|-------|------------|--------|
| 1 | Phase 1 | Schema-first prompts + confidence scoring | **+40% extraction accuracy** |
| 1 | Phase 1 | Dynamic schema injection | Auto-adapts to any TPA form |
| 2 | Phase 2 | `/ai/suggest` + `/ai/suggest-batch` APIs | Staff productivity boost |
| 2 | Phase 2 | Inline suggestion UI (ghost text + accept) | **Core UX differentiator** |
| 2 | Phase 3 | Validation + cross-document checks | Catch errors before submission |
| 3 | Phase 3 | Warning banners in UI | Staff sees issues instantly |
| 3 | Phase 4 | PostgreSQL + audit log | Production data persistence |
| 3 | Phase 4 | Auth hardening + rate limiting | Security compliance |
| 4 | Phase 4 | Docker + deployment config | Production deployment |
| 4+ | Phase 5 | Learning from corrections, HIS integration | Continuous improvement |

---

## Files That Will Be Modified/Created

### Modified
| File | Changes |
|---|---|
| `services/extractors/gemini_extractor.py` | Rewrite prompts, confidence parsing, schema injection |
| `services/mapping_engine.py` | Becomes safety-net only (Gemini does primary mapping) |
| `app.py` | New `/ai/suggest`, `/ai/suggest-batch` endpoints, validation integration |
| `frontend/index.html` | Suggestion UI, confidence indicators, warning banners, auto-fill button |
| `services/extractors/hybrid_extractor.py` | Pass target schema through to Gemini |
| `config/field_mapping.json` | Add `gemini_description` to all fields (used in prompt) |

### New Files
| File | Purpose |
|---|---|
| `services/validators.py` | Post-extraction validation + cross-document checks |
| `services/suggestion_engine.py` | AI suggestion logic (context assembly, Gemini call, caching) |
| `config/hospital_defaults.json` | Hospital info, common diagnoses, room rates |
| `config/tpa_rules.json` | Per-TPA validation rules and auto-fill logic |
| `config/medical_abbreviations.json` | Externalized abbreviation glossary (updateable without code change) |

---

## Success Metrics

| Metric | Current | Target |
|---|---|---|
| Fields auto-filled correctly (no staff edit needed) | ~45% | **75%+** |
| Unmatched OCR keys per session | ~8-10 | **< 3** |
| Average extraction confidence | 0.85 (hardcoded) | **0.82 real** (but accurate) |
| Time for staff to complete form | ~8-10 min | **< 4 min** |
| Suggestion acceptance rate | N/A (no suggestions) | **60%+** |
| Cost total cross-check pass rate | N/A | **95%** |
| Privacy compliance | Partial | **Full DPDP Act** |

---

## Quick Start — What to Build First

**Highest ROI, do this first:**
1. Rewrite the 4 document-type prompts (Phase 1.1) — biggest accuracy gain
2. Add confidence parsing (Phase 1.4) — enables everything else  
3. Add `/ai/suggest-batch` endpoint (Phase 2.2) — fills the gaps
4. Add "✨ Auto-fill" button + ghost-text UI (Phase 2.3) — staff sees the value immediately

These 4 items can be done in **3-4 days** and will transform accuracy from ~45% to ~70%+ auto-fill.
