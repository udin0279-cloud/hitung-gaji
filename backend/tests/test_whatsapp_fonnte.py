"""Tests for Fonnte WhatsApp integration (mock mode) + phone field + CSV import."""
import os
import io
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://hitung-gaji.preview.emergentagent.com").rstrip("/")


# ---------------- helpers ----------------
def _admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return s


def _portal_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/portal/login", json={"email": "udin0279@gmail.com", "nik": "211"})
    if r.status_code != 200:
        pytest.skip(f"portal login failed: {r.status_code} {r.text}")
    return s


# ---------------- 1. WhatsApp Status ----------------
class TestWhatsAppStatus:
    def test_status_unauth(self):
        r = requests.get(f"{BASE_URL}/api/admin/whatsapp/status")
        assert r.status_code == 401

    def test_status_admin(self):
        s = _admin_session()
        r = s.get(f"{BASE_URL}/api/admin/whatsapp/status")
        assert r.status_code == 200
        data = r.json()
        assert data["configured"] is False
        assert data["provider"] == "Fonnte"
        assert data["mode"] == "mock"

    def test_status_portal_blocked(self):
        ps = _portal_session()
        r = ps.get(f"{BASE_URL}/api/admin/whatsapp/status")
        assert r.status_code == 401


# ---------------- 2. Employee phone field ----------------
class TestEmployeePhone:
    def test_create_and_update_phone(self):
        s = _admin_session()
        nik = f"TEST{uuid.uuid4().hex[:6].upper()}"
        payload = {
            "nik": nik,
            "name": "TEST_Phone Emp",
            "email": f"test_{nik}@example.com",
            "phone": "081234567890",
            "position": "QA",
            "department": "Test",
            "join_date": "2024-01-01",
            "basic_salary": 5000000,
            "fixed_allowance": 0,
            "ptkp_status": "TK/0",
            "has_npwp": True,
            "bpjs_kesehatan": True,
            "bpjs_ketenagakerjaan": True,
        }
        r = s.post(f"{BASE_URL}/api/employees", json=payload)
        assert r.status_code in (200, 201), r.text
        emp = r.json()
        assert emp.get("phone") == "081234567890"
        emp_id = emp["id"]

        # GET to verify persistence
        r = s.get(f"{BASE_URL}/api/employees/{emp_id}")
        assert r.status_code == 200
        assert r.json().get("phone") == "081234567890"

        # PUT update phone
        upd = dict(payload)
        upd["phone"] = "6281298765432"
        r = s.put(f"{BASE_URL}/api/employees/{emp_id}", json=upd)
        assert r.status_code == 200, r.text
        assert r.json().get("phone") == "6281298765432"

        # cleanup
        s.delete(f"{BASE_URL}/api/employees/{emp_id}")

    def test_template_has_phone_column(self):
        s = _admin_session()
        r = s.get(f"{BASE_URL}/api/employees-template.csv")
        assert r.status_code == 200
        header_line = r.text.splitlines()[0]
        assert "phone" in header_line.lower()

    def test_csv_import_with_phone(self):
        s = _admin_session()
        nik = f"TIMP{uuid.uuid4().hex[:6].upper()}"
        csv_data = (
            "nik,name,email,phone,position,department,join_date,basic_salary,fixed_allowance,"
            "ptkp_status,npwp,has_npwp,bpjs_kesehatan,bpjs_ketenagakerjaan,bank_name,bank_account\n"
            f"{nik},TEST_CSV Emp,csv_{nik}@x.id,082311112222,Dev,IT,2024-02-01,7000000,0,TK/0,,true,true,true,BCA,123\n"
        )
        files = {"file": ("emp.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
        r = s.post(f"{BASE_URL}/api/employees-import", files=files)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result.get("created", 0) >= 1, f"Expected at least one created. Got: {result}"

        # verify phone stored
        listing = s.get(f"{BASE_URL}/api/employees").json()
        match = [e for e in listing if e["nik"] == nik]
        assert match, "imported employee not found"
        assert match[0]["phone"] == "082311112222"

        # cleanup
        s.delete(f"{BASE_URL}/api/employees/{match[0]['id']}")


# ---------------- 3. Single WhatsApp send ----------------
class TestWhatsAppSingle:
    def _get_syarifuddin_slip(self, s):
        """Return Syarifuddin's payslip for 2026-01 if exists."""
        emps = s.get(f"{BASE_URL}/api/employees").json()
        syaf = next((e for e in emps if e.get("nik") == "211"), None)
        assert syaf is not None, "Syarifuddin (NIK 211) not found"
        # ensure phone is set
        if not syaf.get("phone"):
            payload = {**syaf, "phone": "081234567890"}
            payload.pop("_id", None)
            s.put(f"{BASE_URL}/api/employees/{syaf['id']}", json=payload)
        slips = s.get(f"{BASE_URL}/api/payroll/runs/2026-01/slips").json()
        match = [p for p in slips if p.get("employee_id") == syaf["id"]] if isinstance(slips, list) else []
        return syaf, match[0] if match else None

    def test_unauth_send(self):
        r = requests.post(f"{BASE_URL}/api/payroll/payslip/fake-id/whatsapp")
        assert r.status_code == 401

    def test_portal_blocked(self):
        ps = _portal_session()
        r = ps.post(f"{BASE_URL}/api/payroll/payslip/fake-id/whatsapp")
        assert r.status_code == 401

    def test_send_mock_with_phone(self):
        s = _admin_session()
        syaf, slip = self._get_syarifuddin_slip(s)
        if not slip:
            pytest.skip("No 2026-01 payslip for Syarifuddin")
        r = s.post(f"{BASE_URL}/api/payroll/payslip/{slip['id']}/whatsapp")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "mocked"
        assert data["reason"] == "no_token"
        # normalized to 62...
        assert data["phone"].startswith("62"), f"phone not normalized: {data['phone']}"

    def test_send_no_phone_returns_400(self):
        s = _admin_session()
        # Find any employee WITHOUT phone in 2026-01 payslips
        emps = {e["id"]: e for e in s.get(f"{BASE_URL}/api/employees").json()}
        run = s.get(f"{BASE_URL}/api/payroll/runs/2026-01/slips").json()
        slips = run if isinstance(run, list) else run.get("payslips", [])
        target_slip = None
        for sl in slips if isinstance(slips, list) else []:
            emp = emps.get(sl.get("employee_id"))
            if emp and not emp.get("phone"):
                target_slip = sl
                break
        if not target_slip:
            pytest.skip("No employee without phone in 2026-01")
        r = s.post(f"{BASE_URL}/api/payroll/payslip/{target_slip['id']}/whatsapp")
        assert r.status_code == 400


# ---------------- 4. Bulk WhatsApp ----------------
class TestWhatsAppBulk:
    def test_unauth(self):
        r = requests.post(f"{BASE_URL}/api/payroll/runs/2026-01/whatsapp-all")
        assert r.status_code == 401

    def test_portal_blocked(self):
        ps = _portal_session()
        r = ps.post(f"{BASE_URL}/api/payroll/runs/2026-01/whatsapp-all")
        assert r.status_code == 401

    def test_bulk_mock(self):
        s = _admin_session()
        # ensure Syarifuddin has phone
        emps = s.get(f"{BASE_URL}/api/employees").json()
        syaf = next((e for e in emps if e.get("nik") == "211"), None)
        if syaf and not syaf.get("phone"):
            payload = {**syaf, "phone": "081234567890"}
            payload.pop("_id", None)
            s.put(f"{BASE_URL}/api/employees/{syaf['id']}", json=payload)

        r = s.post(f"{BASE_URL}/api/payroll/runs/2026-01/whatsapp-all")
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("sent", "mocked", "failed", "skipped_no_phone", "details"):
            assert k in d
        # At least Syarifuddin should be mocked, others skipped
        assert d["mocked"] >= 1, f"Expected at least 1 mocked. Got: {d}"
        # details list
        assert isinstance(d["details"], list)
        assert len(d["details"]) >= 1

    def test_bulk_unknown_period_404(self):
        s = _admin_session()
        r = s.post(f"{BASE_URL}/api/payroll/runs/1999-12/whatsapp-all")
        assert r.status_code == 404


# ---------------- 5. Regression smoke ----------------
class TestRegressionSmoke:
    def test_login_works(self):
        s = _admin_session()
        r = s.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200

    def test_employees_list(self):
        s = _admin_session()
        r = s.get(f"{BASE_URL}/api/employees")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_payroll_run_2026_01(self):
        s = _admin_session()
        r = s.get(f"{BASE_URL}/api/payroll/runs/2026-01/slips")
        assert r.status_code == 200

    def test_portal_login_works(self):
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/portal/login", json={"email": "udin0279@gmail.com", "nik": "211"})
        assert r.status_code == 200

    def test_email_endpoint_still_exists(self):
        # Only smoke: that route is mounted & returns sensible code (not 404)
        s = _admin_session()
        r = s.post(f"{BASE_URL}/api/payroll/payslip/nonexistent-id/email")
        # 404 expected for missing slip — not 405 (method) or 500
        assert r.status_code in (400, 404), r.status_code
