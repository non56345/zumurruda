"""إعدادات الخادم. كل القيم قابلة للتغيير بمتغيرات البيئة."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # مجلد المشروع (zumurrud/)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SEED_PATH = ROOT / "admin" / "seed.js"


class Config:
    ROOT = ROOT
    DATABASE = os.environ.get("ZUM_DB", str(ROOT / "data" / "zumurrud.db"))
    UPLOADS = Path(os.environ.get("ZUM_UPLOADS", str(ROOT / "uploads")))     # الصور المرفوعة من اللوحة
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024                                     # حد حجم أي طلب
    BACKUP_INTERVAL = int(os.environ.get("ZUM_BACKUP_INTERVAL", str(6 * 3600)))  # نسخة تلقائية كل 6 ساعات عند الكتابة
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
    # ---- خلف وكيل عكسي (nginx...): عدد الوكلاء الموثوقين لقراءة IP الحقيقي ----
    PROXY_HOPS = int(os.environ.get("ZUM_PROXY_HOPS", "0"))
