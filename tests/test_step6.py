"""الخطوة 6: الموقع العام يُولَّد من القاعدة، مع بقاء القالب والتصميم دون تغيير."""
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from helpers import add_admin, csrf_of, login, make_app  # noqa: E402
from server import render  # noqa: E402
from server.seed_loader import read_seed  # noqa: E402

SEED = read_seed()
ORIG = (ROOT / "index.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def node_eval(js_expr_src):
    out = subprocess.run([NODE, "-e", js_expr_src], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def extract(page, start, end):
    i = page.index(start)
    return page[i:page.index(end, i) + len(end)]


def main_script(page):
    return extract(page, "<script>\n/* =====", "</script>")[len("<script>"):-len("</script>")]


class TestFidelity(unittest.TestCase):
    """المولّدات تعيد إنتاج الأصل حرفياً من البيانات الأصلية."""

    @classmethod
    def setUpClass(cls):
        cls.tpl = render.Template(ROOT / "index.html", SEED)

    def test_services_markup_identical(self):
        i, j = self.tpl.services_span
        self.assertEqual(render.gen_services(self.tpl, SEED["services"], SEED["images"]), ORIG[i:j])

    def test_form_options_identical(self):
        i, j = self.tpl.form_span
        self.assertEqual(render.gen_form(self.tpl, SEED["services"]), ORIG[i:j])

    def test_text_positions_hold_original_text(self):
        import html
        self.assertEqual(len(self.tpl.text_pos), 46)
        for k, (i, j) in self.tpl.text_pos.items():
            self.assertEqual(html.unescape(ORIG[i:j]), SEED["content"][k], k)

    @unittest.skipUnless(NODE, "node غير متوفر")
    def test_site_and_prices_objects_equal_original_js(self):
        i, j = self.tpl.site_span
        k, m = self.tpl.prices_span
        orig = node_eval(ORIG[i:j] + ORIG[k:m] + "console.log(JSON.stringify({SITE, PRICES}))")
        site = render.site_object(SEED["content"], SEED["contact"], SEED["services"], SEED["images"],
                                  SEED["gallery"], SEED["products"])
        for key in ("name", "pageName", "contact", "images", "gallery", "opal"):
            self.assertEqual(site[key], orig["SITE"][key], key)
        for sid, name in orig["SITE"]["serviceNames"].items():
            self.assertEqual(site["serviceNames"][sid], name, sid)
        self.assertEqual(render.prices_array(SEED["priceCats"]), orig["PRICES"])
        gen = node_eval("const SITE=" + render.js_literal(site) + ";const PRICES=" +
                        render.js_literal(render.prices_array(SEED["priceCats"])) +
                        ";console.log(JSON.stringify({SITE, PRICES}))")
        self.assertEqual(gen["PRICES"], orig["PRICES"])

    def test_template_file_untouched(self):
        sums = json.loads((Path(__file__).parent / "phase2.sha256.json").read_text())
        self.assertEqual(hashlib.sha256((ROOT / "index.html").read_bytes()).hexdigest(), sums["index.html"])

    def test_broken_template_fails_clearly(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "index.html"
            p.write_text(ORIG.replace("<h2 class=\"h2 rv d1\">خدماتنا وأسعارها</h2>", "<h2>x</h2>"), encoding="utf8")
            with self.assertRaises(render.TemplateError):
                render.Template(p, SEED)
            p.write_text(ORIG.replace("const PRICES=[", "const PRICE_LIST=["), encoding="utf8")
            with self.assertRaises(render.TemplateError):
                render.Template(p, SEED)

    def test_js_literal_cannot_break_out(self):
        s = render.js_literal({"x": "</script><script>alert(1)</script> &"})
        self.assertNotIn("</script", s.lower())
        self.assertNotIn(" ", s)


class TestLive(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.app.config["UPLOADS"] = Path(self.app._tmp.name) / "uploads"
        add_admin(self.app)
        self.c = self.app.test_client()
        login(self.c)
        self.h = {"X-CSRF-Token": csrf_of(self.c)}

    def tearDown(self):
        self.app._tmp.cleanup()

    def save(self, mutate):
        j = self.c.get("/api/admin/state").get_json()
        st = copy.deepcopy(j["state"])
        mutate(st)
        r = self.c.put("/api/admin/state", json={"state": st, "rev": j["rev"]}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_json())
        return self.public()

    def public(self):
        cl = self.app.test_client()                      # زائرة بلا جلسة
        r = cl.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(r.headers["Cache-Control"], "no-cache")
        return r.get_data(as_text=True)

    @unittest.skipUnless(NODE, "node غير متوفر")
    def assert_js_ok(self, page):
        src = main_script(page)
        r = subprocess.run([NODE, "--check", "-"], input=src, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def site_prices(self, page):
        site = extract(page, "const SITE = ", "};\n")
        prices = extract(page, "const PRICES=", "];\n")
        return node_eval(site + prices + "console.log(JSON.stringify({SITE, PRICES}))") if NODE else None

    def test_unchanged_is_byte_identical(self):
        self.assertEqual(self.public(), ORIG)
        self.assertEqual(self.save(lambda s: None), ORIG)        # حفظ بلا تغيير لا يغيّر شيئاً

    def test_text_edit_and_escaping(self):
        page = self.save(lambda s: s["content"].update(hero_h1b="<script>alert('x')</script> & جديد",
                                                       about_h2="عنوان جديد"))
        self.assertIn("<em>&lt;script&gt;alert('x')&lt;/script&gt; &amp; جديد</em>", page)
        self.assertNotIn("<script>alert('x')", page)
        self.assertIn('<h2 class="h2 rv d1">عنوان جديد</h2>', page)
        self.assertNotIn(SEED["content"]["about_h2"], page)
        # كل ما عدا النصين بقي كما هو
        self.assertEqual(len(page) - len(ORIG),
                         len("&lt;script&gt;alert('x')&lt;/script&gt; &amp; جديد") - len("في مكان واحد")
                         + len("عنوان جديد") - len(SEED["content"]["about_h2"]))
        self.assert_js_ok(page)

    def test_price_edit_reaches_public_page(self):
        def m(s):
            s["priceCats"][0]["groups"][0]["items"][0]["p"] = "135"
            s["priceCats"][4]["note"] = "ملاحظة </script><b>"
        page = self.save(m)
        self.assert_js_ok(page)
        sp = self.site_prices(page)
        if sp:
            self.assertEqual(sp["PRICES"][0]["groups"][0]["items"][0]["p"], "135")
            self.assertEqual(sp["PRICES"][4]["note"], "ملاحظة </script><b>")
            flat = lambda cats: [i["p"] for c in cats for g in c["groups"] for i in g["items"]]
            self.assertEqual(flat(sp["PRICES"])[1:], flat(SEED["priceCats"])[1:])
        self.assertEqual(page.count("</script>"), ORIG.count("</script>"))

    def test_contact_links(self):
        page = self.save(lambda s: s["contact"].update(whatsapp="218934884148", facebook="https://facebook.com/zumurrud",
                                                       map="https://maps.google.com/?q=1"))
        self.assert_js_ok(page)
        sp = self.site_prices(page)
        if sp:
            self.assertEqual(sp["SITE"]["contact"], {"facebook": "https://facebook.com/zumurrud",
                                                     "whatsapp": "218934884148", "map": "https://maps.google.com/?q=1"})

    def test_add_edit_delete_services(self):
        def m(s):
            s["services"][0]["name"] = "العناية بالبشرة والوجه"
            s["services"] = [x for x in s["services"] if x["id"] != "cafe"]
            s["services"].append({"id": "x1", "name": "خدمة <جديدة>", "en": "", "desc": "وصف", "group": "beauty",
                                  "slot": "svc_x1", "price": ""})
            s["services"].append({"id": "x2", "name": "قسم آخر جديد", "en": "", "desc": "وصف 2", "group": "other",
                                  "slot": "svc_x2", "price": ""})
            s["images"]["svc_x1"] = {"label": "x", "group": "sections", "src": ""}
            s["images"]["svc_x2"] = {"label": "y", "group": "sections", "src": ""}
        page = self.save(m)
        self.assert_js_ok(page)
        self.assertIn("<h3>العناية بالبشرة والوجه<span>Skin Care</span></h3>", page)
        self.assertIn('data-open="svc_x1"', page)
        self.assertIn("<h3>خدمة &lt;جديدة&gt;</h3>", page)
        self.assertNotIn('data-slot="cafe"', page)
        self.assertNotIn('<option value="cafe">', page)
        self.assertIn('<option value="x1">خدمة &lt;جديدة&gt;</option>', page)
        self.assertIn('data-pick="x2">استفسري عن قسم آخر جديد', page)
        self.assertNotIn('<option value="care">', page)            # كما في الأصل
        self.assertEqual(page.count('class="tile rv'), 5)
        self.assertEqual(page.count('<article class="card rv'), 2)
        # بقية الصفحة (قبل الخدمات وبعدها) دون تغيير في التصميم
        self.assertTrue(page.startswith(ORIG[:ORIG.index('    <div class="tiles">')]))

    def test_images_gallery_products(self):
        import io
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (100, 100)).save(b, "JPEG")
        src = self.c.post("/api/admin/upload", data={"file": (io.BytesIO(b.getvalue()), "a.jpg")},
                          headers=self.h, content_type="multipart/form-data").get_json()["src"]

        def m(s):
            s["images"]["skin"]["src"] = src
            s["images"]["promo-poster"]["src"] = src
            s["products"][0]["name"] = "منتج معدّل"
            s["gallery"] = s["gallery"][1:]
        page = self.save(m)
        self.assert_js_ok(page)
        self.assertIn(f'poster="{src}"', page)
        sp = self.site_prices(page)
        if sp:
            self.assertEqual(sp["SITE"]["images"]["skin"], src)
            self.assertEqual(sp["SITE"]["opal"][0], {"slot": "opal1", "cap": "منتج معدّل"})
            self.assertEqual(len(sp["SITE"]["gallery"]), 5)
            self.assertNotIn("promo-poster", sp["SITE"]["images"])

    def test_name_and_footer(self):
        page = self.save(lambda s: s["content"].update(name="الزمردة الجديدة", footer_credit="نص تذييل"))
        self.assertIn("<title>الزمردة الجديدة | بيوتي سنتر", page)
        self.assertEqual(page.count('<b data-site="name">الزمردة الجديدة</b>'), 2)
        self.assertIn("© <span>نص تذييل</span>", page)

    def test_cache_invalidates_on_every_save(self):
        self.assertEqual(self.public(), ORIG)
        self.assertIn("رقم 1", self.save(lambda s: s["content"].update(gallery_h2="رقم 1")))
        self.assertIn("رقم 2", self.save(lambda s: s["content"].update(gallery_h2="رقم 2")))
        r = self.c.post("/api/admin/reset", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.public(), ORIG)


if __name__ == "__main__":
    unittest.main(verbosity=2)
