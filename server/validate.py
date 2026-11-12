"""التحقق من بيانات لوحة التحكم قبل حفظها في القاعدة (الخطوة 4).

القواعد نفسها التي تطبّقها اللوحة في المتصفح، مكرّرة على الخادم لأن المتصفح لا يُوثق به.
لا تُعدَّل أي قيمة هنا سوى إزالة المسافات الطرفية؛ الأسعار تُحفظ نصاً كما أُدخلت.
"""
import re

PRICE_RE = re.compile(r"^\s*[\d٠-٩]+(\s*[–\-—]\s*[\d٠-٩]+)?\s*$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
SLOT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SRC_RE = re.compile(r"^(images|uploads)/[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
URL_RE = re.compile(r"^https://[^\s<>\"']+\.[^\s<>\"']+$", re.I)
WA_RE = re.compile(r"^\d{8,15}$")
IMG_GROUPS = {"identity", "sections", "products", "gallery"}


class ValidationError(ValueError):
    def __init__(self, message, where=""):
        super().__init__(message)
        self.where = where


def _fail(msg, where=""):
    raise ValidationError(msg, where)


def _s(v, where, *, required=False, max_len=200):
    if v is None:
        v = ""
    if not isinstance(v, str):
        _fail("قيمة نصية غير صالحة.", where)
    v = v.strip()
    if required and not v:
        _fail("حقل مطلوب فارغ.", where)
    if len(v) > max_len:
        _fail(f"النص أطول من الحد المسموح ({max_len} حرفاً).", where)
    if "\x00" in v:
        _fail("النص يحتوي رموزاً غير مسموحة.", where)
    return v


def _price(v, where, required):
    v = _s(v, where, required=required, max_len=40)
    if v and not PRICE_RE.match(v):
        _fail("السعر يجب أن يكون رقماً أو نطاقاً مثل 50–100.", where)
    return v


def _id(v, where, seen):
    if not isinstance(v, str) or not ID_RE.match(v):
        _fail("معرّف غير صالح.", where)
    if v in seen:
        _fail("معرّف مكرر.", where)
    seen.add(v)
    return v


def _list(v, where, max_n):
    if not isinstance(v, list):
        _fail("قائمة غير صالحة.", where)
    if len(v) > max_n:
        _fail(f"عدد العناصر أكبر من المسموح ({max_n}).", where)
    return v


def _dict(v, where):
    if not isinstance(v, dict):
        _fail("بيانات غير صالحة.", where)
    return v


def validate_state(d, *, content_keys, required_slots, upload_exists):
    """يعيد نسخة نظيفة من البيانات أو يرفع ValidationError برسالة عربية."""
    _dict(d, "state")

    # ---- النصوص: المفاتيح ثابتة (49 حقلاً) ولا تُضاف ولا تُحذف
    content = _dict(d.get("content"), "content")
    if set(content) != set(content_keys):
        _fail("حقول النصوص لا تطابق حقول الموقع.", "content")
    out_content = {k: _s(content[k], f"content.{k}", required=True, max_len=2000) for k in content_keys}

    # ---- التواصل
    contact = _dict(d.get("contact"), "contact")
    if set(contact) != {"facebook", "whatsapp", "map"}:
        _fail("بيانات التواصل غير مكتملة.", "contact")
    fb = _s(contact["facebook"], "contact.facebook", max_len=500)
    wa = _s(contact["whatsapp"], "contact.whatsapp", max_len=20)
    mp = _s(contact["map"], "contact.map", max_len=1000)
    if fb and not URL_RE.match(fb):
        _fail("رابط فيسبوك غير صالح. يجب أن يبدأ بـ https://", "contact.facebook")
    if mp and not URL_RE.match(mp):
        _fail("رابط الخريطة غير صالح. يجب أن يبدأ بـ https://", "contact.map")
    if wa and not WA_RE.match(wa):
        _fail("رقم واتساب غير صالح: أرقام فقط بصيغة دولية (8 إلى 15 رقماً).", "contact.whatsapp")

    # ---- الصور
    images = _dict(d.get("images"), "images")
    if len(images) > 400:
        _fail("عدد الصور أكبر من المسموح.", "images")
    missing = [s for s in required_slots if s not in images]
    if missing:
        _fail("لا يمكن حذف صور الموقع الأساسية: " + "، ".join(missing), "images")
    out_images = {}
    for slot, im in images.items():
        w = f"images.{slot}"
        if not SLOT_RE.match(slot):
            _fail("اسم موضع صورة غير صالح.", w)
        _dict(im, w)
        grp = im.get("group")
        if grp not in IMG_GROUPS:
            _fail("تصنيف صورة غير صالح.", w)
        src = _s(im.get("src"), w + ".src", max_len=140)
        if src:
            if not SRC_RE.match(src) or ".." in src:
                _fail("مسار صورة غير مسموح. ارفعي الصورة من اللوحة.", w)
            if src.startswith("uploads/") and not upload_exists(src[len("uploads/"):]):
                _fail("ملف الصورة المرفوعة غير موجود على الخادم.", w)
        out_images[slot] = {"label": _s(im.get("label"), w + ".label", required=True, max_len=200),
                            "group": grp, "src": src}

    def slot_ok(slot, where):
        if not isinstance(slot, str) or slot not in out_images:
            _fail("الصورة المرتبطة غير موجودة.", where)
        return slot

    # ---- الخدمات
    seen = set()
    out_services = []
    for i, s in enumerate(_list(d.get("services"), "services", 100)):
        w = f"services[{i}]"
        _dict(s, w)
        if s.get("group") not in ("beauty", "other"):
            _fail("تصنيف خدمة غير صالح.", w)
        out_services.append({
            "id": _id(s.get("id"), w, seen),
            "name": _s(s.get("name"), w + ".name", required=True, max_len=120),
            "en": _s(s.get("en"), w + ".en", max_len=120),
            "desc": _s(s.get("desc"), w + ".desc", required=True, max_len=1000),
            "group": s["group"],
            "slot": slot_ok(s.get("slot"), w + ".slot"),
            "price": _price(s.get("price"), w + ".price", False),
        })

    # ---- الأسعار
    seen = set()
    out_cats = []
    for ci, c in enumerate(_list(d.get("priceCats"), "priceCats", 50)):
        w = f"priceCats[{ci}]"
        _dict(c, w)
        cat = {"id": _id(c.get("id"), w, seen), "t": _s(c.get("t"), w + ".t", required=True, max_len=120)}
        note = _s(c.get("note"), w + ".note", max_len=500)
        if note:
            cat["note"] = note
        cat["groups"] = []
        pk_count = 0
        for gi, g in enumerate(_list(c.get("groups"), w + ".groups", 40)):
            wg = f"{w}.groups[{gi}]"
            _dict(g, wg)
            is_pk = bool(g.get("pk"))
            grp = {}
            if is_pk:
                pk_count += 1
                grp["pk"] = 1
            else:
                grp["g"] = _s(g.get("g"), wg + ".g", required=True, max_len=120)
            grp["items"] = []
            for ii, it in enumerate(_list(g.get("items"), wg + ".items", 100)):
                wi = f"{wg}.items[{ii}]"
                _dict(it, wi)
                item = {"n": _s(it.get("n"), wi + ".n", required=True, max_len=200),
                        "p": _price(it.get("p"), wi + ".p", True)}
                if is_pk:
                    inc = it.get("inc", [])
                    _list(inc, wi + ".inc", 30)
                    item["inc"] = [_s(x, wi + ".inc", required=True, max_len=300) for x in inc]
                    if it.get("star"):
                        item["star"] = 1
                else:
                    dd = _s(it.get("d"), wi + ".d", max_len=300)
                    if dd:
                        item["d"] = dd
                grp["items"].append(item)
            cat["groups"].append(grp)
        if pk_count > 1:
            _fail("القسم يحتوي أكثر من مجموعة باقات.", w)
        out_cats.append(cat)

    # ---- المنتجات
    seen = set()
    out_products = []
    for i, p in enumerate(_list(d.get("products"), "products", 200)):
        w = f"products[{i}]"
        _dict(p, w)
        out_products.append({
            "id": _id(p.get("id"), w, seen),
            "name": _s(p.get("name"), w + ".name", required=True, max_len=200),
            "desc": _s(p.get("desc"), w + ".desc", max_len=1000),
            "price": _price(p.get("price"), w + ".price", False),
            "slot": slot_ok(p.get("slot"), w + ".slot"),
        })

    # ---- المعرض
    seen = set()
    out_gallery = []
    for i, g in enumerate(_list(d.get("gallery"), "gallery", 200)):
        w = f"gallery[{i}]"
        _dict(g, w)
        if g.get("cat") not in ("beauty", "gym"):
            _fail("تصنيف عنصر المعرض غير صالح.", w)
        out_gallery.append({"id": _id(g.get("id"), w, seen), "slot": slot_ok(g.get("slot"), w + ".slot"),
                            "cat": g["cat"], "cap": _s(g.get("cap"), w + ".cap", required=True, max_len=200)})

    return {"content": out_content, "contact": {"facebook": fb, "whatsapp": wa, "map": mp},
            "services": out_services, "priceCats": out_cats, "products": out_products,
            "images": out_images, "gallery": out_gallery}
