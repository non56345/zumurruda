"""توليد الصفحة العامة من index.html الأصلي + بيانات القاعدة (الخطوة 6).

المبدأ: index.html يبقى على القرص كما هو تماماً (قالب). عند كل طلب تُستبدل فيه فقط المواضع
التي تختلف بياناتها عن البيانات الأصلية (seed). لذلك:
  - إن لم تُعدَّل أي بيانات، تكون الصفحة المُرسلة مطابقة للأصل بايتاً ببايت.
  - التصميم والألوان والخطوط والشعار والـ CSS والسلوك لا تُمَسّ؛ تتغير النصوص والبيانات فقط.

المواضع: النصوص (49 حقلاً)، بطاقات الخدمات، خيارات «الخدمة المطلوبة» في نموذج التواصل،
كائن SITE (الاسم، روابط التواصل، الصور، المعرض، منتجات أوبال)، مصفوفة PRICES، صورة خلفية الفيديو والشعار.
كل النصوص تُهرَّب (HTML/JS) فلا يمكن حقن شيفرة من اللوحة.
"""
import html
import json
import re
import threading
from pathlib import Path

from . import queries
from .seed_loader import read_seed

ARROW = '<svg class="i" viewBox="0 0 24 24"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>'
SPARKLE = '<svg class="i" viewBox="0 0 24 24"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/></svg>'
DELAYS_TILES = ["", " d1", " d2", " d3"]
DELAYS_CARDS = ["", " d1"]
FIXED_FORM_TAIL = [("events", "تأجير مساحة المناسبات"), ("opal", "متجر أوبال")]
# النصوص المكررة في الصفحة: نحدد موضعها بالسياق
CONTEXT = {"contact_eyebrow": '<span class="eyebrow rv">'}


def t(v):
    return html.escape(v, quote=False)


def a(v):
    return html.escape(v, quote=True)


