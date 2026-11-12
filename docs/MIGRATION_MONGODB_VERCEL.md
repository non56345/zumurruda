# خطة ترحيل موقع الزُمردة: SQLite ← MongoDB Atlas، والنشر على Vercel

> **للوكيل (Antigravity):** هذه الخطة هي المرجع الكامل. حمّل المستودع https://github.com/non56345/zumurruda ونفّذ كل البنود بالترتيب، ثم ارفع العمل إلى المستودع نفسه (انظر قسم 9). اقرأ `server/` و`manage.py` و`tests/` و`docs/` كاملة قبل أي تعديل. اللغة: رسائل الواجهة والأخطاء تبقى بالعربية كما هي، والكود والتعليقات التقنية بالإنجليزية أو العربية كما في الملف الأصلي.

---

## 0. الهدف

موقع Flask عربي (موقع عام + لوحة تحكم + بطاقات إهداء) يعمل حالياً على SQLite وملفات محلية. المطلوب:

1. قاعدة البيانات على **MongoDB Atlas** بدل SQLite.
2. النشر على **Vercel** (Python serverless) مع كل الإعدادات في **Environment Variables**.
3. **بدون أي أمر Python يدوي لإنشاء القاعدة.** لا `init-db` ولا `create-admin` كشرط للتشغيل. القاعدة تتجهّز تلقائياً، وحساب المديرة يُنشأ من **صفحة إعداد أولي في المتصفح** عند أول تشغيل.
4. لا تغيير في شكل الموقع ولا في سلوك اللوحة ولا في ردود الـ API.

## 1. القرارات المحسومة (لا تعيد فتحها)

| الموضوع | القرار |
|---|---|
| نموذج البيانات | وثيقة `site` واحدة تحمل كل بيانات الموقع + `rev`. الحفظ = Compare-and-Set على `rev` (يعوّض `BEGIN IMMEDIATE` والـ 409) |
| الـ "SQL" في Atlas | لا يوجد. مونجو بلا schema، والـ collections تُنشأ عند أول كتابة. الـ indexes والبيانات الأولية يتجهّزان تلقائياً (قسم 4) |
| إنشاء الأدمن | صفحة `/admin/setup` محمية بـ `SETUP_TOKEN`، تعمل مرة واحدة فقط (قسم 5) |
| الصور المرفوعة | تُخزن داخل مونجو (collection `uploads`) بعد التصغير، وتُخدم من `/uploads/<name>` بكاش طويل |
| النسخ الاحتياطي | Atlas Backups للقاعدة كلها + نسخة مصغّرة لوثيقة `site` قبل كل import/reset (collection `site_backups`) |
| الجلسات | تبقى جلسات خادم (تجزئة SHA-256 للتوكن) لكن في مونجو مع TTL |
| `serve.py`, `passenger_wsgi.py`, waitress | تُحذف من مسار الإنتاج (تبقى `run.py` للتطوير المحلي) |

## 2. ما يجب أن يفعله صاحب المشروع يدوياً (مرة واحدة)

> الوكيل لا يستطيع ولا يجب أن يفعل هذه. اذكرها في تقرير النهاية كقائمة.

1. **Atlas:** أنشئ Cluster مجاني (M0). المنطقة: **AWS eu-central-1 (Frankfurt)** (الأقرب لليبيا ولـ Vercel `fra1`).
2. **Database Access:** أنشئ مستخدماً بصلاحية `readWrite` على قاعدة `zumurruda` فقط (ليس Atlas admin). كلمة مرور بلا رموز خاصة، أو رمّزها URL-encode داخل الـ URI.
3. **Network Access:** أضف `0.0.0.0/0` (عناوين Vercel متغيرة).
4. انسخ **Connection String** (`mongodb+srv://...`).
5. **Vercel → Project → Settings → Environment Variables:** أضف المتغيرات في قسم 3 لبيئتي **Production** و**Preview**، ثم أعد النشر (المتغيرات الجديدة لا تُطبّق على نشر قديم).
6. بعد أول نشر افتح `/admin/setup` وأنشئ حساب المديرة (قسم 5).

