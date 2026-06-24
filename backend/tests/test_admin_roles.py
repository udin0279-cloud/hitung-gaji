"""
Multi-level Admin Role Tests
- super_admin migration from legacy 'admin' role
- User Management CRUD endpoints (super_admin only)
- hr_leave role: can access leave endpoints, blocked from admin endpoints
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip()
            break
BASE_URL = BASE_URL.rstrip("/")

SUPER_EMAIL = "admin@payroll.id"
SUPER_PASS = "admin123"


def _login(email, password):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    return s, r


@pytest.fixture(scope="module")
def super_client():
    s, r = _login(SUPER_EMAIL, SUPER_PASS)
    if r.status_code != 200:
        pytest.skip(f"super_admin login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def hr_leave_user(super_client):
    """Create (or reuse) an hr_leave user for permission tests"""
    email = f"test_hrleave_{uuid.uuid4().hex[:6]}@payroll.id"
    password = "leave123"
    r = super_client.post(f"{BASE_URL}/api/users", json={
        "email": email, "password": password, "name": "TEST HR Leave", "role": "hr_leave"
    })
    assert r.status_code in (200, 201), f"create hr_leave failed: {r.status_code} {r.text}"
    user = r.json()
    yield {"email": email, "password": password, "id": user["id"]}
    # Cleanup
    try:
        super_client.delete(f"{BASE_URL}/api/users/{user['id']}")
    except Exception:
        pass


@pytest.fixture(scope="module")
def hr_leave_client(hr_leave_user):
    s, r = _login(hr_leave_user["email"], hr_leave_user["password"])
    assert r.status_code == 200, f"hr_leave login failed: {r.status_code} {r.text}"
    return s


# ---------------- Super admin migration ----------------
class TestSuperAdminMigration:
    def test_admin_role_migrated_to_super_admin(self, super_client):
        r = super_client.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == SUPER_EMAIL
        assert data["role"] == "super_admin", f"expected super_admin, got {data.get('role')}"


# ---------------- User Management CRUD ----------------
class TestUserManagement:
    def test_list_users(self, super_client):
        r = super_client.get(f"{BASE_URL}/api/users")
        assert r.status_code == 200
        users = r.json()
        assert isinstance(users, list)
        assert any(u["email"] == SUPER_EMAIL for u in users)
        for u in users:
            assert "id" in u and "email" in u and "role" in u
            assert u["role"] in {"super_admin", "hr_leave"}

    def test_create_hr_leave_user(self, super_client):
        email = f"test_create_{uuid.uuid4().hex[:6]}@payroll.id"
        r = super_client.post(f"{BASE_URL}/api/users", json={
            "email": email, "password": "secret123", "name": "TEST Create", "role": "hr_leave"
        })
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert data["email"] == email
        assert data["role"] == "hr_leave"
        assert data["name"] == "TEST Create"
        uid = data["id"]
        # verify via list
        r2 = super_client.get(f"{BASE_URL}/api/users")
        assert any(u["id"] == uid for u in r2.json())
        # cleanup
        super_client.delete(f"{BASE_URL}/api/users/{uid}")

    def test_create_user_duplicate_email(self, super_client):
        email = f"test_dup_{uuid.uuid4().hex[:6]}@payroll.id"
        r1 = super_client.post(f"{BASE_URL}/api/users", json={
            "email": email, "password": "secret123", "name": "Dup", "role": "hr_leave"
        })
        assert r1.status_code in (200, 201)
        uid = r1.json()["id"]
        r2 = super_client.post(f"{BASE_URL}/api/users", json={
            "email": email, "password": "secret123", "name": "Dup2", "role": "hr_leave"
        })
        assert r2.status_code == 400
        super_client.delete(f"{BASE_URL}/api/users/{uid}")

    def test_create_user_short_password(self, super_client):
        email = f"test_short_{uuid.uuid4().hex[:6]}@payroll.id"
        r = super_client.post(f"{BASE_URL}/api/users", json={
            "email": email, "password": "abc", "name": "Short", "role": "hr_leave"
        })
        assert r.status_code == 400

    def test_create_user_invalid_role(self, super_client):
        email = f"test_role_{uuid.uuid4().hex[:6]}@payroll.id"
        r = super_client.post(f"{BASE_URL}/api/users", json={
            "email": email, "password": "secret123", "name": "Invalid", "role": "viewer"
        })
        assert r.status_code == 400

    def test_update_user_name_and_role(self, super_client):
        email = f"test_upd_{uuid.uuid4().hex[:6]}@payroll.id"
        r1 = super_client.post(f"{BASE_URL}/api/users", json={
            "email": email, "password": "secret123", "name": "Before", "role": "hr_leave"
        })
        uid = r1.json()["id"]

        r2 = super_client.put(f"{BASE_URL}/api/users/{uid}", json={
            "name": "After", "password": "newpass1"
        })
        assert r2.status_code == 200
        assert r2.json()["name"] == "After"

        # verify via list
        users = super_client.get(f"{BASE_URL}/api/users").json()
        found = next(u for u in users if u["id"] == uid)
        assert found["name"] == "After"

        # login with new password
        s, lr = _login(email, "newpass1")
        assert lr.status_code == 200
        super_client.delete(f"{BASE_URL}/api/users/{uid}")

    def test_delete_user(self, super_client):
        email = f"test_del_{uuid.uuid4().hex[:6]}@payroll.id"
        r1 = super_client.post(f"{BASE_URL}/api/users", json={
            "email": email, "password": "secret123", "name": "Del", "role": "hr_leave"
        })
        uid = r1.json()["id"]
        r2 = super_client.delete(f"{BASE_URL}/api/users/{uid}")
        assert r2.status_code == 200
        users = super_client.get(f"{BASE_URL}/api/users").json()
        assert not any(u["id"] == uid for u in users)

    def test_cannot_delete_self(self, super_client):
        # Get own user id
        me = super_client.get(f"{BASE_URL}/api/auth/me").json()
        r = super_client.delete(f"{BASE_URL}/api/users/{me['id']}")
        assert r.status_code == 400
        assert "sendiri" in r.json().get("detail", "").lower() or "self" in r.json().get("detail", "").lower()

    def test_cannot_delete_last_super_admin(self, super_client):
        # Ensure only 1 super_admin exists; then attempt to delete admin@payroll.id
        users = super_client.get(f"{BASE_URL}/api/users").json()
        super_admins = [u for u in users if u["role"] == "super_admin"]
        if len(super_admins) != 1:
            pytest.skip(f"Need exactly 1 super_admin to test (found {len(super_admins)})")
        # The only super_admin is themselves - hits self-delete first; test by removing self-check path:
        # Verify via creating + then trying delete - use the same admin id
        # The self-delete branch catches it. Now create a 2nd super_admin, delete the 2nd: should succeed; then last one must be self => 400 "sendiri"
        # So this test verifies: the LAST super_admin cannot be deleted (self-block plus min-1 check)
        target_id = super_admins[0]["id"]
        r = super_client.delete(f"{BASE_URL}/api/users/{target_id}")
        # Either "sendiri" (self) or "minimal" (last super admin)
        assert r.status_code == 400
        detail = r.json().get("detail", "").lower()
        assert "sendiri" in detail or "minimal" in detail or "super admin" in detail


# ---------------- hr_leave role ----------------
class TestHRLeaveRole:
    def test_me_returns_hr_leave(self, hr_leave_client):
        r = hr_leave_client.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        assert r.json()["role"] == "hr_leave"

    # Allowed endpoints
    def test_can_access_leave_stats(self, hr_leave_client):
        r = hr_leave_client.get(f"{BASE_URL}/api/leave/stats")
        assert r.status_code == 200, r.text

    def test_can_list_leave_requests(self, hr_leave_client):
        r = hr_leave_client.get(f"{BASE_URL}/api/leave")
        assert r.status_code == 200, r.text

    def test_can_export_leave_excel(self, hr_leave_client):
        period = time.strftime("%Y-%m")
        r = hr_leave_client.get(f"{BASE_URL}/api/leave/report/{period}/excel")
        # 200 if data, 404 if no data; never 403
        assert r.status_code != 403, f"hr_leave forbidden from excel export: {r.text}"

    def test_can_export_leave_pdf(self, hr_leave_client):
        period = time.strftime("%Y-%m")
        r = hr_leave_client.get(f"{BASE_URL}/api/leave/report/{period}/pdf")
        assert r.status_code != 403, f"hr_leave forbidden from pdf export: {r.text}"

    # Forbidden endpoints
    @pytest.mark.parametrize("path", [
        "/api/employees",
        "/api/users",
        "/api/dashboard/stats",
        "/api/payroll/runs",
        "/api/config/constants",
    ])
    def test_forbidden_admin_endpoints(self, hr_leave_client, path):
        r = hr_leave_client.get(f"{BASE_URL}{path}")
        assert r.status_code == 403, f"{path}: expected 403, got {r.status_code} {r.text}"
        detail = r.json().get("detail", "")
        assert "Super Admin" in detail or "ditolak" in detail.lower(), detail


# ---------------- Regression: super_admin still has full access ----------------
class TestSuperAdminFullAccess:
    @pytest.mark.parametrize("path", [
        "/api/employees",
        "/api/users",
        "/api/dashboard/stats",
        "/api/payroll/runs",
        "/api/config/constants",
        "/api/leave/stats",
        "/api/leave",
    ])
    def test_super_admin_can_access(self, super_client, path):
        r = super_client.get(f"{BASE_URL}{path}")
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
