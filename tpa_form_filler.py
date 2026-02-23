#!/usr/bin/env python3
"""
TPA Form Automation Script
Analyzes and fills TPA pre-authorization forms without using LLM
"""

import json
from datetime import datetime
from pathlib import Path
import sys

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from PyPDF2 import PdfReader, PdfWriter
    import io
except ImportError:
    print("ERROR: Required packages not installed.")
    print("Please run: pip install reportlab PyPDF2")
    sys.exit(1)


class TPAFormFiller:
    """Fills TPA forms with provided data"""
    
    def __init__(self, template_path, form_structure):
        self.template_path = template_path
        self.form_structure = form_structure
        
    def fill_form(self, data, output_path):
        """
        Main method to fill the form
        
        Args:
            data: Dictionary with patient/doctor/cost information
            output_path: Where to save the filled PDF
        """
        print("\n" + "="*60)
        print("FILLING TPA FORM")
        print("="*60)
        
        # Load the blank template
        template = PdfReader(self.template_path)
        output = PdfWriter()
        
        # Map data to field values
        field_values = self._map_data_to_fields(data)
        
        # Process each page
        total_pages = len(template.pages)
        for page_num in range(total_pages):
            print(f"Processing page {page_num + 1}/{total_pages}...")
            page = template.pages[page_num]
            
            # Get fields for this page
            page_fields = self._get_fields_for_page(page_num + 1)
            
            if page_fields:
                # Create overlay with data
                overlay = self._create_overlay(page_num + 1, page_fields, field_values)
                
                # Merge overlay with template page
                if overlay:
                    page.merge_page(overlay.pages[0])
            
            output.add_page(page)
        
        # Save filled PDF
        with open(output_path, 'wb') as f:
            output.write(f)
        
        print(f"\n✓ Form filled successfully!")
        print(f"✓ Saved to: {output_path}")
        
        return output_path
    
    def _map_data_to_fields(self, data):
        """Maps user input data to form field IDs.
        
        Supports direct field_id keys from analyzed JSON structure.
        Also handles convenience aliases like 'gender' -> gender_male/gender_female/gender_third checkboxes.
        """
        field_values = {}
        
        # Handle gender convenience alias -> checkbox fields
        gender = data.get('gender', '')
        if gender:
            field_values['gender_male'] = (gender == 'Male')
            field_values['gender_female'] = (gender == 'Female')
            field_values['gender_third'] = (gender == 'Third Gender')
        
        # Pass through ALL data keys directly as field_id values
        # This works because sample_test_data.json uses exact field_id names
        for key, value in data.items():
            if key == 'gender':
                continue  # Already handled above as checkboxes
            if key not in field_values:
                if isinstance(value, bool):
                    field_values[key] = value
                elif value is not None:
                    field_values[key] = str(value)
                else:
                    field_values[key] = ''
        
        return field_values
    
    def _get_fields_for_page(self, page_num):
        """Get all fields that belong to a specific page"""
        return [
            field for field in self.form_structure['fields']
            if field['page'] == page_num
        ]
    
    def _get_page_height(self, page_num):
        """Get the actual page height for coordinate conversion"""
        page_heights = self.form_structure.get('page_heights', {})
        return float(page_heights.get(str(page_num), 842))

    def _get_page_width(self, page_num):
        """Get the actual page width for coordinate conversion"""
        page_widths = self.form_structure.get('page_widths', {})
        return float(page_widths.get(str(page_num), A4[0]))

    def _create_overlay(self, page_num, fields, field_values):
        """Creates an overlay with text/checkboxes for the page"""
        packet = io.BytesIO()
        # Use actual page dimensions for the canvas
        page_height = self._get_page_height(page_num)
        page_width = self._get_page_width(page_num)
        page_size = (page_width, page_height)
        can = canvas.Canvas(packet, pagesize=page_size)
        
        # Set default font
        can.setFont("Helvetica", 10)
        
        for field in fields:
            field_id = field['field_id']
            value = field_values.get(field_id)
            
            if value is None or value == '':
                continue
            
            # Fill based on field type
            if field['type'] in ('text_line', 'date_field'):
                self._fill_text_line(can, field, value, page_num)
            
            elif field['type'] == 'text_box':
                self._fill_text_box(can, field, value, page_num)
            
            elif field['type'] == 'checkbox':
                self._fill_checkbox(can, field, value, page_num)
        
        can.save()
        packet.seek(0)
        
        return PdfReader(packet)
    
    def _fill_text_line(self, canvas_obj, field, value, page_num):
        """Fills text on a line"""
        x = field['coordinates']['x']
        # PDF coordinate system: origin at bottom-left
        # Convert from top-left (pdfplumber) to bottom-left (reportlab)
        page_height = self._get_page_height(page_num)
        y = page_height - field['coordinates']['y']
        
        font_size = field.get('font_size', 10)
        font_name = "Helvetica-Bold" if field.get('bold') else "Helvetica"
        canvas_obj.setFont(font_name, font_size)
        canvas_obj.drawString(x, y, str(value))
    
    def _fill_text_box(self, canvas_obj, field, value, page_num):
        """Fills text inside a bordered box"""
        x = field['coordinates']['x'] + 2  # Small padding
        page_height = self._get_page_height(page_num)
        y = page_height - field['coordinates']['y'] - field.get('height', 20) + 5
        
        font_size = field.get('font_size', 10)
        font_name = "Helvetica-Bold" if field.get('bold') else "Helvetica"
        canvas_obj.setFont(font_name, font_size)
        canvas_obj.drawString(x, y, str(value))
    
    def _fill_checkbox(self, canvas_obj, field, value, page_num):
        """Marks a checkbox if value is True"""
        if value is True:
            x = field['coordinates']['x']
            page_height = self._get_page_height(page_num)
            y = page_height - field['coordinates']['y']
            canvas_obj.setFont("Helvetica-Bold", 12)
            canvas_obj.drawString(x + 2, y - 2, "X")