## 3. متغيرات البيئة

أعد كتابة `.env.example` بهذه المتغيرات مع شرح عربي لكل واحد، وأزل متغيرات SQLite القديمة (`ZUM_DB`, `ZUM_UPLOADS`, `ZUM_BACKUP_INTERVAL`, `ZUM_HOST`, `ZUM_PORT` تبقى للتطوير فقط):

```
MONGODB_URI=mongodb+srv://USER:PASS@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=zumurruda
SECRET_KEY=<64+ حرف عشوائي>              # مطلوب في الإنتاج
SETUP_TOKEN=<24+ حرف عشوائي>             # لصفحة الإعداد الأولي
ZUM_COOKIE_SECURE=1
ZUM_PROXY_HOPS=1                          # Vercel خلف وكيل: ضروري لقراءة IP الحقيقي
ZUM_AUTO_INIT=1                           # التجهيز التلقائي للقاعدة (الافتراضي 1)
ZUM_SESSION_IDLE=1800
ZUM_SESSION_MAX=28800
```

قواعد في `config.py`:
- `SECRET_KEY` يُقرأ من البيئة. إن غاب في الإنتاج (`VERCEL` موجود أو `ZUM_ENV=production`) يفشل الإقلاع برسالة واضحة. محلياً يُولَّد مفتاح مؤقت مع تحذير. (حالياً `gift.py` يستعمله كملح بـ fallback، وهو غير معرّف في `Config`.)
- `MONGODB_URI` مطلوب دائماً.
- `MAX_CONTENT_LENGTH = 4 * 1024 * 1024` (حد طلب Vercel Functions حوالي 4.5MB). حدّث `uploads.MAX_BYTES` ورسائل الخطأ في `server/__init__.py` و`admin_api.py` من «10 ميغابايت» إلى «4 ميغابايت». افحص `admin/` (grep على `10` و`MB` و`ميغا`): إن وُجد حد في JS اللوحة فحدّثه، واحذر أن `tests/phase2.sha256.json` قد يثبّت بصمات ملفات `admin/`؛ إن تغيّر ملف هناك فحدّث البصمة عمداً واذكر ذلك في التقرير. ويجب ألا يتغير `index.html` إطلاقاً.

## 4. التجهيز التلقائي للقاعدة (بدل init-db)

### 4.1 `server/db.py` (أعد كتابته)

- `MongoClient` واحد على مستوى الوحدة، يُنشأ عند أول استخدام، ويُعاد استخدامه بين الطلبات (مهم في serverless): `MongoClient(uri, serverSelectionTimeoutMS=5000, maxPoolSize=5, appname="zumurruda")`.
- `get_db()`: يخزن `g.db = client[MONGODB_DB]` ويستدعي `ensure_ready(db)`.
- `close_db`: لا يغلق العميل (فقط ينظف `g`).
- `ensure_ready(db)`:
  1. علم على مستوى الوحدة `_ready`؛ إن كان True يخرج فوراً (صفر استعلامات).
  2. اقرأ `db.meta.find_one({"_id": "init"})`؛ إن كان `schema_version == SCHEMA_VERSION` اضبط `_ready=True` واخرج.
  3. وإلا، وإن كان `ZUM_AUTO_INIT != "0"`: نفّذ `ensure_indexes(db)` ثم `seed(db)` ثم `db.meta.update_one({"_id":"init"}, {"$set": {"schema_version": SCHEMA_VERSION, "at": ...}}, upsert=True)`.
  4. أي فشل اتصال يُرفع كخطأ واضح (500 برسالة عامة، والتفاصيل في اللوج).
- كل العمليات **idempotent وآمنة للتزامن** (عدة نسخ serverless قد تقلع معاً).

