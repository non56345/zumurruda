"""الخطوة 8: التجهيز للنشر (Vercel Serverless، .env، فحص الجاهزية، إدارة MongoDB)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from helpers import PASSWORD, USER, add_admin, make_app  # noqa: E402
from server.config import Config  # noqa: E402


class TestOps(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.db = self.app.mongo_client[self.app.config["MONGODB_DB"]]

    def tearDown(self):
        self.app._tmp.cleanup()

    def test_check_and_status(self):
        import manage
        from server.seed_loader import seed
        seed(self.db)
        with mock.patch("manage._get_db", return_value=self.db), \
             mock.patch("manage.get_client", return_value=self.app.mongo_client):
            # دون أدمن وبدون SETUP_TOKEN
            with mock.patch.object(Config, "SETUP_TOKEN", ""):
                r = manage.check_command(self.db)
                self.assertEqual(r, 1)

            # بعد إضافة الأدمن
            add_admin(self.app)
            r = manage.check_command(self.db)
            self.assertEqual(r, 0)

            # فحص حالة status
            r_status = manage.main(["manage.py", "status"])
            self.assertEqual(r_status, 0)

    def test_backup_restore_atlas_guidance(self):
        import manage
        with mock.patch("manage._get_db", return_value=self.db):
            for cmd in ("backup", "list-backups", "restore"):
                r = manage.main(["manage.py", cmd])
                self.assertEqual(r, 1)

    def test_cleanup_uploads(self):
        import manage
        from bson import Binary
        # إضافة صورة يتيمة وصورة مستخدمة
        self.db.uploads.insert_one({
            "_id": "orphan123.jpg",
            "data": Binary(b"test"),
            "content_type": "image/jpeg",
            "size": 4,
            "created_at": 1000.0,
        })
        with mock.patch("manage._get_db", return_value=self.db):
            # dry run لا يحذف
            r = manage.main(["manage.py", "cleanup-uploads", "--dry-run"])
            self.assertEqual(r, 0)
            self.assertIsNotNone(self.db.uploads.find_one({"_id": "orphan123.jpg"}))

            # التنظيف الفعلي
            r = manage.main(["manage.py", "cleanup-uploads"])
            self.assertEqual(r, 0)
            self.assertIsNone(self.db.uploads.find_one({"_id": "orphan123.jpg"}))


class TestEnvFile(unittest.TestCase):
    def test_env_loader(self):
        import load_env
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# تعليق\nZUM_TEST_A=1\nZUM_TEST_B='x y'\nOTHER=bad\nZUM_TEST_C=keep\n", encoding="utf8")
            os.environ["ZUM_TEST_C"] = "already"
            try:
                self.assertTrue(load_env.load(p))
                self.assertEqual(os.environ["ZUM_TEST_A"], "1")
                self.assertEqual(os.environ["ZUM_TEST_B"], "x y")
                self.assertEqual(os.environ["ZUM_TEST_C"], "already")       # البيئة لها الأولوية
                self.assertNotIn("OTHER", os.environ)                       # فقط مفاتيح ZUM_
            finally:
                for k in ("ZUM_TEST_A", "ZUM_TEST_B", "ZUM_TEST_C"):
                    os.environ.pop(k, None)
        self.assertFalse(load_env.load(Path("/nonexistent/.env")))

    def test_no_env_or_db_shipped(self):
        # التأكد من أن .env غير متتبع في git وداخل .gitignore
        r = subprocess.run(["git", "ls-files", ".env"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "")
        self.assertIn(".env", (ROOT / ".gitignore").read_text())
        ex = (ROOT / ".env.example").read_text(encoding="utf8")
        self.assertNotIn("PASSWORD", ex.upper().replace("كلمة المرور", ""))
        self.assertIn("ZUM_COOKIE_SECURE=1", ex)
        self.assertIn("MONGODB_URI", ex)
        self.assertIn("SETUP_TOKEN", ex)


class TestVercelEntryPoints(unittest.TestCase):
    def test_entry_points(self):
        import app
        self.assertTrue(hasattr(app, "app"))
        import wsgi
        self.assertTrue(hasattr(wsgi, "app"))

    def test_vercel_json_configuration(self):
        import json
        vjson_path = ROOT / "vercel.json"
        self.assertTrue(vjson_path.exists())
        data = json.loads(vjson_path.read_text(encoding="utf8"))
        self.assertEqual(data.get("regions"), ["fra1"])
        self.assertTrue(any(r.get("destination") == "/app.py" for r in data.get("rewrites", [])))


class TestHttpExtras(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.c = self.app.test_client()

    def tearDown(self):
        self.app._tmp.cleanup()

    def test_robots(self):
        r = self.c.get("/robots.txt")
        self.assertIn("Disallow: /admin/", r.get_data(as_text=True))

    def test_public_security_headers(self):
        r = self.c.get("/")
        self.assertEqual(r.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(r.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertNotIn("Set-Cookie", r.headers)

    def test_upload_dotfiles_hidden(self):
        self.assertEqual(self.c.get("/uploads/.gitkeep").status_code, 404)
        self.assertEqual(self.c.get("/uploads/..").status_code, 404)

    def test_video_present(self):
        p = ROOT / "images" / "promo-bg.mp4"
        self.assertTrue(p.exists())
        self.assertLess(p.stat().st_size, 3 * 1024 * 1024)


class TestProjectRequirements(unittest.TestCase):
    def test_bat_files_crlf_and_ascii(self):
        win_dir = ROOT / "windows"
        if not win_dir.exists():
            return
        bats = list(win_dir.glob("*.bat"))
        for b in bats:
            data = b.read_bytes()
            self.assertIn(b"\r\n", data, b.name)
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), b.name)     # كل الأسطر CRLF
            data.decode("ascii")                                            # لا مشاكل ترميز في cmd

    def test_requirements(self):
        req = (ROOT / "requirements.txt").read_text()
        for pkg in ("Flask", "Pillow", "pymongo"):
            self.assertIn(pkg, req)
        self.assertNotIn("waitress", req)


if __name__ == "__main__":
    unittest.main(verbosity=2)
