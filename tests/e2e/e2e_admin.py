"""اختبار متصفح حقيقي للوحة التحكم (الخطوة 5). يحتاج خادماً يعمل على قاعدة اختبار وحساباً تجريبياً:
  ZUM_E2E_USER و ZUM_E2E_PASS  (لا توجد قيم افتراضية؛ لا تستخدمي حساب الإنتاج)
  python tests/e2e/e2e_admin.py http://127.0.0.1:8765
يتطلب: pip install playwright && playwright install chromium   (أو CHROME_PATH لمتصفح Chrome مثبت)
"""
import json, os, sys, tempfile, urllib.request
from PIL import Image
from playwright.sync_api import sync_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
USER, PASS = os.environ["ZUM_E2E_USER"], os.environ["ZUM_E2E_PASS"]
IMG = os.path.join(tempfile.mkdtemp(), "test.jpg")
Image.new("RGB", (1800, 1200), (200, 170, 120)).save(IMG)
LAUNCH = {"executable_path": os.environ["CHROME_PATH"]} if os.environ.get("CHROME_PATH") else {}
errors = []
def settle(pg):
    """اللوحة تنقل التركيز لأول حقل بعد فتح النافذة بـ 30ms؛ ننتظره قبل الكتابة الآلية حتى لا يتسابقا."""
    pg.wait_for_selector(".modal form"); pg.wait_for_timeout(120)
def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: errors.append(msg)
def api(path):
    return json.load(urllib.request.urlopen(BASE + path))
