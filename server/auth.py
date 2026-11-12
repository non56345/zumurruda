"""المصادقة وحماية لوحة الإدارة (المرحلة الثالثة – الخطوة 3).

- كلمات المرور: تجزئة scrypt (Werkzeug) بملح عشوائي؛ لا تُخزَّن ولا تُسجَّل كنص.
- الجلسات: على الخادم (SQLite). الكوكي يحمل رمزاً عشوائياً فقط، ويُخزَّن SHA-256 له.
  تنتهي بالخمول أو بالحد الأقصى، وتُلغى عند الخروج أو تغيير كلمة المرور.
- CSRF: رمز لكل جلسة (ترويسة X-CSRF-Token أو حقل نموذج) + فحص Origin/Referer.
- الحماية افتراضياً-مغلقة: كل مسار تحت /admin وكل طلب كتابة تحت /api يتطلب جلسة ورمز CSRF،
  عدا مسارات الدخول/الخروج المذكورة صراحةً في PUBLIC_ENDPOINTS.
- لا يوجد مستخدم أو كلمة مرور افتراضية: يُنشأ الحساب عبر `python3 manage.py create-admin`.
"""
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import quote, urlparse

from flask import (Blueprint, current_app, g, jsonify, make_response, redirect,
                   render_template, request)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

bp = Blueprint("auth", __name__, url_prefix="/admin")

COOKIE = "zum_sid"
LOGIN_CSRF_COOKIE = "zum_login_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_ENDPOINTS = {"auth.login_page", "auth.login_submit", "auth.logout", "gift_public.create_order"}   # الأخير: إرسال طلب بطاقة إهداء من الزبون (يحفظ الطلب فقط)
GENERIC_FAIL = "اسم المستخدم أو كلمة المرور غير صحيحة."
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
_COMMON = {"password", "password1", "123456789012", "qwertyuiopas", "zumurrud", "zumurrud1234",
           "administrator", "adminadmin12", "letmein12345", "iloveyou1234"}
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing")


def now():
    return time.time()


# ------------------------------------------------------------------ كلمات المرور والحسابات
def validate_username(name):
    n = (name or "").strip().lower()
    if not USERNAME_RE.match(n):
        return None, "اسم المستخدم: من 3 إلى 32 حرفاً (أحرف إنجليزية صغيرة وأرقام و . _ - فقط)."
    return n, None


def validate_password(pw, username=""):
    if not isinstance(pw, str) or len(pw) < 12:
        return "كلمة المرور يجب ألا تقل عن 12 حرفاً."
    if len(pw) > 128:
        return "كلمة المرور يجب ألا تزيد عن 128 حرفاً."
    low = pw.lower()
    if username and username.lower() in low:
        return "كلمة المرور يجب ألا تحتوي اسم المستخدم."
    if low in _COMMON or len(set(pw)) < 5 or pw.isdigit():
        return "كلمة المرور ضعيفة أو شائعة؛ اختاري كلمة أصعب."
    return None


def admin_exists(conn):
    return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def create_admin(conn, username, password):
    """ينشئ حساب المديرة الأول. يرفض إن وُجد حساب. يرفع ValueError برسالة عربية."""
    name, err = validate_username(username)
    if err:
        raise ValueError(err)
    err = validate_password(password, name)
    if err:
        raise ValueError(err)
    if admin_exists(conn):
        raise ValueError("يوجد حساب مدير بالفعل. استخدمي change-password لتغيير كلمة المرور.")
    t = now()
    with conn:
        conn.execute("INSERT INTO users(username,password_hash,created_at,updated_at) VALUES(?,?,?,?)",
                     (name, generate_password_hash(password), t, t))
    return name


def set_password(conn, user_id, new_password):
    """يغيّر كلمة المرور ويُلغي كل جلسات هذا المستخدم."""
    u = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    if not u:
        raise ValueError("المستخدم غير موجود.")
    err = validate_password(new_password, u["username"])
    if err:
        raise ValueError(err)
    with conn:
        conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
                     (generate_password_hash(new_password), now(), user_id))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def verify_credentials(conn, username, password):
    n = (username or "").strip().lower()
    row = conn.execute("SELECT * FROM users WHERE username=?", (n,)).fetchone()
    # نفّذ تجزئة دائماً حتى لا يكشف الزمن وجود الحساب
    ok = check_password_hash(row["password_hash"] if row else _DUMMY_HASH, password or "")
    return row if (row and ok) else None


# ------------------------------------------------------------------ تقييد المحاولات
def _client_ip():
    return request.remote_addr or "?"


def _lock_remaining(conn, key):
    r = conn.execute("SELECT locked_until FROM login_attempts WHERE key=?", (key,)).fetchone()
    return max(0, int(r["locked_until"] - now())) if r else 0


