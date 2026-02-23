"""Fix problematic coordinates in Heritage Health Pre-Auth Form JSON."""
import json

JSON_PATH = "analyzed/Heritage-Health-Pre-Auth-Form.json"

with open(JSON_PATH) as f:
    data = json.load(f)

# Targeted fixes based on ground truth pdfplumber positions
fixes = {
    # Page 1
    "age_years": {"x": 130, "y": 404.0, "max_width": 60},
    "age_month": {"x": 230, "y": 404.0, "max_width": 60},
    "date_of_birth": {"x": 195, "y": 427.2, "max_width": 200},

    # Page 2: treatment checkboxes - each on its own line (y=304,316,328,339,351)
    "treatment_medical_management": {"x": 350, "y": 304.0},
    "treatment_surgical_management": {"x": 350, "y": 316.0},
    "treatment_intensive_care": {"x": 350, "y": 328.0},
    "treatment_investigation": {"x": 350, "y": 339.0},
    "treatment_non_allopathic": {"x": 350, "y": 351.0},

    # Page 2: text fields pushed to far right (x>500)
    "investigation_medical_management_details": {"x": 380, "max_width": 150},
    "route_of_drug_administration": {"x": 280, "max_width": 250},
    "icd_10_pcs_code": {"x": 220, "max_width": 300},

    # Page 3: fields pushed to far right
    "date_of_admission": {"x": 250, "y": 73.9, "max_width": 200},
    "time_of_admission_hh": {"x": 260, "y": 97.0, "max_width": 50},
    "time_of_admission_mm": {"x": 350, "y": 97.0, "max_width": 50},
    "hospitalization_event_emergency": {"x": 453.0, "y": 124.5},
    "hospitalization_event_planned": {"x": 513.0, "y": 124.5},
    "chronic_illness_since_month_year": {"x": 400, "max_width": 130},
    "chronic_illness_diabetes": {"x": 170, "max_width": 370},
    "chronic_illness_heart_disease": {"x": 190, "max_width": 350},
    "chronic_illness_hypertension": {"x": 190, "max_width": 350},
    "chronic_illness_hyperlipidemias": {"x": 200, "max_width": 340},
    "chronic_illness_osteoarthritis": {"x": 190, "max_width": 350},
    "chronic_illness_asthma_copd_bronchitis": {"x": 230, "max_width": 310},
    "chronic_illness_cancer": {"x": 170, "max_width": 370},
    "chronic_illness_alcohol_drug_abuse": {"x": 220, "max_width": 320},
    "chronic_illness_hiv_std": {"x": 280, "max_width": 260},
    "chronic_illness_other_details": {"x": 280, "max_width": 260},
    "expected_days_stay_hospital": {"x": 340, "max_width": 100},
    "days_in_icu": {"x": 250, "max_width": 200},
    "per_day_room_rent_nursing_service_diet": {"x": 400, "max_width": 140},
    "expected_cost_investigation_diagnostic": {"x": 350, "max_width": 190},
    "professional_fees_surgeon_anesthetist_consultation": {"x": 400, "max_width": 140},
    "medicines_consumables_implants_cost": {"x": 400, "max_width": 140},

    # Page 4
    "declaration_treating_doctor_qualification": {"x": 200, "y": 125.0},

    # Page 5
    "patient_representative_name": {"x": 250, "y": 373.0},
    "patient_representative_contact_number": {"x": 215, "y": 396.0},
    "patient_representative_email_id": {"x": 400, "y": 396.0, "max_width": 140},
    "patient_representative_date": {"x": 145, "y": 444.0},
    "patient_representative_time": {"x": 370, "y": 444.0},

    # Page 6
    "hospital_declaration_date": {"x": 110, "y": 289.0},
    "hospital_declaration_time": {"x": 210, "y": 289.0},
}

fixed = 0
for field in data["fields"]:
    fid = field["field_id"]
    if fid in fixes:
        for key, val in fixes[fid].items():
            if key in ("x", "y"):
                field["coordinates"][key] = val
            else:
                field[key] = val
        fixed += 1
        cx = field["coordinates"]["x"]
        cy = field["coordinates"]["y"]
        print(f"  Fixed {fid}: x={cx}, y={cy}")

# Remove unnecessary metadata keys
for key in ["template_id", "hospital_name", "analysis_model"]:
    data.pop(key, None)

with open(JSON_PATH, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print(f"\nFixed {fixed} fields. JSON saved.")
