import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from server import create_app                      # noqa: E402
from server.seed_loader import read_seed, seed, snapshot, counts  # noqa: E402
from helpers import add_admin, login, make_app  # noqa: E402

PHASE2_INDEX_MD5 = "b588a33f5236df0e79eb2927114f2cb5"


def md5(b):
    return hashlib.md5(b).hexdigest()


class Step1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = make_app()
        add_admin(cls.app)
        cls.c = cls.app.test_client()
        cls.db = cls.app.mongo_client[cls.app.config["MONGODB_DB"]]

    # --- البيانات ---
    def test_counts_match_phase2_summary(self):
        c = counts(self.db)
        self.assertEqual(c, {"services": 6, "price_categories": 9, "price_items": 55,
                             "products": 6, "texts": 49, "images": 18, "gallery": 6})

    def test_roundtrip_identical_to_seed(self):
        s = read_seed()
        snap = snapshot(self.db)
        for k in ("content", "contentFields", "contact", "services", "priceCats",
                  "products", "images", "gallery"):
            self.assertEqual(snap[k], s[k], k)
        # الأسعار حرفياً
        sp = [i["p"] for c in s["priceCats"] for g in c["groups"] for i in g["items"]]
        dp = [i["p"] for c in snap["priceCats"] for g in c["groups"] for i in g["items"]]
        self.assertEqual(sp, dp)

    def test_seed_is_idempotent(self):
        self.assertFalse(seed(self.db))
        self.assertEqual(counts(self.db)["price_items"], 55)

    def test_restart_keeps_data(self):
        app2 = make_app(MONGO_CLIENT=self.app.mongo_client)
        with app2.test_client() as c:
            c.get("/api/health")
        self.assertEqual(counts(self.db)["price_items"], 55)

    def test_unique_indexes(self):
        # التحقق من أن فهرس اسم المستخدم فريد
        with self.assertRaises(Exception):
            self.db.users.insert_one({"username": "manager1", "password_hash": "x"})

    # --- الملفات الثابتة ---
    def test_public_site_served_byte_identical(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(md5(r.data), PHASE2_INDEX_MD5)
        self.assertEqual(md5(self.c.get("/index.html").data), PHASE2_INDEX_MD5)
        self.assertEqual(md5((ROOT / "index.html").read_bytes()), PHASE2_INDEX_MD5)

    def test_admin_served_byte_identical(self):
        self.assertEqual(login(self.c).status_code, 302)
        for url, f in (("/admin/", "index.html"), ("/admin/app.js", "app.js"),
                       ("/admin/admin.css", "admin.css"), ("/admin/seed.js", "seed.js")):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertEqual(r.data, (ROOT / "admin" / f).read_bytes(), url)
        self.assertEqual(self.c.get("/admin").status_code, 301)
        self.c.delete_cookie("zum_sid")

    def test_images_served(self):
        for p in (ROOT / "images").iterdir():
            r = self.c.get(f"/images/{p.name}")
            self.assertEqual(r.status_code, 200, p.name)
            self.assertEqual(r.data, p.read_bytes(), p.name)

    def test_private_paths_not_exposed(self):
        for url in ("/server/config.py", "/data/zumurrud.db", "/manage.py", "/run.py",
                    "/backup-phase1/zumurrud-phase1.zip", "/tests/test_step1.py",
                    "/admin/../server/config.py", "/images/../server/config.py",
                    "/images/%2e%2e/manage.py", "/README.md", "/requirements.txt"):
            r = self.c.get(url)
            self.assertIn(r.status_code, (302, 404), url)
            self.assertNotIn(b"SECRET_KEY", r.data, url)
            self.assertNotIn(b"SQLite format", r.data, url)

    def test_private_paths_404_when_logged_in(self):
        login(self.c)
        for url in ("/admin/../server/config.py", "/admin/%2e%2e/server/config.py", "/images/../server/config.py"):
            r = self.c.get(url)
            self.assertIn(r.status_code, (404, 308, 301), url)
            self.assertNotIn(b"SECRET_KEY", r.data, url)
        self.c.delete_cookie("zum_sid")

    def test_health(self):
        j = self.c.get("/api/health").get_json()
        self.assertEqual(j["status"], "ok")
        self.assertTrue(j["seeded"])
        self.assertEqual(j["counts"]["price_items"], 55)

    def test_protected_files_unchanged(self):
        sums = json.loads((Path(__file__).parent / "phase2.sha256.json").read_text())
        for rel, h in sums.items():
            if rel in ("admin/index.html", "admin/app.js"):
                continue
            p = ROOT / rel
            if not p.exists():
                continue
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), h, rel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
