# Expected Output Example

## When you run: `python quick_test.py`

```
============================================================
TPA FORM AUTOMATION - QUICK TEST
============================================================

[1/3] Analyzing form structure...
============================================================
ANALYZING FORM STRUCTURE
============================================================
Template: /mnt/user-data/uploads/Ericson_TPA_Preauth.pdf
✓ Detected 17 fields across 6 pages
✓ Form analysis complete
✓ Form structure saved to: analyzed/amrita_form_structure.json

[2/3] Loading test data...
✓ Loaded data for patient: Rajesh Kumar

[3/3] Filling form...
============================================================
FILLING TPA FORM
============================================================
Processing page 1/6...
Processing page 2/6...
Processing page 3/6...
Processing page 4/6...
Processing page 5/6...
Processing page 6/6...

✓ Form filled successfully!
✓ Saved to: output/filled_tpa_form_test.pdf

============================================================
TEST COMPLETE
============================================================
✓ Filled form: output/filled_tpa_form_test.pdf
============================================================
```

## When you run: `python tpa_form_filler.py`

```
============================================================
TPA FORM AUTOMATION SYSTEM
============================================================

============================================================
ANALYZING FORM STRUCTURE
============================================================
Template: templates/amrita_preauth.pdf
✓ Detected 17 fields across 6 pages
✓ Form analysis complete
✓ Form structure saved to: analyzed/amrita_form_structure.json

============================================================
TPA FORM DATA COLLECTION
============================================================
Please provide the following information:

--- PATIENT INFORMATION ---
Patient Name: Rajesh Kumar
Age (years): 45
Gender (Male/Female/Third Gender) [Male]: Male
Date of Birth (DD/MM/YYYY): 15/08/1979
Contact Number: 9876543210

--- INSURANCE INFORMATION ---
Policy Number: POL/2024/12345
Card ID: AIMS/2024/001

--- DOCTOR INFORMATION ---
Treating Doctor Name: Dr. Amit Verma
Doctor Contact Number: 9123456780
Diagnosis/Illness: Acute Coronary Syndrome

--- ADMISSION INFORMATION ---
Admission Type (Emergency/Planned) [Emergency]: Emergency
Expected Hospital Stay (days): 5

--- COST ESTIMATES (in INR) ---
Room Rent per day: 3000
Investigation Cost: 15000
Total Estimated Cost: 77000

✓ Data collection complete

============================================================
FILLING TPA FORM
============================================================
Processing page 1/6...
Processing page 2/6...
Processing page 3/6...
Processing page 4/6...
Processing page 5/6...
Processing page 6/6...

✓ Form filled successfully!
✓ Saved to: output/filled_tpa_form.pdf

============================================================
PROCESS COMPLETE
============================================================
✓ Filled form: output/filled_tpa_form.pdf
✓ Structure file: analyzed/amrita_form_structure.json

You can now view the filled form!
============================================================
```

## Generated Files

### 1. `analyzed/amrita_form_structure.json`
```json
{
  "template_id": "AMRITA_001",
  "hospital_name": "Amrita Institute of Medical Sciences",
  "total_pages": 6,
  "fields": [
    {
      "field_id": "patient_name",
      "label": "Name of the Patient",
      "type": "text_line",
      "page": 1,
      "coordinates": {
        "x": 200,
        "y": 310
      },
      "font_size": 10,
      "required": true
    },
    {
      "field_id": "gender",
      "label": "Gender",
      "type": "text_line",
      "page": 1,
      "coordinates": {
        "x": 180,
        "y": 335
      },
      "font_size": 10
    },
    ... (15 more fields)
  ]
}
```

### 2. `output/filled_tpa_form.pdf`

Visual representation of what gets filled:

