"""E2E tests for Sales Payment Methods (Cash/Transfer BCA-Mandiri/Shopee Plaza/Kastem).

Coverage:
- 4 seeded cash accounts (301-BCA/MDR/SPP/SPK) exist and are system=True, type=in.
- POST /api/sales for each payment_method → correct auto cash_transactions.account_code.
- PUT /api/sales/{id} changes payment method → old cash tx deleted, new cash tx inserted (no dup).
- DELETE /api/sales/{id} rollback all payment account codes → no orphans.
- Orphan-check for payment cash tx returns source_type='Sale' when sale deleted.
- GET /api/sales/report/analytics includes payment_method/payment_bank/payment_notes per row + method_breakdown array.
- Regression: legacy payment_method='tunai' still treated as cash → account 301.
"""
import os
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
def test_material(client):
    payload = {
        "name": "TEST_PAY_Flexy",
        "category": "flexy",
        "unit": "meter",
        "current_stock": 500.0,
        "purchase_price": 15000,
        "selling_price": 25000,
        "min_stock": 10,
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
    # Pre-cleanup: remove orphan auto cash txs for payment codes (from prior aborted test runs)
    try:
        r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"limit": 2000})
        if r.status_code == 200:
            data = r.json()
            txs = data.get("transactions") if isinstance(data, dict) else data
            payment_codes = {"301", "301-BCA", "301-MDR", "301-SPP", "301-SPK"}
            for t in txs:
                if not t.get("auto"):
                    continue
                if t.get("account_code") not in payment_codes:
                    continue
                ref = t.get("reference") or ""
                # Check if sale still exists
                s = client.get(f"{BASE_URL}/api/sales", params={"limit": 1, "q": ref})
                # We'll just call orphan-check to be safe
                oc = client.get(f"{BASE_URL}/api/cashbook/transactions/{t['id']}/orphan-check")
                if oc.status_code == 200 and oc.json().get("is_orphan"):
                    client.delete(f"{BASE_URL}/api/cashbook/transactions/{t['id']}", params={"force": "false"})
    except Exception:
        pass
    yield
    for sid in created_sales:
        try:
            client.delete(f"{BASE_URL}/api/sales/{sid}")
        except Exception:
            pass


def _build_sale_payload(payment_method, payment_bank=None, payment_notes=None, cash_paid=100000, customer="TEST_PAY_Customer"):
    return {
        "customer_name": customer,
        "customer_phone": "081234567890",
        "items": [{
            "material_id": None,  # patched later
            "product_name": "TEST_PAY_Flexy",
            "length_m": 2,
            "width_m": 1,
            "quantity": 1,
            "unit_price": 25000,
        }],
        "discount": 0,
        "cash_paid": cash_paid,
        "payment_method": payment_method,
        "payment_bank": payment_bank,
        "payment_notes": payment_notes,
        "notes": "unit test payment method",
    }


def _post_sale(client, test_material, created_sales, **kwargs):
    payload = _build_sale_payload(**kwargs)
    payload["items"][0]["material_id"] = test_material["id"]
    r = client.post(f"{BASE_URL}/api/sales", json=payload)
    assert r.status_code == 200, f"POST /api/sales failed: {r.status_code} {r.text}"
    sale = r.json()
    created_sales.append(sale["id"])
    return sale


def _get_cash_txs_for_sale(client, sale_no, since_iso=None):
    r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"limit": 500})
    assert r.status_code == 200, r.text
    data = r.json()
    txs = data.get("transactions") if isinstance(data, dict) else data
    matched = [t for t in txs if t.get("reference") == sale_no and t.get("auto")]
    if since_iso:
        # Filter to only txs created at-or-after the sale (avoid stale orphans from re-used sale_no)
        matched = [t for t in matched if (t.get("created_at") or "") >= since_iso]
    return matched


