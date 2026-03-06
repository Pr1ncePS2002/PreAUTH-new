#!/usr/bin/env python3
"""
PPN Declaration Form PDF Generator.

Fills the PPN (Preferred Provider Network) declaration form used for GIPSA cases.
Maps patient/insurance/clinical data onto the PPN_DECELARATION.pdf template
using coordinate-based overlay (ReportLab + PyPDF2), consistent with the main
TPA form engine approach.

Usage:
    from services.pdf.generate_ppn_pdf import generate_ppn_pdf

    output_path = generate_ppn_pdf(data, output_path="output/ppn_filled.pdf")
"""

import io
import json
import logging
from pathlib import Path
from typing import Optional

from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_PATH = BASE_DIR / "templates" / "PPN_DECELARATION.pdf"
SCHEMA_PATH = BASE_DIR / "analyzed" / "PPN_DECELARATION.json"

# ── Hardcoded hospital fields (always filled) ────────────────────────────
HARDCODED_FIELDS = {
    "ppn_hospital_name": "AMRITA HOSPITAL",
    "ppn_hospital_address": "MATA AMRITANANDAMAYI MARG, SECTOR-88, FARIDABAD (HR-121002)",
    "ppn_id_proof": "ID PROOF ENCLOSED",
    "ppn_attendant_address": "ENCLOSED",
}

# ── Dynamic field mapping: PPN field_id → source field_id in session data ─
# Includes aliases from all TPA schemas (Bajaj, Ericson, Heritage) + raw OCR keys
PPN_FIELD_MAP = {
    "ppn_patient_name":       ["patient_name", "insured_name", "Patient Name", "Insured Name", "Name"],
    "ppn_age_sex":            None,  # Computed from patient_age + patient_gender
    "ppn_ip_no":              ["ip_number", "patient_ip_number", "MRD No", "MRD Number", "MRD_No", "MRD_Number"],
    "ppn_uhid_no":            ["uhid_number", "patient_uhid", "uhid", "Card ID", "patient_insured_card_id", "insured_card_id_number"],
    "ppn_mobile_no":          ["patient_mobile", "mobile_number", "mobile_no", "patient_contact_no", "patient_contact_number", "Mobile No"],
    "ppn_date_of_admission":  ["date_of_admission", "admission_date", "Expected D.O.A", "Date of Admission"],
    "ppn_time_of_admission":  ["time_of_admission", "admission_time", "Time of Admission"],
    "ppn_date_of_discharge":  ["date_of_discharge", "discharge_date", "Date of Discharge"],
    "ppn_time_of_discharge":  ["time_of_discharge", "discharge_time", "Time of Discharge"],
    "ppn_attendant_name":     ["attendant_name", "name_of_attendant", "patient_attendant_name", "Attendant Name"],
    "ppn_attendant_mobile":   ["attendant_mobile", "attendant_mobile_number", "patient_attendant_contact_no", "attending_relative_contact_number", "relative_contact_number"],
    "ppn_policy_number":      ["policy_number", "policy_no", "tpa_card_number", "patient_policy_corporate_name", "policy_number_corporate_name", "Policy Number", "patient_insured_card_id", "insured_card_id_number"],
    "ppn_insurance_company":  ["insurance_company", "insurer_name", "tpa_insurance_company_name", "patient_other_mediclaim_company_name", "Insurance Company"],
    "ppn_additional_facility": None,  # Computed from procedure_name + room_category
    "ppn_cost_amount":        ["expected_cost_of_treatment", "sum_total_expected_cost", "cost_estimate", "cost_total_expected_hospitalization", "sum_total_expected_cost_of_hospitalization", "cost_all_inclusive_package", "Total Estimate"],
    "ppn_cost_words":         ["cost_in_words"],
}


