"""اختبار متصفح حقيقي لبطاقة الإهداء: إرسال طلب من الموقع العام ← ظهوره في اللوحة ← تجهيز البطاقة ← تحميل الصورة.
يحتاج خادماً يعمل على قاعدة اختبار وحساباً تجريبياً (لا تستخدمي قاعدة الإنتاج):
  ZUM_E2E_USER و ZUM_E2E_PASS   ثم:   python tests/e2e/e2e_gift.py http://127.0.0.1:8765
اختيارياً: SHOTS_DIR لحفظ لقطات الشاشة، و CHROME_PATH لمتصفح مثبت.
"""
import json, os, sys, tempfile, time, urllib.request
TAG = str(int(time.time()))      # اسم فريد لكل تشغيل حتى لا تختلط طلبات الاختبارات
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
USER, PASS = os.environ["ZUM_E2E_USER"], os.environ["ZUM_E2E_PASS"]
SHOTS = os.environ.get("SHOTS_DIR")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORIG = os.path.join(ROOT, "images", "zumurruda_gift_card_page_1.png")
LAUNCH = {"executable_path": os.environ["CHROME_PATH"]} if os.environ.get("CHROME_PATH") else {}
errors = []
def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: errors.append(msg)
def shot(pg, name, **kw):
    if SHOTS: os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, name), **kw)

