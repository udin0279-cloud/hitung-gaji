"""Backend tests for Sales autocomplete + auto-save pelanggan ke Master (iteration 17).

Covers:
  1. GET /api/inventory/customers regression (super_admin cookie auth)
  2. POST /api/inventory/customers create/dup rejection
  3. Full flow: create sale w/ new customer → POST /inventory/customers succeeds
  4. Sale with existing customer → POST /inventory/customers rejected (400) but sale ok
  5. Sale with 'Umum'/empty → no customer master row created
  6. Regression /api/sales, /api/sales/stats/today

Uses TEST_QA_ prefix for cleanup.
"""
import os
import time
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break


TIMESTAMP = str(int(time.time()))
TEST_NEW_CUSTOMER = f"TEST_QA_Pelanggan_{TIMESTAMP}"
TEST_EXISTING_CUSTOMER = f"TEST_QA_BuAniQA_{TIMESTAMP}"


# ---------- helpers ----------
def _get_active_material(auth_client):
    r = auth_client.get(f"{BASE_URL}/api/inventory/materials")
    assert r.status_code == 200
    mats = [m for m in r.json() if m.get("active") is not False and (m.get("current_stock") or 0) > 5]
    if not mats:
        pytest.skip("No usable material with stock+price found")
    return mats[0]


def _make_sale_payload(customer_name, customer_phone, material):
    return {
        "customer_name": customer_name,
        "customer_phone": customer_phone or "",
        "discount": 0,
        "cash_paid": 200000,
        "payment_method": "tunai",
        "notes": None,
        "items": [{
            "material_id": material["id"],
            "product_name": "TEST_QA_Banner",
            "length_m": 1,
            "width_m": 1,
            "quantity": 1,
            "unit_price": float(material.get("selling_price") or 50000),
        }],
    }


