# TPA Form Analysis & Filling Workflow

This guide outlines the step-by-step process for adding new TPA forms to the system. The workflow involves analyzing the PDF, generating test data, verifying the output, and refining the coordinate mapping.

## Prerequisites

Ensure you have the following files in place:
- **PDF Template**: Place the blank PDF form in the `templates/` directory.
- **Environment**: Ensure your `.env` file has a valid `GEMINI_API_KEY`.

---

## Workflow Steps

### 1. Analyze the PDF Form
Run the Gemini analyzer to detect form fields and their coordinates. This script uses a hybrid approach (pdfplumber + Gemini) for high accuracy.

**Command:**
```bash
python gemini_analyzer.py "templates/<Your_Form_Name>.pdf"
```

**Example:**
```bash
python gemini_analyzer.py "templates/Star Health Preauth.pdf"
```

**Output:**
- `analyzed/<Your_Form_Name>.json`: The structured schema with field coordinates.
- `analyzed/<Your_Form_Name>_gemini_raw.json`: Raw response for debugging.

---

### 2. Generate Test Data
Create a dummy data file to test the field mapping. We have a helper script that reads the analyzed schema and generates a JSON file with placeholder values for every field.

**Command:**
```bash
python scripts/generate_test_data.py "analyzed/<Your_Form_Name>.json"
```

**Example:**
```bash
python scripts/generate_test_data.py "analyzed/Star Health Preauth.json"
```

**Output:**
- `test_data/<Your_Form_Name>_test_data.json`: A JSON file containing test values for all detected fields.

---

### 3. Run Test Fill
Fill the PDF with the generated test data to visually verify the alignment of fields.

**Command:**
```bash
python scripts/test_fill.py --template "templates/<Your_Form_Name>.pdf" --schema "analyzed/<Your_Form_Name>.json" --data "test_data/<Your_Form_Name>_test_data.json" --output "output/<Your_Form_Name>_filled.pdf"
```

**Example:**
```bash
python scripts/test_fill.py --template "templates/Star Health Preauth.pdf" --schema "analyzed/Star Health Preauth.json" --data "test_data/Star Health Preauth_test_data.json" --output "output/Star_Health_filled.pdf"
```

**Output:**
- `output/<Your_Form_Name>_filled.pdf`: The filled PDF form.

---

### 4. Review and Refine Coordinates
Open the generated PDF (`output/<Your_Form_Name>_filled.pdf`) and check if the text aligns correctly with the blanks/boxes.

If alignment is off:
1.  Open `analyzed/<Your_Form_Name>.json` in your editor.
2.  Find the `field_id` corresponding to the misaligned text.
3.  Adjust the `coordinates` manually:
    -   **x**: Increase to move right, decrease to move left.
    -   **y**: Increase to move down, decrease to move up (origin is top-left).
4.  Save the JSON file.
5.  Re-run the **Test Fill** command (Step 3) to verify the fix.
6.  Repeat until perfect.

---

### 5. Finalize
Once the form is perfectly calibrated:
1.  (Optional) Add the form configuration to the `FORMS` list in `scripts/test_fill.py` for easier future testing.
2.  Commit the new template, schema, and test data to the repository.
