#!/usr/bin/env python3
"""
PDF Form Analyzer - Precisely analyzes PDF forms to extract field locations.

Three-layer analysis:
  1. AcroForm detection (fillable fields embedded in PDF)
  2. pdfplumber text extraction (exact coordinates of every text element)
  3. Visual structure detection (lines, rectangles = form boxes)

Outputs a detailed JSON with exact coordinates for each detected field.
"""

import json
import sys
from pathlib import Path

try:
    from PyPDF2 import PdfReader
    import pdfplumber
except ImportError:
    print("ERROR: Install required packages: pip install PyPDF2 pdfplumber")
    sys.exit(1)


def analyze_acroform_fields(pdf_path):
    """Layer 1: Detect embedded fillable form fields (AcroForm)"""
    print("\n" + "=" * 60)
    print("LAYER 1: AcroForm Field Detection")
    print("=" * 60)

    reader = PdfReader(pdf_path)
    fields = reader.get_fields()

    if not fields:
        print("  No AcroForm fields found (non-fillable PDF)")
        print("  -> Will rely on text-coordinate analysis instead")
        return []

    acro_fields = []
    for name, field_obj in fields.items():
        info = {
            "name": name,
            "type": str(field_obj.get("/FT", "Unknown")),
            "value": str(field_obj.get("/V", "")),
        }
        # Try to get the widget annotation for coordinates
        if "/Rect" in field_obj:
            rect = field_obj["/Rect"]
            info["rect"] = [float(r) for r in rect]
        acro_fields.append(info)

    print(f"  Found {len(acro_fields)} AcroForm fields!")
    for f in acro_fields:
        rect_str = f"  rect={f['rect']}" if 'rect' in f else ""
        print(f"    - {f['name']} ({f['type']}){rect_str}")

    return acro_fields


def analyze_text_positions(pdf_path):
    """Layer 2: Extract every text element with precise coordinates using pdfplumber"""
    print("\n" + "=" * 60)
    print("LAYER 2: Text Position Analysis (pdfplumber)")
    print("=" * 60)

    pdf = pdfplumber.open(pdf_path)
    all_pages_data = []

    for page_num, page in enumerate(pdf.pages, 1):
        print(f"\n  --- Page {page_num} (size: {page.width} x {page.height}) ---")

        page_data = {
            "page": page_num,
            "width": float(page.width),
            "height": float(page.height),
            "text_elements": [],
            "lines": [],
            "rects": [],
        }

        # Extract all text with positions
        words = page.extract_words(
            x_tolerance=3,
            y_tolerance=3,
            keep_blank_chars=True,
            extra_attrs=["fontname", "size"]
        )

        for w in words:
            elem = {
                "text": w["text"],
                "x0": round(float(w["x0"]), 2),
                "y0": round(float(w["top"]), 2),  # top of text
                "x1": round(float(w["x1"]), 2),
                "y1": round(float(w["bottom"]), 2),  # bottom of text
                "font": w.get("fontname", ""),
                "size": round(float(w.get("size", 0)), 1),
            }
            page_data["text_elements"].append(elem)

        # Extract lines (form field borders/underlines)
        if page.lines:
            for line in page.lines:
                page_data["lines"].append({
                    "x0": round(float(line["x0"]), 2),
                    "y0": round(float(line["top"]), 2),
                    "x1": round(float(line["x1"]), 2),
                    "y1": round(float(line["bottom"]), 2),
                })

        # Extract rectangles (form field boxes)
        if page.rects:
            for rect in page.rects:
                page_data["rects"].append({
                    "x0": round(float(rect["x0"]), 2),
                    "y0": round(float(rect["top"]), 2),
                    "x1": round(float(rect["x1"]), 2),
                    "y1": round(float(rect["bottom"]), 2),
                })

        all_pages_data.append(page_data)

        # Print summary
        print(f"    Text elements: {len(page_data['text_elements'])}")
        print(f"    Lines: {len(page_data['lines'])}")
        print(f"    Rectangles: {len(page_data['rects'])}")

        # Print text labels found (likely form field labels)
        print(f"    Key text labels found:")
        for elem in page_data["text_elements"]:
            text = elem["text"].strip()
            if len(text) > 2:  # Skip tiny fragments
                print(f"      [{elem['x0']:6.1f}, {elem['y0']:6.1f}] "
                      f"(font={elem['font']}, size={elem['size']}) "
                      f"\"{text}\"")

    pdf.close()
    return all_pages_data