def js_literal(obj):
    """JSON صالح كـ JavaScript وآمن داخل <script> (لا يمكن إغلاق الوسم أو كسر السطر)."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return (s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
             .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


class TemplateError(RuntimeError):
    pass


class Template:
    """يحلّل index.html مرة واحدة ويحدد المواضع القابلة للاستبدال، ويتأكد أنها موجودة وفريدة."""

    def __init__(self, path: Path, seed: dict):
        self.path = path
        self.src = path.read_text(encoding="utf-8")
        self.mtime = path.stat().st_mtime
        self.seed = seed
        s = self.src
        self.script_at = s.index("<script>\n/* =====")           # بداية السكربت الرئيسي
        self.site_span = self._span(r"const SITE = \{.*?\n\};\n", "SITE")
        self.prices_span = self._span(r"const PRICES=\[.*?\n\];\n", "PRICES")
        self.services_span = self._span(r'    <div class="tiles">\n.*?\n    </div>\n\n    <div class="cards">\n.*?\n    </div>\n',
                                        "services")
        self.form_span = self._span(r'          <option value="استفسار عام">استفسار عام</option>\n.*?        </select>', "form")
        region = s[self.services_span[0]:self.services_span[1]]
        # بيانات العرض الأصلية لكل خدمة (النص البديل، وسم الصورة الناقصة، الأيقونة، نص الرابط)
        self.tile_meta = {m[0]: {"label": html.unescape(m[1]), "alt": html.unescape(m[2])} for m in re.findall(
            r'data-open="([^"]+)"><span class="ph missing" data-slot="[^"]+" data-label="([^"]*)"><img alt="([^"]*)">', region)}
        self.card_meta = {}
        for m in re.finditer(r'<div class="ph missing" data-slot="([^"]+)" data-label="([^"]*)"><img alt="([^"]*)"></div>\n'
                             r'        \n        <div class="card-b"><span class="ic">(.*?)</span>\n.*?data-pick="([^"]+)">(.*?) <svg',
                             region, re.S):
            self.card_meta[m[5]] = {"label": html.unescape(m[2]), "alt": html.unescape(m[3]), "icon": m[4],
                                    "more": html.unescape(m[6])}
        self.form_ids = re.findall(r'<option value="([^"]+)">', s[self.form_span[0]:self.form_span[1]])
        # النصوص
        body = s[:self.script_at]
        self.text_pos = {}
        for k, v in seed["content"].items():
            if k in ("name", "pageName", "footer_credit"):
                continue
            needle = CONTEXT.get(k, "") + ("" if k in CONTEXT else ">") + t(v) + "<"
            if body.count(needle) != 1:
                raise TemplateError(f"النص «{k}» غير موجود أو مكرر في index.html")
            i = body.index(needle) + len(needle) - 1 - len(t(v))
            self.text_pos[k] = (i, i + len(t(v)))
        self._check(self.services_span, self.form_span, self.site_span, self.prices_span)
        if set(self.tile_meta) | set(self.card_meta) != {sv["id"] for sv in seed["services"]}:
            raise TemplateError("بطاقات الخدمات في index.html لا تطابق البيانات الأصلية")

    def _span(self, pattern, what):
        ms = list(re.finditer(pattern, self.src, re.S))
        if len(ms) != 1:
            raise TemplateError(f"تعذّر تحديد موضع {what} في index.html")
        return ms[0].span()

    @staticmethod
    def _check(*spans):
        spans = sorted(spans)
        for x, y in zip(spans, spans[1:]):
            if x[1] > y[0]:
                raise TemplateError("مواضع متداخلة في index.html")


# ------------------------------------------------------------------ المولّدات
def gen_services(tpl, services, images):
    beauty = [s for s in services if s["group"] == "beauty"]
    other = [s for s in services if s["group"] != "beauty"]
    tiles = []
    for i, s in enumerate(beauty):
        meta = tpl.tile_meta.get(s["id"], {"label": "الصورة قريبًا", "alt": s["name"]})
        en = f'<span>{t(s["en"])}</span>' if s.get("en") else ""
        tiles.append(
            f'      <button class="tile rv{DELAYS_TILES[i % 4]}" data-open="{a(s["slot"])}"><span class="ph missing" '
            f'data-slot="{a(s["slot"])}" data-label="{a(meta["label"])}"><img alt="{a(meta["alt"])}"></span>\n'
            f'        <span class="cap"><h3>{t(s["name"])}{en}</h3><p>{t(s["desc"])}</p></span></button>\n')
    cards = []
    for i, s in enumerate(other):
        meta = tpl.card_meta.get(s["id"], {"label": "الصورة قريبًا", "alt": s["name"], "icon": SPARKLE,
                                           "more": "استفسري عن " + s["name"]})
        cards.append(
            f'      <article class="card rv{DELAYS_CARDS[i % 2]}">\n'
            f'        <div class="ph missing" data-slot="{a(s["slot"])}" data-label="{a(meta["label"])}"><img alt="{a(meta["alt"])}"></div>\n'
            f'        \n'
            f'        <div class="card-b"><span class="ic">{meta["icon"]}</span>\n'
            f'          <h3>{t(s["name"])}</h3>\n'
            f'          <p>{t(s["desc"])}</p>\n'
            f'          <a href="#contact" class="more" data-pick="{a(s["id"])}">{t(meta["more"])} {ARROW}</a></div>\n'
            f'      </article>\n')
    return ('    <div class="tiles">\n' + "".join(tiles) + '    </div>\n\n    <div class="cards">\n' + "".join(cards)
            + '    </div>\n')


def gen_form(tpl, services):
    seed_ids = {s["id"] for s in tpl.seed["services"]}
    opts = [("استفسار عام", "استفسار عام")]
    # الخدمات الأصلية تظهر في النموذج كما كانت (مثلاً «مقشرات وأقنعة» لم تكن فيه)، والجديدة تُضاف
    opts += [(s["id"], s["name"]) for s in services if s["id"] in tpl.form_ids or s["id"] not in seed_ids]
    opts += FIXED_FORM_TAIL
    return "".join(f'          <option value="{a(v)}">{t(l)}</option>\n' for v, l in opts) + "        </select>"


def site_object(content, contact, services, images, gallery, products):
    return {
        "name": content["name"],
        "pageName": content["pageName"],
        "contact": {"facebook": contact.get("facebook", ""), "whatsapp": contact.get("whatsapp", ""),
                    "map": contact.get("map", "")},
        "images": {k: v["src"] for k, v in images.items() if k != "promo-poster" and v["src"]},
        "gallery": [{"slot": g["slot"], "cat": g["cat"], "cap": g["cap"]} for g in gallery],
        "opal": [{"slot": p["slot"], "cap": p["name"]} for p in products],
        "serviceNames": {**{s["id"]: s["name"] for s in services}, **{s["slot"]: s["name"] for s in services},
                         **dict(FIXED_FORM_TAIL)},
    }


def prices_array(cats):
    return [{k: c[k] for k in ("id", "t", "note", "groups") if k in c} for c in cats]


# ------------------------------------------------------------------ التوليد
_lock = threading.Lock()
_cache = {"tpl": None, "key": None, "html": None}


def _template(path):
    tpl = _cache["tpl"]
    if tpl is None or tpl.path != path or tpl.mtime != path.stat().st_mtime:
        tpl = Template(path, read_seed())
        _cache.update(tpl=tpl, key=None, html=None)
    return tpl


def data_from_db(conn):
    return {"content": queries.content(conn), "contact": queries.contact(conn), "services": queries.services(conn),
            "priceCats": queries.price_cats(conn), "products": queries.products(conn),
            "images": queries.images(conn), "gallery": queries.gallery(conn)}


def render(path: Path, d: dict) -> str:
    tpl = _template(path)
    seed, s = tpl.seed, tpl.src
    edits = []                                          # (بداية، نهاية، نص جديد)

    # النصوص
    for k, (i, j) in tpl.text_pos.items():
        if d["content"].get(k, seed["content"][k]) != seed["content"][k]:
            edits.append((i, j, t(d["content"][k])))

    if d["services"] != seed["services"]:
        edits.append((*tpl.services_span, gen_services(tpl, d["services"], d["images"])))
        edits.append((*tpl.form_span, gen_form(tpl, d["services"])))

    site_now = site_object(d["content"], d["contact"], d["services"], d["images"], d["gallery"], d["products"])
    site_seed = site_object(seed["content"], seed["contact"], seed["services"], seed["images"], seed["gallery"],
                            seed["products"])
    if site_now != site_seed:
        edits.append((*tpl.site_span, "const SITE = " + js_literal(site_now) + ";\n"))

    if prices_array(d["priceCats"]) != prices_array(seed["priceCats"]):
        edits.append((*tpl.prices_span, "const PRICES=" + js_literal(prices_array(d["priceCats"])) + ";\n"))

    out = s
    for i, j, new in sorted(edits, reverse=True):
        out = out[:i] + new + out[j:]

    # استبدالات صغيرة لا تتداخل مع ما سبق (خارج المواضع المحسوبة بالفهرس)
    c, sc = d["content"], seed["content"]
    if (c["name"], c["pageName"]) != (sc["name"], sc["pageName"]):
        old_title = f'<title>{t(sc["name"])} | {t(sc["pageName"])}'
        out = out.replace(old_title, f'<title>{t(c["name"])} | {t(c["pageName"])}', 1)
        out = out.replace(f'<b data-site="name">{t(sc["name"])}</b>', f'<b data-site="name">{t(c["name"])}</b>')
        out = out.replace(f'<small data-site="pageName">{t(sc["pageName"])}</small>',
                          f'<small data-site="pageName">{t(c["pageName"])}</small>')
    credit_old = f'© <span data-site="name">{t(sc["name"])}</span>'
    if c["footer_credit"] != sc["footer_credit"]:
        # نص التذييل منفصل عن الاسم: نزيل data-site حتى لا يكتب السكربت الاسم فوقه
        out = out.replace(credit_old, f'© <span>{t(c["footer_credit"])}</span>', 1)
    elif c["name"] != sc["name"]:
        out = out.replace(credit_old, f'© <span data-site="name">{t(c["name"])}</span>', 1)
    img, simg = d["images"], seed["images"]
    poster = img.get("promo-poster", {}).get("src") or simg["promo-poster"]["src"]
    if poster != simg["promo-poster"]["src"]:
        out = out.replace(f'poster="{simg["promo-poster"]["src"]}"', f'poster="{a(poster)}"', 1)
    logo = img.get("logo", {}).get("src") or simg["logo"]["src"]
    if logo != simg["logo"]["src"]:
        out = out.replace(f'<div class="hero-emblem rv d2" aria-hidden="true"><img src="{simg["logo"]["src"]}"',
                          f'<div class="hero-emblem rv d2" aria-hidden="true"><img src="{a(logo)}"', 1)
    return out


def render_cached(path: Path, conn, rev: int, db_id: str) -> str:
    with _lock:
        tpl = _template(path)
        key = (db_id, rev, tpl.mtime)
        if _cache["key"] == key and _cache["html"] is not None:
            return _cache["html"]
        out = render(path, data_from_db(conn))
        _cache.update(key=key, html=out)
        return out
