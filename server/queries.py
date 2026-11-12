"""قراءة بيانات الموقع من SQLite بنفس بنية البيانات الأولية (seed.js) وترتيبها.

للقراءة فقط. لا تُرجع أي أعمدة داخلية (معرّفات الجداول، sort، original_src، meta).
"""
import json


def _all(conn, q, *a):
    return conn.execute(q, a).fetchall()


def content(conn):
    return {r["key"]: r["value"] for r in _all(conn, "SELECT key,value FROM content ORDER BY sort")}


def content_fields(conn):
    return [{"key": r["key"], "label": r["label"], "group": r["grp"], "type": r["type"]}
            for r in _all(conn, "SELECT * FROM content ORDER BY sort")]


def contact(conn):
    return {r["key"]: r["value"] for r in _all(conn, "SELECT key,value FROM contact ORDER BY rowid")}


def _service(r):
    s = {"id": r["id"], "name": r["name"], "en": r["en"], "desc": r["desc"],
         "group": r["grp"], "slot": r["slot"], "price": r["price"]}
    return {k: v for k, v in s.items() if v is not None}


def services(conn):
    return [_service(r) for r in _all(conn, "SELECT * FROM services ORDER BY sort")]


def service(conn, sid):
    r = conn.execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
    return _service(r) if r else None


def _price_cat(conn, c):
    cat = {"id": c["id"], "t": c["title"]}
    if c["note"] is not None:
        cat["note"] = c["note"]
    cat["groups"] = []
    for g in _all(conn, "SELECT * FROM price_groups WHERE cat_id=? ORDER BY sort", c["id"]):
        grp = {}
        if g["pk"] is not None:
            grp["pk"] = g["pk"]
        if g["title"] is not None:
            grp["g"] = g["title"]
        grp["items"] = []
        for it in _all(conn, "SELECT * FROM price_items WHERE group_id=? ORDER BY sort", g["id"]):
            item = {"n": it["name"], "p": it["price"]}
            if it["includes"] is not None:
                item["inc"] = json.loads(it["includes"])
            if it["star"] is not None:
                item["star"] = it["star"]
            if it["desc"] is not None:
                item["d"] = it["desc"]
            grp["items"].append(item)
        cat["groups"].append(grp)
    return cat


def price_cats(conn):
    return [_price_cat(conn, c) for c in _all(conn, "SELECT * FROM price_cats ORDER BY sort")]


def price_cat(conn, cid):
    c = conn.execute("SELECT * FROM price_cats WHERE id=?", (cid,)).fetchone()
    return _price_cat(conn, c) if c else None


def _product(r):
    return {"id": r["id"], "name": r["name"], "desc": r["desc"], "price": r["price"], "slot": r["slot"]}


def products(conn):
    return [_product(r) for r in _all(conn, "SELECT * FROM products ORDER BY sort")]


def product(conn, pid):
    r = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    return _product(r) if r else None


def images(conn):
    return {r["slot"]: {"label": r["label"], "group": r["grp"], "src": r["src"]}
            for r in _all(conn, "SELECT * FROM images ORDER BY sort")}


def gallery(conn):
    return [{"id": r["id"], "slot": r["slot"], "cat": r["cat"], "cap": r["cap"]}
            for r in _all(conn, "SELECT * FROM gallery ORDER BY sort")]
