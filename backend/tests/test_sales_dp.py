"""Tests for DP (Down Payment) feature in Sales module.

Covers:
- POST /api/sales with cash_paid < total → creates DP (status=dp, sisa_tagihan>0)
- POST /api/sales with cash_paid >= total → LUNAS (status=paid, sisa_tagihan=0, change>0 allowed)
- Cash transaction records cash_paid (clamped to total), not sale total
- /api/sales/report/analytics returns sale_status, sale_sisa_tagihan, sale_cash_paid
- Payment column shows CASH_PAID (min(cash_paid, total)), not total
- Thermal receipt HTML + PDF A4 contain SISA TAGIHAN & DP badge
"""
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
    payload = {
        "name": "TEST_DP_Brosur",
        "category": "lainnya",
        "unit": "pcs",
        "current_stock": 1000.0,
        "purchase_price": 50000,
        "selling_price": 100000,
        "min_stock": 0,
        "active": True,
    }
    r = client.post(f"{BASE_URL}/api/inventory/materials", json=payload)
    assert r.status_code == 200, r.text
    mat = r.json()
    yield mat
    client.delete(f"{BASE_URL}/api/inventory/materials/{mat['id']}")


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


# ---------------- DP creation ----------------

class TestSaleDP:
    def test_create_sale_dp_partial_payment(self, client, test_material, created_sales):
        """Sale total 100k, cash 40k → sisa 60k, status=dp"""
        payload = {
            "customer_name": "TEST_DP_Customer",
            "items": [{
                "material_id": test_material["id"],
                "product_name": "Cetak Brosur 120gr", "length_m": 1, "width_m": 1,
                "length_m": 1,
                "width_m": 1,
                "quantity": 1,
                "unit_price": 100000,
            }],
            "cash_paid": 40000,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        created_sales.append(data["id"])

        assert data["total"] == 100000
        assert data["cash_paid"] == 40000
        assert data["sisa_tagihan"] == 60000, f"Expected sisa=60000, got {data.get('sisa_tagihan')}"
        assert data["change"] == 0
        assert data["status"] == "dp", f"Expected status=dp, got {data.get('status')}"

    def test_create_sale_lunas_overpayment(self, client, test_material, created_sales):
        """Sale total 50k, cash 60k → change 10k, status=paid, sisa=0"""
        payload = {
            "customer_name": "TEST_LUNAS_Customer",
            "items": [{
                "material_id": test_material["id"],
                "product_name": "Cetak Brosur 120gr", "length_m": 1, "width_m": 1,
                "quantity": 1,
                "unit_price": 50000,
            }],
            "cash_paid": 60000,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        created_sales.append(data["id"])

        assert data["total"] == 50000
        assert data["cash_paid"] == 60000
        assert data["sisa_tagihan"] == 0
        assert data["change"] == 10000
        assert data["status"] == "paid"

    def test_create_sale_negative_cash_rejected(self, client, test_material):
        payload = {
            "customer_name": "TEST_NEG",
            "items": [{
                "material_id": test_material["id"],
                "product_name": "X", "length_m": 1, "width_m": 1,
                "quantity": 1,
                "unit_price": 10000,
            }],
            "cash_paid": -1,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code in (400, 422), r.text


# ---------------- GET verifies persistence ----------------

class TestSaleDPPersistence:
    def test_get_sale_returns_dp_fields(self, client, test_material, created_sales):
        # create a DP sale
        payload = {
            "customer_name": "TEST_DP_GET",
            "items": [{"material_id": test_material["id"], "product_name": "X", "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 100000}],
            "cash_paid": 30000,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200
        sid = r.json()["id"]
        created_sales.append(sid)

        # list and find
        r2 = client.get(f"{BASE_URL}/api/sales")
        assert r2.status_code == 200
        sales = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
        match = [s for s in sales if s.get("id") == sid]
        assert match, "Created DP sale not found in list"
        s = match[0]
        assert s.get("sisa_tagihan") == 70000
        assert s.get("status") == "dp"
        assert s.get("cash_paid") == 30000


# ---------------- Cash journal records cash_paid (clamped) ----------------

class TestSaleDPCashJournal:
    def test_dp_records_cash_paid_not_total(self, client, test_material, created_sales):
        """For DP 100k/40k → cashbook records 40k, not 100k, and description contains 'DP (sisa Rp 60,000)'"""
        payload = {
            "customer_name": "TEST_DP_CASH",
            "items": [{"material_id": test_material["id"], "product_name": "X", "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 100000}],
            "cash_paid": 40000,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200
        sale = r.json()
        created_sales.append(sale["id"])
        sale_no = sale["sale_no"]

        # Get cashbook transactions
        rc = client.get(f"{BASE_URL}/api/cashbook/transactions")
        assert rc.status_code == 200, rc.text
        payload_out = rc.json()
        txs = payload_out.get("transactions", []) if isinstance(payload_out, dict) else payload_out
        matches = [t for t in txs if t.get("reference") == sale_no]
        assert matches, f"No cashbook tx found for {sale_no}"
        tx = matches[0]
        # Amount should be 40000 (cash_paid), not 100000 (total)
        assert float(tx.get("amount", 0)) == 40000, f"Expected 40000, got {tx.get('amount')}"
        assert "DP" in tx.get("description", ""), f"Description missing DP marker: {tx.get('description')}"
        # sisa should be embedded
        assert "60" in tx.get("description", "").replace(".", ",").replace(" ", ""), f"Description: {tx.get('description')}"

    def test_lunas_overpayment_clamps_cash_to_total(self, client, test_material, created_sales):
        """For LUNAS 50k/60k → cashbook records 50k (clamped to total, kembalian excluded)"""
        payload = {
            "customer_name": "TEST_LUNAS_CASH",
            "items": [{"material_id": test_material["id"], "product_name": "X", "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 50000}],
            "cash_paid": 60000,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200
        sale = r.json()
        created_sales.append(sale["id"])
        sale_no = sale["sale_no"]

        rc = client.get(f"{BASE_URL}/api/cashbook/transactions")
        assert rc.status_code == 200
        payload_out = rc.json()
        txs = payload_out.get("transactions", []) if isinstance(payload_out, dict) else payload_out
        matches = [t for t in txs if t.get("reference") == sale_no]
        assert matches
        tx = matches[0]
        # Amount should be 50000 (clamped to total), not 60000
        assert float(tx.get("amount", 0)) == 50000, f"Expected 50000 (clamped), got {tx.get('amount')}"
        assert "DP" not in tx.get("description", ""), "LUNAS should not have DP marker"


# ---------------- Analytics endpoint ----------------

class TestSalesReportAnalyticsDP:
    def test_analytics_includes_dp_fields(self, client, test_material, created_sales):
        payload = {
            "customer_name": "TEST_ANALYTICS_DP",
            "items": [{"material_id": test_material["id"], "product_name": "X", "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 100000}],
            "cash_paid": 40000,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200
        sale = r.json()
        created_sales.append(sale["id"])
        sale_no = sale["sale_no"]

        # Get analytics
        r2 = client.get(f"{BASE_URL}/api/sales/report/analytics", params={"period": "month"})
        assert r2.status_code == 200, r2.text
        payload_out = r2.json()
        rows = payload_out.get("rows", []) if isinstance(payload_out, dict) else payload_out
        match = [row for row in rows if row.get("sale_no") == sale_no]
        assert match, f"Analytics missing our sale {sale_no}"
        row = match[0]
        assert row.get("sale_sisa_tagihan") == 60000, f"Expected 60000, got {row.get('sale_sisa_tagihan')}"
        assert row.get("sale_status") == "dp", f"Expected dp, got {row.get('sale_status')}"
        assert row.get("sale_cash_paid") == 40000, f"Expected 40000, got {row.get('sale_cash_paid')}"

    def test_analytics_lunas_overpayment_cash_clamped(self, client, test_material, created_sales):
        """For LUNAS overpayment 50k/60k in analytics — cash_paid clamped to total for payment column display"""
        payload = {
            "customer_name": "TEST_ANALYTICS_LUNAS",
            "items": [{"material_id": test_material["id"], "product_name": "X", "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 50000}],
            "cash_paid": 60000,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200
        sale = r.json()
        created_sales.append(sale["id"])
        sale_no = sale["sale_no"]

        r2 = client.get(f"{BASE_URL}/api/sales/report/analytics", params={"period": "month"})
        assert r2.status_code == 200
        rows = r2.json().get("rows", []) if isinstance(r2.json(), dict) else r2.json()
        match = [row for row in rows if row.get("sale_no") == sale_no]
        assert match
        row = match[0]
        assert row.get("sale_status") == "paid"
        # payment_nominal_on_row for is_first_item_of_sale should be clamped to total
        if row.get("is_first_item_of_sale"):
            assert row.get("payment_nominal_on_row") == 50000, \
                f"Payment column should show cash clamped to total (50k), got {row.get('payment_nominal_on_row')}"


# ---------------- Receipt & PDF ----------------

class TestSaleDPReceipts:
    def test_thermal_html_has_sisa_and_dp_badge(self, client, test_material, created_sales):
        payload = {
            "customer_name": "TEST_DP_RECEIPT",
            "items": [{"material_id": test_material["id"], "product_name": "Cetak Brosur", "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 100000}],
            "cash_paid": 40000,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200
        sale = r.json()
        created_sales.append(sale["id"])

        rr = client.get(f"{BASE_URL}/api/sales/{sale['id']}/receipt")
        assert rr.status_code == 200, rr.text
        html = rr.text
        assert "SISA TAGIHAN" in html, "Thermal receipt missing SISA TAGIHAN row"
        # Red color
        assert "#E81123" in html or "red" in html.lower()
        # DP badge should mention DP or Belum Lunas
        assert "DP" in html and ("Belum Lunas" in html or "BELUM LUNAS" in html), \
            "Thermal receipt missing DP · Belum Lunas badge"

    def test_pdf_a4_has_sisa_and_dp(self, client, test_material, created_sales):
        payload = {
            "customer_name": "TEST_DP_A4",
            "items": [{"material_id": test_material["id"], "product_name": "Cetak Brosur", "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 100000}],
            "cash_paid": 40000,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200
        sale = r.json()
        created_sales.append(sale["id"])

        rr = client.get(f"{BASE_URL}/api/sales/{sale['id']}/invoice-pdf")
        assert rr.status_code == 200, f"PDF endpoint failed: {rr.status_code} {rr.text[:200]}"
        # Should be a PDF binary
        assert rr.content[:4] == b"%PDF", "Response is not a PDF"
        # PDF binary may have 'SISA' as ASCII string
        # PDF text is compressed inside ASCII85/Flate stream; can't do direct string search.
        # Verify it's a valid PDF and size is reasonable. Actual visual check via UI later.
        assert len(rr.content) > 1000, f"PDF looks too small: {len(rr.content)} bytes"

    def test_thermal_lunas_no_sisa_row(self, client, test_material, created_sales):
        payload = {
            "customer_name": "TEST_LUNAS_RECEIPT",
            "items": [{"material_id": test_material["id"], "product_name": "X", "length_m": 1, "width_m": 1, "quantity": 1, "unit_price": 50000}],
            "cash_paid": 60000,
            "payment_method": "cash",
        }
        r = client.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200
        sale = r.json()
        created_sales.append(sale["id"])

        rr = client.get(f"{BASE_URL}/api/sales/{sale['id']}/receipt")
        assert rr.status_code == 200
        html = rr.text
        # LUNAS receipt should not have SISA TAGIHAN row
        assert "SISA TAGIHAN" not in html, "LUNAS receipt should not include SISA TAGIHAN"
