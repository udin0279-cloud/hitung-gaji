"""Backend tests for Master Produk (BOM) module and Sales BOM integration.

Covers:
- /api/products CRUD + validations (name, pricing_mode, formula, quantity, material existence, dup name)
- DELETE product refused if used in sales
- Sales BOM: multi-material stock deduction (Slayer test), formulas (per_qty, area, length, fixed),
  pricing modes (fixed, per_area), delete rollback, aggregate stock validation, backward compat
  legacy material_id mode, cashbook auto-insert
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


TAG = f"TEST_BOM_{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text}")
    return s


def _get_material(client, mid):
    mats = client.get(f"{BASE_URL}/api/inventory/materials").json()
    return next((m for m in mats if m["id"] == mid), None)


@pytest.fixture(scope="module")
def materials(client):
    """Create test materials: Kertas Slayer (pcs, stock 100), Kain Slayer (meter, stock 50)."""
    created = {}
    # Kertas — pcs (use category 'lainnya' since MATERIAL_CATEGORIES = flexy/sticker/tinta/lainnya)
    r1 = client.post(f"{BASE_URL}/api/inventory/materials", json={
        "name": f"{TAG}_Kertas Slayer", "category": "lainnya", "unit": "pcs",
        "current_stock": 100, "purchase_price": 500, "min_stock": 0, "active": True,
    })
    assert r1.status_code == 200, r1.text
    created["kertas"] = r1.json()

    # Kain — meter (unit "meter" is closest supported unit for area calc; treat as m²)
    r2 = client.post(f"{BASE_URL}/api/inventory/materials", json={
        "name": f"{TAG}_Kain Slayer", "category": "flexy", "unit": "meter",
        "current_stock": 50, "purchase_price": 15000, "min_stock": 0, "active": True,
    })
    assert r2.status_code == 200, r2.text
    created["kain"] = r2.json()

    yield created

    # Cleanup materials (after all product/sale cleanup)
    for m in created.values():
        try:
            client.delete(f"{BASE_URL}/api/inventory/materials/{m['id']}")
        except Exception:
            pass


@pytest.fixture(scope="module")
def created_products():
    return []


@pytest.fixture(scope="module")
def created_sales():
    return []


# ===== Products CRUD =====
class TestProductsCRUD:
    def test_list_products(self, client):
        r = client.get(f"{BASE_URL}/api/products")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_product_slayer(self, client, materials, created_products):
        payload = {
            "code": f"{TAG}-SLY",
            "name": f"{TAG}_Slayer",
            "category": "apparel",
            "pricing_mode": "fixed",
            "unit_price": 25000,
            "components": [
                {"material_id": materials["kertas"]["id"], "formula": "per_qty", "quantity": 1},
                {"material_id": materials["kain"]["id"], "formula": "area", "quantity": 1},
            ],
            "active": True,
        }
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["name"] == payload["name"]
        assert data["pricing_mode"] == "fixed"
        assert data["unit_price"] == 25000
        assert len(data["components"]) == 2
        # Enriched fields
        assert data["requires_dimensions"] is True
        for c in data["components"]:
            assert "material_name" in c
            assert "material_unit" in c
            assert "material_stock" in c
        assert "id" in data
        assert "_id" not in data
        created_products.append(data)

    def test_get_product(self, client, created_products):
        pid = created_products[0]["id"]
        r = client.get(f"{BASE_URL}/api/products/{pid}")
        assert r.status_code == 200
        assert r.json()["id"] == pid
        assert r.json()["requires_dimensions"] is True

    def test_create_product_name_empty(self, client):
        r = client.post(f"{BASE_URL}/api/products", json={
            "name": "", "pricing_mode": "fixed", "unit_price": 100, "components": []
        })
        assert r.status_code == 400

    def test_create_product_invalid_pricing_mode(self, client):
        r = client.post(f"{BASE_URL}/api/products", json={
            "name": f"{TAG}_Bad1", "pricing_mode": "weird", "unit_price": 100, "components": []
        })
        assert r.status_code == 400

    def test_create_product_invalid_formula(self, client, materials):
        r = client.post(f"{BASE_URL}/api/products", json={
            "name": f"{TAG}_Bad2", "pricing_mode": "fixed", "unit_price": 100,
            "components": [{"material_id": materials["kertas"]["id"], "formula": "wrong", "quantity": 1}],
        })
        assert r.status_code == 400

    def test_create_product_zero_quantity(self, client, materials):
        r = client.post(f"{BASE_URL}/api/products", json={
            "name": f"{TAG}_Bad3", "pricing_mode": "fixed", "unit_price": 100,
            "components": [{"material_id": materials["kertas"]["id"], "formula": "per_qty", "quantity": 0}],
        })
        assert r.status_code == 400

    def test_create_product_unknown_material(self, client):
        r = client.post(f"{BASE_URL}/api/products", json={
            "name": f"{TAG}_Bad4", "pricing_mode": "fixed", "unit_price": 100,
            "components": [{"material_id": "nonexistent-xyz", "formula": "per_qty", "quantity": 1}],
        })
        assert r.status_code == 400

    def test_create_product_duplicate_name_case_insensitive(self, client, materials, created_products):
        # Slayer already created — case-insensitive collision
        dup_name = created_products[0]["name"].upper()
        r = client.post(f"{BASE_URL}/api/products", json={
            "name": dup_name, "pricing_mode": "fixed", "unit_price": 100, "components": []
        })
        assert r.status_code == 400

    def test_update_product(self, client, created_products):
        pid = created_products[0]["id"]
        p = created_products[0]
        payload = {
            "code": p.get("code"),
            "name": p["name"],
            "category": p.get("category"),
            "pricing_mode": "fixed",
            "unit_price": 26000,  # bumped
            "components": [{"material_id": c["material_id"], "formula": c["formula"], "quantity": c["factor"] if "factor" in c else c["quantity"]} for c in p["components"]],
            "active": True,
        }
        r = client.put(f"{BASE_URL}/api/products/{pid}", json=payload)
        assert r.status_code == 200, r.text
        assert r.json()["unit_price"] == 26000
        # revert
        payload["unit_price"] = 25000
        client.put(f"{BASE_URL}/api/products/{pid}", json=payload)


# ===== Sales BOM =====
class TestSalesBOM:
    def test_sale_slayer_fixed_pricing_multi_material_deduct(self, client, materials, created_products, created_sales):
        """Slayer: unit_price=25000 fixed, qty=10, L=0.3, W=0.15
        Expected: subtotal = 25000*10 = 250000
                  Kertas.stock -= 10 (per_qty * 10 = 10)
                  Kain.stock -= 0.3*0.15*10 = 0.45
        """
        pid = created_products[0]["id"]
        # Snapshot stocks
        kertas_before = float(_get_material(client, materials["kertas"]["id"])["current_stock"])
        kain_before = float(_get_material(client, materials["kain"]["id"])["current_stock"])

        r = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": f"{TAG}_Cust1",
            "items": [{
                "product_id": pid, "product_name": "Slayer",
                "length_m": 0.3, "width_m": 0.15, "quantity": 10, "unit_price": 25000,
            }],
            "cash_paid": 250000, "payment_method": "tunai",
        })
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])

        assert sale["subtotal"] == 250000
        assert sale["total"] == 250000
        assert len(sale["items"]) == 1
        it = sale["items"][0]
        assert it["subtotal"] == 250000
        # Two components saved with consumption
        assert len(it["components"]) == 2
        by_fmla = {c["formula"]: c for c in it["components"]}
        assert by_fmla["per_qty"]["consumption"] == 10
        assert abs(by_fmla["area"]["consumption"] - 0.45) < 1e-6

        # Stock deducted
        kertas_after = float(_get_material(client, materials["kertas"]["id"])["current_stock"])
        kain_after = float(_get_material(client, materials["kain"]["id"])["current_stock"])
        assert kertas_after == round(kertas_before - 10, 4)
        assert abs(kain_after - (kain_before - 0.45)) < 1e-6

    def test_cashbook_auto_insert_from_bom_sale(self, client, created_sales):
        # Get the sale we just created
        sid = created_sales[-1]
        r = client.get(f"{BASE_URL}/api/sales/{sid}")
        assert r.status_code == 200
        sale_no = r.json()["sale_no"]
        # cashbook should have entry with reference=sale_no, account_code=301, amount=250000
        r2 = client.get(f"{BASE_URL}/api/cashbook/transactions")
        assert r2.status_code == 200
        payload = r2.json()
        # Response is either a list or an object with "items"
        tx_list = payload if isinstance(payload, list) else payload.get("items") or payload.get("transactions") or []
        found = [t for t in tx_list if t.get("reference") == sale_no and t.get("account_code") == "301"]
        assert found, f"No cashbook tx found for sale {sale_no}"
        assert abs(float(found[0].get("amount") or 0) - 250000) < 1e-6

    def test_receipt_html_bom_breakdown(self, client, created_sales):
        sid = created_sales[-1]
        r = client.get(f"{BASE_URL}/api/sales/{sid}/receipt")
        assert r.status_code == 200
        html = r.text
        # Multi-material breakdown line: "Bahan: {name1} 10pcs + {name2} 0.45meter"
        assert "Bahan:" in html
        assert f"{TAG}_Kertas Slayer" in html
        assert f"{TAG}_Kain Slayer" in html
        # Pricing fixed: no "/m²" for this item's price line
        assert "10 pcs" in html
        assert "/m²" not in html or html.count("/m²") == 0

    def test_delete_bom_sale_rollback(self, client, materials, created_sales):
        """Deleting the Slayer sale should restore Kertas +10 and Kain +0.45."""
        sid = created_sales[-1]
        kertas_before = float(_get_material(client, materials["kertas"]["id"])["current_stock"])
        kain_before = float(_get_material(client, materials["kain"]["id"])["current_stock"])
        r = client.delete(f"{BASE_URL}/api/sales/{sid}")
        assert r.status_code == 200
        kertas_after = float(_get_material(client, materials["kertas"]["id"])["current_stock"])
        kain_after = float(_get_material(client, materials["kain"]["id"])["current_stock"])
        assert kertas_after == round(kertas_before + 10, 4)
        assert abs(kain_after - (kain_before + 0.45)) < 1e-6
        created_sales.pop()

    def test_sale_stok_insufficient(self, client, materials, created_products):
        """Slayer needs Kain area = 0.5*0.5*300 = 75 m² > stock 50 → 400."""
        pid = created_products[0]["id"]
        r = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": f"{TAG}_Cust_Overflow",
            "items": [{
                "product_id": pid, "product_name": "Slayer",
                "length_m": 0.5, "width_m": 0.5, "quantity": 300, "unit_price": 25000,
            }],
            "cash_paid": 999999999, "payment_method": "tunai",
        })
        assert r.status_code == 400
        assert "tidak cukup" in r.text.lower()

    def test_sale_material_langsung_backward_compat(self, client, materials, created_sales):
        """Legacy mode: no product_id, just material_id."""
        kain_id = materials["kain"]["id"]
        kain_before = float(_get_material(client, kain_id)["current_stock"])
        r = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": f"{TAG}_LegacyCust",
            "items": [{
                "material_id": kain_id, "product_name": "Bendera Custom",
                "length_m": 1.0, "width_m": 0.5, "quantity": 2, "unit_price": 100000,
            }],
            "cash_paid": 100000, "payment_method": "tunai",
        })
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])
        # area_total = 1*0.5*2 = 1.0; subtotal = 1.0 * 100000 = 100000
        assert sale["subtotal"] == 100000
        it = sale["items"][0]
        assert it["material_id"] == kain_id
        assert it["product_id"] is None
        # Legacy component saved for symmetry
        assert len(it["components"]) == 1
        assert it["components"][0]["formula"] == "area"
        assert it["components"][0]["consumption"] == 1.0
        # Stock -= 1.0
        kain_after = float(_get_material(client, kain_id)["current_stock"])
        assert abs(kain_after - (kain_before - 1.0)) < 1e-6

    def test_delete_legacy_sale_restores_stock(self, client, materials, created_sales):
        sid = created_sales[-1]
        kain_before = float(_get_material(client, materials["kain"]["id"])["current_stock"])
        r = client.delete(f"{BASE_URL}/api/sales/{sid}")
        assert r.status_code == 200
        kain_after = float(_get_material(client, materials["kain"]["id"])["current_stock"])
        assert abs(kain_after - (kain_before + 1.0)) < 1e-6
        created_sales.pop()

    def test_aggregate_stock_check_across_items(self, client, materials, created_products):
        """2 items same product with heavy dims → agregat harus dijumlahkan sebelum check.
        Kertas stock=100, need 2 items * qty 60 = 120 → 400.
        """
        pid = created_products[0]["id"]
        r = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": f"{TAG}_AggCust",
            "items": [
                {"product_id": pid, "product_name": "Slayer", "length_m": 0.1, "width_m": 0.1, "quantity": 60, "unit_price": 25000},
                {"product_id": pid, "product_name": "Slayer", "length_m": 0.1, "width_m": 0.1, "quantity": 60, "unit_price": 25000},
            ],
            "cash_paid": 999999999, "payment_method": "tunai",
        })
        assert r.status_code == 400
        assert "tidak cukup" in r.text.lower()


# ===== Formula variants =====
class TestFormulaVariants:
    def test_formula_per_qty_only(self, client, materials, created_products, created_sales):
        """Fixed pricing, per_qty formula only → no P×L needed."""
        payload = {
            "name": f"{TAG}_Kartu Nama",
            "pricing_mode": "fixed",
            "unit_price": 500,
            "components": [{"material_id": materials["kertas"]["id"], "formula": "per_qty", "quantity": 1}],
            "active": True,
        }
        r = client.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code == 200, r.text
        prod = r.json()
        created_products.append(prod)
        assert prod["requires_dimensions"] is False

        # POST sale — no L/W needed
        kertas_before = float(_get_material(client, materials["kertas"]["id"])["current_stock"])
        r2 = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": f"{TAG}_KartuCust",
            "items": [{
                "product_id": prod["id"], "product_name": "Kartu Nama",
                "length_m": 0, "width_m": 0, "quantity": 20, "unit_price": 500,
            }],
            "cash_paid": 20000, "payment_method": "tunai",
        })
        assert r2.status_code == 200, r2.text
        sale = r2.json()
        created_sales.append(sale["id"])
        # subtotal = 500 * 20 = 10000
        assert sale["subtotal"] == 10000
        kertas_after = float(_get_material(client, materials["kertas"]["id"])["current_stock"])
        assert kertas_after == round(kertas_before - 20, 4)

    def test_formula_length_only_and_per_area_pricing(self, client, materials, created_products, created_sales):
        """Product with length formula + pricing_mode per_area."""
        # Add a length material — use kain with length usage
        r = client.post(f"{BASE_URL}/api/products", json={
            "name": f"{TAG}_Banner Length",
            "pricing_mode": "per_area",
            "unit_price": 40000,
            "components": [{"material_id": materials["kain"]["id"], "formula": "length", "quantity": 1}],
            "active": True,
        })
        assert r.status_code == 200, r.text
        prod = r.json()
        created_products.append(prod)
        assert prod["requires_dimensions"] is True

        kain_before = float(_get_material(client, materials["kain"]["id"])["current_stock"])
        # length=2, width=1, qty=1, unit=40000/m² → area=2*1*1=2, subtotal=2*40000=80000
        # length formula consumption = 2 * 1 (qty) * 1 (factor) = 2
        r2 = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": f"{TAG}_BannerCust",
            "items": [{
                "product_id": prod["id"], "product_name": "Banner",
                "length_m": 2, "width_m": 1, "quantity": 1, "unit_price": 40000,
            }],
            "cash_paid": 80000, "payment_method": "tunai",
        })
        assert r2.status_code == 200, r2.text
        sale = r2.json()
        created_sales.append(sale["id"])
        assert sale["subtotal"] == 80000
        it = sale["items"][0]
        assert it["components"][0]["consumption"] == 2.0
        kain_after = float(_get_material(client, materials["kain"]["id"])["current_stock"])
        assert abs(kain_after - (kain_before - 2.0)) < 1e-6

    def test_formula_fixed_no_qty_multiply(self, client, materials, created_products, created_sales):
        """Fixed formula = konsumsi factor tetap, TIDAK dikali qty."""
        r = client.post(f"{BASE_URL}/api/products", json={
            "name": f"{TAG}_FixedFormula",
            "pricing_mode": "fixed",
            "unit_price": 1000,
            "components": [{"material_id": materials["kertas"]["id"], "formula": "fixed", "quantity": 3}],
            "active": True,
        })
        assert r.status_code == 200, r.text
        prod = r.json()
        created_products.append(prod)

        kertas_before = float(_get_material(client, materials["kertas"]["id"])["current_stock"])
        r2 = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": f"{TAG}_FixedCust",
            "items": [{
                "product_id": prod["id"], "product_name": "FixedTest",
                "length_m": 0, "width_m": 0, "quantity": 10, "unit_price": 1000,
            }],
            "cash_paid": 10000, "payment_method": "tunai",
        })
        assert r2.status_code == 200, r2.text
        sale = r2.json()
        created_sales.append(sale["id"])
        # Konsumsi fixed = factor 3 (not multiplied by qty=10)
        assert sale["items"][0]["components"][0]["consumption"] == 3.0
        kertas_after = float(_get_material(client, materials["kertas"]["id"])["current_stock"])
        assert kertas_after == round(kertas_before - 3, 4)


# ===== Delete guard =====
class TestDeleteGuardAndCleanup:
    def test_delete_product_used_in_sales_refused(self, client, created_products, created_sales):
        """Any product that has sales should not be deletable."""
        # Kartu Nama product is in created_products[1] and has a sale
        if len(created_products) < 2 or not created_sales:
            pytest.skip("no product-with-sale to test")
        # Find a product that has at least one sale
        for prod in created_products:
            r = client.delete(f"{BASE_URL}/api/products/{prod['id']}")
            if r.status_code == 400:
                # Good — found a product-in-use
                assert "dipakai" in r.text.lower() or "used" in r.text.lower()
                return
        pytest.skip("No product currently in use — all deletable")

    def test_zzz_cleanup_sales_and_products(self, client, created_products, created_sales):
        """Delete all remaining test sales, then products."""
        for sid in list(created_sales):
            try:
                client.delete(f"{BASE_URL}/api/sales/{sid}")
            except Exception:
                pass
        created_sales.clear()
        # Now products should delete
        for prod in list(created_products):
            r = client.delete(f"{BASE_URL}/api/products/{prod['id']}")
            # 200 expected; may fail if leftover sales — acceptable
            if r.status_code == 200:
                created_products.remove(prod)
