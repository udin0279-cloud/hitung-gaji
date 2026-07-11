"""Backend tests for Inventory module (Materials, Stock-In, Waste, Stats)."""
import os
import pytest
import requests
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
def created_ids():
    return {"materials": [], "stock_in": [], "waste": []}


# ----- Auth guard -----
class TestInventoryAuth:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/inventory/materials")
        assert r.status_code in (401, 403)


# ----- Materials CRUD -----
class TestMaterials:
    def test_list_materials(self, client):
        r = client.get(f"{BASE_URL}/api/inventory/materials")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_material_decimal(self, client, created_ids):
        payload = {
            "name": "TEST_Sticker Ritrama",
            "category": "sticker",
            "unit": "roll",
            "current_stock": 2.5,
            "purchase_price": 750000,
            "min_stock": 1,
            "supplier_default": "PT Ritrama",
            "notes": "TEST",
            "active": True,
        }
        r = client.post(f"{BASE_URL}/api/inventory/materials", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["name"] == payload["name"]
        assert data["category"] == "sticker"
        assert data["unit"] == "roll"
        assert data["current_stock"] == 2.5
        assert data["purchase_price"] == 750000
        assert "id" in data
        assert "_id" not in data
        created_ids["materials"].append(data["id"])

    def test_get_created_material_persisted(self, client, created_ids):
        assert created_ids["materials"], "no material created"
        mid = created_ids["materials"][0]
        r = client.get(f"{BASE_URL}/api/inventory/materials")
        assert r.status_code == 200
        mat = next((m for m in r.json() if m["id"] == mid), None)
        assert mat is not None
        assert mat["current_stock"] == 2.5

    def test_invalid_category(self, client):
        r = client.post(f"{BASE_URL}/api/inventory/materials", json={
            "name": "TEST_Bad", "category": "invalid_cat", "unit": "roll",
        })
        assert r.status_code == 400

    def test_invalid_unit(self, client):
        r = client.post(f"{BASE_URL}/api/inventory/materials", json={
            "name": "TEST_Bad2", "category": "flexy", "unit": "gallon",
        })
        assert r.status_code == 400

    def test_update_material(self, client, created_ids):
        mid = created_ids["materials"][0]
        payload = {
            "name": "TEST_Sticker Ritrama Updated",
            "category": "sticker",
            "unit": "roll",
            "current_stock": 3.75,
            "purchase_price": 800000,
            "min_stock": 1,
            "active": True,
        }
        r = client.put(f"{BASE_URL}/api/inventory/materials/{mid}", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["current_stock"] == 3.75
        assert data["purchase_price"] == 800000
        assert data["name"] == "TEST_Sticker Ritrama Updated"


# ----- Stock-In -----
class TestStockIn:
    def test_create_stock_in_increases_stock(self, client, created_ids):
        mid = created_ids["materials"][0]
        # Get current stock (was 3.75 after update)
        mats = client.get(f"{BASE_URL}/api/inventory/materials").json()
        mat_before = next(m for m in mats if m["id"] == mid)
        stock_before = float(mat_before["current_stock"])

        payload = {
            "material_id": mid,
            "quantity": 1.5,
            "unit_price": 780000,
            "supplier": "PT TEST",
            "invoice_no": "INV-TEST-001",
            "date": "2026-01-15",
            "notes": "TEST",
        }
        r = client.post(f"{BASE_URL}/api/inventory/stock-in", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["quantity"] == 1.5
        assert d["total_price"] == round(1.5 * 780000, 2)
        assert d["new_stock"] == round(stock_before + 1.5, 4)
        assert "id" in d
        created_ids["stock_in"].append(d["id"])

        # Verify persisted increase
        mats2 = client.get(f"{BASE_URL}/api/inventory/materials").json()
        mat_after = next(m for m in mats2 if m["id"] == mid)
        assert float(mat_after["current_stock"]) == round(stock_before + 1.5, 4)
        # purchase_price updates to latest unit_price
        assert float(mat_after["purchase_price"]) == 780000

    def test_stock_in_quantity_zero_rejected(self, client, created_ids):
        mid = created_ids["materials"][0]
        r = client.post(f"{BASE_URL}/api/inventory/stock-in", json={
            "material_id": mid, "quantity": 0, "unit_price": 100000, "date": "2026-01-15",
        })
        assert r.status_code == 400

    def test_stock_in_negative_rejected(self, client, created_ids):
        mid = created_ids["materials"][0]
        r = client.post(f"{BASE_URL}/api/inventory/stock-in", json={
            "material_id": mid, "quantity": -1, "unit_price": 100000, "date": "2026-01-15",
        })
        assert r.status_code == 400

    def test_stock_in_unknown_material(self, client):
        r = client.post(f"{BASE_URL}/api/inventory/stock-in", json={
            "material_id": "nonexistent-id", "quantity": 1, "unit_price": 100, "date": "2026-01-15",
        })
        assert r.status_code == 404

    def test_list_stock_in_enriched(self, client, created_ids):
        r = client.get(f"{BASE_URL}/api/inventory/stock-in")
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        assert any(it["id"] == created_ids["stock_in"][0] for it in items)
        it = next(i for i in items if i["id"] == created_ids["stock_in"][0])
        assert it.get("material_name")
        assert it.get("material_unit")
        assert it.get("material_category")


# ----- Waste -----
class TestWaste:
    def test_create_waste_decreases_stock_and_computes_loss(self, client, created_ids):
        mid = created_ids["materials"][0]
        mats = client.get(f"{BASE_URL}/api/inventory/materials").json()
        mat_before = next(m for m in mats if m["id"] == mid)
        stock_before = float(mat_before["current_stock"])
        price = float(mat_before["purchase_price"])  # should be 780000

        payload = {
            "material_id": mid,
            "quantity": 0.75,
            "reason": "rusak",
            "date": "2026-01-15",
            "reported_by": "TEST User",
            "notes": "TEST",
        }
        r = client.post(f"{BASE_URL}/api/inventory/waste", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["quantity"] == 0.75
        # estimated_loss = quantity * material.purchase_price
        assert d["estimated_loss"] == round(0.75 * price, 2)
        assert d["new_stock"] == round(stock_before - 0.75, 4)
        created_ids["waste"].append(d["id"])

        # Verify stock persisted
        mats2 = client.get(f"{BASE_URL}/api/inventory/materials").json()
        mat_after = next(m for m in mats2 if m["id"] == mid)
        assert float(mat_after["current_stock"]) == round(stock_before - 0.75, 4)

    def test_waste_invalid_reason_rejected(self, client, created_ids):
        mid = created_ids["materials"][0]
        r = client.post(f"{BASE_URL}/api/inventory/waste", json={
            "material_id": mid, "quantity": 0.5, "reason": "invalid_reason", "date": "2026-01-15",
        })
        assert r.status_code == 400

    def test_waste_quantity_zero_rejected(self, client, created_ids):
        mid = created_ids["materials"][0]
        r = client.post(f"{BASE_URL}/api/inventory/waste", json={
            "material_id": mid, "quantity": 0, "reason": "rusak", "date": "2026-01-15",
        })
        assert r.status_code == 400


# ----- Stats -----
class TestStats:
    def test_stats_shape(self, client):
        r = client.get(f"{BASE_URL}/api/inventory/stats")
        assert r.status_code == 200
        d = r.json()
        for k in ("total_materials", "total_stock_value", "low_stock_count", "low_stock", "total_waste_this_month"):
            assert k in d, f"missing key {k}"
        assert isinstance(d["low_stock"], list)
        assert isinstance(d["total_stock_value"], (int, float))
        assert isinstance(d["total_waste_this_month"], (int, float))


# ----- Rollback on delete -----
class TestRollbackAndCleanup:
    def test_delete_waste_restores_stock(self, client, created_ids):
        mid = created_ids["materials"][0]
        mats = client.get(f"{BASE_URL}/api/inventory/materials").json()
        stock_before = float(next(m for m in mats if m["id"] == mid)["current_stock"])
        wid = created_ids["waste"][0]
        r = client.delete(f"{BASE_URL}/api/inventory/waste/{wid}")
        assert r.status_code == 200
        mats2 = client.get(f"{BASE_URL}/api/inventory/materials").json()
        stock_after = float(next(m for m in mats2 if m["id"] == mid)["current_stock"])
        assert stock_after == round(stock_before + 0.75, 4)

    def test_delete_stock_in_reverses_stock(self, client, created_ids):
        mid = created_ids["materials"][0]
        mats = client.get(f"{BASE_URL}/api/inventory/materials").json()
        stock_before = float(next(m for m in mats if m["id"] == mid)["current_stock"])
        sid = created_ids["stock_in"][0]
        r = client.delete(f"{BASE_URL}/api/inventory/stock-in/{sid}")
        assert r.status_code == 200
        mats2 = client.get(f"{BASE_URL}/api/inventory/materials").json()
        stock_after = float(next(m for m in mats2 if m["id"] == mid)["current_stock"])
        assert stock_after == round(stock_before - 1.5, 4)

    def test_delete_material_hard_delete_when_no_history(self, client, created_ids):
        # After deleting waste & stock-in, no history exists; expect hard delete
        mid = created_ids["materials"][0]
        r = client.delete(f"{BASE_URL}/api/inventory/materials/{mid}")
        assert r.status_code == 200
        assert r.json().get("soft_deleted") is False
        # verify gone
        mats = client.get(f"{BASE_URL}/api/inventory/materials").json()
        assert all(m["id"] != mid for m in mats)


# ----- Soft-delete behavior -----
class TestSoftDelete:
    def test_material_with_history_is_soft_deleted(self, client):
        # Create fresh material + stock-in, then delete the material
        r = client.post(f"{BASE_URL}/api/inventory/materials", json={
            "name": "TEST_SoftDelete Mat", "category": "flexy", "unit": "meter",
            "current_stock": 0, "purchase_price": 1000, "min_stock": 0, "active": True,
        })
        assert r.status_code == 200
        mid = r.json()["id"]
        r2 = client.post(f"{BASE_URL}/api/inventory/stock-in", json={
            "material_id": mid, "quantity": 1, "unit_price": 1000, "date": "2026-01-15",
        })
        assert r2.status_code == 200
        sid = r2.json()["id"]
        # Delete material -> should soft-delete
        r3 = client.delete(f"{BASE_URL}/api/inventory/materials/{mid}")
        assert r3.status_code == 200
        assert r3.json().get("soft_deleted") is True
        # confirm active=false
        mats = client.get(f"{BASE_URL}/api/inventory/materials").json()
        mat = next(m for m in mats if m["id"] == mid)
        assert mat.get("active") is False
        # cleanup: delete stock-in then hard delete material
        client.delete(f"{BASE_URL}/api/inventory/stock-in/{sid}")
        client.delete(f"{BASE_URL}/api/inventory/materials/{mid}")
