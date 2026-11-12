"""الخطوة 4: واجهة الكتابة المحمية، التحقق، التعارض، السجل، النسخ الاحتياطي، رفع الصور."""
import copy
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PIL import Image  # noqa: E402

from helpers import USER, add_admin, csrf_of, login, make_app  # noqa: E402
from server.db import connect  # noqa: E402
from server.seed_loader import read_seed  # noqa: E402

SEED = read_seed()
KEYS = ("content", "contact", "services", "priceCats", "products", "images", "gallery")


def img_bytes(fmt="JPEG", size=(2400, 1200), mode="RGB", exif=False):
    im = Image.new(mode, size, (10, 107, 58) if mode == "RGB" else (10, 107, 58, 120))
    b = io.BytesIO()
    kw = {}
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretCameraMaker"
        kw["exif"] = ex.tobytes()
    im.save(b, fmt, **kw)
    return b.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.app.config["UPLOADS"] = Path(self.app._tmp.name) / "uploads"
        add_admin(self.app)
        self.c = self.app.test_client()

    def tearDown(self):
        self.app._tmp.cleanup()

    def auth(self):
        login(self.c)
        self.tok = csrf_of(self.c)
        return {"X-CSRF-Token": self.tok}

    def get_state(self):
        j = self.c.get("/api/admin/state").get_json()
        return j["state"], j["rev"]

    def put(self, state, rev, msg="اختبار", **extra):
        return self.c.put("/api/admin/state", json={"state": state, "rev": rev, "msg": msg, **extra},
                          headers={"X-CSRF-Token": self.tok})


