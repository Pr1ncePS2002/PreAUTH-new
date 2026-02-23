#!/usr/bin/env python3
"""
Gemini + pdfplumber Hybrid PDF Form Analyzer (v2 — High Accuracy)

Strategy:
  1. pdfplumber extracts exact text coordinates (ground truth positions)
  2. We build "label lines" — grouping words on the same y-band into full labels
     with the exact x-position where the label ends (= where the fill-blank starts)
  3. Gemini analyzes the PDF visually + with the label-line data to identify ALL
     fillable fields and their exact fill coordinates
  4. We cross-reference Gemini's output with pdfplumber label-lines to snap
     coordinates to ground truth (the END of the full label text)

This approach works on ANY PDF form.
"""

import json
import sys
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

try:
    from google import genai
    from google.genai import types
    import pdfplumber
except ImportError as e:
    print(f"ERROR: Missing package: {e}")
    print("Run: pip install google-genai pdfplumber python-dotenv")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

if not GEMINI_API_KEY:
    print("ERROR: Set GEMINI_API_KEY in .env file")
    sys.exit(1)


# ---------------------------------------------------------------------------
# pdfplumber: Extract ground-truth text positions & build label lines
# ---------------------------------------------------------------------------
def extract_text_positions(pdf_path):
    """Extract every text element with exact coordinates using pdfplumber."""
    print("\n[1/5] Extracting text positions with pdfplumber...")
    pdf = pdfplumber.open(pdf_path)
    pages_data = []

    for page_num, page in enumerate(pdf.pages, 1):
        page_data = {
            "page": page_num,
            "width": float(page.width),
            "height": float(page.height),
            "text_elements": [],
            "rects": [],
            "edges": [],
        }

        words = page.extract_words(
            x_tolerance=3,
            y_tolerance=3,
            keep_blank_chars=True,
            extra_attrs=["fontname", "size"]
        )

        for w in words:
            page_data["text_elements"].append({
                "text": w["text"],
                "x0": round(float(w["x0"]), 1),
                "y0": round(float(w["top"]), 1),
                "x1": round(float(w["x1"]), 1),
                "y1": round(float(w["bottom"]), 1),
                "font": w.get("fontname", ""),
                "size": round(float(w.get("size", 0)), 1),
            })

        # Extract rectangles (potential checkbox boundaries)
        for rect in page.rects:
            w = round(float(rect.get("width", 0)), 1)
            h = round(float(rect.get("height", 0)), 1)
            page_data["rects"].append({
                "x0": round(float(rect["x0"]), 1),
                "y0": round(float(rect["top"]), 1),
                "x1": round(float(rect["x1"]), 1),
                "y1": round(float(rect["bottom"]), 1),
                "width": w,
                "height": h,
            })

        # Extract horizontal edges/lines (potential underlines / fill blanks)
        for edge in page.edges:
            if edge.get("orientation") == "h":
                page_data["edges"].append({
                    "x0": round(float(edge["x0"]), 1),
                    "y0": round(float(edge["top"]), 1),
                    "x1": round(float(edge["x1"]), 1),
                })

        pages_data.append(page_data)
        print(f"  Page {page_num}: {len(page_data['text_elements'])} words, "
              f"{len(page_data['rects'])} rects, {len(page_data['edges'])} h-lines "
              f"({page.width:.0f} x {page.height:.0f} pts)")

    pdf.close()
    return pages_data


def _is_underscore_word(text):
    """Check if a word is entirely underscores/blanks (fill area indicator)."""
    stripped = text.strip()
    if not stripped:
        return True
    return all(c in ('_', ' ', '\u00a0', '.', '\t') for c in stripped) and len(stripped) >= 3


