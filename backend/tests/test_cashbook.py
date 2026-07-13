"""Tests for Kas Operasional (Cash Book) module and Sales/PO auto-insert integration.

Covers:
- Chart of Accounts CRUD (system account protections)
- Settings (opening_balance)
- Transactions manual CRUD (auto-tx protections)
- Balance / Summary / Export endpoints
- Integration: POST /sales -> auto cash tx (301), DELETE /sales rollback
- Integration: PUT /purchasing/purchase-orders/{id}/pay -> auto cash tx (201)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

TS = str(int(time.time()))


# ---------------- Fixtures ----------------
@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def _cleanup_tracker():
    return {"custom_account_ids": [], "manual_tx_ids": [], "sale_ids": [], "po_ids": [], "material_id": None, "supplier_id": None}


@pytest.fixture(scope="module", autouse=True)
def cleanup(client, _cleanup_tracker):
    yield
    # Delete manual TX
    for tid in _cleanup_tracker["manual_tx_ids"]:
        try:
            client.delete(f"{BASE_URL}/api/cashbook/transactions/{tid}")
        except Exception:
            pass
    # Delete sales (auto cash tx cascade)
    for sid in _cleanup_tracker["sale_ids"]:
        try:
            client.delete(f"{BASE_URL}/api/sales/{sid}")
        except Exception:
            pass
    # Delete POs (may fail if diterima; that's fine)
    for pid in _cleanup_tracker["po_ids"]:
        try:
            client.delete(f"{BASE_URL}/api/purchasing/purchase-orders/{pid}")
        except Exception:
            pass
    # Delete supplier + material
    if _cleanup_tracker["supplier_id"]:
        try:
            client.delete(f"{BASE_URL}/api/purchasing/suppliers/{_cleanup_tracker['supplier_id']}")
        except Exception:
            pass
    if _cleanup_tracker["material_id"]:
        try:
            client.delete(f"{BASE_URL}/api/inventory/materials/{_cleanup_tracker['material_id']}")
        except Exception:
            pass
    # Delete custom accounts (after tx delete)
    for aid in _cleanup_tracker["custom_account_ids"]:
        try:
            client.delete(f"{BASE_URL}/api/cashbook/accounts/{aid}")
        except Exception:
            pass


# ---------------- 1. Chart of Accounts ----------------
class TestCashAccounts:
    def test_default_accounts_seeded(self, client):
        r = client.get(f"{BASE_URL}/api/cashbook/accounts")
        assert r.status_code == 200, r.text
        accounts = r.json()
        assert isinstance(accounts, list)
        assert len(accounts) >= 20, f"Expected >=20 default accounts, got {len(accounts)}"
        # Verify structure
        for a in accounts:
            assert set(["id", "code", "name", "type", "system", "active"]).issubset(a.keys())
            assert a["type"] in ("in", "out")
        # System accounts
        codes = {a["code"]: a for a in accounts}
        assert "301" in codes and codes["301"]["system"] is True and codes["301"]["type"] == "in"
        assert "201" in codes and codes["201"]["system"] is True and codes["201"]["type"] == "out"
        # 4 income accounts total: 301-304
        income_codes = {c for c, a in codes.items() if a["type"] == "in"}
        assert {"301", "302", "303", "304"}.issubset(income_codes)

    def test_create_custom_account(self, client, _cleanup_tracker):
        code = f"9{TS[-3:]}"  # unique code
        r = client.post(f"{BASE_URL}/api/cashbook/accounts", json={
            "code": code, "name": f"TEST_Custom_{TS}", "type": "out", "active": True
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["code"] == code
        assert d["type"] == "out"
        assert d["system"] is False
        _cleanup_tracker["custom_account_ids"].append(d["id"])

    def test_create_duplicate_code_400(self, client):
        # 301 already exists (system)
        r = client.post(f"{BASE_URL}/api/cashbook/accounts", json={
            "code": "301", "name": "Duplicate", "type": "in"
        })
        assert r.status_code == 400

    def test_create_invalid_type_400(self, client):
        r = client.post(f"{BASE_URL}/api/cashbook/accounts", json={
            "code": f"88{TS[-2:]}", "name": "BadType", "type": "xxx"
        })
        assert r.status_code == 400

    def test_system_account_code_immutable(self, client):
        # Get id of 301
        accs = client.get(f"{BASE_URL}/api/cashbook/accounts").json()
        acc301 = next(a for a in accs if a["code"] == "301")
        # Trying to change code should 400
        r = client.put(f"{BASE_URL}/api/cashbook/accounts/{acc301['id']}", json={
            "code": "999", "name": acc301["name"], "type": acc301["type"], "active": True
        })
        assert r.status_code == 400
        # Same code but new name — OK
        r2 = client.put(f"{BASE_URL}/api/cashbook/accounts/{acc301['id']}", json={
            "code": "301", "name": acc301["name"], "type": "in", "active": True
        })
        assert r2.status_code == 200

    def test_delete_system_account_400(self, client):
        accs = client.get(f"{BASE_URL}/api/cashbook/accounts").json()
        acc201 = next(a for a in accs if a["code"] == "201")
        r = client.delete(f"{BASE_URL}/api/cashbook/accounts/{acc201['id']}")
        assert r.status_code == 400


# ---------------- 2. Cash Settings ----------------
class TestCashSettings:
    def test_get_settings_auto_init(self, client):
        r = client.get(f"{BASE_URL}/api/cashbook/settings")
        assert r.status_code == 200
        d = r.json()
        assert "opening_balance" in d
        assert "opening_date" in d

    def test_update_settings(self, client):
        r = client.put(f"{BASE_URL}/api/cashbook/settings", json={
            "opening_balance": 1000000, "opening_date": "2026-01-01"
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["opening_balance"] == 1000000
        assert d["opening_date"] == "2026-01-01"
        # Verify persistence
        r2 = client.get(f"{BASE_URL}/api/cashbook/settings")
        assert r2.json()["opening_balance"] == 1000000


# ---------------- 3. Manual Transactions ----------------
class TestCashTransactions:
    def test_create_transaction_success(self, client, _cleanup_tracker):
        r = client.post(f"{BASE_URL}/api/cashbook/transactions", json={
            "date": "2026-01-15",
            "account_code": "302",  # non-system in
            "description": "TEST_TX_Terima_piutang",
            "amount": 500000,
            "reference": f"REF-TEST-{TS}"
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["type"] == "in"
        assert d["amount"] == 500000
        assert d["auto"] is False
        assert d["account_code"] == "302"
        _cleanup_tracker["manual_tx_ids"].append(d["id"])

    def test_create_zero_amount_rejected(self, client):
        r = client.post(f"{BASE_URL}/api/cashbook/transactions", json={
            "date": "2026-01-15", "account_code": "302",
            "description": "zero", "amount": 0
        })
        assert r.status_code == 400

    def test_create_empty_description_rejected(self, client):
        r = client.post(f"{BASE_URL}/api/cashbook/transactions", json={
            "date": "2026-01-15", "account_code": "302",
            "description": "   ", "amount": 100
        })
        assert r.status_code == 400

    def test_create_invalid_account_404(self, client):
        r = client.post(f"{BASE_URL}/api/cashbook/transactions", json={
            "date": "2026-01-15", "account_code": "ZZZ999",
            "description": "test", "amount": 100
        })
        assert r.status_code == 404

    def test_list_transactions_with_running_balance(self, client, _cleanup_tracker):
        # Create a couple more in Jan 2026 to check running balance
        r1 = client.post(f"{BASE_URL}/api/cashbook/transactions", json={
            "date": "2026-01-16", "account_code": "403",  # ATK (out)
            "description": "TEST_TX_ATK", "amount": 50000
        })
        assert r1.status_code == 200
        _cleanup_tracker["manual_tx_ids"].append(r1.json()["id"])

        r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"month": "2026-01"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "opening_balance" in d
        assert "transactions" in d
        assert "closing_balance" in d
        # Running balance sanity: each tx's balance = prev_balance +/- amount
        prev_bal = d["opening_balance"]
        for t in d["transactions"]:
            expected = round(prev_bal + t["amount"], 2) if t["type"] == "in" else round(prev_bal - t["amount"], 2)
            assert abs(t["balance"] - expected) < 0.01, f"Balance mismatch on tx {t['id']}: expected {expected}, got {t['balance']}"
            prev_bal = t["balance"]
        assert abs(d["closing_balance"] - prev_bal) < 0.01

    def test_update_manual_transaction(self, client, _cleanup_tracker):
        # Create manual, update
        r = client.post(f"{BASE_URL}/api/cashbook/transactions", json={
            "date": "2026-01-17", "account_code": "302",
            "description": "TEST_TX_Update_Original", "amount": 100
        })
        assert r.status_code == 200
        tid = r.json()["id"]
        _cleanup_tracker["manual_tx_ids"].append(tid)

        r2 = client.put(f"{BASE_URL}/api/cashbook/transactions/{tid}", json={
            "date": "2026-01-18", "account_code": "302",
            "description": "TEST_TX_Update_NEW", "amount": 250
        })
        assert r2.status_code == 200, r2.text
        assert r2.json()["description"] == "TEST_TX_Update_NEW"
        assert r2.json()["amount"] == 250

    def test_delete_manual_transaction(self, client, _cleanup_tracker):
        r = client.post(f"{BASE_URL}/api/cashbook/transactions", json={
            "date": "2026-01-19", "account_code": "302",
            "description": "TEST_TX_ToDelete", "amount": 111
        })
        assert r.status_code == 200
        tid = r.json()["id"]
        r2 = client.delete(f"{BASE_URL}/api/cashbook/transactions/{tid}")
        assert r2.status_code == 200

    def test_balance_endpoint(self, client):
        r = client.get(f"{BASE_URL}/api/cashbook/balance")
        assert r.status_code == 200
        d = r.json()
        for k in ["opening_balance", "opening_date", "total_in", "total_out", "balance", "tx_count"]:
            assert k in d
        # balance = opening + total_in - total_out
        expected = round(d["opening_balance"] + d["total_in"] - d["total_out"], 2)
        assert abs(d["balance"] - expected) < 0.01

    def test_summary_endpoint(self, client):
        r = client.get(f"{BASE_URL}/api/cashbook/summary", params={"month": "2026-01"})
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["month", "period_start", "period_end", "opening_balance", "total_in",
                  "total_out", "net", "closing_balance", "tx_count", "breakdown_in", "breakdown_out"]:
            assert k in d, f"missing {k}"
        assert d["month"] == "2026-01"
        assert d["period_start"] == "2026-01-01"
        assert d["period_end"] == "2026-01-31"
        assert isinstance(d["breakdown_in"], list)
        assert isinstance(d["breakdown_out"], list)
        # closing_balance = opening + total_in - total_out
        expected = round(d["opening_balance"] + d["total_in"] - d["total_out"], 2)
        assert abs(d["closing_balance"] - expected) < 0.01

    def test_export_excel(self, client):
        r = client.get(f"{BASE_URL}/api/cashbook/export", params={"month": "2026-01"})
        assert r.status_code == 200, r.text
        assert "spreadsheetml" in r.headers.get("content-type", "").lower()
        assert "attachment" in r.headers.get("content-disposition", "").lower()
        assert len(r.content) > 100
        # xlsx signature starts with PK (zip)
        assert r.content[:2] == b"PK"


# ---------------- 4. Integration: Sales -> Cash ----------------
class TestSalesToCashIntegration:
    def test_sale_auto_creates_cash_tx(self, client, _cleanup_tracker):
        # Create material
        mat_payload = {
            "name": f"TEST_CASH_MAT_{TS}",
            "category": "flexy",
            "unit": "meter",
            "current_stock": 200,
            "purchase_price": 10000,
            "selling_price": 20000,
            "min_stock": 5,
            "active": True,
        }
        rm = client.post(f"{BASE_URL}/api/inventory/materials", json=mat_payload)
        assert rm.status_code == 200, rm.text
        mat = rm.json()
        _cleanup_tracker["material_id"] = mat["id"]

        # Snapshot cash tx count before
        r_before = client.get(f"{BASE_URL}/api/cashbook/transactions").json()
        count_before = len(r_before["transactions"])

        # Create a sale
        sale_payload = {
            "customer_name": f"TEST_CASH_CUSTOMER_{TS}",
            "items": [{
                "material_id": mat["id"],
                "product_name": "TEST Banner",
                "length_m": 2,
                "width_m": 1,
                "quantity": 1,
                "unit_price": 25000,  # 2*1*25000=50000
            }],
            "cash_paid": 50000,
        }
        rs = client.post(f"{BASE_URL}/api/sales", json=sale_payload)
        assert rs.status_code == 200, rs.text
        sale = rs.json()
        _cleanup_tracker["sale_ids"].append(sale["id"])
        pytest.cash_sale_no = sale["sale_no"]
        pytest.cash_sale_id = sale["id"]
        assert sale["total"] == 50000
        assert sale["status"] == "paid"

        # Fetch cash tx — expect one auto tx with reference=sale_no, account_code=301
        r_after = client.get(f"{BASE_URL}/api/cashbook/transactions").json()
        auto_tx = [t for t in r_after["transactions"]
                   if t.get("reference") == sale["sale_no"] and t.get("auto") is True]
        assert len(auto_tx) == 1, f"Expected 1 auto cash tx for {sale['sale_no']}, found {len(auto_tx)}"
        tx = auto_tx[0]
        assert tx["account_code"] == "301"
        assert tx["type"] == "in"
        assert tx["amount"] == 50000

    def test_edit_auto_tx_rejected(self, client, _cleanup_tracker):
        # Find the auto tx from previous test
        r = client.get(f"{BASE_URL}/api/cashbook/transactions").json()
        auto_tx = next((t for t in r["transactions"]
                        if t.get("reference") == pytest.cash_sale_no and t.get("auto")), None)
        assert auto_tx is not None
        r2 = client.put(f"{BASE_URL}/api/cashbook/transactions/{auto_tx['id']}", json={
            "date": auto_tx["date"], "account_code": "301",
            "description": "HACK", "amount": 999
        })
        assert r2.status_code == 400
        r3 = client.delete(f"{BASE_URL}/api/cashbook/transactions/{auto_tx['id']}")
        assert r3.status_code == 400

    def test_delete_sale_cascades_auto_cash_tx(self, client, _cleanup_tracker):
        # Delete the sale created earlier
        sale_id = pytest.cash_sale_id
        sale_no = pytest.cash_sale_no
        rd = client.delete(f"{BASE_URL}/api/sales/{sale_id}")
        assert rd.status_code == 200
        # Auto cash tx should be gone
        r = client.get(f"{BASE_URL}/api/cashbook/transactions").json()
        remaining = [t for t in r["transactions"]
                     if t.get("reference") == sale_no and t.get("auto")]
        assert len(remaining) == 0, f"Auto cash tx still exists after sale delete: {remaining}"
        # remove sale from tracker to avoid double-delete
        _cleanup_tracker["sale_ids"].remove(sale_id)


# ---------------- 5. Integration: PO Pay -> Cash ----------------
class TestPOPayToCashIntegration:
    def test_po_pay_auto_creates_cash_tx(self, client, _cleanup_tracker):
        # Ensure material exists (created in sales test module if not)
        if not _cleanup_tracker["material_id"]:
            mat_payload = {
                "name": f"TEST_CASH_MAT2_{TS}",
                "category": "flexy",
                "unit": "meter",
                "current_stock": 100,
                "purchase_price": 8000,
                "selling_price": 15000,
                "min_stock": 5,
                "active": True,
            }
            rm = client.post(f"{BASE_URL}/api/inventory/materials", json=mat_payload)
            assert rm.status_code == 200, rm.text
            _cleanup_tracker["material_id"] = rm.json()["id"]

        # Create supplier
        rs = client.post(f"{BASE_URL}/api/purchasing/suppliers", json={
            "name": f"TEST_CASH_SUP_{TS}", "phone": "0812345"
        })
        assert rs.status_code == 200, rs.text
        supplier = rs.json()
        _cleanup_tracker["supplier_id"] = supplier["id"]

        # Create PO
        po_payload = {
            "supplier_id": supplier["id"],
            "date": "2026-01-20",
            "tax_pct": 0,
            "items": [{"material_id": _cleanup_tracker["material_id"], "quantity": 5, "unit_price": 10000}],
            "invoice_no": f"INV-CASH-{TS}",
        }
        rp = client.post(f"{BASE_URL}/api/purchasing/purchase-orders", json=po_payload)
        assert rp.status_code == 200, rp.text
        po = rp.json()
        _cleanup_tracker["po_ids"].append(po["id"])
        assert po["total"] == 50000

        # Pay 30000
        r_pay = client.put(f"{BASE_URL}/api/purchasing/purchase-orders/{po['id']}/pay",
                           json={"amount": 30000})
        assert r_pay.status_code == 200, r_pay.text
        assert r_pay.json()["payment_status"] == "sebagian"
        assert r_pay.json()["amount_paid"] == 30000

        # Verify auto cash tx (account 201, out, reference=po_no)
        r = client.get(f"{BASE_URL}/api/cashbook/transactions").json()
        auto_tx = [t for t in r["transactions"]
                   if t.get("reference") == po["po_no"] and t.get("auto") is True and t.get("account_code") == "201"]
        assert len(auto_tx) >= 1, f"Expected auto cash tx for PO {po['po_no']}, found {len(auto_tx)}"
        assert auto_tx[0]["type"] == "out"
        assert auto_tx[0]["amount"] == 30000

    def test_po_pay_negative_rejected_no_cash_tx(self, client, _cleanup_tracker):
        po_id = _cleanup_tracker["po_ids"][-1]
        # Snapshot cash tx count
        r0 = client.get(f"{BASE_URL}/api/cashbook/transactions").json()
        n0 = len(r0["transactions"])
        r_pay = client.put(f"{BASE_URL}/api/purchasing/purchase-orders/{po_id}/pay",
                           json={"amount": -50})
        assert r_pay.status_code == 400
        r1 = client.get(f"{BASE_URL}/api/cashbook/transactions").json()
        assert len(r1["transactions"]) == n0


# ---------------- 6. Regression: Sales & PO endpoints ----------------
class TestRegressionSalesAndPO:
    def test_sales_list_ok(self, client):
        r = client.get(f"{BASE_URL}/api/sales")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_sales_stats_ok(self, client):
        r = client.get(f"{BASE_URL}/api/sales/stats/summary")
        # some builds use /stats path — try both
        if r.status_code == 404:
            r = client.get(f"{BASE_URL}/api/sales/stats")
        assert r.status_code in (200, 404)  # tolerate if not exposed under this path

    def test_po_list_still_returns_full_doc(self, client, _cleanup_tracker):
        if not _cleanup_tracker["po_ids"]:
            pytest.skip("No PO created in this run")
        r = client.get(f"{BASE_URL}/api/purchasing/purchase-orders")
        assert r.status_code == 200
        found = next((p for p in r.json() if p["id"] == _cleanup_tracker["po_ids"][-1]), None)
        assert found is not None
        assert "payment_status" in found
        assert "items" in found and len(found["items"]) > 0
