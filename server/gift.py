"""بطاقة الإهداء: طلبات الزبائن (عام) وتجهيز البطاقة (لوحة الإدارة).

- المسار العام الوحيد: POST /api/gift-orders (يُحفظ الطلب فقط؛ لا يستطيع الزبون تعديل البطاقة).
- كل مسارات الإدارة تحت /api/admin وتخضع لـ auth.guard (جلسة + CSRF) مثل بقية اللوحة.
- صورة البطاقة الأصلية لا تُعدَّل أبداً: الكتابة فوقها تتمّ في متصفح المديرة وتُحفظ كإحداثيات ونصوص فقط.
"""
import hashlib
import json
import re
import time

from flask import Blueprint, current_app, g, jsonify, request

from .db import get_db

public_bp = Blueprint("gift_public", __name__, url_prefix="/api/gift-orders")
admin_bp = Blueprint("gift_admin", __name__, url_prefix="/api/admin")

STATUSES = ("new", "preparing", "ready", "delivered")
RATE_LIMIT = 5                 # طلبات لكل عنوان IP
RATE_WINDOW = 3600             # خلال ساعة
LIMITS = {"to": 22, "from": 22, "gift": 80, "message": 120, "phone": 20}
ELEMENTS = ("to", "from", "gift", "message", "value")
FONTS = ("IBM Plex Sans Arabic", "El Messiri", "serif")
LAYOUT_BASE_W = 1242           # عرض صورة البطاقة الأصلية؛ أحجام الخط تُحسب نسبةً إلى هذا العرض

# المواضع الافتراضية مستخرجة من صورة البطاقة نفسها (خطوط الكتابة المطبوعة)؛ x,y نسب من عرض/ارتفاع الصورة.
# x هو الحافة اليمنى للنص (اتجاه RTL) وy هو خط الأساس.
DEFAULT_LAYOUT = {
    "to":      {"x": 0.8445, "y": 0.3965, "size": 30, "align": "right", "color": "#1f2a24", "font": "IBM Plex Sans Arabic", "weight": 500, "width": 0.50, "lh": 1.5, "visible": True},
    "from":    {"x": 0.8445, "y": 0.4895, "size": 30, "align": "right", "color": "#1f2a24", "font": "IBM Plex Sans Arabic", "weight": 500, "width": 0.50, "lh": 1.5, "visible": True},
    "gift":    {"x": 0.8180, "y": 0.5820, "size": 28, "align": "right", "color": "#1f2a24", "font": "IBM Plex Sans Arabic", "weight": 500, "width": 0.46, "lh": 1.5, "visible": True},
    "message": {"x": 0.8210, "y": 0.6745, "size": 26, "align": "right", "color": "#1f2a24", "font": "IBM Plex Sans Arabic", "weight": 400, "width": 0.47, "lh": 2.15, "visible": True},
    "value":   {"x": 0.4000, "y": 0.8300, "size": 30, "align": "center", "color": "#064d2a", "font": "El Messiri", "weight": 700, "width": 0.30, "lh": 1.4, "visible": True},
}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f‎‏‪-‮⁦-⁩]")


class GiftError(ValueError):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def _clean(v, field, maxlen, *, required, label, multiline=False):
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise GiftError(f"قيمة «{label}» غير صحيحة.", field)
    v = _CTRL.sub("", v).replace("\r\n", "\n").replace("\r", "\n")
    v = v.strip() if multiline else re.sub(r"\s+", " ", v).strip()
    if required and not v:
        raise GiftError(f"«{label}» مطلوب.", field)
    if len(v) > maxlen:
        raise GiftError(f"«{label}» يجب ألا يزيد عن {maxlen} حرفاً.", field)
    return v