### 4.2 `ensure_indexes(db)` (كلها `create_index` وهي idempotent)

| Collection | Index |
|---|---|
| `users` | `username` unique |
| `sessions` | `token_hash` unique؛ TTL على `last_seen_dt` بقيمة `SESSION_IDLE+60`؛ TTL على `created_dt` بقيمة `SESSION_MAX+60` |
| `login_attempts` | `key` unique؛ TTL على `expires_dt` (`expireAfterSeconds=0`) |
| `auth_events` | `ts` (وTTL 90 يوماً على `ts_dt`) |
| `audit_log` | `rev` |
| `gift_orders` | `id` unique؛ `created_at`؛ `ip_hash` + `created_at` |
| `counters` | `_id` (افتراضي) |
| `uploads` | `_id` (اسم الملف، افتراضي) |

ملاحظة: TTL للتنظيف فقط (المراقب يعمل كل ~60 ثانية). منطق انتهاء الجلسة الفعلي يبقى في الكود كما هو في `auth.current_session`.

### 4.3 `seed(db)` في `server/seed_loader.py`

- يقرأ `admin/seed.js` بـ `read_seed()` الموجودة (لا تغيّرها).
- يبني وثيقة `site`:
  ```
  {_id: "site", rev: 0, schema: 1,
   contentFields: [...], content: {...}, contact: {...},
   services: [...], priceCats: [...], products: [...],
   images: {slot: {label, group, src, original_src}}, gallery: [...],
   seeded_at: ...}
  ```
  - الأسعار تبقى **نصوصاً** كما هي. لا تحوّل أي قيمة. `priceCats` تُحفظ بنفس بنية `queries.price_cats` (`id,t,note,groups[{pk,g,items[{n,p,inc,star,d}]}]`).
  - `images[slot].original_src` = `src` الأصلي (للاستعادة).
- الكتابة: `db.site.update_one({"_id":"site"}, {"$setOnInsert": doc}, upsert=True)`. هذا ذرّي: لا يمسّ وثيقة موجودة ولا يتكرر عند التزامن.
- `is_seeded(db)` = وجود وثيقة `site`. `counts(db)` و`snapshot(db)` تُحسبان من الوثيقة.

### 4.4 إزالة التجهيز من الإقلاع

في `server/__init__.py::create_app`: احذف `connect/init_schema/seed` من الإقلاع. أبقِ فقط `Template(root/"index.html", read_seed())` (يقرأ ملفات فقط ويتحقق أن `index.html` سليم). `create_app()` يجب ألا يتصل بمونجو ولا يكتب شيئاً.

### 4.5 ملفات احتياطية يدوية (اختيارية، للأمان)

أنشئ مجلد `mongo/` فيه:
- `mongo/README.md`: كيف تُجهَّز القاعدة يدوياً إن عطّل المستخدم `ZUM_AUTO_INIT`.
- `mongo/site.seed.json`: تُولَّد من `seed.js` بنص برمجي `mongo/export_seed.py` (يعمل محلياً بدون اتصال).
- `mongo/indexes.js`: سكربت `mongosh` يطابق 4.2 حرفياً.

## 5. الإعداد الأولي للمديرة: `/admin/setup`

**المبدأ:** الصفحة العامة الوحيدة التي تنشئ حساباً. تعمل فقط إذا (لا يوجد أدمن) **و**(`SETUP_TOKEN` معرّف بطول ≥ 24). وإلا ترجع 404.

### 5.1 السلوك

