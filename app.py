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
import asyncio
import uuid
import logging
import shutil
import contextlib
import threading
import base64
import io
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

import jwt
import qrcode
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Query, Form, Body, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services.mapping_engine import MappingEngine
from services.ocr_service import OCRService
from services.form_engine import FormEngine
from services.his_service import HISService
from services.pdf.generate_ppn_pdf import generate_ppn_pdf
from services.pdf.merge_claim_documents import merge_claim_documents

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
SESSIONS_DIR = BASE_DIR / "sessions"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
SESSIONS_DIR.mkdir(exist_ok=True)

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 8

# PHI data retention — DPDP Act 2023 compliance
DATA_RETENTION_HOURS = int(os.getenv("DATA_RETENTION_HOURS", "24"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PHI auto-cleanup
# ---------------------------------------------------------------------------
def _purge_old_phi() -> None:
    """Delete uploaded PHI files and sessions older than DATA_RETENTION_HOURS."""
    cutoff = datetime.utcnow() - timedelta(hours=DATA_RETENTION_HOURS)
    purge_dirs = [UPLOADS_DIR, OUTPUT_DIR, SESSIONS_DIR]
    deleted = 0
    for directory in purge_dirs:
        if not directory.exists():
            continue
        for file_path in directory.iterdir():
            if not file_path.is_file():
                continue
            try:
                mtime = datetime.utcfromtimestamp(file_path.stat().st_mtime)
                if mtime < cutoff:
                    file_path.unlink()
                    deleted += 1
                    logger.debug("PHI purge: deleted %s", file_path.name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("PHI purge: could not delete %s — %s", file_path, exc)
    if deleted:
        logger.info(
            "PHI purge: removed %d file(s) older than %d hours",
            deleted, DATA_RETENTION_HOURS,
        )
    else:
        logger.debug("PHI purge: no files to remove (retention %dh)", DATA_RETENTION_HOURS)


def _start_cleanup_scheduler(interval_hours: int = 6) -> None:
    """Run _purge_old_phi() every `interval_hours` in a background daemon thread."""
    def _loop():
        while True:
            threading.Event().wait(interval_hours * 3600)
            try:
                _purge_old_phi()
            except Exception as exc:  # noqa: BLE001
                logger.error("PHI cleanup scheduler error: %s", exc)

    t = threading.Thread(target=_loop, daemon=True, name="phi-cleanup")
    t.start()
    logger.info(
        "PHI cleanup scheduler started — purging every %dh, retention=%dh",
        interval_hours, DATA_RETENTION_HOURS,
    )

# ---------------------------------------------------------------------------
# App & middleware
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def lifespan(app_: FastAPI):
    """Startup: purge stale PHI + start scheduler. Shutdown: final purge."""
    logger.info("[startup] Running initial PHI purge (retention=%dh)", DATA_RETENTION_HOURS)
    _purge_old_phi()
    _start_cleanup_scheduler(interval_hours=6)
    yield
    logger.info("[shutdown] Running final PHI purge")
    _purge_old_phi()


app = FastAPI(
    title="TPA Pre-Authorization System",
    description="Automated TPA form filling for hospital pre-authorization",
    version="1.0.0",
    lifespan=lifespan,
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
EXTRACTION_MODE = os.getenv("EXTRACTION_MODE", "gemini")  # "gemini" | "documentai" | "hybrid"
mapping_engine = MappingEngine()
ocr_service = OCRService(mode=EXTRACTION_MODE)
form_engine = FormEngine()
his_service = HISService()  # Stub mode

# In-memory stores (replace with DB in production)
_populated_forms: dict[str, dict] = {}  # form_id -> {path, data, template, schema, created}
_ocr_results: dict[str, dict] = {}     # result_id -> {file, type, data}
_sessions: dict[str, dict] = {}        # session_id -> full workflow state

# Mobile upload sessions: session_token -> {mrd_number, created, expires_at, files: [...]}
_upload_sessions: dict[str, dict] = {}

# WebSocket connections per upload_token: upload_token -> list[WebSocket]
_ws_connections: dict[str, list] = {}

SESSION_EXPIRY_MINUTES = int(os.getenv("SESSION_EXPIRY_MINUTES", "30"))
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "5")) * 1024 * 1024  # 5MB default
ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


def _save_session(session_id: str):
    """Persist session to disk so it survives server reloads."""
    if session_id in _sessions:
        path = SESSIONS_DIR / f"{session_id}.json"
        with open(path, "w") as f:
            json.dump(_sessions[session_id], f)


def _load_session(session_id: str) -> dict | None:
    """Load session from disk if not in memory."""
    if session_id in _sessions:
        return _sessions[session_id]
    path = SESSIONS_DIR / f"{session_id}.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        _sessions[session_id] = data
        return data
    return None


# ---------------------------------------------------------------------------
# TPA template auto-detection map
# ---------------------------------------------------------------------------

# Hospital details — hardcoded for Amrita Hospital
HOSPITAL_INFO = {
    # All possible field_id variations across schemas
    "hospital_name": "Amrita Hospital",
    "provider_hospital_name": "Amrita Hospital",
    "hospital_address": "Sector 88, Faridabad, Haryana",
    "provider_address": "Sector 88, Faridabad, Haryana",
    "hospital_state": "Haryana",
    "provider_state_name": "Haryana",
    "hospital_city": "Faridabad",
    "provider_city_name": "Faridabad",
    "hospital_pin_code": "121002",
    "provider_pin_code": "121002",
    "hospital_rohini_id": "8900080528185",
    "provider_hosp_id": "8900080528185",
}


def inject_hospital_data(mapped_data: dict, schema_fields: list[str]) -> dict:
    """Inject hardcoded hospital info into mapped data for fields that exist in the schema."""
    for field_id, value in HOSPITAL_INFO.items():
        if field_id in schema_fields:
            mapped_data[field_id] = value
    return mapped_data


def calculate_age_from_dob(mapped_data: dict) -> dict:
    """
    If any DOB field is present, calculate age in years and months
    and populate ALL age field variants (Ericson + Bajaj + Heritage).
    """
    # Try all possible DOB field names
    dob_str = ""
    for dob_key in ["date_of_birth", "patient_dob", "dob"]:
        dob_str = mapped_data.get(dob_key, "") or ""
        if dob_str:
            break
    if not dob_str:
        return mapped_data

    from dateutil import parser as dateparser
    try:
        dob = dateparser.parse(dob_str, dayfirst=True)
        today = datetime.utcnow()
        years = today.year - dob.year
        months = today.month - dob.month
        if today.day < dob.day:
            months -= 1
        if months < 0:
            years -= 1
            months += 12
        # Ericson field names
        mapped_data["age_years_duration"] = str(years)
        mapped_data["age_months_duration"] = str(months)
        # Bajaj field names
        mapped_data["patient_age_years"] = str(years)
        mapped_data["patient_age_months"] = str(months)
        # Generic
        mapped_data["patient_age"] = str(years)
        logger.info("Calculated age: %d years %d months from DOB %s", years, months, dob_str)
    except Exception as e:
        logger.warning("Could not parse DOB '%s': %s", dob_str, e)
    return mapped_data


TPA_TEMPLATE_MAP = {
    "ericson": "Ericson TPA Preauth.pdf",
    "bajaj allianz": "BAJAJ ALLIANZ TPA PREAUTH FORM.pdf",
    "bajaj": "BAJAJ ALLIANZ TPA PREAUTH FORM.pdf",
    "bajaj general": "BAJAJ ALLIANZ TPA PREAUTH FORM.pdf",
    "bajaj general insurance": "BAJAJ ALLIANZ TPA PREAUTH FORM.pdf",
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

# GIPSA TPA list — insurance companies that require PPN declaration
GIPSA_TPA_LIST = {
    "oriental insurance", "national insurance", "new india assurance",
    "united india insurance", "general insurance corporation",
    "oriental", "national", "new india", "united india", "gic",
    "iffco tokio", "bajaj allianz", "icici lombard", "hdfc ergo",
    "tata aig", "reliance general", "sbi general", "cholamandalam",
    "chola ms", "future generali", "universal sompo", "go digit",
    "niva bupa", "star health", "care health", "aditya birla",
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
    mapped = mapping_engine.handle_gender(mapped, raw_ocr=extracted)

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
    files: List[UploadFile] = File(None),
    document_types: str = Form(""),  # comma-separated types matching file order
    mrd_number: str = Form(""),  # staff-entered MRD number for identification + filename
    upload_token: str = Form(""),  # optional — mobile upload session token to include those files
):
    """
    Step 1: Upload multiple documents and run OCR on each.
    Also includes any files previously uploaded via mobile (upload_token).
    Returns a session with all extracted data merged into a master form dict.
    """
    session_id = str(uuid.uuid4())[:12]
    type_list = [t.strip() for t in document_types.split(",") if t.strip()] if document_types else []

    uploaded = []
    all_extracted: dict = {}
    raw_extractions: list[dict] = []

    # --- Step 1a: Save desktop-uploaded files to disk ---
    file_info = []
    if files:
        for i, file in enumerate(files):
            doc_type = type_list[i] if i < len(type_list) else "generic"
            file_id = str(uuid.uuid4())[:8]
            safe_name = f"{file_id}_{file.filename}"
            save_path = UPLOADS_DIR / safe_name

            content = await file.read()
            with open(save_path, "wb") as f:
                f.write(content)

            info = {
                "file_id": file_id,
                "filename": file.filename,
                "saved_as": safe_name,
                "path": str(save_path),
                "document_type": doc_type,
                "size": len(content),
            }
            file_info.append(info)
            uploaded.append(info)

    # --- Step 1b: Include mobile-uploaded files ---
    if upload_token:
        us = _upload_sessions.get(upload_token)
        if us and us.get("files"):
            for mf in us["files"]:
                fi = {
                    "file_id": mf["file_id"],
                    "filename": mf["filename"],
                    "saved_as": mf["saved_as"],
                    "path": mf["path"],
                    "document_type": mf.get("document_type", "generic"),
                    "size": mf["size"],
                }
                file_info.append(fi)
                uploaded.append(fi)
            logger.info("Including %d mobile-uploaded files from upload_token=%s...", len(us["files"]), upload_token[:8])

    if not file_info:
        err("No files provided (upload documents on desktop or via mobile)", 400)

    # --- Step 2: Run OCR on all documents IN PARALLEL (major speedup for Document AI) ---
    # Document AI takes 6–30s per file; parallel cuts total wait to max(individual times)
    loop = asyncio.get_event_loop()

    async def _extract_one(path: str, doc_type: str):
        return await loop.run_in_executor(None, ocr_service.extract, path, doc_type)

    ocr_tasks = [_extract_one(fi["path"], fi["document_type"]) for fi in file_info]
    ocr_results = await asyncio.gather(*ocr_tasks, return_exceptions=True)

    for fi, result in zip(file_info, ocr_results):
        if isinstance(result, Exception):
            logger.error("OCR failed for %s: %s", fi["filename"], result)
            raw_extractions.append({
                "file": fi["filename"],
                "type": fi["document_type"],
                "error": str(result),
            })
        else:
            raw_extractions.append({
                "file": fi["filename"],
                "type": fi["document_type"],
                "fields": result,
            })
            # Merge into master dict (first document wins for conflicting keys)
            for k, v in result.items():
                if k not in all_extracted:
                    all_extracted[k] = v

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
        from rapidfuzz import fuzz as rfuzz
        with open(schema_path) as f:
            schema = json.load(f)
        schema_fields = [field["field_id"] for field in schema["fields"]]

        # Pass 1: mapping engine (aliases + fuzzy against field_mapping keys)
        mapped_data = mapping_engine.map_ocr_to_schema(all_extracted, schema_fields)
        mapped_data = mapping_engine.handle_gender(mapped_data, raw_ocr=all_extracted)

        # Pass 2: label-based matching for schema-specific field IDs
        claimed = set(mapped_data.keys())
        used_ocr = set()
        for ocr_key, val in all_extracted.items():
            for fid, fval in mapped_data.items():
                if str(fval) == str(val):
                    used_ocr.add(ocr_key)
                    break

        label_candidates = {}
        for fd in schema["fields"]:
            fid = fd["field_id"]
            if fid in claimed:
                continue
            label_candidates[fd["label"].lower().strip()] = fid
            label_candidates[fid.replace("_", " ")] = fid

        remaining = {k: v for k, v in all_extracted.items() if k not in used_ocr}
        for ocr_key, value in remaining.items():
            key_norm = ocr_key.lower().strip()
            if key_norm in label_candidates:
                fid = label_candidates[key_norm]
                if fid not in claimed:
                    mapped_data[fid] = value
                    claimed.add(fid)
                    continue
            best_score, best_fid = 0, None
            for label, fid in label_candidates.items():
                if fid in claimed:
                    continue
                score = rfuzz.token_sort_ratio(key_norm, label)
                if score > best_score:
                    best_score, best_fid = score, fid
            if best_score >= 65 and best_fid:
                mapped_data[best_fid] = value
                claimed.add(best_fid)

        mapped_data = inject_hospital_data(mapped_data, schema_fields)
        mapped_data = calculate_age_from_dob(mapped_data)

    # ── MRD validation against OCR-extracted data ──
    mrd_validation = None
    if mrd_number:
        mrd_number = mrd_number.strip()
        # Search for MRD in OCR results (clinical notes, estimates, etc.)
        ocr_mrd_candidates = []
        for key in ("MRD No", "MRD Number", "Medical Record Number", "MR No",
                    "Patient MRD", "Medical Record No", "mrd_number", "MRD"):
            val = all_extracted.get(key)
            if val:
                ocr_mrd_candidates.append({"key": key, "value": str(val).strip()})
        
        if ocr_mrd_candidates:
            # Check if any OCR-extracted MRD matches the staff-entered one
            matched = any(
                mrd_number.lower() == c["value"].lower()
                for c in ocr_mrd_candidates
            )
            mrd_validation = {
                "entered": mrd_number,
                "found_in_documents": ocr_mrd_candidates,
                "match": matched,
                "status": "verified" if matched else "mismatch",
            }
        else:
            mrd_validation = {
                "entered": mrd_number,
                "found_in_documents": [],
                "match": None,
                "status": "not_found_in_docs",
            }
        # Ensure mrd_number is in mapped_data for downstream use (filename, etc.)
        mapped_data["mrd_number"] = mrd_number

    # Store session (persist to disk so it survives server reloads)
    _sessions[session_id] = {
        "session_id": session_id,
        "uploaded_files": uploaded,
        "raw_extractions": raw_extractions,
        "raw_ocr_merged": all_extracted,
        "mapped_data": mapped_data,
        "tpa_detection": tpa_detection,
        "mrd_number": mrd_number or None,
        "mrd_validation": mrd_validation,
        "status": "extracted",
        "created": datetime.utcnow().isoformat(),
    }
    _save_session(session_id)

    return ok({
        "session_id": session_id,
        "files_uploaded": len(uploaded),
        "ocr_fields_extracted": len(all_extracted),
        "mapped_fields": len(mapped_data),
        "mapped_data": mapped_data,
        "tpa_detection": tpa_detection,
        "raw_extractions": raw_extractions,
        "mrd_number": mrd_number or None,
        "mrd_validation": mrd_validation,
    })


@app.get("/workflow/{session_id}")
def workflow_get(session_id: str):
    """Get current workflow session state."""
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)
    return ok(session)


@app.post("/workflow/{session_id}/remap")
def workflow_remap(session_id: str, schema_name: str = Form(...)):
    """
    Re-map raw OCR data against a specific TPA schema.
    Uses alias match + fuzzy match against field labels.
    """
    from rapidfuzz import fuzz as rfuzz

    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)

    raw_ocr = session.get("raw_ocr_merged", {})

    schema_path = BASE_DIR / "analyzed" / schema_name
    if not schema_path.exists():
        err(f"Schema not found: {schema_name}", 404)

    with open(schema_path) as f:
        schema = json.load(f)

    schema_fields = [fd["field_id"] for fd in schema["fields"]]

    # Pass 1: standard mapping engine (aliases + fuzzy against field_mapping keys)
    mapped = mapping_engine.map_ocr_to_schema(raw_ocr, schema_fields)
    mapped = mapping_engine.handle_gender(mapped, raw_ocr=raw_ocr)
    mapped = inject_hospital_data(mapped, schema_fields)
    mapped = calculate_age_from_dob(mapped)

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
    _save_session(session_id)

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
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)
    session["mapped_data"] = data
    session["status"] = "verified"
    session["verified_at"] = datetime.utcnow().isoformat()
    _save_session(session_id)
    return ok({"session_id": session_id, "status": "verified", "fields": len(data)})


