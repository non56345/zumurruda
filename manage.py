"""أوامر إدارة قاعدة البيانات والخادم.

  python3 manage.py init-db     إنشاء الجداول واستيراد البيانات الأولية (إن كانت القاعدة فارغة)
  python3 manage.py status      عرض أعداد البيانات
  python3 manage.py reseed      نسخة احتياطية مؤرخة ثم إعادة بناء القاعدة من seed.js
  python3 manage.py create-admin     إنشاء حساب المديرة (مرة واحدة): يطلب اسم المستخدم وكلمة المرور بإدخال مخفي
  python3 manage.py change-password  تغيير كلمة مرور المديرة (يُنهي كل جلساتها المفتوحة)
  python3 manage.py admin-info       عرض اسم مستخدم المديرة (دون أي كلمة مرور)
  python3 manage.py backup           نسخة احتياطية فورية في data/backups/
  python3 manage.py list-backups     عرض النسخ الاحتياطية
  python3 manage.py restore <ملف>    استرجاع نسخة احتياطية (يأخذ نسخة من الحالية أولاً). أوقفي الخادم قبلها.
  python3 manage.py cleanup-uploads  حذف الصور المرفوعة غير المستخدمة (أضيفي --dry-run للمعاينة)
  python3 manage.py check            فحص الجاهزية قبل النشر

لا يوجد مستخدم أو كلمة مرور افتراضية. كلمة المرور لا تُمرَّر كوسيط في سطر الأوامر ولا تُطبع.
"""
import getpass
import shutil
import sqlite3
import sys
from pathlib import Path

import load_env

load_env.load()

from server.config import Config  # noqa: E402
from server.db import connect, init_schema  # noqa: E402
from server import auth, store, uploads  # noqa: E402
from server.seed_loader import backup_file, counts, is_seeded, read_seed, seed  # noqa: E402


def _ask(prompt, secret=False):
    """إدخال تفاعلي (مخفي للسر)؛ وعند عدم وجود طرفية يقرأ من الإدخال القياسي (للأتمتة الآمنة)."""
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


def admin_command(cmd, conn):
    try:
        if cmd == "create-admin":
            if auth.admin_exists(conn):
                raise ValueError("يوجد حساب مدير بالفعل. استخدمي change-password.")
            name, err = auth.validate_username(_ask("اسم المستخدم (أحرف إنجليزية صغيرة وأرقام): "))
            if err:
                raise ValueError(err)
            auth.create_admin(conn, name, _new_password(name))
            print(f"تم إنشاء حساب المديرة: {name}")
        elif cmd == "change-password":
            row = conn.execute("SELECT id, username FROM users LIMIT 1").fetchone()
            if not row:
                raise ValueError("لا يوجد حساب بعد. استخدمي create-admin.")
            auth.set_password(conn, row["id"], _new_password(row["username"]))
            print(f"تم تغيير كلمة مرور {row['username']} وإنهاء جلساتها المفتوحة.")
        else:  # admin-info
            row = conn.execute("SELECT username FROM users LIMIT 1").fetchone()
            print("اسم المستخدم:", row["username"] if row else "لا يوجد حساب بعد")
    except ValueError as e:
        print("خطأ:", e, file=sys.stderr)
        return 1
    return 0


