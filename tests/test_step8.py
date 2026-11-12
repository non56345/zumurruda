"""الخطوة 8: التجهيز للنشر (waitress، .env، أوامر النسخ الاحتياطي، فحص الجاهزية، ملفات Windows)."""
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from helpers import PASSWORD, USER, make_app  # noqa: E402


def cli(db, *args, stdin="", extra=None):
    env = {**os.environ, "ZUM_DB": db, "PYTHONUTF8": "1", "ZUM_UPLOADS": str(Path(db).parent / "uploads")}
    env.pop("ZUM_COOKIE_SECURE", None)
    env.update(extra or {})
    return subprocess.run([sys.executable, "manage.py", *args], cwd=ROOT, env=env, input=stdin,
                          capture_output=True, text=True, timeout=60)


class TestOps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "z.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_backup_restore_cycle(self):
        r = cli(self.db, "check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("create-admin", r.stdout)
        self.assertEqual(cli(self.db, "create-admin", stdin=f"{USER}\n{PASSWORD}\n{PASSWORD}\n").returncode, 0)
        r = cli(self.db, "check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("images/skin.jpg", r.stdout)                    # ملاحظة عن الصورة الناقصة
        self.assertEqual(cli(self.db, "check", extra={"ZUM_COOKIE_SECURE": "0"}).returncode, 1)
        r = cli(self.db, "backup")
        self.assertEqual(r.returncode, 0)
        bak = sorted((Path(self.tmp.name) / "backups").glob("*.db"))[0]
        # تعديل ثم استرجاع
        c = sqlite3.connect(self.db)
        c.execute("UPDATE price_items SET price='999'")
        c.commit()
        c.close()
        r = cli(self.db, "restore", bak.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        c = sqlite3.connect(self.db)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM price_items WHERE price='999'").fetchone()[0], 0)
        self.assertTrue(list((Path(self.tmp.name) / "backups").glob("*before-restore*.db")))
        self.assertNotEqual(cli(self.db, "restore", "nope.db").returncode, 0)
        self.assertIn(bak.name, cli(self.db, "list-backups").stdout)

    def test_cleanup_uploads(self):
        cli(self.db, "init-db")
        up = Path(self.tmp.name) / "uploads"
        up.mkdir()
        (up / "orphan123.jpg").write_bytes(b"x")
        (up / ".gitkeep").write_bytes(b"")
        r = cli(self.db, "cleanup-uploads", "--dry-run")
        self.assertIn("1", r.stdout)
        self.assertTrue((up / "orphan123.jpg").exists())
        cli(self.db, "cleanup-uploads")
        self.assertFalse((up / "orphan123.jpg").exists())
        self.assertTrue((up / ".gitkeep").exists())


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
        self.assertFalse((ROOT / ".env").exists())
        self.assertIn(".env", (ROOT / ".gitignore").read_text())
        ex = (ROOT / ".env.example").read_text(encoding="utf8")
        self.assertNotIn("PASSWORD", ex.upper().replace("كلمة المرور", ""))
        self.assertIn("ZUM_COOKIE_SECURE=1", ex)


class TestServers(unittest.TestCase):
    def test_waitress_serves_site(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        tmp = tempfile.TemporaryDirectory()
        env = {**os.environ, "ZUM_DB": str(Path(tmp.name) / "w.db"), "ZUM_PORT": str(port), "PYTHONUTF8": "1",
               "ZUM_UPLOADS": str(Path(tmp.name) / "up")}
        proc = subprocess.Popen([sys.executable, "serve.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        try:
            for _ in range(50):
                try:
                    r = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
                    break
                except OSError:
                    time.sleep(0.2)
            else:
                self.fail("waitress لم يبدأ: " + proc.stderr.read1().decode(errors="ignore"))
            self.assertEqual(r.status, 200)
            self.assertEqual(r.read(), (ROOT / "index.html").read_bytes())
            v = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/images/promo-bg.mp4",
                                                              headers={"Range": "bytes=0-99"}))
            self.assertEqual(v.status, 206)                          # Safari/iOS يحتاج Range للفيديو
            self.assertEqual(len(v.read()), 100)
        finally:
            proc.terminate()
            proc.wait(10)
            proc.stdout.close()
            proc.stderr.close()
            tmp.cleanup()

    def test_wsgi_entry_points(self):
        src = (ROOT / "wsgi.py").read_text(encoding="utf8")
        self.assertIn("app = create_app()", src)
        self.assertIn("application = create_app()", (ROOT / "passenger_wsgi.py").read_text(encoding="utf8"))


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
        up = Path(self.app._tmp.name) / "uploads"
        up.mkdir()
        (up / ".gitkeep").write_text("")
        self.app.config["UPLOADS"] = up
        self.assertEqual(self.c.get("/uploads/.gitkeep").status_code, 404)

    def test_video_present(self):
        p = ROOT / "images" / "promo-bg.mp4"
        self.assertTrue(p.exists())
        self.assertLess(p.stat().st_size, 3 * 1024 * 1024)


class TestWindowsFiles(unittest.TestCase):
    def test_bat_files_crlf_and_ascii(self):
        bats = list((ROOT / "windows").glob("*.bat"))
        self.assertGreaterEqual(len(bats), 4)
        for b in bats:
            data = b.read_bytes()
            self.assertIn(b"\r\n", data, b.name)
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), b.name)     # كل الأسطر CRLF
            data.decode("ascii")                                            # لا مشاكل ترميز في cmd
        self.assertIn(b"ZUM_COOKIE_SECURE=0", (ROOT / "windows" / "run-local.bat").read_bytes())

    def test_requirements(self):
        req = (ROOT / "requirements.txt").read_text()
        for pkg in ("Flask", "Pillow", "waitress"):
            self.assertIn(pkg, req)


if __name__ == "__main__":
    unittest.main(verbosity=2)
