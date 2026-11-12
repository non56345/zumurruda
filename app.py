import load_env

load_env.load()

from server import create_app

app = create_app()


class VercelPathFix:
    """يصلح مسار PATH_INFO عند توجيه طلبات Vercel إلى app.py."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        matched = (
            environ.get("HTTP_X_MATCHED_PATH")
            or environ.get("HTTP_X_VERCEL_MATCHED_PATH")
            or environ.get("HTTP_X_FORWARDED_PATH")
        )
        if matched:
            environ["PATH_INFO"] = matched
        elif environ.get("PATH_INFO", "").startswith("/app.py"):
            rest = environ["PATH_INFO"][len("/app.py"):]
            environ["PATH_INFO"] = rest if rest.startswith("/") else ("/" + rest)
        return self.wsgi_app(environ, start_response)


app.wsgi_app = VercelPathFix(app.wsgi_app)

if __name__ == "__main__":
    from server.config import Config
    app.run(host=Config.HOST, port=Config.PORT, debug=False)
