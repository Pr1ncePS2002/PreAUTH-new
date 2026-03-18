#!/usr/bin/env python3
"""
Test script for TPA form filling — supports all configured forms.
Usage: 
  python scripts/test_fill.py [form_number]
  python scripts/test_fill.py --template <path> --schema <path> --data <path> [--output <path>]
"""

import json
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tpa_form_filler import TPAFormFiller

# ── Registry of forms with test data ──────────────────────────
FORMS = [
    {
        "name": "Ericson TPA Preauth",
        "template": "templates/Ericson TPA Preauth.pdf",
        "schema": "analyzed/Ericson TPA Preauth.json",
        "test_data": "test_data/Ericson TPA Preauth_test_data.json",
        "output": "output/Ericson TPA Preauth_filled.pdf",
    },
    {
        "name": "Bajaj Allianz TPA Preauth",
        "template": "templates/BAJAJ ALLIANZ TPA PREAUTH FORM.pdf",
        "schema": "analyzed/BAJAJ ALLIANZ TPA PREAUTH FORM.json",
        "test_data": "test_data/BAJAJ ALLIANZ TPA PREAUTH FORM_test_data.json",
        "output": "output/BAJAJ ALLIANZ TPA PREAUTH FORM_filled.pdf",
    },
    {
        "name": "Care Health PRE AUTH",
        "template": "templates/Care Health  PRE AUTH.pdf",
        "schema": "analyzed/Care Health  PRE AUTH.json",
        "test_data": "test_data/Care Health  PRE AUTH_test_data.json",
        "output": "output/Care Health  PRE AUTH_filled.pdf",
    },
    {
        "name": "Chola MS Pre-Authorisation",
        "template": "templates/Chola-MS-Pre-Authorisation-Form.pdf",
        "schema": "analyzed/Chola-MS-Pre-Authorisation-Form.json",
        "test_data": "test_data/Chola-MS-Pre-Authorisation-Form_test_data.json",
        "output": "output/Chola-MS-Pre-Authorisation-Form_filled.pdf",
    },
    {
        "name": "East West TPA",
        "template": "templates/East West TPA.pdf",
        "schema": "analyzed/East West TPA.json",
        "test_data": "test_data/East West TPA_test_data.json",
        "output": "output/East West TPA_filled.pdf",
    },
    {
        "name": "FHPL TPA",
        "template": "templates/FHPL TPA.pdf",
        "schema": "analyzed/FHPL TPA.json",
        "test_data": "test_data/FHPL TPA_test_data.json",
        "output": "output/FHPL TPA_filled.pdf",
    },
    {
        "name": "Future Generali Pre Auth",
        "template": "templates/FUTURE GENERLI pre auth.pdf",
        "schema": "analyzed/FUTURE GENERLI pre auth.json",
        "test_data": "test_data/FUTURE GENERLI pre auth_test_data.json",
        "output": "output/FUTURE GENERLI pre auth_filled.pdf",
    },
    {
        "name": "Genins TPA Pre-Auth",
        "template": "templates/Genins TPA Pre-Auth form.pdf",
        "schema": "analyzed/Genins TPA Pre-Auth form.json",
        "test_data": "test_data/Genins TPA Pre-Auth form_test_data.json",
        "output": "output/Genins TPA Pre-Auth form_filled.pdf",
    },
    {
        "name": "GO DIGIT PREAUTH",
        "template": "templates/GO DIGIT PREAUTH.pdf",
        "schema": "analyzed/GO DIGIT PREAUTH.json",
        "test_data": "test_data/GO DIGIT PREAUTH_test_data.json",
        "output": "output/GO DIGIT PREAUTH_filled.pdf",
    },
    {
        "name": "Good Health TPA Preauth",
        "template": "templates/GOOD HEALTH TPA PREAUTH INS. FOAM.pdf",
        "schema": "analyzed/GOOD HEALTH TPA PREAUTH INS. FOAM.json",
        "test_data": "test_data/GOOD HEALTH TPA PREAUTH INS. FOAM_test_data.json",
        "output": "output/GOOD HEALTH TPA PREAUTH INS. FOAM_filled.pdf",
    },
    {
        "name": "HDFC",
        "template": "templates/HDFC.pdf",
        "schema": "analyzed/HDFC.json",
        "test_data": "test_data/HDFC_test_data.json",
        "output": "output/HDFC_filled.pdf",
    },
    {
        "name": "HDGC Claim Form A & B",
        "template": "templates/HDGC CLAIM FORM A & B PART.pdf",
        "schema": "analyzed/HDGC CLAIM FORM A & B PART.json",
        "test_data": "test_data/HDGC CLAIM FORM A & B PART_test_data.json",
        "output": "output/HDGC CLAIM FORM A & B PART_filled.pdf",
    },
    {
        "name": "Health India Pre-Auth",
        "template": "templates/Health India Pre-Auth.pdf",
        "schema": "analyzed/Health India Pre-Auth.json",
        "test_data": "test_data/Health India Pre-Auth_test_data.json",
        "output": "output/Health India Pre-Auth_filled.pdf",
    },
    {
        "name": "Health Insurance",
        "template": "templates/Health Insurance.pdf",
        "schema": "analyzed/Health Insurance.json",
        "test_data": "test_data/Health Insurance_test_data.json",
        "output": "output/Health Insurance_filled.pdf",
    },
    {
        "name": "Heritage Health Pre-Auth",
        "template": "templates/Heritage-Health-Pre-Auth-Form.pdf",
        "schema": "analyzed/Heritage-Health-Pre-Auth-Form.json",
        "test_data": "test_data/Heritage-Health-Pre-Auth-Form_test_data.json",
        "output": "output/Heritage-Health-Pre-Auth-Form_filled.pdf",
    },
    {
        "name": "ICICI Lombard",
        "template": "templates/ICICI LOMBARD.pdf",
        "schema": "analyzed/ICICI LOMBARD.json",
        "test_data": "test_data/ICICI LOMBARD_test_data.json",
        "output": "output/ICICI LOMBARD_filled.pdf",
    },
    {
        "name": "Liberty Request Form",
        "template": "templates/LIBERTY  Request Form.pdf",
        "schema": "analyzed/LIBERTY  Request Form.json",
        "test_data": "test_data/LIBERTY  Request Form_test_data.json",
        "output": "output/LIBERTY  Request Form_filled.pdf",
    },
    {
        "name": "Med-Save Pre-Auth",
        "template": "templates/Med-Save Pre-Auth.pdf",
        "schema": "analyzed/Med-Save Pre-Auth.json",
        "test_data": "test_data/Med-Save Pre-Auth_test_data.json",
        "output": "output/Med-Save Pre-Auth_filled.pdf",
    },
    {
        "name": "Medi-assist TPA",
        "template": "templates/Medi-assist TPA.pdf",
        "schema": "analyzed/Medi-assist TPA.json",
        "test_data": "test_data/Medi-assist TPA_test_data.json",
        "output": "output/Medi-assist TPA_filled.pdf",
    },
    {
        "name": "NIVA-BUPA",
        "template": "templates/NIVA-BUPA.pdf",
        "schema": "analyzed/NIVA-BUPA.json",
        "test_data": "test_data/NIVA-BUPA_test_data.json",
        "output": "output/NIVA-BUPA_filled.pdf",
    },
    {
        "name": "Paramount TPA",
        "template": "templates/Paramount TPA.pdf",
        "schema": "analyzed/Paramount TPA.json",
        "test_data": "test_data/Paramount TPA_test_data.json",
        "output": "output/Paramount TPA_filled.pdf",
    },
    {
        "name": "PPN Declaration",
        "template": "templates/PPN_DECELARATION.pdf",
        "schema": "analyzed/PPN_DECELARATION.json",
        "test_data": "test_data/PPN_DECELARATION_test_data.json",
        "output": "output/PPN_DECELARATION_filled.pdf",
    },
    {
        "name": "Raksha TPA Preauth",
        "template": "templates/RAKSHA TPA PREAUTH.pdf",
        "schema": "analyzed/RAKSHA TPA PREAUTH.json",
        "test_data": "test_data/RAKSHA TPA PREAUTH_test_data.json",
        "output": "output/RAKSHA TPA PREAUTH_filled.pdf",
    },
    {
        "name": "Aditya Birla",
        "template": "templates/Aditya Birla.pdf",
        "schema": "analyzed/Aditya Birla.json",
        "test_data": "test_data/Aditya Birla_test_data.json",
        "output": "output/Aditya Birla_filled.pdf",
    },
]


