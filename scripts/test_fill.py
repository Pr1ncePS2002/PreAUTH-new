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
        "test_data": "test_data/ericson_test_data.json",
        "output": "output/ericson_test_filled.pdf",
    },
    {
        "name": "Bajaj Allianz TPA Preauth",
        "template": "templates/BAJAJ ALLIANZ TPA PREAUTH FORM.pdf",
        "schema": "analyzed/BAJAJ ALLIANZ TPA PREAUTH FORM.json",
        "test_data": "test_data/bajaj_test_data.json",
        "output": "output/bajaj_test_filled.pdf",
    },
    {
        "name": "Heritage Health Pre-Auth",
        "template": "templates/Heritage-Health-Pre-Auth-Form.pdf",
        "schema": "analyzed/Heritage-Health-Pre-Auth-Form.json",
        "test_data": "test_data/heritage_test_data.json",
        "output": "output/heritage_test_filled.pdf",
    },
    {
        "name": "PPN Declaration",
        "template": "templates/PPN_DECELARATION.pdf",
        "schema": "analyzed/PPN_DECELARATION.json",
        "test_data": "test_data/ppn_test_data.json",
        "output": "output/ppn_test_filled.pdf",
    },
]


def list_forms():
    """Show available forms with status."""
    print("\nAvailable forms:")
    print("-" * 50)
    for i, form in enumerate(FORMS, 1):
        schema_exists = (PROJECT_ROOT / form["schema"]).exists()
        data_exists = (PROJECT_ROOT / form["test_data"]).exists()
        status = "✓ ready" if (schema_exists and data_exists) else "✗ missing files"
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

    # Mode 2: Form number argument
    if args.form_number:
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
