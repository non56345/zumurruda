"""بطاقة الإهداء: الطلب العام، الحماية، الإدارة، والتحقق على الخادم."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from helpers import add_admin, csrf_of, login, make_app  # noqa: E402

GOOD = {"to": "مريم", "from": "سارة", "gift": "حمام مغربي VIP", "message": "كل عام وأنتِ بخير", "phone": "0912345678"}
H = {"Origin": "https://localhost"}


class GiftBase(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        add_admin(self.app)
        self.c = self.app.test_client()

    def post(self, body, headers=None, client=None):
        return (client or self.c).post("/api/gift-orders", json=body, headers=headers or {})

    def admin(self):
        c = self.app.test_client()
        login(c)
        return c, {"X-CSRF-Token": csrf_of(c)}


class TestPublic(GiftBase):
    def test_create_order_without_login(self):
        r = self.post(GOOD)
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.get_json()["ok"])

    def test_required_fields_and_messages(self):
        for f in ("to", "from", "gift", "phone"):
            r = self.post({**GOOD, f: " "})
            self.assertEqual(r.status_code, 400, f)
            self.assertEqual(r.get_json()["field"], f)
        self.assertEqual(self.post({**GOOD, "phone": "12"}).status_code, 400)
        self.assertEqual(self.post({**GOOD, "phone": "abc12345678"}).status_code, 400)
        self.assertEqual(self.post({**GOOD, "to": "x" * 23}).status_code, 400)
        self.assertEqual(self.post({**GOOD, "message": "x" * 121}).status_code, 400)
        self.assertEqual(self.post({**GOOD, "message": ""}).status_code, 201)
        self.assertEqual(self.post([1, 2]).status_code, 400)

    def test_foreign_origin_rejected(self):
        self.assertEqual(self.post(GOOD, {"Origin": "https://evil.example"}).status_code, 403)

    def test_honeypot_saves_nothing(self):
        self.assertEqual(self.post({**GOOD, "website": "http://spam"}).status_code, 201)
        c, h = self.admin()
        self.assertEqual(c.get("/api/admin/gift-orders").get_json()["orders"], [])

    def test_rate_limit(self):
        codes = [self.post(GOOD).status_code for _ in range(7)]
        self.assertEqual(codes[:5], [201] * 5)
        self.assertEqual(codes[5], 429)

    def test_html_is_stored_as_text(self):
        self.post({**GOOD, "to": "<b>x</b>"})
        c, _ = self.admin()
        self.assertEqual(c.get("/api/admin/gift-orders").get_json()["orders"][0]["to"], "<b>x</b>")   # الواجهة تُهرِّبه عند العرض

    def test_only_one_public_write_endpoint(self):
        # لا يزال كل شيء آخر تحت /api مقفلاً: لا يمكن للزائر تعديل بطاقة أو حالة
        self.assertEqual(self.c.put("/api/admin/gift-orders/1", json={"status": "ready"}, headers=H).status_code, 401)
        self.assertEqual(self.c.get("/api/admin/gift-orders").status_code, 401)
        self.assertEqual(self.c.get("/api/admin/gift-orders/1").status_code, 401)
        self.assertEqual(self.c.put("/api/admin/gift-card-layout", json={}, headers=H).status_code, 401)
        self.assertIn(self.c.post("/api/services", json={}, headers=H).status_code, (401, 403))


class TestAdmin(GiftBase):
    def test_list_open_prepare_and_persist(self):
        self.post(GOOD)
        c, h = self.admin()
        lst = c.get("/api/admin/gift-orders").get_json()
        self.assertEqual(lst["counts"]["new"], 1)
        oid = lst["orders"][0]["id"]
        d = c.get(f"/api/admin/gift-orders/{oid}").get_json()
        self.assertEqual(d["order"]["card"]["to"]["text"], "مريم")
        self.assertEqual(d["order"]["card"]["message"]["text"], "كل عام وأنتِ بخير")
        self.assertEqual(d["order"]["phone"], "0912345678")
        card = {k: {k2: v2 for k2, v2 in v.items()} for k, v in d["order"]["card"].items()}
        card["to"].update(text="مريم أحمد", x=0.7, y=0.41, size=33)
        r = c.put(f"/api/admin/gift-orders/{oid}", json={"card": card}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["order"]["status"], "preparing")
        again = c.get(f"/api/admin/gift-orders/{oid}").get_json()["order"]
        self.assertEqual(again["card"]["to"]["text"], "مريم أحمد")
        self.assertEqual((again["card"]["to"]["x"], again["card"]["to"]["size"]), (0.7, 33))
        self.assertTrue(again["saved"])
        self.assertEqual(c.put(f"/api/admin/gift-orders/{oid}", json={"status": "ready"}, headers=h).get_json()["order"]["status"], "ready")

    def test_write_needs_csrf(self):
        self.post(GOOD)
        c, _ = self.admin()
        self.assertEqual(c.put("/api/admin/gift-orders/1", json={"status": "ready"}, headers=H).status_code, 403)

    def test_invalid_card_rejected(self):
        self.post(GOOD)
        c, h = self.admin()
        card = c.get("/api/admin/gift-orders/1").get_json()["order"]["card"]
        for mut in ({"x": 5}, {"size": 1}, {"color": "red"}, {"font": "Comic"}, {"align": "up"}, {"weight": 1000}, {"size": "9"}):
            bad = json.loads(json.dumps(card))
            bad["to"].update(mut)
            self.assertEqual(c.put("/api/admin/gift-orders/1", json={"card": bad}, headers=h).status_code, 400, mut)
        self.assertEqual(c.put("/api/admin/gift-orders/1", json={"status": "zzz"}, headers=h).status_code, 400)
        self.assertEqual(c.put("/api/admin/gift-orders/99", json={"status": "ready"}, headers=h).status_code, 404)

    def test_default_layout(self):
        self.post(GOOD)
        c, h = self.admin()
        d = c.get("/api/admin/gift-orders/1").get_json()
        lay = {k: {kk: vv for kk, vv in v.items() if kk != "text"} for k, v in d["order"]["card"].items()}
        lay["from"]["x"] = 0.6
        self.assertEqual(c.put("/api/admin/gift-card-layout", json={"layout": lay}, headers=h).status_code, 200)
        self.post({**GOOD, "to": "ثانية"})
        new = c.get("/api/admin/gift-orders/2").get_json()["order"]["card"]
        self.assertEqual(new["from"]["x"], 0.6)
        self.assertEqual(new["to"]["text"], "ثانية")


class TestIsolation(GiftBase):
    def test_existing_data_untouched(self):
        self.c.get("/api/health")
        from server.seed_loader import counts
        db = self.app.mongo_client[self.app.config["MONGODB_DB"]]
        self.assertEqual(counts(db)["price_items"], 55)
        self.assertEqual(db.gift_orders.count_documents({}), 0)

    def test_card_image_unchanged_and_no_overlay(self):
        import hashlib
        html = (ROOT / "index.html").read_text(encoding="utf8")
        self.assertIn('id="gcard" role="img"', html)
        self.assertNotIn('id="gc-to"', html)
        self.assertEqual(hashlib.sha256((ROOT / "images" / "zumurruda_gift_card_page_1.png").read_bytes()).hexdigest(),
                         "0bfd31a7a3be5d785cbb76816fac2bcf3439c88b263bd97239945d880f375bc6")


if __name__ == "__main__":
    unittest.main(verbosity=2)
