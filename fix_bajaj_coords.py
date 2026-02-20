#!/usr/bin/env python3
"""
Fix coordinates for Bajaj Allianz TPA Preauth Form.
Based on pdfplumber ground truth extraction.

The form layout (595.276 wide):
- Labels start at x~42
- Fill blanks are typically after the label's underline ends
- Many fields share a row (e.g. city + pin code on same line)

Key observations from ground truth:
PAGE 1:
  - Hospital Name line: y=168.3, label ends, blank after ~220
  - City/Pin Code line: y=200.7, city blank after ~90, pin code after "Pin Code:" ~357
  - State/Hosp Id line: y=216.9, state blank after ~95, hosp id after ~352
  - Landmark: y=233.1, blank after ~85
  - Contact/Fax/TPA/Email all on y=249.3, spread across the line
  - Patient name: y=292.6, blank after ~155
  - Gender/Age/DOB on y=308.6
  - Attendant/Contact on y=325.0
  - Contact/Card ID on y=341.2
  - Policy: y=357.4, blank after ~210
  - Employee ID: y=373.6, blank after ~97
  - Other mediclaim yes/no: y=389.8, checkboxes at ~338, ~408
  - Company name: y=406.0, blank after ~110
  - Give details: y=422.2, blank after ~100
  - Family physician yes/no/name: y=438.4
  - Contact number: y=454.6, blank after ~131
  - Email: y=470.8, blank after ~130
  - Doctor name/contact: y=507.3
  - Nature of illness: y=523.5, blank after ~300
  - Clinical findings: y=539.7, blank after ~170
  - Duration/First consultation: y=555.1
  - Past history: y=572.1, blank after ~230
  - Provisional diagnosis/ICD10: y=588.3
  - Treatment checkboxes: y=604.5 and y=620.7
  - Investigation details: y=636.9
  - Drug route: y=653.1
  - Surgery name/ICD10 PCS: y=685.5
  - Other treatments: y=701.7
  - Injury cause: y=717.9
  - Accident RTA/date: y=734.1
  - Police/FIR: y=750.3
  - Substance abuse: y=766.5
  - Test conducted: y=782.7
  - Maternity: y=798.9

PAGE 2:
  - Admission date: y=54.4, DD at x=128.5, MM at x~157, YY at x~185
  - Admission time: y=54.4, after "b) Time:" at x~290
  - Emergency/Planned: y=70.6, checkboxes at ~256, ~315
  - Expected days: y=86.8, after ~236
  - Room type: y=86.8, after ~293
  - Costs: Rs. column starts at x~266
  - History checkboxes: right side, x~378 area
  - History dates: after checkbox text
  - Declaration doctor: y=327.4
  - Qualification/Registration: y=343.6

PAGE 3:
  - Patient declaration name: y=305.2
  - Contact/Signature: y=321.4
"""

import json

# Load current schema
with open('analyzed/BAJAJ ALLIANZ TPA PREAUTH FORM.json', 'r') as f:
    schema = json.load(f)

fields = schema['fields']
fix_count = 0

def fix(field_id, x=None, y=None, font_size=None, max_width=None):
    global fix_count
    for f in fields:
        if f['field_id'] == field_id:
            old_x = f['coordinates']['x']
            old_y = f['coordinates']['y']
            if x is not None:
                f['coordinates']['x'] = x
            if y is not None:
                f['coordinates']['y'] = y
            if font_size is not None:
                f['font_size'] = font_size
            if max_width is not None:
                f['max_width'] = max_width
            fix_count += 1
            print(f"  Fixed {field_id}: ({old_x},{old_y}) -> ({f['coordinates']['x']},{f['coordinates']['y']})")
            return
    print(f"  WARNING: {field_id} not found!")

# ==================== PAGE 1 ====================
print("PAGE 1 FIXES:")

# Provider section
# Hospital Name: label "Hospital Name/nursing Home Name:" ends at text, blank line continues
# Label text goes to ~250, form blank area starts after that
fix('provider_hospital_name', x=250, y=168.3, font_size=8, max_width=300)

# City Name: label ends ~90, blank runs to "Pin Code:" at ~340
fix('provider_city_name', x=90, y=200.7, font_size=7, max_width=250)
# Pin Code: after "Pin Code:" label at ~357, boxes start ~365
fix('provider_pin_code', x=370, y=200.7, font_size=7, max_width=60)

# State Name: label ends ~95, blank runs to "Hosp Id:" at ~348
fix('provider_state_name', x=95, y=216.9, font_size=7, max_width=250)
# Hosp Id: after label at ~352, blank starts ~380
fix('provider_hosp_id', x=385, y=216.9, font_size=7, max_width=100)