class FormAnalyzer:
    """Analyzes TPA form structure (simplified for this demo)"""
    
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
    
    def analyze(self):
        """
        For this demo, we're using a pre-defined structure
        In production, this would use OpenCV + pdfplumber to detect fields
        """
        print("\n" + "="*60)
        print("ANALYZING FORM STRUCTURE")
        print("="*60)
        print(f"Template: {self.pdf_path}")
        
        # Pre-defined structure for Amrita TPA form
        # In production, this would be auto-detected
        structure = {
            "template_id": "AMRITA_001",
            "hospital_name": "Amrita Institute of Medical Sciences",
            "total_pages": 6,
            "fields": [
                # PAGE 1 - Patient Information
                {
                    "field_id": "patient_name",
                    "label": "Name of the Patient",
                    "type": "text_line",
                    "page": 1,
                    "coordinates": {"x": 200, "y": 310},
                    "font_size": 10,
                    "required": True
                },
                {
                    "field_id": "gender",
                    "label": "Gender",
                    "type": "text_line",
                    "page": 1,
                    "coordinates": {"x": 180, "y": 335},
                    "font_size": 10
                },
                {
                    "field_id": "age_years",
                    "label": "Age (Years)",
                    "type": "text_line",
                    "page": 1,
                    "coordinates": {"x": 180, "y": 360},
                    "font_size": 10
                },
                {
                    "field_id": "dob",
                    "label": "Date of Birth",
                    "type": "text_line",
                    "page": 1,
                    "coordinates": {"x": 200, "y": 385},
                    "font_size": 10
                },
                {
                    "field_id": "contact",
                    "label": "Contact number",
                    "type": "text_line",
                    "page": 1,
                    "coordinates": {"x": 200, "y": 410},
                    "font_size": 10
                },
                {
                    "field_id": "policy_number",
                    "label": "Policy number",
                    "type": "text_line",
                    "page": 1,
                    "coordinates": {"x": 250, "y": 485},
                    "font_size": 10
                },
                {
                    "field_id": "card_id",
                    "label": "Insured Card ID",
                    "type": "text_line",
                    "page": 1,
                    "coordinates": {"x": 240, "y": 460},
                    "font_size": 10
                },
                
                # PAGE 2 - Medical Information
                {
                    "field_id": "doctor_name",
                    "label": "Name of treating Doctor",
                    "type": "text_line",
                    "page": 2,
                    "coordinates": {"x": 220, "y": 80},
                    "font_size": 10
                },
                {
                    "field_id": "doctor_contact",
                    "label": "Contact number",
                    "type": "text_line",
                    "page": 2,
                    "coordinates": {"x": 180, "y": 105},
                    "font_size": 10
                },
                {
                    "field_id": "diagnosis",
                    "label": "Nature of Illness",
                    "type": "text_line",
                    "page": 2,
                    "coordinates": {"x": 200, "y": 130},
                    "font_size": 10
                },
                
                # PAGE 3 - Admission Details
                {
                    "field_id": "admission_date",
                    "label": "Date of admission",
                    "type": "text_line",
                    "page": 3,
                    "coordinates": {"x": 200, "y": 80},
                    "font_size": 10
                },
                {
                    "field_id": "admission_time",
                    "label": "Time of admission",
                    "type": "text_line",
                    "page": 3,
                    "coordinates": {"x": 200, "y": 105},
                    "font_size": 10
                },
                {
                    "field_id": "emergency_check",
                    "label": "Emergency",
                    "type": "checkbox",
                    "page": 3,
                    "coordinates": {"x": 345, "y": 130}
                },
                {
                    "field_id": "planned_check",
                    "label": "Planned",
                    "type": "checkbox",
                    "page": 3,
                    "coordinates": {"x": 430, "y": 130}
                },
                {
                    "field_id": "expected_days",
                    "label": "Expected Days",
                    "type": "text_line",
                    "page": 3,
                    "coordinates": {"x": 300, "y": 330},
                    "font_size": 10
                },
                {
                    "field_id": "room_rent",
                    "label": "Room Rent",
                    "type": "text_line",
                    "page": 3,
                    "coordinates": {"x": 400, "y": 390},
                    "font_size": 10
                },
                {
                    "field_id": "investigation_cost",
                    "label": "Investigation Cost",
                    "type": "text_line",
                    "page": 3,
                    "coordinates": {"x": 400, "y": 415},
                    "font_size": 10
                },
                {
                    "field_id": "total_cost",
                    "label": "Total Cost",
                    "type": "text_line",
                    "page": 3,
                    "coordinates": {"x": 400, "y": 560},
                    "font_size": 10
                }
            ]
        }
        
        print(f"✓ Detected {len(structure['fields'])} fields across {structure['total_pages']} pages")
        print(f"✓ Form analysis complete")
        
        return structure


