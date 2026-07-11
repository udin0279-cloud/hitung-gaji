"""Backend tests for Inventory extras: Job Orders (BOM), Stock Adjust (Opname),
Waste monthly report (Excel/PDF) and Dashboard inventory widget."""
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


@pytest.fixture(scope="module")
def material(client):
    """Create an isolated material for order/adjust tests. Cleanup at end."""
    uniq = uuid.uuid4().hex[:6]
    payload = {
        "name": f"TEST_JobMat_{uniq}",
        "category": "flexy",
        "unit": "meter",
        "current_stock": 100,
        "purchase_price": 25000,
        "min_stock": 5,
        "active": True,
    }
    r = client.post(f"{BASE_URL}/api/inventory/materials", json=payload)
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    yield {"id": mid, "start_stock": 100, "unit_price": 25000}
    # Best-effort cleanup
    try:
        client.delete(f"{BASE_URL}/api/inventory/materials/{mid}")
    except Exception:
        pass


def _current_stock(client, mid):
    mats = client.get(f"{BASE_URL}/api/inventory/materials").json()
    return float(next(m for m in mats if m["id"] == mid)["current_stock"])


# ---------------- Job Orders ----------------
class TestJobOrders:
    order_ids = []

    def test_auth_guard(self):
        r = requests.get(f"{BASE_URL}/api/inventory/orders")
        assert r.status_code in (401, 403)

    def test_list_orders_empty_ok(self, client):
        r = client.get(f"{BASE_URL}/api/inventory/orders")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_order_decrements_stock_and_computes_totals(self, client, material):
        mid = material["id"]
        stock_before = _current_stock(client, mid)
        payload = {
            "customer": "TEST_PT Contoh",
            "product_name": "Banner 3x2m",
            "quantity": 5,               # 5 units of product
            "unit_price": 150000,        # selling price / unit
            "start_date": "2026-01-15",
            "due_date": "2026-01-20",
            "items": [{"material_id": mid, "quantity": 10}],
            "notes": "TEST BOM order",
        }
        r = client.post(f"{BASE_URL}/api/inventory/orders", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "aktif"
        assert d["customer"] == "TEST_PT Contoh"
        assert d["order_no"].startswith("JO-")
        assert d["total_material_cost"] == round(10 * 25000, 2)
        assert d["total_price"] == round(5 * 150000, 2)
        assert d["gross_margin"] == round(5 * 150000 - 10 * 25000, 2)
        assert "id" in d and "_id" not in d
        assert len(d["items"]) == 1
        assert d["items"][0]["quantity"] == 10
        assert d["items"][0]["unit_price_snapshot"] == 25000
        TestJobOrders.order_ids.append(d["id"])

        # Verify stock decremented in DB
        stock_after = _current_stock(client, mid)
        assert stock_after == round(stock_before - 10, 4)

    def test_create_order_rejects_zero_quantity_item(self, client, material):
        r = client.post(f"{BASE_URL}/api/inventory/orders", json={
            "customer": "TEST", "product_name": "P", "quantity": 1,
            "unit_price": 1000, "start_date": "2026-01-15",
            "items": [{"material_id": material["id"], "quantity": 0}],
        })
        assert r.status_code == 400

    def test_create_order_rejects_insufficient_stock(self, client, material):
        r = client.post(f"{BASE_URL}/api/inventory/orders", json={
            "customer": "TEST", "product_name": "P", "quantity": 1,
            "unit_price": 1000, "start_date": "2026-01-15",
            "items": [{"material_id": material["id"], "quantity": 999999}],
        })
        assert r.status_code == 400
        assert "tidak cukup" in r.json().get("detail", "").lower() or "cukup" in r.json().get("detail", "").lower()

    def test_create_order_missing_customer(self, client, material):
        r = client.post(f"{BASE_URL}/api/inventory/orders", json={
            "customer": "", "product_name": "P", "quantity": 1, "unit_price": 100,
            "start_date": "2026-01-15", "items": [],
        })
        assert r.status_code == 400

    def test_complete_order_sets_status_selesai(self, client, material):
        oid = TestJobOrders.order_ids[0]
        stock_before = _current_stock(client, material["id"])
        r = client.put(f"{BASE_URL}/api/inventory/orders/{oid}/complete")
        assert r.status_code == 200
        assert r.json().get("status") == "selesai"
        # Stock should NOT change on complete
        assert _current_stock(client, material["id"]) == stock_before
        # Verify persisted
        orders = client.get(f"{BASE_URL}/api/inventory/orders").json()
        found = next(o for o in orders if o["id"] == oid)
        assert found["status"] == "selesai"

    def test_cancel_order_after_complete_restores_stock(self, client, material):
        # Create a fresh order to cancel (previous is now 'selesai' but cancel should still rollback)
        stock_before = _current_stock(client, material["id"])
        payload = {
            "customer": "TEST_Cancel", "product_name": "P2", "quantity": 2,
            "unit_price": 50000, "start_date": "2026-01-15",
            "items": [{"material_id": material["id"], "quantity": 4}],
        }
        r = client.post(f"{BASE_URL}/api/inventory/orders", json=payload)
        assert r.status_code == 200
        oid = r.json()["id"]
        assert _current_stock(client, material["id"]) == round(stock_before - 4, 4)
        # Cancel
        r2 = client.put(f"{BASE_URL}/api/inventory/orders/{oid}/cancel")
        assert r2.status_code == 200
        assert r2.json().get("status") == "batal"
        # Stock restored
        assert _current_stock(client, material["id"]) == round(stock_before, 4)
        # Verify persisted in list
        orders = client.get(f"{BASE_URL}/api/inventory/orders").json()
        found = next(o for o in orders if o["id"] == oid)
        assert found["status"] == "batal"
        # Second cancel should be idempotent (no double restore)
        r3 = client.put(f"{BASE_URL}/api/inventory/orders/{oid}/cancel")
        assert r3.status_code == 200
        assert _current_stock(client, material["id"]) == round(stock_before, 4)
        # Delete order (cancelled → no stock change)
        client.delete(f"{BASE_URL}/api/inventory/orders/{oid}")

    def test_delete_active_order_rolls_back_stock(self, client, material):
        stock_before = _current_stock(client, material["id"])
        r = client.post(f"{BASE_URL}/api/inventory/orders", json={
            "customer": "TEST_Del", "product_name": "P3", "quantity": 1,
            "unit_price": 10000, "start_date": "2026-01-15",
            "items": [{"material_id": material["id"], "quantity": 3}],
        })
        assert r.status_code == 200
        oid = r.json()["id"]
        assert _current_stock(client, material["id"]) == round(stock_before - 3, 4)
        r2 = client.delete(f"{BASE_URL}/api/inventory/orders/{oid}")
        assert r2.status_code == 200
        assert _current_stock(client, material["id"]) == round(stock_before, 4)

    def test_delete_completed_order_also_rolls_back(self, client, material):
        # The first order was completed (selesai). Delete it and verify stock restored.
        oid = TestJobOrders.order_ids[0]
        stock_before = _current_stock(client, material["id"])
        r = client.delete(f"{BASE_URL}/api/inventory/orders/{oid}")
        assert r.status_code == 200
        # The order took 10 units originally
        assert _current_stock(client, material["id"]) == round(stock_before + 10, 4)


# ---------------- Stock Adjustment (Opname) ----------------
class TestStockAdjust:
    def test_auth_guard(self):
        r = requests.get(f"{BASE_URL}/api/inventory/stock-adjust")
        assert r.status_code in (401, 403)

    def test_list_stock_adjust(self, client):
        r = client.get(f"{BASE_URL}/api/inventory/stock-adjust")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_adjust_positive_delta(self, client, material):
        stock_before = _current_stock(client, material["id"])
        target = stock_before + 5
        r = client.post(f"{BASE_URL}/api/inventory/stock-adjust", json={
            "material_id": material["id"], "new_stock": target,
            "reason": "opname", "date": "2026-01-15", "notes": "TEST positive",
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["stock_before"] == round(stock_before, 4)
        assert d["stock_after"] == round(target, 4)
        assert d["delta"] == round(5, 4)
        assert "id" in d and "_id" not in d
        # Stock persisted
        assert _current_stock(client, material["id"]) == round(target, 4)
        # Cleanup: delete + verify rollback
        rid = d["id"]
        r2 = client.delete(f"{BASE_URL}/api/inventory/stock-adjust/{rid}")
        assert r2.status_code == 200
        assert _current_stock(client, material["id"]) == round(stock_before, 4)

    def test_create_adjust_negative_delta(self, client, material):
        stock_before = _current_stock(client, material["id"])
        target = max(0, stock_before - 3)
        r = client.post(f"{BASE_URL}/api/inventory/stock-adjust", json={
            "material_id": material["id"], "new_stock": target,
            "reason": "koreksi", "date": "2026-01-15",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["delta"] == round(target - stock_before, 4)
        assert _current_stock(client, material["id"]) == round(target, 4)
        # Rollback via delete
        client.delete(f"{BASE_URL}/api/inventory/stock-adjust/{d['id']}")
        assert _current_stock(client, material["id"]) == round(stock_before, 4)

    def test_adjust_unknown_material(self, client):
        r = client.post(f"{BASE_URL}/api/inventory/stock-adjust", json={
            "material_id": "does-not-exist", "new_stock": 1,
            "reason": "opname", "date": "2026-01-15",
        })
        assert r.status_code == 404


# ---------------- Waste Monthly Report ----------------
class TestWasteReport:
    def _period(self):
        # Use current year-month so any seeded/existing waste can populate but report must succeed even if empty
        now = datetime.utcnow()
        return f"{now.year}-{now.month:02d}"

    def test_auth_guard_excel(self):
        r = requests.get(f"{BASE_URL}/api/inventory/waste/report/2026-01/excel")
        assert r.status_code in (401, 403)

    def test_excel_report_returns_xlsx(self, client):
        period = self._period()
        r = client.get(f"{BASE_URL}/api/inventory/waste/report/{period}/excel")
        assert r.status_code == 200, r.text
        ctype = r.headers.get("content-type", "")
        assert "spreadsheetml" in ctype or "officedocument" in ctype
        # XLSX = ZIP magic bytes PK\x03\x04
        assert r.content[:2] == b"PK", f"Not a valid xlsx (starts with {r.content[:4]!r})"
        assert len(r.content) > 500
        # Verify parseable
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(r.content))
            assert wb.active is not None
        except Exception as ex:
            pytest.fail(f"Could not parse xlsx: {ex}")

    def test_pdf_report_returns_pdf(self, client):
        period = self._period()
        r = client.get(f"{BASE_URL}/api/inventory/waste/report/{period}/pdf")
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        # PDF magic bytes %PDF-
        assert r.content[:5] == b"%PDF-", f"Not a valid PDF (starts with {r.content[:8]!r})"
        assert len(r.content) > 500

    def test_report_invalid_period_format(self, client):
        r = client.get(f"{BASE_URL}/api/inventory/waste/report/not-a-date/excel")
        assert r.status_code in (400, 422, 500)  # some validation error


# ---------------- Dashboard Inventory Widget ----------------
class TestDashboardInventoryWidget:
    def test_dashboard_stats_returns_inventory(self, client):
        r = client.get(f"{BASE_URL}/api/dashboard/stats")
        assert r.status_code == 200, r.text
        d = r.json()
        assert "inventory" in d
        inv = d["inventory"]
        assert inv is not None, "inventory summary is null"
        for k in ("total_stock_value", "total_materials", "low_stock_count",
                  "total_waste_this_month", "top_waste"):
            assert k in inv, f"missing key {k} in inventory summary"
        assert isinstance(inv["top_waste"], list)
        assert isinstance(inv["total_stock_value"], (int, float))
        assert isinstance(inv["total_materials"], int)
        assert isinstance(inv["low_stock_count"], int)
        assert isinstance(inv["total_waste_this_month"], (int, float))
        # top_waste row shape (if any rows)
        for row in inv["top_waste"]:
            for k in ("material_name", "material_unit", "qty", "loss"):
                assert k in row
