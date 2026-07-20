"""RBAC / Menu-permission tests for admin_privileged role.

Covers:
- Super admin bypass
- Middleware 403 for unauthorized menus
- 200 for granted menus
- User CRUD by admin_privileged with 'kelola_user' perm
- Legacy hr_leave -> admin_privileged migration
"""
import os
import uuid
import requests
import pytest

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        # try reading from frontend/.env
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        return line.split("=", 1)[1].strip().rstrip("/")
        except FileNotFoundError:
            pass
    return (v or "").rstrip("/")


BASE_URL = _load_backend_url()
assert BASE_URL, "REACT_APP_BACKEND_URL not configured"
API = f"{BASE_URL}/api"

SUPER_EMAIL = "admin@payroll.id"
SUPER_PASS = "admin123"

LEGACY_EMAIL = "hrcuti@payroll.id"
LEGACY_PASS = "cuti123"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    return s, r.json()


@pytest.fixture(scope="module")
def super_client():
    s, me = _login(SUPER_EMAIL, SUPER_PASS)
    return s


@pytest.fixture(scope="module")
def created_privileged_user(super_client):
    # Create a fresh admin_privileged with only penjualan + inventory
    unique = uuid.uuid4().hex[:8]
    email = f"TEST_priv_{unique}@payroll.id"
    password = "priv12345"
    payload = {
        "email": email,
        "password": password,
        "name": f"TEST Priv {unique}",
        "role": "admin_privileged",
        "permissions": ["penjualan", "inventory"],
    }
    r = super_client.post(f"{API}/users", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "admin_privileged"
    assert set(body["permissions"]) == {"penjualan", "inventory"}
    yield {"email": email, "password": password, "id": body["id"]}
    # cleanup
    try:
        super_client.delete(f"{API}/users/{body['id']}", timeout=10)
    except Exception:
        pass


# ---------- Super admin sanity ----------

def test_super_admin_login_and_me(super_client):
    r = super_client.get(f"{API}/auth/me", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == SUPER_EMAIL
    assert body["role"] == "super_admin"


def test_super_admin_can_access_all_menus(super_client):
    for path in [
        "/employees", "/payroll/runs", "/leave", "/cashbook/accounts",
        "/users", "/categories", "/config/constants", "/sales", "/inventory/materials",
        "/reports/profit-loss/2026-01",
    ]:
        r = super_client.get(f"{API}{path}", timeout=15)
        assert r.status_code == 200, f"Super admin blocked on {path}: {r.status_code} {r.text[:200]}"


# ---------- Middleware 403 for restricted menus ----------

def test_privileged_user_login(created_privileged_user):
    s, me = _login(created_privileged_user["email"], created_privileged_user["password"])
    assert me["role"] == "admin_privileged"
    assert set(me["permissions"]) == {"penjualan", "inventory"}


def test_privileged_allowed_endpoints(created_privileged_user):
    s, _ = _login(created_privileged_user["email"], created_privileged_user["password"])
    r1 = s.get(f"{API}/sales", timeout=15)
    assert r1.status_code == 200, r1.text[:200]
    r2 = s.get(f"{API}/inventory/materials", timeout=15)
    assert r2.status_code == 200, r2.text[:200]


@pytest.mark.parametrize("path,menu", [
    ("/employees", "karyawan"),
    ("/payroll/runs", "payroll"),
    ("/leave", "izin_cuti"),
    ("/cashbook/accounts", "kas_operasional"),
    ("/users", "kelola_user"),
    ("/reports/profit-loss/2026-01", "laba_rugi"),
    ("/categories", "master_kategori"),
    ("/config/constants", "konfigurasi"),
])
def test_privileged_denied_endpoints(created_privileged_user, path, menu):
    s, _ = _login(created_privileged_user["email"], created_privileged_user["password"])
    r = s.get(f"{API}{path}", timeout=15)
    assert r.status_code == 403, f"Expected 403 for {path}, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    detail = body.get("detail", "")
    assert "Akses ditolak" in detail
    assert menu in detail


# ---------- Permission update flow ----------

def test_permission_update_grants_access(super_client, created_privileged_user):
    uid = created_privileged_user["id"]
    new_perms = ["penjualan", "inventory", "kelola_user", "konfigurasi"]
    r = super_client.put(
        f"{API}/users/{uid}",
        json={"permissions": new_perms},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["permissions"]) == set(new_perms)

    # Re-login and verify /users + /config/constants now 200
    s, me = _login(created_privileged_user["email"], created_privileged_user["password"])
    assert set(me["permissions"]) == set(new_perms)
    r1 = s.get(f"{API}/users", timeout=15)
    assert r1.status_code == 200, r1.text[:200]
    r2 = s.get(f"{API}/config/constants", timeout=15)
    assert r2.status_code == 200, r2.text[:200]

    # Still denied for other menus
    r3 = s.get(f"{API}/employees", timeout=15)
    assert r3.status_code == 403


def test_privileged_with_kelola_user_can_crud_users(super_client, created_privileged_user):
    """After being granted kelola_user, privileged user can create + delete another user."""
    s, _ = _login(created_privileged_user["email"], created_privileged_user["password"])
    unique = uuid.uuid4().hex[:8]
    email = f"TEST_child_{unique}@payroll.id"
    r = s.post(f"{API}/users", json={
        "email": email,
        "password": "childpw123",
        "name": "TEST Child",
        "role": "admin_privileged",
        "permissions": ["penjualan"],
    }, timeout=15)
    assert r.status_code == 200, r.text
    child_id = r.json()["id"]

    # verify GET list contains the new user
    r_list = s.get(f"{API}/users", timeout=15)
    assert r_list.status_code == 200
    assert any(u["id"] == child_id for u in r_list.json())

    # delete child user
    r_del = s.delete(f"{API}/users/{child_id}", timeout=15)
    assert r_del.status_code in (200, 204)

    # verify deletion persisted
    r_list2 = s.get(f"{API}/users", timeout=15)
    assert r_list2.status_code == 200
    assert all(u["id"] != child_id for u in r_list2.json())


def test_cannot_delete_last_super_admin(super_client):
    # Attempt to delete super admin — should fail
    r_list = super_client.get(f"{API}/users", timeout=15)
    supers = [u for u in r_list.json() if u["role"] == "super_admin"]
    if len(supers) == 1:
        r = super_client.delete(f"{API}/users/{supers[0]['id']}", timeout=15)
        assert r.status_code >= 400, "Should not allow deleting last super_admin"


# ---------- Legacy hr_leave migration ----------

def test_legacy_hr_leave_migrated():
    s, me = _login(LEGACY_EMAIL, LEGACY_PASS)
    assert me["role"] == "admin_privileged"
    assert "izin_cuti" in (me.get("permissions") or [])

    r_leave = s.get(f"{API}/leave", timeout=15)
    assert r_leave.status_code == 200, r_leave.text[:200]

    r_emp = s.get(f"{API}/employees", timeout=15)
    assert r_emp.status_code == 403


# ---------- Sanity: invalid role rejected ----------

def test_create_user_invalid_role(super_client):
    unique = uuid.uuid4().hex[:8]
    r = super_client.post(f"{API}/users", json={
        "email": f"TEST_inv_{unique}@payroll.id",
        "password": "abcdef",
        "name": "Invalid role",
        "role": "hacker_role",
        "permissions": [],
    }, timeout=15)
    assert r.status_code == 400


def test_create_user_invalid_menu_key_sanitized(super_client):
    unique = uuid.uuid4().hex[:8]
    r = super_client.post(f"{API}/users", json={
        "email": f"TEST_san_{unique}@payroll.id",
        "password": "abcdef",
        "name": "Sanitize",
        "role": "admin_privileged",
        "permissions": ["penjualan", "not_a_menu", "inventory"],
    }, timeout=15)
    assert r.status_code == 200
    # not_a_menu should be filtered
    assert set(r.json()["permissions"]) == {"penjualan", "inventory"}
    # cleanup
    super_client.delete(f"{API}/users/{r.json()['id']}", timeout=10)
