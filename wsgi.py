"""نقطة دخول WSGI لخوادم الإنتاج (gunicorn / mod_wsgi / uWSGI):  gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app"""
import load_env

load_env.load()

from server import create_app  # noqa: E402

app = create_app()
