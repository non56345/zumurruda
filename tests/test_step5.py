"""الخطوة 5: لوحة التحكم تعمل على الخادم، لا على localStorage.

اختبار المتصفح الكامل (تسجيل الدخول، تعديل سعر، رفع صورة، التعارض، الجوال) في tests/e2e/e2e_admin.py.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ADMIN_INDEX_TEXT_CHANGES = [
    ('<p>نسخة المرحلة الثانية: واجهة تجريبية بلا قاعدة بيانات.</p>',
     '<p>البيانات محفوظة على الخادم وتظهر في الموقع العام فور الحفظ.</p>'),
    ('<span class="demo-badge">وضع تجريبي</span>', '<span class="demo-badge">متصلة بالخادم</span>'),
    ('<p><b>ملاحظة مهمة:</b> هذه اللوحة بلا تسجيل دخول، والتعديلات تُحفظ في متصفحك فقط (<span dir="ltr">localStorage</span>) '
     'ولا تظهر في الموقع العام. الربط بقاعدة البيانات وتسجيل الدخول الآمن يتمّان في المرحلة الثالثة.</p>',
     '<p><b>ملاحظة:</b> كل تعديل تحفظينه هنا يُكتب في قاعدة بيانات الخادم ويظهر في الموقع العام مباشرة. '
     'يأخذ الخادم نسخة احتياطية تلقائيًا، ويمكنكِ استعادة البيانات الأصلية من «الرئيسية».</p>'),
]


class TestAdminClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (ROOT / "admin" / "app.js").read_text(encoding="utf8")
        cls.html = (ROOT / "admin" / "index.html").read_text(encoding="utf8")

    def test_no_localstorage_persistence(self):
        self.assertNotIn("localStorage.setItem", self.js)
        # الاستخدام الوحيد المسموح: قراءة/حذف بيانات النسخة التجريبية القديمة لنقلها مرة واحدة
        uses = re.findall(r"localStorage\.(\w+)", self.js)
        self.assertTrue(set(uses) <= {"getItem", "removeItem"}, uses)

    def test_uses_server_api_with_csrf(self):
        for needle in ("/api/admin/state", "/api/admin/upload", "/api/admin/reset", "X-CSRF-Token", "'PUT'"):
            self.assertIn(needle, self.js)

    def test_no_data_url_images_saved(self):
        self.assertNotIn("toDataURL", self.js)          # الصور تُرفع للخادم بدل تخزينها نصاً

    def test_demo_notices_removed(self):
        self.assertNotIn("localStorage", self.html)
        self.assertNotIn("وضع تجريبي", self.html)
        for _old, new in ADMIN_INDEX_TEXT_CHANGES:
            self.assertEqual(self.html.count(new), 1)

    def test_no_secrets_in_client(self):
        for f in (ROOT / "admin").glob("*.js"):
            t = f.read_text(encoding="utf8").lower()
            for bad in ("password =", "password:", "secret", "api_key", "apikey"):
                self.assertNotIn(bad, t, f.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
