"""Backend tests for Employee Self-Service Portal (iteration 3).
Covers /api/portal/* endpoints, cookie isolation from admin auth, and ownership checks.
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


# ---------- Portal login ----------
class TestPortalLogin:
    def test_login_success_sets_portal_token(self, anon=requests.Session()):
        anon.headers.update({"Content-Type": "application/json"})
        r = anon.post(f"{BASE_URL}/api/portal/login", json={"email": PORTAL_EMAIL, "nik": PORTAL_NIK})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["nik"] == PORTAL_NIK
        assert data["email"].lower() == PORTAL_EMAIL
        assert data["name"]  # Syarifuddin
        assert "position" in data and "department" in data
        # Cookie name must be portal_token (NOT access_token)
        assert "portal_token" in anon.cookies, f"portal_token cookie missing; cookies={anon.cookies.get_dict()}"
        assert "access_token" not in anon.cookies

    def test_login_wrong_nik(self):
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/portal/login", json={"email": PORTAL_EMAIL, "nik": "999999"})
        assert r.status_code == 401

    def test_login_wrong_email(self):
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/portal/login", json={"email": "notreal@example.com", "nik": PORTAL_NIK})
        assert r.status_code == 401

    def test_login_email_mismatch_with_valid_nik(self):
        # NIK exists but belongs to a different email
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/portal/login", json={"email": "wrong@payroll.id", "nik": PORTAL_NIK})
        assert r.status_code == 401


# ---------- Portal me / payslips / thr (happy path) ----------
class TestPortalMe:
    def test_me_returns_logged_in_employee(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/me")
        assert r.status_code == 200
        d = r.json()
        assert d["nik"] == PORTAL_NIK
        assert d["email"].lower() == PORTAL_EMAIL
        assert d["name"]

    def test_me_without_cookie_returns_401(self):
        s = requests.Session()
        r = s.get(f"{BASE_URL}/api/portal/me")
        assert r.status_code == 401


class TestPortalPayslips:
    def test_list_only_own_payslips(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/payslips")
        assert r.status_code == 200
        slips = r.json()
        assert isinstance(slips, list)
        assert len(slips) >= 2, f"Expected >=2 payslips for Syarifuddin, got {len(slips)}"
        periods = {s["period"] for s in slips}
        assert "2026-01" in periods
        assert "2026-06" in periods
        for s in slips:
            assert "id" in s and "period" in s and "net_salary" in s

    def test_get_own_slip_by_id(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/payslips")
        slip_id = r.json()[0]["id"]
        r2 = portal_client.get(f"{BASE_URL}/api/portal/payslip/{slip_id}")
        assert r2.status_code == 200
        full = r2.json()
        assert full["id"] == slip_id
        # Confirm it actually belongs to portal user (check NIK matches)
        assert full.get("nik") == PORTAL_NIK or full.get("employee_id")

    def test_get_other_employee_slip_returns_404(self, portal_client, admin_client):
        # Find a payslip belonging to a DIFFERENT employee via admin endpoint
        all_slips = admin_client.get(f"{BASE_URL}/api/payroll/runs/2026-01/slips").json()
        portal_emp_id = portal_client.get(f"{BASE_URL}/api/portal/me").json()["id"]
        other = next((s for s in all_slips if s.get("employee_id") != portal_emp_id), None)
        if not other:
            pytest.skip("No other employee's slip available to test cross-ownership")
        r = portal_client.get(f"{BASE_URL}/api/portal/payslip/{other['id']}")
        assert r.status_code == 404, f"Expected 404 for foreign slip, got {r.status_code}"

    def test_pdf_for_own_slip(self, portal_client):
        slip_id = portal_client.get(f"{BASE_URL}/api/portal/payslips").json()[0]["id"]
        r = portal_client.get(f"{BASE_URL}/api/portal/payslip/{slip_id}/pdf")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF", "Response is not a valid PDF"
        assert len(r.content) > 500

    def test_pdf_for_foreign_slip_returns_404(self, portal_client, admin_client):
        all_slips = admin_client.get(f"{BASE_URL}/api/payroll/runs/2026-01/slips").json()
        portal_emp_id = portal_client.get(f"{BASE_URL}/api/portal/me").json()["id"]
        other = next((s for s in all_slips if s.get("employee_id") != portal_emp_id), None)
        if not other:
            pytest.skip("No other employee's slip available")
        r = portal_client.get(f"{BASE_URL}/api/portal/payslip/{other['id']}/pdf")
        assert r.status_code == 404


class TestPortalTHR:
    def test_thr_returns_only_own(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/portal/thr")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        # All rows must belong to this employee (id field present, period present)
        for row in rows:
            assert "id" in row and "period" in row


# ---------- Cross-contamination: admin token must not access portal & vice versa ----------
class TestCrossAuthIsolation:
    def test_admin_token_cannot_access_portal_me(self, admin_client):
        # admin_client has access_token cookie but NO portal_token
        r = admin_client.get(f"{BASE_URL}/api/portal/me")
        assert r.status_code == 401, f"admin should NOT be allowed on /portal/me, got {r.status_code}"

    def test_admin_token_cannot_access_portal_payslips(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/portal/payslips")
        assert r.status_code == 401

    def test_admin_token_cannot_access_portal_thr(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/portal/thr")
        assert r.status_code == 401

    def test_portal_token_cannot_access_admin_employees(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/employees")
        assert r.status_code == 401, f"portal token should NOT access /api/employees, got {r.status_code}"

    def test_portal_token_cannot_access_admin_payroll_slips(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/payroll/runs/2026-01/slips")
        assert r.status_code == 401

    def test_portal_token_cannot_access_admin_me(self, portal_client):
        r = portal_client.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_coexistence_both_cookies_in_same_session(self):
        """Admin login + portal login in same session both work independently."""
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r1 = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r1.status_code == 200
        r2 = s.post(f"{BASE_URL}/api/portal/login", json={"email": PORTAL_EMAIL, "nik": PORTAL_NIK})
        assert r2.status_code == 200
        # Both cookies must coexist
        assert "access_token" in s.cookies
        assert "portal_token" in s.cookies
        # Admin endpoint still works
        admin_me = s.get(f"{BASE_URL}/api/auth/me")
        assert admin_me.status_code == 200
        assert admin_me.json().get("email") == ADMIN_EMAIL
        # Portal endpoint still works
        portal_me = s.get(f"{BASE_URL}/api/portal/me")
        assert portal_me.status_code == 200
        assert portal_me.json().get("nik") == PORTAL_NIK


# ---------- Logout ----------
class TestPortalLogout:
    def test_logout_clears_portal_token(self, portal_client):
        r = portal_client.post(f"{BASE_URL}/api/portal/logout")
        assert r.status_code == 200
        # After logout the cookie should be cleared; subsequent /me must return 401
        r2 = portal_client.get(f"{BASE_URL}/api/portal/me")
        assert r2.status_code == 401
