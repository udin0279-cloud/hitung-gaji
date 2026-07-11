from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import re
import logging
import uuid
import asyncio
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
import csv
import io
import base64

# ---------------- DB ----------------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# ---------------- App ----------------
app = FastAPI(title="Payroll Indonesia API")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("payroll")

JWT_ALGORITHM = "HS256"


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


# ---------------- Auth helpers ----------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        "type": "access",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_portal_token(employee_id: str, email: str) -> str:
    payload = {
        "sub": employee_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "type": "portal",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


async def get_current_employee(request: Request) -> Dict[str, Any]:
    token = request.cookies.get("portal_token")
    if not token:
        raise HTTPException(status_code=401, detail="Portal: not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "portal":
            raise HTTPException(status_code=401, detail="Invalid token type")
        emp = await db.employees.find_one({"id": payload["sub"]}, {"_id": 0})
        if not emp:
            raise HTTPException(status_code=401, detail="Karyawan tidak ditemukan")
        return emp
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sesi berakhir")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token tidak valid")


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=False, samesite="lax", max_age=43200, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=False, samesite="lax", max_age=604800, path="/")


async def get_current_user(request: Request) -> Dict[str, Any]:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user.pop("_id", None)
        user.pop("password_hash", None)
        # Backwards compatibility: legacy "admin" role acts as super_admin
        if user.get("role") == "admin":
            user["role"] = "super_admin"
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# Role-based access helpers
ROLE_SUPER_ADMIN = "super_admin"
ROLE_HR_LEAVE = "hr_leave"
VALID_ROLES = {ROLE_SUPER_ADMIN, ROLE_HR_LEAVE}


async def require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Akses ditolak: Super Admin only")
    return user


async def require_leave_access(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in {ROLE_SUPER_ADMIN, ROLE_HR_LEAVE}:
        raise HTTPException(status_code=403, detail="Akses ditolak")
    return user


# ---------------- Models ----------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str


# Employee
class EmployeeIn(BaseModel):
    nik: str  # employee internal id (NIP)
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None  # WhatsApp number (Indonesian local 08... or 62...)
    position: str
    department: str
    join_date: str  # ISO date
    basic_salary: float
    fixed_allowance: float = 0  # tunjangan tetap (dianggap sebagai tunjangan taxable / legacy)
    tunjangan_jabatan: float = 0  # taxable, masuk base BPJS & PPh21
    tunjangan_transport: float = 0  # non-taxable benefit
    tunjangan_lainnya: float = 0  # non-taxable benefit
    insentif_individu: float = 0  # taxable untuk PPh21, TIDAK masuk base BPJS
    tunjangan_tidak_tetap: float = 0  # taxable PPh21, TIDAK masuk base BPJS
    tunjangan_wfh: float = 0  # non-taxable benefit
    insentif_kolektif: float = 0  # taxable PPh21, TIDAK masuk base BPJS
    insentif_lain: float = 0  # taxable PPh21, TIDAK masuk base BPJS
    potongan_terlambat: float = 0  # dipotong dari gross
    potongan_pulang_cepat: float = 0  # dipotong dari gross
    loan_installment: float = 0  # angsuran pinjaman bulanan
    loan_total_amount: float = 0  # total nilai pinjaman
    loan_tenor_total: int = 0  # total bulan tenor pinjaman
    loan_tenor_paid: int = 0  # sudah dibayar berapa bulan
    ptkp_status: str = "TK/0"  # TK/0, K/0, K/1, K/2, K/3
    npwp: Optional[str] = None
    has_npwp: bool = True
    bpjs_kesehatan: bool = True
    bpjs_ketenagakerjaan: bool = True
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    bank_account_holder: Optional[str] = None
    employment_status: str = "tetap"  # ojt | kontrak_6 | kontrak_12 | tetap
    status_start_date: Optional[str] = None  # ISO YYYY-MM-DD — tanggal mulai OJT/Kontrak
    status_end_date: Optional[str] = None    # ISO YYYY-MM-DD — tanggal berakhir
    active: bool = True


class EmployeeOut(EmployeeIn):
    id: str
    created_at: str


# Payroll
class PayrollRunIn(BaseModel):
    period: str  # YYYY-MM
    attendance: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    # attendance[employee_id] = {"days_worked": 22, "overtime_hours": 0, "bonus": 0, "deduction": 0}


# ---------------- Indonesian Payroll Configuration (overridable via /api/config) ----------------
CONFIG: Dict[str, Any] = {
    "ptkp_table": {
        "TK/0": 54_000_000,
        "TK/1": 58_500_000,
        "TK/2": 63_000_000,
        "TK/3": 67_500_000,
        "K/0": 58_500_000,
        "K/1": 63_000_000,
        "K/2": 67_500_000,
        "K/3": 72_000_000,
    },
    # PPh 21 brackets (UU HPP 2022) — list of [limit, rate]; last limit uses None for infinity
    "pph21_brackets": [
        [60_000_000, 0.05],
        [250_000_000, 0.15],
        [500_000_000, 0.25],
        [5_000_000_000, 0.30],
        [None, 0.35],
    ],
    "bpjs_kesehatan_employee": 0.01,
    "bpjs_kesehatan_employer": 0.04,
    "bpjs_kesehatan_max_base": 12_000_000,
    "jht_employee": 0.02,
    "jht_employer": 0.037,
    "jp_employee": 0.01,
    "jp_employer": 0.02,
    "jp_max_base": 10_042_300,
    "jkk_employer": 0.0024,
    "jkm_employer": 0.003,
    "biaya_jabatan_rate": 0.05,
    "biaya_jabatan_max_year": 6_000_000,
    "standard_workdays": 22,
    "overtime_multiplier": 1.5,
}


def _pph21_brackets_normalized():
    out = []
    for b in CONFIG["pph21_brackets"]:
        limit = b[0] if b[0] is not None else float("inf")
        out.append((float(limit), float(b[1])))
    return out


def compute_pph21_annual(pkp: float) -> float:
    if pkp <= 0:
        return 0.0
    tax = 0.0
    prev_limit = 0.0
    for limit, rate in _pph21_brackets_normalized():
        taxable_in_bracket = min(pkp, limit) - prev_limit
        if taxable_in_bracket <= 0:
            break
        tax += taxable_in_bracket * rate
        prev_limit = limit
        if pkp <= limit:
            break
    return tax


def calculate_payslip(employee: Dict[str, Any], attendance: Dict[str, float]) -> Dict[str, Any]:
    """
    Returns full payslip breakdown for one employee for one month.
    """
    basic = float(employee.get("basic_salary", 0))
    fixed_allowance = float(employee.get("fixed_allowance", 0))
    tj_jabatan = float(employee.get("tunjangan_jabatan", 0))
    tj_transport = float(employee.get("tunjangan_transport", 0))
    tj_lainnya = float(employee.get("tunjangan_lainnya", 0))
    insentif_individu = float(employee.get("insentif_individu", 0))
    tj_tidak_tetap = float(employee.get("tunjangan_tidak_tetap", 0))
    tj_wfh = float(employee.get("tunjangan_wfh", 0))
    insentif_kolektif = float(employee.get("insentif_kolektif", 0))
    insentif_lain = float(employee.get("insentif_lain", 0))
    potongan_terlambat = float(employee.get("potongan_terlambat", 0))
    potongan_pulang_cepat = float(employee.get("potongan_pulang_cepat", 0))
    loan_installment = float(employee.get("loan_installment", 0))
    loan_tenor_total = int(employee.get("loan_tenor_total", 0) or 0)
    loan_tenor_paid = int(employee.get("loan_tenor_paid", 0) or 0)
    overtime_hours = float(attendance.get("overtime_hours", 0) or 0)
    bonus = float(attendance.get("bonus", 0) or 0)
    other_deduction = float(attendance.get("deduction", 0) or 0)
    standard_days = float(CONFIG["standard_workdays"]) or 22.0
    days_worked = float(attendance.get("days_worked", standard_days) or standard_days)

    # Overtime rate: 1/173 * basic salary per hour (Indonesian standard)
    overtime_rate_per_hour = basic / 173 if basic else 0
    overtime_pay = overtime_rate_per_hour * overtime_hours * float(CONFIG["overtime_multiplier"])

    # Pro-rate basic if days_worked < standard
    prorate_factor = min(days_worked / standard_days, 1.0) if standard_days > 0 else 1.0
    basic_paid = basic * prorate_factor

    # Taxable = tunjangan yang masuk BPJS & PPh21 base
    taxable_allowance = fixed_allowance + tj_jabatan
    # Non-taxable = benefit (transport, lain-lain, WFH) — masuk gross tapi tidak masuk base
    non_taxable_allowance = tj_transport + tj_lainnya + tj_wfh
    # Taxable-only allowance (PPh21 kena, BPJS tidak) — insentif + tunjangan tidak tetap
    taxable_only_earnings = insentif_individu + insentif_kolektif + insentif_lain + tj_tidak_tetap

    gross = basic_paid + taxable_allowance + non_taxable_allowance + taxable_only_earnings + overtime_pay + bonus

    # BPJS Kesehatan (capped) — base = basic + taxable allowance only
    bpjs_kes_base = min(basic_paid + taxable_allowance, CONFIG["bpjs_kesehatan_max_base"]) if employee.get("bpjs_kesehatan") else 0
    bpjs_kes_employee = bpjs_kes_base * CONFIG["bpjs_kesehatan_employee"]
    bpjs_kes_employer = bpjs_kes_base * CONFIG["bpjs_kesehatan_employer"]

    # BPJS Ketenagakerjaan
    has_btk = employee.get("bpjs_ketenagakerjaan", True)
    jht_base = basic_paid + taxable_allowance if has_btk else 0
    jp_base = min(basic_paid + taxable_allowance, CONFIG["jp_max_base"]) if has_btk else 0

    jht_employee = jht_base * CONFIG["jht_employee"]
    jht_employer = jht_base * CONFIG["jht_employer"]
    jp_employee = jp_base * CONFIG["jp_employee"]
    jp_employer = jp_base * CONFIG["jp_employer"]
    jkk_employer = jht_base * CONFIG["jkk_employer"]
    jkm_employer = jht_base * CONFIG["jkm_employer"]

    # Annual PPh21 calculation — only taxable earnings contribute
    taxable_gross_monthly = basic_paid + taxable_allowance + taxable_only_earnings + overtime_pay + bonus
    bruto_monthly = taxable_gross_monthly + bpjs_kes_employer + jkk_employer + jkm_employer
    bruto_yearly = bruto_monthly * 12

    biaya_jabatan_yearly = min(bruto_yearly * CONFIG["biaya_jabatan_rate"], CONFIG["biaya_jabatan_max_year"])
    iuran_pengurang_yearly = (jht_employee + jp_employee) * 12

    netto_yearly = bruto_yearly - biaya_jabatan_yearly - iuran_pengurang_yearly
    ptkp = CONFIG["ptkp_table"].get(employee.get("ptkp_status", "TK/0"), 54_000_000)
    pkp = max(0, netto_yearly - ptkp)
    # Round down PKP to thousands per UU HPP
    pkp = (pkp // 1000) * 1000

    pph21_yearly = compute_pph21_annual(pkp)
    # Non-NPWP surcharge: +20%
    if not employee.get("has_npwp", True):
        pph21_yearly *= 1.2
    pph21_monthly = pph21_yearly / 12

    # Loan deduction: only if tenor still active
    loan_active = loan_installment > 0 and (loan_tenor_total == 0 or loan_tenor_paid < loan_tenor_total)
    loan_deduction = loan_installment if loan_active else 0

    total_deductions = bpjs_kes_employee + jht_employee + jp_employee + pph21_monthly + other_deduction + loan_deduction + potongan_terlambat + potongan_pulang_cepat
    net_salary = gross - total_deductions

    return {
        "earnings": {
            "basic_salary": round(basic_paid, 2),
            "fixed_allowance": round(fixed_allowance, 2),
            "tunjangan_jabatan": round(tj_jabatan, 2),
            "tunjangan_transport": round(tj_transport, 2),
            "tunjangan_lainnya": round(tj_lainnya, 2),
            "insentif_individu": round(insentif_individu, 2),
            "tunjangan_tidak_tetap": round(tj_tidak_tetap, 2),
            "tunjangan_wfh": round(tj_wfh, 2),
            "insentif_kolektif": round(insentif_kolektif, 2),
            "insentif_lain": round(insentif_lain, 2),
            "overtime": round(overtime_pay, 2),
            "bonus": round(bonus, 2),
            "gross": round(gross, 2),
        },
        "deductions": {
            "bpjs_kesehatan_employee": round(bpjs_kes_employee, 2),
            "jht_employee": round(jht_employee, 2),
            "jp_employee": round(jp_employee, 2),
            "pph21": round(pph21_monthly, 2),
            "loan": round(loan_deduction, 2),
            "other_deduction": round(other_deduction, 2),
            "potongan_terlambat": round(potongan_terlambat, 2),
            "potongan_pulang_cepat": round(potongan_pulang_cepat, 2),
            "total": round(total_deductions, 2),
        },
        "loan_info": {
            "active": loan_active,
            "installment": round(loan_installment, 2),
            "tenor_total": loan_tenor_total,
            "tenor_paid_before": loan_tenor_paid,
            "tenor_paid_after": loan_tenor_paid + 1 if loan_active else loan_tenor_paid,
            "remaining_after": max(0, loan_tenor_total - (loan_tenor_paid + 1)) if loan_active and loan_tenor_total else 0,
        },
        "employer_contributions": {
            "bpjs_kesehatan_employer": round(bpjs_kes_employer, 2),
            "jht_employer": round(jht_employer, 2),
            "jp_employer": round(jp_employer, 2),
            "jkk_employer": round(jkk_employer, 2),
            "jkm_employer": round(jkm_employer, 2),
        },
        "tax_detail": {
            "bruto_yearly": round(bruto_yearly, 2),
            "biaya_jabatan_yearly": round(biaya_jabatan_yearly, 2),
            "netto_yearly": round(netto_yearly, 2),
            "ptkp": ptkp,
            "pkp": round(pkp, 2),
            "pph21_yearly": round(pph21_yearly, 2),
        },
        "attendance": {
            "days_worked": days_worked,
            "overtime_hours": overtime_hours,
        },
        "net_salary": round(net_salary, 2),
    }


# ---------------- Auth Endpoints ----------------
@api_router.post("/auth/register")
async def register(payload: RegisterIn, response: Response):
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = str(uuid.uuid4())
    doc = {
        "id": user_id,
        "email": email,
        "name": payload.name,
        "role": "admin",
        "password_hash": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    access = create_access_token(user_id, email)
    refresh = create_refresh_token(user_id)
    set_auth_cookies(response, access, refresh)
    return {"id": user_id, "email": email, "name": payload.name, "role": "admin"}


@api_router.post("/auth/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access = create_access_token(user["id"], email)
    refresh = create_refresh_token(user["id"])
    set_auth_cookies(response, access, refresh)
    return {"id": user["id"], "email": user["email"], "name": user["name"], "role": user.get("role", "admin")}


@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user


# ---------------- Employee Portal (Self-service) ----------------
class PortalLoginIn(BaseModel):
    email: EmailStr
    nik: str


@api_router.post("/portal/login")
async def portal_login(payload: PortalLoginIn, response: Response):
    email = payload.email.lower().strip()
    nik = payload.nik.strip()
    emp = await db.employees.find_one({"nik": nik, "active": True}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=401, detail="NIK atau email salah")
    if (emp.get("email") or "").lower() != email:
        raise HTTPException(status_code=401, detail="NIK atau email salah")
    token = create_portal_token(emp["id"], email)
    response.set_cookie("portal_token", token, httponly=True, secure=False, samesite="lax", max_age=86400, path="/")
    return {
        "id": emp["id"],
        "nik": emp["nik"],
        "name": emp["name"],
        "email": emp.get("email"),
        "position": emp["position"],
        "department": emp["department"],
    }


@api_router.post("/portal/logout")
async def portal_logout(response: Response):
    response.delete_cookie("portal_token", path="/")
    return {"ok": True}


@api_router.get("/portal/me")
async def portal_me(emp: dict = Depends(get_current_employee)):
    return {
        "id": emp["id"],
        "nik": emp["nik"],
        "name": emp["name"],
        "email": emp.get("email"),
        "position": emp["position"],
        "department": emp["department"],
        "join_date": emp.get("join_date"),
        "ptkp_status": emp.get("ptkp_status"),
        "bank_name": emp.get("bank_name"),
        "bank_account": emp.get("bank_account"),
    }


@api_router.get("/portal/payslips")
async def portal_payslips(emp: dict = Depends(get_current_employee)):
    slips = await db.payslips.find(
        {"employee_id": emp["id"]},
        {"_id": 0, "id": 1, "period": 1, "net_salary": 1, "earnings.gross": 1, "deductions.pph21": 1},
    ).sort("period", -1).to_list(length=240)
    return [
        {
            "id": s["id"],
            "period": s["period"],
            "net_salary": s["net_salary"],
            "gross": s["earnings"]["gross"],
            "pph21": s["deductions"]["pph21"],
        }
        for s in slips
    ]


@api_router.get("/portal/payslip/{slip_id}")
async def portal_payslip(slip_id: str, emp: dict = Depends(get_current_employee)):
    slip = await db.payslips.find_one({"id": slip_id, "employee_id": emp["id"]}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Slip tidak ditemukan")
    return slip


@api_router.get("/portal/payslip/{slip_id}/pdf")
async def portal_payslip_pdf(slip_id: str, emp: dict = Depends(get_current_employee)):
    slip = await db.payslips.find_one({"id": slip_id, "employee_id": emp["id"]}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Slip tidak ditemukan")
    pdf = _build_payslip_pdf(slip)
    fname = f"slip-{slip['period']}-{slip['nik']}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api_router.get("/portal/thr")
async def portal_thr_list(emp: dict = Depends(get_current_employee)):
    rows = await db.thr_slips.find({"employee_id": emp["id"]}, {"_id": 0}).sort("period", -1).to_list(length=120)
    return [
        {
            "id": r["id"],
            "period": r["period"],
            "thr_gross": r["thr_gross"],
            "thr_net": r["thr_net"],
            "pph21_thr": r["pph21_thr"],
            "formula": r["formula"],
        }
        for r in rows
    ]


# ---------------- Annual Summary & Bukti Potong 1721-A1 ----------------
async def _build_annual_summary(employee_id: str, year: int) -> Dict[str, Any]:
    year_prefix = f"{year}-"
    slips = await db.payslips.find(
        {"employee_id": employee_id, "period": {"$regex": f"^{year_prefix}"}},
        {"_id": 0},
    ).sort("period", 1).to_list(length=24)
    thrs = await db.thr_slips.find(
        {"employee_id": employee_id, "period": {"$regex": f"^{year_prefix}"}},
        {"_id": 0},
    ).to_list(length=12)

    months = {}
    for s in slips:
        e, d = s["earnings"], s["deductions"]
        months[s["period"]] = {
            "period": s["period"],
            "gross": e["gross"],
            "basic": e["basic_salary"],
            "allowance": e["fixed_allowance"],
            "overtime": e["overtime"],
            "bonus": e["bonus"],
            "pph21": d["pph21"],
            "bpjs_employee": d["bpjs_kesehatan_employee"] + d["jht_employee"] + d["jp_employee"],
            "net": s["net_salary"],
        }

    total_gross = sum(m["gross"] for m in months.values())
    total_basic = sum(m["basic"] for m in months.values())
    total_allowance = sum(m["allowance"] for m in months.values())
    total_overtime = sum(m["overtime"] for m in months.values())
    total_bonus = sum(m["bonus"] for m in months.values())
    total_pph21 = sum(m["pph21"] for m in months.values())
    total_bpjs = sum(m["bpjs_employee"] for m in months.values())
    total_net = sum(m["net"] for m in months.values())

    total_thr_gross = sum(t["thr_gross"] for t in thrs)
    total_thr_pph = sum(t["pph21_thr"] for t in thrs)

    return {
        "year": year,
        "months": sorted(months.values(), key=lambda x: x["period"]),
        "totals": {
            "gross": round(total_gross, 2),
            "basic": round(total_basic, 2),
            "allowance": round(total_allowance, 2),
            "overtime": round(total_overtime, 2),
            "bonus": round(total_bonus, 2),
            "pph21": round(total_pph21, 2),
            "bpjs_employee": round(total_bpjs, 2),
            "net": round(total_net, 2),
            "thr_gross": round(total_thr_gross, 2),
            "thr_pph21": round(total_thr_pph, 2),
        },
        "months_count": len(months),
    }


def _build_bukti_potong_pdf(employee: Dict[str, Any], summary: Dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("body", parent=styles["Normal"], fontName="Helvetica", fontSize=8.5, leading=11)
    bold_style = ParagraphStyle("bold", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=11)
    tiny = ParagraphStyle("tiny", parent=styles["Normal"], fontName="Helvetica", fontSize=7, textColor=colors.HexColor("#71717a"))

    company = os.environ.get("COMPANY_NAME", "Payroll Indonesia")
    year = summary["year"]
    totals = summary["totals"]

    story = []
    # Header
    header = Table([
        [Paragraph("<b>FORMULIR 1721-A1</b><br/><font size=7>BUKTI PEMOTONGAN PAJAK PENGHASILAN PASAL 21</font>", bold_style),
         Paragraph(f"<para alignment='right'><font size=7>MASA PEROLEHAN PENGHASILAN<br/></font><b>JANUARI &nbsp;–&nbsp; DESEMBER {year}</b></para>", body_style)],
    ], colWidths=[110 * mm, 70 * mm])
    header.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.5, colors.HexColor("#18181b")),
        ("LINEBELOW", (0, -1), (-1, -1), 1.5, colors.HexColor("#18181b")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f4f5")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(header)
    story.append(Spacer(1, 6))

    # Employer info
    story.append(Paragraph("<b>A. IDENTITAS PEMOTONG</b>", bold_style))
    employer = Table([
        ["Nama Pemotong", ":", company],
        ["NPWP Pemotong", ":", os.environ.get("COMPANY_NPWP", "00.000.000.0-000.000")],
    ], colWidths=[40 * mm, 6 * mm, 130 * mm])
    employer.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(employer)
    story.append(Spacer(1, 6))

    # Employee info
    story.append(Paragraph("<b>B. IDENTITAS PENERIMA PENGHASILAN</b>", bold_style))
    emp_table = Table([
        ["Nama", ":", employee.get("name", ""), "NIK/NIP", ":", employee.get("nik", "")],
        ["NPWP", ":", employee.get("npwp") or "—", "Status PTKP", ":", employee.get("ptkp_status", "")],
        ["Jabatan", ":", employee.get("position", ""), "Departemen", ":", employee.get("department", "")],
    ], colWidths=[22 * mm, 5 * mm, 60 * mm, 25 * mm, 5 * mm, 63 * mm])
    emp_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(emp_table)
    story.append(Spacer(1, 10))

    # Bagian C: Rincian Penghasilan
    story.append(Paragraph("<b>C. RINCIAN PENGHASILAN DAN PENGHITUNGAN PPh PASAL 21</b>", bold_style))

    biaya_jabatan = min(totals["gross"] * CONFIG["biaya_jabatan_rate"], CONFIG["biaya_jabatan_max_year"])
    ptkp = CONFIG["ptkp_table"].get(employee.get("ptkp_status", "TK/0"), 54_000_000)
    # Use the per-month progressive PPh already computed in slips (includes THR PPh separately)
    pph_total = totals["pph21"] + totals["thr_pph21"]

    rows = [
        ["NO", "PENGHASILAN", "JUMLAH (Rp)"],
        ["1", "Gaji/Tunjangan Tetap", _format_idr(totals["basic"] + totals["allowance"])],
        ["2", "Uang Lembur", _format_idr(totals["overtime"])],
        ["3", "Bonus / Tantiem", _format_idr(totals["bonus"])],
        ["4", "Tunjangan Hari Raya (THR)", _format_idr(totals["thr_gross"])],
        ["5", "Jumlah Penghasilan Bruto (1+2+3+4)", _format_idr(totals["gross"] + totals["thr_gross"])],
        ["", "PENGURANGAN", ""],
        ["6", "Biaya Jabatan", _format_idr(biaya_jabatan)],
        ["7", "Iuran BPJS Karyawan (Kes + JHT + JP)", _format_idr(totals["bpjs_employee"])],
        ["8", "Jumlah Pengurangan (6+7)", _format_idr(biaya_jabatan + totals["bpjs_employee"])],
        ["", "PERHITUNGAN PPh 21", ""],
        ["9", "Penghasilan Neto (5−8)", _format_idr(totals["gross"] + totals["thr_gross"] - biaya_jabatan - totals["bpjs_employee"])],
        ["10", f"PTKP Setahun ({employee.get('ptkp_status', 'TK/0')})", _format_idr(ptkp)],
        ["11", "PKP (9−10)", _format_idr(max(0, totals["gross"] + totals["thr_gross"] - biaya_jabatan - totals["bpjs_employee"] - ptkp))],
        ["12", "PPh 21 Terutang Setahun", _format_idr(pph_total)],
        ["13", "PPh 21 yang sudah dipotong", _format_idr(pph_total)],
        ["14", "PPh 21 kurang/(lebih) dipotong", _format_idr(0)],
    ]
    t = Table(rows, colWidths=[10 * mm, 110 * mm, 60 * mm])
    style = TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f4f5")),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("FONTNAME", (2, 1), (2, -1), "Courier"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d4d4d8")),
        ("BACKGROUND", (0, 6), (-1, 6), colors.HexColor("#f4f4f5")),
        ("BACKGROUND", (0, 10), (-1, 10), colors.HexColor("#f4f4f5")),
        ("FONTNAME", (0, 5), (-1, 5), "Helvetica-Bold"),
        ("FONTNAME", (0, 9), (-1, 9), "Helvetica-Bold"),
        ("FONTNAME", (0, 11), (-1, 11), "Helvetica-Bold"),
        ("FONTNAME", (0, 14), (-1, 14), "Helvetica-Bold"),
        ("LINEABOVE", (0, 14), (-1, 14), 1.2, colors.HexColor("#18181b")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])
    t.setStyle(style)
    story.append(t)
    story.append(Spacer(1, 12))

    # Monthly breakdown
    story.append(Paragraph("<b>D. RINCIAN BULANAN</b>", bold_style))
    m_rows = [["BULAN", "BRUTO", "PPh 21", "BPJS", "TAKE HOME"]]
    for m in summary["months"]:
        m_rows.append([m["period"], _format_idr(m["gross"]), _format_idr(m["pph21"]), _format_idr(m["bpjs_employee"]), _format_idr(m["net"])])
    m_rows.append(["TOTAL", _format_idr(totals["gross"]), _format_idr(totals["pph21"]), _format_idr(totals["bpjs_employee"]), _format_idr(totals["net"])])
    mt = Table(m_rows, colWidths=[30 * mm, 35 * mm, 35 * mm, 35 * mm, 45 * mm])
    mt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f4f5")),
        ("FONTNAME", (1, 1), (-1, -1), "Courier"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, -1), (-1, -1), "Courier-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fafafa")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d4d4d8")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(mt)
    story.append(Spacer(1, 12))

    # Footer signature
    story.append(Paragraph(
        "<i>Catatan: Formulir ini merupakan ringkasan dari rincian slip gaji bulanan. "
        "Gunakan sebagai referensi untuk SPT Tahunan PPh Orang Pribadi.</i>",
        tiny,
    ))
    story.append(Spacer(1, 14))
    sign_table = Table([
        ["", ""],
        ["Diterima oleh,", "Diterbitkan oleh Pemotong,"],
        ["", ""],
        [Paragraph(f"<b>{employee.get('name','')}</b><br/><font size=7>NIK: {employee.get('nik','')}</font>", body_style),
         Paragraph(f"<b>{company}</b><br/><font size=7>HR / Pajak</font>", body_style)],
    ], colWidths=[90 * mm, 90 * mm])
    sign_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TOPPADDING", (0, 2), (-1, 2), 24),
    ]))
    story.append(sign_table)

    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


