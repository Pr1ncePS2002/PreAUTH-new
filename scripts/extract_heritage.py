"""Quick pdfplumber extraction of Heritage Health Pre-Auth Form."""
import pdfplumber

pdf = pdfplumber.open("templates/Heritage-Health-Pre-Auth-Form.pdf")
for i, page in enumerate(pdf.pages, 1):
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=True)
    rects = page.rects
    small_rects = [r for r in rects if 5 < r.get("width", 0) < 25 and 5 < r.get("height", 0) < 25]
    print(f"\n=== PAGE {i} ({page.width:.1f} x {page.height:.1f}) ===")
    print(f"  Words: {len(words)}, Rects: {len(rects)}, Checkboxes: {len(small_rects)}")
    
    lines = {}
    for w in words:
        y = round(float(w["top"]), 0)
        key = None
        for k in lines:
            if abs(k - y) <= 3:
                key = k
                break
        if key is None:
            key = y
            lines[key] = []
        lines[key].append(w)
    
    for y in sorted(lines.keys()):
        ws = sorted(lines[y], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws)
        x0 = round(float(ws[0]["x0"]), 1)
        x1 = round(float(ws[-1]["x1"]), 1)
        print(f"  y={y:6.0f}  x=[{x0:5.1f} -> {x1:5.1f}]  \"{text}\"")
    
    if small_rects:
        print(f"  Checkbox rects:")
        for r in small_rects:
            print(f"    ({r['x0']:.1f}, {r['top']:.1f}) {r['width']:.0f}x{r['height']:.0f}")

    # Also show horizontal lines (underlines for fill areas)
    h_lines = [e for e in page.edges if e.get("orientation") == "h"]
    if h_lines:
        print(f"  Horizontal lines ({len(h_lines)}):")
        for hl in sorted(h_lines, key=lambda e: (e["top"], e["x0"])):
            length = round(float(hl["x1"]) - float(hl["x0"]), 1)
            if length > 20:
                print(f"    y={hl['top']:.1f}  x=[{hl['x0']:.1f} -> {hl['x1']:.1f}]  len={length}")

pdf.close()
