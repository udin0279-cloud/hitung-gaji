"""Backend tests iteration 13: Customer Master + Profit/Loss monthly report."""
import os
import io
import uuid
import pytest
import requests
from datetime import datetime
from pathlib import Path

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text}")
    return s


# ---------------- Customer Master ----------------
class TestCustomerMaster:
    created_ids = []

    def test_auth_guard(self):
        r = requests.get(f"{BASE_URL}/api/inventory/customers")
        assert r.status_code in (401, 403)

    def test_list_customers_ok(self, client):
        r = client.get(f"{BASE_URL}/api/inventory/customers")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_customer(self, client):
        uniq = uuid.uuid4().hex[:6].upper()
        name = f"TEST_Cust_{uniq}"
        payload = {
            "name": name,
            "phone": "0812-3456-7890",
            "email": "test@example.com",
            "address": "Jl. Contoh 1",
            "npwp": "12.345.678.9-012.000",
            "contact_person": "Budi",
            "notes": "TEST record",
            "active": True,
        }
        r = client.post(f"{BASE_URL}/api/inventory/customers", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == name
        assert d["phone"] == payload["phone"]
        assert d["email"] == payload["email"]
        assert "id" in d and "_id" not in d
        TestCustomerMaster.created_ids.append(d["id"])
        # Verify GET has the customer
        lst = client.get(f"{BASE_URL}/api/inventory/customers").json()
        found = next((c for c in lst if c["id"] == d["id"]), None)
        assert found is not None
        # Aggregate fields should exist (order_count / total_revenue / total_material_cost)
        for k in ("order_count", "total_revenue", "total_material_cost"):
            assert k in found

    def test_create_customer_empty_name_rejected(self, client):
        r = client.post(f"{BASE_URL}/api/inventory/customers", json={"name": "  "})
        assert r.status_code == 400

    def test_create_customer_duplicate_rejected(self, client):
        # Reuse the previously created customer name (case insensitive)
        assert TestCustomerMaster.created_ids, "prerequisite failed"
        lst = client.get(f"{BASE_URL}/api/inventory/customers").json()
        existing_name = next(c["name"] for c in lst if c["id"] == TestCustomerMaster.created_ids[0])
        # Same name lower-case should be rejected
        r = client.post(f"{BASE_URL}/api/inventory/customers", json={"name": existing_name.lower()})
        assert r.status_code == 400
        assert "sudah ada" in r.json().get("detail", "").lower()

    def test_update_customer(self, client):
        cid = TestCustomerMaster.created_ids[0]
        # Fetch current name so we don't collide
        lst = client.get(f"{BASE_URL}/api/inventory/customers").json()
        current_name = next(c["name"] for c in lst if c["id"] == cid)
        r = client.put(f"{BASE_URL}/api/inventory/customers/{cid}", json={
            "name": current_name,  # same name is fine (self)
            "phone": "0899-9999-0000",
            "email": "updated@example.com",
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["phone"] == "0899-9999-0000"
        assert d["email"] == "updated@example.com"

    def test_customer_aggregate_from_orders(self, client):
        """Create customer, create order under its name, verify aggregation."""
        uniq = uuid.uuid4().hex[:6].upper()
        cust_name = f"TEST_AggCust_{uniq}"
        cr = client.post(f"{BASE_URL}/api/inventory/customers", json={"name": cust_name})
        assert cr.status_code == 200
        cid = cr.json()["id"]
        TestCustomerMaster.created_ids.append(cid)

        # Create material
        mr = client.post(f"{BASE_URL}/api/inventory/materials", json={
            "name": f"TEST_AggMat_{uniq}", "category": "flexy", "unit": "meter",
            "current_stock": 50, "purchase_price": 20000, "min_stock": 1, "active": True,
        })
        assert mr.status_code == 200
        mid = mr.json()["id"]

        # Create order for this customer (start_date this month)
        now = datetime.utcnow()
        period = f"{now.year:04d}-{now.month:02d}"
        start_date = f"{period}-15"
        order_ids = []
        r1 = client.post(f"{BASE_URL}/api/inventory/orders", json={
            "customer": cust_name.lower(),  # test case-insensitive matching
            "product_name": "Banner", "quantity": 2, "unit_price": 200000,
            "start_date": start_date, "items": [{"material_id": mid, "quantity": 5}],
        })
        assert r1.status_code == 200, r1.text
        order_ids.append(r1.json()["id"])

        # Order 2, cancelled → should not be counted
        r2 = client.post(f"{BASE_URL}/api/inventory/orders", json={
            "customer": cust_name, "product_name": "Banner2", "quantity": 1, "unit_price": 50000,
            "start_date": start_date, "items": [{"material_id": mid, "quantity": 1}],
        })
        assert r2.status_code == 200
        oid2 = r2.json()["id"]
        order_ids.append(oid2)
        # Cancel it
        client.put(f"{BASE_URL}/api/inventory/orders/{oid2}/cancel")

        # GET customers → verify aggregate
        lst = client.get(f"{BASE_URL}/api/inventory/customers").json()
        row = next((c for c in lst if c["id"] == cid), None)
        assert row is not None
        # Only order 1 (Rp 400k) should be counted; order 2 was cancelled
        assert row["order_count"] == 1
        assert row["total_revenue"] == 400000.0
        assert row["total_material_cost"] == 100000.0  # 5 * 20000

        # Save for P&L tests
        TestCustomerMaster._pl_context = {
            "period": period, "start_date": start_date, "material_id": mid,
            "customer_name": cust_name, "order_ids": order_ids,
        }

    def test_delete_customer(self, client):
        # Create a throwaway to delete
        uniq = uuid.uuid4().hex[:6].upper()
        r = client.post(f"{BASE_URL}/api/inventory/customers", json={"name": f"TEST_Del_{uniq}"})
        assert r.status_code == 200
        cid = r.json()["id"]
        r2 = client.delete(f"{BASE_URL}/api/inventory/customers/{cid}")
        assert r2.status_code == 200
        # Verify not in list
        lst = client.get(f"{BASE_URL}/api/inventory/customers").json()
        assert not any(c["id"] == cid for c in lst)

    def test_delete_unknown_customer_404(self, client):
        r = client.delete(f"{BASE_URL}/api/inventory/customers/does-not-exist")
        assert r.status_code == 404


# ---------------- Profit & Loss ----------------
class TestProfitLoss:
    def test_auth_guard(self):
        r = requests.get(f"{BASE_URL}/api/reports/profit-loss/2026-01")
        assert r.status_code in (401, 403)

    def test_pl_report_current_month(self, client):
        # Use context from customer aggregate test if present, else current month
        ctx = getattr(TestCustomerMaster, "_pl_context", None)
        period = ctx["period"] if ctx else datetime.utcnow().strftime("%Y-%m")
        r = client.get(f"{BASE_URL}/api/reports/profit-loss/{period}")
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("period", "revenue", "cogs", "gross_profit", "gross_margin_pct",
                  "waste_loss", "payroll_cost", "employee_count", "total_expenses",
                  "net_profit", "net_margin_pct", "order_count", "waste_records",
                  "top_customers"):
            assert k in d, f"missing key: {k}"
        assert d["period"] == period
        assert isinstance(d["top_customers"], list)
        # net_profit = gross_profit - total_expenses
        assert round(d["net_profit"], 2) == round(d["gross_profit"] - d["total_expenses"], 2)
        # gross_profit = revenue - cogs
        assert round(d["gross_profit"], 2) == round(d["revenue"] - d["cogs"], 2)
        # total_expenses = waste_loss + payroll_cost
        assert round(d["total_expenses"], 2) == round(d["waste_loss"] + d["payroll_cost"], 2)

        if ctx:
            # Our AggCust order should show up in top_customers (revenue 400k, margin 300k)
            found = next((c for c in d["top_customers"] if c["customer"].lower() == ctx["customer_name"].lower()), None)
            assert found is not None, f"customer {ctx['customer_name']} not in top_customers"
            assert found["orders"] >= 1
            assert found["revenue"] >= 400000
            assert found["margin"] == found["revenue"] - found["material_cost"]

    def test_pl_report_invalid_period(self, client):
        r = client.get(f"{BASE_URL}/api/reports/profit-loss/not-a-date")
        assert r.status_code in (400, 422)

    def test_pl_report_no_data_zero_month(self, client):
        # Use a far-past month to ensure zero data
        r = client.get(f"{BASE_URL}/api/reports/profit-loss/2000-01")
        assert r.status_code == 200
        d = r.json()
        assert d["revenue"] == 0
        assert d["cogs"] == 0
        assert d["gross_profit"] == 0
        assert d["order_count"] == 0
        # payroll should be 0 too since no run for that period
        assert d["payroll_cost"] == 0
        assert d["employee_count"] == 0
        # Division by zero guard
        assert d["gross_margin_pct"] == 0
        assert d["net_margin_pct"] == 0

    def test_pl_pdf_returns_pdf(self, client):
        period = datetime.utcnow().strftime("%Y-%m")
        r = client.get(f"{BASE_URL}/api/reports/profit-loss/{period}/pdf")
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:5] == b"%PDF-", f"not a valid PDF (got {r.content[:8]!r})"
        assert len(r.content) > 500


# ---------------- Cleanup (best-effort, runs last) ----------------
def test_zzz_cleanup(client):
    # Delete created customers
    for cid in TestCustomerMaster.created_ids:
        try:
            client.delete(f"{BASE_URL}/api/inventory/customers/{cid}")
        except Exception:
            pass
    # Cleanup orders/materials from aggregate test
    ctx = getattr(TestCustomerMaster, "_pl_context", None)
    if ctx:
        for oid in ctx.get("order_ids", []):
            try:
                client.delete(f"{BASE_URL}/api/inventory/orders/{oid}")
            except Exception:
                pass
        try:
            client.delete(f"{BASE_URL}/api/inventory/materials/{ctx['material_id']}")
        except Exception:
            pass