def _resolve_value(data: dict, source_keys: list[str]) -> str:
    """Return the first non-empty value from a list of candidate source keys."""
    for key in source_keys:
        val = data.get(key, "")
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _build_ppn_data(session_data: dict) -> dict:
    """
    Build the final PPN field values from session mapped_data.
    Applies hardcoded values, then dynamic mapping, then computed fields.
    """
    result = dict(HARDCODED_FIELDS)

    # Dynamic mapping from session data
    for ppn_field, sources in PPN_FIELD_MAP.items():
        if sources is None:
            continue  # Computed fields handled below
        val = _resolve_value(session_data, sources)
        if val:
            result[ppn_field] = val

    # ── Computed: Age / Sex ──
    # Check all schema variants: Bajaj (patient_age_years), Ericson (age_years_duration), Heritage (age_years), raw OCR (Age)
    age = (
        session_data.get("patient_age", "")
        or session_data.get("age_years_duration", "")
        or session_data.get("patient_age_years", "")
        or session_data.get("age_years", "")
        or session_data.get("Age", "")
    )
    # Strip trailing text like "31Y 10M 31D" → just take the first number
    if age and not str(age).strip().isdigit():
        import re as _re
        m = _re.match(r'(\d+)', str(age).strip())
        if m:
            age = m.group(1)
    gender = session_data.get("patient_gender", "") or session_data.get("gender", "") or session_data.get("Gender", "")
    if not gender:
        # Bajaj schema uses patient_gender_male/female, Ericson/Heritage use gender_male/female
        if session_data.get("gender_male") or session_data.get("patient_gender_male"):
            gender = "M"
        elif session_data.get("gender_female") or session_data.get("patient_gender_female"):
            gender = "F"
    age_sex_parts = []
    if age:
        age_sex_parts.append(str(age))
    if gender:
        g = str(gender).strip().upper()
        if g in ("MALE", "M"):
            age_sex_parts.append("M")
        elif g in ("FEMALE", "F"):
            age_sex_parts.append("F")
        else:
            age_sex_parts.append(g[:1])
    if age_sex_parts:
        result["ppn_age_sex"] = " / ".join(age_sex_parts)

    # ── Computed: Additional Facility ──
    procedure = (
        session_data.get("procedure_name", "")
        or session_data.get("proposed_treatment", "")
        or session_data.get("doctor_surgery_name", "")
        or session_data.get("surgery_name", "")
        or session_data.get("Surgery Name", "")
        or session_data.get("Plan", "")
    )
    room = (
        session_data.get("room_category", "")
        or session_data.get("room_type", "")
        or session_data.get("Room Type", "")
    )
    parts = []
    if procedure:
        parts.append(str(procedure).strip())
    if room:
        parts.append(str(room).strip())
    if parts:
        result["ppn_additional_facility"] = ", ".join(parts)
    elif not result.get("ppn_additional_facility"):
        result["ppn_additional_facility"] = "ICU with monitors and higher nursing care"

    return result


def generate_ppn_pdf(
    session_data: dict,
    output_path: Optional[str] = None,
) -> str:
    """
    Generate a filled PPN declaration PDF.

    Args:
        session_data: The mapped_data dict from the workflow session.
        output_path: Where to save (auto-generated if None).

    Returns:
        Path to the filled PPN PDF.
    """
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"PPN template not found: {TEMPLATE_PATH}")
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"PPN schema not found: {SCHEMA_PATH}")

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    ppn_data = _build_ppn_data(session_data)

    if not output_path:
        output_dir = BASE_DIR / "output"
        output_dir.mkdir(exist_ok=True)
        output_path = str(output_dir / "ppn_declaration_filled.pdf")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # ── Create overlay ──
    template = PdfReader(str(TEMPLATE_PATH))
    writer = PdfWriter()

    page = template.pages[0]
    page_height = float(schema.get("page_heights", {}).get("1", 720.0))
    page_width = float(schema.get("page_widths", {}).get("1", 504.0))

    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=(page_width, page_height))

    has_content = False
    for field in schema["fields"]:
        fid = field["field_id"]
        value = ppn_data.get(fid, "")
        if not value:
            continue

        x = field["coordinates"]["x"]
        y = page_height - field["coordinates"]["y"]
        font_size = field.get("font_size", 9)
        max_width = field.get("max_width", 300)

        can.setFont("Helvetica", font_size)

        # Truncate if text would overflow
        text = str(value)
        while can.stringWidth(text, "Helvetica", font_size) > max_width and len(text) > 1:
            text = text[:-1]

        can.drawString(x, y, text)
        has_content = True
        logger.debug("PPN field %s = %s at (%s, %s)", fid, value, x, y)

    can.save()
    packet.seek(0)

    if has_content:
        overlay = PdfReader(packet)
        page.merge_page(overlay.pages[0])

    writer.add_page(page)

    # Add remaining pages (if any) unchanged
    for i in range(1, len(template.pages)):
        writer.add_page(template.pages[i])

    with open(output_path, "wb") as f:
        writer.write(f)

    logger.info("PPN declaration generated: %s (fields filled: %d)", output_path, len(ppn_data))
    return output_path