@api_router.get("/portal/annual/{year}")
async def portal_annual(year: int, emp: dict = Depends(get_current_employee)):
    return await _build_annual_summary(emp["id"], year)


@api_router.get("/portal/bukti-potong/{year}/pdf")
async def portal_bukti_potong(year: int, emp: dict = Depends(get_current_employee)):
    summary = await _build_annual_summary(emp["id"], year)
    if summary["months_count"] == 0:
        raise HTTPException(status_code=404, detail=f"Tidak ada data penghasilan tahun {year}")
    pdf = _build_bukti_potong_pdf(emp, summary)
    fname = f"bukti-potong-1721-A1-{year}-{emp['nik']}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# Admin can also download bukti potong for any employee
@api_router.get("/payroll/bukti-potong/{employee_id}/{year}/pdf")
async def admin_bukti_potong(employee_id: str, year: int, user: dict = Depends(require_super_admin)):
    emp = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")
    summary = await _build_annual_summary(employee_id, year)
    if summary["months_count"] == 0:
        raise HTTPException(status_code=404, detail=f"Tidak ada data penghasilan tahun {year}")
    pdf = _build_bukti_potong_pdf(emp, summary)
    fname = f"bukti-potong-1721-A1-{year}-{emp['nik']}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------------- Portal Magic Link (Forgot NIK) ----------------
class ForgotPortalIn(BaseModel):
    email: EmailStr