def _register_fail(conn, key, limit):
    cfg, t = current_app.config, now()
    r = conn.execute("SELECT * FROM login_attempts WHERE key=?", (key,)).fetchone()
    if r is None or t - r["first_fail"] > cfg["LOGIN_WINDOW_SECONDS"] or (0 < r["locked_until"] <= t):
        fails, first = 1, t
    else:
        fails, first = r["fails"] + 1, r["first_fail"]
    locked = t + cfg["LOGIN_LOCK_SECONDS"] if fails >= limit else 0
    conn.execute("INSERT INTO login_attempts(key,fails,first_fail,locked_until) VALUES(?,?,?,?) "
                 "ON CONFLICT(key) DO UPDATE SET fails=?, first_fail=?, locked_until=?",
                 (key, fails, first, locked, fails, first, locked))


def _keys(username):
    ip = _client_ip()
    return (f"ip:{ip}", f"pair:{(username or '').strip().lower()[:64]}|{ip}")


def locked_seconds(conn, username):
    return max(_lock_remaining(conn, k) for k in _keys(username))


def note_failure(conn, username):
    k_ip, k_pair = _keys(username)
    cfg = current_app.config
    with conn:
        _register_fail(conn, k_ip, cfg["LOGIN_MAX_FAILS_IP"])
        _register_fail(conn, k_pair, cfg["LOGIN_MAX_FAILS"])


def note_success(conn, username):
    with conn:
        conn.execute("DELETE FROM login_attempts WHERE key=?", (_keys(username)[1],))


def log_event(conn, event, username=None):
    with conn:
        conn.execute("INSERT INTO auth_events(ts,event,username,ip) VALUES(?,?,?,?)",
                     (now(), event, username, _client_ip()))


# ------------------------------------------------------------------ الجلسات
def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _set_cookie(resp, name, value, path="/", max_age=None):
    resp.set_cookie(name, value, httponly=True, secure=current_app.config["COOKIE_SECURE"],
                    samesite="Lax", path=path, max_age=max_age)


def start_session(conn, user_id, resp):
    cfg, t = current_app.config, now()
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with conn:
        conn.execute("DELETE FROM sessions WHERE created_at < ? OR last_seen < ?",
                     (t - cfg["SESSION_MAX_SECONDS"], t - cfg["SESSION_IDLE_SECONDS"]))
        conn.execute("INSERT INTO sessions(token_hash,user_id,csrf,created_at,last_seen,ip) "
                     "VALUES(?,?,?,?,?,?)", (_hash(token), user_id, csrf, t, t, _client_ip()))
    _set_cookie(resp, COOKIE, token)          # كوكي جلسة (يزول بإغلاق المتصفح) + انتهاء من الخادم
    return resp


def end_session(conn, resp):
    token = request.cookies.get(COOKIE)
    if token:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))
    resp.delete_cookie(COOKIE, path="/", secure=current_app.config["COOKIE_SECURE"],
                       httponly=True, samesite="Lax")
    return resp


def current_session(conn, touch=True):
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 200:
        return None
    th, cfg, t = _hash(token), current_app.config, now()
    row = conn.execute("SELECT s.*, u.username FROM sessions s JOIN users u ON u.id=s.user_id "
                       "WHERE s.token_hash=?", (th,)).fetchone()
    if row is None:
        return None
    if t - row["created_at"] > cfg["SESSION_MAX_SECONDS"] or t - row["last_seen"] > cfg["SESSION_IDLE_SECONDS"]:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
        return None
    if touch:
        with conn:
            conn.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (t, th))
    return row


# ------------------------------------------------------------------ CSRF
def _origin_ok():
    src = request.headers.get("Origin") or request.headers.get("Referer")
    if not src:
        return True            # عملاء غير متصفحية؛ يبقى رمز CSRF مطلوباً
    if src == "null":
        return False
    return urlparse(src).netloc == request.host


def _csrf_ok(expected):
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    return bool(expected) and hmac.compare_digest(sent, expected)


def safe_next(value):
    if not value:
        return "/admin/"
    u = urlparse(value)
    if u.scheme or u.netloc or not value.startswith("/admin") or value.startswith("/admin//") or "\\" in value:
        return "/admin/"
    return value


def _is_admin_path(p):
    return p == "/admin" or p.startswith("/admin/")


def _is_api_path(p):
    return p == "/api" or p.startswith("/api/")


def _deny(status=401, message="يلزم تسجيل الدخول."):
    p = request.path
    wants_json = (_is_api_path(p) or p.startswith("/admin/session") or request.method != "GET"
                  or "application/json" in request.headers.get("Accept", ""))
    if not wants_json:
        nxt = request.full_path.rstrip("?")
        return redirect(f"/admin/login?next={quote(nxt, safe='/')}" if nxt.startswith("/admin") else "/admin/login", 302)
    resp = jsonify(error="unauthorized" if status == 401 else "forbidden", message=message)
    resp.status_code = status
    return resp


