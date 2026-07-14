"""Backend verification for the "Cetak Brosur 120 gr" bug scenario.

Scope:
- Create material "Kertas ArtPaper 120" (pcs, stock 100, price 2000).
- Create product "Cetak Brosur 120 gr" with pricing_mode=fixed, unit_price=32200,
  components=[{Kertas ArtPaper 120, formula=per_qty, qty=1}], active=True.
- Verify GET /api/products?only_active=true returns the product with active=True.
- POST /api/sales qty=5 → subtotal=161000, consumption=5, stock 100->95.
- DELETE the sale → stock restored to 100.
- Cleanup.
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

TAG = f"TESTBROSUR_{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def artifacts():
    return {"material_id": None, "product_id": None, "sale_id": None}


def _get_material_stock(client, mid):
    mats = client.get(f"{BASE_URL}/api/inventory/materials").json()
    mat = next((m for m in mats if m["id"] == mid), None)
    return float(mat["current_stock"]) if mat else None


class TestBrosurBOMFlow:
    def test_01_create_material_artpaper120(self, client, artifacts):
        r = client.post(f"{BASE_URL}/api/inventory/materials", json={
            "name": f"{TAG}_Kertas ArtPaper 120",
            "category": "lainnya",
            "unit": "pcs",
            "current_stock": 100,
            "purchase_price": 2000,
            "min_stock": 0,
            "active": True,
        })
        assert r.status_code == 200, r.text
        m = r.json()
        artifacts["material_id"] = m["id"]
        assert m["current_stock"] == 100
        assert m["active"] is True

    def test_02_create_product_cetak_brosur(self, client, artifacts):
        payload = {
            "code": f"{TAG}-P03",
            "name": f"{TAG}_Cetak Brosur 120 gr",
            "category": "Material Promosi Cetak",
            "pricing_mode": "fixed",
            "unit_price": 32200,
            "active": True,
            "components": [
                {"material_id": artifacts["material_id"], "formula": "per_qty", "quantity": 1}
            ],
        }
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 200, r.text
        p = r.json()
        artifacts["product_id"] = p["id"]
        assert p["active"] is True
        assert p["pricing_mode"] == "fixed"
        assert p["unit_price"] == 32200
        assert p.get("requires_dimensions") is False  # per_qty only, no L/W required
        assert len(p["components"]) == 1
        assert p["components"][0]["formula"] == "per_qty"

    def test_03_product_appears_in_only_active_list(self, client, artifacts):
        r = client.get(f"{BASE_URL}/api/products", params={"only_active": "true"})
        assert r.status_code == 200
        lst = r.json()
        assert isinstance(lst, list)
        found = next((p for p in lst if p["id"] == artifacts["product_id"]), None)
        assert found is not None, "Product not returned by GET /api/products?only_active=true"
        assert found["active"] is True
        assert found["name"] == f"{TAG}_Cetak Brosur 120 gr"

    def test_04_post_sale_qty_5_reduces_stock(self, client, artifacts):
        before = _get_material_stock(client, artifacts["material_id"])
        assert before == 100

        r = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": f"{TAG}_CustBrosur",
            "items": [{
                "product_id": artifacts["product_id"],
                "product_name": "Cetak Brosur 120 gr",
                "quantity": 5,
                "unit_price": 32200,
                # No length/width — fixed pricing, per_qty formula
            }],
            "cash_paid": 161000,
            "payment_method": "tunai",
        })
        assert r.status_code == 200, r.text
        sale = r.json()
        artifacts["sale_id"] = sale["id"]

        # (a) subtotal
        assert sale["subtotal"] == 32200 * 5
        assert sale["total"] == 32200 * 5
        it = sale["items"][0]
        assert it["subtotal"] == 161000
        # (b) consumption = 5
        assert len(it["components"]) == 1
        assert it["components"][0]["consumption"] == 5
        assert it["components"][0]["formula"] == "per_qty"
        # (c) stock 100 -> 95
        after = _get_material_stock(client, artifacts["material_id"])
        assert after == 95, f"Stock should be 95 after sale of 5 units, got {after}"

    def test_05_delete_sale_restores_stock(self, client, artifacts):
        r = client.delete(f"{BASE_URL}/api/sales/{artifacts['sale_id']}")
        assert r.status_code == 200
        after = _get_material_stock(client, artifacts["material_id"])
        assert after == 100, f"Stock should be restored to 100, got {after}"
        artifacts["sale_id"] = None

    def test_06_regression_optgroup_data_available(self, client):
        """Sanity check: both endpoints the Kasir dropdown depends on must be reachable."""
        p = client.get(f"{BASE_URL}/api/products", params={"only_active": "true"})
        assert p.status_code == 200
        m = client.get(f"{BASE_URL}/api/inventory/materials")
        assert m.status_code == 200
        assert isinstance(p.json(), list) and isinstance(m.json(), list)

    def test_99_cleanup(self, client, artifacts):
        if artifacts.get("sale_id"):
            client.delete(f"{BASE_URL}/api/sales/{artifacts['sale_id']}")
        if artifacts.get("product_id"):
            client.delete(f"{BASE_URL}/api/products/{artifacts['product_id']}")
        if artifacts.get("material_id"):
            client.delete(f"{BASE_URL}/api/inventory/materials/{artifacts['material_id']}")