class TestAccess(Base):
    def test_all_admin_api_requires_login(self):
        for m, u in (("get", "/api/admin/state"), ("put", "/api/admin/state"), ("post", "/api/admin/reset"),
                     ("post", "/api/admin/upload"), ("post", "/api/admin/backup"), ("get", "/api/admin/nope")):
            r = getattr(self.c, m)(u)
            self.assertEqual(r.status_code, 401, f"{m} {u}")
            self.assertEqual(r.get_json()["error"], "unauthorized")

    def test_writes_need_csrf_and_same_origin(self):
        h = self.auth()
        st, rev = self.get_state()
        self.assertEqual(self.c.put("/api/admin/state", json={"state": st, "rev": rev}).status_code, 403)
        r = self.c.put("/api/admin/state", json={"state": st, "rev": rev},
                       headers={**h, "Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c.post("/api/admin/reset").status_code, 403)
        self.assertEqual(self.c.post("/api/admin/upload", data={}).status_code, 403)
        self.assertEqual(self.get_state()[1], 0)             # لم يتغير شيء

    def test_public_api_still_read_only(self):
        h = self.auth()
        self.assertEqual(self.c.put("/api/services", json={}, headers=h).status_code, 405)


class TestState(Base):
    def test_state_matches_seed_exactly(self):
        self.auth()
        st, rev = self.get_state()
        self.assertEqual(rev, 0)
        for k in KEYS:
            self.assertEqual(st[k], SEED[k], k)
        self.assertEqual(st["log"], [])

    def test_noop_save_keeps_every_price_byte_identical(self):
        self.auth()
        st, rev = self.get_state()
        r = self.put(st, rev)
        self.assertEqual(r.status_code, 200, r.get_json())
        st2, rev2 = self.get_state()
        self.assertEqual(rev2, 1)
        for k in KEYS:
            self.assertEqual(st2[k], SEED[k], k)
        self.assertEqual(self.c.get("/api/prices").get_json()["prices"], SEED["priceCats"])

    def test_edit_price_reaches_public_api_and_log(self):
        self.auth()
        st, rev = self.get_state()
        st["priceCats"][0]["groups"][0]["items"][0]["p"] = "130"
        r = self.put(st, rev, "تعديل بند «تنظيف البشرة الكلاسيكي» (130 د.ل)")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["log"][0]["m"], "تعديل بند «تنظيف البشرة الكلاسيكي» (130 د.ل)")
        self.assertEqual(r.get_json()["log"][0]["u"], USER)
        p = self.c.get("/api/prices/skin").get_json()["category"]["groups"][0]["items"][0]
        self.assertEqual(p["p"], "130")
        # بقية الأسعار لم تتغير
        others = [i["p"] for c in SEED["priceCats"] for g in c["groups"] for i in g["items"]][1:]
        now = [i["p"] for c in self.c.get("/api/prices").get_json()["prices"] for g in c["groups"] for i in g["items"]][1:]
        self.assertEqual(now, others)

    def test_add_and_delete_everything(self):
        self.auth()
        st, rev = self.get_state()
        st["services"].append({"id": "x1", "name": "خدمة جديدة", "en": "", "desc": "وصف", "group": "beauty",
                               "slot": "svc_x1", "price": "50–70"})
        st["images"]["svc_x1"] = {"label": "خدمة جديدة", "group": "sections", "src": ""}
        st["priceCats"].append({"id": "newc", "t": "قسم", "groups": [{"g": "مجموعة", "items": [{"n": "بند", "p": "10"}]}]})
        st["products"] = st["products"][1:]
        st["gallery"] = st["gallery"][:2]
        r = self.put(st, rev)
        self.assertEqual(r.status_code, 200, r.get_json())
        j = self.c.get("/api/health").get_json()["counts"]
        self.assertEqual((j["services"], j["price_categories"], j["price_items"], j["products"], j["gallery"]),
                         (7, 10, 56, 5, 2))

    def test_conflict_detected(self):
        self.auth()
        st, rev = self.get_state()
        self.assertEqual(self.put(st, rev).status_code, 200)
        st["content"]["hero_h1b"] = "نص قديم"
        r = self.put(st, rev)                                  # rev قديم
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["rev"], 1)
        self.assertEqual(self.c.get("/api/content").get_json()["content"]["hero_h1b"], SEED["content"]["hero_h1b"])

    def test_reset_restores_seed_and_backs_up(self):
        self.auth()
        st, rev = self.get_state()
        st["priceCats"] = []
        self.assertEqual(self.put(st, rev).status_code, 200)
        r = self.c.post("/api/admin/reset", headers={"X-CSRF-Token": self.tok})
        self.assertEqual(r.status_code, 200)
        for k in KEYS:
            self.assertEqual(r.get_json()["state"][k], SEED[k], k)
        backups = list((Path(self.app.config["DATABASE"]).parent / "backups").glob("*reset*.db"))
        self.assertEqual(len(backups), 1)
        # النسخة الاحتياطية تحتوي البيانات قبل الاستعادة (بلا أقسام أسعار)
        self.assertEqual(connect(str(backups[0])).execute("SELECT COUNT(*) FROM price_cats").fetchone()[0], 0)

    def test_import_flag_makes_backup(self):
        self.auth()
        st, rev = self.get_state()
        self.assertEqual(self.put(st, rev, **{"import": True}).status_code, 200)
        self.assertTrue(list((Path(self.app.config["DATABASE"]).parent / "backups").glob("*import*.db")))

    def test_periodic_backup_only_once_per_interval(self):
        self.auth()
        for _ in range(3):
            st, rev = self.get_state()
            self.assertEqual(self.put(st, rev).status_code, 200)
        self.assertEqual(len(list((Path(self.app.config["DATABASE"]).parent / "backups").glob("*auto*.db"))), 1)

    def test_manual_backup_endpoint(self):
        h = self.auth()
        r = self.c.post("/api/admin/backup", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertIn("manual", r.get_json()["file"])


class TestValidation(Base):
    def bad(self, mutate, where_part=""):
        st, rev = self.get_state()
        mutate(st)
        r = self.put(st, rev)
        self.assertEqual(r.status_code, 400, r.get_json())
        self.assertTrue(r.get_json()["message"])
        if where_part:
            self.assertIn(where_part, r.get_json()["where"])
        self.assertEqual(self.get_state()[1], 0)               # لم يُحفظ شيء

    def setUp(self):
        super().setUp()
        self.auth()

    def test_rejections(self):
        item = lambda s: s["priceCats"][1]["groups"][0]["items"][0]
        cases = [
            (lambda s: item(s).__setitem__("p", "abc"), "items"),
            (lambda s: item(s).__setitem__("p", ""), "items"),
            (lambda s: item(s).__setitem__("p", "10-"), "items"),
            (lambda s: item(s).__setitem__("n", "   "), "items"),
            (lambda s: s["services"][0].__setitem__("name", ""), "services"),
            (lambda s: s["services"][0].__setitem__("group", "x"), "services"),
            (lambda s: s["services"][0].__setitem__("slot", "nope"), "services"),
            (lambda s: s["services"].append(dict(s["services"][0])), "services"),          # معرّف مكرر
            (lambda s: s["services"][0].__setitem__("id", "../x"), "services"),
            (lambda s: s["content"].__setitem__("evil", "x"), "content"),
            (lambda s: s["content"].pop("hero_h1a"), "content"),
            (lambda s: s["content"].__setitem__("hero_h1a", ""), "content"),
            (lambda s: s["content"].__setitem__("hero_sub", "x" * 2001), "content"),
            (lambda s: s["contact"].__setitem__("facebook", "javascript:alert(1)"), "facebook"),
            (lambda s: s["contact"].__setitem__("facebook", "http://facebook.com/x"), "facebook"),
            (lambda s: s["contact"].__setitem__("map", "https://x"), "map"),
            (lambda s: s["contact"].__setitem__("whatsapp", "+218 91"), "whatsapp"),
            (lambda s: s["images"]["nails"].__setitem__("src", "data:image/png;base64,AAAA"), "images"),
            (lambda s: s["images"]["nails"].__setitem__("src", "https://evil.example/x.jpg"), "images"),
            (lambda s: s["images"]["nails"].__setitem__("src", "images/../server/config.py"), "images"),
            (lambda s: s["images"]["nails"].__setitem__("src", "uploads/missing.jpg"), "images"),
            (lambda s: s["images"].pop("skin"), "images"),
            (lambda s: s["images"]["nails"].__setitem__("group", "x"), "images"),
            (lambda s: s["gallery"][0].__setitem__("cat", "x"), "gallery"),
            (lambda s: s["gallery"][0].__setitem__("slot", "ghost"), "gallery"),
            (lambda s: s["priceCats"][0]["groups"].append({"pk": 1, "items": []}), "priceCats"),
            (lambda s: s["priceCats"][1]["groups"][0].__setitem__("g", ""), "priceCats"),
            (lambda s: s["products"][0].__setitem__("price", "free"), "products"),
            (lambda s: s.__setitem__("services", "x"), "services"),
        ]
        for i, (mut, where) in enumerate(cases):
            with self.subTest(i=i):
                self.bad(mut, where)

    def test_malformed_bodies(self):
        h = {"X-CSRF-Token": self.tok}
        for body in (None, [], {"state": []}, {"state": {}}, {"state": {}, "rev": "0"}):
            r = self.c.put("/api/admin/state", json=body, headers=h)
            self.assertEqual(r.status_code, 400, body)
        r = self.c.put("/api/admin/state", data="not json", headers={**h, "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 400)

    def test_html_is_stored_as_plain_text(self):
        st, rev = self.get_state()
        st["content"]["hero_h1b"] = '<script>alert(1)</script>'
        self.assertEqual(self.put(st, rev).status_code, 200)
        self.assertEqual(self.c.get("/api/content").get_json()["content"]["hero_h1b"], '<script>alert(1)</script>')

    def test_price_ranges_and_arabic_digits_accepted(self):
        st, rev = self.get_state()
        st["priceCats"][0]["groups"][0]["items"][0]["p"] = "٥٠–١٠٠"
        self.assertEqual(self.put(st, rev).status_code, 200)


class TestUpload(Base):
    def up(self, data, name="a.jpg", kind="image"):
        return self.c.post("/api/admin/upload", data={"file": (io.BytesIO(data), name), "kind": kind},
                           headers={"X-CSRF-Token": self.tok}, content_type="multipart/form-data")

    def setUp(self):
        super().setUp()
        self.auth()

    def test_jpeg_resized_and_exif_stripped(self):
        r = self.up(img_bytes(exif=True))
        self.assertEqual(r.status_code, 200, r.get_json())
        j = r.get_json()
        self.assertRegex(j["src"], r"^uploads/[0-9a-f]{20}\.jpg$")
        self.assertEqual((j["width"], j["height"]), (1600, 800))
        f = self.app.config["UPLOADS"] / j["src"].split("/")[1]
        data = f.read_bytes()
        self.assertNotIn(b"SecretCameraMaker", data)
        # يُقدَّم للعامة
        self.c.delete_cookie("zum_sid")
        pub = self.c.get("/" + j["src"])
        self.assertEqual(pub.status_code, 200)
        self.assertEqual(pub.data, data)

    def test_logo_stays_png_with_alpha(self):
        r = self.up(img_bytes("PNG", (1000, 1000), "RGBA"), "logo.png", "logo")
        j = r.get_json()
        self.assertTrue(j["src"].endswith(".png"))
        self.assertEqual(j["width"], 700)
        im = Image.open(self.app.config["UPLOADS"] / j["src"].split("/")[1])
        self.assertEqual(im.mode, "RGBA")

    def test_webp_and_gif_accepted(self):
        self.assertEqual(self.up(img_bytes("WEBP", (300, 300)), "a.webp").status_code, 200)
        self.assertEqual(self.up(img_bytes("GIF", (300, 300)), "a.gif").status_code, 200)

    def test_rejects_non_images_and_spoofed_extensions(self):
        for data, name in ((b"<?php echo 1; ?>", "x.jpg"), (b"GIF89a<script>", "x.gif"), (b"", "x.png"),
                           (b"%PDF-1.4 ...", "x.png"), (img_bytes("BMP", (50, 50)), "x.bmp")):
            r = self.up(data, name)
            self.assertEqual(r.status_code, 400, name)
        self.assertEqual(self.c.post("/api/admin/upload", data={}, headers={"X-CSRF-Token": self.tok}).status_code, 400)
        self.assertFalse(any(self.app.config["UPLOADS"].glob("*")) if self.app.config["UPLOADS"].exists() else False)

    def test_too_large(self):
        r = self.up(b"\xff" * (13 * 1024 * 1024))
        self.assertEqual(r.status_code, 413)

    def test_uploaded_image_usable_in_state(self):
        src = self.up(img_bytes()).get_json()["src"]
        st, rev = self.c.get("/api/admin/state").get_json().values()
        st = copy.deepcopy(st)
        st["images"]["skin"]["src"] = src
        r = self.c.put("/api/admin/state", json={"state": st, "rev": rev}, headers={"X-CSRF-Token": self.tok})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get("/api/images").get_json()["images"]["skin"]["src"], src)

    def test_uploads_path_traversal(self):
        for u in ("/uploads/../server/config.py", "/uploads/%2e%2e/manage.py", "/uploads/"):
            r = self.c.get(u)
            self.assertIn(r.status_code, (404, 308), u)
            self.assertNotIn(b"SCHEMA_PATH", r.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
