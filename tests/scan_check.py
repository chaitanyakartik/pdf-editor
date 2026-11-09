"""Run scan.analyze on boxes of a scanned PDF, then re-patch each box with the SAME detected text
so before/after crops can be compared by eye. Usage: scan_check.py pdf outdir 'x0,y0,x1,y1' ..."""
import sys, time, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pymupdf, scan, compose
pdf, outdir, boxes = sys.argv[1], sys.argv[2], [list(map(float, b.split(","))) for b in sys.argv[3:]]
d = pymupdf.open(pdf); p = d[0]
for i, b in enumerate(boxes):
    t = time.time(); a = scan.analyze(p, b); dt = time.time() - t
    print(f"[{i}] {dt:.2f}s font={a.get('font_label')} size={a['size']} iou={a.get('match')} color={a['color']} fill={a['fill']} "
          f"hscale={a.get('hscale')} lines={len(a['lines'])} pitch={a['pitch'] and round(a['pitch'],1)}\n     text={a['text']!r}\n     cands={a.get('cands')}")
    clip = pymupdf.Rect(b) + (-10, -6, 10, 6)
    p.get_pixmap(dpi=200, clip=clip).save(f"{outdir}/box{i}_before.png")
    l0 = a["lines"][0] if a["lines"] else {}
    compose.draw(p, {"rect": b, "fill": a["fill"], "text": a["text"], "size": a["size"] or 11, "color": a["color"],
                     "font": a["font"], "x": l0.get("x"), "baseline": l0.get("baseline"), "pitch": a["pitch"],
                     "hscale": a.get("hscale", 1.0)})
    p.get_pixmap(dpi=200, clip=clip).save(f"{outdir}/box{i}_after.png")
