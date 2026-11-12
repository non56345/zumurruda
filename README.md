# موقع الزُمردة بيوتي سنتر — مرحلة الترحيل السحابي (MongoDB Atlas + Vercel)

موقع عام بهوية الزُمردة الأصلية، ولوحة تحكم عربية متصلة بقاعدة بيانات **MongoDB Atlas** ومنشور بسلاسة على بيئة **Vercel Serverless**.
كل تعديل تحفظه المديرة في اللوحة يظهر في الموقع العام فوراً وبشكل متزامن وآمن ضد التعارضات (Optimistic Concurrency Control).

| الوثيقة | المحتوى |
|---|---|
| [docs/DEPLOY.md](docs/DEPLOY.md) | دليل النشر الكامل على MongoDB Atlas وVercel خطوة بخطوة |
| [docs/MIGRATION_MONGODB_VERCEL.md](docs/MIGRATION_MONGODB_VERCEL.md) | خطة الترحيل التقنية الكاملة والقرارات المعتمدة |
| [docs/TEST_REPORT.md](docs/TEST_REPORT.md) | تقرير الاختبارات الشامل (157 اختباراً آلياً بنسبة نجاح 100%) |
| [docs/STATUS.md](docs/STATUS.md) | حالة المشروع ومراحل الإنجاز |
| [docs/WINDOWS.md](docs/WINDOWS.md) | وثيقة التشغيل المحلي السابقة على Windows (أرشيفية) |

---

## التشغيل السريع للتطوير المحلي

```bash
# 1. إنشاء البيئة وتثبيت الاعتماديات
python3 -m venv .venv
source .venv/bin/activate       # على Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

# 2. إعداد ملف البيئة
cp .env.example .env
# اضبطي MONGODB_URI و SETUP_TOKEN في ملف .env
# للتجربة المحلية على HTTP بدون شهادة:
export ZUM_COOKIE_SECURE=0      # على Windows: set ZUM_COOKIE_SECURE=0

# 3. تشغيل خادم التطوير
python3 run.py
```

ثم افتحي في المتصفح:
- الموقع العام: `http://127.0.0.1:8000/`
- صفحة الإعداد الأولي (لأول مرة فقط): `http://127.0.0.1:8000/admin/setup`
- لوحة التحكم: `http://127.0.0.1:8000/admin/`

---

## بنية المشروع

| المسار | الوصف |
|---|---|
| `index.html` | الموقع العام الأصلي. **لم يتغير بايت واحد منه**؛ يُستخدم قالباً يملؤه الخادم ببيانات القاعدة |
| `images/` | الشعار وصور الموقع الأصلية + فيديو الواجهة `promo-bg.mp4` |
| `admin/` | لوحة التحكم المتوافقة مع MongoDB وحدود رفع 4MB |
| `server/` | خادم Flask: وثيقة `site`، الفهارس الذرية، التجهيز التلقائي، وإدارة الجلسات في MongoDB |
| `app.py` | نقطة الدخول لدوال Vercel Serverless |
| `vercel.json` | تكوين نشر Vercel في منطقة `fra1` القريبة من فرانكفورت |
| `manage.py` | أدوات الطوارئ الإدارية وفحص الجاهزية وإدارة الصور |
| `tests/` | 157 اختباراً آلياً تغطي كافة سيناريوهات الترحيل والتزامن والأمان |

---

## أوامر الإدارة (أدوات طوارئ اختيارية)

> ملاحظة: لا يلزم تشغيل أي أمر من هذه الأوامر لنشر الموقع. القاعدة تتجهز تلقائياً وحساب المديرة يُنشأ من المتصفح عبر `/admin/setup`.

```bash
python3 manage.py check              # فحص الجاهزية والاتصال بـ Atlas والأمان
python3 manage.py status             # عرض حالة البيانات والأعداد
python3 manage.py create-admin       # إنشاء حساب المديرة من الطرفية (بديل عن /admin/setup)
python3 manage.py change-password    # تغيير كلمة مرور المديرة وإنهاء الجلسات
python3 manage.py admin-info         # عرض اسم مستخدم المديرة الحالي
python3 manage.py cleanup-uploads    # حذف الصور المرفوعة غير المستخدمة في أي موضع (--dry-run للمعاينة)
python3 manage.py reseed             # إعادة ضبط بيانات الموقع من seed.js بعد أخذ نسخة احتياطية
```

---

## الأمان باختصار

- **بدون أسرار في الكود:** لا يوجد أي مستخدم أو كلمة مرور أو رابط اتصال حقيقي داخل المستودع.
- **تجهيز أولي آمن:** صفحة `/admin/setup` محمية برمز سري `SETUP_TOKEN` وتقييد محاولات وقفل ذرّي، وتُغلق نهائياً بعد إنشاء الحساب الأول.
- **تزامن CAS ذرّي:** كل حفظ يعتمد على رقم مراجعة `rev`؛ أي تعارض تعديل يُلغى فوراً مع تنبيه بالتعارض (409) دون فقدان البيانات.
- **تخزين الصور في Atlas:** تُفحص الصور وتُعاد كتابتها بـ Pillow وتُخزن في MongoDB (`uploads`) وتُخدم بكاش طويل ووسم ETag وعزل أمني.
