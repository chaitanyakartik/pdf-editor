"""Pass = stray_px 0 and no LOST/COLLATERAL lines.
For each PDF: edit up to N spans on page 0 (swap two chars) and check every changed
pixel lies inside the union of the edited spans' old+new boxes. Prints stats only."""
import sys, pathlib, random
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pymupdf, engine
DPI = 100; z = DPI / 72
def render(page):
    pix = page.get_pixmap(dpi=DPI, alpha=False); return pix.samples, pix.width, pix.height
for path in sys.argv[1:]:
    d = pymupdf.open(path); p = d[0]
    spans = [s for s in engine.get_spans(p) if s["editable"] and len(s["text"].strip()) > 4]
    random.seed(0); pick = random.sample(spans, min(6, len(spans)))
    before, w, h = render(p)
    allowed, srcs = [], []
    for s in pick:
        cur = next((c for c in engine.get_spans(p) if c["text"] == s["text"] and max(abs(a - b) for a, b in zip(c["bbox"], s["bbox"])) < 1), None)
        if cur is None: print("  LOST", repr(s["text"][:30])); continue
        t = s["text"]; new = t[:-2] + t[-1] + t[-2]  # swap last two chars, same length
        r = engine.edit_span(d, 0, cur["id"], new); srcs.append(r["font_source"])
        if r["collateral"]: print("  COLLATERAL", r["collateral"])
        b = pymupdf.Rect(s["bbox"]); b.x1 += 4 * s["size"]; allowed.append(b + (-2, -2, 2, 2))
    after, _, _ = render(p)
    bad = 0
    for i in range(0, len(before), 3):
        if max(abs(before[i+k] - after[i+k]) for k in range(3)) > 40:  # ignore sub-pixel AA from content rewrite
            px, py = (i // 3) % w / z, (i // 3) // w / z
            if not any(pymupdf.Point(px, py) in a for a in allowed): bad += 1
    print(f"{pathlib.Path(path).name[:40]:42s} spans={len(spans):4d} edited={len(pick)} fonts={srcs} stray_px={bad}")