def list_forms():
    """Show available forms with status."""
    print("\nAvailable forms:")
    print("-" * 50)
    for i, form in enumerate(FORMS, 1):
        schema_exists = (PROJECT_ROOT / form["schema"]).exists()
        data_exists = (PROJECT_ROOT / form["test_data"]).exists()
        status = "[OK] ready" if (schema_exists and data_exists) else "[!!] missing files"
        print(f"  {i}. {form['name']}  [{status}]")
    print()


def fill_form(form):
    """Fill a single form with its test data."""
    name = form.get("name", "Custom Form")
    template = Path(form["template"])
    schema_path = Path(form["schema"])
    data_path = Path(form["test_data"])
    output = Path(form["output"])

    # Resolve relative paths against PROJECT_ROOT if they don't exist as absolute
    if not template.exists() and (PROJECT_ROOT / template).exists():
        template = PROJECT_ROOT / template
    if not schema_path.exists() and (PROJECT_ROOT / schema_path).exists():
        schema_path = PROJECT_ROOT / schema_path
    if not data_path.exists() and (PROJECT_ROOT / data_path).exists():
        data_path = PROJECT_ROOT / data_path
    if not output.parent.exists() and (PROJECT_ROOT / output.parent).exists():
        output = PROJECT_ROOT / output

    print(f"\n{'='*60}")
    print(f"  TESTING: {name}")
    print(f"{'='*60}")

    # Validate files exist
    for label, path in [("Template", template), ("Schema", schema_path), ("Test data", data_path)]:
        if not path.exists():
            print(f"  ERROR: {label} not found: {path}")
            return None

    # Load schema & data
    try:
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema = json.load(f)
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ERROR loading files: {e}")
        return None

    print(f"  Schema: {len(schema.get('fields', []))} fields, {schema.get('total_pages', '?')} pages")
    print(f"  Test data: {len(data)} field values")

    # Fill
    try:
        filler = TPAFormFiller(str(template), schema)
        result = filler.fill_form(data, str(output))
        print(f"\n  Output: {output}")
        return result
    except Exception as e:
        print(f"  ERROR filling form: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    parser = argparse.ArgumentParser(description="TPA Form Fill Tester")
    parser.add_argument("form_number", nargs="?", help="Number of the form to test (from list)")
    parser.add_argument("--template", help="Path to PDF template")
    parser.add_argument("--schema", help="Path to analyzed JSON schema")
    parser.add_argument("--data", help="Path to test data JSON")
    parser.add_argument("--output", help="Path to output PDF")
    
    args = parser.parse_args()

    # Mode 1: Custom arguments
    if args.template and args.schema and args.data:
        form = {
            "name": Path(args.template).stem,
            "template": args.template,
            "schema": args.schema,
            "test_data": args.data,
            "output": args.output or f"output/{Path(args.template).stem}_filled.pdf"
        }
        fill_form(form)
        return

    print("\n" + "=" * 60)
    print("  TPA FORM FILL TESTER")
    print("=" * 60)

    # Mode 2: Form number or 'all' argument
    if args.form_number:
        if args.form_number.lower() == "all":
            for form in FORMS:
                fill_form(form)
            return
        try:
            choice = int(args.form_number)
            if 1 <= choice <= len(FORMS):
                fill_form(FORMS[choice - 1])
                return
            else:
                print(f"Invalid form number: {choice}")
        except ValueError:
            pass

    # Mode 3: Interactive menu
    list_forms()

    try:
        choice = input("Enter form number (or 'all' to test all): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if choice.lower() == "all":
        for form in FORMS:
            fill_form(form)
    elif choice.isdigit() and 1 <= int(choice) <= len(FORMS):
        fill_form(FORMS[int(choice) - 1])
    else:
        print(f"Invalid choice: {choice}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
