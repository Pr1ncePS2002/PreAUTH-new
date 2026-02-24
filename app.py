#!/usr/bin/env python3
"""
FastAPI Backend — TPA Pre-Authorization Web Application.

Endpoints:
  POST   /auth/login              → Staff authentication (JWT)
  GET    /patient/{mrd}           → Demographics + docs from HIS
  GET    /patient/search          → Search patients
  POST   /documents/upload        → Upload pre-auth documents
  POST   /documents/ocr           → Run Document AI on uploaded docs
  POST   /forms/populate          → Map + populate TPA form
  GET    /forms/preview/{form_id} → Return populated PDF
  GET    /forms/templates         → List available templates
  GET    /forms/schemas           → List analyzed schemas
  POST   /forms/submit            → Final submission
  GET    /mapping/review          → List unconfirmed field mappings
  POST   /mapping/confirm         → Confirm/override a mapping

Run:
    cd "PreAUTH new"
    .\\venv\\Scripts\\python.exe -m uvicorn app:app --reload --port 8001
"""

import json
import os
import uuid
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Query, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services.mapping_engine import MappingEngine
from services.ocr_service import OCRService
from services.form_engine import FormEngine
from services.his_service import HISService

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 8

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App & middleware
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TPA Pre-Authorization System",
    description="Automated TPA form filling for hospital pre-authorization",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Service instances
# ---------------------------------------------------------------------------
mapping_engine = MappingEngine()
ocr_service = OCRService(mode="gemini")
form_engine = FormEngine()
his_service = HISService()  # Stub mode

# In-memory stores (replace with DB in production)
_populated_forms: dict[str, dict] = {}  # form_id -> {path, data, template, schema, created}
_ocr_results: dict[str, dict] = {}     # result_id -> {file, type, data}
_sessions: dict[str, dict] = {}        # session_id -> full workflow state