# Landmark: label ends ~85, blank runs full width
fix('provider_landmark', x=90, y=233.1, font_size=6, max_width=450)

# Contact No / Fax / TPA desk / Email all on y=249.3
# "Hospital Contact No:" ends ~135, blank starts ~140
fix('provider_contact_no', x=140, y=249.3, font_size=7, max_width=80)
# "Fax No:" label at ~230, blank starts ~268
fix('provider_fax_no', x=268, y=249.3, font_size=7, max_width=50)
# "TPA desk No" at ~330, blank starts ~378
fix('provider_tpa_desk_no', x=378, y=249.3, font_size=7, max_width=50)
# "Email id:" at ~440, blank starts ~468
fix('provider_email_id', x=468, y=249.3, font_size=7, max_width=80)

# Patient section
# "a) Name of the Patient:" ends at ~155, blank starts after
fix('patient_name', x=160, y=292.6, font_size=8, max_width=380)

# Gender checkboxes: "Male" at ~100, "Female" at ~150
fix('patient_gender_male', x=100, y=308.6)
fix('patient_gender_female', x=145, y=308.6)

# Age: "Years" boxes at ~215-230, "Months" at ~270-285
fix('patient_age_years', x=225, y=308.6, font_size=8, max_width=25)
fix('patient_age_months', x=282, y=308.6, font_size=8, max_width=20)

# DOB: "D D" starts at ~380, then M M Y Y Y Y
fix('patient_dob', x=380, y=308.6, font_size=8, max_width=100)

# Attendant name: label "e) Name of the Attendant:" ends ~183, blank starts after
fix('patient_attendant_name', x=185, y=325.0, font_size=7, max_width=150)
# Attendant contact: "f) Contact number, if any:" at ~290, blank starts ~380
fix('patient_attendant_contact_no', x=380, y=325.0, font_size=7, max_width=100)

# Contact number: label ends ~115, blank starts after
fix('patient_contact_no', x=120, y=341.2, font_size=7, max_width=120)
# Insured card ID: label "h) Insured card ID number:" ends ~351, blank starts after
fix('patient_insured_card_id', x=355, y=341.2, font_size=7, max_width=120)

# Policy/Corporate: label ends ~210, blank starts after
fix('patient_policy_corporate_name', x=215, y=357.4, font_size=7, max_width=330)

# Employee ID: label ends ~97, blank starts after
fix('patient_employee_id', x=100, y=373.6, font_size=7, max_width=100)

# Other mediclaim: Yes/No checkboxes
# "Yes" at ~338, "No" at ~405
fix('patient_other_mediclaim_yes', x=340, y=389.8)
fix('patient_other_mediclaim_no', x=410, y=389.8)

# Company name: label "Company Name:" ends ~110, blank starts after
fix('patient_other_mediclaim_company_name', x=115, y=406.0, font_size=7, max_width=430)

# Give details: label ends ~100, blank starts after
fix('patient_other_mediclaim_details', x=105, y=422.2, font_size=7, max_width=440)

# Family physician: Yes at ~220, No at ~275
fix('patient_family_physician_yes', x=222, y=438.4)
fix('patient_family_physician_no', x=282, y=438.4)
# Family physician name: "m) Name of the family physician:" at ~330, blank after ~395
fix('patient_family_physician_name', x=350, y=438.4, font_size=7, max_width=195)

# Contact number: label ends ~131, blank starts after
fix('patient_family_physician_contact_no', x=135, y=454.6, font_size=7, max_width=100)

# Email: "o) Insured E-mail id" ends ~130, blank starts after
fix('patient_email_id', x=135, y=470.8, font_size=7, max_width=200)

# Doctor section
# Doctor name: label "a) Name of the treating doctor:" ends ~170, blank starts after
fix('doctor_name', x=175, y=507.3, font_size=8, max_width=200)
# Doctor contact: "b) Contact number:" at ~370, blank starts ~430
fix('doctor_contact_no', x=432, y=507.3, font_size=8, max_width=100)

# Illness nature: label ends ~285, blank starts after
fix('doctor_illness_nature', x=290, y=523.5, font_size=7, max_width=255)

# Clinical findings: label ends ~170, blank starts after
fix('doctor_clinical_findings', x=170, y=539.7, font_size=7, max_width=375)

# Duration days: after "present ailment:" ~167, box at ~175
fix('doctor_ailment_duration_days', x=173, y=555.1, font_size=8, max_width=15)
# First consultation date: "D D" starts at ~297
fix('doctor_first_consultation_date', x=297, y=555.1, font_size=8, max_width=130)