@app.put("/workflow/{session_id}/mrd")
def workflow_update_mrd(session_id: str, body: dict):
    """
    Update the MRD number in the session (staff edited it in Phase 2 form).
    """
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)
    mrd = (body.get("mrd_number") or "").strip()
    if mrd:
        session["mrd_number"] = mrd
        session.setdefault("mapped_data", {})["mrd_number"] = mrd
        _save_session(session_id)
    return ok({"session_id": session_id, "mrd_number": mrd})


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
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)

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

    is_gipsa = session.get("is_gipsa_case", False)
    should_generate_ppn = session.get("generate_ppn", False) and is_gipsa
    attachments = session.get("attachments", [])
    uploaded_files = session.get("uploaded_files", [])

    logger.info(
        "Generating PDF: template=%s, schema=%s, gipsa=%s, ppn=%s, attachments=%d",
        template_name, schema_name, is_gipsa, should_generate_ppn, len(attachments),
    )

    template_path = BASE_DIR / "templates" / template_name
    schema_path = BASE_DIR / "analyzed" / schema_name

    if not template_path.exists():
        err(f"Template not found: {template_name}", 404)
    if not schema_path.exists():
        err(f"Schema not found: {schema_name} — this template has not been analyzed yet", 404)

    form_id = str(uuid.uuid4())[:8]

    # ── Determine MRD number for filename (staff-entered takes priority) ──
    mrd_number = (
        session.get("mrd_number")
        or data.get("mrd_number")
        or session.get("raw_ocr_merged", {}).get("mrd_number")
        or session.get("raw_ocr_merged", {}).get("MRD No")
        or session.get("raw_ocr_merged", {}).get("MRD Number")
        or session.get("raw_ocr_merged", {}).get("Medical Record Number")
    )

    # ── Step 1: Generate TPA claim form ──
    tpa_output_filename = f"{template_path.stem}_{form_id}_filled.pdf"
    tpa_output_path = OUTPUT_DIR / tpa_output_filename

    try:
        tpa_result_path = form_engine.populate(
            str(template_path),
            str(schema_path),
            data,
            str(tpa_output_path),
        )
    except Exception as e:
        logger.error("TPA form population failed: %s", e)
        err(f"TPA form population failed: {str(e)}", 500)

    # ── Step 2: Generate PPN declaration (if GIPSA) ──
    ppn_result_path = None
    if should_generate_ppn:
        try:
            # Merge raw OCR fields as fallback so PPN gets maximum data coverage
            # Raw OCR keys (e.g. "Policy Number", "Insurance Company") are used
            # when the TPA schema field IDs don't match PPN expectations.
            ppn_combined_data = dict(session.get("raw_ocr_merged", {}))
            ppn_combined_data.update(data)  # mapped_data takes priority over raw OCR
            ppn_output_path = str(OUTPUT_DIR / f"ppn_{form_id}_filled.pdf")
            ppn_result_path = generate_ppn_pdf(ppn_combined_data, ppn_output_path)
            logger.info("PPN declaration generated: %s", ppn_result_path)
        except Exception as e:
            logger.error("PPN generation failed (non-fatal): %s", e)
            # PPN failure is non-fatal — continue with TPA form only

    # ── Step 3: Collect attachment file paths (deduplicated) ──
    attachment_paths = []
    seen_paths = set()
    # Include uploaded documents (scans from OCR step)
    for uf in uploaded_files:
        p = Path(uf.get("path", ""))
        if p.exists() and str(p) not in seen_paths:
            attachment_paths.append(str(p))
            seen_paths.add(str(p))

    # Include explicitly uploaded attachments
    for att in attachments:
        p = Path(att.get("path", ""))
        if p.exists() and str(p) not in seen_paths:
            attachment_paths.append(str(p))
            seen_paths.add(str(p))

    # ── Step 4: Merge everything into final package ──
    needs_merge = ppn_result_path or attachment_paths

    if needs_merge:
        try:
            if mrd_number:
                final_filename = f"claim_package_MRD_{mrd_number}.pdf"
            else:
                final_filename = f"claim_package_{form_id}.pdf"
            final_output_path = str(OUTPUT_DIR / final_filename)
            final_path = merge_claim_documents(
                tpa_pdf=tpa_result_path,
                ppn_pdf=ppn_result_path,
                attachments=attachment_paths,
                output_path=final_output_path,
            )
            result_path = final_path
            output_filename = final_filename
        except Exception as e:
            logger.error("PDF merge failed (falling back to TPA-only): %s", e)
            result_path = tpa_result_path
            output_filename = tpa_output_filename
    else:
        result_path = tpa_result_path
        output_filename = tpa_output_filename

    form_info = {
        "path": result_path,
        "filename": output_filename,
        "template": template_name,
        "schema": schema_name,
        "created": datetime.utcnow().isoformat(),
        "data_keys": list(data.keys()),
        "session_id": session_id,
        "is_gipsa": is_gipsa,
        "ppn_generated": ppn_result_path is not None,
        "attachments_count": len(attachment_paths),
        "tpa_only_path": tpa_result_path,
        "ppn_path": ppn_result_path,
    }
    _populated_forms[form_id] = form_info
    session["form_id"] = form_id
    session["status"] = "generated"
    _save_session(session_id)

    return ok({
        "form_id": form_id,
        "filename": output_filename,
        "preview_url": f"/forms/preview/{form_id}",
        "export_url": f"/forms/export/{form_id}",
        "is_gipsa": is_gipsa,
        "ppn_generated": ppn_result_path is not None,
        "attachments_merged": len(attachment_paths),
        "mrd_number": mrd_number,
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


# ---------------------------------------------------------------------------
# ATTACHMENTS
# ---------------------------------------------------------------------------
@app.post("/workflow/{session_id}/attachments")
async def upload_attachments(
    session_id: str,
    files: List[UploadFile] = File(...),
):
    """Upload additional attachments (ID proofs, bills, reports, scans) for the claim package."""
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)

    if "attachments" not in session:
        session["attachments"] = []

    uploaded = []
    for file in files:
        file_id = str(uuid.uuid4())[:8]
        safe_name = f"att_{file_id}_{file.filename}"
        save_path = UPLOADS_DIR / safe_name

        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)

        info = {
            "file_id": file_id,
            "filename": file.filename,
            "saved_as": safe_name,
            "path": str(save_path),
            "size": len(content),
            "content_type": file.content_type or "",
        }
        session["attachments"].append(info)
        uploaded.append(info)
        logger.info("Attachment uploaded: %s -> %s", file.filename, save_path)

    _save_session(session_id)
    return ok({
        "uploaded": len(uploaded),
        "total_attachments": len(session["attachments"]),
        "files": uploaded,
    })