def guard():
    """before_request: القفل الافتراضي لكل ما هو إداري."""
    p, m = request.path, request.method
    admin_api = p == "/api/admin" or p.startswith("/api/admin/")
    if not (_is_admin_path(p) or admin_api or (_is_api_path(p) and m not in SAFE_METHODS)):
        return None                                  # الموقع العام وواجهات GET العامة
    unsafe = m not in SAFE_METHODS
    if unsafe and not _origin_ok():
        return _deny(403, "مصدر الطلب غير مسموح.")
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    sess = current_session(get_db(), touch=request.args.get("check") != "1")
    if sess is None:
        return _deny()
    if unsafe and not _csrf_ok(sess["csrf"]):
        return _deny(403, "رمز CSRF غير صالح.")
    g.session = sess
    return None


def add_security_headers(resp):
    if _is_admin_path(request.path):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    if request.is_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    return resp


# ------------------------------------------------------------------ المسارات
def _login_page(error=None, username="", nxt="/admin/", status=200, token=None):
    token = token or request.cookies.get(LOGIN_CSRF_COOKIE) or secrets.token_urlsafe(24)
    resp = make_response(render_template("login.html", error=error, username=username,
                                         next=nxt, csrf=token, has_admin=admin_exists(get_db())), status)
    _set_cookie(resp, LOGIN_CSRF_COOKIE, token, path="/admin/login")
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
    return resp


@bp.get("/login")
def login_page():
    if current_session(get_db(), touch=False):
        return redirect("/admin/")
    return _login_page(nxt=safe_next(request.args.get("next")))


@bp.post("/login")
def login_submit():
    db = get_db()
    username = request.form.get("username", "")[:64]
    password = request.form.get("password", "")[:256]
    nxt = safe_next(request.form.get("next"))
    cookie_tok = request.cookies.get(LOGIN_CSRF_COOKIE, "")
    form_tok = request.form.get("csrf_token", "")
    if not cookie_tok or not hmac.compare_digest(cookie_tok, form_tok):
        return _login_page("انتهت صلاحية الصفحة، حاولي مرة أخرى.", username, nxt, 403)
    wait = locked_seconds(db, username)
    if wait:
        log_event(db, "login_blocked")
        return _login_page(f"محاولات كثيرة خاطئة. حاولي بعد {max(1, wait // 60 + (1 if wait % 60 else 0))} دقيقة.",
                           username, nxt, 429, cookie_tok)
    user = verify_credentials(db, username, password)
    if user is None:
        note_failure(db, username)
        known = db.execute("SELECT username FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
        log_event(db, "login_fail", known["username"] if known else None)
        return _login_page(GENERIC_FAIL, username, nxt, 401, cookie_tok)
    note_success(db, username)
    log_event(db, "login_ok", user["username"])
    resp = start_session(db, user["id"], redirect(nxt))
    resp.delete_cookie(LOGIN_CSRF_COOKIE, path="/admin/login")
    return resp


@bp.post("/logout")
def logout():
    db = get_db()
    sess = current_session(db, touch=False)
    if sess is not None:
        if not _csrf_ok(sess["csrf"]):
            return _deny(403, "رمز CSRF غير صالح.")
        log_event(db, "logout", sess["username"])
    resp = end_session(db, jsonify(ok=True) if request.headers.get("X-CSRF-Token") else redirect("/admin/login"))
    return resp


@bp.get("/session")
def session_info():
    s = g.session
    return jsonify(authenticated=True, username=s["username"], csrf_token=s["csrf"],
                   idle_seconds=current_app.config["SESSION_IDLE_SECONDS"])


@bp.get("/account")
def account_page():
    msg = "تم تغيير كلمة المرور، وأُنهيت جلسات الأجهزة الأخرى." if request.args.get("changed") == "1" else None
    return render_template("account.html", username=g.session["username"], csrf=g.session["csrf"],
                           msg=msg, error=None)


@bp.post("/password")
def change_password():
    db, s = get_db(), g.session
    cur = request.form.get("current_password", "")[:256]
    new = request.form.get("new_password", "")[:256]
    conf = request.form.get("confirm_password", "")[:256]
    page = lambda err=None, msg=None, status=200: (
        render_template("account.html", username=s["username"], csrf=s["csrf"], msg=msg, error=err), status)
    wait = locked_seconds(db, s["username"])
    if wait:
        return page("محاولات كثيرة خاطئة. حاولي لاحقاً.", status=429)
    if verify_credentials(db, s["username"], cur) is None:
        note_failure(db, s["username"])
        log_event(db, "password_change_fail", s["username"])
        return page("كلمة المرور الحالية غير صحيحة.", status=400)
    if new != conf:
        return page("تأكيد كلمة المرور غير مطابق.", status=400)
    if hmac.compare_digest(new, cur):
        return page("كلمة المرور الجديدة يجب أن تختلف عن الحالية.", status=400)
    try:
        set_password(db, s["user_id"], new)
    except ValueError as e:
        return page(str(e), status=400)
    note_success(db, s["username"])
    log_event(db, "password_changed", s["username"])
    # كل الجلسات أُلغيت؛ نبدأ جلسة جديدة لهذه المتصفحة
    resp = start_session(db, s["user_id"], make_response(redirect("/admin/account?changed=1")))
    return resp
