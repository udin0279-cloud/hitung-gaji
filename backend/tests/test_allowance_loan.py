"""Tests for new allowance components (tj_jabatan/transport/lainnya) and loan tracking."""
import os
import pytest
import requests
import uuid
from pathlib import Path

SITI_ID = "57679bfb-35f0-4b6b-9317-c9929bc016ff"

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break


@pytest.fixture(scope="module")
def base_url_module():
    return BASE_URL


@pytest.fixture(scope="module")
def auth_client_module():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@payroll.id", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def restore_siti(auth_client_module, base_url_module):
    r = auth_client_module.get(f"{base_url_module}/api/employees/{SITI_ID}")
    snapshot = r.json() if r.status_code == 200 else None
    yield snapshot
    if snapshot:
        payload = {k: v for k, v in snapshot.items() if k not in ("id", "created_at")}
        auth_client_module.put(f"{base_url_module}/api/employees/{SITI_ID}", json=payload)


def _new_emp_payload(**overrides):
    p = {
        "nik": f"TEST_{uuid.uuid4().hex[:8]}",
        "name": "TEST_Allowance User",
        "email": None,
        "phone": None,
        "position": "Staff",
        "department": "QA",
        "join_date": "2024-01-01",
        "basic_salary": 15000000,
        "fixed_allowance": 3000000,
        "tunjangan_jabatan": 500000,
        "tunjangan_transport": 300000,
        "tunjangan_lainnya": 100000,
        "loan_installment": 0,
        "loan_tenor_total": 0,
        "loan_tenor_paid": 0,
        "ptkp_status": "TK/0",
        "npwp": None,
        "has_npwp": True,
        "bpjs_kesehatan": True,
        "bpjs_ketenagakerjaan": True,
        "bank_name": None,
        "bank_account": None,
        "active": True,
    }
    p.update(overrides)
    return p


# --- Model schema tests ---
class TestEmployeeSchema:
    def test_create_with_new_fields(self, auth_client_module, base_url_module):
        r = auth_client_module.post(f"{base_url_module}/api/employees", json=_new_emp_payload(
            loan_installment=500000, loan_tenor_total=12, loan_tenor_paid=0,
        ))
        assert r.status_code == 200, r.text
        emp = r.json()
        assert emp["tunjangan_jabatan"] == 500000
        assert emp["tunjangan_transport"] == 300000
        assert emp["tunjangan_lainnya"] == 100000
        assert emp["loan_installment"] == 500000
        assert emp["loan_tenor_total"] == 12
        assert emp["loan_tenor_paid"] == 0
        # cleanup
        auth_client_module.delete(f"{base_url_module}/api/employees/{emp['id']}")

    def test_update_new_fields(self, auth_client_module, base_url_module):
        r = auth_client_module.post(f"{base_url_module}/api/employees", json=_new_emp_payload())
        emp = r.json()
        eid = emp["id"]
        upd = _new_emp_payload(nik=emp["nik"], tunjangan_jabatan=999000, loan_installment=250000, loan_tenor_total=6, loan_tenor_paid=2)
        r2 = auth_client_module.put(f"{base_url_module}/api/employees/{eid}", json=upd)
        assert r2.status_code == 200
        updated = r2.json()
        assert updated["tunjangan_jabatan"] == 999000
        assert updated["loan_installment"] == 250000
        assert updated["loan_tenor_total"] == 6
        assert updated["loan_tenor_paid"] == 2
        # cleanup
        auth_client_module.delete(f"{base_url_module}/api/employees/{eid}")

    def test_backwards_compat_no_new_fields(self, auth_client_module, base_url_module):
        # payload w/o new fields defaults to 0 (Pydantic default)
        payload = {
            "nik": f"TEST_{uuid.uuid4().hex[:8]}",
            "name": "TEST_Legacy",
            "position": "Staff",
            "department": "QA",
            "join_date": "2024-01-01",
            "basic_salary": 10000000,
            "fixed_allowance": 1000000,
        }
        r = auth_client_module.post(f"{base_url_module}/api/employees", json=payload)
        assert r.status_code == 200
        e = r.json()
        assert e.get("tunjangan_jabatan", 0) == 0
        assert e.get("loan_installment", 0) == 0
        # preview should still work
        pr = auth_client_module.post(f"{base_url_module}/api/payroll/preview", json={"period": "2099-12", "attendance": {}})
        assert pr.status_code == 200
        auth_client_module.delete(f"{base_url_module}/api/employees/{e['id']}")


