"""رفع الصور وحفظها في MongoDB (مجموعة uploads).

- يُقبل JPG وPNG وWEBP وGIF فقط، ويُتحقق من المحتوى الفعلي بـ Pillow لا من الامتداد.
- تُعاد كتابة كل صورة من جديد (تصغير + إزالة بيانات EXIF/الموقع) قبل الحفظ.
- الاسم عشوائي يولّده الخادم، والحفظ في MongoDB فقط (حتى 4MB).
"""
import io
import secrets
import time

from bson.binary import Binary
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 50_000_000          # حماية من «قنابل الضغط»
ALLOWED = {"JPEG", "PNG", "WEBP", "GIF", "MPO"}
MAX_BYTES = 4 * 1024 * 1024                  # 4 ميغابايت (حد Vercel Functions)
NAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789.-_")


class UploadError(ValueError):
    pass


def save_image(data: bytes, db, *, kind="image"):
    if not data:
        raise UploadError("لم يتم اختيار ملف.")
    if len(data) > MAX_BYTES:
        raise UploadError("حجم الصورة أكبر من 4 ميغابايت.")
    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format
        im.verify()                                   # يكشف الملفات التالفة
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise UploadError("الملف ليس صورة صالحة. اختاري صورة بصيغة JPG أو PNG أو WEBP.")
    if fmt not in ALLOWED:
        raise UploadError("نوع الملف غير مدعوم. اختاري صورة بصيغة JPG أو PNG أو WEBP.")
    im = ImageOps.exif_transpose(im)                  # تصحيح اتجاه صور الجوال
    max_side = 700 if kind == "logo" else 1600
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)

    buf = io.BytesIO()
    if kind == "logo" or has_alpha:
        im = im.convert("RGBA")
        ext, opts = "png", {"format": "PNG", "optimize": True}
        content_type = "image/png"
    else:
        im = im.convert("RGB")
        ext, opts = "jpg", {"format": "JPEG", "quality": 85, "optimize": True, "progressive": True}
        content_type = "image/jpeg"

    im.save(buf, **opts)                    # بلا EXIF
    bytes_data = buf.getvalue()
    name = f"{secrets.token_hex(10)}.{ext}"

    db.uploads.insert_one({
        "_id": name,
        "data": Binary(bytes_data),
        "content_type": content_type,
        "size": len(bytes_data),
        "width": im.size[0],
        "height": im.size[1],
        "created_at": time.time(),
    })
    return name, im.size


def exists(db, name: str) -> bool:
    if not name or any(c not in NAME_OK for c in name) or name.startswith("."):
        return False
    return db.uploads.count_documents({"_id": name}, limit=1) > 0


def cleanup(db, referenced: set, dry_run=False):
    """يحذف وثائق الصور المرفوعة غير المستخدمة في أي موضع."""
    docs = list(db.uploads.find({}, {"_id": 1}))
    removed = [doc["_id"] for doc in docs if doc["_id"] not in referenced and not doc["_id"].startswith(".")]
    if not dry_run and removed:
        db.uploads.delete_many({"_id": {"$in": removed}})
    return removed
