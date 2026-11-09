"""Big Patch box over the whole letter body, change ONE line -> only that line may change on the page.
Pixel-diffs the page before/after: every changed pixel must be inside the edited line's cover box.
Run on a throwaway server: PORT=43070 python app.py '<SR certificate scan>.pdf'; ui_bigbox.py <outdir> [url]"""
import sys, json, urllib.request
import numpy as np, pymupdf
from playwright.sync_api import sync_playwright
out = sys.argv[1]; URL = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:43070"; k = 1.5
def page_png(z=2):
    data = urllib.request.urlopen(f"{URL}/api/page/0.png?zoom={z}&v={json.load(urllib.request.urlopen(URL+'/api/meta'))['ver']}").read()
    pm = pymupdf.Pixmap(data); return np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)[..., :3].astype(int)
before = page_png()
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_context(viewport={"width": 1300, "height": 820}, device_scale_factor=2).new_page()
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_selector(".page img[src]"); pg.click("[data-mode=patch]")
    o = pg.locator(".page").first.bounding_box(); r = (54, 144, 571, 563)
    pg.mouse.move(o["x"]+r[0]*k, o["y"]+r[1]*k); pg.mouse.down(); pg.mouse.move(o["x"]+r[2]*k, o["y"]+r[3]*k, steps=8); pg.mouse.up()
    pg.wait_for_function("!document.querySelector('#pText').disabled"); pg.wait_for_timeout(800)
    txt = pg.input_value("#pText"); lines = txt.split("\n")
    i = next(n for n, l in enumerate(lines) if l.startswith("End Date"))
    print("prefill line:", repr(lines[i]), "| det before edit:", pg.inner_text("#pDet"))
    lines[i] = "End Date: 1st June 2024"; pg.fill("#pText", "\n".join(lines)); pg.wait_for_timeout(900)
    print("det after edit:", pg.inner_text("#pDet"), "| covers drawn:", pg.evaluate("st.P.covers.length"))
    cover = pg.evaluate("lineItems(spec())[0].rect"); print("cover box:", [round(v, 1) for v in cover])
    pg.screenshot(path=f"{out}/bigbox_preview.png")
    pg.click("#pApply"); pg.wait_for_selector("#toast.show"); pg.wait_for_timeout(700); print("toast:", pg.inner_text("#toast"))
    b.close()
after = page_png(); z = 2
diff = np.abs(after - before).sum(axis=2) > 40
ys, xs = np.where(diff)
inside = (xs / z >= cover[0] - 0.5) & (xs / z <= cover[2] + 0.5) & (ys / z >= cover[1] - 0.5) & (ys / z <= cover[3] + 0.5)
print(f"changed pixels: {diff.sum()}  outside the edited line's box: {(~inside).sum()}")
print("JS errors:", errs or "none")
