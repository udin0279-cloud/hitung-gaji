"""Tests for Sales / POS module (POST/GET/DELETE /api/sales, receipt HTML, stats, and Material.selling_price backward-compat)."""
import os
import re
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break


# ---------------- Helpers / fixtures ----------------

@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code}")
    return s


@pytest.fixture(scope="module")
def test_material(client):
    """Create isolated test material with sufficient stock."""
    payload = {
        "name": "TEST_SALES_Flexy",
        "category": "flexy",
        "unit": "meter",
        "current_stock": 500.0,
        "purchase_price": 15000,
        "selling_price": 25000,  # per m²
        "min_stock": 10,
        "active": True,
    }
    r = client.post(f"{BASE_URL}/api/inventory/materials", json=payload)
    assert r.status_code == 200, r.text
    mat = r.json()
    yield mat
    # teardown: delete (soft or hard)
    client.delete(f"{BASE_URL}/api/inventory/materials/{mat['id']}")


@pytest.fixture(scope="module")
def created_sales():
    # collector to allow cleanup at end
    return []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client, created_sales):
    yield
    for sid in created_sales:
        try:
            client.delete(f"{BASE_URL}/api/sales/{sid}")
        except Exception:
            pass


# ---------------- MaterialIn.selling_price ----------------

class TestMaterialSellingPrice:
    def test_material_accepts_selling_price(self, client):
        payload = {
            "name": "TEST_SELL_MAT",
            "category": "sticker",
            "unit": "meter",
            "current_stock": 10,
            "purchase_price": 1000,
            "selling_price": 3500,
            "min_stock": 0,
        }
        r = client.post(f"{BASE_URL}/api/inventory/materials", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["selling_price"] == 3500
        # PUT update
        payload["selling_price"] = 4000
        r2 = client.put(f"{BASE_URL}/api/inventory/materials/{data['id']}", json=payload)
        assert r2.status_code == 200
        assert r2.json()["selling_price"] == 4000
        client.delete(f"{BASE_URL}/api/inventory/materials/{data['id']}")

    def test_material_without_selling_price_defaults_zero(self, client):
        payload = {
            "name": "TEST_SELL_MAT_NOSP",
            "category": "lainnya",
            "unit": "pcs",
            "current_stock": 5,
            "purchase_price": 100,
        }
        r = client.post(f"{BASE_URL}/api/inventory/materials", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data.get("selling_price", 0) == 0
        client.delete(f"{BASE_URL}/api/inventory/materials/{data['id']}")


# ---------------- Sales stats ----------------

class TestSalesStats:
    def test_stats_endpoint_shape(self, client):
        r = client.get(f"{BASE_URL}/api/sales/stats/today")
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ["count_today", "total_today", "count_month", "total_month"]:
            assert k in data
        assert isinstance(data["count_today"], int)
        assert isinstance(data["count_month"], int)


# ---------------- Sales CRUD ----------------

class TestSalesCreate:
    def test_create_sale_success(self, client, test_material, created_sales):
        # 3m x 2m x 5 qty = 30 m² × 25000 = 750_000
        payload = {
            "customer_name": "TEST_Bu Ani",
            "customer_phone": "0812999",
            "items": [{
                "material_id": test_material["id"],
                "product_name": "Banner Uji",
                "length_m": 3,
                "width_m": 2,
                "quantity": 5,
                "unit_price": 25000,
            }],
            "discount": 50000,
            "cash_paid": 800000,
            "payment_method": "tunai",
            "notes": "test create",
        }
        # Stock before
        m_before = client.get(f"{BASE_URL}/api/inventory/materials").json()
        stock_before = [m for m in m_before if m["id"] == test_material["id"]][0]["current_stock"]

        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        created_sales.append(data["id"])

        # sale_no format NOTA-YYYYMMDD-XXXX
        assert re.match(r"^NOTA-\d{8}-\d{4}$", data["sale_no"]), f"sale_no format wrong: {data['sale_no']}"

        # Financial math
        assert data["subtotal"] == 750000
        assert data["discount"] == 50000
        assert data["total"] == 700000
        assert data["cash_paid"] == 800000
        assert data["change"] == 100000
        assert data["cashier"] == "admin@payroll.id"
        assert data["cashier_name"]
        assert data["customer_name"] == "TEST_Bu Ani"

        # Item enrichment
        item = data["items"][0]
        assert item["area_per_pc"] == 6
        assert item["area_total"] == 30
        assert item["subtotal"] == 750000
        assert item["material_name"] == test_material["name"]

        # Stock auto-decrement by area_total (30)
        m_after = client.get(f"{BASE_URL}/api/inventory/materials").json()
        stock_after = [m for m in m_after if m["id"] == test_material["id"]][0]["current_stock"]
        assert round(stock_before - stock_after, 4) == 30

    def test_create_sale_reject_cash_less_than_total(self, client, test_material):
        payload = {
            "customer_name": "TEST_underpay",
            "items": [{
                "material_id": test_material["id"], "product_name": "X",
                "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 10000,
            }],
            "discount": 0,
            "cash_paid": 5000,  # less than 10000
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 400, r.text
        assert "kurang" in r.text.lower() or "tunai" in r.text.lower()

    def test_create_sale_reject_insufficient_stock(self, client, test_material):
        payload = {
            "customer_name": "TEST_no_stock",
            "items": [{
                "material_id": test_material["id"], "product_name": "Huge",
                "length_m": 100, "width_m": 100, "quantity": 100,  # 1M m²
                "unit_price": 1,
            }],
            "cash_paid": 10_000_000,
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 400
        assert "stok" in r.text.lower() or "tidak cukup" in r.text.lower()

    def test_create_sale_reject_empty_items(self, client):
        r = client.post(f"{BASE_URL}/api/sales", json={"items": [], "cash_paid": 0})
        assert r.status_code == 400

    def test_create_sale_reject_zero_dimension(self, client, test_material):
        r = client.post(f"{BASE_URL}/api/sales", json={
            "items": [{"material_id": test_material["id"], "product_name": "Z",
                       "length_m": 0, "width_m": 2, "quantity": 1, "unit_price": 1000}],
            "cash_paid": 0,
        })
        assert r.status_code == 400


class TestSalesListAndGet:
    def test_list_returns_desc(self, client, test_material, created_sales):
        # Create two sales
        for i in range(2):
            r = client.post(f"{BASE_URL}/api/sales", json={
                "customer_name": f"TEST_list_{i}",
                "items": [{"material_id": test_material["id"], "product_name": "L",
                           "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 5000}],
                "cash_paid": 5000,
            })
            assert r.status_code == 200, r.text
            created_sales.append(r.json()["id"])
        r = client.get(f"{BASE_URL}/api/sales")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 2
        # sorted desc by created_at
        for i in range(len(data) - 1):
            assert data[i]["created_at"] >= data[i + 1]["created_at"]

    def test_get_single_sale(self, client, test_material, created_sales):
        r = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": "TEST_single",
            "items": [{"material_id": test_material["id"], "product_name": "S",
                       "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 1000}],
            "cash_paid": 1000,
        })
        assert r.status_code == 200
        sid = r.json()["id"]
        created_sales.append(sid)
        g = client.get(f"{BASE_URL}/api/sales/{sid}")
        assert g.status_code == 200
        assert g.json()["id"] == sid
        # 404
        g404 = client.get(f"{BASE_URL}/api/sales/nonexistent-xyz")
        assert g404.status_code == 404

    def test_list_filter_date_range(self, client):
        r = client.get(f"{BASE_URL}/api/sales", params={"date_from": "2099-01-01", "date_to": "2099-12-31"})
        assert r.status_code == 200
        assert r.json() == []


class TestSalesReceipt:
    def test_receipt_html_content(self, client, test_material, created_sales):
        r = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": "TEST_Receipt",
            "customer_phone": "0819111",
            "items": [{"material_id": test_material["id"], "product_name": "Struk Test",
                       "length_m": 2, "width_m": 1.5, "quantity": 2, "unit_price": 20000}],
            "discount": 5000,
            "cash_paid": 200000,
            "notes": "cek struk",
        })
        assert r.status_code == 200
        sale = r.json()
        created_sales.append(sale["id"])
        rr = client.get(f"{BASE_URL}/api/sales/{sale['id']}/receipt")
        assert rr.status_code == 200
        assert "text/html" in rr.headers.get("content-type", "")
        html = rr.text
        assert "@page" in html and "80mm" in html
        assert sale["sale_no"] in html
        assert "TEST_Receipt" in html
        assert "0819111" in html
        assert "Struk Test" in html
        assert "Cetak Struk" in html  # print button
        # Total 2*1.5*2 = 6 m² * 20000 = 120_000 - 5000 disc = 115_000
        assert "115" in html  # 115.000 in idr
        # cashier + kembali
        assert "Kembali" in html or "kembali" in html.lower()
        assert "Kasir" in html


class TestSalesDelete:
    def test_delete_rollbacks_stock(self, client, test_material, created_sales):
        # snapshot stock
        m0 = [m for m in client.get(f"{BASE_URL}/api/inventory/materials").json() if m["id"] == test_material["id"]][0]
        stock0 = m0["current_stock"]

        r = client.post(f"{BASE_URL}/api/sales", json={
            "customer_name": "TEST_ToDelete",
            "items": [{"material_id": test_material["id"], "product_name": "DEL",
                       "length_m": 1, "width_m": 1, "quantity": 4, "unit_price": 1000}],
            "cash_paid": 4000,
        })
        assert r.status_code == 200
        sid = r.json()["id"]
        # Stock decremented by 4
        m1 = [m for m in client.get(f"{BASE_URL}/api/inventory/materials").json() if m["id"] == test_material["id"]][0]
        assert round(stock0 - m1["current_stock"], 4) == 4

        d = client.delete(f"{BASE_URL}/api/sales/{sid}")
        assert d.status_code == 200
        assert d.json().get("ok") is True

        # Stock restored
        m2 = [m for m in client.get(f"{BASE_URL}/api/inventory/materials").json() if m["id"] == test_material["id"]][0]
        assert round(m2["current_stock"] - m0["current_stock"], 4) == 0

        # confirm gone
        g = client.get(f"{BASE_URL}/api/sales/{sid}")
        assert g.status_code == 404

    def test_delete_404(self, client):
        r = client.delete(f"{BASE_URL}/api/sales/nonexistent-abc")
        assert r.status_code == 404
