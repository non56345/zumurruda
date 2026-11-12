import re
import tempfile
from pathlib import Path

from server import auth, create_app
from server.db import connect

USER = "manager1"
PASSWORD = "Emerald-Garden-2026!"


def make_app(**over):
    tmp = tempfile.TemporaryDirectory()
    cfg = {"DATABASE": str(Path(tmp.name) / "t.db"), "TESTING": True, "PREFERRED_URL_SCHEME": "https"}
    cfg.update(over)
    app = create_app(cfg)
    app._tmp = tmp
    return app


def add_admin(app, user=USER, password=PASSWORD):
    conn = connect(app.config["DATABASE"])
    try:
        auth.create_admin(conn, user, password)
    finally:
        conn.close()


def login(client, user=USER, password=PASSWORD, follow=False):
    r = client.get("/admin/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    return client.post("/admin/login", data={"username": user, "password": password,
                                             "csrf_token": token, "next": "/admin/"},
                       follow_redirects=follow)


def csrf_of(client):
    return client.get("/admin/session").get_json()["csrf_token"]