- `GET /admin/setup`: نموذج: رمز الإعداد، اسم المستخدم، كلمة المرور، التأكيد. نفس أسلوب `login.html` (قالب جديد `server/templates/setup.html`، RTL، نفس CSS/CSP الخاص بصفحة الدخول).
- `POST /admin/setup`:
  1. تحقق CSRF بنفس آلية صفحة الدخول (كوكي `zum_login_csrf` + حقل).
  2. تقييد محاولات: مفتاح `setup:<ip>` في `login_attempts` (5 محاولات / قفل 15 دقيقة).
  3. قارن الرمز بـ `hmac.compare_digest`.
  4. `auth.validate_username` و`auth.validate_password` (الموجودتان).
  5. **منع السباق:** `db.meta.insert_one({"_id": "admin_lock", "at": now})`؛ إن رفع `DuplicateKeyError` فهناك أدمن بالفعل → 404/رسالة.
  6. أنشئ المستخدم (`generate_password_hash` scrypt كما هو).
  7. سجّل `auth_events` (`admin_created`) وحوّل إلى `/admin/login`.
- بعد وجود أدمن: المسار يرجع **404** دائماً (حتى مع الرمز الصحيح).
- أضف `"auth.setup_page"`, `"auth.setup_submit"` إلى `PUBLIC_ENDPOINTS`، وتأكد أن `guard()` لا يحجبهما، وأن فحص الأصل `_origin_ok` يبقى مطبّقاً على POST.
- صفحة الدخول: إن لم يوجد أدمن وكان الإعداد مفعلاً، اعرض رابطاً «إعداد الحساب لأول مرة». وإن لم يوجد أدمن والـ SETUP_TOKEN غير معرّف اعرض: «لم يُنشأ حساب بعد. أضيفي SETUP_TOKEN في إعدادات Vercel ثم أعيدي النشر».

### 5.2 الاسترجاع (نسيان كلمة المرور)

- من داخل اللوحة: صفحة تغيير كلمة المرور (موجودة).
- إن فُقد الوصول كلياً: من Atlas احذف وثيقة المستخدم من `users` ووثيقة `meta` ذات `_id: "admin_lock"`، فتُفتح `/admin/setup` من جديد (يلزم `SETUP_TOKEN`). وثّق هذا في `docs/DEPLOY.md`.
- يبقى `python manage.py change-password` كأداة طوارئ محلية اختيارية (قسم 6.9)، وليس شرطاً.

### 5.3 توصية أمنية في التوثيق

بعد إنشاء الحساب يُنصح بحذف `SETUP_TOKEN` من Vercel (الصفحة مقفلة أصلاً، لكنه تقليل للسطح).

## 6. تعديل كل ملف (تفصيلي)

### 6.1 `server/config.py`
احذف `DATABASE`, `UPLOADS`, `BACKUP_INTERVAL`, `SCHEMA_PATH`. أضف `MONGODB_URI`, `MONGODB_DB`, `SECRET_KEY`, `AUTO_INIT`, `SETUP_TOKEN`. أبقِ `SEED_PATH` و`ROOT` وإعدادات الجلسة وتقييد الدخول. في `create_app` عيّن `app.secret_key = config["SECRET_KEY"]`.

### 6.2 `server/__init__.py`
- أزل التجهيز عند الإقلاع (4.4).
- `render_cached(..., db_id=app.config["MONGODB_DB"])` بدل مسار القاعدة.
- مسار `/uploads/<name>` يخدم من مونجو (6.7). أبقِ مسار `/images/` و`/admin/` الثابتين.
- `ProxyFix` عند `ZUM_PROXY_HOPS>0` مع `x_for, x_proto, x_host` (موجود). **تحقق من وثائق Vercel الحالية** لترويسات الـ IP (`x-forwarded-for` / `x-real-ip`) وتأكد أن `request.remote_addr` الناتج هو IP الزائر الحقيقي، لأن تقييد الدخول مبني عليه، وإلا يُقفل الجميع معاً بعد 5 محاولات.
- معالجات 413: رسالة 4MB.

