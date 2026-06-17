"""Backend tests for Magic Link / Forgot NIK feature (iteration 4).
Covers /api/portal/forgot and /api/portal/magic-login endpoints.
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


def _extract_token(magic_link: str) -> str:
    assert "token=" in magic_link
    return magic_link.split("token=", 1)[1]


# ---------- /api/portal/forgot ----------
class TestPortalForgot:
    def test_forgot_existing_email_returns_mocked_link(self):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{BASE_URL}/api/portal/forgot", json={"email": PORTAL_EMAIL})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["status"] == "mocked"
        assert data["magic_link_preview"], "magic_link_preview should be present in mock mode"
        assert "/portal/magic-login?token=" in data["magic_link_preview"]

    def test_forgot_unknown_email_no_enumeration(self):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{BASE_URL}/api/portal/forgot", json={"email": "no-such-user@example.com"})
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        # Must NOT expose status or magic link for unknown email
        assert "status" not in data or data.get("status") is None
        assert not data.get("magic_link_preview"), \
            "magic_link_preview must NOT be returned for unknown email (prevents enumeration)"

    def test_forgot_case_insensitive_email(self):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{BASE_URL}/api/portal/forgot", json={"email": PORTAL_EMAIL.upper()})
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        # Should also produce a mocked link (employee record lookup is lowercased)
        assert data.get("status") == "mocked"
        assert data.get("magic_link_preview")

    def test_forgot_invalid_email_format_returns_422(self):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{BASE_URL}/api/portal/forgot", json={"email": "not-an-email"})
        assert r.status_code == 422


# ---------- /api/portal/magic-login ----------
class TestMagicLogin:
    def _get_token(self) -> str:
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{BASE_URL}/api/portal/forgot", json={"email": PORTAL_EMAIL})
        assert r.status_code == 200
        link = r.json()["magic_link_preview"]
        return _extract_token(link)

    def test_magic_login_success_sets_cookie_and_returns_employee(self):
        token = self._get_token()
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/portal/magic-login", params={"token": token})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["nik"] == PORTAL_NIK
        assert data["email"].lower() == PORTAL_EMAIL
        assert data["name"]  # Syarifuddin
        assert "position" in data and "department" in data
        # Cookie must be set
        assert "portal_token" in s.cookies, f"portal_token cookie missing; cookies={s.cookies.get_dict()}"
        # /portal/me works with the cookie
        me = s.get(f"{BASE_URL}/api/portal/me")
        assert me.status_code == 200
        assert me.json()["nik"] == PORTAL_NIK

    def test_magic_login_token_is_single_use(self):
        token = self._get_token()
        s1 = requests.Session()
        r1 = s1.post(f"{BASE_URL}/api/portal/magic-login", params={"token": token})
        assert r1.status_code == 200
        # Reusing the same token must fail
        s2 = requests.Session()
        r2 = s2.post(f"{BASE_URL}/api/portal/magic-login", params={"token": token})
        assert r2.status_code == 400, f"Expected 400 on token reuse, got {r2.status_code}: {r2.text}"
        body = r2.json()
        detail = body.get("detail", "")
        assert "tidak valid" in detail.lower() or "sudah dipakai" in detail.lower(), \
            f"Unexpected error detail: {detail}"

    def test_magic_login_invalid_token_returns_400(self):
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/portal/magic-login", params={"token": "totally-invalid-random-token-xyz123"})
        assert r.status_code == 400


# ---------- Regression: existing portal + admin endpoints still work ----------
class TestRegression:
    def test_portal_login_still_works(self):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{BASE_URL}/api/portal/login", json={"email": PORTAL_EMAIL, "nik": PORTAL_NIK})
        assert r.status_code == 200, r.text
        assert "portal_token" in s.cookies
        me = s.get(f"{BASE_URL}/api/portal/me")
        assert me.status_code == 200

    def test_employees_requires_admin_token(self):
        anon = requests.Session()
        r = anon.get(f"{BASE_URL}/api/employees")
        assert r.status_code == 401

    def test_employees_works_for_admin(self):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        if r.status_code != 200:
            pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
        emp = s.get(f"{BASE_URL}/api/employees")
        assert emp.status_code == 200
        assert isinstance(emp.json(), list)

    def test_portal_token_from_magic_link_cannot_access_admin(self):
        # Login via magic link, then try /api/employees
        s_fresh = requests.Session()
        s_fresh.headers.update({"Content-Type": "application/json"})
        r = s_fresh.post(f"{BASE_URL}/api/portal/forgot", json={"email": PORTAL_EMAIL})
        token = _extract_token(r.json()["magic_link_preview"])
        s = requests.Session()
        r2 = s.post(f"{BASE_URL}/api/portal/magic-login", params={"token": token})
        assert r2.status_code == 200
        r3 = s.get(f"{BASE_URL}/api/employees")
        assert r3.status_code == 401
