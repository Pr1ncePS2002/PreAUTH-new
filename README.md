# TPA Form Automation System

Automate filling of TPA (Third Party Administrator) pre-authorization forms for health insurance without using LLMs.

## 🎯 What This Does

This system:
1. **Analyzes** blank TPA forms to identify field locations
2. **Collects** patient/doctor/cost data (via CLI or JSON)
3. **Fills** the PDF form programmatically at precise coordinates
4. **Validates** the output (optional)

**NO LLM REQUIRED** - Uses only Python libraries (PyPDF2, ReportLab)

## 📋 Features

- ✅ Works with 30-40 different TPA forms (scalable architecture)
- ✅ Pre-defined field mappings (no AI needed for filling)
- ✅ Batch processing with JSON input
- ✅ Interactive CLI data collection
- ✅ Coordinate-based precise text placement
- ✅ Checkbox marking support
- ✅ Multi-page form support
- ✅ Reusable form structure definitions

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- pip

### Installation

```bash
# 1. Clone or download the project
cd tpa-form-automation

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Place your blank TPA form in templates/
cp your_blank_form.pdf templates/

# 5. Run quick test
python quick_test.py
```

## 📁 Project Structure

```
tpa-form-automation/
│
├── tpa_form_filler.py          # Main automation script
├── quick_test.py               # Test with sample JSON data
├── requirements.txt            # Python dependencies
├── sample_test_data.json       # Example patient data
├── COPILOT_SETUP_GUIDE.md     # Detailed setup instructions
│
├── templates/                  # Blank TPA forms
│   └── amrita_preauth.pdf
│
├── analyzed/                   # Form structure JSONs
│   └── amrita_form_structure.json
│
└── output/                     # Filled PDFs
    └── filled_tpa_form.pdf
```

## 🎮 Usage

### Option 1: Interactive Mode

Collect data via command-line prompts:

```bash
python tpa_form_filler.py
```

You'll be prompted for:
- Patient information (name, age, DOB, contact)
- Insurance details (policy number, card ID)
- Doctor information (name, contact, diagnosis)
- Admission details (type, expected days)
- Cost estimates (room rent, tests, total)

### Option 2: Batch Mode (JSON Input)

Use pre-filled JSON data:

```bash
python quick_test.py
```

Edit `sample_test_data.json`:
```json
{
  "patient_name": "Rajesh Kumar",
  "age_years": "45",
  "gender": "Male",
  "dob": "15/08/1979",
  "contact": "9876543210",
  "policy_number": "POL/2024/12345",
  "card_id": "AIMS/2024/001",
  "doctor_name": "Dr. Amit Verma",
  "doctor_contact": "9123456780",
  "diagnosis": "Acute Coronary Syndrome",
  "admission_type": "Emergency",
  "expected_days": "5",
  "room_rent": "3000",
  "investigation_cost": "15000",
  "total_estimated_cost": "77000"
}
```

## 🔧 How It Works

### 1. Form Analysis Phase

```python
analyzer = FormAnalyzer("templates/form.pdf")
structure = analyzer.analyze()
```

**What it does:**
- Identifies form fields and their locations
- Detects field types (text, checkbox, etc.)
- Records coordinates for text placement
- Saves structure as JSON for reuse

**Output:**
```json
{
  "template_id": "AMRITA_001",
  "fields": [
    {
      "field_id": "patient_name",
      "label": "Name of the Patient",
      "type": "text_line",
      "page": 1,
      "coordinates": {"x": 200, "y": 310},
      "font_size": 10
    }
  ]
}
```

### 2. Data Mapping Phase

```python
field_values = map_data_to_fields(user_data)
```

**What it does:**
- Maps user data to form field IDs
- Applies formatting (uppercase, dates, etc.)
- Handles conditional fields (checkboxes)

### 3. Form Filling Phase

```python
filler = TPAFormFiller(template, structure)
filled_pdf = filler.fill_form(data, "output.pdf")
```

**What it does:**
- Creates overlay canvas for each page
- Writes text at exact coordinates
- Marks checkboxes
- Merges overlay with blank template
- Saves final filled PDF

## 🎯 Key Components

### FormAnalyzer
Analyzes blank forms and creates structure definitions.

```python
from tpa_form_filler import FormAnalyzer

analyzer = FormAnalyzer("templates/my_form.pdf")
structure = analyzer.analyze()
```