# ---------------------------------------------------------------------------
# TPA template auto-detection map
# ---------------------------------------------------------------------------
TPA_TEMPLATE_MAP = {
    "ericson": "Ericson TPA Preauth.pdf",
    "bajaj allianz": "BAJAJ ALLIANZ TPA PREAUTH FORM.pdf",
    "care health": "Care Health  PRE AUTH.pdf",
    "chola ms": "Chola-MS-Pre-Authorisation-Form.pdf",
    "cholamandalam": "Chola-MS-Pre-Authorisation-Form.pdf",
    "east west": "East West TPA.pdf",
    "fhpl": "FHPL TPA.pdf",
    "future generali": "FUTURE GENERLI pre auth.pdf",
    "genins": "Genins TPA Pre-Auth form.pdf",
    "go digit": "GO DIGIT PREAUTH.pdf",
    "digit": "GO DIGIT PREAUTH.pdf",
    "good health": "GOOD HEALTH TPA PREAUTH INS. FOAM.pdf",
    "hdfc": "HDFC.pdf",
    "hdfc ergo": "HDFC.pdf",
    "hdgc": "HDGC CLAIM FORM A & B PART.pdf",
    "health india": "Health India Pre-Auth.pdf",
    "health insurance": "Health Insurance.pdf",
    "heritage health": "Heritage-Health-Pre-Auth-Form.pdf",
    "icici lombard": "ICICI LOMBARD.pdf",
    "icici": "ICICI LOMBARD.pdf",
    "liberty": "LIBERTY  Request Form.pdf",
    "md india": "MD-India-Pre-Auth.pdf",
    "medsave": "Med-Save Pre-Auth.pdf",
    "med save": "Med-Save Pre-Auth.pdf",
    "medi assist": "Medi-assist TPA.pdf",
    "mediassist": "Medi-assist TPA.pdf",
    "niva bupa": "NIVA-BUPA.pdf",
    "paramount": "Paramount TPA.pdf",
    "park mediclaim": "PARK MEDICLAIM.pdf",
    "raksha": "RAKSHA TPA PREAUTH.pdf",
    "reliance": "Reliance-Pre-Authorization-Request-Form.pdf",
    "safeway": "Safeway TPA.pdf",
    "sbi": "SBI PRE AUTH.pdf",
    "star health": "STAR PRE AUTH FORM.pdf",
    "star health old": "STAR HEALTH  OLD CLAIM FORM.pdf",
    "tata aig": "TAGIC PREAUTH REQUEST FORM_V2.pdf",
    "tagic": "TAGIC PREAUTH REQUEST FORM_V2.pdf",
    "universal sompo": "UNIVERSAL SOMPOO  PREAUTH FORM.pdf",
    "vidal": "Vidal TPA.pdf",
    "aditya birla": "Aditya Birla.pdf",
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str

class PopulateRequest(BaseModel):
    template_name: str
    schema_name: str
    data: dict

class MappingConfirmRequest(BaseModel):
    ocr_key: str
    field_id: str

class SubmitRequest(BaseModel):
    form_id: str
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
STAFF_USERS = {
    "admin": "admin123",
    "reception": "reception123",
    "doctor": "doctor123",
}

def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(authorization: str = Query(None, alias="token")) -> dict:
    """Simple token auth via query param or header. Expand for production."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Token required")
    token = authorization.replace("Bearer ", "")
    return verify_token(token)


# ---------------------------------------------------------------------------
# Helper: standard response
# ---------------------------------------------------------------------------
def ok(data=None, message: str = ""):
    return {"success": True, "data": data, "error": ""}

def err(message: str, status: int = 400):
    raise HTTPException(status_code=status, detail={"success": False, "data": None, "error": message})


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------
@app.post("/auth/login")
def login(req: LoginRequest):
    """Authenticate staff and return JWT token."""
    if req.username not in STAFF_USERS or STAFF_USERS[req.username] != req.password:
        err("Invalid credentials", 401)
    token = create_token(req.username)
    return ok({"token": token, "username": req.username, "expires_in": JWT_EXPIRY_HOURS * 3600})


# ---------------------------------------------------------------------------
# PATIENT (HIS)
# ---------------------------------------------------------------------------
@app.get("/patient/search")
def search_patients(q: str = Query(..., min_length=1)):
    """Search patients by name or MRD number."""
    results = his_service.search_patients(q)
    return ok(results)

@app.get("/patient/{mrd}")
def get_patient(mrd: str):
    """Get patient demographics and documents from HIS."""
    patient = his_service.get_patient(mrd)
    if not patient:
        err(f"Patient {mrd} not found", 404)

    documents = his_service.get_documents(mrd)
    admission = his_service.get_admission(mrd)

    return ok({
        "patient": patient,
        "documents": documents,
        "admission": admission,
    })

@app.get("/patient/{mrd}/preauth-data")
def get_preauth_data(mrd: str):
    """Build pre-auth data from HIS demographics + admission."""
    data = his_service.build_preauth_data(mrd)
    if not data:
        err(f"Patient {mrd} not found", 404)
    return ok(data)


# ---------------------------------------------------------------------------
# DOCUMENTS
# ---------------------------------------------------------------------------
@app.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form("generic"),
    mrd_number: str = Form(""),
):
    """Upload a pre-auth document (Aadhaar, PAN, policy card, etc.)."""
    # Save file
    file_id = str(uuid.uuid4())[:8]
    safe_name = f"{file_id}_{file.filename}"
    save_path = UPLOADS_DIR / safe_name

    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    logger.info("Uploaded %s (%s) -> %s", file.filename, document_type, save_path)

    return ok({
        "file_id": file_id,
        "filename": file.filename,
        "saved_as": safe_name,
        "path": str(save_path),
        "document_type": document_type,
        "mrd_number": mrd_number,
    })


@app.post("/documents/ocr")
def run_ocr(
    file_path: str = Form(...),
    document_type: str = Form("generic"),
):
    """Run OCR (Gemini Vision) on an uploaded document and extract key-value pairs."""
    path = Path(file_path)
    if not path.exists():
        err(f"File not found: {file_path}", 404)

    try:
        extracted = ocr_service.extract(str(path), document_type)
    except Exception as e:
        logger.error("OCR failed: %s", e)
        err(f"OCR extraction failed: {str(e)}", 500)

    result_id = str(uuid.uuid4())[:8]
    _ocr_results[result_id] = {
        "file": str(path),
        "type": document_type,
        "data": extracted,
    }

    return ok({
        "result_id": result_id,
        "document_type": document_type,
        "extracted_fields": len(extracted),
        "data": extracted,
    })


@app.post("/documents/ocr-and-map")
def ocr_and_map(
    file_path: str = Form(...),
    document_type: str = Form("generic"),
    schema_name: str = Form("Ericson TPA Preauth.json"),
):
    """
    Combined OCR + mapping: extract from document, then map to schema field IDs.
    """
    path = Path(file_path)
    if not path.exists():
        err(f"File not found: {file_path}", 404)

    # OCR
    try:
        extracted = ocr_service.extract(str(path), document_type)
    except Exception as e:
        err(f"OCR failed: {str(e)}", 500)

    # Load schema field IDs
    schema_path = BASE_DIR / "analyzed" / schema_name
    if not schema_path.exists():
        err(f"Schema not found: {schema_name}", 404)

    with open(schema_path) as f:
        schema = json.load(f)
    schema_fields = [field["field_id"] for field in schema["fields"]]

    # Map
    mapped = mapping_engine.map_ocr_to_schema(extracted, schema_fields, document_type)
    mapped = mapping_engine.handle_gender(mapped)

    return ok({
        "raw_ocr": extracted,
        "mapped_data": mapped,
        "ocr_fields": len(extracted),
        "mapped_fields": len(mapped),
    })


# ---------------------------------------------------------------------------
# FORMS
# ---------------------------------------------------------------------------
@app.get("/forms/templates")
def list_templates():
    """List all available TPA form templates."""
    return ok(form_engine.list_templates())

@app.get("/forms/schemas")
def list_schemas():
    """List all analyzed form schemas."""
    return ok(form_engine.list_schemas())

@app.get("/forms/schema/{schema_name}/fields")
def get_schema_fields(schema_name: str):
    """Get all field definitions from a specific schema."""
    schema_path = BASE_DIR / "analyzed" / schema_name
    if not schema_path.exists():
        err(f"Schema not found: {schema_name}", 404)
    fields = form_engine.get_schema_fields(str(schema_path))
    return ok(fields)


@app.post("/forms/populate")
def populate_form(req: PopulateRequest):
    """Populate a TPA form with provided data."""
    template_path = BASE_DIR / "templates" / req.template_name
    schema_path = BASE_DIR / "analyzed" / req.schema_name

    if not template_path.exists():
        err(f"Template not found: {req.template_name}", 404)
    if not schema_path.exists():
        err(f"Schema not found: {req.schema_name}", 404)

    form_id = str(uuid.uuid4())[:8]
    output_filename = f"{template_path.stem}_{form_id}_filled.pdf"
    output_path = OUTPUT_DIR / output_filename

    try:
        result_path = form_engine.populate(
            str(template_path),
            str(schema_path),
            req.data,
            str(output_path),
        )
    except Exception as e:
        logger.error("Form population failed: %s", e)
        err(f"Form population failed: {str(e)}", 500)

    _populated_forms[form_id] = {
        "path": result_path,
        "filename": output_filename,
        "template": req.template_name,
        "schema": req.schema_name,
        "created": datetime.utcnow().isoformat(),
        "data_keys": list(req.data.keys()),
    }

    return ok({
        "form_id": form_id,
        "filename": output_filename,
        "preview_url": f"/forms/preview/{form_id}",
    })


@app.get("/forms/preview/{form_id}")
def preview_form(form_id: str):
    """Download / preview a populated PDF."""
    if form_id not in _populated_forms:
        err(f"Form {form_id} not found", 404)

    form_info = _populated_forms[form_id]
    file_path = Path(form_info["path"])
    if not file_path.exists():
        err("Populated PDF file missing", 500)

    return FileResponse(
        str(file_path),
        media_type="application/pdf",
        filename=form_info["filename"],
    )


@app.post("/forms/populate-from-his")
def populate_from_his(
    mrd_number: str = Form(...),
    template_name: str = Form("Ericson TPA Preauth.pdf"),
    schema_name: str = Form("Ericson TPA Preauth.json"),
):
    """
    End-to-end: Fetch patient data from HIS → populate form.
    """
    # Get data from HIS
    data = his_service.build_preauth_data(mrd_number)
    if not data:
        err(f"Patient {mrd_number} not found in HIS", 404)

    # Populate
    req = PopulateRequest(
        template_name=template_name,
        schema_name=schema_name,
        data=data,
    )
    return populate_form(req)


@app.post("/forms/submit")
def submit_form(req: SubmitRequest):
    """Mark a form as submitted (placeholder for TPA submission logic)."""
    if req.form_id not in _populated_forms:
        err(f"Form {req.form_id} not found", 404)

    _populated_forms[req.form_id]["status"] = "submitted"
    _populated_forms[req.form_id]["submitted_at"] = datetime.utcnow().isoformat()
    _populated_forms[req.form_id]["notes"] = req.notes

    logger.info("Form %s submitted", req.form_id)
    return ok({"form_id": req.form_id, "status": "submitted"})


# ---------------------------------------------------------------------------
# MAPPING
# ---------------------------------------------------------------------------
@app.get("/mapping/review")
def review_mappings():
    """List unconfirmed/unmatched field mappings from recent OCR runs."""
    report = mapping_engine.get_mapping_report()
    return ok(report)

@app.post("/mapping/confirm")
def confirm_mapping(req: MappingConfirmRequest):
    """Manually confirm or override a field mapping."""
    mapping_engine.confirm_mapping(req.ocr_key, req.field_id)
    return ok({"ocr_key": req.ocr_key, "field_id": req.field_id, "status": "confirmed"})

@app.get("/mapping/fields")
def list_mapping_fields():
    """List all fields in field_mapping.json with their aliases."""
    return ok(mapping_engine.field_mapping)


# ---------------------------------------------------------------------------
# TPA TEMPLATE DETECTION
# ---------------------------------------------------------------------------
def detect_tpa_template(insurance_company: str) -> Optional[dict]:
    """Find matching TPA template from insurance company name."""
    if not insurance_company:
        return None
    query = insurance_company.lower().strip()
    # Direct substring match
    for key, filename in TPA_TEMPLATE_MAP.items():
        if key in query or query in key:
            schema_name = Path(filename).stem + ".json"
            schema_path = BASE_DIR / "analyzed" / schema_name
            return {
                "template_name": filename,
                "schema_name": schema_name if schema_path.exists() else None,
                "has_schema": schema_path.exists(),
                "match_key": key,
            }
    # Fuzzy fallback
    from rapidfuzz import fuzz
    best_score, best_key = 0, None
    for key in TPA_TEMPLATE_MAP:
        score = fuzz.partial_ratio(query, key)
        if score > best_score:
            best_score, best_key = score, key
    if best_score >= 60 and best_key:
        filename = TPA_TEMPLATE_MAP[best_key]
        schema_name = Path(filename).stem + ".json"
        schema_path = BASE_DIR / "analyzed" / schema_name
        return {
            "template_name": filename,
            "schema_name": schema_name if schema_path.exists() else None,
            "has_schema": schema_path.exists(),
            "match_key": best_key,
            "confidence": best_score,
        }
    return None

@app.get("/tpa/detect")
def detect_tpa(insurance_company: str = Query(...)):
    """Auto-detect TPA template from insurance company name."""
    result = detect_tpa_template(insurance_company)
    if not result:
        return ok({"detected": False, "templates": form_engine.list_templates()})
    return ok({"detected": True, **result})


# ---------------------------------------------------------------------------
# WORKFLOW — Upload → OCR → Master Form → Verify → Generate PDF
# ---------------------------------------------------------------------------
@app.post("/workflow/start")
async def workflow_start(
    files: List[UploadFile] = File(...),
    document_types: str = Form(""),  # comma-separated types matching file order
):
    """
    Step 1: Upload multiple documents and run OCR on each.
    Returns a session with all extracted data merged into a master form dict.
    """
    session_id = str(uuid.uuid4())[:12]
    type_list = [t.strip() for t in document_types.split(",") if t.strip()] if document_types else []

    uploaded = []
    all_extracted: dict = {}
    raw_extractions: list[dict] = []

    for i, file in enumerate(files):
        doc_type = type_list[i] if i < len(type_list) else "generic"

        # Save file
        file_id = str(uuid.uuid4())[:8]
        safe_name = f"{file_id}_{file.filename}"
        save_path = UPLOADS_DIR / safe_name

        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)

        uploaded.append({
            "file_id": file_id,
            "filename": file.filename,
            "saved_as": safe_name,
            "path": str(save_path),
            "document_type": doc_type,
            "size": len(content),
        })

        # Run OCR
        try:
            extracted = ocr_service.extract(str(save_path), doc_type)
            raw_extractions.append({
                "file": file.filename,
                "type": doc_type,
                "fields": extracted,
            })
            # Merge into master dict (later values don't overwrite earlier)
            for k, v in extracted.items():
                if k not in all_extracted:
                    all_extracted[k] = v
        except Exception as e:
            logger.error("OCR failed for %s: %s", file.filename, e)
            raw_extractions.append({
                "file": file.filename,
                "type": doc_type,
                "error": str(e),
            })

    # Try to detect TPA from insurance company name in OCR results
    insurance_company = (
        all_extracted.get("Insurance Company", "") or
        all_extracted.get("TPA Name", "") or
        all_extracted.get("insurance_company", "")
    )
    tpa_detection = detect_tpa_template(insurance_company) if insurance_company else None

    # Map all OCR keys to schema field IDs — try detected TPA first, fallback to all
    mapped_data = {}
    target_schema = None

    if tpa_detection and tpa_detection.get("has_schema"):
        target_schema = tpa_detection["schema_name"]
    
    if target_schema:
        schema_path = BASE_DIR / "analyzed" / target_schema
    else:
        # Fallback to first available schema with a template
        available = [
            f.name for f in (BASE_DIR / "analyzed").glob("*.json")
            if not f.name.endswith("_gemini_raw.json")
        ]
        target_schema = available[0] if available else None
        schema_path = (BASE_DIR / "analyzed" / target_schema) if target_schema else None

    if schema_path and schema_path.exists():
        with open(schema_path) as f:
            schema = json.load(f)
        schema_fields = [field["field_id"] for field in schema["fields"]]
        mapped_data = mapping_engine.map_ocr_to_schema(all_extracted, schema_fields)
        mapped_data = mapping_engine.handle_gender(mapped_data)

    # Store session
    _sessions[session_id] = {
        "session_id": session_id,
        "uploaded_files": uploaded,
        "raw_extractions": raw_extractions,
        "raw_ocr_merged": all_extracted,
        "mapped_data": mapped_data,
        "tpa_detection": tpa_detection,
        "status": "extracted",
        "created": datetime.utcnow().isoformat(),
    }

    return ok({
        "session_id": session_id,
        "files_uploaded": len(uploaded),
        "ocr_fields_extracted": len(all_extracted),
        "mapped_fields": len(mapped_data),
        "mapped_data": mapped_data,
        "tpa_detection": tpa_detection,
        "raw_extractions": raw_extractions,
    })


@app.get("/workflow/{session_id}")
def workflow_get(session_id: str):
    """Get current workflow session state."""
    if session_id not in _sessions:
        err(f"Session {session_id} not found", 404)
    return ok(_sessions[session_id])


@app.post("/workflow/{session_id}/remap")
def workflow_remap(session_id: str, schema_name: str = Form(...)):
    """
    Re-map raw OCR data against a specific TPA schema.
    Uses alias match + fuzzy match against field labels.
    """
    from rapidfuzz import fuzz as rfuzz

    if session_id not in _sessions:
        err(f"Session {session_id} not found", 404)

    session = _sessions[session_id]
    raw_ocr = session.get("raw_ocr_merged", {})

    schema_path = BASE_DIR / "analyzed" / schema_name
    if not schema_path.exists():
        err(f"Schema not found: {schema_name}", 404)

    with open(schema_path) as f:
        schema = json.load(f)

    schema_fields = [fd["field_id"] for fd in schema["fields"]]

    # Pass 1: standard mapping engine (aliases + fuzzy against field_mapping keys)
    mapped = mapping_engine.map_ocr_to_schema(raw_ocr, schema_fields)
    mapped = mapping_engine.handle_gender(mapped)

    claimed = set(mapped.keys())
    used_ocr = set()
    for ocr_key, val in raw_ocr.items():
        for fid, fval in mapped.items():
            if str(fval) == str(val):
                used_ocr.add(ocr_key)
                break

    # Pass 2: match remaining OCR keys against schema field labels
    label_candidates = {}
    for fd in schema["fields"]:
        fid = fd["field_id"]
        if fid in claimed:
            continue
        label_candidates[fd["label"].lower().strip()] = fid
        label_candidates[fid.replace("_", " ")] = fid

    remaining = {k: v for k, v in raw_ocr.items() if k not in used_ocr}
    for ocr_key, value in remaining.items():
        key_norm = ocr_key.lower().strip()
        # Exact label match
        if key_norm in label_candidates:
            fid = label_candidates[key_norm]
            if fid not in claimed:
                mapped[fid] = value
                claimed.add(fid)
                continue
        # Fuzzy match against labels
        best_score, best_fid = 0, None
        for label, fid in label_candidates.items():
            if fid in claimed:
                continue
            score = rfuzz.token_sort_ratio(key_norm, label)
            if score > best_score:
                best_score, best_fid = score, fid
        if best_score >= 65 and best_fid:
            mapped[best_fid] = value
            claimed.add(best_fid)

    # Determine template name from schema name
    template_stem = Path(schema_name).stem
    template_name = None
    for tkey, tfile in TPA_TEMPLATE_MAP.items():
        if Path(tfile).stem == template_stem:
            template_name = tfile
            break
    if not template_name:
        template_name = template_stem + ".pdf"

    session["mapped_data"] = mapped
    session["selected_schema"] = schema_name
    session["selected_template"] = template_name
    session["status"] = "mapped"

    return ok({
        "mapped_data": mapped,
        "mapped_fields": len(mapped),
        "total_schema_fields": len(schema_fields),
        "schema_name": schema_name,
        "template_name": template_name,
    })


@app.put("/workflow/{session_id}/data")
def workflow_update_data(session_id: str, data: dict):
    """
    Step 2: Staff edits/verifies master form data.
    Receives the full corrected field data dict from the frontend.
    """
    if session_id not in _sessions:
        err(f"Session {session_id} not found", 404)
    _sessions[session_id]["mapped_data"] = data
    _sessions[session_id]["status"] = "verified"
    _sessions[session_id]["verified_at"] = datetime.utcnow().isoformat()
    return ok({"session_id": session_id, "status": "verified", "fields": len(data)})


@app.post("/workflow/{session_id}/generate")
def workflow_generate(
    session_id: str,
    template_name: str = Form(""),
    schema_name: str = Form(""),
):
    """
    Step 3: Generate the final populated TPA PDF from verified data.
    Uses template/schema from the form submission, or falls back to session-stored values.
    """
    if session_id not in _sessions:
        err(f"Session {session_id} not found", 404)

    session = _sessions[session_id]
    data = session.get("mapped_data", {})
    if not data:
        err("No data to populate — run OCR and verify first", 400)

    # Prefer explicitly passed values, fall back to session-stored values from remap
    if not template_name:
        template_name = session.get("selected_template", "")
    if not schema_name:
        schema_name = session.get("selected_schema", "")

    if not template_name or not schema_name:
        err("No TPA form selected — please select a form before generating", 400)

    logger.info("Generating PDF: template=%s, schema=%s", template_name, schema_name)

    template_path = BASE_DIR / "templates" / template_name
    schema_path = BASE_DIR / "analyzed" / schema_name

    if not template_path.exists():
        err(f"Template not found: {template_name}", 404)
    if not schema_path.exists():
        err(f"Schema not found: {schema_name} — this template has not been analyzed yet", 404)

    form_id = str(uuid.uuid4())[:8]
    output_filename = f"{template_path.stem}_{form_id}_filled.pdf"
    output_path = OUTPUT_DIR / output_filename

    try:
        result_path = form_engine.populate(
            str(template_path),
            str(schema_path),
            data,
            str(output_path),
        )
    except Exception as e:
        logger.error("Form population failed: %s", e)
        err(f"Form population failed: {str(e)}", 500)

    form_info = {
        "path": result_path,
        "filename": output_filename,
        "template": template_name,
        "schema": schema_name,
        "created": datetime.utcnow().isoformat(),
        "data_keys": list(data.keys()),
        "session_id": session_id,
    }
    _populated_forms[form_id] = form_info
    session["form_id"] = form_id
    session["status"] = "generated"

    return ok({
        "form_id": form_id,
        "filename": output_filename,
        "preview_url": f"/forms/preview/{form_id}",
        "export_url": f"/forms/export/{form_id}",
    })


@app.get("/forms/export/{form_id}")
def export_form(form_id: str):
    """Download the final populated PDF as an attachment."""
    if form_id not in _populated_forms:
        err(f"Form {form_id} not found", 404)
    form_info = _populated_forms[form_id]
    file_path = Path(form_info["path"])
    if not file_path.exists():
        err("Populated PDF file missing", 500)
    return FileResponse(
        str(file_path),
        media_type="application/pdf",
        filename=form_info["filename"],
        headers={"Content-Disposition": f'attachment; filename="{form_info["filename"]}"'},
    )


@app.get("/workflow/{session_id}/schema-fields")
def workflow_schema_fields(
    session_id: str,
    schema_name: str = Query("Ericson TPA Preauth.json"),
):
    """Get the full field schema for use in the master form UI."""
    schema_path = BASE_DIR / "analyzed" / schema_name
    if not schema_path.exists():
        err(f"Schema not found: {schema_name}", 404)
    with open(schema_path) as f:
        schema = json.load(f)
    fields = schema.get("fields", [])

    # Also include the session's current mapped data
    session_data = {}
    if session_id in _sessions:
        session_data = _sessions[session_id].get("mapped_data", {})

    return ok({
        "fields": fields,
        "current_data": session_data,
        "form_title": schema.get("form_title", ""),
        "total_pages": schema.get("total_pages", 0),
    })


# ---------------------------------------------------------------------------
# SERVE FRONTEND
# ---------------------------------------------------------------------------
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIR.mkdir(exist_ok=True)

@app.get("/ui", response_class=HTMLResponse)
@app.get("/ui/{rest_of_path:path}", response_class=HTMLResponse)
def serve_frontend(rest_of_path: str = ""):
    """Serve the single-page frontend."""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Frontend not found</h1><p>Place index.html in /frontend</p>", 404)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return ok({
        "service": "TPA Pre-Authorization System",
        "version": "1.0.0",
        "status": "running",
        "templates": len(form_engine.list_templates()),
        "schemas": len(form_engine.list_schemas()),
    })


@app.get("/health")
def health():
    return ok({"status": "healthy"})