@app.get("/workflow/{session_id}/attachments")
def list_attachments(session_id: str):
    """List all attachments for a session."""
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)
    return ok(session.get("attachments", []))


@app.delete("/workflow/{session_id}/attachments/{file_id}")
def remove_attachment(session_id: str, file_id: str):
    """Remove an attachment from a session."""
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)

    attachments = session.get("attachments", [])
    found = None
    for att in attachments:
        if att["file_id"] == file_id:
            found = att
            break

    if not found:
        err(f"Attachment {file_id} not found", 404)

    attachments.remove(found)
    session["attachments"] = attachments

    # Clean up file
    try:
        Path(found["path"]).unlink(missing_ok=True)
    except Exception:
        pass

    _save_session(session_id)
    return ok({"removed": file_id, "remaining": len(attachments)})


# ---------------------------------------------------------------------------
# GIPSA / PPN
# ---------------------------------------------------------------------------
@app.post("/workflow/{session_id}/gipsa")
def update_gipsa_status(
    session_id: str,
    is_gipsa: bool = Form(False),
    generate_ppn: bool = Form(False),
):
    """Update the GIPSA status and PPN generation flag for a session."""
    session = _load_session(session_id)
    if not session:
        err(f"Session {session_id} not found", 404)

    session["is_gipsa_case"] = is_gipsa
    session["generate_ppn"] = generate_ppn if is_gipsa else False
    _save_session(session_id)

    return ok({
        "is_gipsa_case": session["is_gipsa_case"],
        "generate_ppn": session["generate_ppn"],
    })


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
    session = _load_session(session_id)
    if session:
        session_data = session.get("mapped_data", {})

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
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

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