with sync_playwright() as p:
    b = p.chromium.launch(**LAUNCH)
    for vw in (390, 1280):
        ctx = b.new_context(viewport={"width": vw, "height": 860})
        pg = ctx.new_page()
        console = []
        pg.on("console", lambda m: console.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
        pg.on("pageerror", lambda e: console.append(str(e)))
        pg.goto(BASE + "/admin/")
        check("/admin/login" in pg.url, f"[{vw}] redirect to login")
        pg.fill("#u", USER); pg.fill("#p", PASS); pg.click("button[type=submit]")
        pg.wait_for_selector(".stats .stat")
        check(pg.locator(".demo-badge").inner_text() == "متصلة بالخادم" or vw < 700, f"[{vw}] badge text")
        sw = pg.evaluate("document.documentElement.scrollWidth"); check(sw <= vw, f"[{vw}] no horizontal scroll on home ({sw})")
        if vw == 390:
            # --- edit a price
            pg.goto(BASE + "/admin/#/prices/skin"); pg.wait_for_selector(".prow")
            pg.locator("[data-act=item-edit]").first.click(); settle(pg); pg.fill("#f_p", "135"); pg.click(".modal button[type=submit]")
            pg.wait_for_selector(".modal", state="detached")
            pg.wait_for_timeout(300)
            p0 = api("/api/prices/skin")["category"]["groups"][0]["items"][0]["p"]
            check(p0 == "135", "price saved to server (135)")
            # invalid price: client-side validation keeps modal open
            pg.locator("[data-act=item-edit]").first.click(); settle(pg); pg.fill("#f_p", "abc"); pg.click(".modal button[type=submit]")
            check(pg.locator(".modal .field.bad").count() == 1, "invalid price rejected in form")
            pg.click(".modal [data-close] >> nth=0")
            # --- add service with uploaded image
            pg.goto(BASE + "/admin/#/services"); pg.wait_for_selector("[data-act=svc-add]")
            pg.click("[data-act=svc-add]"); settle(pg); pg.fill("#f_name", "خدمة اختبار"); pg.fill("#f_desc", "وصف اختبار")
            pg.set_input_files(".modal [data-imgin]", IMG)
            pg.wait_for_selector(".modal [data-prev] img")
            pg.click(".modal button[type=submit]"); pg.wait_for_selector(".modal", state="detached"); pg.wait_for_timeout(300)
            svcs = api("/api/services")["services"]
            check(svcs[-1]["name"] == "خدمة اختبار", "service added on server")
            src = api("/api/images")["images"][svcs[-1]["slot"]]["src"]
            check(src.startswith("uploads/"), f"service image uploaded ({src})")
            check(urllib.request.urlopen(BASE + "/" + src).status == 200, "uploaded image served")
            # --- delete it
            pg.locator("article.item", has_text="خدمة اختبار").locator("[data-act=svc-del]").click()
            pg.click(".modal button[type=submit]"); pg.wait_for_timeout(500)
            ids = [x["id"] for x in api("/api/services")["services"]]
            check(ids == ["skin", "nails", "massage", "care", "gym", "cafe"], f"only the test service deleted ({ids})")
            # --- content + contact
            pg.goto(BASE + "/admin/#/content/contact-info"); pg.wait_for_selector("#contentForm")
            pg.fill("#f_whatsapp", "+218"); pg.click("#contentForm button[type=submit]")
            check(api("/api/contact")["contact"]["whatsapp"] == "", "invalid whatsapp not saved")
            pg.fill("#f_whatsapp", "218934884148"); pg.click("#contentForm button[type=submit]"); pg.wait_for_timeout(500)
            check(api("/api/contact")["contact"]["whatsapp"] == "218934884148", "whatsapp saved")
            # --- reload persists, log shows
            pg.goto(BASE + "/admin/#/home"); pg.reload(); pg.wait_for_selector(".log li")
            check(pg.locator(".log li").count() >= 3, "activity log loaded from server")
            ls = pg.evaluate("Object.keys(localStorage)")
            check(ls == [], f"nothing written to localStorage ({ls})")
            # --- legacy migration offer
            pg.evaluate("""localStorage.setItem('zumurrud_admin_v1', JSON.stringify(Object.assign({}, window.ZUM_SEED, {log:[]})))""")
            pg.reload(); pg.wait_for_selector("[data-act=legacy-import]")
            check(True, "legacy data card shown")
            pg.click("[data-act=legacy-drop]"); pg.click(".modal button[type=submit]"); pg.wait_for_timeout(300)
            check(pg.evaluate("localStorage.length") == 0, "legacy data dropped")
            # --- conflict: change on server behind the page's back
            pg.goto(BASE + "/admin/#/prices/skin"); pg.wait_for_selector(".prow")
            other = b.new_context(); op = other.new_page(); op.goto(BASE + "/admin/login")
            op.fill("#u", USER); op.fill("#p", PASS); op.click("button[type=submit]"); op.wait_for_selector(".stats")
            op.goto(BASE + "/admin/#/prices/skin"); op.wait_for_selector(".prow")
            op.locator("[data-act=item-edit]").first.click(); settle(op); op.fill("#f_p", "140"); op.click(".modal button[type=submit]"); op.wait_for_timeout(500)
            other.close()
            pg.locator("[data-act=item-edit]").first.click(); settle(pg); pg.fill("#f_p", "150"); pg.click(".modal button[type=submit]"); pg.wait_for_timeout(700)
            check(api("/api/prices/skin")["category"]["groups"][0]["items"][0]["p"] == "140", "stale save rejected (conflict)")
            check("140" in pg.locator(".prow").first.inner_text(), "page reloaded newest data after conflict")
            # restore price
            pg.locator("[data-act=item-edit]").first.click(); settle(pg); pg.fill("#f_p", "120"); pg.click(".modal button[type=submit]"); pg.wait_for_timeout(500)
            check(api("/api/prices/skin")["category"]["groups"][0]["items"][0]["p"] == "120", "price restored to original 120")
            # menu on mobile
            pg.click("#burger"); check(pg.locator("#side.open").count() == 1, "mobile menu opens")
        for r in ("home", "services", "prices", "opal", "images", "content"):
            pg.goto(BASE + f"/admin/#/{r}"); pg.wait_for_timeout(250)
            sw = pg.evaluate("document.documentElement.scrollWidth")
            check(sw <= vw, f"[{vw}] {r}: no horizontal scroll ({sw})")
        pg.screenshot(path=os.path.join(tempfile.gettempdir(), f"zum_admin_{vw}.png"))
        check(not console, f"[{vw}] no JavaScript errors {console}")
        ctx.close()
    b.close()
print("FAILURES:", len(errors))
sys.exit(1 if errors else 0)
