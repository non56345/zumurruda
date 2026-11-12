"""استيراد البيانات الأولية من admin/seed.js إلى SQLite، وتصدير لقطة للمقارنة.

لا يغيّر أي قيمة: الأسعار والنصوص تُنقل كما هي حرفياً.
"""
import json
import shutil
import time
from pathlib import Path

from . import queries
from .config import SEED_PATH


def read_seed(path=SEED_PATH):
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def is_seeded(conn):
    return conn.execute("SELECT 1 FROM meta WHERE key='seeded_at'").fetchone() is not None


def seed(conn, data=None):
    """يملأ الجداول الفارغة فقط. لا يلمس قاعدة بيانات سبق استيرادها."""
    if is_seeded(conn):
        return False
    d = data or read_seed()
    with conn:
        for i, f in enumerate(d["contentFields"]):
            conn.execute(
                "INSERT INTO content(key,value,label,grp,type,sort) VALUES(?,?,?,?,?,?)",
                (f["key"], d["content"][f["key"]], f["label"], f["group"], f.get("type", "text"), i))
        for k, v in d["contact"].items():
            conn.execute("INSERT INTO contact(key,value) VALUES(?,?)", (k, v))
        for i, s in enumerate(d["services"]):
            conn.execute(
                "INSERT INTO services(id,name,en,desc,grp,slot,price,sort) VALUES(?,?,?,?,?,?,?,?)",
                (s["id"], s["name"], s.get("en"), s.get("desc"), s.get("group"), s.get("slot"),
                 s.get("price", ""), i))
        for ci, c in enumerate(d["priceCats"]):
            conn.execute("INSERT INTO price_cats(id,title,note,sort) VALUES(?,?,?,?)",
                         (c["id"], c["t"], c.get("note"), ci))
            for gi, g in enumerate(c["groups"]):
                cur = conn.execute(
                    "INSERT INTO price_groups(cat_id,pk,title,sort) VALUES(?,?,?,?)",
                    (c["id"], g.get("pk"), g.get("g"), gi))
                for ii, it in enumerate(g["items"]):
                    conn.execute(
                        "INSERT INTO price_items(group_id,name,price,includes,star,desc,sort)"
                        " VALUES(?,?,?,?,?,?,?)",
                        (cur.lastrowid, it["n"], it["p"],
                         json.dumps(it["inc"], ensure_ascii=False) if "inc" in it else None,
                         it.get("star"), it.get("d"), ii))
        for i, p in enumerate(d["products"]):
            conn.execute("INSERT INTO products(id,name,desc,price,slot,sort) VALUES(?,?,?,?,?,?)",
                         (p["id"], p["name"], p.get("desc", ""), p.get("price", ""), p.get("slot"), i))
        for i, (slot, im) in enumerate(d["images"].items()):
            conn.execute(
                "INSERT INTO images(slot,label,grp,src,original_src,sort) VALUES(?,?,?,?,?,?)",
                (slot, im["label"], im["group"], im["src"], im["src"], i))
        for i, g in enumerate(d["gallery"]):
            conn.execute("INSERT INTO gallery(id,slot,cat,cap,sort) VALUES(?,?,?,?,?)",
                         (g["id"], g.get("slot"), g.get("cat"), g.get("cap"), i))
        conn.execute("INSERT INTO meta(key,value) VALUES('seed_version',?)", (str(d.get("version", 1)),))
        conn.execute("INSERT INTO meta(key,value) VALUES('seeded_at',?)", (time.strftime("%Y-%m-%dT%H:%M:%S"),))
    return True


def snapshot(conn):
    """يعيد بناء بنية البيانات الأولية من قاعدة البيانات (للمقارنة والتحقق)."""
    return {
        "content": queries.content(conn),
        "contentFields": queries.content_fields(conn),
        "contact": queries.contact(conn),
        "services": queries.services(conn),
        "priceCats": queries.price_cats(conn),
        "products": queries.products(conn),
        "images": queries.images(conn),
        "gallery": queries.gallery(conn),
    }


def counts(conn):
    n = lambda q: conn.execute(q).fetchone()[0]
    return {"services": n("SELECT COUNT(*) FROM services"),
            "price_categories": n("SELECT COUNT(*) FROM price_cats"),
            "price_items": n("SELECT COUNT(*) FROM price_items"),
            "products": n("SELECT COUNT(*) FROM products"),
            "texts": n("SELECT COUNT(*) FROM content"),
            "images": n("SELECT COUNT(*) FROM images"),
            "gallery": n("SELECT COUNT(*) FROM gallery")}


def backup_file(db_path):
    """نسخة احتياطية مؤرخة قبل أي عملية تعيد التهيئة."""
    p = Path(db_path)
    if not p.exists():
        return None
    dst = p.with_name(f"{p.stem}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(p, dst)
    return dst
