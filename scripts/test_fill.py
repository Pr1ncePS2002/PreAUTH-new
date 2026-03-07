#!/usr/bin/env python3
"""
Test script for TPA form filling — supports all configured forms.
Usage: python scripts/test_fill.py [form_number]
"""

import json
import sys
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
    # Add more forms here as they are calibrated:
    # {
    #     "name": "Star Health Preauth",
    #     "template": "templates/STAR PRE AUTH FORM.pdf",
    #     "schema": "analyzed/STAR PRE AUTH FORM.json",
    #     "test_data": "test_data/star_test_data.json",
    #     "output": "output/star_test_filled.pdf",
    # },
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
    name = form["name"]
    template = PROJECT_ROOT / form["template"]
    schema_path = PROJECT_ROOT / form["schema"]
    data_path = PROJECT_ROOT / form["test_data"]
    output = PROJECT_ROOT / form["output"]

    print(f"\n{'='*60}")
    print(f"  TESTING: {name}")
    print(f"{'='*60}")

    # Validate files exist
    for label, path in [("Template", template), ("Schema", schema_path), ("Test data", data_path)]:
        if not path.exists():
            print(f"  ERROR: {label} not found: {path}")
            return None

    # Load schema & data
    with open(schema_path) as f:
        schema = json.load(f)
    with open(data_path) as f:
        data = json.load(f)

    print(f"  Schema: {len(schema['fields'])} fields, {schema['total_pages']} pages")
    print(f"  Test data: {len(data)} field values")

    # Fill
    filler = TPAFormFiller(str(template), schema)
    result = filler.fill_form(data, str(output))

    print(f"\n  Output: {output}")
    return result


def main():
    print("\n" + "=" * 60)
    print("  TPA FORM FILL TESTER")
    print("=" * 60)

    # If form number passed as argument, use it directly
    if len(sys.argv) > 1:
        try:
            choice = int(sys.argv[1])
            if 1 <= choice <= len(FORMS):
                fill_form(FORMS[choice - 1])
                return
            else:
                print(f"Invalid form number: {choice}")
        except ValueError:
            print(f"Invalid argument: {sys.argv[1]}")

    # Interactive menu
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