def build_label_lines(pages_data):
    """
    Group words on the same y-band into 'label lines'.
    Each label line = full text string + its x-start, x-end, y position.
    
    KEY IMPROVEMENT: Detects underscore-only words (e.g. "___________") as 
    fill areas, NOT label text. Calculates:
      - clean_text: label without underscores
      - label_x_end: where actual label text ends (BEFORE underscores)
      - fill_x: where the fill/blank area starts (= where to write data)
    """
    print("\n[2/5] Building label lines from text elements...")
    all_label_lines = {}  # page_num -> list of label lines

    for page_data in pages_data:
        pn = page_data["page"]
        elems = sorted(page_data["text_elements"], key=lambda e: (round(e["y0"]), e["x0"]))

        # Group by y-band (±3 points = same line)
        lines = []
        current_line = []
        current_y = None

        for elem in elems:
            y = elem["y0"]
            if current_y is None or abs(y - current_y) <= 3:
                current_line.append(elem)
                if current_y is None:
                    current_y = y
                else:
                    current_y = min(current_y, y)  # use topmost y
            else:
                if current_line:
                    lines.append(current_line)
                current_line = [elem]
                current_y = y

        if current_line:
            lines.append(current_line)

        page_lines = []
        for line_elems in lines:
            full_text = " ".join(e["text"] for e in line_elems)
            x_start = min(e["x0"] for e in line_elems)
            x_end = max(e["x1"] for e in line_elems)
            y_pos = min(e["y0"] for e in line_elems)
            avg_size = sum(e["size"] for e in line_elems if e["size"]) / max(len(line_elems), 1)

            # --- Detect underscore fill areas ---
            # Split elements into label words vs underscore words
            label_elems = []
            fill_elems = []
            for e in sorted(line_elems, key=lambda el: el["x0"]):
                if _is_underscore_word(e["text"]):
                    fill_elems.append(e)
                else:
                    label_elems.append(e)

            # Clean text = only the real label words (no underscores)
            clean_text = " ".join(e["text"] for e in sorted(label_elems, key=lambda el: el["x0"])).strip()
            
            # Where does actual label text end?
            label_x_end = max(e["x1"] for e in label_elems) if label_elems else x_start
            
            # Where does the fill area start? (first underscore word)
            fill_x = None
            if fill_elems:
                fill_x = min(e["x0"] for e in fill_elems)
                # Sanity: fill_x should be after label text, not before
                if fill_x < label_x_end - 5:
                    # Underscores are mixed in with label; use label_x_end + offset
                    fill_x = label_x_end + 10

            page_lines.append({
                "text": full_text,
                "clean_text": clean_text,
                "x_start": round(x_start, 1),
                "x_end": round(x_end, 1),
                "label_x_end": round(label_x_end, 1),
                "fill_x": round(fill_x, 1) if fill_x else None,
                "y": round(y_pos, 1),
                "font_size": round(avg_size, 1),
                "word_count": len(line_elems),
                "has_fill_area": len(fill_elems) > 0,
                "elements": line_elems,
            })

        all_label_lines[pn] = page_lines
        fill_count = sum(1 for ll in page_lines if ll["has_fill_area"])
        print(f"  Page {pn}: {len(page_lines)} label lines ({fill_count} with fill areas)")

    return all_label_lines


