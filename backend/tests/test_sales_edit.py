"""Tests for Sales EDIT feature: PUT /api/sales/{sale_id} — preserve sale_no+id, rollback+reapply stock,
cash tx sync (no dup), error restore, size tier change."""
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
        "name": f"TEST_EDIT_Kain_{uuid.uuid4().hex[:6]}",
        "category": "kain",
        "unit": "meter",
        "current_stock": 100.0,
        "purchase_price": 20000,
        "selling_price": 0,
        "min_stock": 5,
        "active": True,
    }
    r = client.post(f"{BASE_URL}/api/inventory/materials", json=payload)
    assert r.status_code == 200, r.text
    yield r.json()
    client.delete(f"{BASE_URL}/api/inventory/materials/{r.json()['id']}")


@pytest.fixture(scope="module")
def kaos_product(client, kaos_material):
    """Kaos with has_sizes: tier A price 85k+qty 1.0, tier B price 95k+qty 1.2."""
    payload = {
        "name": f"TEST_EDIT_Kaos_{uuid.uuid4().hex[:6]}",
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
    r = client.post(f"{BASE_URL}/api/products", json=payload)
    assert r.status_code == 200, r.text
    yield r.json()
    client.delete(f"{BASE_URL}/api/products/{r.json()['id']}")


@pytest.fixture(scope="module")
def created_sales():
    return []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client, created_sales):
    yield
    for sid in created_sales:
        try:
            client.delete(f"{BASE_URL}/api/sales/{sid}")
        except Exception:
            pass


# ---------------- Helpers ----------------

def _get_stock(client, material_id):
    r = client.get(f"{BASE_URL}/api/inventory/materials")
    assert r.status_code == 200, r.text
    for m in r.json():
        if m["id"] == material_id:
            return float(m.get("current_stock", 0))
    raise AssertionError(f"Material {material_id} not found")


def _sale_payload(product, size="M", qty=2, discount=0, cash_paid=None, customer_name="TEST_EDIT_Cust"):
    total = 0
    # rough for cash_paid default (tier A = 85000)
    if cash_paid is None:
        # Very generous cash_paid
        cash_paid = 1_000_000
    return {
        "customer_name": customer_name,
        "customer_phone": "0812-3456-7890",
        "discount": discount,
        "cash_paid": cash_paid,
        "payment_method": "tunai",
        "notes": None,
        "items": [{
            "product_id": product["id"],
            "material_id": None,
            "product_name": product["name"],
            "length_m": 0,
            "width_m": 0,
            "quantity": qty,
            "unit_price": 0,  # backend akan pakai price_size_a/b
            "size": size,
        }],
    }


def _get_cash_tx_for(client, sale_no):
    """Get cash transactions referencing this sale_no (account 301)."""
    r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"account_code": "301"})
    assert r.status_code == 200, r.text
    data = r.json()
    txs = data.get("transactions", []) if isinstance(data, dict) else data
    return [t for t in txs if t.get("reference") == sale_no and t.get("account_code") == "301"]


# ---------------- Tests ----------------

class TestSalesEditBasic:
    """Preserve id + sale_no + created_at + date; update_at & updated_by present."""

    def test_edit_preserves_ids_and_updates_fields(self, client, kaos_product, kaos_material, created_sales):
        # CREATE qty=2, size=M (tier A price 85k)
        r = client.post(f"{BASE_URL}/api/sales", json=_sale_payload(kaos_product, size="M", qty=2))
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])
        sale_id = sale["id"]
        sale_no = sale["sale_no"]
        created_at = sale["created_at"]
        date_orig = sale["date"]
        subtotal_orig = sale["subtotal"]
        assert subtotal_orig == 170000  # 85k * 2
        assert sale["total"] == 170000

        # UPDATE qty=5 + discount=10k + change customer_name
        upd = _sale_payload(kaos_product, size="M", qty=5, discount=10000, customer_name="TEST_EDIT_Updated")
        r2 = client.put(f"{BASE_URL}/api/sales/{sale_id}", json=upd)
        assert r2.status_code == 200, r2.text
        updated = r2.json()
        # Preserved
        assert updated["id"] == sale_id
        assert updated["sale_no"] == sale_no
        assert updated["created_at"] == created_at
        assert updated["date"] == date_orig
        # Updated
        assert updated["subtotal"] == 425000  # 85k * 5
        assert updated["discount"] == 10000
        assert updated["total"] == 415000
        assert updated["customer_name"] == "TEST_EDIT_Updated"
        assert "updated_at" in updated and updated["updated_at"]
        assert updated.get("updated_by") == "admin@payroll.id"

        # GET verify persistence
        g = client.get(f"{BASE_URL}/api/sales/{sale_id}")
        assert g.status_code == 200
        gj = g.json()
        assert gj["sale_no"] == sale_no
        assert gj["total"] == 415000
        assert gj["customer_name"] == "TEST_EDIT_Updated"
        assert gj["items"][0]["quantity"] == 5