def detect_form_fields(pages_data):
    """Layer 3: Intelligently detect form fields from text + structure"""
    print("\n" + "=" * 60)
    print("LAYER 3: Form Field Detection")
    print("=" * 60)

    # Common TPA form field label patterns
    field_patterns = {
        "patient_name": ["name of the patient", "patient name", "name of patient",
                         "insured name", "patient's name"],
        "age_years": ["age", "age (yrs)", "age years"],
        "gender": ["gender", "sex"],
        "dob": ["date of birth", "dob", "d.o.b"],
        "contact": ["contact", "phone", "mobile", "tel"],
        "policy_number": ["policy no", "policy number", "policy id"],
        "card_id": ["card id", "card no", "id card", "tpa id", "uhid"],
        "doctor_name": ["treating doctor", "doctor name", "name of doctor",
                        "attending doctor", "consultant"],
        "diagnosis": ["diagnosis", "nature of illness", "ailment",
                      "disease", "clinical findings"],
        "admission_date": ["date of admission", "admission date", "doa"],
        "admission_time": ["time of admission"],
        "expected_days": ["expected days", "expected stay", "duration of stay",
                          "days of hospitalization"],
        "room_rent": ["room rent", "room charges"],
        "total_cost": ["total cost", "total estimated", "total amount",
                       "estimated cost", "total charges"],
        "investigation_cost": ["investigation", "diagnostic"],
        "company_name": ["company name", "employer", "corporate"],
        "employee_id": ["employee id", "emp id", "employee no"],
        "insurer_name": ["insurance company", "insurer name", "name of insurer"],
    }

    detected_fields = []

    for page_data in pages_data:
        page_num = page_data["page"]
        page_height = page_data["height"]

        for elem in page_data["text_elements"]:
            text_lower = elem["text"].strip().lower()

            for field_id, patterns in field_patterns.items():
                for pattern in patterns:
                    if pattern in text_lower:
                        # Estimate where the value should be written
                        # Usually to the right of the label, or below it
                        value_x = elem["x1"] + 10  # Right of label
                        value_y = elem["y0"]  # Same vertical position

                        # Check if there's a line/rect nearby (form field box)
                        nearby_rect = find_nearby_rect(
                            elem, page_data.get("rects", []),
                            page_data.get("lines", [])
                        )

                        field_info = {
                            "field_id": field_id,
                            "matched_label": elem["text"].strip(),
                            "page": page_num,
                            "label_coords": {
                                "x0": elem["x0"],
                                "y0": elem["y0"],
                                "x1": elem["x1"],
                                "y1": elem["y1"],
                            },
                            "suggested_value_coords": {
                                "x": round(value_x, 2),
                                "y": round(value_y, 2),
                            },
                            "type": "text_line",
                            "font_size": elem["size"],
                        }

                        if nearby_rect:
                            field_info["nearby_box"] = nearby_rect
                            # Use the box interior for writing
                            field_info["suggested_value_coords"] = {
                                "x": round(nearby_rect["x0"] + 3, 2),
                                "y": round(nearby_rect["y0"] + 2, 2),
                            }
                            field_info["type"] = "text_box"

                        detected_fields.append(field_info)
                        print(f"  [Page {page_num}] {field_id}: "
                              f"\"{elem['text'].strip()}\" at "
                              f"({elem['x0']:.1f}, {elem['y0']:.1f}) "
                              f"-> write at ({field_info['suggested_value_coords']['x']:.1f}, "
                              f"{field_info['suggested_value_coords']['y']:.1f})")
                        break  # Stop after first pattern match
                else:
                    continue
                break  # Stop checking more patterns for this text element

    # Deduplicate by field_id (keep first match per page)
    seen = set()
    unique_fields = []
    for f in detected_fields:
        key = (f["field_id"], f["page"])
        if key not in seen:
            seen.add(key)
            unique_fields.append(f)

    print(f"\n  Total unique fields detected: {len(unique_fields)}")
    return unique_fields