### 6.3 `server/queries.py`
أعد كتابتها لتقرأ من وثيقة `site` (استعلام واحد لكل طلب، أو مرّر الوثيقة المقروءة). **نفس التواقيع ونفس شكل المخرجات** (`content`, `content_fields`, `contact`, `services`, `service(id)`, `price_cats`, `price_cat(id)`, `products`, `product(id)`, `images`, `gallery`) لأن `api.py` و`render.py` و`tests` تعتمد عليها. أبقِ ترتيب المفاتيح (Python dict يحفظه، وPyMongo يحفظ ترتيب الحقول؛ لا تستعمل `sort_keys`). الحقول الاختيارية (`en`, `desc`, `note`, `inc`, `star`, `d`...) لا تُرجَع إلا إن وُجدت، كما في المنطق الحالي.

### 6.4 `server/store.py`
- `get_rev(db)`: من وثيقة `site`.
- `replace_state(db, d, username, msg, base_rev)`:
  1. اقرأ الوثيقة الحالية (لأخذ `images[*].original_src` والمحافظة عليها، وللصور الجديدة `original_src = src`).
  2. ابنِ الوثيقة الجديدة بنفس منطق `replace_state` الحالي (ترتيب `sort` = ترتيب القوائم).
  3. **CAS:** `db.site.update_one({"_id":"site", "rev": current_rev}, {"$set": {...}, "$inc": {"rev": 1}})`. إن لم يُطابق (`matched_count == 0`) → تعارض 409 مع رقم المراجعة الحالي (نفس الرسالة العربية). إن مرّر العميل `base_rev` مختلفاً عن الحالي → 409 قبل الكتابة.
  4. `audit_log.insert_one({ts, username, msg[:300], rev})` ثم احتفظ بآخر `LOG_KEEP=500` (احذف الأقدم بـ `rev`).
- `recent_log`, `full_state`, `content_keys`, `seed_slots`, `restore_seed_state`: كما هي منطقياً.
- **النسخ الاحتياطي:** احذف `make_backup/maybe_periodic_backup/backup_dir`. أضف `snapshot_site(db, reason)` تنسخ وثيقة `site` إلى `site_backups` (`{_id: ObjectId, reason, at, doc}`) وتُبقي آخر 20. تُستدعى قبل `import` و`reset` فقط (كما كان). `POST /api/admin/backup` يستدعيها بسبب `manual` ويرجع `{ok:true, file: "<id>"}`.
- `referenced_uploads(db)`: مجموعة أسماء من `images[*].src` التي تبدأ بـ `uploads/`.

### 6.5 `server/auth.py`
الحفاظ على **كل المنطق** (scrypt، SHA-256 للتوكن، CSRF، `guard`، رؤوس الأمان، قيود كلمة المرور، رسائل العربية). التغيير في طبقة التخزين فقط:
- `users`: `{_id: ObjectId, username, password_hash, created_at, updated_at}`. استبدل `user_id` الصحيح بـ `str(_id)` في `g.session["user_id"]`.
- `sessions`: `{token_hash (unique), user_id, csrf, created_at, last_seen, ip, created_dt, last_seen_dt}`. `current_session` يتحقق من الانتهاء في الكود ويحدّث `last_seen/last_seen_dt` عند `touch`. أرجع dict بنفس مفاتيح الصف الحالي (`username`, `csrf`, `user_id`...) بعمل join يدوي بقراءة المستخدم.
- `login_attempts`: `_register_fail` باستعمال `find_one_and_update` مع `upsert` (يعادل `ON CONFLICT`)، وأضف `expires_dt` للـ TTL.
- `set_password`: حدّث المستخدم واحذف كل جلساته (`delete_many`).
- `admin_exists`: وجود أي مستخدم **أو** وثيقة `admin_lock`.
- `create_admin`: كما في 5.1 (يشمل `admin_lock`).
- أضف مسارات الإعداد (قسم 5).

