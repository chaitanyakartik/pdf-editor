"""Drive the UI in headless Chromium: edit a text run, patch a box, undo/redo. Screenshots to argv[1]."""
import sys, json, urllib.request
from playwright.sync_api import sync_playwright
out = sys.argv[1]; URL = "http://localhost:43063"
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.goto(URL); pg.wait_for_selector(".sp-box")
    pg.screenshot(path=f"{out}/ui_0_loaded.png")
    # edit: click the customer name span
    box = pg.locator(".sp-box", has=None).nth(3); box.hover(); pg.screenshot(path=f"{out}/ui_1_hover.png")
    box.click(); pg.wait_for_selector(".editor")
    pg.screenshot(path=f"{out}/ui_2_editing.png")
    pg.fill(".editor", " Anjali Deshpande"); pg.keyboard.press("Enter")
    pg.wait_for_selector("#toast.show"); pg.wait_for_timeout(500)
    print("toast:", pg.inner_text("#toast"))
    pg.screenshot(path=f"{out}/ui_3_edited.png")
    # patch: switch mode, drag over the red image square (pdf 420,140 -> 500,220 at scale 1.5)
    pg.click("[data-mode=patch]")
    ov = pg.locator(".page").first.bounding_box()
    pg.mouse.move(ov["x"] + 430 * 1.5, ov["y"] + 160 * 1.5); pg.mouse.down()
    pg.mouse.move(ov["x"] + 490 * 1.5, ov["y"] + 200 * 1.5, steps=5); pg.mouse.up()
    pg.wait_for_selector(".pop"); pg.fill(".pop textarea", "SEEN")
    pg.screenshot(path=f"{out}/ui_4_patch.png")
    pg.click(".pop [data-ok]"); pg.wait_for_timeout(800)
    pg.screenshot(path=f"{out}/ui_5_patched.png")
    meta = json.load(urllib.request.urlopen(URL + "/api/meta")); print("after patch can_undo:", meta["can_undo"], "ver", meta["ver"])
    pg.keyboard.press("Meta+z"); pg.wait_for_timeout(800); pg.screenshot(path=f"{out}/ui_6_undone.png")
    spans = json.load(urllib.request.urlopen(URL + "/api/page/0/spans")); print("spans now:", [s["text"] for s in spans][:5])
    b.close()
