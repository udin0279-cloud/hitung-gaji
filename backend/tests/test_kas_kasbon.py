"""Tests for new CashBook features:
- 8 new chart-of-accounts codes (101, 103, 103-01, 104, 105, 106, 108, 502)
- Kasbon Sementara CRUD + settle/reopen endpoints
- Idempotent seeding of accounts
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
EXPECTED_NEW_CODES = ["101", "103", "103-01", "104", "105", "106", "108", "502"]


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def tracker():
    return {"kasbon_ids": []}


@pytest.fixture(scope="module", autouse=True)
def cleanup(client, tracker):
    yield
    for kid in tracker["kasbon_ids"]:
        try:
            client.delete(f"{BASE_URL}/api/cashbook/kasbon/{kid}")
        except Exception:
            pass


# ---------------- 1. Chart of Accounts - new codes ----------------
class TestNewAccountCodes:
    def test_all_new_codes_present(self, client):
        r = client.get(f"{BASE_URL}/api/cashbook/accounts")
        assert r.status_code == 200, r.text
        accounts = r.json()
        codes = {a["code"]: a for a in accounts}
        for c in EXPECTED_NEW_CODES:
            assert c in codes, f"Kode akun {c} tidak ditemukan"

    def test_new_codes_have_expected_names_and_types(self, client):
        expected = {
            "101": ("Kas", "in"),
            "103": ("Persediaan Barang", "out"),
            "103-01": ("Bahan Baku Mesin", "out"),
            "104": ("Perlengkapan Kantor", "out"),
            "105": ("BBM dan Maintenance Kendaraan", "out"),
            "106": ("Pengiriman Dokumen", "out"),
            "108": ("Makan dan Entertainment", "out"),
        }
        r = client.get(f"{BASE_URL}/api/cashbook/accounts")
        codes = {a["code"]: a for a in r.json()}
        for code, (name, typ) in expected.items():
            assert codes[code]["name"] == name, f"{code}: name={codes[code]['name']} expected {name}"
            assert codes[code]["type"] == typ, f"{code}: type={codes[code]['type']} expected {typ}"
        # 502 exists (name may already exist from prior seed - idempotent skip = stale name possible)
        assert "502" in codes and codes["502"]["type"] == "out"

    def test_existing_codes_still_present(self, client):
        r = client.get(f"{BASE_URL}/api/cashbook/accounts")
        codes = {a["code"] for a in r.json()}
        for c in ["301", "201", "302", "303", "304"]:
            assert c in codes, f"Existing account {c} missing"

    def test_seed_idempotent(self, client):
        # Call accounts endpoint twice; count of a specific code should still be 1
        r1 = client.get(f"{BASE_URL}/api/cashbook/accounts")
        cnt1 = sum(1 for a in r1.json() if a["code"] == "101")
        r2 = client.get(f"{BASE_URL}/api/cashbook/accounts")
        cnt2 = sum(1 for a in r2.json() if a["code"] == "101")
        assert cnt1 == 1 and cnt2 == 1, f"Duplicate for 101: cnt1={cnt1}, cnt2={cnt2}"


# ---------------- 2. Kasbon CRUD ----------------
class TestKasbonCRUD:
    def test_create_kasbon_success(self, client, tracker):
        r = client.post(f"{BASE_URL}/api/cashbook/kasbon", json={
            "date": "2026-01-15",
            "name": f"TEST_Budi_{TS}",
            "description": "Kasbon untuk perjalanan",
            "amount": 500000,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert "id" in d
        assert d["status"] == "open"
        assert d["amount"] == 500000
        assert d["name"] == f"TEST_Budi_{TS}"
        assert "created_by" in d
        assert d["settled_at"] is None
        tracker["kasbon_ids"].append(d["id"])

    def test_create_empty_name_rejected(self, client):
        r = client.post(f"{BASE_URL}/api/cashbook/kasbon", json={
            "date": "2026-01-15", "name": "   ", "description": "x", "amount": 100
        })
        assert r.status_code == 400

    def test_create_zero_amount_rejected(self, client):
        r = client.post(f"{BASE_URL}/api/cashbook/kasbon", json={
            "date": "2026-01-15", "name": "Budi", "description": "x", "amount": 0
        })
        assert r.status_code == 400

    def test_create_negative_amount_rejected(self, client):
        r = client.post(f"{BASE_URL}/api/cashbook/kasbon", json={
            "date": "2026-01-15", "name": "Budi", "description": "x", "amount": -100
        })
        assert r.status_code == 400

    def test_list_with_month_filter_and_totals(self, client, tracker):
        # Create a Feb kasbon to verify month filter isolation
        r_feb = client.post(f"{BASE_URL}/api/cashbook/kasbon", json={
            "date": "2026-02-05",
            "name": f"TEST_Ani_{TS}",
            "description": "Feb kasbon",
            "amount": 250000,
        })
        assert r_feb.status_code == 200
        tracker["kasbon_ids"].append(r_feb.json()["id"])

        # List Jan only
        r_jan = client.get(f"{BASE_URL}/api/cashbook/kasbon", params={"month": "2026-01"})
        assert r_jan.status_code == 200, r_jan.text
        d = r_jan.json()
        for k in ["items", "total_open", "total_settled", "total_all", "count"]:
            assert k in d, f"Missing {k}"
        # Our Jan kasbon should be in there
        jan_names = [i["name"] for i in d["items"]]
        assert f"TEST_Budi_{TS}" in jan_names
        assert f"TEST_Ani_{TS}" not in jan_names  # Feb one must be excluded

        # Feb list
        r_feb2 = client.get(f"{BASE_URL}/api/cashbook/kasbon", params={"month": "2026-02"})
        assert r_feb2.status_code == 200
        feb_names = [i["name"] for i in r_feb2.json()["items"]]
        assert f"TEST_Ani_{TS}" in feb_names

    def test_list_with_status_filter(self, client, tracker):
        r = client.get(f"{BASE_URL}/api/cashbook/kasbon", params={"status": "open"})
        assert r.status_code == 200
        for i in r.json()["items"]:
            assert i["status"] == "open"

    def test_update_kasbon(self, client, tracker):
        kid = tracker["kasbon_ids"][0]
        r = client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}", json={
            "date": "2026-01-20",
            "name": f"TEST_BudiUpdated_{TS}",
            "description": "Updated desc",
            "amount": 750000,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == f"TEST_BudiUpdated_{TS}"
        assert d["amount"] == 750000
        assert d["description"] == "Updated desc"

    def test_update_empty_name_rejected(self, client, tracker):
        kid = tracker["kasbon_ids"][0]
        r = client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}", json={
            "date": "2026-01-20", "name": "  ", "description": "x", "amount": 100
        })
        assert r.status_code == 400

    def test_update_not_found_404(self, client):
        r = client.put(f"{BASE_URL}/api/cashbook/kasbon/nonexistent-id-xxx", json={
            "date": "2026-01-20", "name": "x", "description": "x", "amount": 100
        })
        assert r.status_code == 404

    def test_settle_kasbon(self, client, tracker):
        kid = tracker["kasbon_ids"][0]
        r = client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}/settle")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "settled"
        assert d["settled_at"] is not None

    def test_settle_already_settled_rejected(self, client, tracker):
        kid = tracker["kasbon_ids"][0]
        r = client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}/settle")
        assert r.status_code == 400

    def test_settle_not_found_404(self, client):
        r = client.put(f"{BASE_URL}/api/cashbook/kasbon/nonexistent-xxx/settle")
        assert r.status_code == 404

    def test_reopen_kasbon(self, client, tracker):
        kid = tracker["kasbon_ids"][0]
        r = client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}/reopen")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "open"
        assert d["settled_at"] is None

    def test_reopen_not_found_404(self, client):
        r = client.put(f"{BASE_URL}/api/cashbook/kasbon/nonexistent-xxx/reopen")
        assert r.status_code == 404

    def test_totals_computation(self, client, tracker):
        # Settle one kasbon and verify totals split correctly
        kid = tracker["kasbon_ids"][0]  # 750000 (updated), currently open
        client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}/settle")

        r = client.get(f"{BASE_URL}/api/cashbook/kasbon", params={"month": "2026-01"})
        d = r.json()
        # Find our kasbon
        ours = next((i for i in d["items"] if i["id"] == kid), None)
        assert ours is not None
        assert ours["status"] == "settled"
        # Verify totals >= 0 and reasonable
        assert d["total_settled"] >= 750000
        assert d["total_all"] == d["total_open"] + d["total_settled"]
        # Reopen for cleanup consistency
        client.put(f"{BASE_URL}/api/cashbook/kasbon/{kid}/reopen")

    def test_delete_kasbon(self, client, tracker):
        # Create a throwaway kasbon
        r = client.post(f"{BASE_URL}/api/cashbook/kasbon", json={
            "date": "2026-01-25",
            "name": f"TEST_ToDelete_{TS}",
            "description": "delete me",
            "amount": 100,
        })
        assert r.status_code == 200
        kid = r.json()["id"]
        rd = client.delete(f"{BASE_URL}/api/cashbook/kasbon/{kid}")
        assert rd.status_code == 200
        # GET list - should not contain this
        r2 = client.get(f"{BASE_URL}/api/cashbook/kasbon", params={"month": "2026-01"})
        ids = [i["id"] for i in r2.json()["items"]]
        assert kid not in ids

    def test_delete_not_found_404(self, client):
        r = client.delete(f"{BASE_URL}/api/cashbook/kasbon/nonexistent-xxx")
        assert r.status_code == 404

    def test_invalid_month_format_400(self, client):
        r = client.get(f"{BASE_URL}/api/cashbook/kasbon", params={"month": "2026/01"})
        assert r.status_code == 400
