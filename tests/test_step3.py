import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from helpers import PASSWORD, USER, add_admin, csrf_of, login, make_app  # noqa: E402
from server import auth                                                   # noqa: E402
from server.db import connect                                             # noqa: E402

GET_APIS = ["/api/health", "/api/site", "/api/services", "/api/services/skin", "/api/prices",
            "/api/prices/skin", "/api/products", "/api/products/p1", "/api/content", "/api/contact",
            "/api/images", "/api/gallery"]


def cookies(resp):
    return resp.headers.getlist("Set-Cookie")


def sid_cookie(resp):
    return next((c for c in cookies(resp) if c.startswith("zum_sid=")), None)


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


class AuthBase(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        add_admin(self.app)
        self.c = self.app.test_client()

    def tearDown(self):
        self.app._tmp.cleanup()

    def db(self):
        return connect(self.app.config["DATABASE"])


class TestAccounts(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.conn = connect(self.app.config["DATABASE"])

    def tearDown(self):
        self.conn.close()
        self.app._tmp.cleanup()

    def test_no_default_account(self):
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        c = self.app.test_client()
        r = c.get("/admin/login")
        self.assertIn("create-admin", r.get_data(as_text=True))
        self.assertEqual(login(c, "admin", "admin").status_code, 401)

    def test_validation(self):
        bad = [("ab", PASSWORD), ("UPPER name", PASSWORD), ("x" * 40, PASSWORD),
               (USER, "short1!"), (USER, "123456789012"), (USER, "aaaaaaaaaaaa"),
               (USER, "xx" + USER + "Zz9!"), (USER, "password1"), (USER, "A" * 200)]
        for u, p in bad:
            with self.assertRaises(ValueError, msg=(u, p)):
                auth.create_admin(self.conn, u, p)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_hashed_not_plaintext(self):
        auth.create_admin(self.conn, "Manager1", PASSWORD)      # يُطبَّع إلى أحرف صغيرة
        row = self.conn.execute("SELECT * FROM users").fetchone()
        self.assertEqual(row["username"], "manager1")
        self.assertTrue(row["password_hash"].startswith(("scrypt:", "pbkdf2:")))
        self.assertNotIn(PASSWORD, row["password_hash"])
        self.conn.close()
        for suffix in ("", "-wal"):
            f = Path(self.app.config["DATABASE"] + suffix)
            if f.exists():
                self.assertNotIn(PASSWORD.encode(), f.read_bytes())
        self.conn = connect(self.app.config["DATABASE"])

    def test_salted(self):
        a = auth.generate_password_hash(PASSWORD)
        b = auth.generate_password_hash(PASSWORD)
        self.assertNotEqual(a, b)

    def test_single_admin_only(self):
        auth.create_admin(self.conn, USER, PASSWORD)
        with self.assertRaises(ValueError):
            auth.create_admin(self.conn, "second1", PASSWORD)


class TestLogin(AuthBase):
    def test_correct_login_and_cookie_flags(self):
        r = login(self.c)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/admin/"))
        ck = sid_cookie(r)
        self.assertIsNotNone(ck)
        low = ck.lower()
        for flag in ("httponly", "secure", "samesite=lax", "path=/"):
            self.assertIn(flag, low)
        self.assertNotIn("max-age", low)         # كوكي جلسة
        self.assertNotIn("expires", low)
        token = ck.split(";")[0].split("=", 1)[1]
        self.assertGreaterEqual(len(token), 40)
        row = self.db().execute("SELECT token_hash FROM sessions").fetchone()
        self.assertEqual(row["token_hash"], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotEqual(row["token_hash"], token)
        self.assertEqual(self.c.get("/admin/").status_code, 200)

    def test_insecure_cookie_only_when_configured(self):
        app = make_app(COOKIE_SECURE=False)
        add_admin(app)
        r = login(app.test_client())
        self.assertNotIn("secure", sid_cookie(r).lower())
        app._tmp.cleanup()

    def test_wrong_password_and_unknown_user_same_message(self):
        r1 = login(self.c, USER, "Wrong-Password-123!")
        r2 = login(self.c, "nobody", "Wrong-Password-123!")
        self.assertEqual((r1.status_code, r2.status_code), (401, 401))
        self.assertIn(auth.GENERIC_FAIL, r1.get_data(as_text=True))
        self.assertIn(auth.GENERIC_FAIL, r2.get_data(as_text=True))
        self.assertIsNone(sid_cookie(r1))
        self.assertIsNone(sid_cookie(r2))
        self.assertEqual(self.c.get("/admin/").status_code, 302)

    def test_login_requires_csrf_token(self):
        self.c.get("/admin/login")
        r = self.c.post("/admin/login", data={"username": USER, "password": PASSWORD})
        self.assertEqual(r.status_code, 403)
        r = self.c.post("/admin/login", data={"username": USER, "password": PASSWORD, "csrf_token": "forged"})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(sid_cookie(r))

    def test_login_cross_origin_rejected(self):
        self.c.get("/admin/login")
        tok = self.c.get_cookie("zum_login_csrf", path="/admin/login").value
        r = self.c.post("/admin/login", data={"username": USER, "password": PASSWORD, "csrf_token": tok},
                        headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(sid_cookie(r))

    def test_next_open_redirect_blocked(self):
        for nxt in ("https://evil.example", "//evil.example", "/\\evil.example", "/admin//evil", "javascript:1",
                    "/index.html"):
            c = self.app.test_client()
            c.get("/admin/login")
            tok = c.get_cookie("zum_login_csrf", path="/admin/login").value
            r = c.post("/admin/login", data={"username": USER, "password": PASSWORD, "csrf_token": tok, "next": nxt})
            self.assertEqual(r.status_code, 302, nxt)
            self.assertEqual(r.headers["Location"], "/admin/", nxt)
        c = self.app.test_client()
        c.get("/admin/login")
        tok = c.get_cookie("zum_login_csrf", path="/admin/login").value
        r = c.post("/admin/login", data={"username": USER, "password": PASSWORD, "csrf_token": tok,
                                          "next": "/admin/account"})
        self.assertEqual(r.headers["Location"], "/admin/account")

    def test_redirect_after_denied_access_keeps_next(self):
        r = self.c.get("/admin/account")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login?next=/admin/account", r.headers["Location"])

    def test_login_page_when_logged_in_redirects(self):
        login(self.c)
        self.assertEqual(self.c.get("/admin/login").status_code, 302)

    def test_login_page_headers(self):
        r = self.c.get("/admin/login")
        self.assertEqual(r.status_code, 200)
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        ck = [c for c in cookies(r) if c.startswith("zum_login_csrf=")][0].lower()
        self.assertIn("httponly", ck)
        self.assertIn("samesite=lax", ck)

    def test_events_logged_without_secrets(self):
        login(self.c, USER, "Wrong-Password-123!")
        login(self.c)
        rows = self.db().execute("SELECT * FROM auth_events").fetchall()
        self.assertEqual([r["event"] for r in rows], ["login_fail", "login_ok"])
        blob = " ".join(str(tuple(r)) for r in rows)
        self.assertNotIn("Wrong-Password", blob)
        self.assertNotIn(PASSWORD, blob)

    def test_unknown_username_not_stored_in_log(self):
        login(self.c, "mypassword-typed-here", "x")
        r = self.db().execute("SELECT username FROM auth_events").fetchone()
        self.assertIsNone(r["username"])


class TestProtection(AuthBase):
    ADMIN_GETS = ["/admin", "/admin/", "/admin/index.html", "/admin/app.js", "/admin/seed.js",
                  "/admin/admin.css", "/admin/auth.js", "/admin/account", "/admin/session",
                  "/admin/nonexistent", "/admin//app.js", "/%61dmin/app.js", "/admin/./app.js",
                  "/admin/login/../app.js", "/admin/app.js/", "/admin/login/", "/admin/session?check=1"]

    def test_admin_requires_login(self):
        for u in self.ADMIN_GETS:
            r = self.c.get(u)
            self.assertIn(r.status_code, (301, 302, 308, 401, 404), u)
            self.assertNotEqual(r.status_code, 200, u)
            self.assertNotIn(b"ZUM_SEED", r.data, u)
            self.assertNotIn(b"use strict", r.data, u)
            if r.status_code in (301, 302, 308):
                self.assertIn("/admin", r.headers["Location"], u)

    def test_session_endpoint_json_401(self):
        r = self.c.get("/admin/session")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["error"], "unauthorized")

    def test_other_methods_on_admin_blocked(self):
        for m in ("post", "put", "patch", "delete"):
            for u in ("/admin/", "/admin/app.js", "/admin/password", "/admin/account", "/admin/session"):
                r = getattr(self.c, m)(u, data={"a": 1})
                self.assertEqual(r.status_code, 401, f"{m} {u}")
        for u in ("/admin/", "/admin/app.js"):
            for m in ("head", "options"):
                self.assertNotEqual(getattr(self.c, m)(u).status_code, 200, f"{m} {u}")

    def test_public_site_and_get_api_stay_public(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        self.assertEqual(self.c.get("/index.html").status_code, 200)
        self.assertEqual(self.c.get("/images/logo.png").status_code, 200)
        self.assertEqual(self.c.get("/admin/login").status_code, 200)
        for u in GET_APIS:
            r = self.c.get(u)
            self.assertEqual(r.status_code, 200, u)
        self.assertNotIn("Set-Cookie", self.c.get("/").headers)       # الزائر لا يتلقى كوكيز

    def test_admin_after_login_served_unchanged_with_security_headers(self):
        login(self.c)
        for u, f in (("/admin/", "index.html"), ("/admin/app.js", "app.js"), ("/admin/admin.css", "admin.css"),
                     ("/admin/seed.js", "seed.js"), ("/admin/auth.js", "auth.js")):
            r = self.c.get(u)
            self.assertEqual(r.status_code, 200, u)
            self.assertEqual(r.data, (ROOT / "admin" / f).read_bytes(), u)
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        j = self.c.get("/admin/session").get_json()
        self.assertEqual(j["username"], USER)
        self.assertGreaterEqual(len(j["csrf_token"]), 30)

    def test_api_writes_deny_by_default(self):
        for m in ("post", "put", "patch", "delete"):
            for u in ("/api/services", "/api/prices/skin", "/api/anything"):
                self.assertEqual(getattr(self.c, m)(u, json={}).status_code, 401, f"{m} {u}")
        login(self.c)
        tok = csrf_of(self.c)
        for m in ("post", "put", "patch", "delete"):
            # مسجّلة لكن بلا رمز CSRF → 403
            self.assertEqual(getattr(self.c, m)("/api/services", json={}).status_code, 403, m)
            # رمز خاطئ → 403
            self.assertEqual(getattr(self.c, m)("/api/services", json={}, headers={"X-CSRF-Token": "x"}).status_code, 403)
            # مصدر غريب رغم الرمز الصحيح → 403
            r = getattr(self.c, m)("/api/services", json={}, headers={"X-CSRF-Token": tok, "Origin": "https://evil.example"})
            self.assertEqual(r.status_code, 403, m)
            # كل الضوابط مستوفاة → تصل للمسار، وهو غير مُنفَّذ بعد (405)
            self.assertEqual(getattr(self.c, m)("/api/services", json={}, headers={"X-CSRF-Token": tok}).status_code, 405, m)

    def test_csrf_same_origin_header_accepted_but_foreign_rejected(self):
        login(self.c)
        tok = csrf_of(self.c)
        ok = self.c.post("/admin/logout", headers={"X-CSRF-Token": tok, "Origin": "https://localhost"})
        self.assertEqual(ok.status_code, 200)

    def test_original_index_only_gains_auth_script(self):
        orig = (Path(__file__).parent / "phase2.index_admin.html").read_text(encoding="utf8") \
            if (Path(__file__).parent / "phase2.index_admin.html").exists() else None
        cur = (ROOT / "admin" / "index.html").read_text(encoding="utf8")
        self.assertEqual(cur.count('<script src="auth.js"></script>'), 1)
        stripped = cur.replace('<script src="auth.js"></script>\n', "")
        # بطاقة الإهداء: ثلاث إضافات فقط (رابط CSS، عنصر قائمة، سكربت) تُزال هنا قبل مطابقة البصمة الأصلية
        stripped = stripped.replace('<link rel="stylesheet" href="gift.css">\n', "").replace('<script src="gift.js"></script>\n', "")
        stripped = re.sub(r'      <a href="#/gift" data-r="gift">.*?</a>\n', "", stripped, flags=re.S)
        # الخطوة 5: ثلاث عبارات تخص «الوضع التجريبي/localStorage» استُبدلت بنص يصف الحفظ على الخادم؛ لا شيء غيرها
        from test_step5 import ADMIN_INDEX_TEXT_CHANGES
        for old_txt, new_txt in ADMIN_INDEX_TEXT_CHANGES:
            self.assertEqual(stripped.count(new_txt), 1)
            stripped = stripped.replace(new_txt, old_txt)
        import hashlib as h, json
        sums = json.loads((Path(__file__).parent / "phase2.sha256.json").read_text())
        self.assertEqual(h.sha256(stripped.encode("utf8")).hexdigest(), sums["admin/index.html"])


class TestLogout(AuthBase):
    def test_logout_needs_csrf_then_revokes_session(self):
        login(self.c)
        old_cookie = self.c.get_cookie("zum_sid").value
        r = self.c.post("/admin/logout")                       # بلا رمز
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c.get("/admin/").status_code, 200)   # ما زالت الجلسة قائمة
        tok = csrf_of(self.c)
        r = self.c.post("/admin/logout", headers={"X-CSRF-Token": tok})
        self.assertEqual(r.status_code, 200)
        self.assertIn("zum_sid=;", sid_cookie(r))              # حُذف الكوكي
        self.assertEqual(self.c.get("/admin/").status_code, 302)
        self.assertEqual(self.db().execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
        # إعادة استخدام الكوكي القديم (سرقة/إعادة تشغيل) تفشل لأن الجلسة أُلغيت في الخادم
        other = self.app.test_client()
        other.set_cookie("zum_sid", old_cookie)
        self.assertEqual(other.get("/admin/session").status_code, 401)

    def test_logout_get_not_allowed(self):
        login(self.c)
        self.assertIn(self.c.get("/admin/logout").status_code, (404, 405))   # GET لا ينفّذ الخروج
        self.assertEqual(self.c.get("/admin/").status_code, 200)                # والجلسة باقية

    def test_logout_without_session_is_harmless(self):
        r = self.c.post("/admin/logout")
        self.assertIn(r.status_code, (200, 302))

    def test_logout_form_post_redirects(self):
        login(self.c)
        tok = csrf_of(self.c)
        r = self.c.post("/admin/logout", data={"csrf_token": tok})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.c.get("/admin/").status_code, 302)

    def test_new_login_after_logout_gets_new_token(self):
        login(self.c)
        t1 = self.c.get_cookie("zum_sid").value
        self.c.post("/admin/logout", headers={"X-CSRF-Token": csrf_of(self.c)})
        login(self.c)
        self.assertNotEqual(t1, self.c.get_cookie("zum_sid").value)


class TestExpiry(AuthBase):
    def test_idle_expiry(self):
        clk = Clock()
        with mock.patch.object(auth, "now", clk):
            login(self.c)
            clk.t += 29 * 60
            self.assertEqual(self.c.get("/admin/").status_code, 200)      # نشاط يجدّد الخمول
            clk.t += 29 * 60
            self.assertEqual(self.c.get("/admin/").status_code, 200)
            clk.t += 31 * 60                                              # خمول 31 دقيقة
            r = self.c.get("/admin/")
            self.assertEqual(r.status_code, 302)
            self.assertEqual(self.c.get("/admin/session").status_code, 401)
            self.assertEqual(self.db().execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_absolute_expiry_even_if_active(self):
        clk = Clock()
        with mock.patch.object(auth, "now", clk):
            login(self.c)
            for _ in range(15):                                           # 15 × 29 دقيقة ≈ 7.25 ساعة
                clk.t += 29 * 60
                self.assertEqual(self.c.get("/admin/session").status_code, 200)
            clk.t += 29 * 60 * 3                                          # > 8 ساعات
            self.assertEqual(self.c.get("/admin/session").status_code, 401)

    def test_check_mode_does_not_extend(self):
        clk = Clock()
        with mock.patch.object(auth, "now", clk):
            login(self.c)
            clk.t += 20 * 60
            self.assertEqual(self.c.get("/admin/session?check=1").status_code, 200)
            clk.t += 20 * 60                                              # 40 دقيقة منذ آخر نشاط حقيقي
            self.assertEqual(self.c.get("/admin/session?check=1").status_code, 401)

    def test_tampered_or_garbage_cookie(self):
        for v in ("", "abc", "x" * 500, "../../etc/passwd", "' OR 1=1 --"):
            c = self.app.test_client()
            c.set_cookie("zum_sid", v)
            self.assertIn(c.get("/admin/").status_code, (302, 401), v)
            self.assertEqual(c.get("/admin/session").status_code, 401, v)

    def test_session_dies_if_user_deleted(self):
        login(self.c)
        conn = self.db()
        with conn:
            conn.execute("DELETE FROM users")
        conn.close()
        self.assertEqual(self.c.get("/admin/session").status_code, 401)


class TestThrottle(AuthBase):
    def test_lockout_after_five_failures_then_expires(self):
        clk = Clock()
        with mock.patch.object(auth, "now", clk):
            for _ in range(5):
                self.assertEqual(login(self.c, USER, "Wrong-Password-123!").status_code, 401)
            r = login(self.c, USER, PASSWORD)                              # حتى الصحيحة تُرفض أثناء القفل
            self.assertEqual(r.status_code, 429)
            self.assertIsNone(sid_cookie(r))
            self.assertEqual(self.c.get("/admin/").status_code, 302)
            clk.t += 16 * 60
            self.assertEqual(login(self.c, USER, PASSWORD).status_code, 302)

    def test_lock_is_per_ip_so_attacker_cannot_lock_out_owner(self):
        for _ in range(6):
            c = self.app.test_client()
            c.get("/admin/login", environ_overrides={"REMOTE_ADDR": "6.6.6.6"})
            tok = c.get_cookie("zum_login_csrf", path="/admin/login").value
            c.post("/admin/login", data={"username": USER, "password": "bad-bad-bad-bad", "csrf_token": tok},
                   environ_overrides={"REMOTE_ADDR": "6.6.6.6"})
        c = self.app.test_client()
        c.get("/admin/login", environ_overrides={"REMOTE_ADDR": "7.7.7.7"})
        tok = c.get_cookie("zum_login_csrf", path="/admin/login").value
        r = c.post("/admin/login", data={"username": USER, "password": PASSWORD, "csrf_token": tok},
                   environ_overrides={"REMOTE_ADDR": "7.7.7.7"})
        self.assertEqual(r.status_code, 302)

    def test_success_resets_counter(self):
        for _ in range(4):
            login(self.c, USER, "Wrong-Password-123!")
        self.assertEqual(login(self.c).status_code, 302)
        self.c.post("/admin/logout", headers={"X-CSRF-Token": csrf_of(self.c)})
        for _ in range(4):
            self.assertEqual(login(self.c, USER, "Wrong-Password-123!").status_code, 401)

    def test_ip_wide_limit(self):
        for i in range(20):
            login(self.c, f"user{i:03d}", "Wrong-Password-123!")
        self.assertEqual(login(self.c, USER, PASSWORD).status_code, 429)


class TestPasswordChange(AuthBase):
    NEW = "Jasmine-Courtyard-7788!"

    def post(self, c, cur=PASSWORD, new=NEW, conf=None, tok=True):
        data = {"current_password": cur, "new_password": new, "confirm_password": conf or new}
        if tok:
            data["csrf_token"] = csrf_of(c)
        return c.post("/admin/password", data=data)

    def test_requires_login_and_csrf(self):
        self.assertEqual(self.c.post("/admin/password", data={"current_password": PASSWORD}).status_code, 401)
        login(self.c)
        self.assertEqual(self.post(self.c, tok=False).status_code, 403)
        self.assertEqual(login(self.app.test_client(), USER, PASSWORD).status_code, 302)   # لم تتغير

    def test_validation_errors(self):
        login(self.c)
        self.assertEqual(self.post(self.c, cur="Wrong-Password-123!").status_code, 400)
        self.assertEqual(self.post(self.c, conf="Different-Confirm-1!").status_code, 400)
        self.assertEqual(self.post(self.c, new="short").status_code, 400)
        self.assertEqual(self.post(self.c, new=PASSWORD).status_code, 400)
        self.assertEqual(self.post(self.c, new=USER + "-Zzz-99887").status_code, 400)
        self.assertEqual(login(self.app.test_client(), USER, PASSWORD).status_code, 302)

    def test_success_revokes_other_sessions_and_old_password(self):
        other = self.app.test_client()
        login(other)
        login(self.c)
        r = self.post(self.c)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(other.get("/admin/session").status_code, 401)            # الجهاز الآخر أُنهي
        self.assertEqual(self.c.get("/admin/session").status_code, 200)           # هذه الجلسة جُدِّدت
        self.assertEqual(login(self.app.test_client(), USER, PASSWORD).status_code, 401)
        self.assertEqual(login(self.app.test_client(), USER, self.NEW).status_code, 302)
        self.assertIn("تم تغيير كلمة المرور", self.c.get("/admin/account?changed=1").get_data(as_text=True))

    def test_wrong_current_password_is_throttled(self):
        login(self.c)
        for _ in range(5):
            self.assertEqual(self.post(self.c, cur="Wrong-Password-123!").status_code, 400)
        self.assertEqual(self.post(self.c).status_code, 429)


class TestCLI(unittest.TestCase):
    def run_cli(self, db, *args, stdin=""):
        env = dict(os.environ, ZUM_DB=db)
        return subprocess.run([sys.executable, "manage.py", *args], cwd=ROOT, env=env,
                              input=stdin, capture_output=True, text=True, timeout=60)

    def test_create_and_change_password(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "c.db")
            r = self.run_cli(db, "create-admin", stdin=f"{USER}\n{PASSWORD}\n{PASSWORD}\n")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertNotIn(PASSWORD, r.stdout + r.stderr)
            conn = sqlite3.connect(db)
            h = conn.execute("SELECT password_hash FROM users").fetchone()[0]
            self.assertTrue(h.startswith("scrypt:"))
            conn.close()
            r = self.run_cli(db, "create-admin", stdin=f"another1\n{PASSWORD}\n{PASSWORD}\n")
            self.assertNotEqual(r.returncode, 0)
            new = "Lavender-Terrace-4455!"
            r = self.run_cli(db, "change-password", stdin=f"{new}\n{new}\n")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertNotIn(new, r.stdout + r.stderr)
            app = make_app(DATABASE=db)
            self.assertEqual(login(app.test_client(), USER, new).status_code, 302)
            self.assertEqual(login(app.test_client(), USER, PASSWORD).status_code, 401)
            app._tmp.cleanup()

    def test_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "c.db")
            r = self.run_cli(db, "create-admin", stdin=f"{USER}\n{PASSWORD}\nsomething-else-1234\n")
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(sqlite3.connect(db).execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)


class TestNoSecretsInSource(unittest.TestCase):
    def test_no_hardcoded_credentials(self):
        files = [*(ROOT / "server").rglob("*.py"), ROOT / "manage.py", ROOT / "run.py", ROOT / "README.md",
                 *(ROOT / "server" / "templates").glob("*.html"), ROOT / "admin" / "auth.js"]
        for f in files:
            txt = f.read_text(encoding="utf8")
            for bad in ("admin123", "password123", "default password", "كلمة المرور الافتراضية", "changeme"):
                self.assertNotIn(bad, txt.lower(), f"{bad} in {f.name}")
        self.assertNotIn(PASSWORD, (ROOT / "README.md").read_text(encoding="utf8"))


class TestHeaders(AuthBase):
    def test_hsts_only_on_https(self):
        self.assertIn("Strict-Transport-Security", self.c.get("/admin/login").headers)   # الاختبارات تعمل بـ https
        r = self.c.get("/admin/login", base_url="http://localhost")
        self.assertNotIn("Strict-Transport-Security", r.headers)

    def test_nosniff_everywhere(self):
        for u in ("/", "/admin/login", "/api/site"):
            self.assertEqual(self.c.get(u).headers["X-Content-Type-Options"], "nosniff")


if __name__ == "__main__":
    unittest.main(verbosity=2)
