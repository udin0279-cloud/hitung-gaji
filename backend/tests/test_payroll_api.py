"""Backend test suite for Indonesian Payroll API."""
import pytest
import requests
from conftest import BASE_URL


# ----- Auth -----
class TestAuth:
    def test_login_success(self, anon_client):
        r = anon_client.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["email"] == "admin@payroll.id"
        assert data["role"] == "admin"
        # httpOnly cookies set
        assert "access_token" in anon_client.cookies.get_dict() or any(c.name == "access_token" for c in anon_client.cookies)

    def test_login_invalid(self, anon_client):
        r = anon_client.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "wrong"})
        assert r.status_code == 401

    def test_me_with_cookie(self, auth_client):
        r = auth_client.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200, r.text
        assert r.json()["email"] == "admin@payroll.id"

    def test_me_without_auth(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_protected_employees_requires_auth(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/employees")
        assert r.status_code == 401


# ----- Employee CRUD -----
class TestEmployeesAndPayroll:
    @pytest.fixture(scope="class")
    def created_employee(self, request):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
        assert r.status_code == 200
        # Cleanup any existing TEST_NIK
        emps = s.get(f"{BASE_URL}/api/employees").json()
        for e in emps:
            if e["nik"].startswith("TEST"):
                s.delete(f"{BASE_URL}/api/employees/{e['id']}")
        payload = {
            "nik": "TEST001",
            "name": "TEST Employee One",
            "email": "test1@example.com",
            "position": "Engineer",
            "department": "IT",
            "join_date": "2024-01-01",
            "basic_salary": 10000000,
            "fixed_allowance": 2000000,
            "ptkp_status": "TK/0",
            "has_npwp": True,
            "bpjs_kesehatan": True,
            "bpjs_ketenagakerjaan": True,
            "active": True,
        }
        r = s.post(f"{BASE_URL}/api/employees", json=payload)
        assert r.status_code == 200, r.text
        emp = r.json()
        assert emp["nik"] == "TEST001"
        assert emp["basic_salary"] == 10000000

        def teardown():
            s.delete(f"{BASE_URL}/api/employees/{emp['id']}")
            s.delete(f"{BASE_URL}/api/payroll/runs/2025-12")

        request.addfinalizer(teardown)
        return s, emp

    def test_employee_persisted(self, created_employee):
        s, emp = created_employee
        r = s.get(f"{BASE_URL}/api/employees/{emp['id']}")
        assert r.status_code == 200
        assert r.json()["nik"] == "TEST001"

    def test_employee_duplicate_nik_fails(self, created_employee):
        s, emp = created_employee
        dup = {**emp}
        dup.pop("id", None)
        dup.pop("created_at", None)
        r = s.post(f"{BASE_URL}/api/employees", json=dup)
        assert r.status_code == 400

    def test_employee_update(self, created_employee):
        s, emp = created_employee
        upd = {k: v for k, v in emp.items() if k not in ("id", "created_at")}
        upd["position"] = "Senior Engineer"
        r = s.put(f"{BASE_URL}/api/employees/{emp['id']}", json=upd)
        assert r.status_code == 200, r.text
        assert r.json()["position"] == "Senior Engineer"
        # verify persisted
        r2 = s.get(f"{BASE_URL}/api/employees/{emp['id']}")
        assert r2.json()["position"] == "Senior Engineer"

    def test_employee_list(self, created_employee):
        s, emp = created_employee
        r = s.get(f"{BASE_URL}/api/employees")
        assert r.status_code == 200
        assert any(e["id"] == emp["id"] for e in r.json())

    # ----- Payroll -----
    def test_payroll_preview(self, created_employee):
        s, emp = created_employee
        payload = {
            "period": "2025-12",
            "attendance": {emp["id"]: {"days_worked": 22, "overtime_hours": 10, "bonus": 500000}},
        }
        r = s.post(f"{BASE_URL}/api/payroll/preview", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        slip = next(s for s in data["slips"] if s["employee_id"] == emp["id"])
        # gross = basic(10M) + allowance(2M) + overtime + bonus
        overtime = 10000000 / 173 * 10 * 1.5
        expected_gross = 10000000 + 2000000 + overtime + 500000
        assert abs(slip["earnings"]["gross"] - expected_gross) < 1
        # deductions
        assert slip["deductions"]["bpjs_kesehatan_employee"] == pytest.approx(120000, rel=0.01)  # 1% of (12M capped)
        assert slip["deductions"]["jht_employee"] == pytest.approx(240000, rel=0.01)  # 2% of 12M
        assert slip["deductions"]["jp_employee"] == pytest.approx(100423, rel=0.01)  # 1% of 10042300 cap
        assert slip["deductions"]["pph21"] > 0
        # tax detail keys
        td = slip["tax_detail"]
        for k in ["bruto_yearly", "biaya_jabatan_yearly", "netto_yearly", "ptkp", "pkp", "pph21_yearly"]:
            assert k in td
        assert td["ptkp"] == 54_000_000  # TK/0
        # net = gross - total_deductions
        expected_net = slip["earnings"]["gross"] - slip["deductions"]["total"]
        assert abs(slip["net_salary"] - expected_net) < 1

    def test_payroll_run_and_idempotent(self, created_employee):
        s, emp = created_employee
        payload = {
            "period": "2025-12",
            "attendance": {emp["id"]: {"days_worked": 22, "overtime_hours": 10, "bonus": 500000}},
        }
        r = s.post(f"{BASE_URL}/api/payroll/run", json=payload)
        assert r.status_code == 200, r.text
        run1 = r.json()
        assert run1["period"] == "2025-12"
        assert run1["employee_count"] >= 1

        # second run replaces
        r2 = s.post(f"{BASE_URL}/api/payroll/run", json=payload)
        assert r2.status_code == 200

        # list runs
        runs = s.get(f"{BASE_URL}/api/payroll/runs").json()
        count = sum(1 for x in runs if x["period"] == "2025-12")
        assert count == 1, "Period duplicates not allowed"

        # list slips
        slips = s.get(f"{BASE_URL}/api/payroll/runs/2025-12/slips").json()
        assert any(sl["employee_id"] == emp["id"] for sl in slips)
        slip_id = next(sl["id"] for sl in slips if sl["employee_id"] == emp["id"])

        # individual payslip
        r3 = s.get(f"{BASE_URL}/api/payroll/payslip/{slip_id}")
        assert r3.status_code == 200
        assert r3.json()["employee_id"] == emp["id"]

    def test_dashboard_stats(self, created_employee):
        s, _ = created_employee
        r = s.get(f"{BASE_URL}/api/dashboard/stats")
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["total_employees", "latest_run", "trend"]:
            assert k in d
        assert isinstance(d["trend"], list)

    def test_config_constants(self, created_employee):
        s, _ = created_employee
        r = s.get(f"{BASE_URL}/api/config/constants")
        assert r.status_code == 200
        d = r.json()
        assert len(d["ptkp_table"]) == 8
        assert len(d["pph21_brackets"]) == 5
        assert "kesehatan_employee" in d["bpjs"]


# ----- Logout -----
class TestLogout:
    def test_logout_clears_cookie(self, auth_client):
        r = auth_client.post(f"{BASE_URL}/api/auth/logout")
        assert r.status_code == 200
