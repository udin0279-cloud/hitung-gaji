"""Backend tests for Purchasing module (suppliers, PO, price history, stats)."""
import os
import time
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

TS = str(int(time.time()))


# ---- helper: create test material if needed
def _ensure_material(auth_client, name_prefix="TEST_MAT"):
    r = auth_client.get(f"{BASE_URL}/api/inventory/materials")
    assert r.status_code == 200, r.text
    mats = r.json()
    # Reuse existing test material if any
    for m in mats:
        if m.get("name", "").startswith(name_prefix):
            return m
    # Create
    payload = {
        "name": f"{name_prefix}_{TS}",
        "unit": "pcs",
        "category": "lainnya",
        "purchase_price": 10000,
        "selling_price": 15000,
        "current_stock": 0,
        "active": True,
    }
    r = auth_client.post(f"{BASE_URL}/api/inventory/materials", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ---- Supplier CRUD tests
class TestSupplierCRUD:
    def test_supplier_create_and_list(self, auth_client):
        name = f"TEST_Sup_{TS}"
        r = auth_client.post(f"{BASE_URL}/api/purchasing/suppliers", json={
            "name": name, "phone": "0812", "email": "t@test.id", "contact_person": "Pak A"
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["name"] == name
        assert "id" in data
        pytest.supplier_id = data["id"]

        # list with enrich
        r = auth_client.get(f"{BASE_URL}/api/purchasing/suppliers")
        assert r.status_code == 200
        arr = r.json()
        s = next((x for x in arr if x["id"] == data["id"]), None)
        assert s is not None
        assert "po_count" in s and "total_purchase" in s and "outstanding" in s

    def test_supplier_duplicate_case_insensitive(self, auth_client):
        name = f"TEST_Sup_{TS}"  # already exists
        r = auth_client.post(f"{BASE_URL}/api/purchasing/suppliers", json={"name": name.upper()})
        assert r.status_code == 400, f"Expected 400 dup, got {r.status_code}: {r.text}"

    def test_supplier_empty_name(self, auth_client):
        r = auth_client.post(f"{BASE_URL}/api/purchasing/suppliers", json={"name": "  "})
        assert r.status_code == 400

    def test_supplier_update(self, auth_client):
        sid = pytest.supplier_id
        r = auth_client.put(f"{BASE_URL}/api/purchasing/suppliers/{sid}", json={
            "name": f"TEST_Sup_{TS}", "phone": "0899", "email": "n@test.id"
        })
        assert r.status_code == 200, r.text
        assert r.json()["phone"] == "0899"


# ---- PO CRUD tests
class TestPurchaseOrder:
    def test_po_create_requires_items(self, auth_client):
        r = auth_client.post(f"{BASE_URL}/api/purchasing/purchase-orders", json={
            "supplier_id": pytest.supplier_id, "date": "2026-01-15", "items": []
        })
        assert r.status_code == 400

    def test_po_create_success(self, auth_client):
        mat = _ensure_material(auth_client)
        pytest.material_id = mat["id"]
        payload = {
            "supplier_id": pytest.supplier_id,
            "date": "2026-01-15",
            "tax_pct": 11,
            "items": [{"material_id": mat["id"], "quantity": 10, "unit_price": 5000}],
            "invoice_no": f"INV-TEST-{TS}",
        }
        r = auth_client.post(f"{BASE_URL}/api/purchasing/purchase-orders", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "draft"
        assert d["payment_status"] == "belum_lunas"
        assert d["po_no"].startswith("PO-")
        # subtotal 50000, tax 5500, total 55500
        assert d["subtotal"] == 50000
        assert d["tax_amount"] == 5500
        assert d["total"] == 55500
        assert d["amount_paid"] == 0
        pytest.po_id = d["id"]
        pytest.po_total = d["total"]
        pytest.po_no = d["po_no"]

    def test_po_list_enriched(self, auth_client):
        r = auth_client.get(f"{BASE_URL}/api/purchasing/purchase-orders")
        assert r.status_code == 200
        found = next((p for p in r.json() if p["id"] == pytest.po_id), None)
        assert found is not None
        assert found["items"][0].get("material_name")

    def test_po_pay_partial(self, auth_client):
        r = auth_client.put(f"{BASE_URL}/api/purchasing/purchase-orders/{pytest.po_id}/pay",
                            json={"amount": 10000})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["payment_status"] == "sebagian"
        assert d["amount_paid"] == 10000

    def test_po_pay_negative_rejected(self, auth_client):
        r = auth_client.put(f"{BASE_URL}/api/purchasing/purchase-orders/{pytest.po_id}/pay",
                            json={"amount": -100})
        assert r.status_code == 400

    def test_po_receive_updates_stock_and_price(self, auth_client):
        # Get material state before
        r = auth_client.get(f"{BASE_URL}/api/inventory/materials")
        mat_before = next(m for m in r.json() if m["id"] == pytest.material_id)
        stock_before = float(mat_before.get("current_stock", 0))

        r = auth_client.put(f"{BASE_URL}/api/purchasing/purchase-orders/{pytest.po_id}/receive")
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

        # Verify PO status
        r = auth_client.get(f"{BASE_URL}/api/purchasing/purchase-orders")
        po = next(p for p in r.json() if p["id"] == pytest.po_id)
        assert po["status"] == "diterima"

        # Verify material stock updated (+10) and purchase_price=5000
        r = auth_client.get(f"{BASE_URL}/api/inventory/materials")
        mat_after = next(m for m in r.json() if m["id"] == pytest.material_id)
        assert abs(float(mat_after["current_stock"]) - (stock_before + 10)) < 0.001, \
            f"Stock: before={stock_before}, after={mat_after['current_stock']}"
        assert float(mat_after["purchase_price"]) == 5000

    def test_po_receive_idempotent(self, auth_client):
        r = auth_client.put(f"{BASE_URL}/api/purchasing/purchase-orders/{pytest.po_id}/receive")
        assert r.status_code == 200
        assert r.json().get("already") is True

    def test_po_pay_lunas(self, auth_client):
        # Remaining = 55500 - 10000 = 45500. Pay all.
        r = auth_client.put(f"{BASE_URL}/api/purchasing/purchase-orders/{pytest.po_id}/pay",
                            json={"amount": 45500})
        assert r.status_code == 200
        d = r.json()
        assert d["payment_status"] == "lunas"
        assert d["amount_paid"] == 55500

    def test_po_cancel_rejects_received(self, auth_client):
        r = auth_client.put(f"{BASE_URL}/api/purchasing/purchase-orders/{pytest.po_id}/cancel")
        assert r.status_code == 400

    def test_price_history_grouped(self, auth_client):
        r = auth_client.get(f"{BASE_URL}/api/purchasing/price-history")
        assert r.status_code == 200
        d = r.json()
        assert "items" in d
        row = next((x for x in d["items"] if x["material_id"] == pytest.material_id), None)
        assert row is not None
        assert row["history"], "History should be non-empty after PO receive"
        assert row["current_price"] == 5000
        assert row["first_price"] > 0
        assert "min_price" in row and "max_price" in row and "avg_price" in row and "change_pct" in row

    def test_stats(self, auth_client):
        r = auth_client.get(f"{BASE_URL}/api/purchasing/stats")
        assert r.status_code == 200
        d = r.json()
        for k in ("total_po", "total_purchase", "outstanding", "unpaid_pos", "total_suppliers"):
            assert k in d
        assert d["total_po"] >= 1
        assert d["total_suppliers"] >= 1

    def test_po_delete_received_rollback_stock(self, auth_client):
        # Snapshot stock
        r = auth_client.get(f"{BASE_URL}/api/inventory/materials")
        mat_before = next(m for m in r.json() if m["id"] == pytest.material_id)
        stock_before = float(mat_before["current_stock"])

        r = auth_client.delete(f"{BASE_URL}/api/purchasing/purchase-orders/{pytest.po_id}")
        assert r.status_code == 200

        # Stock decreased by 10
        r = auth_client.get(f"{BASE_URL}/api/inventory/materials")
        mat_after = next(m for m in r.json() if m["id"] == pytest.material_id)
        assert abs(float(mat_after["current_stock"]) - (stock_before - 10)) < 0.001, \
            f"Rollback failed: before={stock_before}, after={mat_after['current_stock']}"

        # PO gone
        r = auth_client.get(f"{BASE_URL}/api/purchasing/purchase-orders")
        assert not any(p["id"] == pytest.po_id for p in r.json())


class TestPOCancel:
    def test_create_and_cancel_draft(self, auth_client):
        mat_id = pytest.material_id
        r = auth_client.post(f"{BASE_URL}/api/purchasing/purchase-orders", json={
            "supplier_id": pytest.supplier_id,
            "date": "2026-01-15",
            "items": [{"material_id": mat_id, "quantity": 5, "unit_price": 3000}],
        })
        assert r.status_code == 200
        po_id = r.json()["id"]
        r = auth_client.put(f"{BASE_URL}/api/purchasing/purchase-orders/{po_id}/cancel")
        assert r.status_code == 200
        # cleanup
        auth_client.delete(f"{BASE_URL}/api/purchasing/purchase-orders/{po_id}")


class TestSupplierDelete:
    def test_supplier_soft_delete_when_has_po(self, auth_client):
        # Create supplier + PO, then delete supplier — should soft-delete
        mat_id = pytest.material_id
        # New sup
        r = auth_client.post(f"{BASE_URL}/api/purchasing/suppliers", json={"name": f"TEST_SupSoft_{TS}"})
        assert r.status_code == 200
        sid = r.json()["id"]
        # PO
        r = auth_client.post(f"{BASE_URL}/api/purchasing/purchase-orders", json={
            "supplier_id": sid, "date": "2026-01-15",
            "items": [{"material_id": mat_id, "quantity": 1, "unit_price": 100}],
        })
        assert r.status_code == 200
        po_id = r.json()["id"]
        # Delete supplier
        r = auth_client.delete(f"{BASE_URL}/api/purchasing/suppliers/{sid}")
        assert r.status_code == 200
        assert r.json().get("soft_deleted") is True
        # cleanup PO then hard delete supplier
        auth_client.delete(f"{BASE_URL}/api/purchasing/purchase-orders/{po_id}")

    def test_supplier_hard_delete_when_no_po(self, auth_client):
        r = auth_client.post(f"{BASE_URL}/api/purchasing/suppliers", json={"name": f"TEST_SupHard_{TS}"})
        assert r.status_code == 200
        sid = r.json()["id"]
        r = auth_client.delete(f"{BASE_URL}/api/purchasing/suppliers/{sid}")
        assert r.status_code == 200
        assert r.json().get("soft_deleted") is False


# ---- Cleanup after all tests
def test_zzz_cleanup(auth_client):
    """Final cleanup — delete created supplier."""
    if hasattr(pytest, "supplier_id"):
        auth_client.delete(f"{BASE_URL}/api/purchasing/suppliers/{pytest.supplier_id}")