class TestSalesEditRollbackStock:
    """qty 2→5, final stock must = initial - 5 (net), not -3, not -7."""

    def test_rollback_and_reapply_stock_correctly(self, client, kaos_product, kaos_material, created_sales):
        stock_before = _get_stock(client, kaos_material["id"])

        # Sale qty=2, size=M (tier A consumption = 1.0 * 2 = 2)
        r = client.post(f"{BASE_URL}/api/sales", json=_sale_payload(kaos_product, size="M", qty=2))
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])
        stock_after_create = _get_stock(client, kaos_material["id"])
        assert abs(stock_after_create - (stock_before - 2.0)) < 1e-6, (
            f"After create expected {stock_before - 2}, got {stock_after_create}"
        )

        # UPDATE qty=5, size=M (tier A cons = 1.0 * 5 = 5) — net from ORIGINAL should be -5
        upd = _sale_payload(kaos_product, size="M", qty=5)
        r2 = client.put(f"{BASE_URL}/api/sales/{sale['id']}", json=upd)
        assert r2.status_code == 200, r2.text
        stock_after_update = _get_stock(client, kaos_material["id"])
        assert abs(stock_after_update - (stock_before - 5.0)) < 1e-6, (
            f"After update expected {stock_before - 5}, got {stock_after_update} "
            f"(bukan -3 additive dan bukan -7 tanpa rollback)"
        )


class TestSalesEditCashTxSync:
    """Cash tx lama harus dihapus, cash tx baru inserted — never duplicated."""

    def test_no_duplicate_cash_tx_after_edit(self, client, kaos_product, kaos_material, created_sales):
        r = client.post(f"{BASE_URL}/api/sales", json=_sale_payload(kaos_product, size="M", qty=2))
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])
        sale_no = sale["sale_no"]
        # cash tx original 170000
        txs = _get_cash_tx_for(client, sale_no)
        assert len(txs) == 1, f"Expected 1 tx after create, got {len(txs)}"
        assert abs(float(txs[0]["amount"]) - 170000) < 1e-6

        # Edit → new total 415000
        upd = _sale_payload(kaos_product, size="M", qty=5, discount=10000)
        r2 = client.put(f"{BASE_URL}/api/sales/{sale['id']}", json=upd)
        assert r2.status_code == 200, r2.text

        txs_after = _get_cash_tx_for(client, sale_no)
        assert len(txs_after) == 1, (
            f"Expected 1 tx after edit (old deleted, new inserted), got {len(txs_after)}"
        )
        assert abs(float(txs_after[0]["amount"]) - 415000) < 1e-6


