"""Batch fix coordinates and styles for Bajaj Allianz form fields."""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = PROJECT_ROOT / "analyzed" / "BAJAJ ALLIANZ TPA PREAUTH FORM.json"

with open(JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

changes_log = []

def update_field(field_id, dy=0, dx=0, font_size=None, bold=None):
    for field in data["fields"]:
        if field["field_id"] == field_id:
            old_x = field["coordinates"]["x"]
            old_y = field["coordinates"]["y"]
            if dx:
                field["coordinates"]["x"] = round(old_x + dx, 1)
            if dy:
                field["coordinates"]["y"] = round(old_y + dy, 1)
            if font_size is not None:
                field["font_size"] = font_size
            if bold is not None:
                field["bold"] = bold
            changes_log.append(f"  {field_id}: ({old_x},{old_y}) -> ({field['coordinates']['x']},{field['coordinates']['y']})"
                               + (f" font={font_size}" if font_size else "")
                               + (f" bold={bold}" if bold else ""))
            return True
    print(f"  WARNING: field '{field_id}' not found!")
    return False

# --- 1. Contact number: 5 down, bold, font 10 ---
print("1. patient_contact_no: +5 down, bold, font 10")
update_field("patient_contact_no", dy=5, font_size=10, bold=True)

# --- 2. Insurance card ID number: 5 down, bold, font 10 ---
print("2. patient_insured_card_id: +5 down, bold, font 10")
update_field("patient_insured_card_id", dy=5, font_size=10, bold=True)

# --- 3. Policy number/name of corporate: 5 down, 20 left ---
print("3. patient_policy_corporate_name: +5 down, -20 left")
update_field("patient_policy_corporate_name", dy=5, dx=-20)

# --- 4. Employee ID: 5 down, font 10, bold ---
print("4. patient_employee_id: +5 down, font 10, bold")
update_field("patient_employee_id", dy=5, font_size=10, bold=True)

# --- 5. Other mediclaim checkboxes: Yes -30 left, No -40 left ---
print("5. patient_other_mediclaim_yes: -30 left, patient_other_mediclaim_no: -40 left")
update_field("patient_other_mediclaim_yes", dx=-30)
update_field("patient_other_mediclaim_no", dx=-40)

# --- 6. Company name: 5 down ---
print("6. patient_other_mediclaim_company_name: +5 down")
update_field("patient_other_mediclaim_company_name", dy=5)

# --- 7. Give details: 5 down ---
print("7. patient_other_mediclaim_details: +5 down")
update_field("patient_other_mediclaim_details", dy=5)

# --- 8. Family Physician checkboxes: 50 left, 3 down ---
print("8. Family Physician checkboxes: -50 left, +3 down")
update_field("patient_family_physician_yes", dx=-50, dy=3)
update_field("patient_family_physician_no", dx=-50, dy=3)

# --- 9. Name of family physician: 3 down, 10 left ---
print("9. patient_family_physician_name: +3 down, -10 left")
update_field("patient_family_physician_name", dy=3, dx=-10)

# --- 10. Contact number, if any: bold, font 10, 5 down ---
print("10. patient_family_physician_contact_no: bold, font 10, +5 down")
update_field("patient_family_physician_contact_no", dy=5, font_size=10, bold=True)

# --- 11. Insured email: 5 down, 15 left ---
print("11. patient_email_id: +5 down, -15 left")
update_field("patient_email_id", dy=5, dx=-15)

# --- 12. Section C: All doctor fields 5 down, contact_no & icd codes bold ---
print("\n12. Section C - all doctor fields +5 down:")
doctor_fields = [f for f in data["fields"] if f["field_id"].startswith("doctor_")]
bold_doctor_fields = {"doctor_contact_no", "doctor_icd10_code", "doctor_icd10_pcs_code"}

for field in doctor_fields:
    fid = field["field_id"]
    make_bold = fid in bold_doctor_fields
    update_field(fid, dy=5, bold=True if make_bold else None)

# Write back
with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print(f"\n--- {len(changes_log)} fields updated. JSON saved. ---")
