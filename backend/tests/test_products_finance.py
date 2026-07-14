"""Tests for Master Produk finance fields: current_stock, purchase_price, bom_cost, stock_value.

Coverage:
- ProductIn accepts current_stock & purchase_price
- Backward compat: defaults 0 when omitted
- _enrich_product computes bom_cost from components (component.quantity × material.purchase_price)
- _enrich_product computes stock_value = current_stock × purchase_price
- PUT preserves new fields
- Regression: sale does NOT auto-decrement product.current_stock
"""
import os
import uuid
import pytest
import requests
from pathlib import Path

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

TAG = f"TEST_PF_{uuid.uuid4().hex[:6]}"


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
    """Kertas ArtPaper 120 - purchase_price 2000, stock 500."""
    r = client.post(f"{BASE_URL}/api/inventory/materials", json={
        "name": f"{TAG}_Kertas ArtPaper 120", "category": "lainnya", "unit": "pcs",
        "current_stock": 500, "purchase_price": 2000, "min_stock": 0, "active": True,
    })
    assert r.status_code == 200, r.text
    mat = r.json()
    yield mat
    try:
        client.delete(f"{BASE_URL}/api/inventory/materials/{mat['id']}")
    except Exception:
        pass


@pytest.fixture(scope="module")
def state():
    return {"pids": []}


class TestProductFinanceFields:
    def test_create_product_with_finance_fields(self, client, material, state):
        payload = {
            "name": f"{TAG}_Cetak Brosur 120gr",
            "pricing_mode": "fixed",
            "unit_price": 20000,
            "purchase_price": 5000,
            "current_stock": 100,
            "components": [
                {"material_id": material["id"], "formula": "per_qty", "quantity": 1},
            ],
            "active": True,
        }
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 200, r.text
        p = r.json()
        state["pids"].append(p["id"])
        # Persistence assertions
        assert p["current_stock"] == 100
        assert p["purchase_price"] == 5000
        # Enrichment: bom_cost = 1 (quantity) × 2000 (material.purchase_price) = 2000
        assert p["bom_cost"] == 2000, f"expected bom_cost 2000, got {p.get('bom_cost')}"
        # stock_value = 100 × 5000 = 500000
        assert p["stock_value"] == 500000, f"expected 500000, got {p.get('stock_value')}"
        # Component enriched with material_purchase_price
        assert p["components"][0]["material_purchase_price"] == 2000

    def test_get_product_returns_enriched_fields(self, client, state):
        pid = state["pids"][0]
        r = client.get(f"{BASE_URL}/api/products/{pid}")
        assert r.status_code == 200
        p = r.json()
        assert p["bom_cost"] == 2000
        assert p["stock_value"] == 500000
        assert p["components"][0]["material_purchase_price"] == 2000
        assert "_id" not in p

    def test_update_product_finance_fields(self, client, material, state):
        pid = state["pids"][0]
        payload = {
            "name": f"{TAG}_Cetak Brosur 120gr",
            "pricing_mode": "fixed",
            "unit_price": 20000,
            "purchase_price": 15000,
            "current_stock": 25,
            "components": [
                {"material_id": material["id"], "formula": "per_qty", "quantity": 1},
            ],
            "active": True,
        }
        r = client.put(f"{BASE_URL}/api/products/{pid}", json=payload)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["current_stock"] == 25
        assert p["purchase_price"] == 15000
        # stock_value = 25 × 15000 = 375000
        assert p["stock_value"] == 375000
        # bom_cost unchanged (still 2000)
        assert p["bom_cost"] == 2000

        # Verify persisted via GET
        r2 = client.get(f"{BASE_URL}/api/products/{pid}")
        assert r2.status_code == 200
        p2 = r2.json()
        assert p2["current_stock"] == 25
        assert p2["purchase_price"] == 15000
        assert p2["stock_value"] == 375000

    def test_backward_compat_default_zero(self, client, state):
        """POST without current_stock/purchase_price → defaults to 0."""
        payload = {
            "name": f"{TAG}_Legacy Product",
            "pricing_mode": "fixed",
            "unit_price": 10000,
            "components": [],
            "active": True,
        }
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 200, r.text
        p = r.json()
        state["pids"].append(p["id"])
        assert p["current_stock"] == 0
        assert p["purchase_price"] == 0
        assert p["bom_cost"] == 0
        assert p["stock_value"] == 0

    def test_list_products_returns_enriched(self, client, state):
        r = client.get(f"{BASE_URL}/api/products")
        assert r.status_code == 200
        items = r.json()
        # Find our product
        p = next((x for x in items if x["id"] == state["pids"][0]), None)
        assert p is not None
        assert p["stock_value"] == 375000
        assert p["bom_cost"] == 2000

    def test_sale_does_not_decrement_product_stock(self, client, material, state):
        """Regression: creating a sale should NOT auto-decrement product.current_stock.
        (Only material stock decrements.)"""
        pid = state["pids"][0]
        # Snapshot BEFORE sale
        p_before = client.get(f"{BASE_URL}/api/products/{pid}").json()
        product_stock_before = p_before["current_stock"]

        mats = client.get(f"{BASE_URL}/api/inventory/materials").json()
        mat_before = next(m for m in mats if m["id"] == material["id"])["current_stock"]

        # Create sale with 5 units
        r = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": f"{TAG}_Cust",
            "items": [{
                "product_id": pid, "product_name": p_before["name"],
                "length_m": 0, "width_m": 0, "quantity": 5, "unit_price": 20000,
            }],
            "cash_paid": 100000, "payment_method": "tunai",
        })
        assert r.status_code == 200, r.text
        sale = r.json()
        state.setdefault("sids", []).append(sale["id"])

        # Product stock UNCHANGED
        p_after = client.get(f"{BASE_URL}/api/products/{pid}").json()
        assert p_after["current_stock"] == product_stock_before, \
            f"Product stock should NOT auto-decrement: before={product_stock_before}, after={p_after['current_stock']}"

        # Material stock DECREMENTED by 5 (per_qty × 5 = 5)
        mats2 = client.get(f"{BASE_URL}/api/inventory/materials").json()
        mat_after = next(m for m in mats2 if m["id"] == material["id"])["current_stock"]
        assert mat_after == round(mat_before - 5, 4)

    def test_zzz_cleanup(self, client, state):
        for sid in state.get("sids", []):
            try:
                client.delete(f"{BASE_URL}/api/sales/{sid}")
            except Exception:
                pass
        for pid in state["pids"]:
            try:
                client.delete(f"{BASE_URL}/api/products/{pid}")
            except Exception:
                pass