# ---------------------------------------------------------------------------
# Gemini: Analyze form structure from PDF
# ---------------------------------------------------------------------------
def analyze_with_gemini(pdf_path, pages_data, label_lines):
    """
    Send the PDF + precise label-line mapping to Gemini.
    """
    print(f"\n[3/5] Analyzing form with Gemini ({GEMINI_MODEL})...")

    client = genai.Client(api_key=GEMINI_API_KEY)

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    # Build a precise label-line summary for each page
    # Use clean_text (without underscores) and fill_x to show where data should go
    text_summaries = []
    for page_data in pages_data:
        pn = page_data["page"]
        page_ll = label_lines.get(pn, [])

        page_summary = f"PAGE {pn} (size: {page_data['width']:.1f} x {page_data['height']:.1f} pts):\n"
        page_summary += f"  Label lines ({len(page_ll)}):\n"
        for ll in page_ll:
            # Show clean text (without underscores) and where fill area starts
            display_text = ll.get('clean_text', ll['text'])
            fill_info = ""
            if ll.get('fill_x'):
                fill_info = f"  FILL_AT_X={ll['fill_x']:.1f}"
            page_summary += (f"    y={ll['y']:6.1f}  label_x=[{ll['x_start']:5.1f} -> {ll.get('label_x_end', ll['x_end']):5.1f}]  "
                             f"font={ll['font_size']:.0f}pt  \"{display_text}\"{fill_info}\n")

        # Add rectangles info (potential checkboxes)
        rects = page_data.get("rects", [])
        small_rects = [r for r in rects if 5 < r["width"] < 25 and 5 < r["height"] < 25]
        if small_rects:
            page_summary += f"  Small rectangles (potential checkboxes):\n"
            for r in small_rects:
                page_summary += f"    RECT at ({r['x0']}, {r['y0']}) size {r['width']}x{r['height']}\n"

        text_summaries.append(page_summary)

    text_layout = "\n".join(text_summaries)

    prompt = f"""You are a PDF form analysis expert. Analyze this TPA/health insurance pre-authorization PDF form 
and identify ALL fillable fields where data needs to be written.

COORDINATE SYSTEM:
- Origin = TOP-LEFT corner of each page
- x increases to the RIGHT (horizontal)
- y increases DOWNWARD (vertical)
- Unit = PDF points (1 pt = 1/72 inch = 0.35mm)

EXACT LABEL LINE DATA (from pdfplumber — these positions are GROUND TRUTH):
{text_layout}

UNDERSTANDING THE DATA:
- Each label line shows: y position, label_x range (where the printed LABEL TEXT is), font size, and the label text
- Lines that say "FILL_AT_X=<value>" have a blank fill area (underlines/blanks) starting at that x coordinate
- The underlines (______) on the PDF are NOT text to be preserved — they mark WHERE user data should be written
- The FILL_AT_X value is the EXACT x coordinate where you should place the fill data

CRITICAL RULES FOR COORDINATES:
1. For text fields (text_line, date_field): The x coordinate MUST be where the FILL BLANK starts:
   - If the label line has FILL_AT_X, use that EXACT value as the x coordinate
   - If no FILL_AT_X, use label_x_end + 15 (the blank space after the label)
   - NEVER place coordinates at the far right edge of the page (x > 480)
   - The fill area is the blank/underlined space IMMEDIATELY after the label text

2. For checkboxes: The x,y should be the CENTER of the checkbox square.
   - Use the RECT positions provided in the data (they are ground truth)
   - The checkbox rectangle is typically BEFORE (to the left of) its label text
   - For RECT at (x0, y0) with size WxH, use x = x0 + W/2, y = y0 + H/2

3. The y coordinate should match the label line's y position (from the data above)

4. DO NOT place coordinates ON TOP of existing label text. The coordinates are for WHERE TO WRITE THE VALUE.

5. max_width should be calculated as: (end of blank area) - (fill x position)
   - Typically the blank area extends to about x=530-540
   - So max_width = 540 - fill_x (approximately)

FIELD TYPES:
- "text_line": Single-line text input (name, number, date, etc.)
- "text_box": Multi-line text area
- "checkbox": Square box to check/mark with X  
- "date_field": Date input (DD/MM/YYYY format)

OUTPUT FORMAT — Return ONLY valid JSON:
{{
  "form_title": "descriptive title",
  "total_pages": <number>,
  "page_heights": {{"1": <height>, "2": <height>, ...}},
  "fields": [
    {{
      "field_id": "unique_snake_case_id",
      "label": "Label text next to the field",
      "page": 1,
      "type": "text_line",
      "coordinates": {{"x": <FILL_X>, "y": <LABEL_Y>}},
      "font_size": 9,
      "max_width": 200
    }}
  ]
}}

IMPORTANT:
- Include fields from ALL pages
- Do NOT include pre-printed headers, titles, or decorative text  
- The underlines/blanks (________) are FILL AREAS, not text — do not skip them
- Every blank line, checkbox, or input area on the form = one field entry
- For checkbox groups, create ONE entry per option (e.g., gender_male, gender_female)
- Ensure field_id values are unique across the entire form
- Be very precise with coordinates — accuracy of positioning matters greatly
- The label text should be CLEAN (no underscores) — just the field label"""

    print(f"  Sending PDF ({len(pdf_bytes) / 1024:.0f} KB) + label data to Gemini...")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(
                        data=pdf_bytes,
                        mime_type="application/pdf"
                    ),
                    types.Part.from_text(text=prompt),
                ]
            )
        ],
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=65536,
        )
    )

    raw_text = response.text.strip()
    print(f"  Gemini response received ({len(raw_text)} chars)")

    return raw_text


