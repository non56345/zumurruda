"""أوامر إدارة قاعدة البيانات والخادم (MongoDB Atlas).

  python3 manage.py status           عرض أعداد البيانات وحالة التهيئة
  python3 manage.py check            فحص الجاهزية والاتصال قبل النشر
  python3 manage.py create-admin     إنشاء حساب المديرة يدوياً (أداة طوارئ بديلة عن /admin/setup)
  python3 manage.py change-password  تغيير كلمة مرور المديرة (يُنهي كل جلساتها المفتوحة)
  python3 manage.py admin-info       عرض اسم مستخدم المديرة (دون أي كلمة مرور)
  python3 manage.py cleanup-uploads  حذف الصور المرفوعة غير المستخدمة في أي موضع (أضيفي --dry-run للمعاينة)
  python3 manage.py reseed           إعادة ضبط بيانات الموقع إلى seed.js (بعد أخذ لقطة احتياطية)

لا يوجد مستخدم أو كلمة مرور افتراضية. كلمة المرور لا تُمرَّر كوسيط في سطر الأوامر ولا تُطبع.
"""
import getpass
import sys
from pathlib import Path

import load_env

load_env.load()

from pymongo.errors import PyMongoError  # noqa: E402
from server.config import Config  # noqa: E402
from server.db import get_client  # noqa: E402
from server import auth, store, uploads  # noqa: E402
from server.seed_loader import counts, is_seeded, read_seed, seed  # noqa: E402


def _get_db():
    client = get_client()
    return client[Config.MONGODB_DB]


def _ask(prompt, secret=False):
    """إدخال تفاعلي (مخفي للسر)؛ وعند عدم وجود طرفية يقرأ من الإدخال القياسي."""
    if sys.stdin.isatty():
        return getpass.getpass(prompt) if secret else input(prompt)
    return sys.stdin.readline().rstrip("\n")


def _new_password(username):
    pw = _ask("كلمة المرور الجديدة (12 حرفاً على الأقل): ", secret=True)
    if _ask("أعيدي كتابة كلمة المرور: ", secret=True) != pw:
        raise ValueError("كلمتا المرور غير متطابقتين.")
    err = auth.validate_password(pw, username)
    if err:
        raise ValueError(err)
    return pw


def admin_command(cmd, db):
    try:
        if cmd == "create-admin":
            if auth.admin_exists(db):
                raise ValueError("يوجد حساب مدير بالفعل. استخدمي change-password.")
            name, err = auth.validate_username(_ask("اسم المستخدم (أحرف إنجليزية صغيرة وأرقام): "))
            if err:
                raise ValueError(err)
            auth.create_admin(db, name, _new_password(name))
            print(f"تم إنشاء حساب المديرة: {name}")
        elif cmd == "change-password":
            row = db.users.find_one()
            if not row:
                raise ValueError("لا يوجد حساب بعد. استخدمي create-admin أو صفحة /admin/setup.")
            auth.set_password(db, row["_id"], _new_password(row["username"]))
            print(f"تم تغيير كلمة مرور {row['username']} وإنهاء جلساتها المفتوحة.")
        else:  # admin-info
            row = db.users.find_one()
            print("اسم المستخدم:", row["username"] if row else "لا يوجد حساب بعد")
    except ValueError as e:
        print("خطأ:", e, file=sys.stderr)
        return 1
    return 0


def check_command(db):
    problems, notes = [], []
    # 1. الاتصال بمونجو
    try:
        get_client().admin.command("ping")
    except PyMongoError as e:
        problems.append(f"فشل الاتصال بقاعدة MongoDB Atlas: {e}")
        print("مشكلة:", problems[-1])
        return 1

    # 2. وثيقة site
    doc = db.site.find_one({"_id": "site"})
    if not doc:
        problems.append("وثيقة الموقع site غير موجودة (لم تُهيأ القاعدة بعد).")
    else:
        # فحص روابط التواصل الفارغة
        c = doc.get("contact", {})
        empty = [k for k, v in c.items() if not v]
        if empty:
            notes.append("روابط تواصل فارغة (تُضاف من اللوحة): " + "، ".join(empty))
        # فحص الصور
        missing = []
        for im in doc.get("images", {}).values():
            src = im.get("src", "")
            if not src:
                continue
            if src.startswith("uploads/"):
                if not uploads.exists(db, src[len("uploads/"):]):
                    missing.append(src)
            elif not (Config.ROOT / src).exists():
                missing.append(src)
        if missing:
            notes.append("صور غير موجودة (تظهر كـ«الصورة قريبًا»): " + "، ".join(missing))

    # 3. حساب المديرة
    if not auth.admin_exists(db):
        if auth.setup_enabled():
            notes.append("لم يُنشأ حساب مديرة بعد. يمكنكِ إنشاؤه عبر صفحة /admin/setup في المتصفح.")
        else:
            problems.append("لا يوجد حساب مديرة ورمز SETUP_TOKEN غير معرّف.")

    # 4. قالب index.html
    try:
        from server.render import Template
        Template(Config.ROOT / "index.html", read_seed())
    except Exception as e:  # noqa: BLE001
        problems.append(f"قالب index.html: {e}")

    # 5. الكوكيز والأمان
    if not Config.COOKIE_SECURE:
        problems.append("ZUM_COOKIE_SECURE=0: مسموح محلياً فقط، ويجب أن يكون 1 على الإنترنت (HTTPS)")
    if not Config.SECRET_KEY or len(Config.SECRET_KEY) < 32:
        problems.append("SECRET_KEY غير معرّف أو قصير جداً.")

    for n in notes:
        print("ملاحظة:", n)
    for p in problems:
        print("مشكلة:", p)
    print("جاهز للنشر." if not problems else f"غير جاهز: {len(problems)} مشكلة.")
    return 1 if problems else 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"

    if cmd in ("backup", "list-backups", "restore"):
        print(
            "تنبيه: النسخ الاحتياطي في بيئة MongoDB Atlas يتم تلقائياً ومباشرة عبر لوحة Atlas Backups.\n"
            "للمزيد راجعي توثيق النشر في docs/DEPLOY.md.",
            file=sys.stderr,
        )
        return 1

    try:
        db = _get_db()
    except Exception as e:
        print(f"تعذّر الاتصال بقاعدة البيانات: {e}", file=sys.stderr)
        return 1

    if cmd == "status":
        print("seeded:", is_seeded(db), counts(db))
        return 0
    if cmd == "check":
        return check_command(db)
    if cmd in ("create-admin", "change-password", "admin-info"):
        return admin_command(cmd, db)
    if cmd == "cleanup-uploads":
        removed = uploads.cleanup(db, store.referenced_uploads(db), dry_run="--dry-run" in argv)
        print(("سيُحذف" if "--dry-run" in argv else "حُذف"), len(removed), "صورة غير مستخدمة من uploads")
        return 0
    if cmd == "reseed":
        ans = _ask("تحذير: هذا الأمر سيعيد كتابة بيانات الموقع من seed.js. للتأكيد اكتبي «نعم»: ")
        if ans.strip() != "نعم":
            print("أُلغيت العملية.")
            return 0
        bak_id = store.snapshot_site(db, "reseed")
        print("تم أخذ نسخة احتياطية سريعة بالمعرّف:", bak_id)
        db.site.delete_one({"_id": "site"})
        seed(db)
        print("تمت إعادة ضبط البيانات الأولية بنجاح.")
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