### TPAFormFiller
Fills forms with provided data.

```python
from tpa_form_filler import TPAFormFiller

filler = TPAFormFiller(template_path, form_structure)
output = filler.fill_form(data, "output.pdf")
```

## 📊 Supported Field Types

| Type | Description | Example |
|------|-------------|---------|
| `text_line` | Text on a line (not boxed) | Name, Address |
| `text_box` | Text inside bordered box | Age, Date |
| `checkbox` | Checkboxes for options | Gender, Yes/No |

## 🔍 Coordinate System

PDFs use bottom-left origin:
- X-axis: Left (0) → Right (595 for A4)
- Y-axis: Bottom (0) → Top (842 for A4)

Convert top-based coordinates:
```python
pdf_y = 842 - screen_y
```

## 🛠️ Customization

### Adding New TPA Forms

1. **Analyze the form:**
```python
analyzer = FormAnalyzer("templates/new_form.pdf")
structure = analyzer.analyze()
```

2. **Adjust field coordinates** (if needed):
Edit the generated JSON in `analyzed/` folder

3. **Test filling:**
```python
filler = TPAFormFiller("templates/new_form.pdf", structure)
filler.fill_form(test_data, "output.pdf")
```

### Calibrating Coordinates

If text appears in wrong positions:

1. Open the blank form
2. Measure field positions (use PDF editor's coordinate display)
3. Update coordinates in structure JSON:

```json
{
  "field_id": "patient_name",
  "coordinates": {"x": 200, "y": 310}  // Adjust these
}
```

## 📝 Example Output

**Input Data:**
```json
{
  "patient_name": "Rajesh Kumar",
  "age_years": "45",
  "doctor_name": "Dr. Amit Verma"
}
```

**Result:**
- ✅ "RAJESH KUMAR" written at coordinates (200, 310)
- ✅ "45" written at coordinates (180, 360)
- ✅ "Dr. Amit Verma" written at coordinates (220, 80) on page 2
- ✅ PDF saved to `output/filled_tpa_form.pdf`

## 🔄 Workflow for 30-40 Forms

```
1. One-time: Analyze each TPA form → Save structure JSON
   ├── amrita_structure.json
   ├── star_health_structure.json
   └── hdfc_ergo_structure.json

2. Runtime: Match insurer → Load structure → Fill form
   └── Auto-select correct template based on insurance card
```

## 🐛 Troubleshooting

### Text Not Appearing
- Check coordinates are correct for your PDF
- Verify font size isn't too small
- Open in Adobe Reader (not browser preview)

### Import Errors
```bash
pip install --upgrade PyPDF2 reportlab
```

### Coordinate Issues
Use this helper to visualize coordinates:

```python
def draw_debug_grid(pdf_path):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas("grid.pdf")
    for x in range(0, 600, 50):
        c.drawString(x, 820, str(x))
    c.save()
```

## 📚 Dependencies

- **PyPDF2** (3.0.1): PDF reading/writing
- **ReportLab** (4.0.7): PDF generation/overlay
- **pdfplumber** (0.10.3): PDF analysis (optional)
- **opencv-python** (4.8.1): Image processing (optional)

## 🚀 Future Enhancements

- [ ] Auto-detect field coordinates using OpenCV
- [ ] OCR validation of filled forms
- [ ] Web interface for data entry
- [ ] Integration with Hospital Management Systems
- [ ] Signature image placement
- [ ] Multi-language support
- [ ] Batch processing from Excel/CSV

## 📄 License

This is a demonstration project. Adapt for your use case.

## 🤝 Contributing

To add support for new TPA forms:
1. Analyze the blank form
2. Create structure JSON
3. Test filling
4. Submit structure definition

## 📧 Support

For issues:
1. Check COPILOT_SETUP_GUIDE.md
2. Verify all dependencies installed
3. Test with sample_test_data.json first

## 🎓 Learn More

- [PDF Coordinate System](https://www.adobe.com/content/dam/acom/en/devnet/pdf/pdfs/pdf_reference_archives/PDFReference.pdf)
- [ReportLab User Guide](https://www.reportlab.com/docs/reportlab-userguide.pdf)
- [PyPDF2 Documentation](https://pypdf2.readthedocs.io/)

---

**Built with ❤️ for healthcare automation**