# Past history: label ends ~230, blank starts after
fix('doctor_past_ailment_history', x=235, y=572.1, font_size=7, max_width=310)

# Provisional diagnosis: label ends ~155, blank starts after
fix('doctor_provisional_diagnosis', x=160, y=588.3, font_size=7, max_width=260)
# ICD 10 Code: label "i. ICD 10 Code:" ends ~425, blank starts after
fix('doctor_icd10_code', x=430, y=588.3, font_size=7, max_width=80)

# Treatment type checkboxes
# Medical Management: checkbox before text at ~160
fix('doctor_treatment_medical_management', x=156, y=604.5)
# Surgical Management: checkbox at ~284
fix('doctor_treatment_surgical_management', x=284, y=604.5)
# Intensive care: checkbox at ~435
fix('doctor_treatment_intensive_care', x=434, y=604.5)
# Investigation: checkbox at ~155
fix('doctor_treatment_investigation', x=155, y=620.7)
# Non allopathic: checkbox at ~284
fix('doctor_treatment_non_allopathic', x=284, y=620.7)

# Investigation details: label ends ~330, blank starts after
fix('doctor_investigation_management_details', x=335, y=636.9, font_size=7, max_width=210)

# Drug administration: label ends ~185, blank starts after
fix('doctor_drug_administration_route', x=190, y=653.1, font_size=7, max_width=355)

# Surgery name: label ends ~205, blank starts after
fix('doctor_surgery_name', x=210, y=685.5, font_size=7, max_width=200)
# ICD 10 PCS Code: label ends ~423, blank starts after
fix('doctor_icd10_pcs_code', x=428, y=685.5, font_size=7, max_width=80)

# Other treatments: label ends ~220, blank starts after
fix('doctor_other_treatments_details', x=225, y=701.7, font_size=7, max_width=320)

# Injury cause: label ends ~145, blank starts after
fix('doctor_injury_cause', x=150, y=717.9, font_size=7, max_width=395)

# Accident RTA: Yes at ~180, No at ~210
fix('doctor_accident_rta_yes', x=183, y=734.1)
fix('doctor_accident_rta_no', x=213, y=734.1)
# Date of injury: "D D" starts at ~280
fix('doctor_accident_date_of_injury', x=280, y=734.1, font_size=8, max_width=140)

# Reported to police: Yes at ~148, No at ~180
fix('doctor_accident_reported_police_yes', x=150, y=750.3)
fix('doctor_accident_reported_police_no', x=180, y=750.3)
# FIR No: label ends ~292, blank starts after
fix('doctor_accident_fir_no', x=295, y=750.3, font_size=7, max_width=80)

# Substance abuse: Yes at ~345, No at ~370
fix('doctor_substance_abuse_yes', x=348, y=766.5)
fix('doctor_substance_abuse_no', x=375, y=766.5)

# Test conducted: Yes at ~200, No at ~230
fix('doctor_test_conducted_yes', x=202, y=782.7)
fix('doctor_test_conducted_no', x=232, y=782.7)

# Maternity: G checkbox at ~131, P at ~148, L at ~167, A at ~188
fix('doctor_maternity_g', x=133, y=798.9)
fix('doctor_maternity_p', x=150, y=798.9)
fix('doctor_maternity_l', x=170, y=798.9)
fix('doctor_maternity_a', x=192, y=798.9)
# Date of Delivery: "D D" at ~313
fix('doctor_maternity_date_of_delivery', x=313, y=799.7, font_size=7, max_width=100)
# LMP: "D D" at ~448
fix('doctor_maternity_lmp', x=448, y=799.7, font_size=7, max_width=100)


# ==================== PAGE 2 ====================
print("\nPAGE 2 FIXES:")

# Admission date: "D D" starts at ~128.5
fix('admission_date', x=129, y=55.2, font_size=8, max_width=75)
# Admission time: after "b) Time:" H H : M M, at ~286
fix('admission_time', x=290, y=54.4, font_size=8, max_width=45)

# Emergency/Planned checkboxes
fix('admission_type_emergency', x=258, y=70.6)
fix('admission_type_planned', x=318, y=70.6)

# Expected days: after label ends ~236, blank at ~240
fix('expected_stay_days', x=240, y=86.8, font_size=7, max_width=25)
# Room type: after "e) Room Type" at ~293, blank at ~298
fix('room_type', x=298, y=86.8, font_size=7, max_width=70)

