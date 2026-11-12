"""المصادقة وحماية لوحة الإدارة (MongoDB Atlas).

- كلمات المرور: تجزئة scrypt (Werkzeug) بملح عشوائي؛ لا تُخزَّن ولا تُسجَّل كنص.
- الجلسات: في MongoDB مع انتهاء الصلاحية بالخمول أو الحد الأقصى. الكوكي يحمل رمزاً عشوائياً فقط، ويُخزَّن SHA-256 له.
- CSRF: رمز لكل جلسة (ترويسة X-CSRF-Token أو حقل نموذج) + فحص Origin/Referer.
- الحماية افتراضياً-مغلقة: كل مسار تحت /admin وكل طلب كتابة تحت /api يتطلب جلسة ورمز CSRF،
  عدا مسارات الدخول/الخروج والإعداد المذكورة صراحةً في PUBLIC_ENDPOINTS.
- إنشاء الحساب الأول للمديرة: عبر صفحة /admin/setup المحمية برمز SETUP_TOKEN.
"""
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

from bson import ObjectId
from flask import (Blueprint, current_app, g, has_app_context, has_request_context, jsonify, make_response, redirect,
                   render_template, request)
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

bp = Blueprint("auth", __name__, url_prefix="/admin")

COOKIE = "zum_sid"
LOGIN_CSRF_COOKIE = "zum_login_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_ENDPOINTS = {
    "auth.login_page",
    "auth.login_submit",
    "auth.logout",
    "auth.setup_page",
    "auth.setup_submit",
    "gift_public.create_order",
}
GENERIC_FAIL = "اسم المستخدم أو كلمة المرور غير صحيحة."
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
_COMMON = {
    "password", "password1", "123456789012", "qwertyuiopas", "zumurrud", "zumurrud1234",
    "administrator", "adminadmin12", "letmein12345", "iloveyou1234",
}
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


def admin_exists(db):
    return (
        db.users.count_documents({}, limit=1) > 0
        or db.meta.count_documents({"_id": "admin_lock"}, limit=1) > 0
    )


def setup_enabled():
    if has_app_context():
        tok = current_app.config.get("SETUP_TOKEN") or ""
    else:
        from .config import Config
        tok = Config.SETUP_TOKEN or ""
    return len(tok) >= 24


def create_admin(db, username, password):
    """ينشئ حساب المديرة الأول بشكل ذرّي وآمن ضد السباق. يرفع ValueError برسالة عربية."""
    name, err = validate_username(username)
    if err:
        raise ValueError(err)
    err = validate_password(password, name)
    if err:
        raise ValueError(err)
    if admin_exists(db):
        raise ValueError("يوجد حساب مدير بالفعل. استخدمي change-password لتغيير كلمة المرور.")

    t = now()
    try:
        db.meta.insert_one({"_id": "admin_lock", "at": t})
    except DuplicateKeyError:
        raise ValueError("يوجد حساب مدير بالفعل.")

    db.users.insert_one({
        "username": name,
        "password_hash": generate_password_hash(password),
        "created_at": t,
        "updated_at": t,
    })
    return name


def set_password(db, user_id, new_password):
    """يغيّر كلمة المرور ويُلغي كل جلسات هذا المستخدم."""
    try:
        oid = ObjectId(user_id) if isinstance(user_id, str) else user_id
    except Exception:
        oid = user_id
    u = db.users.find_one({"_id": oid})
    if not u:
        raise ValueError("المستخدم غير موجود.")
    err = validate_password(new_password, u["username"])
    if err:
        raise ValueError(err)
    t = now()
    db.users.update_one(
        {"_id": oid},
        {"$set": {"password_hash": generate_password_hash(new_password), "updated_at": t}},
    )
    db.sessions.delete_many({"user_id": str(oid)})


def verify_credentials(db, username, password):
    n = (username or "").strip().lower()
    row = db.users.find_one({"username": n})
    ok = check_password_hash(row["password_hash"] if row else _DUMMY_HASH, password or "")
    if row and ok:
        row["id"] = str(row["_id"])
        return row
    return None


# ------------------------------------------------------------------ تقييد المحاولات
def _client_ip():
    if has_request_context():
        return request.remote_addr or "?"
    return "?"


