#!/usr/bin/env python3
"""
Quick test script for TPA form filling using sample JSON data
"""

import json
from pathlib import Path
from tpa_form_filler import FormAnalyzer, TPAFormFiller, save_form_structure


def load_test_data(json_path):
    """Load test data from JSON file"""
    with open(json_path, 'r') as f:
        return json.load(f)


def main():
    print("\n" + "="*60)
    print("TPA FORM AUTOMATION - QUICK TEST")
    print("="*60)
    
    # File paths
    template_path = "templates/Ericson TPA Preauth.pdf"
    test_data_path = "sample_test_data.json"
    structure_path = "analyzed/Ericson TPA Preauth.json"
    output_path = "output/Ericson TPA Preauth_filled.pdf"
    
    # Check if template exists
    if not Path(template_path).exists():
        print(f"ERROR: Template not found at {template_path}")
        return
    
    # Step 1: Load pre-analyzed form structure (or analyze if not found)
    print("\n[1/3] Loading form structure...")
    if Path(structure_path).exists():
        with open(structure_path, 'r') as f:
            form_structure = json.load(f)
        print(f"✓ Loaded structure from: {structure_path}")
        print(f"✓ {len(form_structure['fields'])} fields across {form_structure['total_pages']} pages")
    else:
        print("  No pre-analyzed structure found, analyzing...")
        analyzer = FormAnalyzer(template_path)
        form_structure = analyzer.analyze()
        save_form_structure(form_structure, structure_path)
    
    # Step 2: Load test data
    print("\n[2/3] Loading test data...")
    data = load_test_data(test_data_path)
    print(f"✓ Loaded data for patient: {data['patient_name']}")
    
    # Step 3: Fill the form
    print("\n[3/3] Filling form...")
    filler = TPAFormFiller(template_path, form_structure)
    filled_pdf_path = filler.fill_form(data, output_path)
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)
    print(f"✓ Filled form: {filled_pdf_path}")
    print("="*60 + "\n")
    
    return filled_pdf_path


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