# --- Payroll calc tests ---
class TestPayrollCalculation:
    def test_gross_and_bpjs_base_excludes_transport(self, auth_client_module, base_url_module, restore_siti):
        r = auth_client_module.post(f"{base_url_module}/api/payroll/preview", json={"period": "2099-01", "attendance": {}})
        assert r.status_code == 200
        siti = next((s for s in r.json()["slips"] if s["employee_id"] == SITI_ID), None)
        assert siti is not None, "Siti Aminah not found"
        e = siti["earnings"]
        # gross = 15M basic + 3M fixed + 500k + 300k + 100k = 18.9M
        assert e["gross"] == 18900000.0, f"gross={e['gross']}"
        assert e["tunjangan_jabatan"] == 500000
        assert e["tunjangan_transport"] == 300000
        assert e["tunjangan_lainnya"] == 100000
        d = siti["deductions"]
        # BPJS Kes base = min(15M+3M+500k=18.5M, 12M cap) = 12M -> 1% = 120,000
        assert d["bpjs_kesehatan_employee"] == 120000.0, f"bpjs={d['bpjs_kesehatan_employee']}"
        # JHT = 18.5M * 2% = 370,000
        assert d["jht_employee"] == 370000.0, f"jht={d['jht_employee']}"

    def test_loan_deduction_active(self, auth_client_module, base_url_module):
        payload = _new_emp_payload(loan_installment=500000, loan_tenor_total=12, loan_tenor_paid=0)
        r = auth_client_module.post(f"{base_url_module}/api/employees", json=payload)
        emp = r.json()
        pr = auth_client_module.post(f"{base_url_module}/api/payroll/preview", json={"period": "2099-02", "attendance": {}})
        slip = next(s for s in pr.json()["slips"] if s["employee_id"] == emp["id"])
        assert slip["deductions"]["loan"] == 500000
        li = slip["loan_info"]
        assert li["active"] is True
        assert li["tenor_paid_after"] == 1
        assert li["remaining_after"] == 11
        auth_client_module.delete(f"{base_url_module}/api/employees/{emp['id']}")

    def test_loan_auto_stop(self, auth_client_module, base_url_module):
        payload = _new_emp_payload(loan_installment=500000, loan_tenor_total=3, loan_tenor_paid=3)
        r = auth_client_module.post(f"{base_url_module}/api/employees", json=payload)
        emp = r.json()
        pr = auth_client_module.post(f"{base_url_module}/api/payroll/preview", json={"period": "2099-03", "attendance": {}})
        slip = next(s for s in pr.json()["slips"] if s["employee_id"] == emp["id"])
        assert slip["deductions"]["loan"] == 0
        assert slip["loan_info"]["active"] is False
        auth_client_module.delete(f"{base_url_module}/api/employees/{emp['id']}")


# --- Loan lifecycle tests ---
class TestLoanLifecycle:
    def test_loan_auto_increment_on_run(self, auth_client_module, base_url_module):
        payload = _new_emp_payload(loan_installment=500000, loan_tenor_total=12, loan_tenor_paid=0)
        r = auth_client_module.post(f"{base_url_module}/api/employees", json=payload)
        emp = r.json()
        eid = emp["id"]
        period = "2099-04"
        try:
            rr = auth_client_module.post(f"{base_url_module}/api/payroll/run", json={"period": period, "attendance": {}})
            assert rr.status_code == 200
            got = auth_client_module.get(f"{base_url_module}/api/employees/{eid}").json()
            assert got["loan_tenor_paid"] == 1, f"expected 1, got {got['loan_tenor_paid']}"
        finally:
            auth_client_module.delete(f"{base_url_module}/api/payroll/runs/{period}")
            auth_client_module.delete(f"{base_url_module}/api/employees/{eid}")

    def test_loan_rollback_on_delete(self, auth_client_module, base_url_module):
        payload = _new_emp_payload(loan_installment=500000, loan_tenor_total=12, loan_tenor_paid=0)
        r = auth_client_module.post(f"{base_url_module}/api/employees", json=payload)
        emp = r.json()
        eid = emp["id"]
        period = "2099-05"
        try:
            auth_client_module.post(f"{base_url_module}/api/payroll/run", json={"period": period, "attendance": {}})
            after_run = auth_client_module.get(f"{base_url_module}/api/employees/{eid}").json()["loan_tenor_paid"]
            assert after_run == 1
            auth_client_module.delete(f"{base_url_module}/api/payroll/runs/{period}")
            after_del = auth_client_module.get(f"{base_url_module}/api/employees/{eid}").json()["loan_tenor_paid"]
            assert after_del == 0, f"expected rollback to 0, got {after_del}"
        finally:
            auth_client_module.delete(f"{base_url_module}/api/payroll/runs/{period}")
            auth_client_module.delete(f"{base_url_module}/api/employees/{eid}")

    def test_loan_rollback_on_rerun(self, auth_client_module, base_url_module):
        payload = _new_emp_payload(loan_installment=500000, loan_tenor_total=12, loan_tenor_paid=0)
        r = auth_client_module.post(f"{base_url_module}/api/employees", json=payload)
        emp = r.json()
        eid = emp["id"]
        period = "2099-06"
        try:
            auth_client_module.post(f"{base_url_module}/api/payroll/run", json={"period": period, "attendance": {}})
            first = auth_client_module.get(f"{base_url_module}/api/employees/{eid}").json()["loan_tenor_paid"]
            assert first == 1
            # rerun same period
            auth_client_module.post(f"{base_url_module}/api/payroll/run", json={"period": period, "attendance": {}})
            second = auth_client_module.get(f"{base_url_module}/api/employees/{eid}").json()["loan_tenor_paid"]
            assert second == 1, f"expected still 1 (rollback+re-inc), got {second}"
        finally:
            auth_client_module.delete(f"{base_url_module}/api/payroll/runs/{period}")
            auth_client_module.delete(f"{base_url_module}/api/employees/{eid}")


# --- PDF test ---
class TestPayslipPDF:
    def test_pdf_valid_bytes(self, auth_client_module, base_url_module):
        payload = _new_emp_payload(loan_installment=500000, loan_tenor_total=12, loan_tenor_paid=0)
        r = auth_client_module.post(f"{base_url_module}/api/employees", json=payload)
        emp = r.json()
        eid = emp["id"]
        period = "2099-07"
        try:
            auth_client_module.post(f"{base_url_module}/api/payroll/run", json={"period": period, "attendance": {}})
            slips = auth_client_module.get(f"{base_url_module}/api/payroll/runs/{period}/slips").json()
            slip = next(s for s in slips if s["employee_id"] == eid)
            pdf_r = auth_client_module.get(f"{base_url_module}/api/payroll/payslip/{slip['id']}/pdf")
            assert pdf_r.status_code == 200
            assert pdf_r.content[:4] == b"%PDF"
        finally:
            auth_client_module.delete(f"{base_url_module}/api/payroll/runs/{period}")
            auth_client_module.delete(f"{base_url_module}/api/employees/{eid}")