def _lock_remaining(db, key):
    r = db.login_attempts.find_one({"key": key})
    return max(0, int(r["locked_until"] - now())) if (r and "locked_until" in r) else 0


def _register_fail(db, key, limit):
    cfg, t = current_app.config, now()
    r = db.login_attempts.find_one({"key": key})
    if r is None or t - r.get("first_fail", 0) > cfg["LOGIN_WINDOW_SECONDS"] or (0 < r.get("locked_until", 0) <= t):
        fails, first = 1, t
    else:
        fails, first = r.get("fails", 0) + 1, r.get("first_fail", t)
    locked = t + cfg["LOGIN_LOCK_SECONDS"] if fails >= limit else 0
    expires_dt = datetime.fromtimestamp(t + cfg["LOGIN_WINDOW_SECONDS"] + 3600, tz=timezone.utc)
    db.login_attempts.find_one_and_update(
        {"key": key},
        {"$set": {
            "fails": fails,
            "first_fail": first,
            "locked_until": locked,
            "expires_dt": expires_dt,
        }},
        upsert=True,
    )


def _keys(username):
    ip = _client_ip()
    return (f"ip:{ip}", f"pair:{(username or '').strip().lower()[:64]}|{ip}")


def locked_seconds(db, username):
    return max(_lock_remaining(db, k) for k in _keys(username))


def note_failure(db, username):
    k_ip, k_pair = _keys(username)
    cfg = current_app.config
    _register_fail(db, k_ip, cfg["LOGIN_MAX_FAILS_IP"])
    _register_fail(db, k_pair, cfg["LOGIN_MAX_FAILS"])


def note_success(db, username):
    db.login_attempts.delete_one({"key": _keys(username)[1]})


def log_event(db, event, username=None):
    t = now()
    db.auth_events.insert_one({
        "ts": t,
        "ts_dt": datetime.fromtimestamp(t, tz=timezone.utc),
        "event": event,
        "username": username,
        "ip": _client_ip(),
    })


# ------------------------------------------------------------------ الجلسات
def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _set_cookie(resp, name, value, path="/", max_age=None):
    resp.set_cookie(
        name,
        value,
        httponly=True,
        secure=current_app.config["COOKIE_SECURE"],
        samesite="Lax",
        path=path,
        max_age=max_age,
    )


def start_session(db, user_id, resp):
    cfg, t = current_app.config, now()
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    t_dt = datetime.fromtimestamp(t, tz=timezone.utc)
    db.sessions.delete_many({
        "$or": [
            {"created_at": {"$lt": t - cfg["SESSION_MAX_SECONDS"]}},
            {"last_seen": {"$lt": t - cfg["SESSION_IDLE_SECONDS"]}},
        ]
    })
    db.sessions.insert_one({
        "token_hash": _hash(token),
        "user_id": str(user_id),
        "csrf": csrf,
        "created_at": t,
        "last_seen": t,
        "created_dt": t_dt,
        "last_seen_dt": t_dt,
        "ip": _client_ip(),
    })
    _set_cookie(resp, COOKIE, token)
    return resp


def end_session(db, resp):
    token = request.cookies.get(COOKIE)
    if token:
        db.sessions.delete_many({"token_hash": _hash(token)})
    resp.delete_cookie(COOKIE, path="/", secure=current_app.config["COOKIE_SECURE"],
                       httponly=True, samesite="Lax")
    return resp


def current_session(db, touch=True):
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 200:
        return None
    th, cfg, t = _hash(token), current_app.config, now()
    row = db.sessions.find_one({"token_hash": th})
    if row is None:
        return None
    if t - row["created_at"] > cfg["SESSION_MAX_SECONDS"] or t - row["last_seen"] > cfg["SESSION_IDLE_SECONDS"]:
        db.sessions.delete_many({"token_hash": th})
        return None
    if touch:
        t_dt = datetime.fromtimestamp(t, tz=timezone.utc)
        db.sessions.update_one(
            {"token_hash": th},
            {"$set": {"last_seen": t, "last_seen_dt": t_dt}},
        )
    try:
        oid = ObjectId(row["user_id"])
    except Exception:
        oid = row["user_id"]
    user = db.users.find_one({"_id": oid})
    if not user:
        return None
    return {
        "id": str(row["_id"]),
        "user_id": str(row["user_id"]),
        "username": user["username"],
        "csrf": row["csrf"],
        "created_at": row["created_at"],
        "last_seen": row["last_seen"],
        "ip": row.get("ip", ""),
    }


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
    db = get_db()
    resp = make_response(render_template(
        "login.html",
        error=error,
        username=username,
        next=nxt,
        csrf=token,
        has_admin=admin_exists(db),
        setup_enabled=setup_enabled(),
    ), status)
    _set_cookie(resp, LOGIN_CSRF_COOKIE, token, path="/admin/login")
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
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
        known = db.users.find_one({"username": username.strip().lower()})
        log_event(db, "login_fail", known["username"] if known else None)
        return _login_page(GENERIC_FAIL, username, nxt, 401, cookie_tok)
    note_success(db, username)
    log_event(db, "login_ok", user["username"])
    resp = start_session(db, str(user["_id"]), redirect(nxt))
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