def find_nearby_rect(text_elem, rects, lines):
    """Find a rectangle or line near a text label (likely a form field box)"""
    tx0, ty0, tx1, ty1 = text_elem["x0"], text_elem["y0"], text_elem["x1"], text_elem["y1"]
    tolerance = 30  # points

    # Check rectangles
    for rect in rects:
        # Is the rect to the right of or containing the label?
        if (rect["x0"] >= tx1 - tolerance and
            abs(rect["y0"] - ty0) < tolerance):
            return {
                "x0": round(rect["x0"], 2),
                "y0": round(rect["y0"], 2),
                "x1": round(rect["x1"], 2),
                "y1": round(rect["y1"], 2),
                "type": "rect"
            }

    # Check horizontal lines (underline-style fields)
    for line in lines:
        if (abs(line["y0"] - ty1) < tolerance and
            line["x0"] >= tx0 - tolerance and
            abs(line["x1"] - line["x0"]) > 30):  # Minimum width
            return {
                "x0": round(line["x0"], 2),
                "y0": round(line["y0"] - 12, 2),  # Write above the line
                "x1": round(line["x1"], 2),
                "y1": round(line["y1"], 2),
                "type": "underline"
            }

    return None


def generate_form_structure(detected_fields, pages_data, output_path):
    """Generate the final form structure JSON ready for tpa_form_filler.py"""
    print("\n" + "=" * 60)
    print("GENERATING FORM STRUCTURE")
    print("=" * 60)

    total_pages = len(pages_data)
    page_height = pages_data[0]["height"] if pages_data else 842

    structure = {
        "template_id": "AUTO_DETECTED",
        "hospital_name": "Auto-detected form",
        "total_pages": total_pages,
        "page_height": page_height,
        "fields": []
    }

    for field in detected_fields:
        coords = field["suggested_value_coords"]
        structure["fields"].append({
            "field_id": field["field_id"],
            "label": field["matched_label"],
            "type": field["type"],
            "page": field["page"],
            "coordinates": {
                "x": coords["x"],
                "y": coords["y"],
            },
            "font_size": field.get("font_size", 10),
            "label_coords": field["label_coords"],
        })

    with open(output_path, 'w') as f:
        json.dump(structure, f, indent=2)

    print(f"  Saved {len(structure['fields'])} fields to: {output_path}")
    return structure


def main():
    pdf_path = "templates/amrita_preauth.pdf"
    raw_output = "analyzed/pdf_raw_analysis.json"
    structure_output = "analyzed/amrita_form_structure.json"

    if not Path(pdf_path).exists():
        print(f"ERROR: PDF not found at {pdf_path}")
        return

    print("\n" + "=" * 60)
    print("PDF FORM ANALYZER - PRECISE DETECTION")
    print("=" * 60)
    print(f"Analyzing: {pdf_path}")

    # Layer 1: Check for AcroForm fields
    acro_fields = analyze_acroform_fields(pdf_path)

    # Layer 2: Extract all text positions
    pages_data = analyze_text_positions(pdf_path)

    # Layer 3: Detect form fields from text patterns
    detected_fields = detect_form_fields(pages_data)

    # Save raw analysis
    raw_data = {
        "acroform_fields": acro_fields,
        "pages": pages_data,
        "detected_fields": detected_fields,
    }
    with open(raw_output, 'w') as f:
        json.dump(raw_data, f, indent=2, default=str)
    print(f"\n  Raw analysis saved to: {raw_output}")

    # Generate form structure for the filler
    structure = generate_form_structure(detected_fields, pages_data, structure_output)

    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"  AcroForm fields: {len(acro_fields)}")
    print(f"  Text elements extracted: {sum(len(p['text_elements']) for p in pages_data)}")
    print(f"  Form fields detected: {len(detected_fields)}")
    print(f"\n  Files saved:")
    print(f"    Raw analysis: {raw_output}")
    print(f"    Form structure: {structure_output}")

    if acro_fields:
        print(f"\n  RECOMMENDATION: This PDF has AcroForm fields!")
        print(f"  -> Use AcroForm filling for 100% accuracy.")
    else:
        print(f"\n  RECOMMENDATION: No AcroForm fields found.")
        print(f"  -> Review {raw_output} to verify/adjust detected coordinates.")
        print(f"  -> Then re-run quick_test.py with the updated structure.")


if __name__ == "__main__":
    main()