# ---------------------------------------------------------------------------
# MOBILE UPLOAD — QR Code + Upload Session + WebSocket Sync
# ---------------------------------------------------------------------------

async def _ws_broadcast(session_id: str, message: dict):
    """Send a message to all WebSocket clients connected to a session."""
    connections = _ws_connections.get(session_id, [])
    dead = []
    for ws in connections:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connections.remove(ws)


def _generate_upload_token() -> str:
    """Generate a cryptographically secure upload session token."""
    return secrets.token_urlsafe(24)


def _is_upload_session_valid(session_token: str) -> bool:
    """Check if an upload session token is valid and not expired."""
    us = _upload_sessions.get(session_token)
    if not us:
        return False
    return datetime.utcnow().isoformat() < us["expires_at"]


@app.post("/mobile/create-session")
def create_upload_session(
    request: Request,
    request_body: dict = Body(...),
):
    """
    Create a mobile upload session. Does NOT require an existing workflow session.
    Called as soon as MRD is entered — before Extract Data.
    Returns a session_token and QR code (base64 PNG).
    """
    mrd_number = request_body.get("mrd_number", "")
    if not mrd_number:
        err("mrd_number is required", 400)

    # Generate secure token
    session_token = _generate_upload_token()
    expires_at = (datetime.utcnow() + timedelta(minutes=SESSION_EXPIRY_MINUTES)).isoformat()

    _upload_sessions[session_token] = {
        "mrd_number": mrd_number,
        "created": datetime.utcnow().isoformat(),
        "expires_at": expires_at,
        "files": [],  # list of uploaded file info dicts
    }

    # Build mobile upload URL — derive base from request or env var
    base_url = os.getenv("APP_BASE_URL", "")
    if not base_url:
        # Derive from the incoming request (works across LAN, phone, etc.)
        host = request.headers.get("host", request.base_url.netloc)
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        base_url = f"{scheme}://{host}"
    mobile_path = f"/mobile-upload?session={session_token}"
    mobile_url = f"{base_url}{mobile_path}"

    # Generate QR code as base64 PNG
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(mobile_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    logger.info("Mobile upload session created: token=%s... mrd=%s", session_token[:8], mrd_number)

    return ok({
        "session_token": session_token,
        "mobile_url": mobile_url,
        "qr_code_base64": qr_base64,
        "expires_at": expires_at,
        "mrd_number": mrd_number,
    })


@app.get("/mobile/session/{session_token}")
def get_upload_session(session_token: str):
    """Validate a mobile upload session token and return session info + doc types."""
    us = _upload_sessions.get(session_token)
    if not us:
        err("Invalid or expired session", 404)
    if not _is_upload_session_valid(session_token):
        err("Session expired. Please rescan QR code.", 410)
    return ok({
        "session_token": session_token,
        "mrd_number": us["mrd_number"],
        "expires_at": us["expires_at"],
        "doc_types": [
            {"key": "policy_card",    "label": "Insurance / Policy Card",  "icon": "\U0001f3e5"},
            {"key": "aadhaar",        "label": "Patient ID (Aadhaar)",     "icon": "\U0001f4b3"},
            {"key": "attendant_id",   "label": "Attendant ID Card",        "icon": "\U0001f465"},
            {"key": "clinical_notes", "label": "Clinical Documents",       "icon": "\U0001f4cb"},
            {"key": "estimate",       "label": "Estimate / Proforma",      "icon": "\U0001f4b0"},
            {"key": "generic",        "label": "Other Documents",          "icon": "\U0001f4ce"},
        ],
        "files": us.get("files", []),
    })


@app.post("/mobile/upload")
async def mobile_upload_documents(
    session_token: str = Form(...),
    files: List[UploadFile] = File(...),
    document_type: str = Form("generic"),
    uploaded_from: str = Form("mobile"),
):
    """
    Upload documents from mobile (or desktop dropzone).
    Stores files in the upload session and broadcasts to desktop via WebSocket.
    """
    us = _upload_sessions.get(session_token)
    if not us:
        err("Invalid session token", 404)
    if not _is_upload_session_valid(session_token):
        err("Session expired. Please rescan QR code.", 410)

    uploaded = []
    for file in files:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            continue

        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            continue

        file_id = str(uuid.uuid4())[:8]
        safe_name = f"mob_{file_id}_{file.filename}"
        save_path = UPLOADS_DIR / safe_name

        with open(save_path, "wb") as f:
            f.write(content)

        info = {
            "file_id": file_id,
            "filename": file.filename,
            "saved_as": safe_name,
            "path": str(save_path),
            "size": len(content),
            "document_type": document_type,
            "uploaded_from": uploaded_from,
            "content_type": file.content_type or "",
            "uploaded_at": datetime.utcnow().isoformat(),
        }
        us["files"].append(info)
        uploaded.append(info)
        logger.info("Mobile upload: %s -> %s (type=%s, from=%s)", file.filename, save_path, document_type, uploaded_from)

    # Broadcast to desktop via WebSocket — send full file list
    await _ws_broadcast(session_token, {
        "type": "documents_uploaded",
        "files": [
            {
                "file_id": u["file_id"],
                "filename": u["saved_as"],
                "original_name": u["filename"],
                "size_bytes": u["size"],
                "document_type": u["document_type"],
                "uploaded_from": u["uploaded_from"],
                "uploaded_at": u["uploaded_at"],
            }
            for u in us["files"]
        ],
    })

    return ok({
        "uploaded": len(uploaded),
        "total_files": len(us["files"]),
        "documents": uploaded,
    })


@app.get("/mobile/uploads/{session_token}")
def list_mobile_uploads(session_token: str):
    """List all documents uploaded via this upload session."""
    us = _upload_sessions.get(session_token)
    if not us:
        err("Invalid session token", 404)
    return ok(us.get("files", []))


@app.websocket("/ws/upload/{upload_token}")
async def websocket_endpoint(websocket: WebSocket, upload_token: str):
    """WebSocket endpoint for real-time desktop sync of mobile uploads."""
    await websocket.accept()
    if upload_token not in _ws_connections:
        _ws_connections[upload_token] = []
    _ws_connections[upload_token].append(websocket)
    logger.info("WebSocket connected: upload_token=%s... (total=%d)", upload_token[:8], len(_ws_connections[upload_token]))

    try:
        # Send current files on connect
        us = _upload_sessions.get(upload_token)
        if us:
            await websocket.send_json({
                "type": "current_uploads",
                "files": [
                    {
                        "file_id": u["file_id"],
                        "filename": u["saved_as"],
                        "original_name": u["filename"],
                        "size_bytes": u["size"],
                        "document_type": u["document_type"],
                        "uploaded_from": u["uploaded_from"],
                        "uploaded_at": u["uploaded_at"],
                    }
                    for u in us.get("files", [])
                ],
            })
        # Keep connection alive — listen for pings
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        conns = _ws_connections.get(upload_token, [])
        if websocket in conns:
            conns.remove(websocket)
        logger.info("WebSocket disconnected: upload_token=%s...", upload_token[:8])


# ---------------------------------------------------------------------------
# SERVE MOBILE UPLOAD PAGE
# ---------------------------------------------------------------------------
@app.get("/mobile-upload", response_class=HTMLResponse)
def serve_mobile_upload():
    """Serve the mobile upload page."""
    mobile_path = FRONTEND_DIR / "mobile-upload.html"
    if not mobile_path.exists():
        return HTMLResponse("<h1>Mobile upload page not found</h1>", 404)
    return HTMLResponse(mobile_path.read_text(encoding="utf-8"))