### 6.6 `server/gift.py`
- `gift_orders`: وثائق بنفس أسماء الأعمدة (`id,created_at,updated_at,status,to_name,from_name,gift,message,phone,ip_hash,card,prepared_at`). `card` يُخزن كـ dict مباشرة (بدل نص JSON) أو كنص JSON كما هو، اختر الأبسط مع إبقاء مخرجات `order_dict` متطابقة.
- المعرّف الصحيح المتسلسل: `db.counters.find_one_and_update({"_id":"gift_orders"}, {"$inc":{"seq":1}}, upsert=True, return_document=AFTER)` ثم `id = seq`. هكذا تبقى المسارات `/gift-orders/<int:oid>` وواجهة اللوحة كما هي.
- تحديد معدّل الإرسال: `count_documents({"ip_hash": h, "created_at": {"$gt": now-WINDOW}})`.
- `gift_card_layout`: وثيقة `meta` بـ `_id: "gift_card_layout"` (`{value: <json>}`) أو داخل `site`، مع `update_one(..., upsert=True)`.
- `list_orders`: `find().sort("id",-1).limit(500)` وعدّادات الحالات بـ `aggregate` على `status`.
- `update_order`: بناء `$set` من الحقول المسموح بها نفسها (لا تبنِ استعلاماً من مدخلات المستخدم؛ استعمل قائمة بيضاء).

### 6.7 `server/uploads.py` و`admin_api.py`
- `save_image(data, db, kind)`: أبقِ كل التحقق وإعادة الكتابة بـ Pillow (حجم، حروف، EXIF، تصغير). بدل `im.save(folder/name)` احفظ في `io.BytesIO` ثم `db.uploads.insert_one({"_id": name, "data": Binary(bytes), "content_type": ..., "size": ..., "width":..., "height":..., "created_at": ...})`. الاسم عشوائي كما هو.
- `exists(db, name)`: `NAME_OK` ثم `count_documents({"_id": name}, limit=1)`.
- `cleanup(db, referenced, dry_run)`: يحذف الوثائق غير المرجوعة.
- مسار `GET /uploads/<name>`: تحقق من الاسم، اقرأ الوثيقة، أرجع البايتات مع `Content-Type` و`Cache-Control: public, max-age=31536000, immutable` و`ETag` = الاسم، و`X-Content-Type-Options: nosniff`. 404 إن لم توجد.
- `admin_api._uploads_dir()` يُزال، وكل استدعاء يمرّر `db`.
- الحجم: `MAX_BYTES = 4 MB` (قسم 3).

### 6.8 `server/validate.py`, `server/render.py`, `server/api.py`
لا تغيير منطقي إلا استبدال `conn` بـ `db` حيث لزم و`upload_exists` ليستعمل مونجو. `render.py` يبقى على `read_seed()` ولا يلمس القاعدة إلا عبر `data_from_db`.

### 6.9 `manage.py`
أبقِ الأوامر **كأدوات طوارئ اختيارية** تعمل على مونجو (ولا شيء منها شرط للتشغيل): `admin-info`, `change-password`, `create-admin`, `status`, `check`, `cleanup-uploads`, `reseed` (بتأكيد وبعد `snapshot_site`). احذف `backup`, `list-backups`, `restore` وارجع للمستخدم إلى Atlas Backups في رسالة الخطأ. `check` يفحص: الاتصال، وجود وثيقة `site`، الـ indexes، وجود أدمن، توفر `SECRET_KEY`، وأن كل `images[*].src` موجود (ملف في `images/` أو وثيقة في `uploads`). لا ينشئ شيئاً تلقائياً.

### 6.10 `load_env.py`, `run.py`, `wsgi.py`
`load_env` يبقى للتطوير المحلي فقط ولا يفشل إن غاب `.env`. `run.py` للتطوير. `wsgi.py` يبقى (gunicorn اختياري).

## 7. إعداد Vercel

حسب وثائق Vercel الحالية للـ Python/Flask: يكفي ملف نقطة دخول بمتغير `app` على مستوى الملف في الجذر (`app.py` أو `index.py` ...)، وملف `requirements.txt`، ويكتشف Vercel إطار Flask تلقائياً.