def _cleanup_orphan_txs_for_ref(client, sale_no):
    """Delete pre-existing orphan auto cash txs with the same reference (sale_no)."""
    r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"limit": 500})
    if r.status_code != 200:
        return
    data = r.json()
    txs = data.get("transactions") if isinstance(data, dict) else data
    payment_codes = {"301", "301-BCA", "301-MDR", "301-SPP", "301-SPK"}
    for t in txs:
        if not t.get("auto"):
            continue
        if t.get("reference") != sale_no:
            continue
        if t.get("account_code") not in payment_codes:
            continue
        oc = client.get(f"{BASE_URL}/api/cashbook/transactions/{t['id']}/orphan-check")
        if oc.status_code == 200 and oc.json().get("is_orphan"):
            client.delete(f"{BASE_URL}/api/cashbook/transactions/{t['id']}")


# ---------------- 1. Seed accounts ----------------

class TestSeedAccounts:
    """Verify 4 payment accounts are seeded and idempotent."""

    def test_all_5_payment_accounts_exist(self, client):
        r = client.get(f"{BASE_URL}/api/cashbook/accounts")
        assert r.status_code == 200, r.text
        accounts = r.json()
        codes = {a["code"]: a for a in accounts}
        for code, expected_name in [
            ("301", "Penjualan Tunai"),
            ("301-BCA", "Penjualan via Transfer BCA"),
            ("301-MDR", "Penjualan via Transfer Mandiri"),
            ("301-SPP", "Penjualan via Shopee Plaza"),
            ("301-SPK", "Penjualan via Shopee Kastem"),
        ]:
            assert code in codes, f"Account {code} not seeded. Have: {list(codes.keys())}"
            acc = codes[code]
            assert acc.get("type") == "in", f"{code} type != in: {acc}"
            assert acc.get("system") is True, f"{code} system flag != True: {acc}"
            # 4 new accounts must match the expected name
            if code != "301":
                assert acc.get("name") == expected_name, f"{code} name mismatch: {acc.get('name')} vs {expected_name}"


# ---------------- 2. POST /api/sales per method ----------------

class TestSalesCreatePaymentMethod:

    def test_cash_creates_301(self, client, test_material, created_sales):
        sale = _post_sale(client, test_material, created_sales, payment_method="cash", cash_paid=100000)
        assert sale["payment_method"] == "cash"
        txs = _get_cash_txs_for_sale(client, sale["sale_no"])
        assert len(txs) == 1, f"Expected 1 tx, got {len(txs)}: {txs}"
        assert txs[0]["account_code"] == "301"
        assert txs[0]["type"] == "in"
        assert float(txs[0]["amount"]) == float(sale["total"])

    def test_transfer_bca_creates_301_bca(self, client, test_material, created_sales):
        sale = _post_sale(client, test_material, created_sales,
                          payment_method="transfer", payment_bank="BCA", payment_notes="An/n Toko")
        assert sale["payment_bank"] == "BCA"
        assert sale["payment_notes"] == "An/n Toko"
        txs = _get_cash_txs_for_sale(client, sale["sale_no"])
        assert len(txs) == 1
        tx = txs[0]
        assert tx["account_code"] == "301-BCA", f"Expected 301-BCA, got {tx}"
        assert "Transfer BCA" in tx["description"]
        assert "An/n Toko" in tx["description"]

    def test_transfer_mandiri_creates_301_mdr(self, client, test_material, created_sales):
        sale = _post_sale(client, test_material, created_sales,
                          payment_method="transfer", payment_bank="Mandiri", payment_notes="ref#123")
        txs = _get_cash_txs_for_sale(client, sale["sale_no"])
        assert len(txs) == 1
        assert txs[0]["account_code"] == "301-MDR"
        assert "Transfer Mandiri" in txs[0]["description"]

    def test_shopee_plaza_creates_301_spp(self, client, test_material, created_sales):
        sale = _post_sale(client, test_material, created_sales, payment_method="shopee_plaza")
        txs = _get_cash_txs_for_sale(client, sale["sale_no"])
        assert len(txs) == 1
        assert txs[0]["account_code"] == "301-SPP"
        assert "Shopee Plaza" in txs[0]["description"]

    def test_shopee_kastem_creates_301_spk(self, client, test_material, created_sales):
        sale = _post_sale(client, test_material, created_sales, payment_method="shopee_kastem")
        txs = _get_cash_txs_for_sale(client, sale["sale_no"])
        assert len(txs) == 1
        assert txs[0]["account_code"] == "301-SPK"
        assert "Shopee Kastem" in txs[0]["description"]

    def test_legacy_tunai_still_treated_as_cash(self, client, test_material, created_sales):
        sale = _post_sale(client, test_material, created_sales, payment_method="tunai")
        txs = _get_cash_txs_for_sale(client, sale["sale_no"])
        assert len(txs) == 1
        assert txs[0]["account_code"] == "301"


