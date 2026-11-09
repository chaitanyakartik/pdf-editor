"""UI test for Patch with a reference box. Usage: ui_ref.py outdir. Uses the SR certificate scan (page 1).
A: Set reference over the Start Date line, rewrite the End Date line.  B: Shift-drag a 2-line paragraph
as reference, write into the empty gap below it (should snap to the paragraph's line grid and left edge)."""
import sys
from playwright.sync_api import sync_playwright
out = sys.argv[1]; k = 1.5
def drag(pg, bb, r, shift=False):
    if shift: pg.keyboard.down("Shift")
    pg.mouse.move(bb["x"] + r[0] * k, bb["y"] + r[1] * k); pg.mouse.down()
    pg.mouse.move(bb["x"] + r[2] * k, bb["y"] + r[3] * k, steps=6); pg.mouse.up()
    if shift: pg.keyboard.up("Shift")
def patch(pg, bb, r, text, shot):
    drag(pg, bb, r)
    pg.wait_for_function("document.querySelector('.pop textarea') && !document.querySelector('.pop textarea').disabled")
    print("  popover:", pg.inner_text(".pop .det"), "| prefill:", repr(pg.input_value(".pop textarea")))
    pg.screenshot(path=f"{out}/{shot}_pop.png")
    pg.fill(".pop textarea", text); pg.click(".pop [data-ok]")
    pg.wait_for_selector("#toast.show"); pg.wait_for_timeout(700)
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 1000})
    pg.goto("http://localhost:43063"); pg.wait_for_selector(".page img[src]")
    pg.click("[data-mode=patch]"); pg.evaluate("window.scrollTo(0, 330)"); pg.wait_for_timeout(300)
    bb = pg.locator(".page").first.bounding_box()
    print("A")
    pg.click("#refBtn"); drag(pg, bb, (101, 418, 266, 433))
    pg.wait_for_selector("#refChip:not([hidden])"); print("  ref chip:", pg.inner_text("#refChip"))
    patch(pg, bb, (98, 434, 300, 456), "End Date: 1st June 2024", "refA")
    print("B")
    pg.click("#refClr"); drag(pg, bb, (72, 329, 527, 359), shift=True)
    pg.wait_for_selector("#refChip:not([hidden])"); print("  ref chip:", pg.inner_text("#refChip"))
    patch(pg, bb, (110, 373, 330, 387), "New line in the paragraph gap", "refB")
    bb = pg.locator(".page").first.bounding_box()
    pg.screenshot(path=f"{out}/ref_after.png", clip={"x": bb["x"] + 50 * k, "y": bb["y"] + 305 * k, "width": 330 * k, "height": 170 * k})
    b.close()