# ---------------------------------------------------------------------------
# Parse Gemini JSON response (with truncation repair)
# ---------------------------------------------------------------------------
def parse_gemini_response(raw_text):
    """Parse the JSON from Gemini's response, handling truncation."""
    text = raw_text
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  WARNING: Initial JSON parse failed: {e}")
        # Try to repair truncated JSON
        repaired = _repair_truncated_json(text)
        if repaired:
            try:
                result = json.loads(repaired)
                print(f"  Repaired truncated JSON ({len(result.get('fields', []))} fields)")
                return result
            except json.JSONDecodeError:
                pass

        # Try extracting JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                repaired_subset = _repair_truncated_json(text[start:end])
                if repaired_subset:
                    try:
                        return json.loads(repaired_subset)
                    except json.JSONDecodeError:
                        pass

        print(f"  ERROR: Could not parse. First 500 chars: {text[:500]}")
        return None


def _repair_truncated_json(text):
    """Repair truncated JSON by closing open brackets/braces."""
    last_complete = text.rfind("},")
    if last_complete < 0:
        last_complete = text.rfind("}")
    if last_complete < 0:
        return None

    truncated = text[:last_complete + 1]
    open_brackets = truncated.count("[") - truncated.count("]")
    open_braces = truncated.count("{") - truncated.count("}")
    truncated += "\n" + "]" * max(open_brackets, 0) + "\n" + "}" * max(open_braces, 0)
    return truncated


