"""واجهة الكتابة للوحة التحكم (الخطوة 4). كل المسارات هنا محمية بـ auth.guard:
جلسة صالحة + رمز CSRF + فحص المصدر، حتى طلبات GET.

  GET  /api/admin/state     كل بيانات اللوحة + رقم المراجعة + آخر العمليات
  PUT  /api/admin/state     حفظ كامل بعد التحقق: {state, rev, msg}
  POST /api/admin/reset     نسخة احتياطية ثم استعادة البيانات الأصلية
  POST /api/admin/upload    رفع صورة (multipart: file, kind=image|logo) ← {src}
  POST /api/admin/backup    نسخة احتياطية فورية من وثيقة site
"""
from flask import Blueprint, g, jsonify, request

from . import store, uploads
from .db import get_db
from .validate import ValidationError, validate_state

bp = Blueprint("admin_api", __name__, url_prefix="/api/admin")


def _err(status, code, message, **extra):
    resp = jsonify(error=code, message=message, **extra)
    resp.status_code = status
    return resp


def _state_response(db):
    return jsonify(state=store.full_state(db), rev=store.get_rev(db))


@bp.get("/state")
def get_state():
    return _state_response(get_db())


def _save(db, raw, msg, *, base_rev, backup_reason=None):
    try:
        clean = validate_state(
            raw,
            content_keys=store.content_keys(db),
            required_slots=store.seed_slots(),
            upload_exists=lambda n: uploads.exists(db, n),
        )
    except ValidationError as e:
        return _err(400, "invalid", str(e), where=e.where)

    if backup_reason:
        store.snapshot_site(db, backup_reason)

    try:
        rev = store.replace_state(db, clean, g.session["username"], msg, base_rev=base_rev)
    except store.ConflictError as e:
        return _err(409, "conflict", str(e), rev=e.rev)

    return jsonify(ok=True, rev=rev, log=store.recent_log(db))


@bp.put("/state")
def put_state():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("state"), dict):
        return _err(400, "invalid", "صيغة الطلب غير صحيحة.")
    rev = body.get("rev")
    if not isinstance(rev, int):
        return _err(400, "invalid", "رقم المراجعة مفقود.")
    msg = str(body.get("msg") or "تعديل البيانات")[:300]
    reason = "import" if body.get("import") else None
    return _save(get_db(), body["state"], msg, base_rev=rev, backup_reason=reason)


@bp.post("/reset")
def reset():
    db = get_db()
    resp = _save(db, store.restore_seed_state(db), "استعادة البيانات الأصلية", base_rev=None, backup_reason="reset")
    if resp.status_code != 200:
        return resp
    return _state_response(db)


@bp.post("/upload")
def upload():
    db = get_db()
    f = request.files.get("file")
    kind = "logo" if request.form.get("kind") == "logo" else "image"
    if f is None:
        return _err(400, "invalid", "لم يتم اختيار ملف.")
    try:
        name, size = uploads.save_image(f.read(uploads.MAX_BYTES + 1), db, kind=kind)
    except uploads.UploadError as e:
        return _err(400, "invalid", str(e))
    return jsonify(ok=True, src=f"uploads/{name}", width=size[0], height=size[1])


@bp.post("/backup")
def backup():
    db = get_db()
    backup_id = store.snapshot_site(db, "manual")
    return jsonify(ok=True, file=str(backup_id))


@bp.errorhandler(413)
def _too_big(_e):
    return _err(413, "too_large", "حجم الملف أكبر من المسموح (4 ميغابايت).")