class TestSalesEditErrorRestore:
    """Jika stok baru tak cukup → 400 dan STATE dikembalikan (stok lama masih terpotong, cash tx lama ada)."""

    def test_insufficient_stock_error_restores_state(self, client, kaos_product, kaos_material, created_sales):
        stock_before = _get_stock(client, kaos_material["id"])

        # Buat sale qty=2 (cons 2). stock_after = before-2
        r = client.post(f"{BASE_URL}/api/sales", json=_sale_payload(kaos_product, size="M", qty=2))
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])
        sale_no = sale["sale_no"]
        stock_after_create = _get_stock(client, kaos_material["id"])
        assert abs(stock_after_create - (stock_before - 2.0)) < 1e-6

        # Cash tx original ada
        txs_before_err = _get_cash_tx_for(client, sale_no)
        assert len(txs_before_err) == 1
        orig_amount = float(txs_before_err[0]["amount"])

        # Coba edit ke qty yang lebih besar dari stok yang ada (harus fail)
        # stock saat rollback = stock_before, jadi butuh qty > stock_before → error
        huge_qty = int(stock_before + 100)
        upd = _sale_payload(kaos_product, size="M", qty=huge_qty)
        r2 = client.put(f"{BASE_URL}/api/sales/{sale['id']}", json=upd)
        assert r2.status_code == 400, f"Expected 400 for insufficient stock, got {r2.status_code}: {r2.text}"

        # STATE HARUS DIKEMBALIKAN: stok = stock_before - 2 (original), cash tx original ada
        stock_after_err = _get_stock(client, kaos_material["id"])
        assert abs(stock_after_err - (stock_before - 2.0)) < 1e-6, (
            f"After error restore expected stock={stock_before-2}, got {stock_after_err}"
        )
        txs_after_err = _get_cash_tx_for(client, sale_no)
        assert len(txs_after_err) == 1, (
            f"Expected original cash tx restored (1), got {len(txs_after_err)}"
        )
        assert abs(float(txs_after_err[0]["amount"]) - orig_amount) < 1e-6

        # Sale masih ada dengan data lama
        g = client.get(f"{BASE_URL}/api/sales/{sale['id']}")
        assert g.status_code == 200
        gj = g.json()
        assert gj["items"][0]["quantity"] == 2  # tetap qty lama


class TestSalesEdit404:
    def test_edit_nonexistent_returns_404(self, client, kaos_product):
        fake_id = str(uuid.uuid4())
        upd = _sale_payload(kaos_product, size="M", qty=1)
        r = client.put(f"{BASE_URL}/api/sales/{fake_id}", json=upd)
        assert r.status_code == 404, r.text


class TestSalesEditChangeSizeTier:
    """Change size dari M (tier A, 85k, cons 1.0) ke XXL (tier B, 95k, cons 1.2) — harga & consumption update."""

    def test_change_size_from_M_to_XXL(self, client, kaos_product, kaos_material, created_sales):
        stock_before = _get_stock(client, kaos_material["id"])

        # Create with size=M qty=2 (tier A, cons 2.0)
        r = client.post(f"{BASE_URL}/api/sales", json=_sale_payload(kaos_product, size="M", qty=2))
        assert r.status_code == 200, r.text
        sale = r.json()
        created_sales.append(sale["id"])
        assert sale["items"][0]["size"] == "M"
        assert sale["items"][0]["size_tier"] == "A"
        assert sale["items"][0]["unit_price"] == 85000
        assert sale["subtotal"] == 170000

        # Edit → size=XXL qty=2 (tier B, price 95k, cons 1.2 * 2 = 2.4)
        upd = _sale_payload(kaos_product, size="XXL", qty=2)
        r2 = client.put(f"{BASE_URL}/api/sales/{sale['id']}", json=upd)
        assert r2.status_code == 200, r2.text
        updated = r2.json()
        assert updated["items"][0]["size"] == "XXL"
        assert updated["items"][0]["size_tier"] == "B"
        assert updated["items"][0]["unit_price"] == 95000
        assert updated["subtotal"] == 190000  # 95k * 2

        # Consumption check via components in response
        comp = updated["items"][0]["components"][0]
        assert abs(float(comp["consumption"]) - 2.4) < 1e-6, f"cons XXL should be 2.4, got {comp['consumption']}"

        # Stock: rollback 2.0 dari M, dedu 2.4 dari XXL → net stock_before - 2.4
        stock_after = _get_stock(client, kaos_material["id"])
        assert abs(stock_after - (stock_before - 2.4)) < 1e-6, (
            f"Expected stock={stock_before - 2.4}, got {stock_after}"
        )