def ops_command(cmd, argv, path):
    if cmd == "backup":
        if not Path(path).exists():
            print("لا توجد قاعدة بيانات بعد.", file=sys.stderr)
            return 1
        print("تمت النسخة:", store.make_backup(path, "manual"))
        return 0
    if cmd == "list-backups":
        d = store.backup_dir(path)
        files = sorted(d.glob("zumurrud-*.db")) if d.exists() else []
        for f in files:
            print(f.name, f"{f.stat().st_size // 1024} KB")
        print(f"العدد: {len(files)} — المجلد: {d}")
        return 0
    if cmd == "restore":
        if len(argv) < 3:
            print("حددي ملف النسخة: python manage.py restore data/backups/<اسم الملف>", file=sys.stderr)
            return 1
        src = Path(argv[2])
        if not src.is_file():
            src = store.backup_dir(path) / argv[2]
        try:
            ok = sqlite3.connect(f"file:{src}?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error:
            ok = "not a database"
        if ok != "ok":
            print("الملف ليس نسخة صالحة:", ok, file=sys.stderr)
            return 1
        if Path(path).exists():
            print("نسخة من الحالية قبل الاسترجاع:", store.make_backup(path, "before-restore"))
        for suffix in ("-wal", "-shm"):
            Path(path + suffix).unlink(missing_ok=True)
        shutil.copy2(src, path)
        print("تم الاسترجاع من:", src)
        return 0
    if cmd == "cleanup-uploads":
        conn = connect(path)
        try:
            init_schema(conn)
            removed = uploads.cleanup(Config.UPLOADS, store.referenced_uploads(conn), dry_run="--dry-run" in argv)
        finally:
            conn.close()
        print(("سيُحذف" if "--dry-run" in argv else "حُذف"), len(removed), "ملفاً غير مستخدم")
        return 0
    # check
    problems, notes = [], []
    conn = connect(path)
    try:
        init_schema(conn)
        seed(conn)
        if not auth.admin_exists(conn):
            problems.append("لا يوجد حساب مديرة: python manage.py create-admin")
        c = conn.execute("SELECT key, value FROM contact").fetchall()
        empty = [r["key"] for r in c if not r["value"]]
        if empty:
            notes.append("روابط تواصل فارغة (تُضاف من اللوحة): " + "، ".join(empty))
        missing = [r["src"] for r in conn.execute("SELECT src FROM images WHERE src != ''")
                   if not (Config.ROOT / r["src"]).exists() and not (r["src"].startswith("uploads/")
                   and (Config.UPLOADS / r["src"][8:]).exists())]
        if missing:
            notes.append("صور غير موجودة (تظهر كـ«الصورة قريبًا»): " + "، ".join(missing))
    finally:
        conn.close()
    try:
        from server.render import Template
        Template(Config.ROOT / "index.html", read_seed())
    except Exception as e:  # noqa: BLE001
        problems.append(f"قالب index.html: {e}")
    if not Config.COOKIE_SECURE:
        problems.append("ZUM_COOKIE_SECURE=0: مسموح محلياً فقط، ويجب أن يكون 1 على الإنترنت (HTTPS)")
    try:
        Config.UPLOADS.mkdir(parents=True, exist_ok=True)
        t = Config.UPLOADS / ".write-test"
        t.write_text("x")
        t.unlink()
    except OSError as e:
        problems.append(f"مجلد الصور المرفوعة غير قابل للكتابة: {e}")
    for n in notes:
        print("ملاحظة:", n)
    for p in problems:
        print("مشكلة:", p)
    print("جاهز للنشر." if not problems else f"غير جاهز: {len(problems)} مشكلة.")
    return 1 if problems else 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    path = Config.DATABASE
    if cmd in ("backup", "list-backups", "restore", "cleanup-uploads", "check"):
        return ops_command(cmd, argv, path)
    if cmd == "reseed":
        bak = backup_file(path)
        print("نسخة احتياطية:", bak or "لا توجد قاعدة سابقة")
        for suffix in ("", "-wal", "-shm"):
            Path(path + suffix).unlink(missing_ok=True)
        cmd = "init-db"
    conn = connect(path)
    try:
        if cmd == "init-db":
            init_schema(conn)
            print("تم الاستيراد." if seed(conn) else "القاعدة مستوردة مسبقاً؛ لم يتغير شيء.")
        elif cmd in ("create-admin", "change-password", "admin-info"):
            init_schema(conn)
            return admin_command(cmd, conn)
        elif cmd != "status":
            print(__doc__)
            return 1
        init_schema(conn)
        print("seeded:", is_seeded(conn), counts(conn))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