1. **`app.py`** في الجذر:
   ```python
   import load_env
   load_env.load()          # لا يفعل شيئاً على Vercel إن لم يوجد .env
   from server import create_app
   app = create_app()
   ```
   تحذير: المجلد `server/` يشبه الاسم المحجوز `server.py`. استعمل `app.py` صراحةً، أو حدّد `[tool.vercel] entrypoint = "app:app"` في `pyproject.toml` إن حدث تعارض. **تحقق من الوثائق الحالية** قبل اعتماد الحل.
2. **`requirements.txt`**: `Flask>=3.0,<4`, `Pillow>=10.3`, `pymongo[srv]>=4.7` (ويشمل `dnspython` لـ `mongodb+srv`). احذف `waitress`. أبقِ `requirements-dev.txt` فيه `mongomock` و`pytest`.
3. **إصدار Python:** ثبّته (مثلاً 3.12) عبر `pyproject.toml` أو `.python-version`.
4. **`vercel.json`:**
   - `functions` → `excludeFiles` لـ `tests/**`, `docs/**`, `backup-phase1/**`, `mongo/**`, `**/*.md`، مع **التأكد من بقاء** `index.html`, `admin/**`, `images/**`, `server/templates/**`, `admin/seed.js` داخل الحزمة (الكود يقرؤها من القرص). استعمل `includeFiles` إن لزم.
   - `regions`: `["fra1"]` (قريب من Atlas Frankfurt).
   - لا تضف `routes` معقدة: Flask يخدم كل المسارات (`/`, `/admin/`, `/api/*`, `/images/*`, `/uploads/*`).
5. **التحقق بعد النشر:** `/api/health` يجب أن يتحقق من الاتصال بمونجو ووجود وثيقة `site` ويرجع JSON (بلا أسرار).
6. **الأداء:** `Cache-Control` للصفحة العامة يبقى `no-cache`. `images/` تُخدم بـ `max_age` معقول (مثلاً يوم) عبر `send_from_directory(..., max_age=86400)`.

## 8. الاختبارات (132 اختباراً + e2e)

1. حوّل `tests/helpers.py` لإنشاء تطبيق على **mongomock** (`mongomock.MongoClient()` تُحقن بدل العميل الحقيقي عبر `app.config` أو دالة في `db.py` قابلة للاستبدال، مثل `db.set_client_for_tests(...)`).
2. شغّل `pytest`. mongomock لا ينفّذ TTL ولا يعيد بعض تفاصيل الـ indexes؛ اختبر المنطق الفعلي لانتهاء الجلسة بالكود لا بالـ TTL.
3. أضف اختبارات جديدة:
   - تجهيز تلقائي: أول طلب على قاعدة فارغة ينشئ وثيقة `site` والـ indexes، والطلب الثاني لا يكرّر الـ seed.
   - تزامن seed (استدعاءان) لا ينتجان وثيقتين ولا خطأ.
   - `/admin/setup`: 404 بدون `SETUP_TOKEN`؛ رمز خاطئ يُرفض ويُقيَّد؛ إنشاء ناجح مرة واحدة؛ الثاني 404؛ سباق `admin_lock`؛ لا إنشاء بكلمة مرور ضعيفة.
   - CAS: حفظان بنفس `rev` → الثاني 409.
   - رفع صورة → تُخزن في `uploads` وتُخدم من `/uploads/<name>` بالترويسات الصحيحة، وصورة تتجاوز 4MB تُرفض.
   - عدّاد `gift_orders` متسلسل، وتحديد المعدّل يعمل.
   - `ZUM_PROXY_HOPS=1` مع `X-Forwarded-For` يقيّد الدخول حسب IP الزائر لا الوكيل.
