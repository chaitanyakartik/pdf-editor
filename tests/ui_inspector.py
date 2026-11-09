"""UI test: reference + patch inspector (formatting, live preview, drag-to-snap) + Move mode.
Run against a THROWAWAY server: PORT=43070 python app.py '<SR certificate scan>.pdf'; then ui_inspector.py <outdir> [url]"""
import sys
from playwright.sync_api import sync_playwright
out = sys.argv[1]; URL = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:43070"; k = 1.5
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2).new_page()
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
    pg.goto(URL); pg.wait_for_selector(".page img[src]")
    pg.click("[data-mode=patch]"); pg.evaluate("window.scrollTo(0, 360)"); pg.wait_for_timeout(300)
    bb = lambda: pg.locator(".page").first.bounding_box()
    def drag(r, shift=False):
        o = bb()
        if shift: pg.keyboard.down("Shift")
        pg.mouse.move(o["x"] + r[0]*k, o["y"] + r[1]*k); pg.mouse.down(); pg.mouse.move(o["x"] + r[2]*k, o["y"] + r[3]*k, steps=6); pg.mouse.up()
        if shift: pg.keyboard.up("Shift")
    drag((101, 418, 266, 433), shift=True); pg.wait_for_selector("#refChip:not([hidden])")
    print("ref:", pg.inner_text("#refTxt"))
    drag((98, 434, 300, 456))
    pg.wait_for_function("!document.querySelector('#pText').disabled"); pg.wait_for_selector(".pv-text:not([hidden])")
    v = lambda sel: pg.input_value(sel)
    print("panel:", pg.inner_text("#pDet"), "| text", repr(v("#pText")), "| size", v("#pSize"), "| left", v("#pX"), "| baseline", v("#pY"))
    pg.fill("#pText", "End Date: 1st June 2024"); pg.wait_for_timeout(500)
    pg.screenshot(path=f"{out}/insp_1_plain.png")
    src0 = pg.get_attribute(".pv-text", "src")
    pg.click("#pB"); pg.fill("#pSpacing", "0.4"); pg.evaluate("document.querySelector('#pColor').value='#1a3c8c'; document.querySelector('#pColor').dispatchEvent(new Event('input'))")
    pg.wait_for_timeout(600)
    print("preview changed after formatting:", pg.get_attribute(".pv-text", "src") != src0, "| font now", pg.input_value("#pFam"), "bold on:", "on" in pg.get_attribute("#pB", "class"))
    pg.screenshot(path=f"{out}/insp_2_formatted.png")
    # drag preview text 30pt right and 3pt down, then back near the ref edge: should snap to ref left
    t = pg.locator(".pv-text").bounding_box(); cx, cy = t["x"] + 20, t["y"] + t["height"]/2
    pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx + 30*k, cy + 3*k, steps=5); pg.mouse.move(cx + 2*k, cy + 0.6*k, steps=5); pg.mouse.up(); pg.wait_for_timeout(500)
    print("after drag-back: left", v("#pX"), "(ref left", pg.evaluate("st.ref.left.toFixed(2)") + ") baseline", v("#pY"))
    pg.click("#pApply"); pg.wait_for_selector("#toast.show"); pg.wait_for_timeout(700)
    print("apply toast:", pg.inner_text("#toast"), "| panel hidden:", pg.is_hidden("#insp"))
    o = bb(); pg.screenshot(path=f"{out}/insp_3_applied.png", clip={"x": o["x"] + 60*k, "y": o["y"] + 405*k, "width": 300*k, "height": 70*k})
    # Move: pick up "Location: Hybrid", push it down 30pt with keys (Shift+Down x15)
    pg.click("[data-mode=move]"); drag((100, 456, 200, 470)); pg.wait_for_selector(".mv-lift")
    for _ in range(15): pg.keyboard.press("Shift+ArrowDown")
    print("move bar:", pg.inner_text(".mv-bar .d")); pg.screenshot(path=f"{out}/insp_4_moving.png")
    pg.keyboard.press("Enter"); pg.wait_for_selector("#toast.show"); pg.wait_for_timeout(700)
    print("move toast:", pg.inner_text("#toast"))
    o = bb(); pg.screenshot(path=f"{out}/insp_5_moved.png", clip={"x": o["x"] + 60*k, "y": o["y"] + 405*k, "width": 300*k, "height": 120*k})
    print("JS errors:", errs or "none")
    b.close()