@api_router.post("/portal/forgot")
async def portal_forgot(payload: ForgotPortalIn):
    """Generate one-time magic login token and email it. Always returns ok to avoid email enumeration."""
    import secrets as pysecrets

    email = payload.email.lower().strip()
    emp = await db.employees.find_one({"email": email, "active": True}, {"_id": 0})
    if not emp:
        # Don't reveal whether email exists
        return {"ok": True}

    token = pysecrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    await db.portal_reset_tokens.insert_one({
        "id": str(uuid.uuid4()),
        "token": token,
        "employee_id": emp["id"],
        "email": email,
        "expires_at": expires_at,
        "used": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Build magic link
    frontend_base = os.environ.get("PUBLIC_APP_URL", "").rstrip("/")
    if not frontend_base:
        # Best-effort: derive from referer header would need request; default to relative path
        frontend_base = ""
    magic_link = f"{frontend_base}/portal/magic-login?token={token}"

    company = os.environ.get("COMPANY_NAME", "Payroll Indonesia")
    html = f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; color: #18181b;">
      <tr><td style="padding: 24px 0; border-bottom: 2px solid #18181b;">
        <h2 style="margin:0; font-size:20px;">Akses Portal Karyawan</h2>
        <div style="font-size:12px; color:#71717a; margin-top:4px;">{company}</div>
      </td></tr>
      <tr><td style="padding: 20px 0; font-size:14px;">
        Halo <strong>{emp['name']}</strong>,<br/><br/>
        Klik tombol di bawah untuk masuk ke Portal Karyawan tanpa NIK. Link berlaku <strong>30 menit</strong>.
      </td></tr>
      <tr><td style="padding: 8px 0 24px;">
        <a href="{magic_link}" style="background:#002FA7; color:white; text-decoration:none; padding:12px 20px; font-weight:600; display:inline-block;">Masuk ke Portal</a>
      </td></tr>
      <tr><td style="padding-top: 16px; font-size:11px; color:#71717a;">
        Jika Anda tidak meminta link ini, abaikan email ini. NIK Anda: <strong>{emp['nik']}</strong> (untuk login manual).
      </td></tr>
    </table>
    """
    subject = "Link Masuk Portal Karyawan"

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if api_key:
        try:
            import resend
            resend.api_key = api_key
            sender = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
            await asyncio.to_thread(resend.Emails.send, {
                "from": sender, "to": [email], "subject": subject, "html": html,
            })
            status = "sent"
        except Exception as ex:
            logger.error(f"Magic link email failed: {ex}")
            status = "failed"
    else:
        status = "mocked"
        logger.info(f"[MOCK MAGIC LINK] {email} → {magic_link}")

    await db.email_logs.insert_one({
        "id": str(uuid.uuid4()),
        "type": "magic_link",
        "email": email,
        "employee_id": emp["id"],
        "status": status,
        "magic_link": magic_link if status == "mocked" else None,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True, "status": status, "magic_link_preview": magic_link if status == "mocked" else None}


@api_router.post("/portal/magic-login")
async def portal_magic_login(token: str, response: Response):
    rec = await db.portal_reset_tokens.find_one({"token": token, "used": False})
    if not rec:
        raise HTTPException(status_code=400, detail="Link tidak valid atau sudah dipakai")
    exp = rec.get("expires_at")
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp)
        except Exception:
            exp = None
    if not exp or datetime.now(timezone.utc) > (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)):
        raise HTTPException(status_code=400, detail="Link sudah kedaluwarsa")

    emp = await db.employees.find_one({"id": rec["employee_id"], "active": True}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Karyawan tidak aktif")

    await db.portal_reset_tokens.update_one({"_id": rec["_id"]}, {"$set": {"used": True, "used_at": datetime.now(timezone.utc).isoformat()}})
    portal_token = create_portal_token(emp["id"], emp.get("email") or "")
    response.set_cookie("portal_token", portal_token, httponly=True, secure=False, samesite="lax", max_age=86400, path="/")
    return {
        "id": emp["id"],
        "nik": emp["nik"],
        "name": emp["name"],
        "email": emp.get("email"),
        "position": emp["position"],
        "department": emp["department"],
    }


# ---------------- Employee Endpoints (Admin) ----------------
@api_router.get("/employees")
async def list_employees(user: dict = Depends(require_super_admin)):
    cursor = db.employees.find({}, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(length=2000)
    return items


@api_router.post("/employees")
async def create_employee(payload: EmployeeIn, user: dict = Depends(require_super_admin)):
    if await db.employees.find_one({"nik": payload.nik}):
        raise HTTPException(status_code=400, detail="NIK sudah terdaftar")
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.get("/employees/{employee_id}")
async def get_employee(employee_id: str, user: dict = Depends(require_super_admin)):
    emp = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")
    return emp


@api_router.put("/employees/{employee_id}")
async def update_employee(employee_id: str, payload: EmployeeIn, user: dict = Depends(require_super_admin)):
    emp = await db.employees.find_one({"id": employee_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")
    if payload.nik != emp["nik"]:
        existing = await db.employees.find_one({"nik": payload.nik})
        if existing:
            raise HTTPException(status_code=400, detail="NIK sudah dipakai karyawan lain")
    data = payload.model_dump()
    await db.employees.update_one({"id": employee_id}, {"$set": data})
    updated = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    return updated


@api_router.delete("/employees/{employee_id}")
async def delete_employee(employee_id: str, user: dict = Depends(require_super_admin)):
    res = await db.employees.delete_one({"id": employee_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")
    return {"ok": True}


# ---------------- Payroll Endpoints ----------------
@api_router.post("/payroll/preview")
async def preview_payroll(payload: PayrollRunIn, user: dict = Depends(require_super_admin)):
    employees = await db.employees.find({"active": True}, {"_id": 0}).to_list(length=2000)
    slips = []
    for emp in employees:
        att = payload.attendance.get(emp["id"], {"days_worked": 22})
        slip = calculate_payslip(emp, att)
        slips.append({
            "employee_id": emp["id"],
            "nik": emp["nik"],
            "name": emp["name"],
            "position": emp["position"],
            "department": emp["department"],
            "ptkp_status": emp.get("ptkp_status", "TK/0"),
            **slip,
        })
    totals = {
        "gross": sum(s["earnings"]["gross"] for s in slips),
        "pph21": sum(s["deductions"]["pph21"] for s in slips),
        "bpjs_employee": sum(
            s["deductions"]["bpjs_kesehatan_employee"] + s["deductions"]["jht_employee"] + s["deductions"]["jp_employee"]
            for s in slips
        ),
        "net": sum(s["net_salary"] for s in slips),
        "count": len(slips),
    }
    return {"period": payload.period, "slips": slips, "totals": totals}


@api_router.post("/payroll/run")
async def run_payroll(payload: PayrollRunIn, user: dict = Depends(require_super_admin)):
    existing = await db.payroll_runs.find_one({"period": payload.period})
    if existing:
        # overwrite previous run for same period — first rollback loan_tenor increments
        old_slips = await db.payslips.find({"period": payload.period}, {"_id": 0, "employee_id": 1, "loan_info": 1}).to_list(length=5000)
        for os_ in old_slips:
            if os_.get("loan_info", {}).get("active"):
                await db.employees.update_one({"id": os_["employee_id"]}, {"$inc": {"loan_tenor_paid": -1}})
        await db.payroll_runs.delete_one({"period": payload.period})
        await db.payslips.delete_many({"period": payload.period})

    employees = await db.employees.find({"active": True}, {"_id": 0}).to_list(length=2000)
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    total_gross = 0.0
    total_net = 0.0
    total_pph = 0.0
    total_bpjs_emp = 0.0
    slips_to_insert = []

    for emp in employees:
        att = payload.attendance.get(emp["id"], {"days_worked": 22})
        slip = calculate_payslip(emp, att)
        slip_doc = {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "period": payload.period,
            "employee_id": emp["id"],
            "nik": emp["nik"],
            "name": emp["name"],
            "position": emp["position"],
            "department": emp["department"],
            "ptkp_status": emp.get("ptkp_status", "TK/0"),
            "npwp": emp.get("npwp"),
            "has_npwp": emp.get("has_npwp", True),
            "bank_name": emp.get("bank_name"),
            "bank_account": emp.get("bank_account"),
            "created_at": now,
            **slip,
        }
        slips_to_insert.append(slip_doc)
        total_gross += slip["earnings"]["gross"]
        total_net += slip["net_salary"]
        total_pph += slip["deductions"]["pph21"]
        total_bpjs_emp += (
            slip["deductions"]["bpjs_kesehatan_employee"]
            + slip["deductions"]["jht_employee"]
            + slip["deductions"]["jp_employee"]
        )
        # Auto-increment loan tenor when this run deducted loan
        if slip.get("loan_info", {}).get("active"):
            await db.employees.update_one(
                {"id": emp["id"]},
                {"$inc": {"loan_tenor_paid": 1}},
            )

    if slips_to_insert:
        await db.payslips.insert_many(slips_to_insert)

    run_doc = {
        "id": run_id,
        "period": payload.period,
        "created_at": now,
        "employee_count": len(slips_to_insert),
        "total_gross": round(total_gross, 2),
        "total_net": round(total_net, 2),
        "total_pph21": round(total_pph, 2),
        "total_bpjs_employee": round(total_bpjs_emp, 2),
    }
    await db.payroll_runs.insert_one(run_doc)
    run_doc.pop("_id", None)
    return run_doc


@api_router.get("/payroll/runs")
async def list_runs(user: dict = Depends(require_super_admin)):
    runs = await db.payroll_runs.find({}, {"_id": 0}).sort("period", -1).to_list(length=500)
    return runs


@api_router.get("/payroll/runs/{period}/slips")
async def list_run_slips(period: str, user: dict = Depends(require_super_admin)):
    slips = await db.payslips.find({"period": period}, {"_id": 0}).sort("name", 1).to_list(length=2000)
    if not slips:
        raise HTTPException(status_code=404, detail="Payroll untuk periode ini belum dijalankan")
    return slips


@api_router.get("/payroll/payslip/{slip_id}")
async def get_payslip(slip_id: str, user: dict = Depends(require_super_admin)):
    slip = await db.payslips.find_one({"id": slip_id}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Slip gaji tidak ditemukan")
    return slip


@api_router.delete("/payroll/runs/{period}")
async def delete_run(period: str, user: dict = Depends(require_super_admin)):
    # Rollback loan_tenor increments for any active loan deductions in this run
    old_slips = await db.payslips.find({"period": period}, {"_id": 0, "employee_id": 1, "loan_info": 1}).to_list(length=5000)
    for os_ in old_slips:
        if os_.get("loan_info", {}).get("active"):
            await db.employees.update_one({"id": os_["employee_id"]}, {"$inc": {"loan_tenor_paid": -1}})
    await db.payroll_runs.delete_one({"period": period})
    await db.payslips.delete_many({"period": period})
    return {"ok": True}


# ---------------- PDF Export ----------------
def _format_idr(n: float) -> str:
    try:
        return "Rp " + f"{int(round(n)):,}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _build_payslip_pdf(slip: Dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    styles = getSampleStyleSheet()
    label_style = ParagraphStyle("lbl", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7, textColor=colors.HexColor("#71717a"))
    val_style = ParagraphStyle("val", parent=styles["Normal"], fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#18181b"))
    section_style = ParagraphStyle("sec", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#18181b"), spaceAfter=4, spaceBefore=6)

    story = []
    # Header
    header = Table(
        [[
            Paragraph("<b>PAYROLL.ID</b><br/><font size=7 color='#71717a'>HR · TAX · BPJS</font>", val_style),
            Paragraph(f"<para alignment='right'><font size=7 color='#71717a'>SLIP GAJI</font><br/><b><font size=14>Periode {slip['period']}</font></b><br/><font size=7 color='#71717a' face='Courier'>No: {slip['id'][:8].upper()}</font></para>", val_style),
        ]],
        colWidths=[90 * mm, 90 * mm],
    )
    header.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1.5, colors.HexColor("#18181b")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(header)
    story.append(Spacer(1, 8))

    # Employee
    emp = Table(
        [
            [Paragraph("NAMA KARYAWAN", label_style), Paragraph(slip["name"], val_style),
             Paragraph("NIK", label_style), Paragraph(f"<font face='Courier'>{slip['nik']}</font>", val_style)],
            [Paragraph("JABATAN / DEPT", label_style), Paragraph(f"{slip['position']} · {slip['department']}", val_style),
             Paragraph("PTKP / NPWP", label_style), Paragraph(f"<font face='Courier'>{slip['ptkp_status']} · {'Ya' if slip.get('has_npwp', True) else 'Tidak'}</font>", val_style)],
        ],
        colWidths=[35 * mm, 55 * mm, 30 * mm, 60 * mm],
    )
    emp.setStyle(TableStyle([
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, colors.HexColor("#e4e4e7")),
    ]))
    story.append(emp)
    story.append(Spacer(1, 10))

    # Earnings & Deductions side by side
    e = slip["earnings"]
    d = slip["deductions"]
    earn_rows = [
        ["PENDAPATAN", ""],
        ["Gaji Pokok", _format_idr(e["basic_salary"])],
    ]
    if e.get("fixed_allowance", 0):
        earn_rows.append(["Tunjangan Tetap", _format_idr(e["fixed_allowance"])])
    if e.get("tunjangan_jabatan", 0):
        earn_rows.append(["Tj. Jabatan", _format_idr(e["tunjangan_jabatan"])])
    if e.get("tunjangan_transport", 0):
        earn_rows.append(["Tj. Transport", _format_idr(e["tunjangan_transport"])])
    if e.get("tunjangan_lainnya", 0):
        earn_rows.append(["Tj. Lain-lain", _format_idr(e["tunjangan_lainnya"])])
    if e.get("tunjangan_tidak_tetap", 0):
        earn_rows.append(["Tj. Tidak Tetap", _format_idr(e["tunjangan_tidak_tetap"])])
    if e.get("tunjangan_wfh", 0):
        earn_rows.append(["Tj. WFH", _format_idr(e["tunjangan_wfh"])])
    if e.get("insentif_individu", 0):
        earn_rows.append(["Insentif Individu", _format_idr(e["insentif_individu"])])
    if e.get("insentif_kolektif", 0):
        earn_rows.append(["Insentif Kolektif", _format_idr(e["insentif_kolektif"])])
    if e.get("insentif_lain", 0):
        earn_rows.append(["Insentif Lain-lain", _format_idr(e["insentif_lain"])])
    if e.get("overtime", 0):
        earn_rows.append(["Lembur", _format_idr(e["overtime"])])
    if e.get("bonus", 0):
        earn_rows.append(["Bonus", _format_idr(e["bonus"])])
    earn_rows.append(["Total Bruto", _format_idr(e["gross"])])

    deduct_rows = [
        ["POTONGAN", ""],
        ["BPJS Kesehatan (1%)", _format_idr(d["bpjs_kesehatan_employee"])],
        ["JHT (2%)", _format_idr(d["jht_employee"])],
        ["JP (1%)", _format_idr(d["jp_employee"])],
        ["PPh 21", _format_idr(d["pph21"])],
    ]
    if d.get("loan", 0):
        deduct_rows.append(["Angsuran Pinjaman", _format_idr(d["loan"])])
    if d.get("potongan_terlambat", 0):
        deduct_rows.append(["Potongan Terlambat", _format_idr(d["potongan_terlambat"])])
    if d.get("potongan_pulang_cepat", 0):
        deduct_rows.append(["Potongan Pulang Cepat", _format_idr(d["potongan_pulang_cepat"])])
    if d.get("other_deduction", 0):
        deduct_rows.append(["Potongan Lain", _format_idr(d["other_deduction"])])
    deduct_rows.append(["Total Potongan", _format_idr(d["total"])])
    # Pad to same length
    max_len = max(len(earn_rows), len(deduct_rows))
    while len(earn_rows) < max_len:
        earn_rows.insert(-1, ["", ""])

    def style_box(rows, header_color):
        t = Table(rows, colWidths=[48 * mm, 40 * mm])
        s = TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("TEXTCOLOR", (0, 0), (-1, 0), header_color),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#a1a1aa")),
            ("FONTNAME", (1, 1), (1, -1), "Courier"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, -1), (1, -1), "Courier-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 0.4, colors.HexColor("#71717a")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
        t.setStyle(s)
        return t

    two_col = Table(
        [[style_box(earn_rows, colors.HexColor("#008A00")), style_box(deduct_rows, colors.HexColor("#E81123"))]],
        colWidths=[90 * mm, 90 * mm],
    )
    two_col.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(two_col)
    story.append(Spacer(1, 12))

    # Take home (dark block)
    th = Table(
        [[
            Paragraph(f"<font size=7 color='#a1a1aa'>TAKE HOME PAY</font><br/><font size=7 color='#a1a1aa'>Hari kerja: {slip['attendance']['days_worked']} · Lembur: {slip['attendance']['overtime_hours']} jam</font>", val_style),
            Paragraph(f"<para alignment='right'><b><font face='Courier-Bold' size=18 color='white'>{_format_idr(slip['net_salary'])}</font></b></para>", val_style),
        ]],
        colWidths=[90 * mm, 90 * mm],
    )
    th.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#18181b")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(th)
    story.append(Spacer(1, 12))

    # Tax detail
    t = slip["tax_detail"]
    tax_rows = [
        ["Bruto Setahun", _format_idr(t["bruto_yearly"])],
        ["Biaya Jabatan", "- " + _format_idr(t["biaya_jabatan_yearly"])],
        ["Netto Setahun", _format_idr(t["netto_yearly"])],
        [f"PTKP ({slip['ptkp_status']})", "- " + _format_idr(t["ptkp"])],
        ["PKP", _format_idr(t["pkp"])],
        ["PPh 21 Setahun", _format_idr(t["pph21_yearly"])],
    ]
    story.append(Paragraph("RINCIAN PERHITUNGAN PPH 21", section_style))
    tt = Table(tax_rows, colWidths=[100 * mm, 80 * mm])
    tt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (1, 0), (1, -1), "Courier"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#52525b")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#f4f4f5")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tt)

    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


@api_router.get("/payroll/payslip/{slip_id}/pdf")
async def export_payslip_pdf(slip_id: str, user: dict = Depends(require_super_admin)):
    slip = await db.payslips.find_one({"id": slip_id}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Slip gaji tidak ditemukan")
    pdf = _build_payslip_pdf(slip)
    fname = f"slip-{slip['period']}-{slip['nik']}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------------- Employee CSV Import ----------------
EMPLOYEE_CSV_HEADERS = [
    "nik", "name", "email", "phone", "position", "department", "join_date",
    "basic_salary", "fixed_allowance", "ptkp_status", "npwp", "has_npwp",
    "bpjs_kesehatan", "bpjs_ketenagakerjaan", "bank_name", "bank_account",
]


def _parse_bool(v: str, default: bool = True) -> bool:
    if v is None or v == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "ya", "y")


@api_router.get("/employees-template.csv")
async def employee_template(user: dict = Depends(require_super_admin)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EMPLOYEE_CSV_HEADERS)
    # example row
    writer.writerow([
        "EMP001", "Budi Santoso", "budi@company.id", "081234567890", "Software Engineer", "Engineering",
        "2024-01-15", "10000000", "2000000", "TK/0", "12.345.678.9-012.000", "true",
        "true", "true", "BCA", "1234567890",
    ])
    csv_bytes = output.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="employee_template.csv"'},
    )


@api_router.post("/employees-import")
async def employees_import(file: UploadFile = File(...), user: dict = Depends(require_super_admin)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File harus berformat .csv")
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    missing = [h for h in ["nik", "name", "position", "department", "basic_salary"] if h not in fieldnames]
    if missing:
        raise HTTPException(status_code=400, detail=f"Kolom wajib hilang: {', '.join(missing)}")

    created = 0
    skipped = 0
    errors: List[str] = []

    for i, row in enumerate(reader, start=2):
        try:
            row = {(k or "").strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
            nik = row.get("nik")
            if not nik:
                errors.append(f"Baris {i}: NIK kosong")
                skipped += 1
                continue
            if await db.employees.find_one({"nik": nik}):
                errors.append(f"Baris {i}: NIK '{nik}' sudah ada")
                skipped += 1
                continue

            doc = {
                "id": str(uuid.uuid4()),
                "nik": nik,
                "name": row.get("name") or "",
                "email": row.get("email") or None,
                "phone": row.get("phone") or None,
                "position": row.get("position") or "",
                "department": row.get("department") or "",
                "join_date": row.get("join_date") or datetime.now(timezone.utc).date().isoformat(),
                "basic_salary": float(row.get("basic_salary") or 0),
                "fixed_allowance": float(row.get("fixed_allowance") or 0),
                "ptkp_status": row.get("ptkp_status") or "TK/0",
                "npwp": row.get("npwp") or None,
                "has_npwp": _parse_bool(row.get("has_npwp", ""), True),
                "bpjs_kesehatan": _parse_bool(row.get("bpjs_kesehatan", ""), True),
                "bpjs_ketenagakerjaan": _parse_bool(row.get("bpjs_ketenagakerjaan", ""), True),
                "bank_name": row.get("bank_name") or None,
                "bank_account": row.get("bank_account") or None,
                "active": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.employees.insert_one(doc)
            created += 1
        except Exception as ex:
            errors.append(f"Baris {i}: {str(ex)}")
            skipped += 1

    return {"created": created, "skipped": skipped, "errors": errors[:20]}


# ---------------- Attendance Import (Fingerprint) ----------------
NIK_COLS = {"nik", "pin", "userid", "user_id", "employee_id", "employee", "no_pegawai", "id"}
DATE_COLS = {"tanggal", "date", "tgl"}
TIME_COLS = {"jam", "time", "clock", "waktu", "jam_scan"}
DATETIME_COLS = {"datetime", "date_time", "tanggal_jam", "timestamp", "tgl_jam"}
STATUS_COLS = {"status", "verify", "io", "in_out"}

STANDARD_START_HOUR = 8
STANDARD_END_HOUR = 17
STANDARD_DAYS_DEFAULT = 22


def _normalize_col(c):
    return str(c).strip().lower().replace(" ", "_") if c is not None else ""


def _find_col(cols, candidates):
    for c in cols:
        if _normalize_col(c) in candidates:
            return c
    return None


@api_router.post("/attendance/import")
async def attendance_import(
    period: str,
    file: UploadFile = File(...),
    user: dict = Depends(require_super_admin),
):
    """Import fingerprint export (xlsx/xls/csv).

    Format yang didukung: log mentah (1 baris = 1 scan).
    Sistem akan mengelompokkan per (NIK, tanggal) untuk menentukan jam IN/OUT,
    menghitung hari kerja dan jam lembur (menit setelah 17:00).
    Hasilnya bisa di-load otomatis ke halaman Payroll periode ybs.
    """
    import pandas as pd
    from datetime import time as dtime

    if not file.filename:
        raise HTTPException(status_code=400, detail="File tidak valid")
    fname = file.filename.lower()
    raw = await file.read()

    try:
        if fname.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(raw))
            except Exception:
                df = pd.read_csv(io.BytesIO(raw), encoding="latin-1")
        elif fname.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(raw), engine="openpyxl")
        elif fname.endswith(".xls"):
            df = pd.read_excel(io.BytesIO(raw), engine="xlrd")
        else:
            raise HTTPException(status_code=400, detail="Format harus .csv, .xls, atau .xlsx")
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Gagal membaca file: {str(ex)[:200]}")

    if df.empty:
        raise HTTPException(status_code=400, detail="File kosong")

    cols = list(df.columns)
    nik_col = _find_col(cols, NIK_COLS)
    dt_col = _find_col(cols, DATETIME_COLS)
    date_col = _find_col(cols, DATE_COLS)
    time_col = _find_col(cols, TIME_COLS)

    if not nik_col:
        raise HTTPException(status_code=400, detail=f"Kolom NIK/PIN tidak ditemukan. Kolom file: {cols}")
    if not dt_col and not (date_col and time_col) and not date_col:
        raise HTTPException(status_code=400, detail="Kolom tanggal/jam tidak ditemukan")

    # Build a unified datetime column
    def _try_parse(series, with_dayfirst):
        return pd.to_datetime(series, errors="coerce", dayfirst=with_dayfirst)

    def _best_parse(series):
        a = _try_parse(series, False)
        if a.isna().mean() < 0.3:
            return a
        b = _try_parse(series, True)
        return b if b.isna().mean() < a.isna().mean() else a

    if dt_col:
        df["_dt"] = _best_parse(df[dt_col])
    else:
        if time_col:
            combined = df[date_col].astype(str) + " " + df[time_col].astype(str)
            df["_dt"] = _best_parse(combined)
        else:
            df["_dt"] = _best_parse(df[date_col])

    df = df.dropna(subset=["_dt"])
    df["_nik"] = df[nik_col].astype(str).str.strip()
    df = df[df["_nik"] != ""]
    df["_date"] = df["_dt"].dt.date

    # Aggregate per (nik, date) -> earliest=IN, latest=OUT
    agg = df.groupby(["_nik", "_date"]).agg(in_time=("_dt", "min"), out_time=("_dt", "max")).reset_index()

    # Filter to period (YYYY-MM)
    try:
        period_year, period_month = period.split("-")
        py, pm = int(period_year), int(period_month)
    except Exception:
        raise HTTPException(status_code=400, detail="Periode harus format YYYY-MM")
    agg = agg[agg["_date"].apply(lambda d: d.year == py and d.month == pm)]

    # Aggregate per employee
    employees = await db.employees.find({}, {"_id": 0}).to_list(length=5000)
    emp_by_nik = {e["nik"]: e for e in employees}

    end_dt_template = dtime(STANDARD_END_HOUR, 0)
    summary: Dict[str, Dict[str, float]] = {}
    unmatched_nik = set()
    total_scans = int(len(df))

    for nik, group in agg.groupby("_nik"):
        days_worked = int(len(group))
        overtime_minutes = 0.0
        for _, r in group.iterrows():
            out_t = r["out_time"]
            # compute minutes after STANDARD_END_HOUR:00 on same date
            end_dt = pd.Timestamp.combine(r["_date"], end_dt_template)
            diff = (out_t - end_dt).total_seconds() / 60.0
            if diff > 0:
                overtime_minutes += diff
        overtime_hours = round(overtime_minutes / 60.0, 2)

        emp = emp_by_nik.get(str(nik))
        if not emp:
            unmatched_nik.add(str(nik))
            continue

        summary[emp["id"]] = {
            "nik": nik,
            "name": emp["name"],
            "days_worked": days_worked,
            "overtime_hours": overtime_hours,
            "bonus": 0,
            "deduction": 0,
        }

    # Persist
    record = {
        "period": period,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "filename": file.filename,
        "summary": summary,
        "total_scans": total_scans,
        "matched_employees": len(summary),
        "unmatched_niks": sorted(unmatched_nik),
    }
    await db.attendance_imports.replace_one({"period": period}, record, upsert=True)

    return {
        "period": period,
        "total_scans": total_scans,
        "matched_employees": len(summary),
        "unmatched_niks": sorted(unmatched_nik),
        "summary": summary,
    }


@api_router.get("/attendance/{period}")
async def get_attendance(period: str, user: dict = Depends(require_super_admin)):
    rec = await db.attendance_imports.find_one({"period": period}, {"_id": 0})
    if not rec:
        return {"period": period, "summary": {}, "matched_employees": 0, "total_scans": 0, "unmatched_niks": []}
    return rec


# ---------------- Dashboard ----------------
@api_router.get("/dashboard/stats")
async def dashboard_stats(user: dict = Depends(require_super_admin)):
    total_employees = await db.employees.count_documents({"active": True})
    runs = await db.payroll_runs.find({}, {"_id": 0}).sort("period", -1).to_list(length=12)
    latest = runs[0] if runs else None
    trend = list(reversed([
        {"period": r["period"], "total_net": r["total_net"], "total_gross": r["total_gross"]}
        for r in runs
    ]))
    # Kontrak/OJT akan habis dalam 90 hari
    expiring = await _find_expiring_contracts(90)
    # Inventory summary utk widget dashboard
    inv_summary = {
        "total_materials": 0,
        "total_stock_value": 0.0,
        "low_stock_count": 0,
        "total_waste_this_month": 0.0,
        "waste_records_this_month": 0,
        "top_waste": [],
    }
    try:
        mats = await db.materials.find({}, {"_id": 0}).to_list(length=5000)
        total_stock_value = sum(float(m.get("current_stock", 0)) * float(m.get("purchase_price", 0)) for m in mats)
        low_stock = [m for m in mats if m.get("active", True) and float(m.get("min_stock", 0)) > 0 and float(m.get("current_stock", 0)) <= float(m.get("min_stock", 0))]
        today = datetime.now(timezone.utc).date()
        month_start = today.replace(day=1).isoformat()
        waste_month = await db.waste.find({"date": {"$gte": month_start}}, {"_id": 0}).to_list(length=5000)
        total_waste_month = sum(float(w.get("estimated_loss", 0)) for w in waste_month)
        # top waste
        top_agg: Dict[str, Dict[str, Any]] = {}
        mat_by_id = {m["id"]: m for m in mats}
        for w in waste_month:
            mid = w.get("material_id")
            if not mid:
                continue
            mat = mat_by_id.get(mid, {})
            row = top_agg.setdefault(mid, {"material_name": mat.get("name") or "-", "material_unit": mat.get("unit") or "", "qty": 0.0, "loss": 0.0})
            row["qty"] += float(w.get("quantity", 0))
            row["loss"] += float(w.get("estimated_loss", 0))
        top_waste = sorted(top_agg.values(), key=lambda r: r["loss"], reverse=True)[:3]
        for r in top_waste:
            r["qty"] = round(r["qty"], 4)
            r["loss"] = round(r["loss"], 2)
        inv_summary = {
            "total_materials": sum(1 for m in mats if m.get("active", True)),
            "total_stock_value": round(total_stock_value, 2),
            "low_stock_count": len(low_stock),
            "total_waste_this_month": round(total_waste_month, 2),
            "waste_records_this_month": len(waste_month),
            "top_waste": top_waste,
        }
    except Exception as ex:
        logger.warning(f"Inventory summary failed: {ex}")
    return {
        "total_employees": total_employees,
        "latest_run": latest,
        "trend": trend,
        "total_runs": await db.payroll_runs.count_documents({}),
        "contract_expiring": expiring[:5],  # top 5 untuk widget
        "contract_expiring_count": len(expiring),
        "inventory": inv_summary,
    }


async def _find_expiring_contracts(days_ahead: int = 60) -> List[Dict[str, Any]]:
    """Return employees dgn status OJT/Kontrak yg status_end_date jatuh dalam N hari (termasuk sudah lewat)."""
    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=days_ahead)
    cursor = db.employees.find({
        "active": True,
        "employment_status": {"$in": ["ojt", "kontrak_6", "kontrak_12"]},
        "status_end_date": {"$ne": None, "$exists": True},
    }, {"_id": 0}).sort("status_end_date", 1)
    items = await cursor.to_list(length=500)
    result = []
    for e in items:
        end_str = e.get("status_end_date")
        if not end_str:
            continue
        try:
            end_date = datetime.strptime(end_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if end_date > cutoff:
            continue
        days_left = (end_date - today).days
        result.append({
            "id": e.get("id"),
            "nik": e.get("nik"),
            "name": e.get("name"),
            "position": e.get("position"),
            "department": e.get("department"),
            "employment_status": e.get("employment_status"),
            "status_start_date": e.get("status_start_date"),
            "status_end_date": end_str,
            "days_left": days_left,
            "expired": days_left < 0,
        })
    return result


@api_router.get("/contracts/expiring")
async def contracts_expiring(days: int = 60, user: dict = Depends(require_super_admin)):
    """List karyawan OJT/Kontrak yang berakhir dalam N hari (default 60)."""
    items = await _find_expiring_contracts(days)
    return {"days": days, "count": len(items), "items": items}


# ---------------- Config ----------------
@api_router.get("/config/constants")
async def config_constants(user: dict = Depends(require_super_admin)):
    return {
        "ptkp_table": CONFIG["ptkp_table"],
        "pph21_brackets": [{"limit": b[0], "rate": b[1]} for b in CONFIG["pph21_brackets"]],
        "bpjs": {
            "kesehatan_employee": CONFIG["bpjs_kesehatan_employee"],
            "kesehatan_employer": CONFIG["bpjs_kesehatan_employer"],
            "kesehatan_max_base": CONFIG["bpjs_kesehatan_max_base"],
            "jht_employee": CONFIG["jht_employee"],
            "jht_employer": CONFIG["jht_employer"],
            "jp_employee": CONFIG["jp_employee"],
            "jp_employer": CONFIG["jp_employer"],
            "jp_max_base": CONFIG["jp_max_base"],
            "jkk_employer": CONFIG["jkk_employer"],
            "jkm_employer": CONFIG["jkm_employer"],
        },
        "biaya_jabatan_rate": CONFIG["biaya_jabatan_rate"],
        "biaya_jabatan_max_year": CONFIG["biaya_jabatan_max_year"],
        "standard_workdays": CONFIG["standard_workdays"],
        "overtime_multiplier": CONFIG["overtime_multiplier"],
    }


class ConfigUpdateIn(BaseModel):
    ptkp_table: Optional[Dict[str, float]] = None
    pph21_brackets: Optional[List[List[Any]]] = None  # [[limit_or_null, rate], ...]
    bpjs_kesehatan_employee: Optional[float] = None
    bpjs_kesehatan_employer: Optional[float] = None
    bpjs_kesehatan_max_base: Optional[float] = None
    jht_employee: Optional[float] = None
    jht_employer: Optional[float] = None
    jp_employee: Optional[float] = None
    jp_employer: Optional[float] = None
    jp_max_base: Optional[float] = None
    jkk_employer: Optional[float] = None
    jkm_employer: Optional[float] = None
    biaya_jabatan_rate: Optional[float] = None
    biaya_jabatan_max_year: Optional[float] = None
    standard_workdays: Optional[float] = None
    overtime_multiplier: Optional[float] = None


@api_router.put("/config/constants")
async def update_config(payload: ConfigUpdateIn, user: dict = Depends(require_super_admin)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        return {"updated": 0}
    # Normalize pph21_brackets nulls
    if "pph21_brackets" in update:
        normalized = []
        for row in update["pph21_brackets"]:
            limit = row[0] if (row[0] is not None and row[0] != "") else None
            rate = float(row[1])
            normalized.append([float(limit) if limit is not None else None, rate])
        update["pph21_brackets"] = normalized
    CONFIG.update(update)
    await db.app_config.update_one(
        {"id": "payroll_config"},
        {"$set": {**update, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"updated": len(update), "config": update}


async def _load_config_from_db():
    rec = await db.app_config.find_one({"id": "payroll_config"}, {"_id": 0})
    if rec:
        for k in list(CONFIG.keys()):
            if k in rec and rec[k] is not None:
                CONFIG[k] = rec[k]
        logger.info("Loaded payroll config overrides from DB")


# ---------------- THR (Tunjangan Hari Raya) ----------------
class THRRunIn(BaseModel):
    period: str  # YYYY-MM (month THR is paid)


def _months_between(start_iso: str, end_dt: datetime) -> float:
    try:
        sd = datetime.fromisoformat(start_iso)
    except Exception:
        try:
            sd = datetime.strptime(start_iso, "%Y-%m-%d")
        except Exception:
            return 12.0
    delta = (end_dt.year - sd.year) * 12 + (end_dt.month - sd.month)
    if end_dt.day < sd.day:
        delta -= 1
    return max(0.0, float(delta))


def _calculate_thr(employee: Dict[str, Any], reference_dt: datetime) -> Dict[str, Any]:
    """1x (basic + fixed_allowance) for tenure >= 12 months; proportional for < 12 months (min 1 month)."""
    basic = float(employee.get("basic_salary", 0))
    allowance = float(employee.get("fixed_allowance", 0))
    monthly_base = basic + allowance
    months = _months_between(employee.get("join_date", "2020-01-01"), reference_dt)
    if months < 1:
        thr_gross = 0.0
        formula = "Belum berhak (masa kerja < 1 bulan)"
    elif months >= 12:
        thr_gross = monthly_base
        formula = "1x Gaji + Tunjangan Tetap"
    else:
        thr_gross = monthly_base * (months / 12.0)
        formula = f"({months:.0f}/12) x Gaji + Tunjangan Tetap"
    # PPh 21 on THR using progressive bracket on isolated annual amount per Indonesian practice (simplified)
    # Treat THR as standalone annual income for tax (jumlah neto disetahunkan)
    # For simplicity use 5% bracket; for higher PKP brackets, fall back to compute_pph21_annual on (annual_gross + thr) - (annual_gross alone)
    annual_no_thr = monthly_base * 12
    ptkp = CONFIG["ptkp_table"].get(employee.get("ptkp_status", "TK/0"), 54_000_000)
    pkp_no_thr = max(0, annual_no_thr - ptkp)
    pkp_with_thr = max(0, annual_no_thr + thr_gross - ptkp)
    pph_no_thr = compute_pph21_annual(pkp_no_thr)
    pph_with_thr = compute_pph21_annual(pkp_with_thr)
    pph21_thr = max(0.0, pph_with_thr - pph_no_thr)
    if not employee.get("has_npwp", True):
        pph21_thr *= 1.2
    net = thr_gross - pph21_thr
    return {
        "months_of_service": months,
        "monthly_base": round(monthly_base, 2),
        "thr_gross": round(thr_gross, 2),
        "pph21_thr": round(pph21_thr, 2),
        "thr_net": round(net, 2),
        "formula": formula,
    }


@api_router.post("/payroll/thr/preview")
async def thr_preview(payload: THRRunIn, user: dict = Depends(require_super_admin)):
    try:
        ref = datetime.strptime(payload.period + "-01", "%Y-%m-%d")
    except Exception:
        raise HTTPException(status_code=400, detail="Periode harus format YYYY-MM")
    employees = await db.employees.find({"active": True}, {"_id": 0}).to_list(length=2000)
    items = []
    total_gross = 0.0
    total_net = 0.0
    total_pph = 0.0
    for emp in employees:
        thr = _calculate_thr(emp, ref)
        items.append({
            "employee_id": emp["id"],
            "nik": emp["nik"],
            "name": emp["name"],
            "position": emp["position"],
            "department": emp["department"],
            "ptkp_status": emp.get("ptkp_status", "TK/0"),
            **thr,
        })
        total_gross += thr["thr_gross"]
        total_net += thr["thr_net"]
        total_pph += thr["pph21_thr"]
    return {
        "period": payload.period,
        "items": items,
        "totals": {
            "gross": round(total_gross, 2),
            "net": round(total_net, 2),
            "pph21": round(total_pph, 2),
            "count": len(items),
        },
    }


@api_router.post("/payroll/thr/run")
async def thr_run(payload: THRRunIn, user: dict = Depends(require_super_admin)):
    try:
        ref = datetime.strptime(payload.period + "-01", "%Y-%m-%d")
    except Exception:
        raise HTTPException(status_code=400, detail="Periode harus format YYYY-MM")
    employees = await db.employees.find({"active": True}, {"_id": 0}).to_list(length=2000)
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    docs = []
    total_gross = 0.0
    total_net = 0.0
    total_pph = 0.0
    for emp in employees:
        thr = _calculate_thr(emp, ref)
        docs.append({
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "period": payload.period,
            "employee_id": emp["id"],
            "nik": emp["nik"],
            "name": emp["name"],
            "position": emp["position"],
            "department": emp["department"],
            "ptkp_status": emp.get("ptkp_status", "TK/0"),
            "bank_name": emp.get("bank_name"),
            "bank_account": emp.get("bank_account"),
            "created_at": now,
            **thr,
        })
        total_gross += thr["thr_gross"]
        total_net += thr["thr_net"]
        total_pph += thr["pph21_thr"]
    await db.thr_runs.delete_many({"period": payload.period})
    await db.thr_slips.delete_many({"period": payload.period})
    if docs:
        await db.thr_slips.insert_many(docs)
    rec = {
        "id": run_id,
        "period": payload.period,
        "created_at": now,
        "employee_count": len(docs),
        "total_gross": round(total_gross, 2),
        "total_net": round(total_net, 2),
        "total_pph21": round(total_pph, 2),
    }
    await db.thr_runs.insert_one(rec)
    rec.pop("_id", None)
    return rec


@api_router.get("/payroll/thr/runs")
async def list_thr_runs(user: dict = Depends(require_super_admin)):
    return await db.thr_runs.find({}, {"_id": 0}).sort("period", -1).to_list(length=200)


@api_router.get("/payroll/thr/{period}/slips")
async def thr_slips(period: str, user: dict = Depends(require_super_admin)):
    rows = await db.thr_slips.find({"period": period}, {"_id": 0}).sort("name", 1).to_list(length=2000)
    if not rows:
        raise HTTPException(status_code=404, detail="THR untuk periode ini belum dijalankan")
    return rows


# ---------------- Email Payslip ----------------
def _payslip_html(slip: Dict[str, Any]) -> str:
    e, d = slip["earnings"], slip["deductions"]
    company = os.environ.get("COMPANY_NAME", "Payroll Indonesia")
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #18181b;">
      <tr><td style="padding: 24px 0; border-bottom: 2px solid #18181b;">
        <h2 style="margin:0; font-size:20px; letter-spacing:-0.5px;">SLIP GAJI · {slip['period']}</h2>
        <div style="font-size:12px; color:#71717a; margin-top:4px;">{company} · HR Department</div>
      </td></tr>
      <tr><td style="padding: 20px 0;">
        Halo <strong>{slip['name']}</strong>,<br/><br/>
        Berikut adalah ringkasan slip gaji Anda untuk periode <strong>{slip['period']}</strong>.
        Slip lengkap dengan rincian pajak terlampir sebagai PDF.
      </td></tr>
      <tr><td>
        <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse: collapse; font-size: 13px;">
          <tr style="background:#f4f4f5;"><th align="left" style="border-bottom:1px solid #e4e4e7;">PENDAPATAN</th><th align="right" style="border-bottom:1px solid #e4e4e7;">Rp</th></tr>
          <tr><td>Gaji Pokok</td><td align="right" style="font-family:monospace;">{_format_idr(e['basic_salary'])}</td></tr>
          <tr><td>Tunjangan</td><td align="right" style="font-family:monospace;">{_format_idr(e['fixed_allowance'])}</td></tr>
          <tr><td>Lembur</td><td align="right" style="font-family:monospace;">{_format_idr(e['overtime'])}</td></tr>
          <tr><td>Bonus</td><td align="right" style="font-family:monospace;">{_format_idr(e['bonus'])}</td></tr>
          <tr style="font-weight:bold; border-top:1px solid #a1a1aa;"><td>Total Bruto</td><td align="right" style="font-family:monospace;">{_format_idr(e['gross'])}</td></tr>
          <tr style="background:#f4f4f5;"><th align="left" style="border-bottom:1px solid #e4e4e7;">POTONGAN</th><th align="right" style="border-bottom:1px solid #e4e4e7;">Rp</th></tr>
          <tr><td>BPJS Karyawan</td><td align="right" style="font-family:monospace;">{_format_idr(d['bpjs_kesehatan_employee'] + d['jht_employee'] + d['jp_employee'])}</td></tr>
          <tr><td>PPh 21</td><td align="right" style="font-family:monospace;">{_format_idr(d['pph21'])}</td></tr>
          <tr><td>Lain-lain</td><td align="right" style="font-family:monospace;">{_format_idr(d['other_deduction'])}</td></tr>
          <tr style="font-weight:bold; border-top:1px solid #a1a1aa;"><td>Total Potongan</td><td align="right" style="font-family:monospace;">{_format_idr(d['total'])}</td></tr>
        </table>
      </td></tr>
      <tr><td style="padding:16px; background:#18181b; color:white; margin-top:12px;">
        <table width="100%"><tr>
          <td style="font-size:11px; color:#a1a1aa; text-transform:uppercase; letter-spacing:1px;">Take Home Pay</td>
          <td align="right" style="font-family:monospace; font-size:22px; font-weight:bold;">{_format_idr(slip['net_salary'])}</td>
        </tr></table>
      </td></tr>
      <tr><td style="padding: 16px 0; font-size:11px; color:#71717a;">
        Email otomatis dari sistem payroll. Jangan dibalas. Untuk pertanyaan hubungi HR.
      </td></tr>
    </table>
    """


def _send_email_via_resend(to_email: str, subject: str, html: str, pdf_bytes: bytes, pdf_filename: str) -> Dict[str, Any]:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
    if not api_key:
        return {"status": "mocked", "to": to_email, "subject": subject, "message": "RESEND_API_KEY belum diatur — email tidak dikirim (mode mock)."}
    try:
        import resend
        import base64 as b64
        resend.api_key = api_key
        params = {
            "from": sender,
            "to": [to_email],
            "subject": subject,
            "html": html,
            "attachments": [{
                "filename": pdf_filename,
                "content": b64.b64encode(pdf_bytes).decode("utf-8"),
            }],
        }
        result = resend.Emails.send(params)
        return {"status": "sent", "to": to_email, "email_id": result.get("id")}
    except Exception as ex:
        return {"status": "failed", "to": to_email, "error": str(ex)[:200]}


def _send_simple_email(to_email: str, subject: str, html: str) -> Dict[str, Any]:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
    if not api_key or not to_email:
        return {"status": "mocked", "to": to_email}
    try:
        import resend
        resend.api_key = api_key
        result = resend.Emails.send({"from": sender, "to": [to_email], "subject": subject, "html": html})
        return {"status": "sent", "to": to_email, "email_id": result.get("id")}
    except Exception as ex:
        return {"status": "failed", "to": to_email, "error": str(ex)[:200]}


@api_router.post("/payroll/payslip/{slip_id}/email")
async def email_single_payslip(slip_id: str, user: dict = Depends(require_super_admin)):
    slip = await db.payslips.find_one({"id": slip_id}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Slip tidak ditemukan")
    emp = await db.employees.find_one({"id": slip["employee_id"]}, {"_id": 0})
    if not emp or not emp.get("email"):
        raise HTTPException(status_code=400, detail="Karyawan tidak memiliki email")

    html = _payslip_html(slip)
    pdf = _build_payslip_pdf(slip)
    subject = f"Slip Gaji {slip['period']} - {emp['name']}"
    fname = f"slip-{slip['period']}-{slip['nik']}.pdf"
    result = await asyncio.to_thread(_send_email_via_resend, emp["email"], subject, html, pdf, fname)
    await db.email_logs.insert_one({
        "id": str(uuid.uuid4()),
        "slip_id": slip_id,
        "period": slip["period"],
        "employee_id": emp["id"],
        "email": emp["email"],
        "sent_at": datetime.now(timezone.utc).isoformat(),
        **result,
    })
    return result


@api_router.post("/payroll/runs/{period}/email-all")
async def email_all_payslips(period: str, user: dict = Depends(require_super_admin)):
    slips = await db.payslips.find({"period": period}, {"_id": 0}).to_list(length=2000)
    if not slips:
        raise HTTPException(status_code=404, detail="Tidak ada slip untuk periode ini")
    employees = await db.employees.find({}, {"_id": 0}).to_list(length=5000)
    emp_by_id = {e["id"]: e for e in employees}

    results = {"sent": 0, "mocked": 0, "failed": 0, "skipped_no_email": 0, "details": []}
    for slip in slips:
        emp = emp_by_id.get(slip["employee_id"])
        if not emp or not emp.get("email"):
            results["skipped_no_email"] += 1
            results["details"].append({"name": slip["name"], "status": "skipped", "reason": "no email"})
            continue
        html = _payslip_html(slip)
        pdf = _build_payslip_pdf(slip)
        fname = f"slip-{period}-{slip['nik']}.pdf"
        subj = f"Slip Gaji {period} - {emp['name']}"
        res = await asyncio.to_thread(_send_email_via_resend, emp["email"], subj, html, pdf, fname)
        await db.email_logs.insert_one({
            "id": str(uuid.uuid4()),
            "slip_id": slip["id"],
            "period": period,
            "employee_id": emp["id"],
            "email": emp["email"],
            "sent_at": datetime.now(timezone.utc).isoformat(),
            **res,
        })
        status = res.get("status", "failed")
        if status == "sent":
            results["sent"] += 1
        elif status == "mocked":
            results["mocked"] += 1
        else:
            results["failed"] += 1
        results["details"].append({"name": slip["name"], "email": emp["email"], "status": status})
    return results


# ---------------- Bank Transfer Export ----------------
def _format_bank_export(slips: List[Dict[str, Any]], emp_by_id: Dict[str, Dict[str, Any]], fmt: str, period: str) -> tuple:
    """Returns (content_bytes, filename, mimetype) for given format."""
    rows = []
    for s in slips:
        emp = emp_by_id.get(s["employee_id"], {})
        # Gunakan bank_account_holder bila diisi (kasus rekening atas nama istri/orangtua), fallback ke nama karyawan
        recipient_name = emp.get("bank_account_holder") or s["name"]
        rows.append({
            "nik": s["nik"],
            "name": recipient_name,
            "bank": emp.get("bank_name") or "",
            "account": emp.get("bank_account") or "",
            "amount": round(float(s["net_salary"])),
            "note": f"Gaji {period}",
        })

    out = io.StringIO()
    if fmt == "bca":
        # Format KlikBCA Business sederhana: SourceAcc|Date|DestAcc|Amount|Reference
        out.write("ACCOUNT_NUMBER|DATE|DESTINATION_ACCOUNT|AMOUNT|REFERENCE\n")
        for r in rows:
            out.write(f"SENDER|{period}-25|{r['account']}|{r['amount']}|{r['note']}\n")
        filename = f"bca-payroll-{period}.txt"
        mime = "text/plain"
    elif fmt == "mandiri":
        # Mandiri Cash Management CSV
        out.write("Nama Penerima,Bank Penerima,Nomor Rekening,Jumlah,Berita\n")
        for r in rows:
            out.write(f'"{r["name"]}","{r["bank"]}","{r["account"]}",{r["amount"]},"{r["note"]}"\n')
        filename = f"mandiri-payroll-{period}.csv"
        mime = "text/csv"
    elif fmt == "bni":
        out.write("NomorRekening,NamaPenerima,Bank,Jumlah,Keterangan\n")
        for r in rows:
            out.write(f'"{r["account"]}","{r["name"]}","{r["bank"]}",{r["amount"]},"{r["note"]}"\n')
        filename = f"bni-payroll-{period}.csv"
        mime = "text/csv"
    elif fmt == "bri":
        out.write("NoRekening;NamaPenerima;BankPenerima;Nominal;Berita\n")
        for r in rows:
            out.write(f'{r["account"]};{r["name"]};{r["bank"]};{r["amount"]};{r["note"]}\n')
        filename = f"bri-payroll-{period}.csv"
        mime = "text/csv"
    else:  # generic
        out.write("NIK,Nama,Bank,No Rekening,Jumlah,Keterangan\n")
        for r in rows:
            out.write(f'"{r["nik"]}","{r["name"]}","{r["bank"]}","{r["account"]}",{r["amount"]},"{r["note"]}"\n')
        filename = f"payroll-{period}.csv"
        mime = "text/csv"
    return out.getvalue().encode("utf-8"), filename, mime


@api_router.get("/payroll/runs/{period}/bank-export")
async def bank_export(period: str, format: str = "generic", user: dict = Depends(require_super_admin)):
    fmt = format.lower()
    if fmt not in {"generic", "bca", "mandiri", "bni", "bri"}:
        raise HTTPException(status_code=400, detail="Format tidak valid")
    slips = await db.payslips.find({"period": period}, {"_id": 0}).to_list(length=2000)
    if not slips:
        raise HTTPException(status_code=404, detail="Periode tidak ditemukan")
    employees = await db.employees.find({}, {"_id": 0}).to_list(length=5000)
    emp_by_id = {e["id"]: e for e in employees}
    content, filename, mime = _format_bank_export(slips, emp_by_id, fmt, period)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------- Database Backup & Restore (Admin) ----------------
BACKUP_COLLECTIONS = [
    "users",
    "employees",
    "payslips",
    "payroll_runs",
    "thr_slips",
    "thr_runs",
    "attendance_imports",
    "app_config",
    "email_logs",
    "portal_reset_tokens",
    "leave_requests",
]


def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


@api_router.get("/admin/export-database")
async def export_database(user: dict = Depends(require_super_admin)):
    """Download a full JSON backup of all collections (admin only)."""
    import json as _json

    snapshot: Dict[str, Any] = {
        "_meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exported_by": user.get("email"),
            "db_name": os.environ.get("DB_NAME"),
            "version": 1,
        }
    }

    for col_name in BACKUP_COLLECTIONS:
        docs = await db[col_name].find({}, {"_id": 0}).to_list(length=100000)
        snapshot[col_name] = docs

    content = _json.dumps(snapshot, default=_json_default, ensure_ascii=False, indent=2).encode("utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"payroll-backup-{stamp}.json"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.post("/admin/import-database")
async def import_database(
    file: UploadFile = File(...),
    mode: str = "merge",  # 'replace' or 'merge' (default: safer 'merge')
    user: dict = Depends(require_super_admin),
):
    """Restore database from a JSON backup created via export-database.
    mode='replace': drop existing data in each collection then insert from backup.
    mode='merge': upsert by `id` field (keeps current admin and non-backed-up records).
    """
    import json as _json

    if mode not in {"replace", "merge"}:
        raise HTTPException(status_code=400, detail="mode harus 'replace' atau 'merge'")

    raw = await file.read()
    try:
        snapshot = _json.loads(raw.decode("utf-8-sig"))
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"File JSON tidak valid: {ex}")

    if not isinstance(snapshot, dict) or "_meta" not in snapshot:
        raise HTTPException(status_code=400, detail="Format backup tidak dikenali")

    summary: Dict[str, Any] = {"mode": mode, "restored": {}, "errors": []}

    for col_name in BACKUP_COLLECTIONS:
        docs = snapshot.get(col_name) or []
        if not isinstance(docs, list):
            summary["errors"].append(f"{col_name}: bukan list, dilewati")
            continue
        try:
            if mode == "replace":
                await db[col_name].delete_many({})
                if docs:
                    await db[col_name].insert_many(docs)
            else:  # merge
                for d in docs:
                    if "id" in d:
                        await db[col_name].update_one({"id": d["id"]}, {"$set": d}, upsert=True)
                    else:
                        await db[col_name].insert_one(d)
            summary["restored"][col_name] = len(docs)
        except Exception as ex:
            summary["errors"].append(f"{col_name}: {str(ex)[:200]}")

    # Reload config in memory
    await _load_config_from_db()

    return summary


# ---------------- WhatsApp via Fonnte ----------------
def _normalize_phone_id(phone: str) -> Optional[str]:
    """Normalize Indonesian phone to '62xxx' format. Returns None if invalid."""
    if not phone:
        return None
    p = "".join(c for c in str(phone) if c.isdigit())
    if not p:
        return None
    if p.startswith("0"):
        p = "62" + p[1:]
    elif p.startswith("62"):
        pass
    elif p.startswith("8"):
        p = "62" + p
    if len(p) < 10 or len(p) > 15:
        return None
    return p


def _whatsapp_slip_message(slip: Dict[str, Any], employee: Dict[str, Any]) -> str:
    company = os.environ.get("COMPANY_NAME", "Payroll Indonesia")
    portal = (os.environ.get("PUBLIC_APP_URL", "").rstrip("/")) + "/portal/login"
    take_home = f"{int(round(slip['net_salary'])):,}".replace(",", ".")
    gross = f"{int(round(slip['earnings']['gross'])):,}".replace(",", ".")
    pph = f"{int(round(slip['deductions']['pph21'])):,}".replace(",", ".")
    return (
        f"Halo {employee['name']},\n\n"
        f"Slip gaji periode *{slip['period']}* telah tersedia.\n\n"
        f"💰 Take Home: Rp {take_home}\n"
        f"📊 Bruto: Rp {gross}\n"
        f"🧾 PPh 21: Rp {pph}\n\n"
        f"Lihat slip lengkap di portal:\n{portal}\n"
        f"(Email: {employee.get('email') or '-'}, NIK: {employee['nik']})\n\n"
        f"— {company}"
    )


async def _send_whatsapp(phone: str, message: str) -> Dict[str, Any]:
    """Send a WhatsApp message via Fonnte. Returns status dict."""
    import httpx

    target = _normalize_phone_id(phone)
    if not target:
        return {"status": "failed", "phone": phone, "reason": "phone_invalid"}

    token = os.environ.get("FONNTE_TOKEN", "").strip()
    if not token:
        logger.info(f"[MOCK WA] to {target}: {message[:60]}...")
        return {"status": "mocked", "phone": target, "reason": "no_token"}

    base_url = os.environ.get("FONNTE_BASE_URL", "https://api.fonnte.com").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{base_url}/send",
                data={"target": target, "message": message, "countryCode": "62"},
                headers={"Authorization": token},
            )
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw": resp.text}
        if resp.status_code >= 400 or payload.get("status") is False:
            return {
                "status": "failed",
                "phone": target,
                "reason": payload.get("reason") or f"http_{resp.status_code}",
            }
        return {"status": "sent", "phone": target, "fonnte_id": payload.get("id")}
    except Exception as ex:
        logger.error(f"Fonnte send error: {ex}")
        return {"status": "failed", "phone": phone, "reason": str(ex)[:200]}


@api_router.post("/payroll/payslip/{slip_id}/whatsapp")
async def whatsapp_single_payslip(slip_id: str, user: dict = Depends(require_super_admin)):
    slip = await db.payslips.find_one({"id": slip_id}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Slip tidak ditemukan")
    emp = await db.employees.find_one({"id": slip["employee_id"]}, {"_id": 0})
    if not emp or not emp.get("phone"):
        raise HTTPException(status_code=400, detail="Karyawan tidak memiliki nomor WhatsApp")

    msg = _whatsapp_slip_message(slip, emp)
    res = await _send_whatsapp(emp["phone"], msg)
    await db.whatsapp_logs.insert_one({
        "id": str(uuid.uuid4()),
        "slip_id": slip_id,
        "period": slip["period"],
        "employee_id": emp["id"],
        "phone": emp["phone"],
        "sent_at": datetime.now(timezone.utc).isoformat(),
        **res,
    })
    return res


@api_router.post("/payroll/runs/{period}/whatsapp-all")
async def whatsapp_all_payslips(period: str, user: dict = Depends(require_super_admin)):
    slips = await db.payslips.find({"period": period}, {"_id": 0}).to_list(length=2000)
    if not slips:
        raise HTTPException(status_code=404, detail="Tidak ada slip untuk periode ini")
    employees = await db.employees.find({}, {"_id": 0}).to_list(length=5000)
    emp_by_id = {e["id"]: e for e in employees}

    results = {"sent": 0, "mocked": 0, "failed": 0, "skipped_no_phone": 0, "details": []}
    for slip in slips:
        emp = emp_by_id.get(slip["employee_id"])
        if not emp or not emp.get("phone"):
            results["skipped_no_phone"] += 1
            results["details"].append({"name": slip["name"], "status": "skipped", "reason": "no phone"})
            continue
        msg = _whatsapp_slip_message(slip, emp)
        res = await _send_whatsapp(emp["phone"], msg)
        await db.whatsapp_logs.insert_one({
            "id": str(uuid.uuid4()),
            "slip_id": slip["id"],
            "period": period,
            "employee_id": emp["id"],
            "phone": emp["phone"],
            "sent_at": datetime.now(timezone.utc).isoformat(),
            **res,
        })
        s = res.get("status", "failed")
        if s == "sent":
            results["sent"] += 1
        elif s == "mocked":
            results["mocked"] += 1
        else:
            results["failed"] += 1
        results["details"].append({
            "name": slip["name"], "phone": emp.get("phone"),
            "status": s, "reason": res.get("reason"),
        })
        await asyncio.sleep(0.3)  # gentle pacing for Fonnte free plan
    return results


@api_router.get("/admin/whatsapp/status")
async def whatsapp_status(user: dict = Depends(require_super_admin)):
    has_token = bool(os.environ.get("FONNTE_TOKEN", "").strip())
    return {
        "configured": has_token,
        "provider": "Fonnte",
        "mode": "live" if has_token else "mock",
    }


# ---------------- Leave & Permission Module ----------------
LEAVE_TYPES = {"terlambat", "pulang_awal", "tidak_masuk", "sakit", "lembur"}
LEAVE_TYPE_LABELS = {
    "terlambat": "Izin Datang Terlambat",
    "pulang_awal": "Izin Pulang Awal",
    "tidak_masuk": "Izin Tidak Masuk",
    "sakit": "Izin Sakit",
    "lembur": "Izin Lembur",
}
MAX_ATTACHMENT_SIZE = 2 * 1024 * 1024  # 2 MB
ALLOWED_ATTACHMENT_MIME = {"application/pdf", "image/jpeg", "image/jpg", "image/png"}


def _leave_view(doc: dict, include_attachment_meta: bool = True) -> dict:
    out = {
        "id": doc["id"],
        "employee_id": doc["employee_id"],
        "employee_name": doc.get("employee_name"),
        "employee_nik": doc.get("employee_nik"),
        "department": doc.get("department"),
        "type": doc["type"],
        "type_label": LEAVE_TYPE_LABELS.get(doc["type"], doc["type"]),
        "date_start": doc["date_start"],
        "date_end": doc["date_end"],
        "time_minutes": doc.get("time_minutes"),
        "time_start": doc.get("time_start"),
        "time_end": doc.get("time_end"),
        "reason": doc.get("reason", ""),
        "status": doc.get("status", "pending"),
        "hr_note": doc.get("hr_note"),
        "submitted_at": doc.get("submitted_at"),
        "reviewed_at": doc.get("reviewed_at"),
        "reviewed_by": doc.get("reviewed_by"),
    }
    if include_attachment_meta and doc.get("attachment"):
        att = doc["attachment"]
        out["attachment"] = {
            "filename": att.get("filename"),
            "mime": att.get("mime"),
            "size": att.get("size"),
        }
    else:
        out["attachment"] = None
    return out


@api_router.post("/portal/leave")
async def portal_leave_create(
    type: str = Form(...),
    date_start: str = Form(...),
    date_end: Optional[str] = Form(None),
    time_minutes: Optional[int] = Form(None),
    time_start: Optional[str] = Form(None),
    time_end: Optional[str] = Form(None),
    reason: str = Form(""),
    file: Optional[UploadFile] = File(None),
    emp: dict = Depends(get_current_employee),
):
    if type not in LEAVE_TYPES:
        raise HTTPException(status_code=400, detail="Jenis izin tidak valid")
    if not date_start:
        raise HTTPException(status_code=400, detail="Tanggal wajib diisi")
    end = date_end or date_start
    if end < date_start:
        raise HTTPException(status_code=400, detail="Tanggal akhir tidak boleh sebelum tanggal mulai")

    if type == "terlambat":
        if not time_minutes or time_minutes < 5:
            raise HTTPException(status_code=400, detail="Durasi minimal 5 menit")
        end = date_start  # single day

    if type == "pulang_awal":
        # Karyawan input jam pulang; sistem hitung berapa menit lebih awal dari jam kerja normal (17:00)
        if not time_end:
            raise HTTPException(status_code=400, detail="Jam pulang wajib diisi")
        try:
            eh, em = [int(x) for x in time_end.split(":")[:2]]
            leave_minute = eh * 60 + em
            standard_end = 17 * 60  # 17:00 default
            diff = standard_end - leave_minute
            if diff < 5:
                raise HTTPException(status_code=400, detail="Jam pulang harus minimal 5 menit sebelum 17:00")
            time_minutes = diff
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Format jam tidak valid (gunakan HH:MM)")
        end = date_start  # single day

    if type == "lembur":
        if not time_start or not time_end:
            raise HTTPException(status_code=400, detail="Jam mulai dan jam selesai wajib diisi")
        try:
            sh, sm = [int(x) for x in time_start.split(":")[:2]]
            eh, em = [int(x) for x in time_end.split(":")[:2]]
            start_m = sh * 60 + sm
            end_m = eh * 60 + em
            if end_m <= start_m:
                # Allow next-day overtime (e.g. 22:00 → 02:00)
                end_m += 24 * 60
            duration = end_m - start_m
            if duration <= 0 or duration > 16 * 60:
                raise HTTPException(status_code=400, detail="Durasi lembur tidak valid (maks 16 jam)")
            time_minutes = duration
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Format jam tidak valid (gunakan HH:MM)")
        end = date_start  # single day

    attachment = None
    if file is not None and file.filename:
        content = await file.read()
        if len(content) > MAX_ATTACHMENT_SIZE:
            raise HTTPException(status_code=400, detail="Ukuran file maks 2MB")
        mime = (file.content_type or "").lower()
        if mime not in ALLOWED_ATTACHMENT_MIME:
            raise HTTPException(status_code=400, detail="Format file harus PDF/JPG/PNG")
        attachment = {
            "filename": file.filename,
            "mime": mime,
            "size": len(content),
            "data_base64": base64.b64encode(content).decode("ascii"),
        }

    if type == "sakit" and not attachment:
        # File upload optional sesuai konfigurasi (HR dapat meminta surat dokter saat review jika perlu)
        pass

    doc = {
        "id": str(uuid.uuid4()),
        "employee_id": emp["id"],
        "employee_name": emp.get("name"),
        "employee_nik": emp.get("nik"),
        "department": emp.get("department"),
        "type": type,
        "date_start": date_start,
        "date_end": end,
        "time_minutes": time_minutes if type in {"terlambat", "pulang_awal", "lembur"} else None,
        "time_start": time_start if type == "lembur" else None,
        "time_end": time_end if type in {"lembur", "pulang_awal"} else None,
        "reason": reason.strip(),
        "attachment": attachment,
        "status": "pending",
        "hr_note": None,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_at": None,
        "reviewed_by": None,
    }
    await db.leave_requests.insert_one(doc)

    # Notify HR via email
    try:
        hr_email = os.environ.get("ADMIN_EMAIL", "").strip()
        if hr_email:
            html = f"""
            <div style="font-family:Arial,sans-serif;max-width:560px">
              <h2 style="color:#002FA7;margin:0 0 8px">Pengajuan Izin Baru</h2>
              <p style="color:#444">Karyawan <b>{doc['employee_name']}</b> (NIK {doc['employee_nik']}) mengajukan izin.</p>
              <table style="border-collapse:collapse;width:100%;font-size:14px">
                <tr><td style="padding:6px 0;color:#666">Jenis</td><td><b>{LEAVE_TYPE_LABELS.get(doc['type'])}</b></td></tr>
                <tr><td style="padding:6px 0;color:#666">Tanggal</td><td>{doc['date_start']}{(' s/d ' + doc['date_end']) if doc['date_end'] != doc['date_start'] else ''}</td></tr>
                {('<tr><td style=padding:6px;color:#666>Jam</td><td>' + str(doc.get('time_start', '')) + ' - ' + str(doc.get('time_end', '')) + '</td></tr>') if doc.get('time_start') else ''}
                {('<tr><td style=padding:6px;color:#666>Durasi</td><td>' + str(doc['time_minutes']) + ' menit</td></tr>') if doc.get('time_minutes') else ''}
                <tr><td style="padding:6px 0;color:#666">Alasan</td><td>{doc['reason']}</td></tr>
              </table>
              <p style="margin-top:16px;color:#666;font-size:13px">Login ke Dashboard HR untuk meninjau pengajuan.</p>
            </div>
            """
            _send_simple_email(hr_email, f"[Payroll] Pengajuan Izin Baru — {doc['employee_name']}", html)
    except Exception as ex:
        logger.warning(f"Failed to notify HR for leave {doc['id']}: {ex}")

    return _leave_view(doc)


@api_router.get("/portal/leave")
async def portal_leave_list(emp: dict = Depends(get_current_employee)):
    items = await db.leave_requests.find({"employee_id": emp["id"]}, {"_id": 0, "attachment.data_base64": 0}).sort("submitted_at", -1).to_list(length=500)
    return [_leave_view(x) for x in items]


@api_router.delete("/portal/leave/{leave_id}")
async def portal_leave_cancel(leave_id: str, emp: dict = Depends(get_current_employee)):
    doc = await db.leave_requests.find_one({"id": leave_id, "employee_id": emp["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")
    if doc.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Pengajuan yang sudah diproses tidak dapat dibatalkan")
    await db.leave_requests.delete_one({"id": leave_id})
    return {"ok": True}


@api_router.get("/portal/leave/{leave_id}/attachment")
async def portal_leave_attachment(leave_id: str, emp: dict = Depends(get_current_employee)):
    doc = await db.leave_requests.find_one({"id": leave_id, "employee_id": emp["id"]})
    if not doc or not doc.get("attachment"):
        raise HTTPException(status_code=404, detail="Lampiran tidak ditemukan")
    att = doc["attachment"]
    data = base64.b64decode(att["data_base64"])
    return Response(
        content=data,
        media_type=att["mime"],
        headers={"Content-Disposition": f'inline; filename="{att["filename"]}"'},
    )


# ----- HR Admin endpoints -----
@api_router.get("/leave")
async def admin_leave_list(
    status: Optional[str] = None,
    type: Optional[str] = None,
    user: dict = Depends(require_leave_access),
):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if type:
        q["type"] = type
    items = await db.leave_requests.find(q, {"_id": 0, "attachment.data_base64": 0}).sort("submitted_at", -1).to_list(length=1000)
    return [_leave_view(x) for x in items]


@api_router.get("/leave/stats")
async def admin_leave_stats(user: dict = Depends(require_leave_access)):
    pending = await db.leave_requests.count_documents({"status": "pending"})
    approved = await db.leave_requests.count_documents({"status": "approved"})
    rejected = await db.leave_requests.count_documents({"status": "rejected"})
    return {"pending": pending, "approved": approved, "rejected": rejected, "total": pending + approved + rejected}


@api_router.get("/leave/{leave_id}")
async def admin_leave_detail(leave_id: str, user: dict = Depends(require_leave_access)):
    doc = await db.leave_requests.find_one({"id": leave_id}, {"_id": 0, "attachment.data_base64": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")
    return _leave_view(doc)


@api_router.get("/leave/{leave_id}/attachment")
async def admin_leave_attachment(leave_id: str, user: dict = Depends(require_leave_access)):
    doc = await db.leave_requests.find_one({"id": leave_id})
    if not doc or not doc.get("attachment"):
        raise HTTPException(status_code=404, detail="Lampiran tidak ditemukan")
    att = doc["attachment"]
    data = base64.b64decode(att["data_base64"])
    return Response(
        content=data,
        media_type=att["mime"],
        headers={"Content-Disposition": f'inline; filename="{att["filename"]}"'},
    )


@api_router.delete("/leave/{leave_id}")
async def admin_leave_delete(leave_id: str, user: dict = Depends(require_leave_access)):
    doc = await db.leave_requests.find_one({"id": leave_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")
    await db.leave_requests.delete_one({"id": leave_id})
    return {"ok": True}


class LeaveReviewIn(BaseModel):
    hr_note: Optional[str] = ""


@api_router.put("/leave/{leave_id}/approve")
async def admin_leave_approve(leave_id: str, payload: LeaveReviewIn, user: dict = Depends(require_leave_access)):
    doc = await db.leave_requests.find_one({"id": leave_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")
    await db.leave_requests.update_one(
        {"id": leave_id},
        {"$set": {
            "status": "approved",
            "hr_note": (payload.hr_note or "").strip(),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_by": user.get("email"),
        }},
    )
    updated = await db.leave_requests.find_one({"id": leave_id}, {"_id": 0, "attachment.data_base64": 0})
    _notify_employee_leave_status(updated, "approved")
    return _leave_view(updated)


@api_router.put("/leave/{leave_id}/reject")
async def admin_leave_reject(leave_id: str, payload: LeaveReviewIn, user: dict = Depends(require_leave_access)):
    doc = await db.leave_requests.find_one({"id": leave_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")
    if not (payload.hr_note or "").strip():
        raise HTTPException(status_code=400, detail="Alasan penolakan wajib diisi")
    await db.leave_requests.update_one(
        {"id": leave_id},
        {"$set": {
            "status": "rejected",
            "hr_note": payload.hr_note.strip(),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_by": user.get("email"),
        }},
    )
    updated = await db.leave_requests.find_one({"id": leave_id}, {"_id": 0, "attachment.data_base64": 0})
    _notify_employee_leave_status(updated, "rejected")
    return _leave_view(updated)


def _notify_employee_leave_status(leave_doc: dict, status: str):
    try:
        asyncio.create_task(_send_leave_status_email(leave_doc, status))
    except Exception as ex:
        logger.warning(f"Failed to schedule leave notif: {ex}")


async def _send_leave_status_email(leave_doc: dict, status: str):
    try:
        emp = await db.employees.find_one({"id": leave_doc["employee_id"]}, {"_id": 0, "email": 1, "name": 1})
        if not emp or not emp.get("email"):
            return
        label_status = "DISETUJUI" if status == "approved" else "DITOLAK"
        color = "#059669" if status == "approved" else "#dc2626"
        type_label = LEAVE_TYPE_LABELS.get(leave_doc.get("type"), leave_doc.get("type"))
        period = leave_doc["date_start"]
        if leave_doc.get("date_end") and leave_doc["date_end"] != leave_doc["date_start"]:
            period = f"{leave_doc['date_start']} s/d {leave_doc['date_end']}"
        note_html = ""
        if leave_doc.get("hr_note"):
            note_html = f'<p style="margin-top:12px;padding:10px;background:#f5f5f5;border-left:3px solid {color};font-size:13px"><b>Catatan HR:</b> {leave_doc["hr_note"]}</p>'
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:560px">
          <h2 style="color:{color};margin:0 0 8px">Pengajuan Izin {label_status}</h2>
          <p style="color:#444">Halo {emp.get('name', '')},</p>
          <p style="color:#444">Pengajuan izin Anda telah diproses dengan detail berikut:</p>
          <table style="border-collapse:collapse;width:100%;font-size:14px">
            <tr><td style="padding:6px 0;color:#666">Jenis</td><td><b>{type_label}</b></td></tr>
            <tr><td style="padding:6px 0;color:#666">Tanggal</td><td>{period}</td></tr>
            <tr><td style="padding:6px 0;color:#666">Status</td><td style="color:{color}"><b>{label_status}</b></td></tr>
          </table>
          {note_html}
          <p style="margin-top:16px;color:#666;font-size:13px">Terima kasih.</p>
        </div>
        """
        _send_simple_email(emp["email"], f"[Payroll] Pengajuan Izin {label_status}", html)
    except Exception as ex:
        logger.warning(f"Failed to send leave status email: {ex}")


# ----- Leave Monthly Report Export (Excel + PDF) -----
def _parse_month(period: str):
    """period format: YYYY-MM. Returns (start_date, end_date) as YYYY-MM-DD strings."""
    try:
        year, month = period.split("-")
        year, month = int(year), int(month)
        from calendar import monthrange
        last_day = monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}", year, month
    except Exception:
        raise HTTPException(status_code=400, detail="Format periode tidak valid (gunakan YYYY-MM)")


async def _fetch_monthly_leave(period: str):
    start, end, year, month = _parse_month(period)
    # Get leaves where the request date range overlaps the month
    items = await db.leave_requests.find(
        {"date_start": {"$lte": end}, "date_end": {"$gte": start}},
        {"_id": 0, "attachment.data_base64": 0},
    ).sort([("date_start", 1), ("employee_name", 1)]).to_list(length=5000)
    return items, start, end, year, month


@api_router.get("/leave/report/{period}/excel")
async def leave_report_excel(period: str, user: dict = Depends(require_leave_access)):
    items, start, end, year, month = await _fetch_monthly_leave(period)
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = f"Laporan {period}"

    # Title
    ws["A1"] = f"LAPORAN IZIN KARYAWAN — Periode {period}"
    ws["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor="002FA7")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells("A1:I1")
    ws.row_dimensions[1].height = 28

    ws["A2"] = f"Perusahaan: {os.environ.get('COMPANY_NAME', 'Payroll Indonesia')}"
    ws["A2"].font = Font(italic=True, size=10, color="666666")
    ws.merge_cells("A2:I2")

    # Header row
    headers = ["No", "NIK", "Nama", "Departemen", "Jenis Izin", "Tanggal Mulai", "Tanggal Selesai", "Durasi (menit)", "Alasan"]
    header_row = 4
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=header_row, column=col, value=h)
        c.font = Font(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor="27272A")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = Border(bottom=Side(style="thin", color="888888"))

    # Status column added at the end
    ws.cell(row=header_row, column=10, value="Status").font = Font(bold=True, color="FFFFFF", size=10)
    ws.cell(row=header_row, column=10).fill = PatternFill("solid", fgColor="27272A")
    ws.cell(row=header_row, column=10).alignment = Alignment(horizontal="center")
    ws.cell(row=header_row, column=11, value="Catatan HR").font = Font(bold=True, color="FFFFFF", size=10)
    ws.cell(row=header_row, column=11).fill = PatternFill("solid", fgColor="27272A")
    ws.cell(row=header_row, column=11).alignment = Alignment(horizontal="center")

    status_colors = {"pending": "FEF3C7", "approved": "D1FAE5", "rejected": "FEE2E2"}

    for idx, x in enumerate(items, start=1):
        row = header_row + idx
        ws.cell(row=row, column=1, value=idx).alignment = Alignment(horizontal="center")
        ws.cell(row=row, column=2, value=x.get("employee_nik") or "")
        ws.cell(row=row, column=3, value=x.get("employee_name") or "")
        ws.cell(row=row, column=4, value=x.get("department") or "")
        ws.cell(row=row, column=5, value=LEAVE_TYPE_LABELS.get(x.get("type"), x.get("type")))
        ws.cell(row=row, column=6, value=x.get("date_start"))
        ws.cell(row=row, column=7, value=x.get("date_end"))
        # Durasi cell: show detail based on type
        dur_text = ""
        if x.get("time_minutes"):
            if x.get("type") == "pulang_awal" and x.get("time_end"):
                dur_text = f"Pulang {x['time_end']} ({x['time_minutes']} menit lebih awal)"
            elif x.get("time_start") and x.get("time_end"):
                dur_text = f"{x['time_minutes']} menit ({x['time_start']}-{x['time_end']})"
            else:
                dur_text = f"{x['time_minutes']} menit"
        ws.cell(row=row, column=8, value=dur_text)
        ws.cell(row=row, column=9, value=x.get("reason") or "")
        status_cell = ws.cell(row=row, column=10, value=STATUS_LABEL_MAP.get(x.get("status"), x.get("status")))
        status_cell.fill = PatternFill("solid", fgColor=status_colors.get(x.get("status"), "FFFFFF"))
        status_cell.alignment = Alignment(horizontal="center")
        status_cell.font = Font(bold=True, size=9)
        ws.cell(row=row, column=11, value=x.get("hr_note") or "")

    # Summary at the bottom
    summary_row = header_row + len(items) + 2
    pending = sum(1 for x in items if x.get("status") == "pending")
    approved = sum(1 for x in items if x.get("status") == "approved")
    rejected = sum(1 for x in items if x.get("status") == "rejected")
    ws.cell(row=summary_row, column=1, value="RINGKASAN").font = Font(bold=True, size=11)
    ws.cell(row=summary_row + 1, column=1, value="Total Pengajuan")
    ws.cell(row=summary_row + 1, column=2, value=len(items)).font = Font(bold=True)
    ws.cell(row=summary_row + 2, column=1, value="Menunggu")
    ws.cell(row=summary_row + 2, column=2, value=pending)
    ws.cell(row=summary_row + 3, column=1, value="Disetujui")
    ws.cell(row=summary_row + 3, column=2, value=approved)
    ws.cell(row=summary_row + 4, column=1, value="Ditolak")
    ws.cell(row=summary_row + 4, column=2, value=rejected)

    # Column widths
    widths = [5, 14, 24, 18, 20, 14, 14, 12, 36, 12, 28]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="laporan-izin-{period}.xlsx"'},
    )


@api_router.get("/leave/report/{period}/pdf")
async def leave_report_pdf(period: str, user: dict = Depends(require_leave_access)):
    items, start, end, year, month = await _fetch_monthly_leave(period)
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=14, textColor=colors.HexColor("#002FA7"), spaceAfter=4)
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#666666"))
    cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8, leading=10)

    story = []
    story.append(Paragraph("LAPORAN IZIN KARYAWAN", title_style))
    story.append(Paragraph(f"Periode: <b>{period}</b> &nbsp;|&nbsp; Perusahaan: {os.environ.get('COMPANY_NAME', 'Payroll Indonesia')}", sub_style))
    story.append(Paragraph(f"Dicetak: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", sub_style))
    story.append(Spacer(1, 8))

    # Table
    table_data = [["No", "NIK", "Nama", "Departemen", "Jenis", "Tgl Mulai", "Tgl Selesai", "Durasi", "Status", "Alasan / Catatan HR"]]
    for idx, x in enumerate(items, start=1):
        note_parts = []
        if x.get("reason"):
            note_parts.append(x["reason"])
        if x.get("hr_note"):
            note_parts.append(f"<i>HR: {x['hr_note']}</i>")
        note_html = "<br/>".join(note_parts) or "-"
        dur_text = ""
        if x.get("time_minutes"):
            if x.get("type") == "pulang_awal" and x.get("time_end"):
                dur_text = f"Pulang {x['time_end']}<br/>{x['time_minutes']}m lebih awal"
            elif x.get("time_start") and x.get("time_end"):
                dur_text = f"{x['time_start']}-{x['time_end']}<br/>{x['time_minutes']}m"
            else:
                dur_text = f"{x['time_minutes']}m"
        table_data.append([
            str(idx),
            x.get("employee_nik") or "",
            Paragraph(x.get("employee_name") or "", cell_style),
            x.get("department") or "",
            LEAVE_TYPE_LABELS.get(x.get("type"), x.get("type")),
            x.get("date_start") or "",
            x.get("date_end") or "",
            Paragraph(dur_text, cell_style),
            STATUS_LABEL_MAP.get(x.get("status"), x.get("status")),
            Paragraph(note_html, cell_style),
        ])

    col_widths = [10 * mm, 20 * mm, 38 * mm, 28 * mm, 32 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 52 * mm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27272A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (5, 0), (8, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])
    # Color status column
    for ridx, x in enumerate(items, start=1):
        st = x.get("status")
        if st == "pending":
            style.add("BACKGROUND", (8, ridx), (8, ridx), colors.HexColor("#FEF3C7"))
        elif st == "approved":
            style.add("BACKGROUND", (8, ridx), (8, ridx), colors.HexColor("#D1FAE5"))
        elif st == "rejected":
            style.add("BACKGROUND", (8, ridx), (8, ridx), colors.HexColor("#FEE2E2"))
    table.setStyle(style)
    story.append(table)

    # Summary
    pending = sum(1 for x in items if x.get("status") == "pending")
    approved = sum(1 for x in items if x.get("status") == "approved")
    rejected = sum(1 for x in items if x.get("status") == "rejected")
    story.append(Spacer(1, 12))
    summary_data = [
        ["RINGKASAN", "", "", ""],
        ["Total Pengajuan", str(len(items)), "Menunggu", str(pending)],
        ["Disetujui", str(approved), "Ditolak", str(rejected)],
    ]
    summary_table = Table(summary_data, colWidths=[40 * mm, 25 * mm, 40 * mm, 25 * mm])
    summary_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#002FA7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("SPAN", (0, 0), (3, 0)),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(summary_table)

    # Signature
    story.append(Spacer(1, 30))
    sig_data = [
        ["Diketahui,", "", "Dibuat oleh,"],
        ["", "", ""],
        ["", "", ""],
        ["(_______________________)", "", "(_______________________)"],
        ["Direktur", "", "HR Department"],
    ]
    sig_table = Table(sig_data, colWidths=[80 * mm, 80 * mm, 80 * mm])
    sig_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(sig_table)

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="laporan-izin-{period}.pdf"'},
    )


STATUS_LABEL_MAP = {"pending": "Menunggu", "approved": "Disetujui", "rejected": "Ditolak"}


# ---------------- User Management (Super Admin only) ----------------
class UserCreateIn(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str  # "super_admin" or "hr_leave"


class UserUpdateIn(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None


def _user_view(u: dict) -> dict:
    role = u.get("role")
    if role == "admin":
        role = ROLE_SUPER_ADMIN
    return {
        "id": u["id"],
        "email": u["email"],
        "name": u.get("name", ""),
        "role": role,
        "created_at": u.get("created_at"),
    }


@api_router.get("/users")
async def list_users(user: dict = Depends(require_super_admin)):
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", 1).to_list(length=500)
    return [_user_view(u) for u in users]


@api_router.post("/users")
async def create_user(payload: UserCreateIn, user: dict = Depends(require_super_admin)):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Role tidak valid. Pilihan: {', '.join(sorted(VALID_ROLES))}")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password minimal 6 karakter")
    email = payload.email.lower()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")
    doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": payload.name.strip(),
        "password_hash": hash_password(payload.password),
        "role": payload.role,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    return _user_view(doc)


@api_router.put("/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdateIn, user: dict = Depends(require_super_admin)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    update: Dict[str, Any] = {}
    if payload.name is not None:
        update["name"] = payload.name.strip()
    if payload.role is not None:
        if payload.role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="Role tidak valid")
        # Prevent demoting the last super_admin
        if target.get("role") in {ROLE_SUPER_ADMIN, "admin"} and payload.role != ROLE_SUPER_ADMIN:
            super_admins = await db.users.count_documents({"role": {"$in": [ROLE_SUPER_ADMIN, "admin"]}})
            if super_admins <= 1:
                raise HTTPException(status_code=400, detail="Tidak dapat mengubah role: minimal harus ada 1 Super Admin")
        update["role"] = payload.role
    if payload.password:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password minimal 6 karakter")
        update["password_hash"] = hash_password(payload.password)
    if update:
        await db.users.update_one({"id": user_id}, {"$set": update})
    updated = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return _user_view(updated)


@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_super_admin)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="Tidak dapat menghapus akun sendiri")
    if target.get("role") in {ROLE_SUPER_ADMIN, "admin"}:
        super_admins = await db.users.count_documents({"role": {"$in": [ROLE_SUPER_ADMIN, "admin"]}})
        if super_admins <= 1:
            raise HTTPException(status_code=400, detail="Tidak dapat menghapus: minimal harus ada 1 Super Admin")
    await db.users.delete_one({"id": user_id})
    return {"ok": True}


# ---------------- Health ----------------
@api_router.get("/")
async def root():
    return {"message": "Payroll Indonesia API", "ok": True}


# ---------------- Startup ----------------
@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.employees.create_index("nik", unique=True)
    await db.payslips.create_index([("period", 1), ("employee_id", 1)])
    await db.payroll_runs.create_index("period", unique=True)
    await db.thr_runs.create_index("period", unique=True)
    await db.thr_slips.create_index([("period", 1), ("employee_id", 1)])
    await db.app_config.create_index("id", unique=True)
    await db.email_logs.create_index("sent_at")
    await db.leave_requests.create_index([("employee_id", 1), ("submitted_at", -1)])
    await db.leave_requests.create_index("status")

    # Load config overrides
    await _load_config_from_db()

    admin_email = os.environ.get("ADMIN_EMAIL", "admin@payroll.id").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": "Admin HR",
            "role": ROLE_SUPER_ADMIN,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Seeded super admin user: {admin_email}")
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}},
        )
        logger.info("Updated admin password from .env")

    # Migrate legacy "admin" role -> "super_admin"
    migrated = await db.users.update_many({"role": "admin"}, {"$set": {"role": ROLE_SUPER_ADMIN}})
    if migrated.modified_count:
        logger.info(f"Migrated {migrated.modified_count} legacy 'admin' role(s) to '{ROLE_SUPER_ADMIN}'")


@app.on_event("shutdown")
async def shutdown():
    client.close()


# ---------------- Inventory Module ----------------
class MaterialIn(BaseModel):
    name: str
    category: str  # flexy | sticker | tinta | lainnya
    unit: str  # meter | roll | liter | pcs
    current_stock: float = 0
    purchase_price: float = 0  # harga beli per unit
    min_stock: float = 0
    supplier_default: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True


class StockInIn(BaseModel):
    material_id: str
    quantity: float
    unit_price: float
    supplier: Optional[str] = None
    invoice_no: Optional[str] = None
    date: str  # ISO YYYY-MM-DD
    notes: Optional[str] = None


class WasteIn(BaseModel):
    material_id: str
    quantity: float
    reason: str  # rusak | rijek | kadaluarsa | lainnya
    date: str
    reported_by: Optional[str] = None
    notes: Optional[str] = None


MATERIAL_CATEGORIES = ["flexy", "sticker", "tinta", "lainnya"]
MATERIAL_UNITS = ["meter", "roll", "liter", "pcs"]
WASTE_REASONS = ["rusak", "rijek", "kadaluarsa", "lainnya"]


# ----- Materials CRUD -----
@api_router.get("/inventory/materials")
async def inv_list_materials(user: dict = Depends(require_super_admin)):
    cursor = db.materials.find({}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=2000)


@api_router.post("/inventory/materials")
async def inv_create_material(payload: MaterialIn, user: dict = Depends(require_super_admin)):
    if payload.category not in MATERIAL_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Kategori tidak valid")
    if payload.unit not in MATERIAL_UNITS:
        raise HTTPException(status_code=400, detail=f"Satuan tidak valid")
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["updated_at"] = doc["created_at"]
    await db.materials.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.put("/inventory/materials/{material_id}")
async def inv_update_material(material_id: str, payload: MaterialIn, user: dict = Depends(require_super_admin)):
    if payload.category not in MATERIAL_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Kategori tidak valid")
    if payload.unit not in MATERIAL_UNITS:
        raise HTTPException(status_code=400, detail=f"Satuan tidak valid")
    existing = await db.materials.find_one({"id": material_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")
    update = payload.model_dump()
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.materials.update_one({"id": material_id}, {"$set": update})
    return await db.materials.find_one({"id": material_id}, {"_id": 0})


@api_router.delete("/inventory/materials/{material_id}")
async def inv_delete_material(material_id: str, user: dict = Depends(require_super_admin)):
    existing = await db.materials.find_one({"id": material_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")
    has_in = await db.stock_in.find_one({"material_id": material_id})
    has_waste = await db.waste.find_one({"material_id": material_id})
    if has_in or has_waste:
        await db.materials.update_one({"id": material_id}, {"$set": {"active": False, "updated_at": datetime.now(timezone.utc).isoformat()}})
        return {"ok": True, "soft_deleted": True}
    await db.materials.delete_one({"id": material_id})
    return {"ok": True, "soft_deleted": False}


# ----- Stock In (Barang Masuk) -----
async def _enrich_with_material(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    mats = {m["id"]: m async for m in db.materials.find({}, {"_id": 0})}
    for it in items:
        mat = mats.get(it.get("material_id")) or {}
        it["material_name"] = mat.get("name") or "-"
        it["material_unit"] = mat.get("unit") or ""
        it["material_category"] = mat.get("category") or ""
    return items


@api_router.get("/inventory/stock-in")
async def inv_list_stock_in(user: dict = Depends(require_super_admin), material_id: Optional[str] = None):
    q = {}
    if material_id:
        q["material_id"] = material_id
    cursor = db.stock_in.find(q, {"_id": 0}).sort("date", -1)
    items = await cursor.to_list(length=2000)
    return await _enrich_with_material(items)


@api_router.post("/inventory/stock-in")
async def inv_create_stock_in(payload: StockInIn, user: dict = Depends(require_super_admin)):
    mat = await db.materials.find_one({"id": payload.material_id})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Kuantitas harus > 0")
    total = round(float(payload.quantity) * float(payload.unit_price), 2)
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["total_price"] = total
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["created_by"] = user.get("email")
    await db.stock_in.insert_one(doc)
    new_stock = round(float(mat.get("current_stock", 0)) + float(payload.quantity), 4)
    await db.materials.update_one(
        {"id": payload.material_id},
        {"$set": {
            "current_stock": new_stock,
            "purchase_price": float(payload.unit_price),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    doc.pop("_id", None)
    doc["new_stock"] = new_stock
    return doc


@api_router.delete("/inventory/stock-in/{stock_in_id}")
async def inv_delete_stock_in(stock_in_id: str, user: dict = Depends(require_super_admin)):
    doc = await db.stock_in.find_one({"id": stock_in_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Data barang masuk tidak ditemukan")
    mat = await db.materials.find_one({"id": doc["material_id"]})
    if mat:
        new_stock = round(float(mat.get("current_stock", 0)) - float(doc.get("quantity", 0)), 4)
        await db.materials.update_one(
            {"id": doc["material_id"]},
            {"$set": {"current_stock": new_stock, "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
    await db.stock_in.delete_one({"id": stock_in_id})
    return {"ok": True}


# ----- Waste (Sisa/Rijek) -----
@api_router.get("/inventory/waste")
async def inv_list_waste(user: dict = Depends(require_super_admin), material_id: Optional[str] = None):
    q = {}
    if material_id:
        q["material_id"] = material_id
    cursor = db.waste.find(q, {"_id": 0}).sort("date", -1)
    items = await cursor.to_list(length=2000)
    return await _enrich_with_material(items)


@api_router.post("/inventory/waste")
async def inv_create_waste(payload: WasteIn, user: dict = Depends(require_super_admin)):
    mat = await db.materials.find_one({"id": payload.material_id})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Kuantitas harus > 0")
    if payload.reason not in WASTE_REASONS:
        raise HTTPException(status_code=400, detail=f"Alasan tidak valid")
    unit_price = float(mat.get("purchase_price", 0))
    estimated_loss = round(float(payload.quantity) * unit_price, 2)
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["unit_price_snapshot"] = unit_price
    doc["estimated_loss"] = estimated_loss
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["created_by"] = user.get("email")
    await db.waste.insert_one(doc)
    new_stock = round(float(mat.get("current_stock", 0)) - float(payload.quantity), 4)
    await db.materials.update_one(
        {"id": payload.material_id},
        {"$set": {"current_stock": new_stock, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    doc.pop("_id", None)
    doc["new_stock"] = new_stock
    return doc


@api_router.delete("/inventory/waste/{waste_id}")
async def inv_delete_waste(waste_id: str, user: dict = Depends(require_super_admin)):
    doc = await db.waste.find_one({"id": waste_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Data waste tidak ditemukan")
    mat = await db.materials.find_one({"id": doc["material_id"]})
    if mat:
        new_stock = round(float(mat.get("current_stock", 0)) + float(doc.get("quantity", 0)), 4)
        await db.materials.update_one(
            {"id": doc["material_id"]},
            {"$set": {"current_stock": new_stock, "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
    await db.waste.delete_one({"id": waste_id})
    return {"ok": True}


# ----- Inventory Stats -----
@api_router.get("/inventory/stats")
async def inv_stats(user: dict = Depends(require_super_admin)):
    materials = await db.materials.find({}, {"_id": 0}).to_list(length=5000)
    total_stock_value = 0.0
    low_stock = []
    for m in materials:
        stock = float(m.get("current_stock", 0))
        price = float(m.get("purchase_price", 0))
        total_stock_value += stock * price
        min_stock = float(m.get("min_stock", 0))
        if min_stock > 0 and stock <= min_stock and m.get("active", True):
            low_stock.append({
                "id": m["id"], "name": m["name"], "category": m.get("category"),
                "current_stock": stock, "min_stock": min_stock, "unit": m.get("unit"),
            })
    today = datetime.now(timezone.utc).date()
    month_start = today.replace(day=1).isoformat()
    waste_month = await db.waste.find({"date": {"$gte": month_start}}, {"_id": 0}).to_list(length=5000)
    total_waste_this_month = sum(float(w.get("estimated_loss", 0)) for w in waste_month)
    # Top waste bulan ini per material
    top_agg: Dict[str, Dict[str, Any]] = {}
    mat_by_id = {m["id"]: m for m in materials}
    for w in waste_month:
        mid = w.get("material_id")
        if not mid:
            continue
        mat = mat_by_id.get(mid, {})
        row = top_agg.setdefault(mid, {
            "material_id": mid, "material_name": mat.get("name") or "-",
            "material_unit": mat.get("unit") or "", "material_category": mat.get("category") or "",
            "qty": 0.0, "loss": 0.0, "records": 0,
        })
        row["qty"] += float(w.get("quantity", 0))
        row["loss"] += float(w.get("estimated_loss", 0))
        row["records"] += 1
    top_waste = sorted(top_agg.values(), key=lambda r: r["loss"], reverse=True)[:5]
    for r in top_waste:
        r["qty"] = round(r["qty"], 4)
        r["loss"] = round(r["loss"], 2)
    return {
        "total_materials": sum(1 for m in materials if m.get("active", True)),
        "total_stock_value": round(total_stock_value, 2),
        "low_stock_count": len(low_stock),
        "low_stock": low_stock[:10],
        "total_waste_this_month": round(total_waste_this_month, 2),
        "waste_records_this_month": len(waste_month),
        "top_waste": top_waste,
    }


# ---------------- Stock Adjustment (Opname) ----------------
class StockAdjustIn(BaseModel):
    material_id: str
    new_stock: float  # nilai stok setelah opname
    reason: str = "opname"  # opname | koreksi | lainnya
    date: str
    notes: Optional[str] = None


@api_router.get("/inventory/stock-adjust")
async def inv_list_stock_adjust(user: dict = Depends(require_super_admin), material_id: Optional[str] = None):
    q = {}
    if material_id:
        q["material_id"] = material_id
    items = await db.stock_adjust.find(q, {"_id": 0}).sort("date", -1).to_list(length=2000)
    return await _enrich_with_material(items)


@api_router.post("/inventory/stock-adjust")
async def inv_create_stock_adjust(payload: StockAdjustIn, user: dict = Depends(require_super_admin)):
    mat = await db.materials.find_one({"id": payload.material_id})
    if not mat:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")
    stock_before = float(mat.get("current_stock", 0))
    new_stock = float(payload.new_stock)
    delta = round(new_stock - stock_before, 4)
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["stock_before"] = round(stock_before, 4)
    doc["stock_after"] = round(new_stock, 4)
    doc["delta"] = delta
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["created_by"] = user.get("email")
    await db.stock_adjust.insert_one(doc)
    await db.materials.update_one(
        {"id": payload.material_id},
        {"$set": {"current_stock": round(new_stock, 4), "updated_at": doc["created_at"]}},
    )
    doc.pop("_id", None)
    return doc


@api_router.delete("/inventory/stock-adjust/{adj_id}")
async def inv_delete_stock_adjust(adj_id: str, user: dict = Depends(require_super_admin)):
    doc = await db.stock_adjust.find_one({"id": adj_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Data opname tidak ditemukan")
    # Kembalikan stok ke nilai sebelum adjustment
    await db.materials.update_one(
        {"id": doc["material_id"]},
        {"$set": {"current_stock": float(doc.get("stock_before", 0)), "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    await db.stock_adjust.delete_one({"id": adj_id})
    return {"ok": True}


# ---------------- Job Order (Produksi) ----------------
class JobItemIn(BaseModel):
    material_id: str
    quantity: float  # qty bahan dikonsumsi total


class JobOrderIn(BaseModel):
    order_no: Optional[str] = None  # auto-gen bila kosong
    customer: str
    product_name: str
    quantity: int = 1
    unit_price: float = 0
    start_date: str  # ISO
    due_date: Optional[str] = None
    items: List[JobItemIn] = []
    notes: Optional[str] = None


async def _next_order_no() -> str:
    today = datetime.now(timezone.utc).date()
    prefix = f"JO-{today.strftime('%Y%m')}-"
    count = await db.job_orders.count_documents({"order_no": {"$regex": f"^{prefix}"}})
    return f"{prefix}{count + 1:04d}"


async def _reverse_job_stock(job: Dict[str, Any]) -> None:
    """Kembalikan stok yg pernah dikurangi oleh job (dipakai saat cancel/delete)."""
    for it in job.get("items") or []:
        mid = it.get("material_id")
        qty = float(it.get("quantity", 0))
        if not mid or qty <= 0:
            continue
        mat = await db.materials.find_one({"id": mid})
        if mat:
            new_stock = round(float(mat.get("current_stock", 0)) + qty, 4)
            await db.materials.update_one(
                {"id": mid},
                {"$set": {"current_stock": new_stock, "updated_at": datetime.now(timezone.utc).isoformat()}},
            )


@api_router.get("/inventory/orders")
async def inv_list_orders(user: dict = Depends(require_super_admin), status: Optional[str] = None):
    q = {}
    if status:
        q["status"] = status
    items = await db.job_orders.find(q, {"_id": 0}).sort("created_at", -1).to_list(length=2000)
    # Enrich items dgn nama material
    all_mats = {m["id"]: m async for m in db.materials.find({}, {"_id": 0})}
    for job in items:
        for it in job.get("items") or []:
            mat = all_mats.get(it.get("material_id")) or {}
            it["material_name"] = mat.get("name") or "-"
            it["material_unit"] = mat.get("unit") or ""
    return items


@api_router.post("/inventory/orders")
async def inv_create_order(payload: JobOrderIn, user: dict = Depends(require_super_admin)):
    if not payload.customer or not payload.product_name:
        raise HTTPException(status_code=400, detail="Customer & nama produk wajib diisi")
    # Validate materials + hitung total kerugian bahan snapshot
    items_out = []
    total_material_cost = 0.0
    for it in payload.items:
        mat = await db.materials.find_one({"id": it.material_id})
        if not mat:
            raise HTTPException(status_code=400, detail=f"Bahan {it.material_id} tidak ditemukan")
        if it.quantity <= 0:
            raise HTTPException(status_code=400, detail=f"Kuantitas bahan {mat.get('name')} harus > 0")
        stock = float(mat.get("current_stock", 0))
        if it.quantity > stock:
            raise HTTPException(status_code=400, detail=f"Stok {mat.get('name')} tidak cukup (ada {stock}, butuh {it.quantity})")
        unit_price = float(mat.get("purchase_price", 0))
        items_out.append({
            "material_id": it.material_id,
            "quantity": float(it.quantity),
            "unit_price_snapshot": unit_price,
            "cost": round(float(it.quantity) * unit_price, 2),
        })
        total_material_cost += float(it.quantity) * unit_price

    order_no = payload.order_no or await _next_order_no()
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["order_no"] = order_no
    doc["items"] = items_out
    doc["status"] = "aktif"
    doc["total_material_cost"] = round(total_material_cost, 2)
    doc["total_price"] = round(float(payload.quantity) * float(payload.unit_price), 2)
    doc["gross_margin"] = round(doc["total_price"] - doc["total_material_cost"], 2)
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["created_by"] = user.get("email")
    await db.job_orders.insert_one(doc)

    # Kurangi stok tiap bahan
    for it in items_out:
        mat = await db.materials.find_one({"id": it["material_id"]})
        if mat:
            new_stock = round(float(mat.get("current_stock", 0)) - float(it["quantity"]), 4)
            await db.materials.update_one(
                {"id": it["material_id"]},
                {"$set": {"current_stock": new_stock, "updated_at": datetime.now(timezone.utc).isoformat()}},
            )
    doc.pop("_id", None)
    return doc


@api_router.put("/inventory/orders/{order_id}/complete")
async def inv_complete_order(order_id: str, user: dict = Depends(require_super_admin)):
    job = await db.job_orders.find_one({"id": order_id})
    if not job:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")
    if job.get("status") == "batal":
        raise HTTPException(status_code=400, detail="Order sudah dibatalkan")
    await db.job_orders.update_one(
        {"id": order_id},
        {"$set": {"status": "selesai", "completed_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "status": "selesai"}


@api_router.put("/inventory/orders/{order_id}/cancel")
async def inv_cancel_order(order_id: str, user: dict = Depends(require_super_admin)):
    job = await db.job_orders.find_one({"id": order_id})
    if not job:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")
    if job.get("status") == "batal":
        return {"ok": True, "status": "batal"}
    # Rollback stok jika sebelumnya aktif (belum pernah dibatalkan)
    if job.get("status") in ("aktif", "selesai"):
        await _reverse_job_stock(job)
    await db.job_orders.update_one(
        {"id": order_id},
        {"$set": {"status": "batal", "cancelled_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "status": "batal"}


@api_router.delete("/inventory/orders/{order_id}")
async def inv_delete_order(order_id: str, user: dict = Depends(require_super_admin)):
    job = await db.job_orders.find_one({"id": order_id})
    if not job:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")
    # Rollback bila order aktif/selesai (yg pernah kurangi stok)
    if job.get("status") in ("aktif", "selesai"):
        await _reverse_job_stock(job)
    await db.job_orders.delete_one({"id": order_id})
    return {"ok": True}


# ---------------- Waste Report (Excel + PDF) ----------------
async def _fetch_monthly_waste(period: str):
    start, end, year, month = _parse_month(period)
    cursor = db.waste.find({"date": {"$gte": start, "$lte": end}}, {"_id": 0}).sort("date", 1)
    items = await cursor.to_list(length=5000)
    items = await _enrich_with_material(items)
    total_loss = sum(float(x.get("estimated_loss", 0)) for x in items)
    total_qty = sum(float(x.get("quantity", 0)) for x in items)
    return items, total_loss, total_qty, year, month


@api_router.get("/inventory/waste/report/{period}/excel")
async def inv_waste_report_excel(period: str, user: dict = Depends(require_super_admin)):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    items, total_loss, total_qty, year, month = await _fetch_monthly_waste(period)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Waste {period}"
    ws.append([f"LAPORAN WASTE / RIJEK BULANAN — {year}-{month:02d}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    headers = ["Tanggal", "Bahan", "Kategori", "Alasan", "Qty", "Satuan", "Harga/Unit", "Kerugian (Rp)", "Pelapor", "Catatan"]
    ws.append(headers)
    header_fill = PatternFill(start_color="002FA7", end_color="002FA7", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws[3]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    for it in items:
        ws.append([
            it.get("date", ""),
            it.get("material_name", ""),
            it.get("material_category", ""),
            it.get("reason", ""),
            float(it.get("quantity", 0)),
            it.get("material_unit", ""),
            float(it.get("unit_price_snapshot", 0)),
            float(it.get("estimated_loss", 0)),
            it.get("reported_by", ""),
            it.get("notes", ""),
        ])
    ws.append([])
    total_row = ["TOTAL", "", "", "", total_qty, "", "", total_loss, "", ""]
    ws.append(total_row)
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ws.cell(row=ws.max_row, column=8).font = Font(bold=True)
    for col_idx, width in enumerate([12, 30, 12, 14, 10, 10, 14, 16, 20, 30], 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="laporan-waste-{period}.xlsx"'},
    )


@api_router.get("/inventory/waste/report/{period}/pdf")
async def inv_waste_report_pdf(period: str, user: dict = Depends(require_super_admin)):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    items, total_loss, total_qty, year, month = await _fetch_monthly_waste(period)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    elems = [
        Paragraph(f"<b>LAPORAN WASTE / RIJEK BULANAN</b>", styles["Title"]),
        Paragraph(f"Periode: {year}-{month:02d}", styles["Normal"]),
        Spacer(1, 8),
    ]
    data = [["Tanggal", "Bahan", "Alasan", "Qty", "Satuan", "Kerugian (Rp)", "Pelapor"]]
    for it in items:
        data.append([
            it.get("date", ""),
            it.get("material_name", ""),
            it.get("reason", ""),
            f"{float(it.get('quantity', 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            it.get("material_unit", ""),
            f"Rp {float(it.get('estimated_loss', 0)):,.0f}".replace(",", "."),
            it.get("reported_by", "") or "-",
        ])
    data.append(["", "", "TOTAL", f"{total_qty:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), "", f"Rp {total_loss:,.0f}".replace(",", "."), ""])
    tbl = Table(data, colWidths=[22 * mm, 60 * mm, 25 * mm, 22 * mm, 20 * mm, 40 * mm, 40 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#002FA7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ALIGN", (3, 1), (5, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f5f5f5")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elems.append(tbl)
    doc.build(elems)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="laporan-waste-{period}.pdf"'},
    )


# ---------------- Customer Master ----------------
class CustomerIn(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    npwp: Optional[str] = None
    contact_person: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True


@api_router.get("/inventory/customers")
async def cust_list(user: dict = Depends(require_super_admin)):
    items = await db.customers.find({}, {"_id": 0}).sort("name", 1).to_list(length=5000)
    # Enrich dengan agregat order per customer
    orders = await db.job_orders.find({}, {"_id": 0}).to_list(length=10000)
    by_name: Dict[str, Dict[str, Any]] = {}
    for o in orders:
        key = (o.get("customer") or "").strip().lower()
        if not key:
            continue
        row = by_name.setdefault(key, {"count": 0, "revenue": 0.0, "material_cost": 0.0})
        if o.get("status") != "batal":
            row["count"] += 1
            row["revenue"] += float(o.get("total_price", 0))
            row["material_cost"] += float(o.get("total_material_cost", 0))
    for c in items:
        agg = by_name.get(c.get("name", "").strip().lower()) or {}
        c["order_count"] = agg.get("count", 0)
        c["total_revenue"] = round(agg.get("revenue", 0.0), 2)
        c["total_material_cost"] = round(agg.get("material_cost", 0.0), 2)
    return items


@api_router.post("/inventory/customers")
async def cust_create(payload: CustomerIn, user: dict = Depends(require_super_admin)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Nama customer wajib diisi")
    # Cek duplicate name (case-insensitive) — escape regex special chars
    safe_name = re.escape(payload.name.strip())
    existing = await db.customers.find_one({"name": {"$regex": f"^{safe_name}$", "$options": "i"}})
    if existing:
        raise HTTPException(status_code=400, detail="Customer dengan nama tersebut sudah ada")
    doc = payload.model_dump()
    doc["name"] = payload.name.strip()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.customers.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.put("/inventory/customers/{customer_id}")
async def cust_update(customer_id: str, payload: CustomerIn, user: dict = Depends(require_super_admin)):
    existing = await db.customers.find_one({"id": customer_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan")
    upd = payload.model_dump()
    upd["name"] = payload.name.strip()
    upd["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.customers.update_one({"id": customer_id}, {"$set": upd})
    return await db.customers.find_one({"id": customer_id}, {"_id": 0})


@api_router.delete("/inventory/customers/{customer_id}")
async def cust_delete(customer_id: str, user: dict = Depends(require_super_admin)):
    existing = await db.customers.find_one({"id": customer_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan")
    await db.customers.delete_one({"id": customer_id})
    return {"ok": True}


# ---------------- Laporan Laba/Rugi (Profit & Loss) ----------------
async def _payroll_cost_for_month(period: str) -> tuple:
    """Return (total_net, employee_count) untuk payroll_runs dgn period=YYYY-MM. Fallback 0."""
    run = await db.payroll_runs.find_one({"period": period}, {"_id": 0})
    if not run:
        return 0.0, 0
    return float(run.get("total_net", 0)), int(run.get("employee_count", 0))


@api_router.get("/reports/profit-loss/{period}")
async def profit_loss_report(period: str, user: dict = Depends(require_super_admin)):
    """P&L bulanan: Revenue (orders selesai/aktif) − COGS − Waste − Gaji = Net Profit."""
    start, end, year, month = _parse_month(period)
    # Orders (revenue & material cost) — exclude batal
    orders = await db.job_orders.find({
        "start_date": {"$gte": start, "$lte": end},
        "status": {"$ne": "batal"},
    }, {"_id": 0}).to_list(length=5000)
    revenue = sum(float(o.get("total_price", 0)) for o in orders)
    cogs = sum(float(o.get("total_material_cost", 0)) for o in orders)
    gross_profit = revenue - cogs
    # Waste
    waste_docs = await db.waste.find({"date": {"$gte": start, "$lte": end}}, {"_id": 0}).to_list(length=5000)
    waste_loss = sum(float(w.get("estimated_loss", 0)) for w in waste_docs)
    # Payroll
    payroll_cost, employee_count = await _payroll_cost_for_month(period)
    # Total expenses
    total_expenses = waste_loss + payroll_cost
    net_profit = gross_profit - total_expenses
    # Breakdown top customer
    cust_agg: Dict[str, Dict[str, Any]] = {}
    for o in orders:
        key = (o.get("customer") or "-").strip()
        if not key:
            key = "-"
        row = cust_agg.setdefault(key, {"customer": key, "orders": 0, "revenue": 0.0, "material_cost": 0.0})
        row["orders"] += 1
        row["revenue"] += float(o.get("total_price", 0))
        row["material_cost"] += float(o.get("total_material_cost", 0))
    top_customers = sorted(cust_agg.values(), key=lambda r: r["revenue"], reverse=True)[:10]
    for r in top_customers:
        r["revenue"] = round(r["revenue"], 2)
        r["material_cost"] = round(r["material_cost"], 2)
        r["margin"] = round(r["revenue"] - r["material_cost"], 2)
    return {
        "period": period,
        "revenue": round(revenue, 2),
        "cogs": round(cogs, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_margin_pct": round((gross_profit / revenue * 100) if revenue > 0 else 0, 2),
        "waste_loss": round(waste_loss, 2),
        "payroll_cost": round(payroll_cost, 2),
        "employee_count": employee_count,
        "total_expenses": round(total_expenses, 2),
        "net_profit": round(net_profit, 2),
        "net_margin_pct": round((net_profit / revenue * 100) if revenue > 0 else 0, 2),
        "order_count": len(orders),
        "waste_records": len(waste_docs),
        "top_customers": top_customers,
    }


@api_router.get("/reports/profit-loss/{period}/pdf")
async def profit_loss_pdf(period: str, user: dict = Depends(require_super_admin)):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    r = await profit_loss_report(period, user)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Title"], fontSize=16, spaceAfter=6)
    elems = [
        Paragraph("<b>LAPORAN LABA / RUGI BULANAN</b>", h1),
        Paragraph(f"Periode: <b>{period}</b>", styles["Normal"]),
        Spacer(1, 10),
    ]
    def _fmt(n):
        return f"Rp {n:,.0f}".replace(",", ".")
    rows = [
        ["Uraian", "Jumlah"],
        [f"Pendapatan Penjualan ({r['order_count']} order)", _fmt(r['revenue'])],
        ["(-) Biaya Bahan Baku (COGS)", _fmt(r['cogs'])],
        [f"LABA KOTOR ({r['gross_margin_pct']}%)", _fmt(r['gross_profit'])],
        [f"(-) Kerugian Waste/Rijek ({r['waste_records']} record)", _fmt(r['waste_loss'])],
        [f"(-) Biaya Gaji Karyawan ({r['employee_count']} karyawan)", _fmt(r['payroll_cost'])],
        ["Total Beban Operasional", _fmt(r['total_expenses'])],
        [f"LABA / RUGI BERSIH ({r['net_margin_pct']}%)", _fmt(r['net_profit'])],
    ]
    tbl = Table(rows, colWidths=[100 * mm, 60 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#002FA7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#e8f0ff")),
        ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#002FA7") if r["net_profit"] >= 0 else colors.HexColor("#E81123")),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elems.append(tbl)
    if r["top_customers"]:
        elems.append(Spacer(1, 14))
        elems.append(Paragraph("<b>Top Customer</b>", styles["Heading3"]))
        crows = [["#", "Customer", "Order", "Revenue", "Margin"]]
        for i, c in enumerate(r["top_customers"], 1):
            crows.append([str(i), c["customer"], str(c["orders"]), _fmt(c["revenue"]), _fmt(c["margin"])])
        ctbl = Table(crows, colWidths=[10 * mm, 70 * mm, 20 * mm, 35 * mm, 35 * mm])
        ctbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f5f5")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ALIGN", (2, 1), (4, -1), "RIGHT"),
        ]))
        elems.append(ctbl)
    doc.build(elems)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="laba-rugi-{period}.pdf"'},
    )


# Include router
app.include_router(api_router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
