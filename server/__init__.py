"""الزُمردة – خادم Flask.

- الموقع العام: يُولَّد من index.html الأصلي مع بيانات القاعدة (الخطوة 6).
- لوحة التحكم: ملفات ثابتة خلف تسجيل الدخول (الخطوة 3)، وتحفظ عبر /api/admin (الخطوتان 4 و5).
- واجهة قراءة عامة GET على /api (الخطوة 2).
"""
from flask import Flask, jsonify, make_response, redirect, request, send_from_directory

from .config import Config
from .db import close_db


def create_app(overrides=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    root = app.config["ROOT"]

    app.secret_key = app.config["SECRET_KEY"]
    app.teardown_appcontext(close_db)
    from .render import Template
    from .seed_loader import read_seed
    Template(root / "index.html", read_seed())           # يفشل الإقلاع برسالة واضحة إن تغيّر index.html بشكل يمنع الربط

    # ---- الملفات الثابتة (قائمة بيضاء؛ لا يُكشف server/ ولا data/ ولا backup-phase1/) ----
    @app.get("/")
    @app.get("/index.html")
    def public_index():
        from .db import get_db
        from .render import render_cached
        from .store import get_rev
        db = get_db()
        db_id = f"{app.config['MONGODB_DB']}:{id(db)}"
        page = render_cached(root / "index.html", db, get_rev(db), db_id)
        resp = make_response(page)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        resp.headers["Cache-Control"] = "no-cache"          # تظهر تعديلات اللوحة فوراً
        return resp

    @app.get("/images/<path:name>")
    def public_images(name):
        return send_from_directory(root / "images", name, max_age=86400)

    @app.get("/uploads/<path:name>")
    def public_uploads(name):
        from . import uploads
        if not name or name.startswith(".") or "/" in name or any(c not in uploads.NAME_OK for c in name):
            return "404 Not Found", 404
        from .db import get_db
        db = get_db()
        doc = db.uploads.find_one({"_id": name})
        if not doc or "data" not in doc:
            return "404 Not Found", 404
        resp = make_response(bytes(doc["data"]))
        resp.headers["Content-Type"] = doc.get("content_type", "image/jpeg")
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        resp.headers["ETag"] = name
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.get("/robots.txt")
    def robots():
        resp = make_response("User-agent: *\nDisallow: /admin/\nDisallow: /api/\n")
        resp.headers["Content-Type"] = "text/plain; charset=utf-8"
        return resp

    @app.get("/admin")
    def admin_redirect():
        return redirect("/admin/", code=301)

    @app.get("/admin/")
    def admin_index():
        return send_from_directory(root / "admin", "index.html")

    @app.get("/admin/<path:name>")
    def admin_files(name):
        return send_from_directory(root / "admin", name)

    # ---- المصادقة وحماية الإدارة (القفل الافتراضي لكل /admin وكل كتابة على /api) ----
    from . import auth
    app.register_blueprint(auth.bp)
    app.before_request(auth.guard)
    app.after_request(auth.add_security_headers)
    if app.config["PROXY_HOPS"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=app.config["PROXY_HOPS"], x_proto=app.config["PROXY_HOPS"],
                                x_host=app.config["PROXY_HOPS"])

    # ---- واجهة القراءة ----
    from .api import bp
    app.register_blueprint(bp)
    from .admin_api import bp as admin_bp
    app.register_blueprint(admin_bp)
    from . import gift                                   # بطاقة الإهداء: طلب عام + تجهيز من اللوحة
    app.register_blueprint(gift.public_bp)
    app.register_blueprint(gift.admin_bp)
    app.json.sort_keys = False          # الحفاظ على ترتيب المفاتيح كما في البيانات الأصلية
    app.json.ensure_ascii = False       # عربي مقروء بدل \uXXXX

    def _is_api():
        return request.path == "/api" or request.path.startswith("/api/")

    @app.errorhandler(404)
    def _not_found(_e):
        return jsonify(
            path=request.path,
            path_info=request.environ.get("PATH_INFO"),
            script_name=request.environ.get("SCRIPT_NAME"),
            x_matched_path=request.headers.get("x-matched-path"),
            x_vercel_path=request.headers.get("x-vercel-path"),
            x_forwarded_uri=request.headers.get("x-forwarded-uri"),
            x_invoke_path=request.headers.get("x-invoke-path"),
            headers=dict(request.headers),
        ), 404

    @app.errorhandler(413)
    def _too_large(_e):
        if _is_api():
            return jsonify(error="too_large", message="حجم الملف أكبر من المسموح (4 ميغابايت)."), 413
        return "413 Payload Too Large", 413

    @app.errorhandler(405)
    def _bad_method(_e):
        if _is_api():
            return jsonify(error="method_not_allowed", message="هذه الواجهة للقراءة فقط"), 405
        return "405 Method Not Allowed", 405

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if _is_api():
            resp.headers["Cache-Control"] = "no-store"
        return resp

    return app