4. **e2e** (`tests/e2e/`): شغّلها على قاعدة اختبار حقيقية (`zumurruda_test` على Atlas أو `mongod` محلي بـ Docker). إن تعذّر، وثّق السبب في التقرير ولا تحذفها.
5. المعيار: تنجح كل الاختبارات، أو يُشرح اختبار اختبار سبب حذفه/تعديله. التقرير القديم `docs/TEST_REPORT.md` يُحدَّث بالنتائج الجديدة.

## 9. سير العمل مع Git (مهم)

1. أنشئ فرع `feat/mongodb-vercel` من `main`. **لا تدفع إلى `main` مباشرة.**
2. التزامات صغيرة بالترتيب: (أ) db+config+seed، (ب) queries+store، (ج) auth+setup، (د) gift، (هـ) uploads، (و) manage، (ز) Vercel، (ح) tests، (ط) docs.
3. لا تضف `.env` ولا أي سر أو URI حقيقي إلى أي ملف أو التزام أو اختبار. `.gitignore` يتجاهل `.env` أصلاً؛ أبقِ `.env.example` بقيم وهمية فقط.
4. ادفع الفرع إلى **نفس المستودع** (`git push -u origin feat/mongodb-vercel`). Vercel يبني **Preview Deployment** تلقائياً للفرع (لهذا يجب إضافة المتغيرات لبيئة Preview أيضاً، قسم 2).
5. بعد تجربة صاحب المشروع للـ Preview يدمج الفرع في `main` (PR أو Merge) فيتم النشر على Production.
6. ملفات `docs/`: حدّث `DEPLOY.md` (Atlas + Vercel + الإعداد الأولي + الاسترجاع)، `README.md` (التشغيل السريع المحلي بـ mongomock أو Atlas)، `STATUS.md`، وأضف هذه الخطة إلى `docs/MIGRATION_MONGODB_VERCEL.md`. احذف أو علّم `docs/WINDOWS.md` وملفات `deploy/` (nginx/systemd) و`windows/` كقديمة إن كانت تشير إلى SQLite.

## 10. معايير القبول

- [ ] لا يوجد أي استيراد لـ `sqlite3` في الكود الإنتاجي، ولا `schema.sql`.
- [ ] `create_app()` لا يتصل بالقاعدة ولا يكتب شيئاً عند الإقلاع.
- [ ] تشغيل التطبيق على قاعدة فارغة (Atlas) **بدون أي أمر يدوي** يجهّز القاعدة تلقائياً عند أول طلب.
- [ ] `/admin/setup` ينشئ حساب المديرة مرة واحدة ثم يُقفل (404)، ولا يعمل بدون `SETUP_TOKEN`.
- [ ] الموقع العام مطابق للأصل بايتاً ببايت قبل أي تعديل من اللوحة (اختبارات `render` الموجودة تنجح).
- [ ] اللوحة: دخول، حفظ بيانات (مع 409 عند التعارض)، رفع صورة، استعادة الأصل، طلبات بطاقة الإهداء وتجهيزها، كلها تعمل.
- [ ] تقييد المحاولات يعمل بحسب IP الزائر خلف Vercel.
- [ ] `/api/health` سليم على Vercel، و`manage.py check` يمر.
- [ ] لا أسرار في المستودع. الفرع مدفوع، وPreview يعمل.

## 11. تقرير النهاية المطلوب من الوكيل

1. الملفات المضافة/المعدّلة/المحذوفة.
2. نتيجة `pytest` (العدد والنجاح) وحالة e2e.
3. أي انحراف عن الخطة مع السبب (خصوصاً: حدّ 4MB وتغييرات `admin/` وبصمات `phase2.sha256.json`).
4. قائمة الخطوات اليدوية لصاحب المشروع (قسم 2) بالترتيب، مع قيم المتغيرات المطلوبة بأسمائها فقط.
5. المخاطر المتبقية، ومنها: حدود Atlas M0 (512MB)، وCold start، واعتماد `SETUP_TOKEN` لحين إنشاء الحساب.