# ---------------------------------------------------------------------------
# Precision calibration: snap Gemini coords to pdfplumber ground truth
# ---------------------------------------------------------------------------
def calibrate_coordinates(gemini_fields, pages_data, label_lines):
    """
    Cross-reference Gemini's detected fields with pdfplumber's label lines.
    For each field:
      1. Find the matching label line by text similarity
      2. Snap y to the label line's y (ground truth)
      3. Ensure x is AFTER the label's x_end (in the fill area)
      4. Check for nearby underlines/rects for additional precision
    """
    print("\n[4/5] Calibrating coordinates with pdfplumber ground truth...")

    refined_fields = []
    adjustments = 0

    for field in gemini_fields:
        page_num = field["page"]
        page_ll = label_lines.get(page_num, [])
        page_data = next((p for p in pages_data if p["page"] == page_num), None)

        if not page_data or not page_ll:
            refined_fields.append(field)
            continue

        field_x = field["coordinates"]["x"]
        field_y = field["coordinates"]["y"]
        field_type = field.get("type", "text_line")
        label_text = field.get("label", "").lower().strip()

        # ---- Find best matching label line ----
        best_match = None
        best_score = 0

        for ll in page_ll:
            # Use clean_text (without underscores) for matching
            ll_text = ll.get("clean_text", ll["text"]).lower().strip()
            # Score by word overlap
            label_words = set(w for w in label_text.split() if len(w) > 1)
            ll_words = set(w for w in ll_text.split() if len(w) > 1)
            if not label_words:
                continue
            overlap = len(label_words & ll_words)
            score = overlap / len(label_words) if label_words else 0

            # Also check if label text is contained in the line
            if label_text in ll_text or ll_text in label_text:
                score = max(score, 0.8)

            # Penalize if y is very far
            y_dist = abs(ll["y"] - field_y)
            if y_dist > 50:
                score *= 0.3
            elif y_dist > 20:
                score *= 0.7

            if score > best_score:
                best_score = score
                best_match = ll

        if best_match and best_score >= 0.3:
            adjusted = False

            # Snap y to label line's y
            if abs(best_match["y"] - field_y) > 2:
                old_y = field_y
                field["coordinates"]["y"] = best_match["y"]
                adjusted = True

            # For text fields: use fill_x from label line (ground truth fill area)
            if field_type in ("text_line", "date_field", "text_box"):
                # PRIORITY: use fill_x if available (exact position where underscores start)
                if best_match.get("fill_x"):
                    fill_x = best_match["fill_x"]
                    if abs(field_x - fill_x) > 5:
                        field["coordinates"]["x"] = round(fill_x, 1)
                        adjusted = True
                else:
                    # Fallback: use label_x_end + offset
                    label_end_x = best_match.get("label_x_end", best_match["x_end"])
                    min_fill_x = label_end_x + 12

                    # Check if there's an underline/line near this y
                    nearest_line = _find_nearest_hline(page_data, best_match["y"], label_end_x)
                    if nearest_line:
                        min_fill_x = nearest_line["x0"] + 5

                    if field_x < min_fill_x:
                        field["coordinates"]["x"] = round(min_fill_x, 1)
                        adjusted = True

                # Cap max_width: fill area shouldn't exceed page edge
                page_width = page_data.get("width", 612)
                current_x = field["coordinates"]["x"]
                max_fill_width = round(page_width - current_x - 40, 0)
                if "max_width" in field and field["max_width"] > max_fill_width:
                    field["max_width"] = int(max_fill_width)

            # For checkboxes: look for rect near the position
            elif field_type == "checkbox":
                nearest_rect = _find_nearest_checkbox_rect(page_data, field_x, field_y)
                if nearest_rect:
                    # Place at center of rect
                    cx = round((nearest_rect["x0"] + nearest_rect["x1"]) / 2, 1)
                    cy = round((nearest_rect["y0"] + nearest_rect["y1"]) / 2, 1)
                    if abs(cx - field_x) > 3 or abs(cy - field_y) > 3:
                        field["coordinates"]["x"] = cx
                        field["coordinates"]["y"] = cy
                        adjusted = True

            if adjusted:
                adjustments += 1

            field["_matched_label"] = best_match["text"][:60]
            field["_match_score"] = round(best_score, 2)

        refined_fields.append(field)

    print(f"  Calibrated {len(refined_fields)} fields, adjusted {adjustments}")
    return refined_fields


def _find_nearest_hline(page_data, y, after_x):
    """Find a horizontal line (underline) near y position and after x."""
    best = None
    best_dist = float("inf")
    for edge in page_data.get("edges", []):
        if abs(edge["y0"] - y) < 8 and edge["x0"] >= after_x - 20:
            dist = abs(edge["y0"] - y) + abs(edge["x0"] - after_x) * 0.5
            if dist < best_dist:
                best_dist = dist
                best = edge
    return best


def _find_nearest_checkbox_rect(page_data, x, y):
    """Find a small rectangle (checkbox) near the given position."""
    best = None
    best_dist = float("inf")
    for rect in page_data.get("rects", []):
        if 5 <= rect["width"] <= 25 and 5 <= rect["height"] <= 25:
            cx = (rect["x0"] + rect["x1"]) / 2
            cy = (rect["y0"] + rect["y1"]) / 2
            dist = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
            if dist < 40 and dist < best_dist:
                best_dist = dist
                best = rect
    return best


