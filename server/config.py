"""إعدادات الخادم. كل القيم قابلة للتغيير بمتغيرات البيئة."""
import os
import secrets
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # مجلد المشروع
SEED_PATH = ROOT / "admin" / "seed.js"


def _get_secret_key():
    sk = os.environ.get("SECRET_KEY")
    if sk:
        return sk
    is_prod = bool(os.environ.get("VERCEL")) or os.environ.get("ZUM_ENV") == "production"
    if is_prod:
        raise RuntimeError("SECRET_KEY مطلوب في بيئة الإنتاج.")
    warnings.warn("لم يُحدد SECRET_KEY؛ تم توليد مفتاح مؤقت لبيئة التطوير.", stacklevel=2)
    return secrets.token_hex(32)


class Config:
    ROOT = ROOT
    SEED_PATH = SEED_PATH

    # ---- MongoDB ----
    MONGODB_URI = os.environ.get("MONGODB_URI", "")
    MONGODB_DB = os.environ.get("MONGODB_DB", "zumurruda")
    AUTO_INIT = os.environ.get("ZUM_AUTO_INIT", "1") != "0"

    # ---- أسرار وحماية ----
    SECRET_KEY = _get_secret_key()
    SETUP_TOKEN = os.environ.get("SETUP_TOKEN", "")
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024                                     # حد حجم أي طلب (4MB)

    # ---- التطوير المحلي والشبكة ----
    HOST = os.environ.get("ZUM_HOST", "127.0.0.1")
    PORT = int(os.environ.get("ZUM_PORT", "8000"))

    # ---- الجلسات والكوكيز ----
    COOKIE_SECURE = os.environ.get("ZUM_COOKIE_SECURE", "1") != "0"   # للتجربة على http فقط: ZUM_COOKIE_SECURE=0
    SESSION_IDLE_SECONDS = int(os.environ.get("ZUM_SESSION_IDLE", str(30 * 60)))    # خمول 30 دقيقة
    SESSION_MAX_SECONDS = int(os.environ.get("ZUM_SESSION_MAX", str(8 * 3600)))     # حد أقصى 8 ساعات

    # ---- تقييد المحاولات ----
    LOGIN_MAX_FAILS = 5            # لكل (مستخدم + عنوان IP)
    LOGIN_MAX_FAILS_IP = 20        # لكل عنوان IP
    LOGIN_WINDOW_SECONDS = 15 * 60
    LOGIN_LOCK_SECONDS = 15 * 60

    # ---- خلف وكيل عكسي (Vercel...): عدد الوكلاء الموثوقين لقراءة IP الحقيقي ----
    PROXY_HOPS = int(os.environ.get("ZUM_PROXY_HOPS", "0"))
