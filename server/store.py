"""الكتابة في قاعدة البيانات (الخطوة 4): حفظ كامل لبيانات اللوحة داخل معاملة واحدة.

- رقم مراجعة (rev) يمنع أن يمسح جهازٌ تعديلات جهاز آخر دون علم (تعارض 409).
- سجل عمليات (audit_log) بالنص الذي تعرضه اللوحة واسم المستخدمة.
- نسخة احتياطية تلقائية من القاعدة قبل الاستيراد والاستعادة، ودورياً قبل الكتابة.
"""
import json
import sqlite3
import time
from pathlib import Path

from . import queries
from .seed_loader import read_seed, snapshot

LOG_KEEP = 500


def get_rev(conn):
    r = conn.execute("SELECT value FROM meta WHERE key='rev'").fetchone()
    return int(r["value"]) if r else 0


def _set_rev(conn, rev):
    conn.execute("INSERT INTO meta(key,value) VALUES('rev',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (str(rev),))


def content_keys(conn):
    return [r["key"] for r in conn.execute("SELECT key FROM content ORDER BY sort")]


def seed_slots():
    return list(read_seed()["images"].keys())


def recent_log(conn, n=30):
    return [{"t": int(r["ts"] * 1000), "m": r["msg"], "u": r["username"]}
            for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (n,))]


def full_state(conn):
    s = snapshot(conn)
    s.pop("contentFields", None)
    s["version"] = 1
    s["log"] = recent_log(conn)
    return s


def replace_state(conn, d, username, msg):
    """يستبدل بيانات الموقع بالكامل بالبيانات المتحقَّق منها. يُستدعى داخل معاملة."""
    old_imgs = {r["slot"]: r for r in conn.execute("SELECT * FROM images")}
    for k, v in d["content"].items():
        conn.execute("UPDATE content SET value=? WHERE key=?", (v, k))
    for k, v in d["contact"].items():
        conn.execute("INSERT INTO contact(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (k, v))
    # الصور: تحديث مع الاحتفاظ بالمسار الأصلي لكل موضع (للاستعادة)
    for slot in set(old_imgs) - set(d["images"]):
        conn.execute("DELETE FROM images WHERE slot=?", (slot,))
    for i, (slot, im) in enumerate(d["images"].items()):
        if slot in old_imgs:
            conn.execute("UPDATE images SET label=?, grp=?, src=?, sort=? WHERE slot=?",
                         (im["label"], im["group"], im["src"], i, slot))
        else:
            conn.execute("INSERT INTO images(slot,label,grp,src,original_src,sort) VALUES(?,?,?,?,?,?)",
                         (slot, im["label"], im["group"], im["src"], im["src"], i))
    conn.execute("DELETE FROM services")
    for i, s in enumerate(d["services"]):
        conn.execute("INSERT INTO services(id,name,en,desc,grp,slot,price,sort) VALUES(?,?,?,?,?,?,?,?)",
                     (s["id"], s["name"], s["en"], s["desc"], s["group"], s["slot"], s["price"], i))
    conn.execute("DELETE FROM price_cats")           # يحذف المجموعات والبنود بالتتابع (CASCADE)
    for ci, c in enumerate(d["priceCats"]):
        conn.execute("INSERT INTO price_cats(id,title,note,sort) VALUES(?,?,?,?)", (c["id"], c["t"], c.get("note"), ci))
        for gi, g in enumerate(c["groups"]):
            cur = conn.execute("INSERT INTO price_groups(cat_id,pk,title,sort) VALUES(?,?,?,?)",
                               (c["id"], g.get("pk"), g.get("g"), gi))
            for ii, it in enumerate(g["items"]):
                conn.execute("INSERT INTO price_items(group_id,name,price,includes,star,desc,sort) VALUES(?,?,?,?,?,?,?)",
                             (cur.lastrowid, it["n"], it["p"],
                              json.dumps(it["inc"], ensure_ascii=False) if "inc" in it else None,
                              it.get("star"), it.get("d"), ii))
    conn.execute("DELETE FROM products")
    for i, p in enumerate(d["products"]):
        conn.execute("INSERT INTO products(id,name,desc,price,slot,sort) VALUES(?,?,?,?,?,?)",
                     (p["id"], p["name"], p["desc"], p["price"], p["slot"], i))
    conn.execute("DELETE FROM gallery")
    for i, g in enumerate(d["gallery"]):
        conn.execute("INSERT INTO gallery(id,slot,cat,cap,sort) VALUES(?,?,?,?,?)",
                     (g["id"], g["slot"], g["cat"], g["cap"], i))
    rev = get_rev(conn) + 1
    _set_rev(conn, rev)
    conn.execute("INSERT INTO audit_log(ts,username,msg,rev) VALUES(?,?,?,?)", (time.time(), username, msg[:300], rev))
    conn.execute("DELETE FROM audit_log WHERE id <= (SELECT MAX(id) FROM audit_log) - ?", (LOG_KEEP,))
    return rev


def restore_seed_state(conn):
    """البيانات الأصلية المستخرجة من الموقع (seed.js) بصيغة اللوحة."""
    s = read_seed()
    return {k: s[k] for k in ("content", "contact", "services", "priceCats", "products", "images", "gallery")}


# ------------------------------------------------------------------ النسخ الاحتياطي
def backup_dir(db_path):
    return Path(db_path).parent / "backups"


def make_backup(db_path, reason="manual", keep=40):
    """نسخة متسقة بواجهة SQLite backup (آمنة أثناء التشغيل). تُبقي آخر `keep` نسخة."""
    d = backup_dir(db_path)
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = d / f"zumurrud-{stamp}-{reason}.db"
    n = 1
    while dst.exists():
        n += 1
        dst = d / f"zumurrud-{stamp}-{reason}-{n}.db"
    src = sqlite3.connect(db_path)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    files = sorted(d.glob("zumurrud-*.db"), key=lambda p: p.stat().st_mtime)
    for old in files[:-keep] if keep else []:
        old.unlink(missing_ok=True)
    return dst


def maybe_periodic_backup(db_path, interval_seconds):
    d = backup_dir(db_path)
    latest = max((p.stat().st_mtime for p in d.glob("zumurrud-*.db")), default=0) if d.exists() else 0
    if time.time() - latest >= interval_seconds:
        return make_backup(db_path, "auto")
    return None


def referenced_uploads(conn):
    return {r["src"][len("uploads/"):] for r in conn.execute("SELECT src FROM images WHERE src LIKE 'uploads/%'")}


__all__ = ["get_rev", "content_keys", "seed_slots", "full_state", "replace_state", "restore_seed_state",
           "make_backup", "maybe_periodic_backup", "recent_log", "referenced_uploads", "queries"]
