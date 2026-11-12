import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import create_app            # noqa: E402
from server.seed_loader import read_seed  # noqa: E402

SEED = read_seed()
# الملف الأصلي كنص، لمقارنة الترتيب حرفياً
def dumps(o):
    return json.dumps(o, ensure_ascii=False, sort_keys=False)


class Step2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dbpath = str(Path(cls.tmp.name) / "t.db")
        cls.app = create_app({"DATABASE": cls.dbpath, "TESTING": True, "PREFERRED_URL_SCHEME": "https"})
        cls.c = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def get(self, url):
        r = self.c.get(url)
        self.assertEqual(r.status_code, 200, url)
        self.assertTrue(r.mimetype == "application/json", url)
        # parse مع حفظ الترتيب (dict في بايثون يحفظ ترتيب الإدراج)
        return json.loads(r.get_data(as_text=True))

    # ---------- مطابقة تامة للبيانات الأصلية (قيماً وترتيباً) ----------
    def test_services(self):
        j = self.get("/api/services")
        self.assertEqual(j["count"], 6)
        self.assertEqual(dumps(j["services"]), dumps(SEED["services"]))

    def test_prices(self):
        j = self.get("/api/prices")
        self.assertEqual((j["count"], j["items_count"]), (9, 55))
        self.assertEqual(dumps(j["prices"]), dumps(SEED["priceCats"]))
        sp = [i["p"] for c in SEED["priceCats"] for g in c["groups"] for i in g["items"]]
        ap = [i["p"] for c in j["prices"] for g in c["groups"] for i in g["items"]]
        self.assertEqual(sp, ap)
        self.assertTrue(all(isinstance(p, str) for p in ap))

    def test_products(self):
        j = self.get("/api/products")
        self.assertEqual(j["count"], 6)
        self.assertEqual(dumps(j["products"]), dumps(SEED["products"]))

    def test_content(self):
        j = self.get("/api/content")
        self.assertEqual(j["count"], 49)
        self.assertEqual(dumps(j["content"]), dumps(SEED["content"]))
        self.assertEqual(dumps(j["fields"]), dumps(SEED["contentFields"]))

    def test_contact(self):
        j = self.get("/api/contact")
        self.assertEqual(dumps(j["contact"]), dumps(SEED["contact"]))
        self.assertEqual(list(j["contact"]), ["facebook", "whatsapp", "map"])

    def test_images(self):
        j = self.get("/api/images")
        self.assertEqual(j["count"], 18)
        self.assertEqual(dumps(j["images"]), dumps(SEED["images"]))

    def test_gallery(self):
        j = self.get("/api/gallery")
        self.assertEqual(j["count"], 6)
        self.assertEqual(dumps(j["gallery"]), dumps(SEED["gallery"]))

    def test_site_all_in_one(self):
        j = self.get("/api/site")
        self.assertEqual(list(j), ["content", "contact", "services", "prices", "products", "images", "gallery"])
        self.assertEqual(dumps(j["content"]), dumps(SEED["content"]))
        self.assertEqual(dumps(j["contact"]), dumps(SEED["contact"]))
        self.assertEqual(dumps(j["services"]), dumps(SEED["services"]))
        self.assertEqual(dumps(j["prices"]), dumps(SEED["priceCats"]))
        self.assertEqual(dumps(j["products"]), dumps(SEED["products"]))
        self.assertEqual(dumps(j["images"]), dumps(SEED["images"]))
        self.assertEqual(dumps(j["gallery"]), dumps(SEED["gallery"]))

    def test_raw_response_is_readable_arabic(self):
        raw = self.c.get("/api/content").get_data(as_text=True)
        self.assertIn("جمالكِ ولياقتكِ وراحتكِ،", raw)
        self.assertNotIn("\\u", raw)

    # ---------- مورد واحد ----------
    def test_single_resources(self):
        for s in SEED["services"]:
            self.assertEqual(self.get(f"/api/services/{s['id']}")["service"], s)
        for c in SEED["priceCats"]:
            self.assertEqual(dumps(self.get(f"/api/prices/{c['id']}")["category"]), dumps(c))
        for p in SEED["products"]:
            self.assertEqual(self.get(f"/api/products/{p['id']}")["product"], p)

    def test_not_found_is_json_404(self):
        for url in ("/api/services/nope", "/api/prices/nope", "/api/products/nope", "/api/unknown",
                    "/api/", "/api"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 404, url)
            self.assertEqual(r.get_json()["error"], "not_found", url)

    # ---------- قراءة فقط ----------
    def test_write_methods_rejected(self):
        for url in ("/api/services", "/api/prices", "/api/products", "/api/content", "/api/contact",
                    "/api/images", "/api/gallery", "/api/site", "/api/health", "/api/services/skin"):
            for m in ("post", "put", "patch", "delete"):
                r = getattr(self.c, m)(url, json={"x": 1})
                # الخطوة 3: القفل الافتراضي؛ الكتابة بلا تسجيل دخول مرفوضة بـ 401
                self.assertEqual(r.status_code, 401, f"{m} {url}")
                self.assertEqual(r.get_json()["error"], "unauthorized")
        # لم يتغير شيء
        self.assertEqual(dumps(self.get("/api/site")["services"]), dumps(SEED["services"]))

    # ---------- عدم كشف الملفات الداخلية ----------
    def test_no_internal_leaks(self):
        urls = ["/api/health", "/api/site", "/api/services", "/api/prices", "/api/products",
                "/api/content", "/api/contact", "/api/images", "/api/gallery"]
        for u in urls:
            raw = self.c.get(u).get_data(as_text=True)
            for bad in (self.dbpath, "zumurrud.db", ".db", "sqlite", "seeded_at", "seed_version",
                        "schema_version", "original_src", "sort", "/home/", "Traceback"):
                self.assertNotIn(bad, raw, f"{bad} in {u}")

    def test_internal_columns_not_exposed(self):
        j = self.get("/api/site")
        keys = set()
        def walk(o):
            if isinstance(o, dict):
                keys.update(o); [walk(v) for v in o.values()]
            elif isinstance(o, list):
                [walk(v) for v in o]
        walk({k: v for k, v in j.items() if k not in ("content", "images")})
        self.assertFalse(keys & {"sort", "cat_id", "group_id", "original_src", "grp", "includes"})

    def test_sql_injection_and_traversal_ids(self):
        for bad in ("' OR '1'='1", "skin' --", "1;DROP TABLE services", "%27%20OR%201=1", "..%2f..%2fserver"):
            r = self.c.get(f"/api/services/{bad}")
            self.assertEqual(r.status_code, 404, bad)
        self.assertEqual(self.get("/api/services")["count"], 6)

    def test_api_cannot_reach_files(self):
        for u in ("/api/../server/config.py", "/api/%2e%2e/data/zumurrud.db", "/api/..%2fmanage.py"):
            self.assertEqual(self.c.get(u).status_code, 404, u)

    def test_headers(self):
        r = self.c.get("/api/site")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")

    def test_db_file_unchanged_by_reads(self):
        import hashlib, glob
        def h():
            return hashlib.sha256(Path(self.dbpath).read_bytes()).hexdigest()
        before = h()
        for u in ("/api/site", "/api/prices", "/api/services/skin"):
            self.c.get(u)
        self.assertEqual(before, h())


if __name__ == "__main__":
    unittest.main(verbosity=2)
