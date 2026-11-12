"""تشغيل الموقع للإنتاج بخادم waitress (يعمل على Windows وLinux).

  python serve.py            ← يقرأ الإعدادات من .env أو متغيرات البيئة
ضعي خلفه خادماً عكسياً بـ HTTPS (nginx أو IIS أو لوحة الاستضافة)، واضبطي ZUM_PROXY_HOPS=1.
"""
import load_env

load_env.load()

import os  # noqa: E402
import sys  # noqa: E402

from waitress import serve  # noqa: E402

from server import create_app  # noqa: E402
from server.config import Config  # noqa: E402


def main():
    app = create_app()
    if not app.config["COOKIE_SECURE"]:
        print("تحذير: ZUM_COOKIE_SECURE=0 — مناسب للتجربة المحلية فقط. على الإنترنت يجب تشغيل الموقع بـ HTTPS.",
              file=sys.stderr)
    print(f"الزُمردة يعمل على http://{Config.HOST}:{Config.PORT}/  (لوحة التحكم: /admin/)")
    serve(app, host=Config.HOST, port=Config.PORT, threads=int(os.environ.get("ZUM_THREADS", "8")), ident="zumurrud")


if __name__ == "__main__":
    main()
