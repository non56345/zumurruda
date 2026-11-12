import re
import tempfile

import mongomock

from server import auth, create_app
from server.config import Config
from server.db import get_client, reset_for_tests, set_client_for_tests

USER = "manager1"
PASSWORD = "Emerald-Garden-2026!"


def make_app(**over):
    client = mongomock.MongoClient()
    set_client_for_tests(client)
    cfg = {
        "MONGODB_DB": "test_zumurruda",
        "MONGODB_URI": "mongodb://localhost:27017/test_zumurruda",
        "TESTING": True,
        "PREFERRED_URL_SCHEME": "https",
        "MONGO_CLIENT": client,
        "SECRET_KEY": "test-secret-key-12345678901234567890",
        "SETUP_TOKEN": "test-setup-token-12345678901234567890",
    }
    cfg.update(over)
    app = create_app(cfg)
    app.mongo_client = client
    app._tmp = tempfile.TemporaryDirectory()
    return app


def get_db(app=None):
    if app and hasattr(app, "mongo_client"):
        return app.mongo_client[app.config.get("MONGODB_DB", "test_zumurruda")]
    client = get_client()
    return client[Config.MONGODB_DB]


def connect(_path=None, app=None):
    return get_db(app)


def add_admin(app, user=USER, password=PASSWORD):
    db = get_db(app)
    auth.create_admin(db, user, password)


def login(client, user=USER, password=PASSWORD, follow=False):
    r = client.get("/admin/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True))
    token = match.group(1) if match else ""
    return client.post("/admin/login", data={"username": user, "password": password,
                                             "csrf_token": token, "next": "/admin/"},
                       follow_redirects=follow)


def csrf_of(client):
    return client.get("/admin/session").get_json()["csrf_token"]