# ---------- Regression: customer list endpoint ----------
class TestCustomerListRegression:
    def test_list_requires_auth(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/inventory/customers")
        assert r.status_code in (401, 403)

    def test_list_ok_with_auth(self, auth_client):
        r = auth_client.get(f"{BASE_URL}/api/inventory/customers")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # each item must have id, name, active
        for c in data:
            assert "id" in c
            assert "name" in c
            assert "_id" not in c  # no ObjectId leak
            # enrichment fields present
            assert "order_count" in c
            assert "total_revenue" in c


# ---------- Customer create + dup ----------
class TestCustomerCreate:
    def test_create_new_customer_then_get(self, auth_client):
        payload = {"name": TEST_EXISTING_CUSTOMER, "phone": "08111222333", "active": True}
        r = auth_client.post(f"{BASE_URL}/api/inventory/customers", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["name"] == TEST_EXISTING_CUSTOMER
        assert data["phone"] == "08111222333"
        assert "id" in data
        assert "_id" not in data

        # GET verifies persistence
        listing = auth_client.get(f"{BASE_URL}/api/inventory/customers").json()
        names = [c["name"] for c in listing]
        assert TEST_EXISTING_CUSTOMER in names

    def test_create_duplicate_rejected(self, auth_client):
        payload = {"name": TEST_EXISTING_CUSTOMER, "phone": "08111222333", "active": True}
        r = auth_client.post(f"{BASE_URL}/api/inventory/customers", json=payload)
        assert r.status_code == 400
        assert "sudah ada" in r.text.lower() or "already" in r.text.lower() or "duplicate" in r.text.lower()

    def test_create_duplicate_case_insensitive(self, auth_client):
        payload = {"name": TEST_EXISTING_CUSTOMER.upper(), "phone": "08111222333", "active": True}
        r = auth_client.post(f"{BASE_URL}/api/inventory/customers", json=payload)
        assert r.status_code == 400

    def test_create_empty_name_rejected(self, auth_client):
        r = auth_client.post(f"{BASE_URL}/api/inventory/customers", json={"name": "   "})
        assert r.status_code == 400


# ---------- Full flow: sale + auto-save ----------
class TestSaleAutoSaveCustomerFlow:
    sale_ids = []
    created_customer_names = [TEST_EXISTING_CUSTOMER]

    def test_new_customer_sale_and_master_upsert(self, auth_client):
        """Simulates frontend flow: POST /sales then POST /inventory/customers if new."""
        mat = _get_active_material(auth_client)
        new_name = f"{TEST_NEW_CUSTOMER}_A"
        # 1. Ensure not already in master
        existing = auth_client.get(f"{BASE_URL}/api/inventory/customers").json()
        pre_count = len([c for c in existing if c["name"].lower() == new_name.lower()])
        assert pre_count == 0

        # 2. POST sale
        sale_payload = _make_sale_payload(new_name, "08199988877", mat)
        r = auth_client.post(f"{BASE_URL}/api/sales", json=sale_payload)
        assert r.status_code == 200, r.text
        sale = r.json()
        assert sale["customer_name"] == new_name
        assert "_id" not in sale
        self.__class__.sale_ids.append(sale["id"])

        # 3. Simulate frontend fire-and-forget POST customer
        cr = auth_client.post(f"{BASE_URL}/api/inventory/customers", json={
            "name": new_name, "phone": "08199988877", "active": True
        })
        assert cr.status_code == 200, cr.text
        self.__class__.created_customer_names.append(new_name)

        # 4. Verify appears in list
        listing = auth_client.get(f"{BASE_URL}/api/inventory/customers").json()
        assert any(c["name"] == new_name for c in listing)

    def test_existing_customer_sale_no_double_create(self, auth_client):
        """Sale with existing (from previous test) customer: POST /customers must return 400."""
        mat = _get_active_material(auth_client)
        # first ensure master exists
        pre = auth_client.get(f"{BASE_URL}/api/inventory/customers").json()
        pre_count = len(pre)

        sale_payload = _make_sale_payload(TEST_EXISTING_CUSTOMER, "08111222333", mat)
        r = auth_client.post(f"{BASE_URL}/api/sales", json=sale_payload)
        assert r.status_code == 200
        self.__class__.sale_ids.append(r.json()["id"])

        # frontend would call POST /customers → expect 400 duplicate
        cr = auth_client.post(f"{BASE_URL}/api/inventory/customers", json={
            "name": TEST_EXISTING_CUSTOMER, "phone": "08111222333", "active": True
        })
        assert cr.status_code == 400, "Duplicate customer should be rejected"

        # count unchanged
        post = auth_client.get(f"{BASE_URL}/api/inventory/customers").json()
        assert len(post) == pre_count, "No new customer must be created for existing customer"

    def test_umum_customer_no_master_row(self, auth_client):
        """Sale with 'Umum' or empty must NOT create a customer master entry."""
        mat = _get_active_material(auth_client)
        pre = auth_client.get(f"{BASE_URL}/api/inventory/customers").json()
        pre_umum = len([c for c in pre if c["name"].strip().lower() == "umum"])

        sale_payload = _make_sale_payload("Umum", "", mat)
        r = auth_client.post(f"{BASE_URL}/api/sales", json=sale_payload)
        assert r.status_code == 200
        self.__class__.sale_ids.append(r.json()["id"])

        # Frontend logic: won't post if name == 'umum'. We only verify master unchanged.
        post = auth_client.get(f"{BASE_URL}/api/inventory/customers").json()
        post_umum = len([c for c in post if c["name"].strip().lower() == "umum"])
        assert post_umum == pre_umum, "'Umum' must not be auto-saved into master"


# ---------- Regression: sales endpoints healthy ----------
class TestSalesRegression:
    def test_stats_today(self, auth_client):
        r = auth_client.get(f"{BASE_URL}/api/sales/stats/today")
        assert r.status_code == 200
        data = r.json()
        for k in ("count_today", "total_today", "count_month", "total_month"):
            assert k in data

    def test_sales_list(self, auth_client):
        r = auth_client.get(f"{BASE_URL}/api/sales")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        for s in data[:5]:
            assert "_id" not in s
            assert "sale_no" in s


# ---------- Cleanup ----------
@pytest.fixture(scope="module", autouse=True)
def cleanup_after(request):
    yield
    # Teardown: delete test sales + test customers created
    import requests
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    login = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if login.status_code != 200:
        return
    # sales
    for sid in TestSaleAutoSaveCustomerFlow.sale_ids:
        try:
            s.delete(f"{BASE_URL}/api/sales/{sid}")
        except Exception:
            pass
    # customers created in tests (names contain TEST_QA_)
    try:
        listing = s.get(f"{BASE_URL}/api/inventory/customers").json()
        for c in listing:
            if c.get("name", "").startswith("TEST_QA_"):
                s.delete(f"{BASE_URL}/api/inventory/customers/{c['id']}")
    except Exception:
        pass
