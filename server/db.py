"""الاتصال بقاعدة MongoDB Atlas والتجهيز التلقائي."""
import logging
import time

from flask import current_app, g
from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError

SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)

_client = None
_ready = False
_test_client = None


def set_client_for_tests(client):
    """حقن عميل اختبار (مثل mongomock.MongoClient)."""
    global _test_client, _ready
    _test_client = client
    _ready = False


def reset_for_tests():
    global _ready, _test_client
    _ready = False
    _test_client = None


def get_client():
    global _client, _test_client
    if current_app and current_app.config.get("MONGO_CLIENT"):
        return current_app.config["MONGO_CLIENT"]
    if _test_client is not None:
        return _test_client
    if current_app and current_app.config.get("TESTING"):
        import mongomock
        _test_client = mongomock.MongoClient()
        return _test_client
    if _client is None:
        uri = current_app.config.get("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI مفقود في إعدادات البيئة.")
        _client = MongoClient(
            uri,
            serverSelectionTimeoutMS=5000,
            maxPoolSize=5,
            appname="zumurruda",
        )
    return _client


def get_db():
    if "db" not in g:
        db_name = current_app.config.get("MONGODB_DB", "zumurruda")
        client = get_client()
        db = client[db_name]
        ensure_ready(db)
        g.db = db
    return g.db


def close_db(_exc=None):
    g.pop("db", None)


def ensure_indexes(db):
    """إنشاء الفهارس الضرورية بشكل idempotent وآمن للتكرار."""
    idle_ttl = int(current_app.config.get("SESSION_IDLE_SECONDS", 1800)) + 60
    max_ttl = int(current_app.config.get("SESSION_MAX_SECONDS", 28800)) + 60

    try:
        # 1. users: username unique
        db.users.create_index([("username", ASCENDING)], unique=True)

        # 2. sessions: token_hash unique + TTLs
        db.sessions.create_index([("token_hash", ASCENDING)], unique=True)
        db.sessions.create_index([("last_seen_dt", ASCENDING)], expireAfterSeconds=idle_ttl)
        db.sessions.create_index([("created_dt", ASCENDING)], expireAfterSeconds=max_ttl)

        # 3. login_attempts: key unique + TTL
        db.login_attempts.create_index([("key", ASCENDING)], unique=True)
        db.login_attempts.create_index([("expires_dt", ASCENDING)], expireAfterSeconds=0)

        # 4. auth_events: ts + TTL 90 days
        db.auth_events.create_index([("ts", ASCENDING)])
        db.auth_events.create_index([("ts_dt", ASCENDING)], expireAfterSeconds=90 * 86400)

        # 5. audit_log: rev
        db.audit_log.create_index([("rev", ASCENDING)])

        # 6. gift_orders: id unique, created_at, compound ip_hash + created_at
        db.gift_orders.create_index([("id", ASCENDING)], unique=True)
        db.gift_orders.create_index([("created_at", ASCENDING)])
        db.gift_orders.create_index([("ip_hash", ASCENDING), ("created_at", ASCENDING)])
    except Exception as e:
        logger.warning("تعذّر إنشاء بعض الفهارس (طبيعي مع بعض برامج المحاكاة مثل mongomock): %s", e)


def ensure_ready(db):
    """التحقق من جاهزية القاعدة أو تهيئتها تلقائياً عند أول طلب."""
    global _ready
    if _ready:
        return

    try:
        init_doc = db.meta.find_one({"_id": "init"})
        if init_doc and init_doc.get("schema_version") == SCHEMA_VERSION:
            _ready = True
            return

        auto_init = current_app.config.get("AUTO_INIT", True)
        if auto_init:
            ensure_indexes(db)
            from .seed_loader import seed
            seed(db)
            db.meta.update_one(
                {"_id": "init"},
                {"$set": {"schema_version": SCHEMA_VERSION, "at": time.time()}},
                upsert=True,
            )
            _ready = True
    except PyMongoError as e:
        logger.error("فشل الاتصال بقاعدة MongoDB أو تهيئتها: %s", e)
        raise
