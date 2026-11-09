"""Wrap/reflow UI test on a THROWAWAY server (REDLINE_NO_SESSION=1 PORT=43070 python app.py '<SR scan>.pdf').
A: whole-body box, lengthen one justified line -> reflow inside that paragraph only (pixel diff).
B: empty box, long sentence -> wraps at the box edge.  Usage: ui_wrap.py <outdir> [url]"""
import sys, json, urllib.request
import numpy as np, pymupdf
from playwright.sync_api import sync_playwright
out = sys.argv[1]; URL = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:43070"; k = 1.5
def page_arr(z=2):
    v = json.load(urllib.request.urlopen(URL + "/api/meta"))["ver"]
    pm = pymupdf.Pixmap(urllib.request.urlopen(f"{URL}/api/page/0.png?zoom={z}&v={v}").read())
    return np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)[..., :3].astype(int)
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_context(viewport={"width": 1300, "height": 820}, device_scale_factor=2).new_page()
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_selector(".page img[src]"); pg.click("[data-mode=patch]")
    def box(r):
        o = pg.locator(".page").first.bounding_box()
        pg.mouse.move(o["x"]+r[0]*k, o["y"]+r[1]*k); pg.mouse.down(); pg.mouse.move(o["x"]+r[2]*k, o["y"]+r[3]*k, steps=8); pg.mouse.up()
        pg.wait_for_function("!document.querySelector('#pText').disabled"); pg.wait_for_timeout(700)
    # ---- A
    before = page_arr()
    box((54, 144, 571, 563))
    print("A align:", pg.evaluate("st.P.align"), "| wrap at", pg.input_value("#pWrap"))
    lines = pg.input_value("#pText").split("\n"); i = next(n for n, l in enumerate(lines) if l.startswith("I am"))
    lines[i] = lines[i].replace("an Intern", "a Machine Learning Intern"); pg.fill("#pText", "\n".join(lines)); pg.wait_for_timeout(1200)
    print("A det:", pg.inner_text("#pDet"), "| warn:", pg.inner_text("#pWarn") or "-")
    pg.evaluate("window.scrollTo(0, 300)"); pg.wait_for_timeout(300); pg.screenshot(path=f"{out}/wrapA_preview.png")
    pg.click("#pApply"); pg.wait_for_selector("#toast.show"); pg.wait_for_timeout(700)
    after = page_arr(); ys, xs = np.where(np.abs(after - before).sum(axis=2) > 40)
    print(f"A changed px: {len(ys)}, outside the paragraph's band (y 315-374pt): {((ys/2 < 315) | (ys/2 > 374)).sum()}")
    # ---- B: empty area to the right of the signature
    box((260, 640, 520, 700))
    pg.fill("#pText", "This sentence is long enough that it has to wrap at the right edge of the box I drew."); pg.wait_for_timeout(1200)
    print("B wrap at", pg.input_value("#pWrap"), "| preview width px:", round(pg.locator(".pv-text").bounding_box()["width"]), "box width px:", round((520-260)*k))
    pg.screenshot(path=f"{out}/wrapB_preview.png")
    print("JS errors:", errs or "none"); b.close()
