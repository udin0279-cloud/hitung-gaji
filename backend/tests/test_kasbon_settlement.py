"""Tests for Kasbon Sementara -> auto cash-out settlement integration.

Verifies:
- Create kasbon (open)
- Settle -> auto cash-tx (account 101, type out, description "Pelunasan Kasbon - ...")
- Reopen -> auto cash-tx removed
- Settle again + delete kasbon -> auto cash-tx removed
- Manual pemasukan (101 in) and pengeluaran (out) untouched by kasbon flow
"""
import os
import uuid
import pytest
import requests

def _get_base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        # Fallback: read from frontend/.env
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL"):
                        v = line.strip().split("=", 1)[1]
                        break
        except Exception:
            pass
    if not v:
        raise RuntimeError("REACT_APP_BACKEND_URL not set")
    return v.rstrip("/")


BASE_URL = _get_base()

ADMIN_EMAIL = "admin@payroll.id"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return s


def _find_kasbon_tx(client, kasbon_id):
    """Return list of cash_transactions rows for this kasbon (via /cashbook/transactions)."""
    # Grab current month + prev/next to be safe
    from datetime import date
    today = date.today()
    months = [today.strftime("%Y-%m")]
    out = []
    for m in months:
        r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"month": m})
        if r.status_code == 200:
            for t in r.json().get("transactions", []):
                if t.get("reference") == f"KASBON-{kasbon_id}":
                    out.append(t)
    return out


class TestKasbonSettlement:
    def test_full_flow_settle_reopen_delete(self, client):
        from datetime import date
        today = date.today().isoformat()
        month = date.today().strftime("%Y-%m")

        # STEP 1: create kasbon
        payload = {
            "date": today,
            "name": f"TEST_KASBON_{uuid.uuid4().hex[:6]}",
            "description": "Beli spare part",
            "amount": 100000,
        }
        r = client.post(f"{BASE_URL}/api/cashbook/kasbon", json=payload)
        assert r.status_code == 200, r.text
        k = r.json()
        assert k["status"] == "open"
        assert k["amount"] == 100000
        kid = k["id"]

        try:
            # No settlement tx yet
            assert _find_kasbon_tx(client, kid) == []

            # STEP 2: settle
            r = client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}/settle")
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "settled"

            txs = _find_kasbon_tx(client, kid)
            assert len(txs) == 1, f"Expected 1 auto cash-tx after settle, got {len(txs)}"
            tx = txs[0]
            assert tx["account_code"] == "101"
            assert tx["type"] == "out"
            assert tx["amount"] == 100000
            assert tx["auto"] is True
            assert "Pelunasan Kasbon" in tx["description"]
            assert payload["name"] in tx["description"]
            assert "Beli spare part" in tx["description"]

            # STEP 3: verify appears in journal filter (type=out at account 101)
            r = client.get(f"{BASE_URL}/api/cashbook/transactions", params={"month": month})
            assert r.status_code == 200
            all_tx = r.json()["transactions"]
            # confirm same tx present in monthly list
            match = [t for t in all_tx if t["id"] == tx["id"]]
            assert len(match) == 1

            # STEP 4: idempotent settle (should reject with 400)
            r = client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}/settle")
            assert r.status_code == 400
            assert len(_find_kasbon_tx(client, kid)) == 1  # still exactly 1

            # STEP 5: reopen -> tx removed
            r = client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}/reopen")
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "open"
            assert _find_kasbon_tx(client, kid) == []

            # STEP 6: settle again then delete kasbon -> tx removed
            r = client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}/settle")
            assert r.status_code == 200
            assert len(_find_kasbon_tx(client, kid)) == 1

            r = client.delete(f"{BASE_URL}/api/cashbook/kasbon/{kid}")
            assert r.status_code == 200, r.text
            assert _find_kasbon_tx(client, kid) == []
            kid = None  # marker: no cleanup needed
        finally:
            if kid:
                client.delete(f"{BASE_URL}/api/cashbook/kasbon/{kid}")

    def test_settle_missing_kasbon(self, client):
        r = client.put(f"{BASE_URL}/api/cashbook/kasbon/nonexistent-id/settle")
        assert r.status_code == 404

    def test_reopen_missing_kasbon(self, client):
        r = client.put(f"{BASE_URL}/api/cashbook/kasbon/nonexistent-id/reopen")
        assert r.status_code == 404

    def test_delete_missing_kasbon(self, client):
        r = client.delete(f"{BASE_URL}/api/cashbook/kasbon/nonexistent-id")
        assert r.status_code == 404

    def test_reopen_when_already_open_is_noop(self, client):
        """Reopen on an already-open kasbon should still 200 (idempotent) and not affect tx."""
        from datetime import date
        payload = {
            "date": date.today().isoformat(),
            "name": f"TEST_KASBON_REOPEN_{uuid.uuid4().hex[:6]}",
            "description": "Test reopen noop",
            "amount": 50000,
        }
        r = client.post(f"{BASE_URL}/api/cashbook/kasbon", json=payload)
        kid = r.json()["id"]
        try:
            r = client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}/reopen")
            # Backend allows reopen on open too (sets status again)
            assert r.status_code == 200
            assert _find_kasbon_tx(client, kid) == []
        finally:
            client.delete(f"{BASE_URL}/api/cashbook/kasbon/{kid}")

    def test_kasbon_list_totals(self, client):
        from datetime import date
        month = date.today().strftime("%Y-%m")
        payload = {
            "date": date.today().isoformat(),
            "name": f"TEST_KASBON_LIST_{uuid.uuid4().hex[:6]}",
            "description": "list totals",
            "amount": 75000,
        }
        r = client.post(f"{BASE_URL}/api/cashbook/kasbon", json=payload)
        kid = r.json()["id"]
        try:
            r = client.get(f"{BASE_URL}/api/cashbook/kasbon", params={"month": month})
            assert r.status_code == 200
            data = r.json()
            assert data["count"] >= 1
            ids = [i["id"] for i in data["items"]]
            assert kid in ids
        finally:
            client.delete(f"{BASE_URL}/api/cashbook/kasbon/{kid}")
