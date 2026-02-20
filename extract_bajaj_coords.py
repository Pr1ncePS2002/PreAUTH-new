#!/usr/bin/env python3
"""Extract ground truth text positions from Bajaj Allianz form."""
import pdfplumber

pdf = pdfplumber.open('templates/BAJAJ ALLIANZ TPA PREAUTH FORM.pdf')

for pg_num in range(1, 4):
    page = pdf.pages[pg_num - 1]
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=True)
    
    print(f'=== PAGE {pg_num} ({page.width} x {page.height}) ===')
    
    # Group words by y-band (within 3pt)
    lines = {}
    for w in words:
        y_key = round(float(w['top']) / 3) * 3
        if y_key not in lines:
            lines[y_key] = []
        lines[y_key].append(w)
    
    for y_key in sorted(lines.keys()):
        ws = sorted(lines[y_key], key=lambda w: float(w['x0']))
        parts = []
        for w in ws:
            x0 = round(float(w['x0']), 1)
            x1 = round(float(w['x1']), 1)
            y = round(float(w['top']), 1)
            parts.append(f'{w["text"]}[{x0}-{x1},y={y}]')
        line_text = " | ".join(parts)
        print(f'  y~{y_key}: {line_text}')
    print()

pdf.close()
