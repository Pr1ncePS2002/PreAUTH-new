#!/usr/bin/env python3
"""
Generate dummy test data from an analyzed form schema.
Usage: python scripts/generate_test_data.py <schema_path> [output_path]
"""

import json
import sys
import os
from pathlib import Path

def generate_test_data(schema_path, output_path=None):
    if not os.path.exists(schema_path):
        print(f"ERROR: Schema file not found: {schema_path}")
        return

    try:
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in schema file: {e}")
        return

    fields = schema.get("fields", [])
    test_data = {}

    print(f"Generating test data for {len(fields)} fields...")

    for field in fields:
        field_id = field.get("field_id")
        field_type = field.get("type", "text_line")
        
        if not field_id:
            continue

        if field_type == "checkbox":
            # Set checkboxes to True to verify alignment
            test_data[field_id] = True
        elif field_type == "date_field":
            test_data[field_id] = "01/01/2025"
        else:
            # For text fields, use a value that helps identify the field
            # Use a shorter string to avoid overflow in small fields
            test_data[field_id] = f"TEST_{field_id}"[:20]

    # Determine output path if not provided
    if not output_path:
        schema_filename = Path(schema_path).stem
        # If schema is in analyzed/, put data in test_data/
        # Otherwise put it in the same directory
        if "analyzed" in str(Path(schema_path).parent):
            base_dir = Path(schema_path).parent.parent
            output_dir = base_dir / "test_data"
            output_dir.mkdir(exist_ok=True)
            output_path = output_dir / f"{schema_filename}_test_data.json"
        else:
            output_path = str(Path(schema_path).with_name(f"{schema_filename}_test_data.json"))

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(test_data, f, indent=2)

    print(f"✓ Test data saved to: {output_path}")
    print(f"  (Contains {len(test_data)} fields)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/generate_test_data.py <schema_path> [output_path]")
        print("Example: python scripts/generate_test_data.py \"analyzed/MyForm.json\"")
        sys.exit(1)

    schema_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    generate_test_data(schema_path, output_path)
