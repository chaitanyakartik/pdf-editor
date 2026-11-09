"""Edit several spans of fixture.pdf; print font source + collateral; render before/after."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pymupdf, engine
src, outdir = sys.argv[1], sys.argv[2]
d = pymupdf.open(src)
d[0].get_pixmap(dpi=110).save(f"{outdir}/before.png")
orig = {s["id"]: s["text"] for s in engine.get_spans(d[0])}
edits = {1: "Invoice No: INV-2014", 3: " Priya Sharma-Iyer", 4: "Amount due: Rs 99,999.00 by 15 Dec 2026",
         5: "VOID", 8: "Page 1 of 1 · edited footer", 0: "ACME CORP"}
for sid, txt in edits.items():
    cur = next(s for s in engine.get_spans(d[0]) if s["text"] == orig[sid])
    print(repr(orig[sid]), "->", repr(txt), engine.edit_span(d, 0, cur["id"], txt))
d.save(f"{outdir}/after.pdf", garbage=3, deflate=True)
d[0].get_pixmap(dpi=110).save(f"{outdir}/after.png")
print([s["text"] for s in engine.get_spans(d[0])])
