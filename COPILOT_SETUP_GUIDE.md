# COPILOT SETUP PROMPT FOR TPA FORM AUTOMATION PROJECT

## Project Overview
Set up a Python-based TPA (Third Party Administrator) form automation system that:
- Analyzes PDF form structures (field locations, types, coordinates)
- Collects patient/doctor/cost data from user input
- Automatically fills TPA forms WITHOUT using LLM


## Environment Setup Instructions

### 1. Create Project Directory
```bash
mkdir tpa-form-automation
cd tpa-form-automation
```

### 2. Set Up Python Virtual Environment
```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate

# On Windows:
# venv\Scripts\activate
```

### 3. Install Required Dependencies
```bash
# Install all required packages
pip install --upgrade pip
pip install PyPDF2==3.0.1
pip install reportlab==4.0.7
pip install pdfplumber==0.10.3
pip install pdf2image==1.16.3
pip install pillow==10.1.0
pip install opencv-python==4.8.1.78
pip install numpy==1.26.2
pip install pytesseract==0.3.10
pip install python-dateutil==2.8.2

# Or install from requirements.txt:
pip install -r requirements.txt
```

### 4. Project Structure
Create the following directory structure:
```
tpa-form-automation/
├── venv/                          # Virtual environment (auto-created)
├── templates/                     # Store blank TPA forms here
│   └── amrita_preauth.pdf
├── analyzed/                      # Store form structure JSON files
│   └── amrita_form_structure.json
├── output/                        # Filled forms saved here
│   └── filled_tpa_form.pdf
├── test_data/                     # Sample test data
│   └── sample_test_data.json
├── tpa_form_filler.py            # Main automation script
├── quick_test.py                 # Quick test with JSON data
├── requirements.txt              # Python dependencies
└── README.md                     # Project documentation
```

### 5. Copy the Files
You need to copy these files into your project:
1. `tpa_form_filler.py` - Main script
2. `quick_test.py` - Test script
3. `requirements.txt` - Dependencies
4. `sample_test_data.json` - Test data
5. `Ericson_TPA_Preauth.pdf` - The blank TPA form (copy to templates/)

### 6. File Locations to Update
In the Python scripts, update these paths to match your setup:

**In `tpa_form_filler.py`:**
```python
# Line ~350 - Update these paths:
template_path = "templates/amrita_preauth.pdf"
structure_path = "analyzed/amrita_form_structure.json"
output_path = "output/filled_tpa_form.pdf"
```

**In `quick_test.py`:**
```python
# Line ~20 - Update these paths:
template_path = "templates/amrita_preauth.pdf"
test_data_path = "test_data/sample_test_data.json"
structure_path = "analyzed/amrita_form_structure.json"
output_path = "output/filled_tpa_form_test.pdf"
```

### 7. Create Necessary Directories
```bash
mkdir templates analyzed output test_data
```

### 8. Test the Setup
Run the quick test to verify everything works:
```bash
# Make sure virtual environment is activated
python quick_test.py
```

Expected output:
```
============================================================
TPA FORM AUTOMATION - QUICK TEST
============================================================

[1/3] Analyzing form structure...
✓ Detected 17 fields across 6 pages
✓ Form analysis complete
✓ Form structure saved to: analyzed/amrita_form_structure.json

[2/3] Loading test data...
✓ Loaded data for patient: Rajesh Kumar

[3/3] Filling form...
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

### 9. Run Interactive Mode
To collect data interactively from the user:
```bash
python tpa_form_filler.py
```

This will prompt you to enter:
- Patient information
- Insurance details
- Doctor information
- Admission details
- Cost estimates

## How It Works

### Phase 1: Form Analysis
The `FormAnalyzer` class:
- Loads the blank PDF template
- Identifies field locations (x, y coordinates)
- Determines field types (text_line, text_box, checkbox)
- Saves structure to JSON for reuse

### Phase 2: Data Collection
Two options:
1. **Interactive**: User enters data via command-line prompts
2. **Batch**: Load from JSON file (for testing/automation)

### Phase 3: Form Filling
The `TPAFormFiller` class:
- Loads the blank template PDF
- Creates overlay canvas for each page
- Writes text at calculated coordinates
- Marks checkboxes where needed
- Merges overlay with template
- Saves final filled PDF

### Phase 4: Output
- Filled PDF saved to output directory
- Structure JSON saved for future reference
- Console shows summary of what was filled

## Testing Checklist

- [ ] Virtual environment created and activated
- [ ] All dependencies installed (no import errors)
- [ ] Project directories created
- [ ] Blank TPA form copied to templates/
- [ ] Test data JSON available
- [ ] quick_test.py runs successfully
- [ ] Output PDF generated in output/
- [ ] Fields visible in output PDF (open in PDF reader)
- [ ] Interactive mode works (tpa_form_filler.py)

## Troubleshooting

### Issue: ImportError for PyPDF2 or reportlab
**Solution:**
```bash
pip install --upgrade PyPDF2 reportlab
```

### Issue: PDF not generated
**Solution:**
- Check file paths are correct
- Ensure templates directory exists
- Verify write permissions on output directory

### Issue: Text not appearing in PDF
**Solution:**
- Coordinates may need adjustment
- Open generated PDF in Adobe Reader (not browser)
- Check form_structure coordinates are accurate

### Issue: "Template not found"
**Solution:**
```bash
# Verify file exists:
ls templates/amrita_preauth.pdf

# If not, copy it:
cp /path/to/Ericson_TPA_Preauth.pdf templates/amrita_preauth.pdf
```

## Next Steps After Setup

1. **Test with real data**: Replace sample_test_data.json with actual patient data
2. **Adjust coordinates**: If text appears in wrong positions, modify coordinates in `form_structure`
3. **Add more fields**: Extend the field definitions to cover all form fields
4. **Add validation**: Implement data validation before filling
5. **Add OCR verification**: Use pytesseract to verify filled form is readable
6. **Scale to multiple forms**: Add analyzer for other TPA forms

## Advanced: Coordinate Calibration

If text doesn't appear in the right place, you can calibrate coordinates:

```python
# Add this to quick_test.py to see coordinate grid:
from reportlab.pdfgen import canvas

def draw_grid(pdf_path):
    """Draws coordinate grid on PDF for calibration"""
    c = canvas.Canvas("grid_overlay.pdf")
    
    # Draw grid lines every 50 points
    for x in range(0, 600, 50):
        c.drawString(x, 820, str(x))
        c.line(x, 0, x, 842)
    
    for y in range(0, 850, 50):
        c.drawString(10, y, str(842-y))
        c.line(0, y, 595, y)
    
    c.save()
```

## Support Files Needed

Make sure you have these files in your project:
1. ✅ tpa_form_filler.py
2. ✅ quick_test.py
3. ✅ requirements.txt
4. ✅ sample_test_data.json
5. ✅ Ericson_TPA_Preauth.pdf (blank form)

## Ready to Start!

Once setup is complete, you can:
- Run tests with sample data
- Modify coordinates for accurate placement
- Add more fields to the form structure
- Extend to support multiple TPA forms

Good luck! 🚀
