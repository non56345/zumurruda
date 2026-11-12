"""تشغيل الخادم محلياً للتجربة والتطوير:  python run.py   ثم افتحي http://127.0.0.1:8000/
للإنتاج استخدمي serve.py (waitress) خلف HTTPS."""
import load_env

load_env.load()

from server import create_app  # noqa: E402
from server.config import Config  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=False)