# ------------------------------------------------------------------ الإعداد الأولي (/admin/setup)
@bp.get("/setup")
def setup_page():
    db = get_db()
    if admin_exists(db) or not setup_enabled():
        return "404 Not Found", 404
    token = request.cookies.get(LOGIN_CSRF_COOKIE) or secrets.token_urlsafe(24)
    resp = make_response(render_template("setup.html", error=None, username="", csrf=token), 200)
    _set_cookie(resp, LOGIN_CSRF_COOKIE, token, path="/admin/setup")
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    return resp


@bp.post("/setup")
def setup_submit():
    db = get_db()
    if admin_exists(db) or not setup_enabled():
        return "404 Not Found", 404

    ip = _client_ip()
    key_setup = f"setup:{ip}"
    rem = _lock_remaining(db, key_setup)
    if rem > 0:
        log_event(db, "setup_blocked")
        return make_response(
            render_template(
                "setup.html",
                error=f"محاولات كثيرة خاطئة. حاولي بعد {max(1, rem // 60 + (1 if rem % 60 else 0))} دقيقة.",
                username=request.form.get("username", "")[:32],
                csrf=request.cookies.get(LOGIN_CSRF_COOKIE, ""),
            ),
            429,
        )

    # التحقق من CSRF
    cookie_tok = request.cookies.get(LOGIN_CSRF_COOKIE, "")
    form_tok = request.form.get("csrf_token", "")
    if not cookie_tok or not hmac.compare_digest(cookie_tok, form_tok):
        return make_response(
            render_template(
                "setup.html",
                error="انتهت صلاحية الصفحة، حاولي مرة أخرى.",
                username=request.form.get("username", "")[:32],
                csrf=cookie_tok,
            ),
            403,
        )

    # التحقق من رمز الإعداد
    sent_token = request.form.get("setup_token", "")
    expected_token = current_app.config.get("SETUP_TOKEN") or ""
    if not hmac.compare_digest(sent_token, expected_token):
        _register_fail(db, key_setup, 5)
        log_event(db, "setup_fail")
        return make_response(
            render_template(
                "setup.html",
                error="رمز الإعداد غير صحيح.",
                username=request.form.get("username", "")[:32],
                csrf=cookie_tok,
            ),
            401,
        )

    username = request.form.get("username", "")[:32]
    password = request.form.get("password", "")[:128]
    confirm = request.form.get("confirm", "")[:128]

    if password != confirm:
        return make_response(
            render_template(
                "setup.html",
                error="تأكيد كلمة المرور غير مطابق.",
                username=username,
                csrf=cookie_tok,
            ),
            400,
        )

    try:
        create_admin(db, username, password)
    except ValueError as e:
        return make_response(
            render_template(
                "setup.html",
                error=str(e),
                username=username,
                csrf=cookie_tok,
            ),
            400,
        )

    log_event(db, "admin_created", username)
    db.login_attempts.delete_one({"key": key_setup})
    resp = redirect("/admin/login")
    resp.delete_cookie(LOGIN_CSRF_COOKIE, path="/admin/setup")
    return resp


@bp.get("/session")
def session_info():
    s = g.session
    return jsonify(
        authenticated=True,
        username=s["username"],
        csrf_token=s["csrf"],
        idle_seconds=current_app.config["SESSION_IDLE_SECONDS"],
    )


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
    resp = start_session(db, s["user_id"], make_response(redirect("/admin/account?changed=1")))
    return resp
