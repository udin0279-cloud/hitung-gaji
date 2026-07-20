"""E2E backend tests for Sales Report with branch (Plaza/Kastem) columns.

Verifies:
- User.branch persistence (create/update/list)
- Product.length_meter persistence & meter calculation in report
- Sale captures cashier's branch on POST
- /api/sales/report/analytics returns payment_column mapping, alamat from customer master
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

ADMIN_EMAIL = "admin@payroll.id"
ADMIN_PASS = "admin123"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def kastem_user(admin_session):
    """Create a Kastem user; cleanup on teardown."""
    email = f"test_kastem_{uuid.uuid4().hex[:6]}@payroll.id"
    payload = {
        "email": email,
        "password": "kastem123",
        "name": "TEST_Kasir Kastem",
        "role": "admin_privileged",
        "permissions": ["penjualan", "laporan_penjualan"],
        "branch": "kastem",
    }
    r = admin_session.post(f"{BASE_URL}/api/users", json=payload, timeout=10)
    assert r.status_code == 200, f"Create kastem user failed: {r.text}"
    u = r.json()
    assert u["branch"] == "kastem"
    yield {"email": email, "password": "kastem123", "id": u["id"]}
    # Cleanup
    admin_session.delete(f"{BASE_URL}/api/users/{u['id']}", timeout=10)


@pytest.fixture(scope="module")
def kastem_session(kastem_user):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": kastem_user["email"], "password": kastem_user["password"]}, timeout=15)
    assert r.status_code == 200
    return s


# ================= USER BRANCH =================
class TestUserBranch:
    def test_admin_set_plaza(self, admin_session):
        # Get admin user id
        me = admin_session.get(f"{BASE_URL}/api/auth/me").json()
        admin_id = me["id"]
        r = admin_session.put(f"{BASE_URL}/api/users/{admin_id}", json={"branch": "plaza"}, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["branch"] == "plaza"
        # Verify via GET
        users = admin_session.get(f"{BASE_URL}/api/users").json()
        admin = next(u for u in users if u["id"] == admin_id)
        assert admin["branch"] == "plaza"

    def test_kastem_user_branch_persisted(self, admin_session, kastem_user):
        users = admin_session.get(f"{BASE_URL}/api/users").json()
        u = next((x for x in users if x["id"] == kastem_user["id"]), None)
        assert u is not None
        assert u["branch"] == "kastem"

    def test_invalid_branch_sanitized(self, admin_session):
        me = admin_session.get(f"{BASE_URL}/api/auth/me").json()
        r = admin_session.put(f"{BASE_URL}/api/users/{me['id']}", json={"branch": "invalid_xyz"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["branch"] is None
        # Restore to plaza
        admin_session.put(f"{BASE_URL}/api/users/{me['id']}", json={"branch": "plaza"}, timeout=10)


# ================= PRODUCT length_meter =================
class TestProductLengthMeter:
    def test_create_product_with_length_meter(self, admin_session):
        pname = f"TEST_PROD_METER_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": pname,
            "sku": f"TESTM-{uuid.uuid4().hex[:6]}",
            "unit_price": 15000,
            "purchase_price": 5000,
            "current_stock": 100,
            "length_meter": 2.5,
        }
        r = admin_session.post(f"{BASE_URL}/api/products", json=payload, timeout=10)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        # Read back
        prods = admin_session.get(f"{BASE_URL}/api/products").json()
        p = next(x for x in prods if x["id"] == pid)
        assert float(p["length_meter"]) == 2.5
        # Cleanup
        admin_session.delete(f"{BASE_URL}/api/products/{pid}", timeout=10)


# ================= SALES + REPORT =================
class TestSalesReportBranch:
    @pytest.fixture(scope="class")
    def seed(self, admin_session, kastem_session):
        # Create master customer with alamat
        cust_name = f"TEST_Cust_{uuid.uuid4().hex[:5]}"
        cust_addr = "Jl. Merdeka 10, Solo"
        rc = admin_session.post(f"{BASE_URL}/api/inventory/customers", json={"name": cust_name, "address": cust_addr, "phone": "0812"}, timeout=10)
        assert rc.status_code == 200, rc.text
        cust_id = rc.json()["id"]

        # Create product with length_meter=2.5
        pname = f"TEST_METERPROD_{uuid.uuid4().hex[:5]}"
        rp = admin_session.post(f"{BASE_URL}/api/products", json={
            "name": pname, "sku": f"TM-{uuid.uuid4().hex[:5]}",
            "unit_price": 20000, "purchase_price": 5000,
            "current_stock": 500, "length_meter": 2.5,
        }, timeout=10)
        assert rp.status_code == 200, rp.text
        pid = rp.json()["id"]

        # Admin (plaza) makes a sale cash qty=3
        s1_payload = {
            "customer_name": cust_name,
            "items": [{"product_id": pid, "product_name": pname, "quantity": 3, "unit_price": 20000}],
            "discount": 0,
            "payment_method": "cash",
            "cash_paid": 60000,
        }
        r1 = admin_session.post(f"{BASE_URL}/api/sales", json=s1_payload, timeout=15)
        assert r1.status_code == 200, r1.text
        sale1 = r1.json()
        assert sale1.get("branch") == "plaza"

        # Kastem cashier makes a sale cash qty=2
        s2_payload = {
            "customer_name": cust_name,
            "items": [{"product_id": pid, "product_name": pname, "quantity": 2, "unit_price": 20000}],
            "discount": 0,
            "payment_method": "cash",
            "cash_paid": 40000,
        }
        r2 = kastem_session.post(f"{BASE_URL}/api/sales", json=s2_payload, timeout=15)
        assert r2.status_code == 200, r2.text
        sale2 = r2.json()
        assert sale2.get("branch") == "kastem"

        # Admin (plaza) makes transfer BCA
        s3_payload = {
            "customer_name": cust_name,
            "items": [{"product_id": pid, "product_name": pname, "quantity": 1, "unit_price": 20000}],
            "discount": 0,
            "payment_method": "transfer",
            "payment_bank": "bca",
            "cash_paid": 20000,
        }
        r3 = admin_session.post(f"{BASE_URL}/api/sales", json=s3_payload, timeout=15)
        assert r3.status_code == 200

        # Admin (plaza) makes transfer Mandiri
        s4_payload = {
            "customer_name": cust_name,
            "items": [{"product_id": pid, "product_name": pname, "quantity": 1, "unit_price": 20000}],
            "discount": 0,
            "payment_method": "transfer",
            "payment_bank": "mandiri",
            "cash_paid": 20000,
        }
        r4 = admin_session.post(f"{BASE_URL}/api/sales", json=s4_payload, timeout=15)
        assert r4.status_code == 200

        data = {
            "cust_name": cust_name,
            "cust_addr": cust_addr,
            "cust_id": cust_id,
            "pname": pname,
            "pid": pid,
            "sale_ids": [sale1["id"], sale2["id"], r3.json()["id"], r4.json()["id"]],
            "sale_nos": [sale1["sale_no"], sale2["sale_no"], r3.json()["sale_no"], r4.json()["sale_no"]],
        }
        yield data
        # Cleanup
        for sid in data["sale_ids"]:
            admin_session.delete(f"{BASE_URL}/api/sales/{sid}", timeout=10)
        admin_session.delete(f"{BASE_URL}/api/products/{data['pid']}", timeout=10)
        admin_session.delete(f"{BASE_URL}/api/inventory/customers/{data['cust_id']}", timeout=10)

    def test_report_analytics_alamat_meter_payment_col(self, admin_session, seed):
        r = admin_session.get(f"{BASE_URL}/api/sales/report/analytics", timeout=15)
        assert r.status_code == 200, r.text
        rep = r.json()
        rows = rep["rows"]
        # Filter to our sale_nos
        our = [row for row in rows if row.get("sale_no") in seed["sale_nos"]]
        assert len(our) >= 4, f"Expected >=4 rows for our sales, got {len(our)}"

        by_no = {row["sale_no"]: row for row in our}

        # Sale 1: Admin/Plaza cash qty=3 -> meter=7.5, alamat, cash_plaza
        s1 = by_no[seed["sale_nos"][0]]
        assert s1["alamat"] == seed["cust_addr"], f"alamat={s1['alamat']}"
        assert s1["branch"] == "plaza"
        assert s1["payment_column"] == "cash_plaza"
        assert abs(float(s1["meter"]) - 7.5) < 0.01
        assert s1["pcs"] == 3

        # Sale 2: Kastem cash qty=2 -> meter=5.0, cash_kastem
        s2 = by_no[seed["sale_nos"][1]]
        assert s2["branch"] == "kastem"
        assert s2["payment_column"] == "cash_kastem"
        assert abs(float(s2["meter"]) - 5.0) < 0.01

        # Sale 3: Admin/Plaza transfer BCA -> bca_plaza
        s3 = by_no[seed["sale_nos"][2]]
        assert s3["payment_column"] == "bca_plaza", f"got {s3['payment_column']}"

        # Sale 4: Admin/Plaza transfer Mandiri -> mandiri_plaza
        s4 = by_no[seed["sale_nos"][3]]
        assert s4["payment_column"] == "mandiri_plaza"

        # is_first_item_of_sale should be True (single-item sales)
        for row in our:
            assert row["is_first_item_of_sale"] is True

    def test_period_total_matches_row_sum(self, admin_session, seed):
        r = admin_session.get(f"{BASE_URL}/api/sales/report/analytics", timeout=15)
        rep = r.json()
        # Sum unique sale_total for our sales
        our_totals = {}
        for row in rep["rows"]:
            if row["sale_no"] in seed["sale_nos"]:
                our_totals[row["sale_no"]] = float(row["sale_total"])
        # 3*20000 + 2*20000 + 1*20000 + 1*20000 = 140000
        assert sum(our_totals.values()) == 140000
