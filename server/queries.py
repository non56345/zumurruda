"""قراءة بيانات الموقع من MongoDB (وثيقة site) بنفس بنية البيانات الأولية (seed.js) وترتيبها.

للقراءة فقط. لا تُرجع أي حقول داخلية (original_src, meta, rev, schema).
"""
import json


def _site(db_or_doc):
    if isinstance(db_or_doc, dict):
        return db_or_doc
    return db_or_doc.site.find_one({"_id": "site"}) or {}


def content(db_or_doc):
    doc = _site(db_or_doc)
    return doc.get("content", {})


def content_fields(db_or_doc):
    doc = _site(db_or_doc)
    fields = doc.get("contentFields", [])
    return [
        {
            "key": f["key"],
            "label": f["label"],
            "group": f.get("group", f.get("grp")),
            "type": f.get("type", "text"),
        }
        for f in fields
    ]


def contact(db_or_doc):
    doc = _site(db_or_doc)
    return doc.get("contact", {})


def _service(s):
    out = {"id": s["id"], "name": s["name"]}
    for k in ("en", "desc", "group", "slot", "price"):
        if s.get(k) is not None:
            out[k] = s[k]
    return out


def services(db_or_doc):
    doc = _site(db_or_doc)
    return [_service(s) for s in doc.get("services", [])]


def service(db_or_doc, sid):
    for s in services(db_or_doc):
        if s["id"] == sid:
            return s
    return None


def _price_cat(c):
    cat = {"id": c["id"], "t": c.get("t", c.get("title"))}
    if c.get("note") is not None:
        cat["note"] = c["note"]
    cat["groups"] = []
    for g in c.get("groups", []):
        grp = {}
        if g.get("pk") is not None:
            grp["pk"] = g["pk"]
        if g.get("g") is not None:
            grp["g"] = g["g"]
        elif g.get("title") is not None:
            grp["g"] = g["title"]
        items = []
        for it in g.get("items", []):
            item = {"n": it.get("n", it.get("name")), "p": it.get("p", it.get("price"))}
            inc = it.get("inc") if "inc" in it else it.get("includes")
            if inc is not None:
                item["inc"] = inc if isinstance(inc, list) else json.loads(inc)
            if it.get("star") is not None:
                item["star"] = it["star"]
            desc = it.get("d") if "d" in it else it.get("desc")
            if desc is not None:
                item["d"] = desc
            items.append(item)
        grp["items"] = items
        cat["groups"].append(grp)
    return cat


def price_cats(db_or_doc):
    doc = _site(db_or_doc)
    return [_price_cat(c) for c in doc.get("priceCats", [])]


def price_cat(db_or_doc, cid):
    for c in price_cats(db_or_doc):
        if c["id"] == cid:
            return c
    return None


def _product(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "desc": p.get("desc", ""),
        "price": p.get("price", ""),
        "slot": p.get("slot", ""),
    }


def products(db_or_doc):
    doc = _site(db_or_doc)
    return [_product(p) for p in doc.get("products", [])]


def product(db_or_doc, pid):
    for p in products(db_or_doc):
        if p["id"] == pid:
            return p
    return None


def images(db_or_doc):
    doc = _site(db_or_doc)
    imgs = doc.get("images", {})
    return {
        slot: {
            "label": im["label"],
            "group": im.get("group", im.get("grp")),
            "src": im["src"],
        }
        for slot, im in imgs.items()
    }


def gallery(db_or_doc):
    doc = _site(db_or_doc)
    return [
        {
            "id": g["id"],
            "slot": g.get("slot"),
            "cat": g.get("cat"),
            "cap": g.get("cap"),
        }
        for g in doc.get("gallery", [])
    ]