with sync_playwright() as p:
    b = p.chromium.launch(**LAUNCH)
    # ============ الموقع العام (جوال + حاسوب) ============
    for vw in (390, 1280):
        ctx = b.new_context(viewport={"width": vw, "height": 900}); pg = ctx.new_page()
        console = []
        pg.on("console", lambda m: console.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
        pg.on("pageerror", lambda e: console.append(str(e)))
        pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_selector("#gift")
        pg.evaluate("document.querySelectorAll('.rv').forEach(e=>e.classList.add('in','on','show','vis'))")
        pg.locator("#gift").scroll_into_view_if_needed(); pg.wait_for_timeout(500)
        check(pg.locator("#gcard *").count() == 0, f"[{vw}] صورة البطاقة بلا أي نص مكتوب فوقها")
        bg = pg.evaluate("getComputedStyle(document.querySelector('#gcard')).backgroundImage")
        check("zumurruda_gift_card_page_1.png" in bg, f"[{vw}] صورة البطاقة الأصلية هي الخلفية")
        bx_c, bx_f = pg.locator("#gcard").bounding_box(), pg.locator("#gform").bounding_box()
        if vw >= 1000:
            check(bx_c["x"] + bx_c["width"] <= bx_f["x"] + 2, f"[{vw}] البطاقة على اليسار وحقول الطلب على اليمين")
            ratio = bx_c["width"] / bx_c["height"]; check(abs(ratio - 1242 / 647) < 0.01, f"[{vw}] نسبة أبعاد البطاقة مطابقة للأصل ({ratio:.3f})")
        sw = pg.evaluate("document.documentElement.scrollWidth"); check(sw <= vw, f"[{vw}] لا تمرير أفقي ({sw})")
        # تحقق: إرسال فارغ
        pg.click("#gsend"); pg.wait_for_timeout(150)
        check(pg.locator("#gform .f.bad").count() == 3, f"[{vw}] أخطاء الحقول المطلوبة (إلى/من/الهاتف)")
        check("err" in pg.get_attribute("#gstatus", "class"), f"[{vw}] رسالة خطأ واضحة")
        pg.fill("#gphone", "12"); pg.click("#gsend"); check(pg.locator("#gphone-e").inner_text() != "", f"[{vw}] هاتف غير صالح")
        shot(pg, f"public_gift_error_{vw}.png")
        locator = pg.locator("#gift"); 
        # إرسال صحيح
        pg.fill("#gto", f"مريم {vw} {TAG}"); pg.fill("#gfrom", "سارة"); pg.select_option("#gsv", "حمام مغربي VIP")
        pg.fill("#gmsg-t", "كل عام وأنتِ بخير"); pg.fill("#gphone", "0912345678")
        pg.click("#gsend"); pg.wait_for_selector("#gstatus.ok", timeout=5000)
        check("تم استلام" in pg.inner_text("#gstatus"), f"[{vw}] رسالة نجاح بعد الإرسال")
        check(pg.input_value("#gto") == "", f"[{vw}] تفريغ النموذج بعد النجاح")
        shot(pg, f"public_gift_ok_{vw}.png"); locator.screenshot(path=os.path.join(SHOTS, f"public_gift_section_{vw}.png")) if SHOTS else None
        check(not console, f"[{vw}] لا أخطاء JavaScript في الموقع العام {console}")
        ctx.close()
    # ============ لوحة الإدارة ============
    ctx = b.new_context(viewport={"width": 1366, "height": 900}, accept_downloads=True); pg = ctx.new_page()
    console = []
    pg.on("console", lambda m: console.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.on("pageerror", lambda e: console.append(str(e)))
    pg.goto(BASE + "/admin/"); pg.fill("#u", USER); pg.fill("#p", PASS); pg.click("button[type=submit]")
    pg.wait_for_selector(".stats .stat")
    check(pg.locator("#giftBadge").inner_text() != "", "عدّاد الطلبات الجديدة بجانب القائمة")
    pg.click('#nav a[data-r="gift"]'); pg.wait_for_selector(".gc-row")
    check(pg.locator(".gc-row").count() >= 2, "الطلبات الواردة تظهر في اللوحة")
    shot(pg, "admin_gift_list.png")
    row = pg.locator(".gc-row", has_text=f"مريم 1280 {TAG}").first
    check(row.count() == 1 and "سارة" in row.inner_text() and "حمام مغربي VIP" in row.inner_text(), "بيانات الطلب في القائمة")
    row.locator("a.btn").click(); pg.wait_for_selector("#gcCanvas")
    pg.wait_for_timeout(800)
    info = pg.inner_text(".gc-info")
    check(all(t in info for t in (f"مريم 1280 {TAG}", "سارة", "حمام مغربي VIP", "كل عام وأنتِ بخير", "0912345678")), "كل بيانات الزبونة ظاهرة عند فتح الطلب")
    shot(pg, "admin_gift_editor.png", full_page=True)
    # تحريك النص بالسحب
    cv = pg.locator("#gcCanvas"); box = cv.bounding_box()
    x0 = float(pg.input_value("#gcX")); y0 = float(pg.input_value("#gcY"))
    sx = box["x"] + box["width"] * (x0 / 100 - 0.05); sy = box["y"] + box["height"] * (y0 / 100 - 0.02)
    pg.mouse.move(sx, sy); pg.mouse.down(); pg.mouse.move(sx - 40, sy + 25, steps=6); pg.mouse.up()
    x1 = float(pg.input_value("#gcX")); y1 = float(pg.input_value("#gcY"))
    check(x1 < x0 and y1 > y0, f"السحب يحرّك النص (x {x0}→{x1}, y {y0}→{y1})")
    check(pg.locator("#gcDirty").is_visible(), "مؤشر التعديلات غير المحفوظة")
    # ضبط الحجم والموضع من اللوحة الجانبية
    pg.fill("#gcSize", "34"); pg.fill("#gcX", "84.5"); pg.fill("#gcY", "39.6")
    pg.click('[data-gsel="from"]'); pg.fill("#gcText", "سارة أحمد")
    pg.click('[data-gsel="value"]'); pg.fill("#gcText", "100 د.ل")
    pg.click('[data-gsel="message"]')
    # معاينة
    pg.click('[data-gact="preview"]'); pg.wait_for_selector(".gc-prev"); pg.wait_for_timeout(300)
    nw = pg.evaluate("document.querySelector('.gc-prev').naturalWidth"); check(nw >= 1800, f"معاينة بدقة عالية ({nw}px)")
    shot(pg, "admin_gift_preview.png"); pg.click(".modal [data-close] >> nth=0")
    # حفظ
    pg.click('[data-gact="save-card"]'); pg.wait_for_function("document.querySelector('#gcDirty').hidden")
    # تحميل 2x و 3x
    out = tempfile.mkdtemp()
    for scale, w, h in (("2", 2484, 1294), ("3", 3726, 1941)):
        pg.select_option("#gcScale", scale)
        with pg.expect_download(timeout=20000) as dl: pg.click('[data-gact="download"]')
        path = os.path.join(out, f"card{scale}.png"); dl.value.save_as(path)
        im = Image.open(path); check(im.size == (w, h) and im.mode in ("RGB", "RGBA"), f"تحميل PNG بحجم {w}×{h}: {im.size}")
        check(dl.value.suggested_filename.endswith(".png"), "اسم الملف .png")
    # الصورة المحمّلة تحتوي كتابة، والأصل لم يتغير
    base = Image.open(ORIG).convert("RGB").resize((2484, 1294), Image.LANCZOS)
    got = Image.open(os.path.join(out, "card2.png")).convert("RGB")
    diff = ImageChops.difference(base, got).convert("L").point(lambda v: 255 if v > 40 else 0)
    bbox = diff.getbbox(); check(bbox is not None, "الكتابة ظاهرة فوق صورة البطاقة المحمّلة")
    if SHOTS: got.save(os.path.join(SHOTS, "downloaded_card_2x.png"))
    # مناطق بعيدة عن الكتابة (الشعار على اليسار) تبقى مطابقة للأصل
    logo = (150, 300, 800, 900); d2 = ImageChops.difference(base.crop(logo), got.crop(logo)).convert("L").point(lambda v: 255 if v > 40 else 0)
    check(d2.getbbox() is None, "الشعار والتصميم الأصلي لم يتغيرا")
    # إعادة تحميل الصفحة: التجهيز محفوظ
    pg.reload(); pg.wait_for_selector("#gcCanvas"); pg.wait_for_timeout(600)
    pg.click('[data-gsel="from"]'); check(pg.input_value("#gcText") == "سارة أحمد", "نص «من» المعدَّل محفوظ بعد إعادة التحميل")
    pg.click('[data-gsel="to"]'); check(pg.input_value("#gcSize") == "34" and pg.input_value("#gcX") == "84.5", "الحجم والموضع محفوظان")
    # الحالة
    pg.select_option("#gcStatus", "ready"); pg.click('[data-gact="save-status"]'); pg.wait_for_timeout(400)
    st = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/api/health")).read())
    pg.goto(BASE + "/admin/#/gift"); pg.wait_for_selector(".gc-row"); pg.wait_for_timeout(300)
    check(pg.locator(".gc-row", has_text=f"مريم 1280 {TAG}").locator(".badge", has_text="جاهز").count() == 1, "حالة «جاهز» ظاهرة في القائمة")
    # الجوال للوحة
    pg.set_viewport_size({"width": 390, "height": 860}); pg.goto(BASE + "/admin/#/gift"); pg.wait_for_selector(".gc-row")
    sw = pg.evaluate("document.documentElement.scrollWidth"); check(sw <= 390, f"[admin 390] لا تمرير أفقي في القائمة ({sw})")
    pg.locator(".gc-row a.btn").first.click(); pg.wait_for_selector("#gcCanvas"); pg.wait_for_timeout(600)
    sw = pg.evaluate("document.documentElement.scrollWidth"); check(sw <= 390, f"[admin 390] لا تمرير أفقي في المحرّر ({sw})")
    shot(pg, "admin_gift_editor_390.png", full_page=True)
    check(not console, f"لا أخطاء JavaScript في اللوحة {console}")
    b.close()
print("\nFAILED:" if errors else "\nALL OK", errors if errors else "")
sys.exit(1 if errors else 0)
