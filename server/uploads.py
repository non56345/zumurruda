"""رفع الصور إلى الخادم (الخطوة 4).

- يُقبل JPG وPNG وWEBP وGIF فقط، ويُتحقق من المحتوى الفعلي بـ Pillow لا من الامتداد.
- تُعاد كتابة كل صورة من جديد (تصغير + إزالة بيانات EXIF/الموقع) قبل الحفظ.
- الاسم عشوائي يولّده الخادم، والحفظ في مجلد uploads/ فقط؛ لا يُكتب شيء في images/ الأصلية.
"""
import io
import secrets
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 50_000_000          # حماية من «قنابل الضغط»
ALLOWED = {"JPEG", "PNG", "WEBP", "GIF", "MPO"}
MAX_BYTES = 10 * 1024 * 1024
NAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789.-_")


class UploadError(ValueError):
    pass


def save_image(data: bytes, folder: Path, *, kind="image"):
    if not data:
        raise UploadError("لم يتم اختيار ملف.")
    if len(data) > MAX_BYTES:
        raise UploadError("حجم الصورة أكبر من 10 ميغابايت.")
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
    folder.mkdir(parents=True, exist_ok=True)
    if kind == "logo" or has_alpha:
        im = im.convert("RGBA")
        ext, opts = "png", {"format": "PNG", "optimize": True}
    else:
        im = im.convert("RGB")
        ext, opts = "jpg", {"format": "JPEG", "quality": 85, "optimize": True, "progressive": True}
    name = f"{secrets.token_hex(10)}.{ext}"
    im.save(folder / name, **opts)                    # بلا EXIF
    return name, im.size


def exists(folder: Path, name: str) -> bool:
    if not name or any(c not in NAME_OK for c in name) or name.startswith("."):
        return False
    return (folder / name).is_file()


def cleanup(folder: Path, referenced: set, dry_run=False):
    """يحذف الملفات المرفوعة غير المستخدمة في أي موضع."""
    removed = []
    if not folder.exists():
        return removed
    for p in folder.iterdir():
        if p.is_file() and p.name not in referenced and not p.name.startswith("."):
            removed.append(p.name)
            if not dry_run:
                p.unlink()
    return removed
