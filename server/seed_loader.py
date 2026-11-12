"""استيراد البيانات الأولية من admin/seed.js إلى MongoDB، وتصدير لقطة للمقارنة.

لا يغيّر أي قيمة: الأسعار والنصوص تُنقل كما هي حرفياً.
"""
import json
import time
from pathlib import Path

from . import queries
from .config import SEED_PATH


def read_seed(path=SEED_PATH):
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def is_seeded(db):
    return db.site.find_one({"_id": "site"}) is not None


def seed(db, data=None):
    """يملأ وثيقة site في حال عدم وجودها. لا يلمس قاعدة سبق استيرادها (idempotent)."""
    d = data or read_seed()
    doc = {
        "_id": "site",
        "rev": 0,
        "schema": 1,
        "contentFields": d["contentFields"],
        "content": d["content"],
        "contact": d["contact"],
        "services": d["services"],
        "priceCats": d["priceCats"],
        "products": d["products"],
        "images": {
            slot: {
                "label": im["label"],
                "group": im["group"],
                "src": im["src"],
                "original_src": im["src"],
            }
            for slot, im in d["images"].items()
        },
        "gallery": d["gallery"],
        "seeded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    res = db.site.update_one({"_id": "site"}, {"$setOnInsert": doc}, upsert=True)
    return res.upserted_id is not None


def snapshot(db):
    """يعيد بناء بنية البيانات الأولية من قاعدة البيانات (للمقارنة والتحقق)."""
    return {
        "content": queries.content(db),
        "contentFields": queries.content_fields(db),
        "contact": queries.contact(db),
        "services": queries.services(db),
        "priceCats": queries.price_cats(db),
        "products": queries.products(db),
        "images": queries.images(db),
        "gallery": queries.gallery(db),
    }


def counts(db):
    doc = db.site.find_one({"_id": "site"}) or {}
    price_items_count = sum(
        len(g.get("items", []))
        for c in doc.get("priceCats", [])
        for g in c.get("groups", [])
    )
    return {
        "services": len(doc.get("services", [])),
        "price_categories": len(doc.get("priceCats", [])),
        "price_items": price_items_count,
        "products": len(doc.get("products", [])),
        "texts": len(doc.get("content", {})),
        "images": len(doc.get("images", {})),
        "gallery": len(doc.get("gallery", [])),
    }
