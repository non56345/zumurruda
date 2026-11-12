-- مخطط قاعدة بيانات الزُمردة (المرحلة الثالثة – الخطوة 1)
-- الأسعار تُحفظ كنص كما هي في الموقع حتى لا يتغير أي سعر بالتحويل.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content (          -- النصوص (49 حقلاً)
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL DEFAULT '',
  label  TEXT NOT NULL DEFAULT '',
  grp    TEXT NOT NULL DEFAULT '',
  type   TEXT NOT NULL DEFAULT 'text',
  sort   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS contact (          -- روابط فيسبوك/واتساب/الخريطة
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS services (
  id    TEXT PRIMARY KEY,
  name  TEXT NOT NULL,
  en    TEXT,
  desc  TEXT,
  grp   TEXT,
  slot  TEXT,
  price TEXT NOT NULL DEFAULT '',
  sort  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS price_cats (       -- أقسام الأسعار (9)
  id    TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  note  TEXT,
  sort  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS price_groups (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  cat_id TEXT NOT NULL REFERENCES price_cats(id) ON DELETE CASCADE,
  pk     INTEGER,                                -- علامة المجموعة كما في البيانات الأصلية
  title  TEXT,
  sort   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS price_items (      -- بنود الأسعار (55)
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id INTEGER NOT NULL REFERENCES price_groups(id) ON DELETE CASCADE,
  name     TEXT NOT NULL,
  price    TEXT NOT NULL,
  includes TEXT,                                 -- JSON: قائمة نصوص
  star     INTEGER,
  desc     TEXT,
  sort     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS products (         -- منتجات أوبال (6)
  id    TEXT PRIMARY KEY,
  name  TEXT NOT NULL,
  desc  TEXT NOT NULL DEFAULT '',
  price TEXT NOT NULL DEFAULT '',
  slot  TEXT,
  sort  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS images (           -- الصور (18)
  slot         TEXT PRIMARY KEY,
  label        TEXT NOT NULL,
  grp          TEXT NOT NULL,
  src          TEXT NOT NULL,                    -- المسار الحالي
  original_src TEXT NOT NULL,                    -- المسار الأصلي للاستعادة
  sort         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS gallery (
  id   TEXT PRIMARY KEY,
  slot TEXT,
  cat  TEXT,
  cap  TEXT,
  sort INTEGER NOT NULL
);

-- ===== الخطوة 3: المصادقة =====
CREATE TABLE IF NOT EXISTS users (            -- حساب المديرة (كلمة المرور مجزَّأة فقط)
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at    REAL NOT NULL,
  updated_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (         -- جلسات على الخادم؛ يُخزَّن SHA-256 للرمز لا الرمز نفسه
  token_hash TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf       TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_seen  REAL NOT NULL,
  ip         TEXT
);

CREATE TABLE IF NOT EXISTS login_attempts (   -- تقييد محاولات الدخول الخاطئة
  key          TEXT PRIMARY KEY,
  fails        INTEGER NOT NULL,
  first_fail   REAL NOT NULL,
  locked_until REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS auth_events (      -- سجل أحداث الدخول (بلا كلمات مرور)
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       REAL NOT NULL,
  event    TEXT NOT NULL,
  username TEXT,
  ip       TEXT
);

-- ===== الخطوة 4: سجل عمليات اللوحة =====
CREATE TABLE IF NOT EXISTS audit_log (        -- ما الذي تغيّر ومتى ومن غيّره (بلا أي بيانات حساسة)
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       REAL NOT NULL,
  username TEXT,
  msg      TEXT NOT NULL,
  rev      INTEGER NOT NULL
);

-- ===== بطاقة الإهداء: الطلبات الواردة من الموقع العام (جدول جديد؛ لا يمسّ أي جدول موجود) =====
CREATE TABLE IF NOT EXISTS gift_orders (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at  REAL NOT NULL,
  updated_at  REAL NOT NULL,
  status      TEXT NOT NULL DEFAULT 'new',      -- new | preparing | ready | delivered
  to_name     TEXT NOT NULL,
  from_name   TEXT NOT NULL,
  gift        TEXT NOT NULL,
  message     TEXT NOT NULL DEFAULT '',
  phone       TEXT NOT NULL,
  ip_hash     TEXT,                              -- SHA-256 مملّح لتقييد الإرسال المتكرر (لا يُخزَّن العنوان نفسه)
  card        TEXT,                              -- JSON: نصوص ومواضع الكتابة التي جهّزتها المديرة فوق صورة البطاقة
  prepared_at REAL
);
CREATE INDEX IF NOT EXISTS idx_gift_orders_created ON gift_orders(created_at);
