"""يقرأ ملف .env (إن وُجد) بجانب المشروع ويضع قيمه في متغيرات البيئة قبل تحميل الإعدادات.
صيغة السطر: KEY=VALUE  (الأسطر الفارغة وما يبدأ بـ # تُتجاهل). متغيرات البيئة الموجودة مسبقاً لها الأولوية.
لا يحتوي المشروع أي أسرار؛ ملف .env لا يُرفع إلى Git (انظري .gitignore).
"""
import os
from pathlib import Path


def load(path=None):
    p = Path(path) if path else Path(__file__).resolve().parent / ".env"
    if not p.is_file():
        return False
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k.startswith("ZUM_") and k not in os.environ:
            os.environ[k] = v
    return True
