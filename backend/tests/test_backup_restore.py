"""Backend tests for database backup & restore endpoints."""
import io
import json
import pytest
import requests
from conftest import BASE_URL


BACKUP_COLLECTIONS = [
    "users", "employees", "payslips", "payroll_runs", "thr_slips",
    "thr_runs", "attendance_imports", "app_config", "email_logs",
    "portal_reset_tokens",
]


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def portal_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/portal/login", json={"email": "udin0279@gmail.com", "nik": "211"})
    if r.status_code != 200:
        pytest.skip(f"Portal login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def exported_snapshot(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/admin/export-database")
    assert r.status_code == 200, r.text
    # Content-Disposition attachment header
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd.lower()
    assert "filename" in cd.lower()
    # Media type JSON
    assert "application/json" in r.headers.get("content-type", "")
    data = r.json()
    assert "_meta" in data
    return data


# ---------- Export tests ----------

class TestExport:
    def test_export_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/export-database")
        assert r.status_code == 401

    def test_export_rejects_portal_token(self, portal_session):
        r = portal_session.get(f"{BASE_URL}/api/admin/export-database")
        assert r.status_code == 401

    def test_export_returns_all_collections(self, exported_snapshot):
        meta = exported_snapshot["_meta"]
        assert "exported_at" in meta
        assert meta.get("exported_by") == "admin@payroll.id"
        assert "version" in meta
        for col in BACKUP_COLLECTIONS:
            assert col in exported_snapshot, f"Missing collection {col}"
            assert isinstance(exported_snapshot[col], list), f"{col} is not list"


# ---------- Import tests ----------

class TestImportAuth:
    def test_import_requires_auth(self):
        files = {"file": ("b.json", b'{"_meta":{}}', "application/json")}
        r = requests.post(f"{BASE_URL}/api/admin/import-database", files=files)
        assert r.status_code == 401

    def test_import_rejects_portal_token(self, portal_session):
        files = {"file": ("b.json", b'{"_meta":{}}', "application/json")}
        r = portal_session.post(f"{BASE_URL}/api/admin/import-database", files=files)
        assert r.status_code == 401


class TestImportValidation:
    def test_import_invalid_json(self, admin_session):
        files = {"file": ("bad.json", b"not-json{{", "application/json")}
        r = admin_session.post(f"{BASE_URL}/api/admin/import-database", files=files)
        assert r.status_code == 400
        assert "JSON" in r.json().get("detail", "")

    def test_import_missing_meta(self, admin_session):
        body = json.dumps({"users": []}).encode("utf-8")
        files = {"file": ("nometa.json", body, "application/json")}
        r = admin_session.post(f"{BASE_URL}/api/admin/import-database", files=files)
        assert r.status_code == 400
        assert "Format backup tidak dikenali" in r.json().get("detail", "")

    def test_import_invalid_mode_captures_error(self, admin_session, exported_snapshot):
        body = json.dumps(exported_snapshot).encode("utf-8")
        files = {"file": ("snap.json", body, "application/json")}
        r = admin_session.post(
            f"{BASE_URL}/api/admin/import-database?mode=invalid", files=files
        )
        # Per spec: handled per-collection but at least one error captured
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "invalid"
        assert isinstance(data["errors"], list)
        assert len(data["errors"]) >= 1


# ---------- Merge round-trip ----------

class TestImportMerge:
    def test_merge_roundtrip_counts(self, admin_session, exported_snapshot):
        body = json.dumps(exported_snapshot).encode("utf-8")
        files = {"file": ("snap.json", body, "application/json")}
        r = admin_session.post(
            f"{BASE_URL}/api/admin/import-database?mode=merge", files=files
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "merge"
        assert data["errors"] == []
        for col in BACKUP_COLLECTIONS:
            expected = len(exported_snapshot[col])
            assert data["restored"][col] == expected, f"{col} restored count mismatch"


# ---------- Config reload after import ----------

class TestConfigReloadOnImport:
    def test_config_reapplied_after_import(self, admin_session, exported_snapshot):
        # Get current config
        r = admin_session.get(f"{BASE_URL}/api/config/constants")
        assert r.status_code == 200
        original_workdays = r.json()["standard_workdays"]

        # Modify exported snapshot's app_config standard_workdays to a sentinel value
        sentinel = 27 if original_workdays != 27 else 23
        snapshot = json.loads(json.dumps(exported_snapshot))  # deep copy
        # find and modify app_config record
        app_cfg = snapshot.get("app_config") or []
        modified = False
        for cfg in app_cfg:
            if "standard_workdays" in cfg:
                cfg["standard_workdays"] = sentinel
                modified = True
        if not modified and app_cfg:
            app_cfg[0]["standard_workdays"] = sentinel
            modified = True

        if not modified:
            pytest.skip("No app_config record present to mutate")

        body = json.dumps(snapshot).encode("utf-8")
        files = {"file": ("modified.json", body, "application/json")}
        r = admin_session.post(
            f"{BASE_URL}/api/admin/import-database?mode=merge", files=files
        )
        assert r.status_code == 200, r.text

        # Verify in-memory CONFIG was reapplied
        r = admin_session.get(f"{BASE_URL}/api/config/constants")
        assert r.status_code == 200
        assert r.json()["standard_workdays"] == sentinel

        # Restore by re-importing original snapshot
        body = json.dumps(exported_snapshot).encode("utf-8")
        files = {"file": ("orig.json", body, "application/json")}
        r = admin_session.post(
            f"{BASE_URL}/api/admin/import-database?mode=merge", files=files
        )
        assert r.status_code == 200

        r = admin_session.get(f"{BASE_URL}/api/config/constants")
        assert r.json()["standard_workdays"] == original_workdays


# ---------- Replace mode (non-destructive: replace with same data) ----------

class TestImportReplace:
    def test_replace_with_same_snapshot(self, admin_session, exported_snapshot):
        body = json.dumps(exported_snapshot).encode("utf-8")
        files = {"file": ("snap.json", body, "application/json")}
        r = admin_session.post(
            f"{BASE_URL}/api/admin/import-database?mode=replace", files=files
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "replace"
        assert data["errors"] == []
        for col in BACKUP_COLLECTIONS:
            expected = len(exported_snapshot[col])
            assert data["restored"][col] == expected

        # Re-export and verify counts still match (idempotent)
        r2 = admin_session.get(f"{BASE_URL}/api/admin/export-database")
        assert r2.status_code == 200
        s2 = r2.json()
        for col in BACKUP_COLLECTIONS:
            assert len(s2[col]) == len(exported_snapshot[col]), f"{col} count changed after replace"