# Cost fields: Rs. at x=256, values should go at ~270
fix('cost_room_nursing_diet', x=270, y=119.2, font_size=8, max_width=80)
fix('cost_investigation_diagnostics', x=270, y=135.4, font_size=8, max_width=80)
fix('cost_icu_charges', x=270, y=151.6, font_size=8, max_width=80)
fix('cost_ot_charges', x=270, y=167.8, font_size=8, max_width=80)
fix('cost_professional_fees', x=270, y=184.0, font_size=8, max_width=80)
fix('cost_medicines_consumables_implants', x=270, y=216.4, font_size=8, max_width=80)
fix('cost_all_inclusive_package', x=270, y=248.8, font_size=8, max_width=80)
fix('cost_total_expected_hospitalization', x=270, y=265.0, font_size=8, max_width=80)

# History checkboxes - they're on the RIGHT side of the page
# Diabetes at y=54.4, checkbox ~375
fix('history_diabetes_checkbox', x=375, y=54.4)
fix('history_diabetes_date', x=500, y=54.4, font_size=7, max_width=55)

# Heart Disease at y=70.6
fix('history_heart_disease_checkbox', x=375, y=70.6)
fix('history_heart_disease_date', x=500, y=70.6, font_size=7, max_width=55)

# Hypertension at y=86.8
fix('history_hypertension_checkbox', x=375, y=86.8)
fix('history_hypertension_date', x=500, y=86.8, font_size=7, max_width=55)

# Hyperlipidemia at y=103.0
fix('history_hyperlipidemia_checkbox', x=375, y=103.0)
fix('history_hyperlipidemia_date', x=500, y=103.0, font_size=7, max_width=55)

# Osteoarthritis at y=119.2
fix('history_osteoarthritis_checkbox', x=375, y=119.2)
fix('history_osteoarthritis_date', x=500, y=119.2, font_size=7, max_width=55)

# Asthma/COPD at y=135.4
fix('history_asthma_copd_bronchitis_checkbox', x=375, y=135.4)
fix('history_asthma_copd_bronchitis_date', x=500, y=135.4, font_size=7, max_width=55)

# Cancer at y=151.6
fix('history_cancer_checkbox', x=375, y=151.6)
fix('history_cancer_date', x=500, y=151.6, font_size=7, max_width=55)

# Alcohol/drug abuse at y=167.8
fix('history_alcohol_drug_abuse_checkbox', x=375, y=167.8)
fix('history_alcohol_drug_abuse_date', x=500, y=167.8, font_size=7, max_width=55)

# HIV/STD at y=184.0
fix('history_hiv_std_checkbox', x=375, y=184.0)
fix('history_hiv_std_date', x=500, y=184.0, font_size=7, max_width=55)

# Other ailment: label ends ~475, blank at ~480
fix('history_other_ailment_details', x=480, y=200.2, font_size=7, max_width=70)

# Declaration doctor name: label ends ~215, blank starts after
fix('declaration_doctor_name', x=220, y=327.4, font_size=8, max_width=325)

# Qualification: label "b) Qualification:" ends ~115, blank starts after
fix('declaration_doctor_qualification', x=120, y=343.6, font_size=7, max_width=180)
# Registration No: label ends ~409, blank starts after
fix('declaration_doctor_registration_no', x=415, y=343.6, font_size=7, max_width=130)

# Hospital Seal box: at x=66, y=412.8
fix('declaration_hospital_seal', x=66, y=430, font_size=7, max_width=140)
# Patient signature: at x=402
fix('declaration_patient_signature', x=402, y=430, font_size=7, max_width=120)


# ==================== PAGE 3 ====================
print("\nPAGE 3 FIXES:")

# Patient declaration name: label ends ~210, blank starts after
fix('patient_declaration_name', x=215, y=305.2, font_size=8, max_width=330)

# Contact number: label ends ~113, blank starts after
fix('patient_declaration_contact_no', x=118, y=321.4, font_size=8, max_width=100)

# Patient signature: at right side, ~380
fix('patient_declaration_signature', x=495, y=321.4, font_size=7, max_width=100)

# Hospital seal: at x=42
fix('hospital_declaration_seal', x=42, y=645, font_size=7, max_width=140)
# Doctor signature: at x=341
fix('hospital_declaration_doctor_signature', x=410, y=645, font_size=7, max_width=140)

# Save fixed schema
print(f"\nTotal fixes: {fix_count}")
with open('analyzed/BAJAJ ALLIANZ TPA PREAUTH FORM.json', 'w') as f:
    json.dump(schema, f, indent=2)
print("Saved!")
