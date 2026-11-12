# النشر الفعلي على الإنترنت

الموقع تطبيق Python (Flask) بقاعدة SQLite، لذلك يحتاج استضافة تشغّل Python.
الاستضافة التي تقبل ملفات HTML فقط لا تكفي. يوجد خياران:

- **أ) خادم VPS بنظام Ubuntu:** الأفضل والأكثر تحكماً، وتكلفته عادة 5 دولارات شهرياً أو أكثر.
- **ب) استضافة مشتركة فيها cPanel مع خاصية «Setup Python App».**

في الحالتين يلزم:

- **نطاق (دومين)** موجّه إلى الخادم.
- **HTTPS** إلزامي، لأن كوكي الجلسة لا يُرسل إلا عبره.

---

## قبل النشر (على جهازكِ)

1. شغّلي الاختبارات: `windows\run-tests.bat`. يجب أن تنتهي بكلمة `OK`.
2. إن كانت عندكِ بيانات عدّلتِها محلياً وتريدين نقلها، فلديكِ طريقتان:
   - انسخي `data\zumurrud.db` ومجلد `uploads\` إلى الخادم.
   - أو صدّري نسخة JSON من اللوحة («الرئيسية» ← «تصدير نسخة JSON»)، ثم استورديها في لوحة الخادم.

---

## أ) خادم Ubuntu + nginx + HTTPS

```bash
# 1. المتطلبات
sudo apt update && sudo apt install -y python3 python3-venv nginx certbot python3-certbot-nginx
sudo adduser --system --group --home /srv/zumurrud zumurrud

# 2. رفع المشروع (من جهازكِ: scp أو WinSCP أو git) إلى /srv/zumurrud ثم:
cd /srv/zumurrud
sudo -u zumurrud python3 -m venv .venv
sudo -u zumurrud .venv/bin/pip install -r requirements.txt

# 3. الإعدادات
sudo -u zumurrud cp .env.example .env
sudo -u zumurrud nano .env        # اضبطي: ZUM_COOKIE_SECURE=1  و  ZUM_PROXY_HOPS=1

# 4. القاعدة والحساب
sudo -u zumurrud .venv/bin/python manage.py init-db
sudo -u zumurrud .venv/bin/python manage.py create-admin
sudo -u zumurrud .venv/bin/python manage.py check     # يجب أن تكون النتيجة: جاهز للنشر.

# 5. الخدمة الدائمة (تعمل تلقائياً بعد إعادة التشغيل)
sudo cp deploy/zumurrud.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now zumurrud
sudo systemctl status zumurrud

# 6. nginx + الشهادة
sudo cp deploy/nginx-zumurrud.conf /etc/nginx/sites-available/zumurrud
sudo nano /etc/nginx/sites-available/zumurrud     # استبدلي example.ly بنطاقكِ
sudo ln -s /etc/nginx/sites-available/zumurrud /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d نطاقك.ly -d www.نطاقك.ly

# 7. نسخ احتياطي يومي
sudo -u zumurrud crontab -e       # الصقي السطر الموجود في deploy/backup-cron.txt
```

**تحديث الموقع لاحقاً:**

1. ارفعي الملفات الجديدة، ولا تستبدلي `data/` ولا `uploads/` ولا `.env`.
2. نفّذي:
   ```bash
   sudo systemctl restart zumurrud
   ```

---

## ب) استضافة cPanel («Setup Python App»)

1. في cPanel افتحي **Setup Python App** ← **Create Application**:
   - Python version: 3.11 أو أحدث.
   - Application root: `zumurrud`
   - Application URL: النطاق الرئيسي.
   - Application startup file: `passenger_wsgi.py`
   - Application Entry point: `application`
2. ارفعي ملفات المشروع إلى مجلد `zumurrud` من **File Manager**: ارفعي ملف ZIP ثم فكّيه.
3. في صفحة التطبيق أضيفي متغيرات البيئة:
   - `ZUM_COOKIE_SECURE=1`
   - `ZUM_PROXY_HOPS=1`
4. اضغطي **Run Pip Install** واختاري `requirements.txt`.
5. من **Terminal** في cPanel، أو بالأمر الظاهر أعلى صفحة التطبيق لتفعيل البيئة:
   ```
   cd ~/zumurrud
   python manage.py init-db
   python manage.py create-admin
   python manage.py check
   ```
6. فعّلي **SSL/TLS Status ← AutoSSL** للنطاق، ثم اضغطي **Restart** للتطبيق.

> بعض الاستضافات المشتركة لا تسمح بعمليات الكتابة الكثيرة أو تحذف الملفات المؤقتة. لذلك تأكدي أن مجلدي `data/` و`uploads/` داخل مجلد التطبيق وقابلان للكتابة، وأن `python manage.py check` يقول «جاهز للنشر».

---

## بعد النشر — قائمة تحقق

- [ ] `https://نطاقك/` يفتح الموقع، والفيديو يعمل في الواجهة.
- [ ] `https://نطاقك/admin/` يطلب تسجيل الدخول، والدخول يعمل.
- [ ] عدّلي سعراً من اللوحة وتأكدي أنه ظهر في الموقع، ثم أرجعيه.
- [ ] أضيفي من «محتوى الموقع ← بيانات التواصل» رابط فيسبوك ورقم واتساب ورابط الخريطة.
- [ ] جرّبي زر «استفسري» وزر واتساب العائم من الجوال.
- [ ] `http://نطاقك` (بدون s) يحوّل تلقائياً إلى https.
- [ ] نفّذي `python manage.py backup` مرة، وتأكدي من ظهور الملف في `data/backups/`.
- [ ] انسخي `data/backups/` و`uploads/` إلى مكان خارج الخادم دورياً (أسبوعياً على الأقل).

## الإعدادات (ملف .env)

| المتغير | الافتراضي | الوصف |
|---|---|---|
| `ZUM_HOST` / `ZUM_PORT` | `127.0.0.1` / `8000` | عنوان ومنفذ الخادم |
| `ZUM_DB` | `data/zumurrud.db` | مسار القاعدة |
| `ZUM_UPLOADS` | `uploads/` | مجلد الصور المرفوعة |
| `ZUM_COOKIE_SECURE` | `1` | يجب أن يبقى 1 على الإنترنت |
| `ZUM_PROXY_HOPS` | `0` | 1 خلف nginx أو cPanel، ليُقرأ عنوان IP الحقيقي في تقييد المحاولات |
| `ZUM_SESSION_IDLE` / `ZUM_SESSION_MAX` | `1800` / `28800` | خمول الجلسة وحدها الأقصى بالثواني |
| `ZUM_BACKUP_INTERVAL` | `21600` | الفترة بين النسخ التلقائية عند الحفظ |
| `ZUM_THREADS` | `8` | عدد خيوط waitress |
