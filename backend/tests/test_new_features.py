"""Backend tests for new features: editable config, THR, email (mock), bank export."""
import pytest
import requests
from conftest import BASE_URL


# ----- Editable Config -----
class TestConfigEditable:
    @pytest.fixture(scope="class")
    def s(self):
        sess = requests.Session()
        sess.headers.update({"Content-Type": "application/json"})
        r = sess.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
        assert r.status_code == 200
        return sess

    def test_get_constants_full(self, s):
        r = s.get(f"{BASE_URL}/api/config/constants")
        assert r.status_code == 200
        d = r.json()
        for k in ["biaya_jabatan_rate", "standard_workdays", "overtime_multiplier",
                  "ptkp_table", "pph21_brackets", "bpjs", "biaya_jabatan_max_year"]:
            assert k in d, f"missing key: {k}"
        assert isinstance(d["pph21_brackets"], list)
        assert len(d["pph21_brackets"]) >= 1
        assert "limit" in d["pph21_brackets"][0]
        assert "rate" in d["pph21_brackets"][0]

    def test_put_constants_partial_persist(self, s, request):
        # Save originals
        orig = s.get(f"{BASE_URL}/api/config/constants").json()
        orig_workdays = orig["standard_workdays"]
        orig_overtime = orig["overtime_multiplier"]

        def teardown():
            s.put(f"{BASE_URL}/api/config/constants", json={
                "standard_workdays": orig_workdays,
                "overtime_multiplier": orig_overtime,
            })
        request.addfinalizer(teardown)

        r = s.put(f"{BASE_URL}/api/config/constants", json={
            "standard_workdays": 22,
            "overtime_multiplier": 1.5,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 2

        # GET round-trip
        r2 = s.get(f"{BASE_URL}/api/config/constants")
        assert r2.status_code == 200
        d = r2.json()
        assert d["standard_workdays"] == 22
        assert d["overtime_multiplier"] == 1.5

        # Update only one (partial)
        r3 = s.put(f"{BASE_URL}/api/config/constants", json={"standard_workdays": 21})
        assert r3.status_code == 200
        assert r3.json()["updated"] == 1
        d2 = s.get(f"{BASE_URL}/api/config/constants").json()
        assert d2["standard_workdays"] == 21
        assert d2["overtime_multiplier"] == 1.5  # untouched


# ----- THR -----
class TestTHR:
    @pytest.fixture(scope="class")
    def s(self):
        sess = requests.Session()
        sess.headers.update({"Content-Type": "application/json"})
        sess.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
        return sess

    def test_thr_preview_structure(self, s):
        r = s.post(f"{BASE_URL}/api/payroll/thr/preview", json={"period": "2026-04"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "totals" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) >= 1
        item = data["items"][0]
        for k in ["months_of_service", "monthly_base", "thr_gross", "pph21_thr", "thr_net", "formula"]:
            assert k in item, f"missing item key: {k}"
        # totals
        for k in ["gross", "net", "pph21", "count"]:
            assert k in data["totals"]
        # cross-check totals
        s_gross = sum(i["thr_gross"] for i in data["items"])
        assert abs(s_gross - data["totals"]["gross"]) < 1

    def test_thr_run_and_list(self, s, request):
        period = "2026-04"

        def teardown():
            # cleanup
            try:
                s.delete(f"{BASE_URL}/api/payroll/thr/{period}")
            except Exception:
                pass
        request.addfinalizer(teardown)

        r = s.post(f"{BASE_URL}/api/payroll/thr/run", json={"period": period})
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["period"] == period
        assert run["employee_count"] >= 1
        assert "total_gross" in run and "total_net" in run

        # list
        runs = s.get(f"{BASE_URL}/api/payroll/thr/runs").json()
        assert any(x["period"] == period for x in runs)

        # slips
        slips = s.get(f"{BASE_URL}/api/payroll/thr/{period}/slips")
        assert slips.status_code == 200
        slist = slips.json()
        assert len(slist) >= 1
        sl = slist[0]
        for k in ["thr_gross", "thr_net", "pph21_thr", "monthly_base", "formula", "nik", "name"]:
            assert k in sl

    def test_thr_slips_not_found(self, s):
        r = s.get(f"{BASE_URL}/api/payroll/thr/1999-01/slips")
        assert r.status_code == 404

    def test_thr_invalid_period(self, s):
        r = s.post(f"{BASE_URL}/api/payroll/thr/preview", json={"period": "bad"})
        assert r.status_code == 400


# ----- Bank Export -----
class TestBankExport:
    @pytest.fixture(scope="class")
    def s(self):
        sess = requests.Session()
        sess.headers.update({"Content-Type": "application/json"})
        sess.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
        return sess

    @pytest.fixture(scope="class")
    def period(self, s):
        runs = s.get(f"{BASE_URL}/api/payroll/runs").json()
        if not runs:
            pytest.skip("No payroll runs to export")
        return runs[0]["period"]

    def test_generic_csv_headers(self, s, period):
        r = s.get(f"{BASE_URL}/api/payroll/runs/{period}/bank-export", params={"format": "generic"})
        assert r.status_code == 200, r.text
        text = r.text
        first_line = text.split("\n")[0]
        for h in ["NIK", "Nama", "Bank", "No Rekening", "Jumlah", "Keterangan"]:
            assert h in first_line, f"missing header {h}: {first_line}"
        assert r.headers.get("content-type", "").startswith("text/csv")

    def test_bca_format(self, s, period):
        r = s.get(f"{BASE_URL}/api/payroll/runs/{period}/bank-export", params={"format": "bca"})
        assert r.status_code == 200
        first = r.text.split("\n")[0]
        assert "ACCOUNT_NUMBER" in first
        assert "|" in first  # pipe separated
        assert r.headers.get("content-type", "").startswith("text/plain")

    def test_mandiri_format(self, s, period):
        r = s.get(f"{BASE_URL}/api/payroll/runs/{period}/bank-export", params={"format": "mandiri"})
        assert r.status_code == 200
        first = r.text.split("\n")[0]
        assert "Nama Penerima" in first and "Bank Penerima" in first
        assert "," in first

    def test_bni_format(self, s, period):
        r = s.get(f"{BASE_URL}/api/payroll/runs/{period}/bank-export", params={"format": "bni"})
        assert r.status_code == 200
        first = r.text.split("\n")[0]
        assert "NomorRekening" in first and "NamaPenerima" in first

    def test_bri_format(self, s, period):
        r = s.get(f"{BASE_URL}/api/payroll/runs/{period}/bank-export", params={"format": "bri"})
        assert r.status_code == 200
        first = r.text.split("\n")[0]
        assert ";" in first  # semicolon separated for BRI
        assert "NoRekening" in first

    def test_invalid_format(self, s, period):
        r = s.get(f"{BASE_URL}/api/payroll/runs/{period}/bank-export", params={"format": "invalid"})
        assert r.status_code == 400

    def test_unknown_period(self, s):
        r = s.get(f"{BASE_URL}/api/payroll/runs/1999-01/bank-export", params={"format": "generic"})
        assert r.status_code == 404


# ----- Email Payslip (Mock mode) -----
class TestEmail:
    @pytest.fixture(scope="class")
    def s(self):
        sess = requests.Session()
        sess.headers.update({"Content-Type": "application/json"})
        sess.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
        return sess

    @pytest.fixture(scope="class")
    def period(self, s):
        runs = s.get(f"{BASE_URL}/api/payroll/runs").json()
        if not runs:
            pytest.skip("No payroll runs")
        return runs[0]["period"]

    def test_email_all_mock_mode(self, s, period):
        r = s.post(f"{BASE_URL}/api/payroll/runs/{period}/email-all")
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ["sent", "mocked", "failed", "skipped_no_email", "details"]:
            assert k in data
        # RESEND_API_KEY is empty -> no real sends
        assert data["sent"] == 0
        # at least one mocked OR skipped depending on data
        assert data["mocked"] + data["skipped_no_email"] >= 1
        assert isinstance(data["details"], list)

    def test_email_single_with_email(self, s, period):
        slips = s.get(f"{BASE_URL}/api/payroll/runs/{period}/slips").json()
        # Find slip whose employee has email
        target = None
        for sl in slips:
            emp = s.get(f"{BASE_URL}/api/employees/{sl['employee_id']}").json()
            if emp.get("email"):
                target = (sl, emp)
                break
        if not target:
            pytest.skip("No employee with email")
        sl, emp = target
        r = s.post(f"{BASE_URL}/api/payroll/payslip/{sl['id']}/email")
        assert r.status_code == 200, r.text
        # mocked since API key empty
        assert r.json().get("status") == "mocked"

    def test_email_single_no_email_returns_400(self, s, period):
        slips = s.get(f"{BASE_URL}/api/payroll/runs/{period}/slips").json()
        target = None
        for sl in slips:
            emp = s.get(f"{BASE_URL}/api/employees/{sl['employee_id']}").json()
            if not emp.get("email"):
                target = sl
                break
        if not target:
            pytest.skip("All employees have email")
        r = s.post(f"{BASE_URL}/api/payroll/payslip/{target['id']}/email")
        assert r.status_code == 400

    def test_email_unknown_slip(self, s):
        r = s.post(f"{BASE_URL}/api/payroll/payslip/nonexistent-id/email")
        assert r.status_code == 404