def collect_user_inputs():
    """Collects basic information from user"""
    print("\n" + "="*60)
    print("TPA FORM DATA COLLECTION")
    print("="*60)
    print("Please provide the following information:\n")
    
    data = {}
    
    # Patient Information
    print("--- PATIENT INFORMATION ---")
    data['patient_name'] = input("Patient Name: ").strip()
    data['age_years'] = input("Age (years): ").strip()
    data['gender'] = input("Gender (Male/Female/Third Gender) [Male]: ").strip() or "Male"
    data['dob'] = input("Date of Birth (DD/MM/YYYY): ").strip()
    data['contact'] = input("Contact Number: ").strip()
    
    # Policy Information
    print("\n--- INSURANCE INFORMATION ---")
    data['policy_number'] = input("Policy Number: ").strip()
    data['card_id'] = input("Card ID: ").strip()
    
    # Doctor Information
    print("\n--- DOCTOR INFORMATION ---")
    data['doctor_name'] = input("Treating Doctor Name: ").strip()
    data['doctor_contact'] = input("Doctor Contact Number: ").strip()
    data['diagnosis'] = input("Diagnosis/Illness: ").strip()
    
    # Admission Information
    print("\n--- ADMISSION INFORMATION ---")
    data['admission_type'] = input("Admission Type (Emergency/Planned) [Emergency]: ").strip() or "Emergency"
    data['expected_days'] = input("Expected Hospital Stay (days): ").strip()
    
    # Cost Estimates
    print("\n--- COST ESTIMATES (in INR) ---")
    data['room_rent'] = input("Room Rent per day: ").strip()
    data['investigation_cost'] = input("Investigation Cost: ").strip()
    data['total_estimated_cost'] = input("Total Estimated Cost: ").strip()
    
    print("\n✓ Data collection complete")
    
    return data


def save_form_structure(structure, output_path):
    """Saves analyzed form structure to JSON file"""
    with open(output_path, 'w') as f:
        json.dump(structure, f, indent=2)
    print(f"✓ Form structure saved to: {output_path}")


def main():
    """Main execution flow"""
    print("\n" + "="*60)
    print("TPA FORM AUTOMATION SYSTEM")
    print("="*60)
    
    # File paths
    template_path = "templates/amrita_preauth.pdf"
    structure_path = "analyzed/amrita_form_structure.json"
    output_path = "output/filled_tpa_form.pdf"
    
    # Check if template exists
    if not Path(template_path).exists():
        print(f"ERROR: Template not found at {template_path}")
        return
    
    # Step 1: Analyze form structure
    analyzer = FormAnalyzer(template_path)
    form_structure = analyzer.analyze()
    
    # Save structure for future use
    save_form_structure(form_structure, structure_path)
    
    # Step 2: Collect user inputs
    data = collect_user_inputs()
    
    # Step 3: Fill the form
    filler = TPAFormFiller(template_path, form_structure)
    filled_pdf_path = filler.fill_form(data, output_path)
    
    print("\n" + "="*60)
    print("PROCESS COMPLETE")
    print("="*60)
    print(f"✓ Filled form: {filled_pdf_path}")
    print(f"✓ Structure file: {structure_path}")
    print("\nYou can now view the filled form!")
    print("="*60 + "\n")
    
    return filled_pdf_path


if __name__ == "__main__":
    try:
        output_file = main()
    except KeyboardInterrupt:
        print("\n\nProcess interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