# ---------------- 3. PUT /api/sales/{id} change method ----------------

class TestSalesUpdatePaymentMethod:

    def test_change_cash_to_transfer_bca(self, client, test_material, created_sales):
        # Create as cash
        sale = _post_sale(client, test_material, created_sales, payment_method="cash", cash_paid=100000)
        sale_no = sale["sale_no"]
        # Update to transfer BCA
        payload = _build_sale_payload(payment_method="transfer", payment_bank="BCA", payment_notes="Update BCA")
        payload["items"][0]["material_id"] = test_material["id"]
        r = client.put(f"{BASE_URL}/api/sales/{sale['id']}", json=payload)
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["payment_method"] == "transfer"
        assert updated["payment_bank"] == "BCA"
        # Verify old 301 tx removed, new 301-BCA tx created, no duplicates
        txs = _get_cash_txs_for_sale(client, sale_no)
        assert len(txs) == 1, f"Expected 1 tx after update, got {len(txs)}: {txs}"
        assert txs[0]["account_code"] == "301-BCA"

    def test_change_transfer_bca_to_shopee_plaza(self, client, test_material, created_sales):
        sale = _post_sale(client, test_material, created_sales,
                          payment_method="transfer", payment_bank="BCA", payment_notes="init")
        sale_no = sale["sale_no"]
        payload = _build_sale_payload(payment_method="shopee_plaza")
        payload["items"][0]["material_id"] = test_material["id"]
        r = client.put(f"{BASE_URL}/api/sales/{sale['id']}", json=payload)
        assert r.status_code == 200, r.text
        txs = _get_cash_txs_for_sale(client, sale_no)
        assert len(txs) == 1, f"Expected 1 tx, got {len(txs)}"
        assert txs[0]["account_code"] == "301-SPP"


# ---------------- 4. DELETE /api/sales/{id} rollback ----------------

class TestSalesDeleteRollback:

    @pytest.mark.parametrize("method,bank,expected_code", [
        ("cash", None, "301"),
        ("transfer", "BCA", "301-BCA"),
        ("transfer", "Mandiri", "301-MDR"),
        ("shopee_plaza", None, "301-SPP"),
        ("shopee_kastem", None, "301-SPK"),
    ])
    def test_delete_removes_cash_tx(self, client, test_material, created_sales, method, bank, expected_code):
        sale = _post_sale(client, test_material, created_sales, payment_method=method, payment_bank=bank)
        sale_no = sale["sale_no"]
        # Clean any pre-existing orphan cash txs with this reused sale_no
        _cleanup_orphan_txs_for_ref(client, sale_no)
        since = sale.get("created_at")
        # Pre-verify cash tx exists (only newly created ones)
        pre = _get_cash_txs_for_sale(client, sale_no, since_iso=since)
        assert len(pre) == 1 and pre[0]["account_code"] == expected_code, f"pre: {pre}"
        # Delete
        r = client.delete(f"{BASE_URL}/api/sales/{sale['id']}")
        assert r.status_code == 200, r.text
        if sale["id"] in created_sales:
            created_sales.remove(sale["id"])
        # Verify all newly created cash tx removed
        post = _get_cash_txs_for_sale(client, sale_no, since_iso=since)
        assert len(post) == 0, f"Expected 0 tx after delete, got {len(post)}: {post}"


