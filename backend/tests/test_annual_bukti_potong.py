"""Backend tests for Annual Tax Summary + Bukti Potong 1721-A1 (iteration 5).
Covers:
  - GET /api/portal/annual/{year}                  (employee self-service)
  - GET /api/portal/bukti-potong/{year}/pdf        (employee self-service PDF)
  - GET /api/payroll/bukti-potong/{eid}/{year}/pdf (admin PDF for any employee)
  - Auth/ownership scoping
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

PORTAL_EMAIL = "udin0279@gmail.com"
PORTAL_NIK = "211"
ADMIN_EMAIL = "admin@payroll.id"
ADMIN_PASSWORD = "admin123"


@pytest.fixture
def portal_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/portal/login", json={"email": PORTAL_EMAIL, "nik": PORTAL_NIK})
    if r.status_code != 200:
        pytest.skip(f"Portal login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture
def admin_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture
def syarif_employee_id(admin_client):
    """Resolve Syarifuddin's employee_id (NIK 211) via admin API."""
    r = admin_client.get(f"{BASE_URL}/api/employees")
    assert r.status_code == 200, r.text
    for emp in r.json():
        if emp.get("nik") == PORTAL_NIK:
            return emp["id"]
    pytest.skip("Syarifuddin (NIK 211) not present in employees list")


# ---------- Annual summary endpoint ----------
class TestPortalAnnual:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/portal/annual/2026")
        assert r.status_code == 401

    def test_2026_returns_2_months_for_syarif(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/annual/2026")
        assert r.status_code == 200, r.text
        data = r.json()

        # Top-level shape
        assert data["year"] == 2026
        assert isinstance(data["months"], list)
        assert "totals" in data
        assert "months_count" in data

        # Spec expectations from problem statement
        assert data["months_count"] == 2, f"Expected 2 months, got {data['months_count']}: {data['months']}"
        periods = [m["period"] for m in data["months"]]
        assert "2026-01" in periods
        assert "2026-06" in periods

        # totals.gross = 800000
        assert data["totals"]["gross"] == 800000, f"Expected gross 800000, got {data['totals']['gross']}"

        # Totals must contain all required keys
        for k in ("gross", "basic", "allowance", "overtime", "bonus",
                  "pph21", "bpjs_employee", "net", "thr_gross", "thr_pph21"):
            assert k in data["totals"], f"Missing totals key: {k}"

    def test_year_with_no_data_returns_empty_summary(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/annual/1999")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["months_count"] == 0
        assert data["months"] == []
        assert data["totals"]["gross"] == 0


# ---------- Employee self-service Bukti Potong PDF ----------
class TestPortalBuktiPotongPDF:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/portal/bukti-potong/2026/pdf")
        assert r.status_code == 401

    def test_valid_year_returns_pdf(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/bukti-potong/2026/pdf")
        assert r.status_code == 200, r.text[:200]
        assert r.content.startswith(b"%PDF"), "Response is not a PDF"
        assert len(r.content) >= 1024, f"PDF suspiciously small: {len(r.content)} bytes"
        ct = r.headers.get("content-type", "")
        assert "pdf" in ct.lower(), f"Unexpected content-type: {ct}"

    def test_year_without_data_returns_404(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/bukti-potong/1999/pdf")
        assert r.status_code == 404


# ---------- Admin Bukti Potong PDF for any employee ----------
class TestAdminBuktiPotongPDF:
    def test_requires_admin_auth(self, syarif_employee_id):
        # Anonymous request -> 401
        r = requests.get(f"{BASE_URL}/api/payroll/bukti-potong/{syarif_employee_id}/2026/pdf")
        assert r.status_code == 401

    def test_portal_cookie_cannot_access_admin_endpoint(self, portal_client, syarif_employee_id):
        # Employee portal token is NOT an admin token; admin endpoint must reject.
        r = portal_client.get(f"{BASE_URL}/api/payroll/bukti-potong/{syarif_employee_id}/2026/pdf")
        assert r.status_code == 401, f"Expected 401 for portal cookie on admin endpoint, got {r.status_code}"

    def test_admin_can_download_any_employee_pdf(self, admin_client, syarif_employee_id):
        r = admin_client.get(f"{BASE_URL}/api/payroll/bukti-potong/{syarif_employee_id}/2026/pdf")
        assert r.status_code == 200, r.text[:200]
        assert r.content.startswith(b"%PDF")
        assert len(r.content) >= 1024

    def test_admin_unknown_employee_returns_404(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/payroll/bukti-potong/non-existent-id/2026/pdf")
        assert r.status_code == 404

    def test_admin_year_no_data_returns_404(self, admin_client, syarif_employee_id):
        r = admin_client.get(f"{BASE_URL}/api/payroll/bukti-potong/{syarif_employee_id}/1999/pdf")
        assert r.status_code == 404


# ---------- Ownership: portal endpoints are scoped to logged-in employee ----------
class TestPortalOwnershipScope:
    def test_portal_endpoint_has_no_employee_id_param(self, portal_client):
        """The portal annual/bukti-potong endpoints take only {year} — they cannot be tricked
        into returning another employee's data. This is a structural test."""
        # Calling with a bogus extra path should 404, not return foreign data
        r = portal_client.get(f"{BASE_URL}/api/portal/annual/2026/some-other-eid")
        assert r.status_code in (404, 405)


# ---------- Regression: existing portal endpoints still work ----------
class TestPortalRegression:
    def test_portal_me(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/me")
        assert r.status_code == 200
        assert r.json()["nik"] == PORTAL_NIK

    def test_portal_payslips(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/payslips")
        assert r.status_code == 200
        slips = r.json()
        assert isinstance(slips, list)
        # Syarifuddin should have at least 2 payslips per spec
        periods = [s["period"] for s in slips]
        assert any(p.startswith("2026-") for p in periods)

    def test_portal_thr(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/thr")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_me(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200

    def test_admin_employees_list(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/employees")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
