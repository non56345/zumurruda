"""اختبارات متطلبات الترحيل إلى MongoDB Atlas وVercel (القسم 8.3 من الخطة)."""
import io
import re
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from helpers import USER, make_app  # noqa: E402
from server.config import Config  # noqa: E402
from server import auth, seed_loader, store, uploads  # noqa: E402


def _make_image_bytes(fmt="JPEG", size=(100, 100), color=(200, 100, 50)):
    buf = io.BytesIO()
    im = Image.new("RGB", size, color)
    im.save(buf, format=fmt)
    return buf.getvalue()


def _form_csrf(resp):
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1) if match else ""


class TestAutoInit(unittest.TestCase):
    def test_auto_init_on_empty_db(self):
        # قاعدة فارغة
        app = make_app()
        db = app.mongo_client[app.config["MONGODB_DB"]]
        self.assertEqual(db.site.count_documents({}), 0)

        c = app.test_client()
        r = c.get("/api/health")
        self.assertEqual(r.status_code, 200)

        # التجهيز أنشأ الوثيقة والفهارس
        self.assertEqual(db.site.count_documents({}), 1)
        doc = db.site.find_one({"_id": "site"})
        self.assertIsNotNone(doc)
        self.assertIn("content", doc)
        self.assertEqual(doc.get("rev"), 0)

        # تعديل حقل للتأكد من عدم إعادة الـ seed في الطلب التالي
        db.site.update_one({"_id": "site"}, {"$set": {"content.site_name": "معدل خصيصاً"}})
        r2 = c.get("/")
        self.assertEqual(r2.status_code, 200)
        doc2 = db.site.find_one({"_id": "site"})
        self.assertEqual(doc2["content"]["site_name"], "معدل خصيصاً")

    def test_concurrent_seed_safety(self):
        app = make_app()
        db = app.mongo_client[app.config["MONGODB_DB"]]
        # استدعاءان متتاليان للـ seed
        seed_loader.seed(db)
        seed_loader.seed(db)
        self.assertEqual(db.site.count_documents({}), 1)


