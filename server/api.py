"""واجهة القراءة (GET فقط) لبيانات الموقع. لا كتابة ولا تسجيل دخول في هذه الخطوة.

كل استجابة JSON بترتيب البيانات الأصلي نفسه، وبصيغة:
  { "<الاسم>": <البيانات>, "count": <العدد إن كانت قائمة> }
"""
from flask import Blueprint, jsonify

from . import queries
from .db import get_db

bp = Blueprint("api", __name__, url_prefix="/api")


def _ok(name, data, count=None):
    body = {name: data}
    if count is not None:
        body["count"] = count
    return jsonify(body)


def _list(name, data):
    return _ok(name, data, len(data))


def _one(name, data, what):
    if data is None:
        return jsonify(error="not_found", message=f"{what} غير موجود"), 404
    return _ok(name, data)


@bp.get("/services")
def services():
    return _list("services", queries.services(get_db()))


@bp.get("/services/<sid>")
def service(sid):
    return _one("service", queries.service(get_db(), sid), "الخدمة")


@bp.get("/prices")
def prices():
    cats = queries.price_cats(get_db())
    body = {"prices": cats, "count": len(cats),
            "items_count": sum(len(g["items"]) for c in cats for g in c["groups"])}
    return jsonify(body)


@bp.get("/prices/<cid>")
def price_cat(cid):
    return _one("category", queries.price_cat(get_db(), cid), "قسم الأسعار")


@bp.get("/products")
def products():
    return _list("products", queries.products(get_db()))


@bp.get("/products/<pid>")
def product(pid):
    return _one("product", queries.product(get_db(), pid), "المنتج")


@bp.get("/content")
def content():
    db = get_db()
    data = queries.content(db)
    return jsonify(content=data, fields=queries.content_fields(db), count=len(data))


@bp.get("/contact")
def contact():
    return _ok("contact", queries.contact(get_db()))


@bp.get("/images")
def images():
    data = queries.images(get_db())
    return _ok("images", data, len(data))


@bp.get("/gallery")
def gallery():
    return _list("gallery", queries.gallery(get_db()))


@bp.get("/site")
def site():
    """كل بيانات الموقع في استجابة واحدة (للربط في الخطوات اللاحقة)."""
    db = get_db()
    return jsonify(
        content=queries.content(db),
        contact=queries.contact(db),
        services=queries.services(db),
        prices=queries.price_cats(db),
        products=queries.products(db),
        images=queries.images(db),
        gallery=queries.gallery(db),
    )


@bp.get("/health")
def health():
    from .seed_loader import counts, is_seeded
    db = get_db()
    return jsonify(status="ok", seeded=is_seeded(db), counts=counts(db))


@bp.errorhandler(404)
def _nf(_e):
    return jsonify(error="not_found", message="المسار غير موجود"), 404
