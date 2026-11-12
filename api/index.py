import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import load_env

load_env.load()

from server import create_app

app = create_app()
app.url_map.strict_slashes = False


class VercelQueryPathFix:
    """يعيد بناء PATH_INFO الأصلي من وسيط __p الممرر في vercel.json rewrites."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        qs = environ.get("QUERY_STRING", "")
        if "__p" in qs:
            params = parse_qs(qs, keep_blank_values=True)
            if "__p" in params:
                p = params.pop("__p")[0]
                environ["PATH_INFO"] = p if p.startswith("/") else ("/" + p)
                environ["QUERY_STRING"] = urlencode([(k, v) for k, vs in params.items() for v in vs])
        return self.wsgi_app(environ, start_response)


app.wsgi_app = VercelQueryPathFix(app.wsgi_app)