# ---------------------------------------------------------------------------
# Generate final output
# ---------------------------------------------------------------------------
def generate_structure(gemini_data, refined_fields, pages_data, output_path):
    """Generate the final form structure JSON."""
    print(f"\n[5/5] Generating form structure...")

    page_heights = {}
    for p in pages_data:
        page_heights[str(p["page"])] = p["height"]

    structure = {
        "template_id": "GEMINI_ANALYZED",
        "form_title": gemini_data.get("form_title", "Unknown Form"),
        "hospital_name": gemini_data.get("form_title", ""),
        "total_pages": len(pages_data),
        "page_heights": page_heights,
        "analysis_model": GEMINI_MODEL,
        "fields": []
    }

    for field in refined_fields:
        entry = {
            "field_id": field["field_id"],
            "label": field["label"],
            "type": field.get("type", "text_line"),
            "page": field["page"],
            "coordinates": {
                "x": round(field["coordinates"]["x"], 1),
                "y": round(field["coordinates"]["y"], 1),
            },
            "font_size": field.get("font_size", 9),
        }
        if "max_width" in field:
            entry["max_width"] = field["max_width"]
        structure["fields"].append(entry)

    with open(output_path, "w") as f:
        json.dump(structure, f, indent=2)

    print(f"  Saved {len(structure['fields'])} fields to: {output_path}")
    return structure


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Gemini + pdfplumber PDF Form Analyzer v2")
    parser.add_argument("pdf_path", nargs="?", default=None,
                        help="Path to the PDF form to analyze")
    parser.add_argument("--output", "-o", default=None,
                        help="Output JSON path (default: analyzed/<pdf_name>.json)")
    parser.add_argument("--raw", "-r", default=None,
                        help="Save raw Gemini response to file")
    args = parser.parse_args()

    pdf_path = args.pdf_path
    if not pdf_path:
        print("Usage: python gemini_analyzer.py <pdf_path>")
        print("Example: python gemini_analyzer.py \"templates/Ericson TPA Preauth.pdf\"")
        return

    if not Path(pdf_path).exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        return

    # Output file uses the SAME name as the PDF (just .json extension)
    pdf_name = Path(pdf_path).stem
    output_path = args.output or f"analyzed/{pdf_name}.json"
    raw_path = args.raw or f"analyzed/{pdf_name}_gemini_raw.json"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("GEMINI + PDFPLUMBER HYBRID FORM ANALYZER v2")
    print("=" * 60)
    print(f"  PDF:    {pdf_path}")
    print(f"  Model:  {GEMINI_MODEL}")
    print(f"  Output: {output_path}")

    # Step 1: pdfplumber extraction
    pages_data = extract_text_positions(pdf_path)

    # Step 2: Build label lines
    label_lines = build_label_lines(pages_data)

    # Step 3: Gemini analysis
    raw_response = analyze_with_gemini(pdf_path, pages_data, label_lines)
    gemini_data = parse_gemini_response(raw_response)

    if not gemini_data:
        print("\nERROR: Could not parse Gemini response.")
        with open(raw_path, "w") as f:
            json.dump({"raw_response": raw_response}, f, indent=2)
        print(f"  Raw response saved to: {raw_path}")
        return

    # Save raw Gemini output
    with open(raw_path, "w") as f:
        json.dump(gemini_data, f, indent=2)
    print(f"  Raw Gemini analysis saved to: {raw_path}")

    gemini_fields = gemini_data.get("fields", [])
    print(f"  Gemini detected {len(gemini_fields)} fields")

    # Step 4: Calibrate with pdfplumber ground truth
    refined_fields = calibrate_coordinates(gemini_fields, pages_data, label_lines)

    # Step 5: Generate final structure
    structure = generate_structure(gemini_data, refined_fields, pages_data, output_path)

    # Summary
    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"  Form:   {gemini_data.get('form_title', 'Unknown')}")
    print(f"  Pages:  {len(pages_data)}")
    print(f"  Fields: {len(structure['fields'])}")
    print(f"  Output: {output_path}")

    # Per-page summary
    for p in pages_data:
        pn = p["page"]
        page_fields = [f for f in structure["fields"] if f["page"] == pn]
        if page_fields:
            print(f"\n  Page {pn} ({len(page_fields)} fields):")
            for pf in page_fields:
                print(f"    - {pf['field_id']}: \"{pf['label'][:50]}\" "
                      f"at ({pf['coordinates']['x']}, {pf['coordinates']['y']}) [{pf['type']}]")

    print(f"\n  Next: Review {output_path}, then run quick_test.py")


if __name__ == "__main__":
    main()