def validate_order(body):
    if not isinstance(body, dict):
        raise GiftError("صيغة الطلب غير صحيحة.")
    out = {
        "to": _clean(body.get("to"), "to", LIMITS["to"], required=True, label="إلى"),
        "from": _clean(body.get("from"), "from", LIMITS["from"], required=True, label="من"),
        "gift": _clean(body.get("gift"), "gift", LIMITS["gift"], required=True, label="الهدية"),
        "message": _clean(body.get("message"), "message", LIMITS["message"], required=False, label="الرسالة", multiline=True),
        "phone": _clean(body.get("phone"), "phone", LIMITS["phone"], required=True, label="رقم الهاتف"),
    }
    digits = re.sub(r"\D", "", out["phone"].translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
    if not re.fullmatch(r"[0-9+\s()\-٠-٩]+", out["phone"]) or not 8 <= len(digits) <= 15:
        raise GiftError("رقم الهاتف غير صالح. اكتبي من 8 إلى 15 رقماً.", "phone")
    out["message"] = out["message"].replace("\n", " ")
    return out


def _num(v, lo, hi, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= v <= hi:
        raise GiftError(f"قيمة «{what}» خارج المسموح.")
    return round(float(v), 5)


def validate_geometry(e):
    """يتحقق من خصائص عنصر واحد (الموضع والحجم واللون...) ويعيد نسخة نظيفة."""
    if not isinstance(e, dict):
        raise GiftError("بيانات العنصر غير صحيحة.")
    if e.get("align") not in ("right", "center", "left"):
        raise GiftError("المحاذاة غير صحيحة.")
    if not isinstance(e.get("color"), str) or not _COLOR.match(e["color"]):
        raise GiftError("اللون غير صحيح.")
    if e.get("font") not in FONTS:
        raise GiftError("الخط غير مسموح.")
    if e.get("weight") not in (400, 500, 600, 700):
        raise GiftError("سُمك الخط غير صحيح.")
    return {"x": _num(e.get("x"), -0.2, 1.2, "الموضع الأفقي"), "y": _num(e.get("y"), -0.2, 1.2, "الموضع الرأسي"),
            "size": _num(e.get("size"), 8, 160, "حجم الخط"), "align": e["align"], "color": e["color"].lower(),
            "font": e["font"], "weight": e["weight"], "width": _num(e.get("width"), 0.05, 1.2, "عرض السطر"),
            "lh": _num(e.get("lh"), 1.0, 3.5, "ارتفاع السطر"), "visible": bool(e.get("visible", True))}


def validate_layout(layout):
    if not isinstance(layout, dict) or set(layout) - set(ELEMENTS):
        raise GiftError("بيانات التخطيط غير صحيحة.")
    return {k: validate_geometry(layout[k]) for k in ELEMENTS if k in layout}


def validate_card(card):
    """card = {el: {text, ...geometry}} لكل عنصر من ELEMENTS."""
    if not isinstance(card, dict) or set(card) - set(ELEMENTS):
        raise GiftError("بيانات البطاقة غير صحيحة.")
    out = {}
    for k, e in card.items():
        if not isinstance(e, dict):
            raise GiftError("بيانات العنصر غير صحيحة.")
        text = _clean(e.get("text"), k, 300, required=False, label="نص البطاقة", multiline=True)
        out[k] = {"text": text, **validate_geometry(e)}
    return out


def get_default_layout(db):
    r = db.execute("SELECT value FROM meta WHERE key='gift_card_layout'").fetchone()
    if r:
        try:
            saved = validate_layout(json.loads(r["value"]))
            return {k: saved.get(k, DEFAULT_LAYOUT[k]) for k in ELEMENTS}
        except (ValueError, GiftError):
            pass
    return {k: dict(v) for k, v in DEFAULT_LAYOUT.items()}


def _texts(row):
    return {"to": row["to_name"], "from": row["from_name"], "gift": row["gift"], "message": row["message"], "value": ""}


def card_for(row, default_layout):
    """بطاقة الطلب: المحفوظة إن وُجدت، وإلا بيانات الزبون فوق التخطيط الافتراضي."""
    if row["card"]:
        try:
            saved = json.loads(row["card"])
            return {k: {"text": saved.get(k, {}).get("text", _texts(row)[k]), **saved.get(k, default_layout[k])} for k in ELEMENTS}
        except ValueError:
            pass
    t = _texts(row)
    return {k: {"text": t[k], **default_layout[k]} for k in ELEMENTS}


def order_dict(row, default_layout=None):
    d = {"id": row["id"], "created_at": int(row["created_at"] * 1000), "updated_at": int(row["updated_at"] * 1000),
         "status": row["status"], "to": row["to_name"], "from": row["from_name"], "gift": row["gift"],
         "message": row["message"], "phone": row["phone"], "prepared": row["prepared_at"] is not None}
    if default_layout is not None:
        d["card"] = card_for(row, default_layout)
        d["saved"] = bool(row["card"])
    return d


def _ip_hash():
    salt = current_app.config.get("SECRET_KEY") or "zumurrud-gift"
    return hashlib.sha256(f"{salt}|{request.remote_addr or '?'}".encode()).hexdigest()


def _err(status, code, message, **extra):
    resp = jsonify(error=code, message=message, **extra)
    resp.status_code = status
    return resp


# ------------------------------------------------------------------ عام
@public_bp.post("")
def create_order():
    body = request.get_json(silent=True)
    if isinstance(body, dict) and body.get("website"):          # فخ للروبوتات: حقل مخفي لا يملؤه إنسان
        return jsonify(ok=True, ref=0), 201
    try:
        d = validate_order(body)
    except GiftError as e:
        return _err(400, "invalid", str(e), field=e.field)
    db = get_db()
    now = time.time()
    iph = _ip_hash()
    recent = db.execute("SELECT COUNT(*) c FROM gift_orders WHERE ip_hash=? AND created_at>?", (iph, now - RATE_WINDOW)).fetchone()["c"]
    if recent >= current_app.config.get("GIFT_RATE_LIMIT", RATE_LIMIT):
        return _err(429, "rate_limited", "أرسلتِ عدة طلبات خلال وقت قصير. حاولي مرة أخرى بعد قليل أو تواصلي معنا مباشرة.")
    cur = db.execute("INSERT INTO gift_orders(created_at,updated_at,status,to_name,from_name,gift,message,phone,ip_hash) "
                     "VALUES(?,?,?,?,?,?,?,?,?)",
                     (now, now, "new", d["to"], d["from"], d["gift"], d["message"], d["phone"], iph))
    db.commit()
    return jsonify(ok=True, ref=cur.lastrowid), 201


# ------------------------------------------------------------------ الإدارة
@admin_bp.get("/gift-orders")
def list_orders():
    db = get_db()
    rows = db.execute("SELECT * FROM gift_orders ORDER BY id DESC LIMIT 500").fetchall()
    counts = {s: 0 for s in STATUSES}
    for r in db.execute("SELECT status, COUNT(*) c FROM gift_orders GROUP BY status"):
        counts[r["status"]] = r["c"]
    return jsonify(orders=[order_dict(r) for r in rows], counts=counts)


def _row(db, oid):
    return db.execute("SELECT * FROM gift_orders WHERE id=?", (oid,)).fetchone()


@admin_bp.get("/gift-orders/<int:oid>")
def get_order(oid):
    db = get_db()
    row = _row(db, oid)
    if row is None:
        return _err(404, "not_found", "الطلب غير موجود.")
    dl = get_default_layout(db)
    return jsonify(order=order_dict(row, dl), default_layout=dl, fonts=list(FONTS), base_width=LAYOUT_BASE_W)


@admin_bp.put("/gift-orders/<int:oid>")
def update_order(oid):
    db = get_db()
    row = _row(db, oid)
    if row is None:
        return _err(404, "not_found", "الطلب غير موجود.")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _err(400, "invalid", "صيغة الطلب غير صحيحة.")
    sets, args = [], []
    if "status" in body:
        if body["status"] not in STATUSES:
            return _err(400, "invalid", "الحالة غير صحيحة.")
        sets.append("status=?")
        args.append(body["status"])
    if "card" in body:
        try:
            card = validate_card(body["card"])
        except GiftError as e:
            return _err(400, "invalid", str(e))
        sets += ["card=?", "prepared_at=?"]
        args += [json.dumps(card, ensure_ascii=False, separators=(",", ":")), time.time()]
        if "status" not in body and row["status"] == "new":
            sets.append("status=?")
            args.append("preparing")
    if not sets:
        return _err(400, "invalid", "لا يوجد ما يُحفظ.")
    sets.append("updated_at=?")
    args += [time.time(), oid]
    db.execute(f"UPDATE gift_orders SET {', '.join(sets)} WHERE id=?", args)
    db.commit()
    dl = get_default_layout(db)
    return jsonify(ok=True, order=order_dict(_row(db, oid), dl))


@admin_bp.put("/gift-card-layout")
def put_layout():
    body = request.get_json(silent=True)
    try:
        layout = validate_layout(body.get("layout") if isinstance(body, dict) else None)
    except GiftError as e:
        return _err(400, "invalid", str(e))
    db = get_db()
    full = {**get_default_layout(db), **layout}
    db.execute("INSERT INTO meta(key,value) VALUES('gift_card_layout',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (json.dumps(full, ensure_ascii=False, separators=(",", ":")),))
    db.commit()
    return jsonify(ok=True, layout=full)
