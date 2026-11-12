"""الكتابة في قاعدة البيانات (MongoDB): حفظ كامل لبيانات اللوحة داخل وثيقة site.

- رقم مراجعة (rev) بتقنية Compare-And-Set (CAS) لمنع تداخل التعديلات (تعارض 409).
- سجل عمليات (audit_log) بالنص واسم المستخدمة ورقم المراجعة.
- نسخ احتياطية داخلية لوثيقة site في مجموعة site_backups قبل الاستيراد والاستعادة أو يدوياً.
"""
import time

from . import queries
from .seed_loader import read_seed, snapshot

LOG_KEEP = 500


class ConflictError(Exception):
    def __init__(self, message, rev):
        super().__init__(message)
        self.rev = rev


def get_rev(db):
    doc = db.site.find_one({"_id": "site"}, {"rev": 1})
    return int(doc.get("rev", 0)) if doc else 0


def content_keys(db):
    doc = db.site.find_one({"_id": "site"}, {"content": 1, "contentFields": 1})
    if not doc:
        return []
    if "contentFields" in doc:
        return [f["key"] for f in doc["contentFields"]]
    return list(doc.get("content", {}).keys())


def seed_slots():
    return list(read_seed()["images"].keys())


def recent_log(db, n=30):
    docs = list(db.audit_log.find().sort([("_id", -1)]).limit(n))
    return [
        {"t": int(r["ts"] * 1000), "m": r["msg"], "u": r["username"]}
        for r in docs
    ]


def full_state(db):
    s = snapshot(db)
    s.pop("contentFields", None)
    s["version"] = 1
    s["log"] = recent_log(db)
    return s


def replace_state(db, d, username, msg, base_rev=None):
    """يستبدل بيانات وثيقة site بالكامل بالبيانات المتحقق منها باستخدام Compare-and-Set."""
    curr = db.site.find_one({"_id": "site"}) or {}
    current_rev = curr.get("rev", 0)

    if base_rev is not None and base_rev != current_rev:
        raise ConflictError(
            "تم تعديل البيانات من جهاز أو نافذة أخرى. أُعيد تحميل أحدث نسخة؛ أعيدي تطبيق تعديلكِ.",
            current_rev,
        )

    old_imgs = curr.get("images", {})
    new_imgs = {}
    for slot, im in d["images"].items():
        original_src = old_imgs.get(slot, {}).get("original_src", im["src"])
        new_imgs[slot] = {
            "label": im["label"],
            "group": im["group"],
            "src": im["src"],
            "original_src": original_src,
        }

    update_doc = {
        "content": d["content"],
        "contact": d["contact"],
        "services": d["services"],
        "priceCats": d["priceCats"],
        "products": d["products"],
        "images": new_imgs,
        "gallery": d["gallery"],
        "updated_at": time.time(),
    }

    # ذرّي: CAS
    res = db.site.update_one(
        {"_id": "site", "rev": current_rev},
        {"$set": update_doc, "$inc": {"rev": 1}},
    )
    if res.matched_count == 0:
        latest = get_rev(db)
        raise ConflictError(
            "تم تعديل البيانات من جهاز أو نافذة أخرى. أُعيد تحميل أحدث نسخة؛ أعيدي تطبيق تعديلكِ.",
            latest,
        )

    new_rev = current_rev + 1
    db.audit_log.insert_one({
        "ts": time.time(),
        "username": username,
        "msg": msg[:300],
        "rev": new_rev,
    })

    # إبقاء آخر 500 عملية
    cutoff = list(db.audit_log.find({}, {"rev": 1}).sort([("rev", -1)]).skip(LOG_KEEP).limit(1))
    if cutoff:
        db.audit_log.delete_many({"rev": {"$lte": cutoff[0]["rev"]}})

    return new_rev


def restore_seed_state(_db):
    """البيانات الأصلية المستخرجة من الموقع (seed.js) بصيغة اللوحة."""
    s = read_seed()
    return {k: s[k] for k in ("content", "contact", "services", "priceCats", "products", "images", "gallery")}


def snapshot_site(db, reason="manual", keep=20):
    """نسخة احتياطية لوثيقة site في مجموعة site_backups تُبقي آخر keep نسخة."""
    doc = db.site.find_one({"_id": "site"})
    if not doc:
        return None
    doc_copy = dict(doc)
    doc_copy.pop("_id", None)
    res = db.site_backups.insert_one({
        "reason": reason,
        "at": time.time(),
        "doc": doc_copy,
    })
    # إبقاء آخر keep نسخة
    old_backups = list(db.site_backups.find({}, {"_id": 1}).sort([("at", -1)]).skip(keep))
    if old_backups:
        db.site_backups.delete_many({"_id": {"$in": [b["_id"] for b in old_backups]}})
    return str(res.inserted_id)


def referenced_uploads(db):
    doc = db.site.find_one({"_id": "site"}, {"images": 1})
    if not doc:
        return set()
    imgs = doc.get("images", {})
    return {
        im["src"][len("uploads/"):]
        for im in imgs.values()
        if isinstance(im, dict) and im.get("src", "").startswith("uploads/")
    }


__all__ = [
    "ConflictError",
    "get_rev",
    "content_keys",
    "seed_slots",
    "full_state",
    "replace_state",
    "restore_seed_state",
    "snapshot_site",
    "recent_log",
    "referenced_uploads",
    "queries",
]
