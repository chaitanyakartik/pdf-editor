"""UI test on a scanned page: drag a box over a line, check the popover prefills the detected text,
size and font, change one word, apply. Usage: ui_patch_scan.py outdir x0 y0 x1 y1 old new (pdf points)."""
import sys
from playwright.sync_api import sync_playwright
out, x0, y0, x1, y1, old, new = sys.argv[1], *map(float, sys.argv[2:6]), sys.argv[6], sys.argv[7]
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 1000})
    pg.goto("http://localhost:43063"); pg.wait_for_selector(".page img[src]")
    pg.click("[data-mode=patch]")
    page = pg.locator(".page").first; page.scroll_into_view_if_needed()
    pg.evaluate(f"window.scrollTo(0, {y0 * 1.5 - 300})"); pg.wait_for_timeout(300)
    bb = page.bounding_box(); k = 1.5
    pg.mouse.move(bb["x"] + x0 * k, bb["y"] + y0 * k); pg.mouse.down()
    pg.mouse.move(bb["x"] + x1 * k, bb["y"] + y1 * k, steps=6); pg.mouse.up()
    pg.wait_for_function("document.querySelector('.pop textarea') && !document.querySelector('.pop textarea').disabled")
    print("detected:", pg.inner_text(".pop .det"))
    print("prefill :", repr(pg.input_value(".pop textarea")), "size", pg.input_value(".pop .sz"), "font", pg.input_value(".pop .ff"))
    pg.screenshot(path=f"{out}/scanui_pop.png")
    pg.fill(".pop textarea", pg.input_value(".pop textarea").replace(old, new))
    pg.click(".pop [data-ok]"); pg.wait_for_selector("#toast.show"); pg.wait_for_timeout(600)
    print("toast   :", pg.inner_text("#toast"))
    bb = page.bounding_box(); pg.screenshot(path=f"{out}/scanui_after.png", clip={"x": bb["x"] + (x0 - 30) * k, "y": bb["y"] + (y0 - 40) * k, "width": (x1 - x0 + 200) * k, "height": (y1 - y0 + 80) * k})
    b.close()
