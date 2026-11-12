"""تصدير البيانات الأولية من admin/seed.js إلى صيغة وثيقة site لمونجو."""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "admin" / "seed.js"
OUT_PATH = ROOT / "mongo" / "site.seed.json"


def export():
    text = SEED_PATH.read_text(encoding="utf-8")
    d = json.loads(text[text.index("{"): text.rindex("}") + 1])
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
    OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"تم تصدير {OUT_PATH}")


if __name__ == "__main__":
    export()