class TestAdminSetup(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        seed_loader.seed(self.app.mongo_client[self.app.config["MONGODB_DB"]])
        self.db = self.app.mongo_client[self.app.config["MONGODB_DB"]]
        self.c = self.app.test_client()
        self.token = "A" * 32  # valid token len >= 24

    def test_setup_disabled_without_token_or_short_token(self):
        with mock.patch.dict(self.app.config, {"SETUP_TOKEN": ""}):
            self.assertEqual(self.c.get("/admin/setup").status_code, 404)
            self.assertEqual(self.c.post("/admin/setup").status_code, 404)

        with mock.patch.dict(self.app.config, {"SETUP_TOKEN": "too-short-123"}):
            self.assertEqual(self.c.get("/admin/setup").status_code, 404)

    def test_setup_flow_and_rate_limit(self):
        with mock.patch.dict(self.app.config, {"SETUP_TOKEN": self.token}):
            # صفحة الإعداد متاحة
            r = self.c.get("/admin/setup")
            self.assertEqual(r.status_code, 200)
            csrf = _form_csrf(r)

            # رمز خاطئ
            r_bad = self.c.post(
                "/admin/setup",
                data={
                    "setup_token": "wrong-token-wrong-token-1234",
                    "username": "superadmin",
                    "password": "StrongPassword123!",
                    "confirm": "StrongPassword123!",
                    "csrf_token": csrf,
                },
            )
            self.assertIn("رمز الإعداد غير صحيح", r_bad.get_data(as_text=True))

            # تجربة خاطئة متكررة لاختبار Rate Limiting
            for _ in range(4):
                self.c.post(
                    "/admin/setup",
                    data={
                        "setup_token": "wrong-token-wrong-token-1234",
                        "username": "superadmin",
                        "password": "StrongPassword123!",
                        "confirm": "StrongPassword123!",
                        "csrf_token": csrf,
                    },
                )
            # المحاولة السادسة محظورة
            r_blocked = self.c.post(
                "/admin/setup",
                data={
                    "setup_token": self.token,
                    "username": "superadmin",
                    "password": "StrongPassword123!",
                    "confirm": "StrongPassword123!",
                    "csrf_token": csrf,
                },
            )
            self.assertIn("محاولات كثيرة", r_blocked.get_data(as_text=True))

    def test_setup_weak_password_rejected(self):
        with mock.patch.dict(self.app.config, {"SETUP_TOKEN": self.token}):
            r = self.c.get("/admin/setup")
            csrf = _form_csrf(r)
            r_weak = self.c.post(
                "/admin/setup",
                data={
                    "setup_token": self.token,
                    "username": "admin123",
                    "password": "short",
                    "confirm": "short",
                    "csrf_token": csrf,
                },
            )
            self.assertIn("12", r_weak.get_data(as_text=True))
            self.assertEqual(self.db.users.count_documents({}), 0)

    def test_setup_success_once_then_404(self):
        with mock.patch.dict(self.app.config, {"SETUP_TOKEN": self.token}):
            r = self.c.get("/admin/setup")
            csrf = _form_csrf(r)
            r_ok = self.c.post(
                "/admin/setup",
                data={
                    "setup_token": self.token,
                    "username": "masteradmin",
                    "password": "ValidStrongPassword123!",
                    "confirm": "ValidStrongPassword123!",
                    "csrf_token": csrf,
                },
                follow_redirects=False,
            )
            self.assertEqual(r_ok.status_code, 302)
            self.assertEqual(self.db.users.count_documents({}), 1)

            # بعد نجاح الإنشاء، أي طلب لاحق يرجع 404
            c2 = self.app.test_client()
            self.assertEqual(c2.get("/admin/setup").status_code, 404)
            self.assertEqual(c2.post("/admin/setup").status_code, 404)

    def test_admin_lock_race(self):
        # وجود admin_lock في meta يمنع الإنشاء حتى لو لم يكن هناك مستخدم بعد
        self.db.meta.insert_one({"_id": "admin_lock", "at": time.time()})
        with self.assertRaises(ValueError):
            auth.create_admin(self.db, "admin1", "Password123456!")


class TestOptimisticLockingCAS(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.db = self.app.mongo_client[self.app.config["MONGODB_DB"]]
        seed_loader.seed(self.db)

    def test_cas_concurrency(self):
        rev = store.get_rev(self.db)
        state1 = store.full_state(self.db)
        state2 = store.full_state(self.db)

        # التعديل الأول بنجاح
        res1 = store.replace_state(self.db, state1, "admin", "تعديل 1", base_rev=rev)
        self.assertEqual(res1, rev + 1)

        # التعديل الثاني بنفس base_rev القديم يجب أن يفشل بتعارض ConflictError
        with self.assertRaises(store.ConflictError) as ctx:
            store.replace_state(self.db, state2, "admin", "تعديل 2 متزامن", base_rev=rev)
        self.assertIn("نافذة أخرى", str(ctx.exception))


class TestUploads(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.db = self.app.mongo_client[self.app.config["MONGODB_DB"]]
        self.c = self.app.test_client()

    def test_upload_save_and_serve(self):
        img_bytes = _make_image_bytes()
        name, size = uploads.save_image(img_bytes, self.db, kind="photo")
        self.assertTrue(name.endswith(".jpg"))

        # الوثيقة مخزنة في uploads
        doc = self.db.uploads.find_one({"_id": name})
        self.assertIsNotNone(doc)
        self.assertEqual(doc["content_type"], "image/jpeg")

        # مسار التخديم
        resp = self.c.get(f"/uploads/{name}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "image/jpeg")
        self.assertIn("public, max-age=31536000, immutable", resp.headers.get("Cache-Control", ""))
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("ETag"), name)

    def test_upload_reject_over_4mb(self):
        big_data = b"X" * (4 * 1024 * 1024 + 10)
        with self.assertRaises(ValueError) as ctx:
            uploads.save_image(big_data, self.db, kind="photo")
        self.assertIn("4 ميغابايت", str(ctx.exception))


class TestGiftOrders(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.c = self.app.test_client()

    def test_sequential_counter_and_rate_limit(self):
        order_input = {
            "to": "فاطمة",
            "from": "مريم",
            "gift": "جلسة عناية",
            "message": "ألف مبارك",
            "phone": "0912345678",
        }

        # طلب 1
        r1 = self.c.post("/api/gift-orders", json=order_input)
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r1.get_json()["ref"], 1)

        # طلب 2
        r2 = self.c.post("/api/gift-orders", json=order_input)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r2.get_json()["ref"], 2)

        # طلب 3
        r3 = self.c.post("/api/gift-orders", json=order_input)
        self.assertEqual(r3.status_code, 201)
        self.assertEqual(r3.get_json()["ref"], 3)

        # تجاوز الحد المسموح به (GIFT_RATE_LIMIT = 5)
        self.c.post("/api/gift-orders", json=order_input)
        self.c.post("/api/gift-orders", json=order_input)

        r_blocked = self.c.post("/api/gift-orders", json=order_input)
        self.assertEqual(r_blocked.status_code, 429)
        self.assertEqual(r_blocked.get_json()["error"], "rate_limited")


class TestProxyHops(unittest.TestCase):
    def test_proxy_hops_remote_addr(self):
        # مع ZUM_PROXY_HOPS=1 يتم أخذ IP الحقيقي للزائر
        app = make_app(PROXY_HOPS=1)
        c = app.test_client()

        @app.route("/test-ip")
        def _test_ip():
            from flask import request
            return request.remote_addr or ""

        r = c.get("/test-ip", headers={"X-Forwarded-For": "203.0.113.195"})
        self.assertEqual(r.get_data(as_text=True), "203.0.113.195")


if __name__ == "__main__":
    unittest.main(verbosity=2)
