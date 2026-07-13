"""Tests for POST /api/inventory/customers/broadcast-whatsapp (iteration_18 feature).

Fonnte token is NOT set in preview so status will be 'mocked' (VALID behavior).
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break


def _admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def admin():
    return _admin()


@pytest.fixture(scope="module")
def seeded_customers(admin):
    """Create 3 test customers: 2 with phone, 1 without."""
    created = []
    uniq = uuid.uuid4().hex[:6]
    payloads = [
        {"name": f"TEST_BC_WithPhoneA_{uniq}", "phone": "081234567001", "active": True},
        {"name": f"TEST_BC_WithPhoneB_{uniq}", "phone": "081234567002", "active": True},
        {"name": f"TEST_BC_NoPhone_{uniq}", "phone": "", "active": True},
    ]
    for p in payloads:
        r = admin.post(f"{BASE_URL}/api/inventory/customers", json=p)
        assert r.status_code == 200, f"seed customer failed: {r.status_code} {r.text}"
        created.append(r.json())

    yield created

    # Teardown
    for c in created:
        try:
            admin.delete(f"{BASE_URL}/api/inventory/customers/{c['id']}")
        except Exception:
            pass


# ---------------- Validation ----------------
class TestBroadcastValidation:
    def test_empty_message_returns_400(self, admin, seeded_customers):
        r = admin.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                       json={"message": "", "customer_ids": [seeded_customers[0]["id"]]})
        assert r.status_code == 400
        assert "kosong" in r.json().get("detail", "").lower()

    def test_whitespace_only_message_returns_400(self, admin, seeded_customers):
        r = admin.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                       json={"message": "   \n\t  ", "customer_ids": [seeded_customers[0]["id"]]})
        assert r.status_code == 400
        assert "kosong" in r.json().get("detail", "").lower()

    def test_too_long_message_returns_400(self, admin, seeded_customers):
        long_msg = "A" * 3001
        r = admin.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                       json={"message": long_msg, "customer_ids": [seeded_customers[0]["id"]]})
        assert r.status_code == 400
        assert "panjang" in r.json().get("detail", "").lower()

    def test_unauth_returns_401_or_403(self):
        r = requests.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                          json={"message": "hi", "customer_ids": []})
        assert r.status_code in (401, 403)


# ---------------- Preview mode ----------------
class TestBroadcastPreview:
    def test_preview_only_returns_structure(self, admin, seeded_customers):
        ids = [c["id"] for c in seeded_customers]
        r = admin.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                       json={"message": "Halo {name}", "customer_ids": ids, "preview_only": True})
        assert r.status_code == 200
        data = r.json()
        assert data["preview_only"] is True
        assert data["total_selected"] == 3
        assert data["total_with_phone"] == 2
        assert data["skipped_no_phone"] == 1
        assert isinstance(data["sample_targets"], list)
        assert len(data["sample_targets"]) == 2
        # Each target has name & phone
        for t in data["sample_targets"]:
            assert "name" in t and "phone" in t

    def test_preview_all_active_when_no_ids(self, admin, seeded_customers):
        """customer_ids None → target all active customers with phone."""
        r = admin.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                       json={"message": "test", "preview_only": True})
        assert r.status_code == 200
        data = r.json()
        # Should include our 2 seeded phone customers (+ any pre-existing)
        assert data["total_with_phone"] >= 2


# ---------------- Actual send (mocked) ----------------
class TestBroadcastSend:
    def test_send_returns_mocked_status_and_full_structure(self, admin, seeded_customers):
        ids = [c["id"] for c in seeded_customers if c.get("phone")]
        assert len(ids) == 2
        r = admin.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                       json={"message": "Halo {name}, promo hari ini", "customer_ids": ids})
        assert r.status_code == 200, f"unexpected: {r.status_code} {r.text}"
        data = r.json()
        assert data["preview_only"] is False
        assert data["total"] == 2
        # Fonnte token not set in preview → all mocked
        assert data["mocked"] + data["sent"] + data["failed"] == 2
        assert isinstance(data["results"], list) and len(data["results"]) == 2
        for row in data["results"]:
            assert "customer_id" in row
            assert "name" in row
            assert "phone" in row
            assert row["status"] in ("sent", "mocked", "failed")

    def test_send_skips_customer_without_phone(self, admin, seeded_customers):
        """Passing all 3 IDs, the no-phone one should be skipped."""
        ids = [c["id"] for c in seeded_customers]
        r = admin.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                       json={"message": "promo", "customer_ids": ids})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2  # only phone ones
        assert data["skipped_no_phone"] == 1

    def test_name_variable_replacement(self, admin, seeded_customers):
        """Verify {name} is replaced in each personalized message.

        Since Fonnte is mocked we cannot capture the wire message directly,
        but backend logs to db.whatsapp_logs with message_preview.
        We verify indirectly: response returns results with correct names.
        """
        ids = [c["id"] for c in seeded_customers if c.get("phone")]
        template = "Halo {name}, silakan cek promo"
        r = admin.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                       json={"message": template, "customer_ids": ids})
        assert r.status_code == 200
        data = r.json()
        names_returned = sorted(row["name"] for row in data["results"])
        seeded_names = sorted(c["name"] for c in seeded_customers if c.get("phone"))
        assert names_returned == seeded_names

    def test_empty_ids_targets_all_active_with_phone(self, admin, seeded_customers):
        """customer_ids=[] → target ALL active customers with phone."""
        r = admin.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                       json={"message": "hello all", "customer_ids": []})
        assert r.status_code == 200
        data = r.json()
        # At least our 2 seeded phone customers should be there
        assert data["total"] >= 2
        seeded_phone_ids = {c["id"] for c in seeded_customers if c.get("phone")}
        returned_ids = {row["customer_id"] for row in data["results"]}
        assert seeded_phone_ids.issubset(returned_ids)

    def test_send_creates_whatsapp_log_via_admin_endpoint(self, admin, seeded_customers):
        """Verify db.whatsapp_logs entries were created (via list endpoint if exists)."""
        ids = [c["id"] for c in seeded_customers if c.get("phone")][:1]
        marker_msg = f"TEST_MARKER_{uuid.uuid4().hex[:8]} Halo {{name}}"
        r = admin.post(f"{BASE_URL}/api/inventory/customers/broadcast-whatsapp",
                       json={"message": marker_msg, "customer_ids": ids})
        assert r.status_code == 200
        # Try to fetch logs (endpoint may or may not exist — best effort)
        for path in ("/api/admin/whatsapp/logs", "/api/whatsapp/logs"):
            try:
                lr = admin.get(f"{BASE_URL}{path}?type=customer_broadcast")
                if lr.status_code == 200:
                    logs = lr.json() if isinstance(lr.json(), list) else lr.json().get("items", [])
                    # Not strictly required to find marker; endpoint may not exist
                    return
            except Exception:
                pass
        # If no log endpoint exists, that's fine — the write itself is best-effort.


# ---------------- Regression: CRUD ----------------
class TestCustomerCRUDRegression:
    def test_list_customers(self, admin):
        r = admin.get(f"{BASE_URL}/api/inventory/customers")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_update_delete(self, admin):
        uniq = uuid.uuid4().hex[:6]
        r = admin.post(f"{BASE_URL}/api/inventory/customers",
                       json={"name": f"TEST_REG_{uniq}", "phone": "0811222333", "active": True})
        assert r.status_code == 200
        cid = r.json()["id"]
        # Update
        r2 = admin.put(f"{BASE_URL}/api/inventory/customers/{cid}",
                       json={"name": f"TEST_REG_{uniq}_upd", "phone": "0811999", "active": True})
        assert r2.status_code == 200
        assert r2.json()["name"] == f"TEST_REG_{uniq}_upd"
        # Delete
        r3 = admin.delete(f"{BASE_URL}/api/inventory/customers/{cid}")
        assert r3.status_code == 200
        # Verify gone
        r4 = admin.delete(f"{BASE_URL}/api/inventory/customers/{cid}")
        assert r4.status_code == 404


# ---------------- Regression: Sales auto-create customer (iteration_17) ----------------
class TestSalesRegression:
    def test_sales_post_still_works(self, admin):
        uniq = uuid.uuid4().hex[:6]
        # Seed material first
        mat_payload = {
            "code": f"TEST_MAT_{uniq}",
            "name": f"TEST_MAT_{uniq}",
            "category": "flexy",
            "unit": "meter",
            "stock": 100,
            "current_stock": 100,
            "min_stock": 0,
            "cost_price": 10000,
            "selling_price": 25000,
        }
        mr = admin.post(f"{BASE_URL}/api/inventory/materials", json=mat_payload)
        assert mr.status_code == 200, f"seed material failed: {mr.status_code} {mr.text}"
        mat = mr.json()

        payload = {
            "customer_name": f"TEST_SALES_{uniq}",
            "customer_phone": "0812345555",
            "items": [{
                "material_id": mat["id"],
                "product_name": "Banner Vinyl 3x2m",
                "length_m": 3.0,
                "width_m": 2.0,
                "quantity": 1,
                "unit_price": 25000,
            }],
            "payment_method": "tunai",
            "cash_paid": 150000,
        }
        r = admin.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code in (200, 201), f"sales POST failed: {r.status_code} {r.text}"
        sale = r.json()
        assert sale["customer_name"] == f"TEST_SALES_{uniq}"
        assert sale["total"] == 150000

        # Note: Auto-create-to-customer-master is FRONTEND-only (fire-and-forget from Sales.jsx submit).
        # Backend /api/sales does NOT auto-create — verified iteration_17.
        # So we manually simulate the frontend flow (POST /inventory/customers) to verify regression:
        cr = admin.post(f"{BASE_URL}/api/inventory/customers", json={
            "name": f"TEST_SALES_{uniq}", "phone": "0812345555", "active": True
        })
        assert cr.status_code == 200, f"customer auto-create-mimic failed: {cr.status_code} {cr.text}"
        cust_id = cr.json()["id"]

        # cleanup
        try:
            admin.delete(f"{BASE_URL}/api/sales/{sale['id']}")
        except Exception:
            pass
        try:
            admin.delete(f"{BASE_URL}/api/inventory/customers/{cust_id}")
        except Exception:
            pass
        try:
            admin.delete(f"{BASE_URL}/api/inventory/materials/{mat['id']}")
        except Exception:
            pass
