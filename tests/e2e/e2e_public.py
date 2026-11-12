"""اختبار متصفح حقيقي للموقع العام (الخطوة 6 و7): العرض على أحجام الشاشات، الفيديو، الأسعار،
والتأكد أن تعديلاً من اللوحة يظهر في الموقع. يحتاج خادماً يعمل وحساباً تجريبياً (ZUM_E2E_USER/ZUM_E2E_PASS).
  python tests/e2e/e2e_public.py http://127.0.0.1:8765
"""
import json, os, sys, tempfile, urllib.request
from playwright.sync_api import sync_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
USER, PASS = os.environ["ZUM_E2E_USER"], os.environ["ZUM_E2E_PASS"]
LAUNCH = {"executable_path": os.environ["CHROME_PATH"]} if os.environ.get("CHROME_PATH") else {}
OUT = tempfile.gettempdir()
errors = []
def settle(pg):
    """اللوحة تنقل التركيز لأول حقل بعد فتح النافذة بـ 30ms؛ ننتظره قبل الكتابة الآلية حتى لا يتسابقا."""
    pg.wait_for_selector(".modal form"); pg.wait_for_timeout(120)
def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: errors.append(msg)

with sync_playwright() as p:
    b = p.chromium.launch(**LAUNCH)
    for vw, vh in ((360, 760), (390, 844), (768, 1024), (1280, 860)):
        ctx = b.new_context(viewport={"width": vw, "height": vh})
        pg = ctx.new_page(); jserr = []
        pg.on("pageerror", lambda e: jserr.append(str(e)))
        pg.on("console", lambda m: jserr.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
        pg.goto(BASE + "/", wait_until="networkidle")
        check(pg.locator("#ptabs .pt").count() == 9, f"[{vw}] 9 price tabs")
        check(pg.locator("#og .o").count() == 6, f"[{vw}] 6 opal products")
        check(pg.locator("#grid .g").count() == 6, f"[{vw}] 6 gallery items")
        check(pg.locator(".tiles .tile").count() == 4 and pg.locator(".cards .card").count() == 2, f"[{vw}] service tiles/cards")
        pg.wait_for_timeout(1200)
        v = pg.evaluate("(() => { const v = document.getElementById('heroVid'); return {rs: v.readyState, err: v.error && v.error.code, w: v.videoWidth, t: v.currentTime, paused: v.paused}; })()")
        check(v["rs"] >= 2 and v["w"] == 848 and not v["err"], f"[{vw}] hero video loads ({v})")
        sw = pg.evaluate("document.documentElement.scrollWidth")
        check(sw <= vw, f"[{vw}] no horizontal scroll ({sw})")
        pg.screenshot(path=os.path.join(OUT, f"zum_public_{vw}.png"))
        pg.locator("#prices").scroll_into_view_if_needed(); pg.wait_for_timeout(500)
        pg.screenshot(path=os.path.join(OUT, f"zum_public_prices_{vw}.png"))
        check(not jserr, f"[{vw}] no JavaScript errors {jserr}")
        ctx.close()

    # تعديل من اللوحة ← يظهر في الموقع
    ctx = b.new_context(viewport={"width": 1280, "height": 860}); pg = ctx.new_page()
    pg.goto(BASE + "/admin/login"); pg.fill("#u", USER); pg.fill("#p", PASS); pg.click("button[type=submit]"); pg.wait_for_selector(".stats")
    pg.goto(BASE + "/admin/#/prices/hair-rem"); pg.wait_for_selector(".prow")
    pg.locator("[data-act=item-edit]").first.click(); settle(pg); old = pg.input_value("#f_p")
    pg.fill("#f_p", "777"); pg.click(".modal button[type=submit]"); pg.wait_for_selector(".modal", state="detached"); pg.wait_for_timeout(300)
    pg.goto(BASE + "/admin/#/content/hero"); pg.wait_for_selector("#contentForm")
    old_h = pg.input_value("#f_hero_h1b"); pg.fill("#f_hero_h1b", "نص تجريبي للاختبار"); pg.click("#contentForm button[type=submit]"); pg.wait_for_timeout(500)
    pub = b.new_context(viewport={"width": 390, "height": 844}).new_page()
    pub.goto(BASE + "/"); pub.click("#ptabs .pt >> nth=1"); pub.wait_for_timeout(300)
    check("777" in pub.locator("#pbody").inner_text(), "edited price visible on public site")
    check(pub.locator(".hero h1 em").inner_text() == "نص تجريبي للاختبار", "edited hero text visible on public site")
    wa = pub.get_attribute("#wa", "href")
    print("INFO whatsapp button href:", wa)
    # إرجاع القيم
    pg.goto(BASE + "/admin/#/prices/hair-rem"); pg.wait_for_selector(".prow")
    pg.locator("[data-act=item-edit]").first.click(); settle(pg); pg.fill("#f_p", old); pg.click(".modal button[type=submit]"); pg.wait_for_selector(".modal", state="detached")
    pg.goto(BASE + "/admin/#/content/hero"); pg.wait_for_selector("#contentForm"); pg.fill("#f_hero_h1b", old_h); pg.click("#contentForm button[type=submit]"); pg.wait_for_timeout(500)
    pub.goto(BASE + "/"); pub.click("#ptabs .pt >> nth=1"); pub.wait_for_timeout(300)
    check("777" not in pub.locator("#pbody").inner_text() and old in pub.locator("#pbody").inner_text(), f"price restored to original ({old})")
    b.close()
print("FAILURES:", len(errors)); sys.exit(1 if errors else 0)
