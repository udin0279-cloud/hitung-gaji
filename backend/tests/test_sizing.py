"""Tests for SIZING feature: Product has_sizes/sizes/price_size_a/b + quantity_size_b + Sale item size + tier auto-pricing/consumption."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break


# ---------------- Fixtures ----------------

@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code}")
    return s


@pytest.fixture(scope="module")
def kaos_material(client):
    payload = {
        "name": f"TEST_SIZING_Kain_{uuid.uuid4().hex[:6]}",
        "category": "kain",
        "unit": "meter",
        "current_stock": 1000.0,
        "purchase_price": 20000,
        "selling_price": 0,
        "min_stock": 5,
        "active": True,
    }
    r = client.post(f"{BASE_URL}/api/inventory/materials", json=payload)
    assert r.status_code == 200, r.text
    mat = r.json()
    yield mat
    client.delete(f"{BASE_URL}/api/inventory/materials/{mat['id']}")


@pytest.fixture(scope="module")
def created_products():
    return []


@pytest.fixture(scope="module")
def created_sales():
    return []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client, created_products, created_sales):
    yield
    for sid in created_sales:
        try:
            client.delete(f"{BASE_URL}/api/sales/{sid}")
        except Exception:
            pass
    for pid in created_products:
        try:
            client.delete(f"{BASE_URL}/api/products/{pid}")
        except Exception:
            pass


def _mk_kaos_payload(kaos_material, **overrides):
    payload = {
        "name": f"TEST_SIZING_Kaos_{uuid.uuid4().hex[:6]}",
        "category": "kaos",
        "pricing_mode": "fixed",
        "unit_price": 0,
        "current_stock": 0,
        "components": [
            {"material_id": kaos_material["id"], "formula": "per_qty", "quantity": 1.0, "quantity_size_b": 1.2},
        ],
        "active": True,
        "has_sizes": True,
        "sizes": ["S", "M", "L", "XL", "XXL"],
        "price_size_a": 85000,
        "price_size_b": 95000,
    }
    payload.update(overrides)
    return payload


# ---------------- Products create with sizing ----------------

class TestProductCreateSizing:
    def test_create_product_with_full_sizing(self, client, kaos_material, created_products):
        payload = _mk_kaos_payload(kaos_material)
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 200, r.text
        p = r.json()
        created_products.append(p["id"])
        assert p["has_sizes"] is True
        assert p["sizes"] == ["S", "M", "L", "XL", "XXL"]
        assert p["price_size_a"] == 85000
        assert p["price_size_b"] == 95000
        # component preserved with quantity_size_b
        assert len(p["components"]) == 1
        c0 = p["components"][0]
        assert c0["quantity"] == 1.0
        assert c0.get("quantity_size_b") == 1.2

        # GET verifies persistence
        g = client.get(f"{BASE_URL}/api/products/{p['id']}")
        # products endpoint returns list, use list endpoint
        r2 = client.get(f"{BASE_URL}/api/products").json()
        found = [x for x in r2 if x["id"] == p["id"]][0]
        assert found["has_sizes"] is True
        assert found["price_size_a"] == 85000
        assert found["price_size_b"] == 95000
        assert found["components"][0]["quantity_size_b"] == 1.2

    def test_reject_has_sizes_empty_sizes(self, client, kaos_material):
        payload = _mk_kaos_payload(kaos_material, sizes=[])
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 400, r.text
        assert "ukuran" in r.json().get("detail", "").lower()

    def test_reject_price_a_zero(self, client, kaos_material):
        payload = _mk_kaos_payload(kaos_material, price_size_a=0)
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 400, r.text
        assert "S-XL" in r.json().get("detail", "")

    def test_reject_price_b_zero_when_tier_b_present(self, client, kaos_material):
        payload = _mk_kaos_payload(kaos_material, sizes=["M", "L", "XXL"], price_size_b=0)
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 400, r.text
        assert "XXL" in r.json().get("detail", "")

    def test_allow_price_b_zero_when_only_tier_a(self, client, kaos_material, created_products):
        """Kalau hanya pilih S/M/L/XL, price_size_b boleh 0."""
        payload = _mk_kaos_payload(kaos_material, sizes=["S", "M", "L", "XL"], price_size_b=0)
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 200, r.text
        created_products.append(r.json()["id"])


# ---------------- Products update with sizing ----------------

class TestProductUpdateSizing:
    def test_update_sizing_fields_persist(self, client, kaos_material, created_products):
        # create initial
        payload = _mk_kaos_payload(kaos_material)
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 200
        p = r.json()
        created_products.append(p["id"])

        # update: extend to XXXL, change prices, change component quantity_size_b
        upd = dict(payload)
        upd["sizes"] = ["M", "L", "XL", "XXL", "XXXL"]
        upd["price_size_a"] = 90000
        upd["price_size_b"] = 100000
        upd["components"] = [
            {"material_id": kaos_material["id"], "formula": "per_qty", "quantity": 1.0, "quantity_size_b": 1.5},
        ]
        r2 = client.put(f"{BASE_URL}/api/products/{p['id']}", json=upd)
        assert r2.status_code == 200, r2.text
        u = r2.json()
        assert u["sizes"] == ["M", "L", "XL", "XXL", "XXXL"]
        assert u["price_size_a"] == 90000
        assert u["price_size_b"] == 100000
        assert u["components"][0]["quantity_size_b"] == 1.5

        # verify persisted via list
        found = [x for x in client.get(f"{BASE_URL}/api/products").json() if x["id"] == p["id"]][0]
        assert found["price_size_a"] == 90000
        assert found["price_size_b"] == 100000
        assert found["sizes"] == ["M", "L", "XL", "XXL", "XXXL"]

    def test_update_turn_off_has_sizes_clears_fields(self, client, kaos_material, created_products):
        payload = _mk_kaos_payload(kaos_material)
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 200
        p = r.json()
        created_products.append(p["id"])

        # update: has_sizes false + set unit_price
        upd = dict(payload)
        upd["has_sizes"] = False
        upd["sizes"] = []
        upd["price_size_a"] = 0
        upd["price_size_b"] = 0
        upd["unit_price"] = 50000
        r2 = client.put(f"{BASE_URL}/api/products/{p['id']}", json=upd)
        assert r2.status_code == 200, r2.text
        u = r2.json()
        assert u["has_sizes"] is False
        assert u["sizes"] == []
        assert u["price_size_a"] == 0
        assert u["price_size_b"] == 0


# ---------------- Sales with size ----------------

@pytest.fixture(scope="module")
def sizing_product(client, kaos_material, created_products):
    payload = _mk_kaos_payload(kaos_material)
    r = client.post(f"{BASE_URL}/api/products", json=payload)
    assert r.status_code == 200, r.text
    p = r.json()
    created_products.append(p["id"])
    return p


class TestSalesSizing:
    def test_sale_tier_a_M(self, client, kaos_material, sizing_product, created_sales):
        # snapshot material stock
        m0 = [m for m in client.get(f"{BASE_URL}/api/inventory/materials").json() if m["id"] == kaos_material["id"]][0]
        s0 = float(m0["current_stock"])

        payload = {
            "items": [{
                "product_id": sizing_product["id"],
                "product_name": sizing_product["name"],
                "quantity": 2,
                "unit_price": 0,   # should be overridden by tier
                "size": "M",
            }],
            "cash_paid": 200000,
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])
        it = sale["items"][0]
        assert it["size"] == "M"
        assert it["size_tier"] == "A"
        assert it["unit_price"] == 85000
        assert it["subtotal"] == 85000 * 2
        # consumption per unit = 1.0 * 2 = 2.0
        cons = it["components"][0]["consumption"]
        assert abs(cons - 2.0) < 1e-6, f"expected 2.0 got {cons}"
        # material stock decreased by 2.0
        m1 = [m for m in client.get(f"{BASE_URL}/api/inventory/materials").json() if m["id"] == kaos_material["id"]][0]
        assert abs(float(m1["current_stock"]) - (s0 - 2.0)) < 1e-6

    def test_sale_tier_b_XXL(self, client, kaos_material, sizing_product, created_sales):
        m0 = [m for m in client.get(f"{BASE_URL}/api/inventory/materials").json() if m["id"] == kaos_material["id"]][0]
        s0 = float(m0["current_stock"])

        payload = {
            "items": [{
                "product_id": sizing_product["id"],
                "product_name": sizing_product["name"],
                "quantity": 1,
                "unit_price": 0,
                "size": "XXL",
            }],
            "cash_paid": 100000,
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])
        it = sale["items"][0]
        assert it["size"] == "XXL"
        assert it["size_tier"] == "B"
        assert it["unit_price"] == 95000
        assert it["subtotal"] == 95000
        # consumption per unit factor 1.2 * qty 1 = 1.2
        cons = it["components"][0]["consumption"]
        assert abs(cons - 1.2) < 1e-6, f"expected 1.2 got {cons}"
        m1 = [m for m in client.get(f"{BASE_URL}/api/inventory/materials").json() if m["id"] == kaos_material["id"]][0]
        assert abs(float(m1["current_stock"]) - (s0 - 1.2)) < 1e-6

    def test_sale_missing_size_rejected(self, client, sizing_product):
        payload = {
            "items": [{
                "product_id": sizing_product["id"],
                "product_name": sizing_product["name"],
                "quantity": 1,
                "unit_price": 0,
            }],
            "cash_paid": 100000,
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 400, r.text
        assert "ukuran" in r.json().get("detail", "").lower()

    def test_sale_invalid_size_rejected(self, client, sizing_product):
        payload = {
            "items": [{
                "product_id": sizing_product["id"],
                "product_name": sizing_product["name"],
                "quantity": 1,
                "unit_price": 0,
                "size": "XXXXL",
            }],
            "cash_paid": 100000,
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "").lower()
        assert "tidak tersedia" in detail or "xxxxl" in detail


# ---------------- Backward compat: non-sizing product still works ----------------

@pytest.fixture(scope="module")
def nonsize_product(client, kaos_material, created_products):
    payload = {
        "name": f"TEST_NONSIZE_Banner_{uuid.uuid4().hex[:6]}",
        "category": "banner",
        "pricing_mode": "fixed",
        "unit_price": 30000,
        "current_stock": 0,
        "components": [
            {"material_id": kaos_material["id"], "formula": "per_qty", "quantity": 1.0},
        ],
        "active": True,
        "has_sizes": False,
        "sizes": [],
        "price_size_a": 0,
        "price_size_b": 0,
    }
    r = client.post(f"{BASE_URL}/api/products", json=payload)
    assert r.status_code == 200, r.text
    p = r.json()
    created_products.append(p["id"])
    return p


class TestBackwardCompat:
    def test_sale_nonsize_product_no_size_field(self, client, nonsize_product, created_sales):
        payload = {
            "items": [{
                "product_id": nonsize_product["id"],
                "product_name": nonsize_product["name"],
                "quantity": 3,
                "unit_price": 30000,
            }],
            "cash_paid": 100000,
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])
        it = sale["items"][0]
        assert it["unit_price"] == 30000
        assert it["subtotal"] == 90000
        # size fields should be None for non-sizing product
        assert it.get("size") in (None, "")
        assert it.get("size_tier") in (None, "")

    def test_sale_nonsize_product_with_stray_size_ignored(self, client, nonsize_product, created_sales):
        """Bila produk tanpa has_sizes menerima size='M' — sistem harus tidak error dan tidak mengubah harga tier."""
        payload = {
            "items": [{
                "product_id": nonsize_product["id"],
                "product_name": nonsize_product["name"],
                "quantity": 1,
                "unit_price": 30000,
                "size": "M",
            }],
            "cash_paid": 50000,
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])
        it = sale["items"][0]
        assert it["unit_price"] == 30000
        assert it.get("size_tier") in (None, "")