```
PAGE 1:
┌─────────────────────────────────────────────────────────┐
│ REQUEST FOR CASHLESS HOSPITALISATION                   │
│                                                         │
│ Hospital: Amrita Institute of Medical Sciences          │
│ Address: Mata Amritanandamayi Marg Sector-88 Faridabad│
│                                                         │
│ TO BE FILLED BY INSURED/PATIENT                        │
│                                                         │
│ A. Name of Patient:  RAJESH KUMAR                      │ ← Filled
│                                                         │
│ B. Gender:  Male                                       │ ← Filled
│                                                         │
│ C. Age: 45                                             │ ← Filled
│                                                         │
│ D. Date of Birth: 15/08/1979                           │ ← Filled
│                                                         │
│ E. Contact number: 9876543210                          │ ← Filled
│                                                         │
│ G. Insured Card ID: AIMS/2024/001                      │ ← Filled
│                                                         │
│ H. Policy number: POL/2024/12345                       │ ← Filled
│                                                         │
└─────────────────────────────────────────────────────────┘

PAGE 2:
┌─────────────────────────────────────────────────────────┐
│ TO BE FILLED BY TREATING DOCTOR/HOSPITAL               │
│                                                         │
│ A. Name of treating Doctor: Dr. Amit Verma             │ ← Filled
│                                                         │
│ B. Contact number: 9123456780                          │ ← Filled
│                                                         │
│ C. Nature of Illness: Acute Coronary Syndrome          │ ← Filled
│                                                         │
└─────────────────────────────────────────────────────────┘

PAGE 3:
┌─────────────────────────────────────────────────────────┐
│ DETAILS OF PATIENT ADMITTED                            │
│                                                         │
│ A. Date of admission: 17/02/2026                       │ ← Auto-filled
│                                                         │
│ B. Time of admission: 15:30                            │ ← Auto-filled
│                                                         │
│ C. Emergency ☑  Planned ☐                              │ ← Checkboxes
│                                                         │
│ E. Expected Days: 5                                    │ ← Filled
│                                                         │
│ H. Room Rent: 3000                                     │ ← Filled
│                                                         │
│ I. Investigation Cost: 15000                           │ ← Filled
│                                                         │
│ P. Total Estimated Cost: 77000                         │ ← Filled
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## File Sizes (Approximate)

- `amrita_form_structure.json`: 3-5 KB
- `filled_tpa_form.pdf`: Same as original (~150-200 KB)
- `sample_test_data.json`: < 1 KB

## Verification Steps

After running the script:

1. **Check output directory:**
   ```bash
   ls -lh output/
   # Should show: filled_tpa_form.pdf
   ```

2. **Open the PDF:**
   ```bash
   # Linux
   xdg-open output/filled_tpa_form.pdf
   
   # Mac
   open output/filled_tpa_form.pdf
   
   # Windows
   start output/filled_tpa_form.pdf
   ```

3. **Verify filled fields:**
   - Patient name appears in UPPERCASE
   - All numeric fields have values
   - Emergency checkbox is marked (✓)
   - Text is readable and properly positioned

4. **Check structure file:**
   ```bash
   cat analyzed/amrita_form_structure.json | python -m json.tool
   # Should show properly formatted JSON
   ```

## Common Results

### ✅ Success Indicators
- Script completes without errors
- PDF file created in output/
- File size > 0 bytes
- Opening PDF shows filled text
- Fields are aligned properly

### ⚠️ Warning Signs
- Text appears but misaligned → Adjust coordinates
- Some fields missing → Add to field definitions
- Checkboxes not marked → Verify checkbox coordinates
- Empty PDF → Check template path is correct

## Performance Metrics

For a typical 6-page TPA form:
- Analysis time: < 2 seconds
- Data collection: 2-3 minutes (interactive mode)
- Form filling: < 1 second
- Total process: < 5 seconds (batch mode)

## Next Test: Your Own Data

Edit `sample_test_data.json` with your patient's information:

```json
{
  "patient_name": "Your Patient Name",
  "age_years": "30",
  "doctor_name": "Your Doctor Name",
  ... etc
}
```

Then run:
```bash
python quick_test.py
```

The filled form will appear in `output/filled_tpa_form_test.pdf`