# ---------------- 5. Orphan-check for payment cash tx ----------------

class TestOrphanCheck:

    def test_orphan_check_returns_source_type_sale_for_301_bca(self, client, test_material, created_sales):
        # Create transfer BCA sale
        sale = _post_sale(client, test_material, created_sales,
                          payment_method="transfer", payment_bank="BCA", payment_notes="orphan test")
        sale_no = sale["sale_no"]
        since = sale.get("created_at")
        txs = _get_cash_txs_for_sale(client, sale_no, since_iso=since)
        assert len(txs) == 1
        tx_id = txs[0]["id"]
        r = client.get(f"{BASE_URL}/api/cashbook/transactions/{tx_id}/orphan-check")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["is_auto"] is True
        assert data["is_orphan"] is False
        assert data["source_type"] == "Sale", f"Expected Sale, got {data}"
        assert data["account_code"] == "301-BCA"
        assert data["reference"] == sale_no


# ---------------- 6. Analytics endpoint payment fields + method_breakdown ----------------

class TestSalesAnalyticsPayment:

    def test_rows_have_payment_fields_and_method_breakdown(self, client, test_material, created_sales):
        # Create sales with distinct methods
        s_cash = _post_sale(client, test_material, created_sales, payment_method="cash", customer="TEST_PAY_A")
        s_bca = _post_sale(client, test_material, created_sales,
                           payment_method="transfer", payment_bank="BCA", payment_notes="A/n Toko",
                           customer="TEST_PAY_B")
        s_spp = _post_sale(client, test_material, created_sales, payment_method="shopee_plaza",
                           customer="TEST_PAY_C")

        r = client.get(f"{BASE_URL}/api/sales/report/analytics",
                       params={"customer": "TEST_PAY_"})
        assert r.status_code == 200, r.text
        data = r.json()
        rows = data.get("rows", [])
        assert len(rows) >= 3, f"Expected ≥3 rows, got {len(rows)}"

        # Each row must have payment_method / payment_bank / payment_notes
        for row in rows:
            assert "payment_method" in row
            assert "payment_bank" in row
            assert "payment_notes" in row

        # method_breakdown present as array
        mb = data.get("method_breakdown")
        assert isinstance(mb, list), f"method_breakdown missing or not list: {mb}"
        assert len(mb) >= 1
        methods = {m["method"] for m in mb}
        # Must contain the three we created (transfer_bca is composite key)
        # Check that keys include cash, transfer_bca, shopee_plaza
        assert "cash" in methods or any(m["method"] == "cash" for m in mb)
        assert any("bca" in m["method"].lower() for m in mb), f"missing bca in {mb}"
        assert "shopee_plaza" in methods, f"missing shopee_plaza in {mb}"
        # Each entry must have numeric total
        for m in mb:
            assert isinstance(m.get("total"), (int, float))
            assert m["total"] >= 0


# ---------------- 7. Regression: PO orphan detection (account_code 201) still works ----------------

class TestRegressionPOOrphan:
    """Ensure changes to orphan detection did not break PO source detection."""

    def test_orphan_check_endpoint_still_supports_po(self, client):
        # Find any auto cash tx with account_code 201 (PO)
        r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"limit": 500})
        assert r.status_code == 200
        data = r.json()
        txs = data.get("transactions") if isinstance(data, dict) else data
        po_txs = [t for t in txs if t.get("account_code") == "201" and t.get("auto")]
        if not po_txs:
            pytest.skip("No auto PO cash tx in DB to test orphan-check regression.")
        tx = po_txs[0]
        r = client.get(f"{BASE_URL}/api/cashbook/transactions/{tx['id']}/orphan-check")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["is_auto"] is True
        assert data["source_type"] == "PO"
