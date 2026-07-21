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
from typing import List, Optional, Dict, Any, Tuple

from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, UploadFile, File, Form, Body
from fastapi.responses import StreamingResponse, HTMLResponse
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
app = FastAPI(title="HRIS API")
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
        # Legacy hr_leave role → treat as admin_privileged with izin_cuti perm
        if user.get("role") == "hr_leave":
            user["role"] = "admin_privileged"
            user["permissions"] = list(set((user.get("permissions") or []) + ["izin_cuti"]))
        # Ensure permissions field exists
        if user.get("role") == "admin_privileged" and not isinstance(user.get("permissions"), list):
            user["permissions"] = []
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# Role-based access helpers
ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN_PRIVILEGED = "admin_privileged"
ROLE_HR_LEAVE = "hr_leave"  # legacy, migrated to admin_privileged on startup
VALID_ROLES = {ROLE_SUPER_ADMIN, ROLE_ADMIN_PRIVILEGED}

# All menu keys that can be granted to an "Admin dengan Privilege"
MENU_KEYS = [
    "karyawan", "payroll", "inventory", "pembelian", "penjualan",
    "laporan_penjualan", "kas_operasional", "laba_rugi", "master_kategori",
    "thr", "izin_cuti", "kelola_user", "konfigurasi",
]

# Ordered rules: (path_prefix, menu_key). First matching prefix wins.
# Path is the full request path INCLUDING /api prefix.
PATH_MENU_RULES = [
    # ---- Payroll & Slips ----
    ("/api/payroll/thr", "thr"),
    ("/api/payroll/bukti-potong", "payroll"),
    ("/api/payroll", "payroll"),
    ("/api/payslip", "payroll"),
    ("/api/attendance", "payroll"),
    # ---- Employees ----
    ("/api/employees", "karyawan"),
    ("/api/contracts", "karyawan"),
    # ---- Sales sub-routes (most specific first) ----
    ("/api/sales/report", "laporan_penjualan"),
    ("/api/sales/stats", "penjualan"),
    ("/api/sales", "penjualan"),
    ("/api/products", "penjualan"),
    ("/api/inventory/customers", "penjualan"),
    # ---- Inventory / Purchasing ----
    ("/api/inventory", "inventory"),
    ("/api/purchasing", "pembelian"),
    # ---- Cashbook ----
    ("/api/cashbook", "kas_operasional"),
    # ---- Reports (Laba Rugi) ----
    ("/api/reports", "laba_rugi"),
    # ---- Categories ----
    ("/api/categories", "master_kategori"),
    # ---- Leave ----
    ("/api/leave", "izin_cuti"),
    # ---- User Mgmt ----
    ("/api/users", "kelola_user"),
    # ---- Config / Konfigurasi ----
    ("/api/config", "konfigurasi"),
    ("/api/admin/whatsapp", "konfigurasi"),
    ("/api/admin/export-database", "konfigurasi"),
    ("/api/admin/import-database", "konfigurasi"),
]

# Paths that do NOT require menu-permission (still may require login separately).
# Auth endpoints, portal endpoints, root health, dashboard, and public misc.
RBAC_BYPASS_PREFIXES = (
    "/api/auth/",
    "/api/portal/",
    "/api/dashboard",  # any authenticated admin sees a filtered dashboard
    "/api/employees-template.csv",  # only used from imports page (karyawan menu)
    "/api/employees-import",
)


def _menu_for_path(path: str) -> Optional[str]:
    for prefix, menu in PATH_MENU_RULES:
        if path.startswith(prefix):
            return menu
    return None


async def require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    """Backward-compat: allow both super_admin AND admin_privileged.
    Fine-grained menu access is enforced by the RBAC middleware based on path."""
    role = user.get("role")
    if role not in VALID_ROLES:
        raise HTTPException(status_code=403, detail="Akses ditolak")
    return user


async def require_super_admin_strict(user: dict = Depends(get_current_user)) -> dict:
    """Strict: only super_admin. Reserved for meta/system routes."""
    if user.get("role") != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Akses ditolak: Super Admin only")
    return user


async def require_leave_access(user: dict = Depends(get_current_user)) -> dict:
    role = user.get("role")
    if role == ROLE_SUPER_ADMIN:
        return user
    if role == ROLE_ADMIN_PRIVILEGED and "izin_cuti" in (user.get("permissions") or []):
        return user
    raise HTTPException(status_code=403, detail="Akses ditolak")


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
    return _user_view(user)


@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return _user_view(user)


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

    company = os.environ.get("COMPANY_NAME", "PLAZAKREASI DIGITAL PRINTING")
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

    company = os.environ.get("COMPANY_NAME", "PLAZAKREASI DIGITAL PRINTING")
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
    company = os.environ.get("COMPANY_NAME", "PLAZAKREASI DIGITAL PRINTING")
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
    company = os.environ.get("COMPANY_NAME", "PLAZAKREASI DIGITAL PRINTING")
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

    ws["A2"] = f"Perusahaan: {os.environ.get('COMPANY_NAME', 'PLAZAKREASI DIGITAL PRINTING')}"
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
    story.append(Paragraph(f"Periode: <b>{period}</b> &nbsp;|&nbsp; Perusahaan: {os.environ.get('COMPANY_NAME', 'PLAZAKREASI DIGITAL PRINTING')}", sub_style))
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
    role: str  # "super_admin" or "admin_privileged"
    permissions: Optional[List[str]] = None
    branch: Optional[str] = None  # "plaza" | "kastem" | None


class UserUpdateIn(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    permissions: Optional[List[str]] = None
    branch: Optional[str] = None


def _sanitize_permissions(role: str, perms: Optional[List[str]]) -> List[str]:
    if role == ROLE_SUPER_ADMIN:
        return list(MENU_KEYS)  # super admin implicitly has all
    valid = [p for p in (perms or []) if p in MENU_KEYS]
    # de-dup while preserving order
    seen = set()
    out = []
    for p in valid:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


VALID_BRANCHES = {"plaza", "kastem"}


def _sanitize_branch(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    v = str(val).strip().lower()
    return v if v in VALID_BRANCHES else None


def _user_view(u: dict) -> dict:
    role = u.get("role")
    if role == "admin":
        role = ROLE_SUPER_ADMIN
    if role == "hr_leave":
        role = ROLE_ADMIN_PRIVILEGED
    perms = u.get("permissions") or []
    if role == ROLE_SUPER_ADMIN:
        perms = list(MENU_KEYS)
    else:
        perms = [p for p in perms if p in MENU_KEYS]
    return {
        "id": u["id"],
        "email": u["email"],
        "name": u.get("name", ""),
        "role": role,
        "permissions": perms,
        "branch": _sanitize_branch(u.get("branch")),
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
        "permissions": _sanitize_permissions(payload.role, payload.permissions),
        "branch": _sanitize_branch(payload.branch),
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
    new_role = payload.role
    if new_role is not None:
        if new_role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="Role tidak valid")
        # Prevent demoting the last super_admin
        if target.get("role") in {ROLE_SUPER_ADMIN, "admin"} and new_role != ROLE_SUPER_ADMIN:
            super_admins = await db.users.count_documents({"role": {"$in": [ROLE_SUPER_ADMIN, "admin"]}})
            if super_admins <= 1:
                raise HTTPException(status_code=400, detail="Tidak dapat mengubah role: minimal harus ada 1 Super Admin")
        update["role"] = new_role
    if payload.password:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password minimal 6 karakter")
        update["password_hash"] = hash_password(payload.password)
    # Permissions: always sanitize according to final role
    if payload.permissions is not None or new_role is not None:
        role_effective = new_role or target.get("role") or ROLE_ADMIN_PRIVILEGED
        if role_effective == "admin":
            role_effective = ROLE_SUPER_ADMIN
        if role_effective == "hr_leave":
            role_effective = ROLE_ADMIN_PRIVILEGED
        perms_input = payload.permissions if payload.permissions is not None else (target.get("permissions") or [])
        update["permissions"] = _sanitize_permissions(role_effective, perms_input)
    if payload.branch is not None:
        # Allow explicit empty string / null to clear
        update["branch"] = _sanitize_branch(payload.branch)
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
    return {"message": "HRIS API", "ok": True}


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

    # Migrate legacy "hr_leave" role -> "admin_privileged" with izin_cuti permission
    hr_leave_users = await db.users.find({"role": "hr_leave"}, {"_id": 0}).to_list(length=200)
    for u in hr_leave_users:
        perms = list(set((u.get("permissions") or []) + ["izin_cuti"]))
        await db.users.update_one(
            {"id": u["id"]},
            {"$set": {"role": ROLE_ADMIN_PRIVILEGED, "permissions": perms}},
        )
    if hr_leave_users:
        logger.info(f"Migrated {len(hr_leave_users)} 'hr_leave' role(s) to '{ROLE_ADMIN_PRIVILEGED}'")

    # Ensure super_admin users have full permissions array populated (idempotent)
    await db.users.update_many(
        {"role": ROLE_SUPER_ADMIN},
        {"$set": {"permissions": list(MENU_KEYS)}},
    )
    # Ensure admin_privileged users have a permissions field
    await db.users.update_many(
        {"role": ROLE_ADMIN_PRIVILEGED, "permissions": {"$exists": False}},
        {"$set": {"permissions": []}},
    )


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
    selling_price: float = 0  # harga jual per m² (untuk POS Sales)
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
    if not (payload.category or "").strip():
        raise HTTPException(status_code=400, detail="Kategori wajib diisi")
    if payload.unit not in MATERIAL_UNITS:
        raise HTTPException(status_code=400, detail=f"Satuan tidak valid")
    doc = payload.model_dump()
    doc["category"] = (doc.get("category") or "").strip()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["updated_at"] = doc["created_at"]
    await db.materials.insert_one(doc)
    await _upsert_category("material", doc["category"])
    doc.pop("_id", None)
    return doc


@api_router.put("/inventory/materials/{material_id}")
async def inv_update_material(material_id: str, payload: MaterialIn, user: dict = Depends(require_super_admin)):
    if not (payload.category or "").strip():
        raise HTTPException(status_code=400, detail="Kategori wajib diisi")
    if payload.unit not in MATERIAL_UNITS:
        raise HTTPException(status_code=400, detail=f"Satuan tidak valid")
    existing = await db.materials.find_one({"id": material_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Bahan tidak ditemukan")
    update = payload.model_dump()
    update["category"] = (update.get("category") or "").strip()
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.materials.update_one({"id": material_id}, {"$set": update})
    await _upsert_category("material", update["category"])
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
    category: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True


# ================================================================
# ==================== MASTER KATEGORI (unified) ==================
# ================================================================
CATEGORY_TYPES = ("material", "product", "supplier", "customer")

class CategoryIn(BaseModel):
    type: str  # material | product | supplier | customer
    name: str
    description: Optional[str] = None
    color: Optional[str] = None  # hex mis. #002FA7
    active: bool = True


async def _upsert_category(cat_type: str, name: Optional[str]):
    """Idempotent upsert kategori. Dipanggil dari CRUD master lain."""
    if not name or not name.strip() or cat_type not in CATEGORY_TYPES:
        return
    nm = name.strip()
    # Case-insensitive dedupe
    exists = await db.categories.find_one({"type": cat_type, "name": {"$regex": f"^{re.escape(nm)}$", "$options": "i"}})
    if exists:
        return
    await db.categories.insert_one({
        "id": str(uuid.uuid4()),
        "type": cat_type,
        "name": nm,
        "description": None,
        "color": None,
        "active": True,
        "auto_created": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def _backfill_categories():
    """One-shot backfill: scan existing masters lalu upsert kategori-kategori yang belum ada."""
    for src_coll, cat_type in [
        ("materials", "material"),
        ("products", "product"),
        ("suppliers", "supplier"),
        ("customers", "customer"),
    ]:
        try:
            names = await db[src_coll].distinct("category")
            for n in names or []:
                if n and isinstance(n, str) and n.strip():
                    await _upsert_category(cat_type, n.strip())
        except Exception as ex:
            logger.warning(f"Backfill category from {src_coll} failed: {ex}")


@api_router.get("/categories")
async def categories_list(user: dict = Depends(require_super_admin), type: Optional[str] = None, only_active: bool = False):
    q: Dict[str, Any] = {}
    if type:
        if type not in CATEGORY_TYPES:
            raise HTTPException(status_code=400, detail=f"Type harus salah satu: {CATEGORY_TYPES}")
        q["type"] = type
    if only_active:
        q["active"] = {"$ne": False}
    items = await db.categories.find(q, {"_id": 0}).sort([("type", 1), ("name", 1)]).to_list(length=5000)
    return items


@api_router.post("/categories/backfill")
async def categories_backfill(user: dict = Depends(require_super_admin)):
    before = await db.categories.count_documents({})
    await _backfill_categories()
    after = await db.categories.count_documents({})
    return {"added": after - before, "total": after}


@api_router.post("/categories")
async def categories_create(payload: CategoryIn, user: dict = Depends(require_super_admin)):
    if payload.type not in CATEGORY_TYPES:
        raise HTTPException(status_code=400, detail=f"Type harus salah satu: {CATEGORY_TYPES}")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Nama kategori wajib")
    exists = await db.categories.find_one({"type": payload.type, "name": {"$regex": f"^{re.escape(payload.name.strip())}$", "$options": "i"}})
    if exists:
        raise HTTPException(status_code=400, detail=f"Kategori '{payload.name}' sudah ada untuk tipe {payload.type}")
    doc = {
        "id": str(uuid.uuid4()),
        "type": payload.type,
        "name": payload.name.strip(),
        "description": (payload.description or "").strip() or None,
        "color": (payload.color or "").strip() or None,
        "active": payload.active,
        "auto_created": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.categories.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.put("/categories/{cat_id}")
async def categories_update(cat_id: str, payload: CategoryIn, user: dict = Depends(require_super_admin)):
    existing = await db.categories.find_one({"id": cat_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    new_name = payload.name.strip()
    if payload.type not in CATEGORY_TYPES:
        raise HTTPException(status_code=400, detail=f"Type harus salah satu: {CATEGORY_TYPES}")
    if not new_name:
        raise HTTPException(status_code=400, detail="Nama kategori wajib")
    if new_name.lower() != (existing.get("name") or "").lower() or payload.type != existing.get("type"):
        dup = await db.categories.find_one({
            "type": payload.type,
            "name": {"$regex": f"^{re.escape(new_name)}$", "$options": "i"},
            "id": {"$ne": cat_id},
        })
        if dup:
            raise HTTPException(status_code=400, detail=f"Kategori '{new_name}' sudah ada untuk tipe {payload.type}")
    # Kalau rename, cascade update di collections terkait
    old_name = existing.get("name") or ""
    old_type = existing.get("type")
    upd = {
        "type": payload.type,
        "name": new_name,
        "description": (payload.description or "").strip() or None,
        "color": (payload.color or "").strip() or None,
        "active": payload.active,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.categories.update_one({"id": cat_id}, {"$set": upd})
    # Cascade rename di master data terkait
    if old_name and old_name != new_name and old_type == payload.type:
        coll_map = {"material": "materials", "product": "products", "supplier": "suppliers", "customer": "customers"}
        coll = coll_map.get(payload.type)
        if coll:
            await db[coll].update_many({"category": old_name}, {"$set": {"category": new_name}})
    return await db.categories.find_one({"id": cat_id}, {"_id": 0})


@api_router.delete("/categories/{cat_id}")
async def categories_delete(cat_id: str, user: dict = Depends(require_super_admin)):
    existing = await db.categories.find_one({"id": cat_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    # Cek apakah masih dipakai
    coll_map = {"material": "materials", "product": "products", "supplier": "suppliers", "customer": "customers"}
    coll = coll_map.get(existing.get("type"))
    if coll:
        used = await db[coll].count_documents({"category": existing.get("name")})
        if used > 0:
            raise HTTPException(status_code=400, detail=f"Kategori masih dipakai di {used} data {existing.get('type')}. Non-aktifkan saja atau ubah data yang menggunakan.")
    await db.categories.delete_one({"id": cat_id})
    return {"ok": True}


@api_router.get("/categories/stats")
async def categories_stats(user: dict = Depends(require_super_admin)):
    """Return count per type + usage per category."""
    coll_map = {"material": "materials", "product": "products", "supplier": "suppliers", "customer": "customers"}
    stats = {}
    for t in CATEGORY_TYPES:
        total = await db.categories.count_documents({"type": t})
        active = await db.categories.count_documents({"type": t, "active": {"$ne": False}})
        stats[t] = {"total": total, "active": active}
    return stats


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
    await _upsert_category("customer", doc.get("category"))
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
    await _upsert_category("customer", upd.get("category"))
    return await db.customers.find_one({"id": customer_id}, {"_id": 0})


@api_router.delete("/inventory/customers/{customer_id}")
async def cust_delete(customer_id: str, user: dict = Depends(require_super_admin)):
    existing = await db.customers.find_one({"id": customer_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan")
    await db.customers.delete_one({"id": customer_id})
    return {"ok": True}


# ---------------- Broadcast WhatsApp ke Pelanggan ----------------
class CustomerBroadcastIn(BaseModel):
    message: str
    customer_ids: Optional[List[str]] = None  # None/empty = semua pelanggan aktif yg punya phone
    preview_only: bool = False


@api_router.post("/inventory/customers/broadcast-whatsapp")
async def customers_broadcast_whatsapp(payload: CustomerBroadcastIn, user: dict = Depends(require_super_admin)):
    msg_template = (payload.message or "").strip()
    if not msg_template:
        raise HTTPException(status_code=400, detail="Pesan tidak boleh kosong")
    if len(msg_template) > 3000:
        raise HTTPException(status_code=400, detail="Pesan terlalu panjang (max 3000 karakter)")

    # Ambil target customers
    query: Dict[str, Any] = {"active": {"$ne": False}}
    if payload.customer_ids:
        query["id"] = {"$in": payload.customer_ids}
    all_customers = await db.customers.find(query, {"_id": 0}).to_list(length=5000)
    # Filter yang punya phone
    targets = [c for c in all_customers if (c.get("phone") or "").strip()]
    skipped_no_phone = len(all_customers) - len(targets)

    if payload.preview_only:
        return {
            "preview_only": True,
            "total_selected": len(all_customers),
            "total_with_phone": len(targets),
            "skipped_no_phone": skipped_no_phone,
            "sample_targets": [{"name": c["name"], "phone": c.get("phone")} for c in targets[:5]],
        }

    if not targets:
        raise HTTPException(status_code=400, detail="Tidak ada pelanggan dengan nomor WhatsApp yang bisa dikirim")

    results = []
    sent = failed = mocked = 0
    for c in targets:
        # Replace variabel {name} & {phone}
        personalized = msg_template.replace("{name}", c.get("name", "")).replace("{phone}", c.get("phone", ""))
        res = await _send_whatsapp(c.get("phone", ""), personalized)
        status = res.get("status", "failed")
        if status == "sent":
            sent += 1
        elif status == "mocked":
            mocked += 1
        else:
            failed += 1
        results.append({
            "customer_id": c.get("id"),
            "name": c.get("name"),
            "phone": res.get("phone") or c.get("phone"),
            "status": status,
            "reason": res.get("reason"),
        })
        # Log ke db (opsional, best-effort)
        try:
            await db.whatsapp_logs.insert_one({
                "id": str(uuid.uuid4()),
                "type": "customer_broadcast",
                "customer_id": c.get("id"),
                "customer_name": c.get("name"),
                "phone": res.get("phone") or c.get("phone"),
                "message_preview": personalized[:200],
                "status": status,
                "reason": res.get("reason"),
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "sent_by": user.get("email"),
            })
        except Exception:
            pass
        # Gentle pacing untuk Fonnte free plan
        await asyncio.sleep(0.3)

    return {
        "preview_only": False,
        "total": len(targets),
        "sent": sent,
        "failed": failed,
        "mocked": mocked,
        "skipped_no_phone": skipped_no_phone,
        "results": results,
    }


# ---------------- Laporan Laba/Rugi (Profit & Loss) ----------------
async def _payroll_cost_for_month(period: str) -> tuple:
    """Return (total_net, employee_count) untuk payroll_runs dgn period=YYYY-MM. Fallback 0."""
    run = await db.payroll_runs.find_one({"period": period}, {"_id": 0})
    if not run:
        return 0.0, 0
    return float(run.get("total_net", 0)), int(run.get("employee_count", 0))


@api_router.get("/reports/product-margin/{period}")
async def product_margin_report(period: str, user: dict = Depends(require_super_admin)):
    """Ranking margin per produk untuk periode YYYY-MM.
    Data source: db.sales items. Cost = sum(component.consumption × material.purchase_price).
    """
    start, end, _year, _month = _parse_month(period)
    sales = await db.sales.find(
        {"date": {"$gte": start, "$lte": end}}, {"_id": 0},
    ).to_list(length=50000)

    # Cache materials untuk lookup purchase_price
    material_cache: Dict[str, Dict[str, Any]] = {}
    async def _mat(mid: str):
        if mid in material_cache:
            return material_cache[mid]
        m = await db.materials.find_one({"id": mid}, {"_id": 0, "name": 1, "purchase_price": 1, "unit": 1})
        material_cache[mid] = m or {}
        return material_cache[mid]

    # Group by product identity
    # Key: (product_id or "") + "::" + product_name (untuk group produk yg sama)
    groups: Dict[str, Dict[str, Any]] = {}
    for s in sales:
        for it in (s.get("items") or []):
            key = f"{it.get('product_id') or ''}::{(it.get('product_name') or '-').strip()}"
            row = groups.setdefault(key, {
                "product_id": it.get("product_id"),
                "product_name": (it.get("product_name") or "-").strip() or "-",
                "is_bom": bool(it.get("product_id")),
                "sale_count": 0,
                "qty_total": 0,
                "revenue": 0.0,
                "cost": 0.0,
                "materials_used": {},  # name -> total consumption
            })
            row["sale_count"] += 1
            row["qty_total"] += int(it.get("quantity", 0) or 0)
            row["revenue"] += float(it.get("subtotal", 0) or 0)
            # Cost from components (BOM) or legacy area_total × purchase_price
            comps = it.get("components") or []
            if comps:
                for c in comps:
                    m = await _mat(c.get("material_id"))
                    cost = float(c.get("consumption", 0) or 0) * float(m.get("purchase_price", 0) or 0)
                    row["cost"] += cost
                    mname = m.get("name") or c.get("material_name") or "-"
                    mu = row["materials_used"].setdefault(mname, {"consumption": 0.0, "unit": m.get("unit") or c.get("material_unit") or ""})
                    mu["consumption"] += float(c.get("consumption", 0) or 0)
            else:
                # Legacy: material_id + area_total
                mid = it.get("material_id")
                if mid:
                    m = await _mat(mid)
                    area_total = float(it.get("area_total", 0) or 0)
                    row["cost"] += area_total * float(m.get("purchase_price", 0) or 0)
                    mname = m.get("name") or it.get("material_name") or "-"
                    mu = row["materials_used"].setdefault(mname, {"consumption": 0.0, "unit": m.get("unit") or it.get("material_unit") or ""})
                    mu["consumption"] += area_total

    rows = []
    for _k, r in groups.items():
        margin = r["revenue"] - r["cost"]
        pct = (margin / r["revenue"] * 100) if r["revenue"] > 0 else 0.0
        rows.append({
            "product_id": r["product_id"],
            "product_name": r["product_name"],
            "is_bom": r["is_bom"],
            "sale_count": r["sale_count"],
            "qty_total": r["qty_total"],
            "revenue": round(r["revenue"], 2),
            "cost": round(r["cost"], 2),
            "margin": round(margin, 2),
            "margin_pct": round(pct, 2),
            "materials_used": [
                {"name": k, "consumption": round(v["consumption"], 4), "unit": v["unit"]}
                for k, v in sorted(r["materials_used"].items(), key=lambda x: -x[1]["consumption"])
            ],
        })
    # Sort by revenue desc default (frontend bisa re-sort)
    rows.sort(key=lambda x: x["revenue"], reverse=True)
    total_revenue = sum(r["revenue"] for r in rows)
    total_cost = sum(r["cost"] for r in rows)
    total_margin = total_revenue - total_cost
    return {
        "period": period,
        "period_start": start,
        "period_end": end,
        "total_products": len(rows),
        "total_revenue": round(total_revenue, 2),
        "total_cost": round(total_cost, 2),
        "total_margin": round(total_margin, 2),
        "total_margin_pct": round((total_margin / total_revenue * 100) if total_revenue > 0 else 0, 2),
        "products": rows,
    }


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


@api_router.get("/reports/profit-loss-trend")
async def profit_loss_trend(months: int = 12, user: dict = Depends(require_super_admin)):
    """Return P&L summary utk N bulan terakhir termasuk bulan sekarang. Plus data YoY (bulan sama tahun lalu)."""
    if months < 1 or months > 36:
        raise HTTPException(status_code=400, detail="months harus 1-36")
    today = datetime.now(timezone.utc).date()
    # Buat list periode dari (months-1) bulan lalu → sekarang
    periods = []
    y, m = today.year, today.month
    for _ in range(months):
        periods.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    periods.reverse()
    # YoY: bulan-bulan yg sama tahun sebelumnya
    yoy_periods = []
    for p in periods:
        yy, mm = int(p[:4]) - 1, int(p[5:7])
        yoy_periods.append(f"{yy:04d}-{mm:02d}")

    async def _summary(period: str):
        start, end, _, _ = _parse_month(period)
        orders = await db.job_orders.find({
            "start_date": {"$gte": start, "$lte": end},
            "status": {"$ne": "batal"},
        }, {"_id": 0, "total_price": 1, "total_material_cost": 1}).to_list(length=5000)
        revenue = sum(float(o.get("total_price", 0)) for o in orders)
        cogs = sum(float(o.get("total_material_cost", 0)) for o in orders)
        waste_docs = await db.waste.find({"date": {"$gte": start, "$lte": end}}, {"_id": 0, "estimated_loss": 1}).to_list(length=5000)
        waste_loss = sum(float(w.get("estimated_loss", 0)) for w in waste_docs)
        payroll_cost, _ = await _payroll_cost_for_month(period)
        gross = revenue - cogs
        net = gross - (waste_loss + payroll_cost)
        return {
            "period": period,
            "revenue": round(revenue, 2),
            "cogs": round(cogs, 2),
            "waste_loss": round(waste_loss, 2),
            "payroll_cost": round(payroll_cost, 2),
            "gross_profit": round(gross, 2),
            "net_profit": round(net, 2),
            "order_count": len(orders),
        }

    # Fetch parallel
    curr_data, yoy_data = await asyncio.gather(
        asyncio.gather(*[_summary(p) for p in periods]),
        asyncio.gather(*[_summary(p) for p in yoy_periods]),
    )
    # Gabungkan yoy ke curr_data
    yoy_map = {y["period"]: y for y in yoy_data}
    for i, row in enumerate(curr_data):
        yoy_row = yoy_map.get(yoy_periods[i], {})
        row["yoy_period"] = yoy_periods[i]
        row["yoy_revenue"] = yoy_row.get("revenue", 0)
        row["yoy_net_profit"] = yoy_row.get("net_profit", 0)
        # Growth %
        base_rev = row["yoy_revenue"]
        base_np = row["yoy_net_profit"]
        row["revenue_growth_pct"] = round(((row["revenue"] - base_rev) / abs(base_rev) * 100) if base_rev != 0 else 0, 2) if base_rev != 0 else None
        row["net_profit_growth_pct"] = round(((row["net_profit"] - base_np) / abs(base_np) * 100) if base_np != 0 else 0, 2) if base_np != 0 else None
    # Rangkuman total periode
    total_revenue = sum(r["revenue"] for r in curr_data)
    total_net = sum(r["net_profit"] for r in curr_data)
    total_yoy_revenue = sum(r["yoy_revenue"] for r in curr_data)
    total_yoy_net = sum(r["yoy_net_profit"] for r in curr_data)
    return {
        "months": months,
        "periods": periods,
        "data": curr_data,
        "totals": {
            "revenue": round(total_revenue, 2),
            "net_profit": round(total_net, 2),
            "yoy_revenue": round(total_yoy_revenue, 2),
            "yoy_net_profit": round(total_yoy_net, 2),
            "revenue_growth_pct": round(((total_revenue - total_yoy_revenue) / abs(total_yoy_revenue) * 100) if total_yoy_revenue != 0 else 0, 2) if total_yoy_revenue != 0 else None,
            "net_profit_growth_pct": round(((total_net - total_yoy_net) / abs(total_yoy_net) * 100) if total_yoy_net != 0 else 0, 2) if total_yoy_net != 0 else None,
        },
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



# ---------------- Purchasing Module ----------------
class SupplierIn(BaseModel):
    name: str
    phone: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    contact_person: Optional[str] = None
    category: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True


class POItemIn(BaseModel):
    material_id: str
    quantity: float
    unit_price: float


class PurchaseOrderIn(BaseModel):
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None  # jika supplier belum di-master
    po_no: Optional[str] = None
    date: str  # ISO YYYY-MM-DD
    items: List[POItemIn] = []
    tax_pct: float = 0
    notes: Optional[str] = None
    invoice_no: Optional[str] = None


PO_STATUS = ["draft", "diterima", "batal"]
PAY_STATUS = ["belum_lunas", "sebagian", "lunas"]


async def _next_po_no() -> str:
    today = datetime.now(timezone.utc).date()
    prefix = f"PO-{today.strftime('%Y%m')}-"
    count = await db.purchase_orders.count_documents({"po_no": {"$regex": f"^{re.escape(prefix)}"}})
    return f"{prefix}{count + 1:04d}"


# ----- Supplier CRUD -----
@api_router.get("/purchasing/suppliers")
async def sup_list(user: dict = Depends(require_super_admin)):
    items = await db.suppliers.find({}, {"_id": 0}).sort("name", 1).to_list(length=5000)
    # Enrich dgn agregat PO
    pos = await db.purchase_orders.find({}, {"_id": 0, "supplier_id": 1, "total": 1, "status": 1, "payment_status": 1, "amount_paid": 1}).to_list(length=20000)
    agg: Dict[str, Dict[str, Any]] = {}
    for p in pos:
        sid = p.get("supplier_id")
        if not sid or p.get("status") == "batal":
            continue
        row = agg.setdefault(sid, {"po_count": 0, "total_purchase": 0.0, "outstanding": 0.0})
        row["po_count"] += 1
        total = float(p.get("total", 0))
        paid = float(p.get("amount_paid", 0))
        row["total_purchase"] += total
        if p.get("payment_status") != "lunas":
            row["outstanding"] += max(total - paid, 0)
    for s in items:
        a = agg.get(s.get("id")) or {}
        s["po_count"] = a.get("po_count", 0)
        s["total_purchase"] = round(a.get("total_purchase", 0), 2)
        s["outstanding"] = round(a.get("outstanding", 0), 2)
    return items


@api_router.post("/purchasing/suppliers")
async def sup_create(payload: SupplierIn, user: dict = Depends(require_super_admin)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Nama supplier wajib diisi")
    safe = re.escape(payload.name.strip())
    exists = await db.suppliers.find_one({"name": {"$regex": f"^{safe}$", "$options": "i"}})
    if exists:
        raise HTTPException(status_code=400, detail="Supplier dengan nama tersebut sudah ada")
    doc = payload.model_dump()
    doc["name"] = payload.name.strip()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.suppliers.insert_one(doc)
    await _upsert_category("supplier", doc.get("category"))
    doc.pop("_id", None)
    return doc


@api_router.put("/purchasing/suppliers/{sid}")
async def sup_update(sid: str, payload: SupplierIn, user: dict = Depends(require_super_admin)):
    existing = await db.suppliers.find_one({"id": sid})
    if not existing:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    new_name = payload.name.strip()
    if new_name.lower() != (existing.get("name") or "").lower():
        safe = re.escape(new_name)
        dup = await db.suppliers.find_one({"name": {"$regex": f"^{safe}$", "$options": "i"}, "id": {"$ne": sid}})
        if dup:
            raise HTTPException(status_code=400, detail="Supplier dengan nama tersebut sudah ada")
    upd = payload.model_dump()
    upd["name"] = new_name
    upd["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.suppliers.update_one({"id": sid}, {"$set": upd})
    await _upsert_category("supplier", upd.get("category"))
    return await db.suppliers.find_one({"id": sid}, {"_id": 0})


@api_router.delete("/purchasing/suppliers/{sid}")
async def sup_delete(sid: str, user: dict = Depends(require_super_admin)):
    existing = await db.suppliers.find_one({"id": sid})
    if not existing:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    has_po = await db.purchase_orders.find_one({"supplier_id": sid})
    if has_po:
        await db.suppliers.update_one({"id": sid}, {"$set": {"active": False, "updated_at": datetime.now(timezone.utc).isoformat()}})
        return {"ok": True, "soft_deleted": True}
    await db.suppliers.delete_one({"id": sid})
    return {"ok": True, "soft_deleted": False}


# ----- Purchase Order CRUD -----
async def _enrich_po(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    mats = {m["id"]: m async for m in db.materials.find({}, {"_id": 0})}
    for po in items:
        for it in po.get("items") or []:
            mat = mats.get(it.get("material_id")) or {}
            it["material_name"] = mat.get("name") or "-"
            it["material_unit"] = mat.get("unit") or ""
    return items


@api_router.get("/purchasing/purchase-orders")
async def po_list(user: dict = Depends(require_super_admin), status: Optional[str] = None, payment_status: Optional[str] = None):
    q = {}
    if status:
        q["status"] = status
    if payment_status:
        q["payment_status"] = payment_status
    items = await db.purchase_orders.find(q, {"_id": 0}).sort("created_at", -1).to_list(length=5000)
    return await _enrich_po(items)


@api_router.post("/purchasing/purchase-orders")
async def po_create(payload: PurchaseOrderIn, user: dict = Depends(require_super_admin)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="PO harus memiliki minimal 1 item bahan")
    supplier_name = payload.supplier_name
    if payload.supplier_id:
        sup = await db.suppliers.find_one({"id": payload.supplier_id})
        if not sup:
            raise HTTPException(status_code=400, detail="Supplier tidak ditemukan")
        supplier_name = sup.get("name")
    if not supplier_name:
        raise HTTPException(status_code=400, detail="Supplier wajib diisi")
    items_out = []
    subtotal = 0.0
    for it in payload.items:
        mat = await db.materials.find_one({"id": it.material_id})
        if not mat:
            raise HTTPException(status_code=400, detail=f"Bahan {it.material_id} tidak ditemukan")
        if it.quantity <= 0 or it.unit_price < 0:
            raise HTTPException(status_code=400, detail=f"Qty & harga bahan {mat.get('name')} tidak valid")
        line_total = round(float(it.quantity) * float(it.unit_price), 2)
        items_out.append({
            "material_id": it.material_id,
            "quantity": float(it.quantity),
            "unit_price": float(it.unit_price),
            "total": line_total,
        })
        subtotal += line_total
    tax = round(subtotal * float(payload.tax_pct or 0) / 100, 2)
    total = round(subtotal + tax, 2)
    po_no = payload.po_no or await _next_po_no()
    doc = {
        "id": str(uuid.uuid4()),
        "po_no": po_no,
        "supplier_id": payload.supplier_id,
        "supplier_name": supplier_name,
        "date": payload.date,
        "items": items_out,
        "subtotal": round(subtotal, 2),
        "tax_pct": float(payload.tax_pct or 0),
        "tax_amount": tax,
        "total": total,
        "status": "draft",
        "payment_status": "belum_lunas",
        "amount_paid": 0.0,
        "invoice_no": payload.invoice_no,
        "notes": payload.notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user.get("email"),
    }
    await db.purchase_orders.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.put("/purchasing/purchase-orders/{po_id}/receive")
async def po_receive(po_id: str, user: dict = Depends(require_super_admin)):
    """Tandai PO diterima → auto-buat stock_in entry per item + update material stok & harga beli terbaru."""
    po = await db.purchase_orders.find_one({"id": po_id})
    if not po:
        raise HTTPException(status_code=404, detail="PO tidak ditemukan")
    if po.get("status") == "diterima":
        return {"ok": True, "already": True}
    if po.get("status") == "batal":
        raise HTTPException(status_code=400, detail="PO sudah dibatalkan")
    now = datetime.now(timezone.utc).isoformat()
    for it in po.get("items") or []:
        mat = await db.materials.find_one({"id": it["material_id"]})
        if not mat:
            continue
        qty = float(it["quantity"])
        unit_price = float(it["unit_price"])
        # Insert stock_in entry
        si_doc = {
            "id": str(uuid.uuid4()),
            "material_id": it["material_id"],
            "quantity": qty,
            "unit_price": unit_price,
            "total_price": round(qty * unit_price, 2),
            "supplier": po.get("supplier_name"),
            "invoice_no": po.get("invoice_no") or po.get("po_no"),
            "date": po.get("date"),
            "notes": f"Auto dari PO {po.get('po_no')}",
            "po_id": po_id,
            "po_no": po.get("po_no"),
            "created_at": now,
            "created_by": user.get("email"),
        }
        await db.stock_in.insert_one(si_doc)
        # Update material stok & harga beli
        new_stock = round(float(mat.get("current_stock", 0)) + qty, 4)
        await db.materials.update_one(
            {"id": it["material_id"]},
            {"$set": {"current_stock": new_stock, "purchase_price": unit_price, "updated_at": now}},
        )
    await db.purchase_orders.update_one(
        {"id": po_id},
        {"$set": {"status": "diterima", "received_at": now, "received_by": user.get("email")}},
    )
    return {"ok": True, "received_at": now}


@api_router.put("/purchasing/purchase-orders/{po_id}/cancel")
async def po_cancel(po_id: str, user: dict = Depends(require_super_admin)):
    po = await db.purchase_orders.find_one({"id": po_id})
    if not po:
        raise HTTPException(status_code=404, detail="PO tidak ditemukan")
    if po.get("status") == "diterima":
        raise HTTPException(status_code=400, detail="PO sudah diterima, batalkan penerimaan dulu bila perlu")
    await db.purchase_orders.update_one({"id": po_id}, {"$set": {"status": "batal", "cancelled_at": datetime.now(timezone.utc).isoformat()}})
    return {"ok": True}


@api_router.put("/purchasing/purchase-orders/{po_id}/pay")
async def po_pay(po_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(require_super_admin)):
    amount = float(payload.get("amount", 0))
    if amount < 0:
        raise HTTPException(status_code=400, detail="Jumlah pembayaran tidak valid")
    po = await db.purchase_orders.find_one({"id": po_id})
    if not po:
        raise HTTPException(status_code=404, detail="PO tidak ditemukan")
    new_paid = round(float(po.get("amount_paid", 0)) + amount, 2)
    total = float(po.get("total", 0))
    if new_paid >= total:
        new_paid = total
        payment_status = "lunas"
    elif new_paid > 0:
        payment_status = "sebagian"
    else:
        payment_status = "belum_lunas"
    await db.purchase_orders.update_one(
        {"id": po_id},
        {"$set": {"amount_paid": new_paid, "payment_status": payment_status, "last_payment_at": datetime.now(timezone.utc).isoformat()}},
    )
    # Auto-insert ke Kas Operasional (Pengeluaran Bayar Utang Usaha)
    if amount > 0:
        try:
            await _insert_cash_transaction(
                account_code="201",
                description=f"Bayar PO {po.get('po_no', po_id)} — {po.get('supplier_name', '')}".strip(" —"),
                amount=amount,
                reference=po.get("po_no") or po_id,
                date_iso=datetime.now(timezone.utc).date().isoformat(),
                auto=True,
                created_by=user.get("email"),
            )
        except Exception as ex:
            logger.warning(f"Cashbook auto-insert (PO payment) failed: {ex}")
    doc = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
    return doc


@api_router.delete("/purchasing/purchase-orders/{po_id}")
async def po_delete(po_id: str, user: dict = Depends(require_super_admin)):
    po = await db.purchase_orders.find_one({"id": po_id})
    if not po:
        raise HTTPException(status_code=404, detail="PO tidak ditemukan")
    if po.get("status") == "diterima":
        # Rollback stock_in entries + kurangi stok
        si_docs = await db.stock_in.find({"po_id": po_id}, {"_id": 0}).to_list(length=1000)
        for si in si_docs:
            mat = await db.materials.find_one({"id": si["material_id"]})
            if mat:
                new_stock = round(float(mat.get("current_stock", 0)) - float(si.get("quantity", 0)), 4)
                await db.materials.update_one({"id": si["material_id"]}, {"$set": {"current_stock": new_stock, "updated_at": datetime.now(timezone.utc).isoformat()}})
        await db.stock_in.delete_many({"po_id": po_id})
    # Rollback cash transactions AUTO yang dibuat dari pembayaran PO ini
    po_no = po.get("po_no")
    if po_no:
        await db.cash_transactions.delete_many({"reference": po_no, "auto": True, "account_code": "201"})
    await db.purchase_orders.delete_one({"id": po_id})
    return {"ok": True}


# ----- Price History -----
@api_router.get("/purchasing/price-history")
async def price_history(material_id: Optional[str] = None, user: dict = Depends(require_super_admin)):
    """Riwayat harga beli — dari stock_in (semua sumber: manual + auto-PO)."""
    q = {}
    if material_id:
        q["material_id"] = material_id
    items = await db.stock_in.find(q, {"_id": 0}).sort("date", 1).to_list(length=10000)
    items = await _enrich_with_material(items)
    # Group by material — return per material terpisah bila material_id tidak diisi
    grouped: Dict[str, Dict[str, Any]] = {}
    for it in items:
        mid = it.get("material_id")
        if not mid:
            continue
        g = grouped.setdefault(mid, {
            "material_id": mid,
            "material_name": it.get("material_name"),
            "material_unit": it.get("material_unit"),
            "history": [],
        })
        g["history"].append({
            "date": it.get("date"),
            "unit_price": float(it.get("unit_price", 0)),
            "quantity": float(it.get("quantity", 0)),
            "supplier": it.get("supplier"),
            "po_no": it.get("po_no"),
            "invoice_no": it.get("invoice_no"),
        })
    # Hitung min/max/avg + first/last
    result = []
    for g in grouped.values():
        hist = g["history"]
        prices = [h["unit_price"] for h in hist]
        g["min_price"] = round(min(prices), 2) if prices else 0
        g["max_price"] = round(max(prices), 2) if prices else 0
        g["avg_price"] = round(sum(prices) / len(prices), 2) if prices else 0
        g["current_price"] = hist[-1]["unit_price"] if hist else 0
        g["first_price"] = hist[0]["unit_price"] if hist else 0
        g["change_pct"] = round(((g["current_price"] - g["first_price"]) / g["first_price"] * 100), 2) if g["first_price"] > 0 else 0
        result.append(g)
    result.sort(key=lambda x: x.get("material_name") or "")
    return {"count": len(result), "items": result}


# ----- Purchasing Stats -----
@api_router.get("/purchasing/stats")
async def purchasing_stats(user: dict = Depends(require_super_admin)):
    pos = await db.purchase_orders.find({}, {"_id": 0}).to_list(length=20000)
    total_po = len(pos)
    total_purchase = sum(float(p.get("total", 0)) for p in pos if p.get("status") != "batal")
    outstanding = 0.0
    unpaid_pos = 0
    for p in pos:
        if p.get("status") == "batal":
            continue
        if p.get("payment_status") != "lunas":
            outstanding += max(float(p.get("total", 0)) - float(p.get("amount_paid", 0)), 0)
            if p.get("payment_status") == "belum_lunas":
                unpaid_pos += 1
    total_suppliers = await db.suppliers.count_documents({"active": True})
    return {
        "total_po": total_po,
        "total_purchase": round(total_purchase, 2),
        "outstanding": round(outstanding, 2),
        "unpaid_pos": unpaid_pos,
        "total_suppliers": total_suppliers,
    }



# ---------------- Sales / POS Module ----------------
# Master Produk dengan BOM (Bill of Materials)
PRODUCT_FORMULAS = ("fixed", "per_qty", "area", "length")

class ProductComponent(BaseModel):
    material_id: str
    formula: str  # "fixed" | "per_qty" | "area" | "length"
    quantity: float = 1.0  # faktor konsumsi (untuk tier A / non-size / S-XL)
    # NEW: konsumsi untuk tier B (XXL keatas). None = pakai quantity yg sama
    quantity_size_b: Optional[float] = None

class ProductIn(BaseModel):
    code: Optional[str] = None
    name: str
    category: Optional[str] = None
    pricing_mode: str = "fixed"  # "fixed" (per unit) | "per_area" (per m²)
    unit_price: float = 0  # harga jual default (dipakai bila has_sizes=False)
    purchase_price: float = 0  # harga beli / modal per unit (opsional, bisa auto dari BOM)
    current_stock: float = 0  # stok produk jadi (untuk finished goods yang di-stok)
    components: List[ProductComponent] = []
    active: bool = True
    # NEW: sizing untuk produk kaos/jersey
    has_sizes: bool = False
    sizes: List[str] = []  # subset dari ["S","M","L","XL","XXL","XXXL"]
    price_size_a: float = 0  # harga untuk S–XL (dipakai kalau has_sizes=True)
    price_size_b: float = 0  # harga untuk XXL keatas
    # NEW: panjang per pcs (meter) — dipakai di Laporan Penjualan untuk hitung total meter
    length_meter: float = 0  # 0 = tidak ada info panjang (mis. produk non-linear seperti kaos)


# Klasifikasi tier size
SIZE_TIER_A = {"S", "M", "L", "XL"}
# Everything else (XXL, XXXL, 2XL, 3XL, dsb) = tier B


def _size_tier(size: Optional[str]) -> str:
    """Return 'A' untuk S-XL, 'B' untuk XXL+ atau default 'A' bila tidak ada."""
    if not size:
        return "A"
    return "A" if size.strip().upper() in SIZE_TIER_A else "B"


def _product_requires_dimensions(components: List[Dict[str, Any]]) -> bool:
    return any(c.get("formula") in ("area", "length") for c in components)


async def _enrich_product(p: Dict[str, Any]) -> Dict[str, Any]:
    """Isi snapshot material_name & material_unit ke tiap component. Compute bom_cost & stock_value."""
    if not p:
        return p
    bom_cost = 0.0
    for c in p.get("components", []):
        mat = await db.materials.find_one({"id": c.get("material_id")}, {"_id": 0, "name": 1, "unit": 1, "current_stock": 1, "purchase_price": 1})
        if mat:
            c["material_name"] = mat.get("name")
            c["material_unit"] = mat.get("unit")
            c["material_stock"] = mat.get("current_stock")
            c["material_purchase_price"] = mat.get("purchase_price", 0)
        else:
            c["material_name"] = "(bahan dihapus)"
            c["material_unit"] = ""
            c["material_stock"] = 0
            c["material_purchase_price"] = 0
        # BOM cost per unit produk (untuk formula per_qty & fixed cukup faktor × harga beli)
        # Untuk area/length butuh dimensi standard — kita hitung per unit dasar (asumsi 1m²/1m)
        factor = float(c.get("quantity", 1) or 1)
        buy = float(c.get("material_purchase_price", 0) or 0)
        formula = c.get("formula", "")
        if formula in ("fixed", "per_qty"):
            bom_cost += factor * buy
        elif formula in ("area", "length"):
            # Cost per 1m² atau 1m (sebagai reference); pengguna bisa hitung berdasar ukuran actual
            bom_cost += factor * buy
    p["requires_dimensions"] = _product_requires_dimensions(p.get("components", []))
    p["bom_cost"] = round(bom_cost, 2)  # modal bahan per unit (reference)
    p["stock_value"] = round(float(p.get("current_stock", 0) or 0) * float(p.get("purchase_price", 0) or 0), 2)
    return p


def _compute_component_consumption(
    formula: str, factor: float, length_m: float, width_m: float, qty: int
) -> float:
    """Hitung konsumsi bahan untuk 1 component sale."""
    f = (formula or "").lower()
    factor = float(factor or 0)
    q = int(qty or 0)
    if f == "fixed":
        return round(factor, 4)
    if f == "per_qty":
        return round(factor * q, 4)
    if f == "area":
        return round(factor * float(length_m or 0) * float(width_m or 0) * q, 4)
    if f == "length":
        return round(factor * float(length_m or 0) * q, 4)
    return 0.0


@api_router.get("/products")
async def products_list(user: dict = Depends(require_super_admin), only_active: bool = False):
    q: Dict[str, Any] = {}
    if only_active:
        q["active"] = {"$ne": False}
    items = await db.products.find(q, {"_id": 0}).sort("name", 1).to_list(length=2000)
    for p in items:
        await _enrich_product(p)
    return items


@api_router.get("/products/{product_id}")
async def products_get(product_id: str, user: dict = Depends(require_super_admin)):
    p = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    await _enrich_product(p)
    return p


@api_router.post("/products")
async def products_create(payload: ProductIn, user: dict = Depends(require_super_admin)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Nama produk wajib")
    if payload.pricing_mode not in ("fixed", "per_area"):
        raise HTTPException(status_code=400, detail="pricing_mode harus 'fixed' atau 'per_area'")
    if payload.unit_price < 0:
        raise HTTPException(status_code=400, detail="Harga tidak boleh negatif")
    for c in payload.components:
        if c.formula not in PRODUCT_FORMULAS:
            raise HTTPException(status_code=400, detail=f"Formula '{c.formula}' tidak valid. Pilih: {PRODUCT_FORMULAS}")
        if c.quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity komponen harus > 0")
        m = await db.materials.find_one({"id": c.material_id})
        if not m:
            raise HTTPException(status_code=400, detail=f"Bahan {c.material_id} tidak ditemukan")
    # Validasi sizing
    if payload.has_sizes:
        if not payload.sizes:
            raise HTTPException(status_code=400, detail="Pilih minimal 1 ukuran untuk produk ini")
        if payload.price_size_a <= 0:
            raise HTTPException(status_code=400, detail="Harga S-XL harus > 0")
        has_tier_b = any(_size_tier(s) == "B" for s in payload.sizes)
        if has_tier_b and payload.price_size_b <= 0:
            raise HTTPException(status_code=400, detail="Harga XXL keatas harus > 0")
    # Cek duplicate nama
    safe = re.escape(payload.name.strip())
    exists = await db.products.find_one({"name": {"$regex": f"^{safe}$", "$options": "i"}})
    if exists:
        raise HTTPException(status_code=400, detail="Produk dengan nama tersebut sudah ada")
    doc = {
        "id": str(uuid.uuid4()),
        "code": (payload.code or "").strip() or None,
        "name": payload.name.strip(),
        "category": (payload.category or "").strip() or None,
        "pricing_mode": payload.pricing_mode,
        "unit_price": round(float(payload.unit_price), 2),
        "purchase_price": round(float(payload.purchase_price or 0), 2),
        "current_stock": round(float(payload.current_stock or 0), 4),
        "components": [c.model_dump() for c in payload.components],
        "active": payload.active,
        # Sizing (kaos/jersey)
        "has_sizes": bool(payload.has_sizes),
        "sizes": list(payload.sizes) if payload.has_sizes else [],
        "price_size_a": round(float(payload.price_size_a or 0), 2) if payload.has_sizes else 0,
        "price_size_b": round(float(payload.price_size_b or 0), 2) if payload.has_sizes else 0,
        "length_meter": round(float(payload.length_meter or 0), 4),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.products.insert_one(doc)
    await _upsert_category("product", doc.get("category"))
    doc.pop("_id", None)
    await _enrich_product(doc)
    return doc


@api_router.put("/products/{product_id}")
async def products_update(product_id: str, payload: ProductIn, user: dict = Depends(require_super_admin)):
    existing = await db.products.find_one({"id": product_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    if payload.pricing_mode not in ("fixed", "per_area"):
        raise HTTPException(status_code=400, detail="pricing_mode harus 'fixed' atau 'per_area'")
    for c in payload.components:
        if c.formula not in PRODUCT_FORMULAS:
            raise HTTPException(status_code=400, detail=f"Formula '{c.formula}' tidak valid")
        if c.quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity komponen harus > 0")
        m = await db.materials.find_one({"id": c.material_id})
        if not m:
            raise HTTPException(status_code=400, detail=f"Bahan {c.material_id} tidak ditemukan")
    # Validasi sizing
    if payload.has_sizes:
        if not payload.sizes:
            raise HTTPException(status_code=400, detail="Pilih minimal 1 ukuran untuk produk ini")
        if payload.price_size_a <= 0:
            raise HTTPException(status_code=400, detail="Harga S-XL harus > 0")
        has_tier_b = any(_size_tier(s) == "B" for s in payload.sizes)
        if has_tier_b and payload.price_size_b <= 0:
            raise HTTPException(status_code=400, detail="Harga XXL keatas harus > 0")
    upd = {
        "code": (payload.code or "").strip() or None,
        "name": payload.name.strip(),
        "category": (payload.category or "").strip() or None,
        "pricing_mode": payload.pricing_mode,
        "unit_price": round(float(payload.unit_price), 2),
        "purchase_price": round(float(payload.purchase_price or 0), 2),
        "current_stock": round(float(payload.current_stock or 0), 4),
        "components": [c.model_dump() for c in payload.components],
        "active": payload.active,
        # Sizing
        "has_sizes": bool(payload.has_sizes),
        "sizes": list(payload.sizes) if payload.has_sizes else [],
        "price_size_a": round(float(payload.price_size_a or 0), 2) if payload.has_sizes else 0,
        "price_size_b": round(float(payload.price_size_b or 0), 2) if payload.has_sizes else 0,
        "length_meter": round(float(payload.length_meter or 0), 4),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.products.update_one({"id": product_id}, {"$set": upd})
    await _upsert_category("product", upd.get("category"))
    doc = await db.products.find_one({"id": product_id}, {"_id": 0})
    await _enrich_product(doc)
    return doc


@api_router.delete("/products/{product_id}")
async def products_delete(product_id: str, user: dict = Depends(require_super_admin)):
    existing = await db.products.find_one({"id": product_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    used = await db.sales.count_documents({"items.product_id": product_id})
    if used > 0:
        raise HTTPException(status_code=400, detail=f"Produk masih dipakai di {used} transaksi. Non-aktifkan saja.")
    await db.products.delete_one({"id": product_id})
    return {"ok": True}


class SaleItemIn(BaseModel):
    # MODE 1 (backward compat): pilih material langsung
    material_id: Optional[str] = None
    # MODE 2 (baru): pilih product dengan BOM
    product_id: Optional[str] = None
    product_name: str  # nama produk/jasa (mis. "Banner 3x2m", "Slayer")
    length_m: float = 0
    width_m: float = 0
    quantity: int = 1
    unit_price: float  # harga per m² (mode material) ATAU harga per unit (mode product fixed) ATAU per m² (product per_area)
    size: Optional[str] = None  # NEW: untuk produk yang has_sizes (S/M/L/XL/XXL/XXXL)


class SaleIn(BaseModel):
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    items: List[SaleItemIn] = []
    discount: float = 0
    cash_paid: float = 0
    payment_method: str = "cash"  # cash | transfer | shopee_plaza | shopee_kastem
    payment_bank: Optional[str] = None  # BCA | Mandiri (khusus transfer)
    payment_notes: Optional[str] = None  # keterangan tambahan (khusus transfer)
    notes: Optional[str] = None


# Mapping payment method → account_code untuk auto cash tx
PAYMENT_ACCOUNT_MAP = {
    "cash": "301",             # Penjualan Tunai (existing)
    "transfer_bca": "301-BCA", # Transfer BCA
    "transfer_mandiri": "301-MDR",
    "shopee_plaza": "301-SPP",
    "shopee_kastem": "301-SPK",
}


def _resolve_payment_account(payment_method: str, payment_bank: Optional[str] = None) -> Tuple[str, str]:
    """Return (account_code, human_label) untuk auto cash tx."""
    pm = (payment_method or "cash").lower()
    if pm == "transfer":
        b = (payment_bank or "").strip().lower()
        if b == "mandiri":
            return ("301-MDR", "Transfer Mandiri")
        return ("301-BCA", "Transfer BCA")
    if pm == "shopee_plaza":
        return ("301-SPP", "Shopee Plaza")
    if pm == "shopee_kastem":
        return ("301-SPK", "Shopee Kastem")
    if pm in ("cash", "tunai"):
        return ("301", "Penjualan Tunai")
    # Fallback (legacy "tunai" atau lainnya)
    return ("301", "Penjualan Tunai")


async def _next_sale_no() -> str:
    today = datetime.now(timezone.utc).date()
    prefix = f"NOTA-{today.strftime('%Y%m%d')}-"
    count = await db.sales.count_documents({"sale_no": {"$regex": f"^{re.escape(prefix)}"}})
    return f"{prefix}{count + 1:04d}"


def _company_info() -> Dict[str, str]:
    return {
        "name": os.environ.get("COMPANY_NAME", "PLAZAKREASI DIGITAL PRINTING"),
        "address": os.environ.get("COMPANY_ADDRESS", "Jl. Ruko Sentralan B72 Driyorejo Gresik"),
        "phone": os.environ.get("COMPANY_PHONE", "081235598288"),
    }


@api_router.get("/sales")
async def sales_list(
    user: dict = Depends(require_super_admin),
    limit: int = 200,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    q: Optional[str] = None,
    paginate: bool = False,
):
    """Return either plain list (backward compat) atau {items,total,page,page_size,pages} bila paginate=true."""
    query: Dict[str, Any] = {}
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        query["date"] = rng
    if q and q.strip():
        safe = re.escape(q.strip())
        query["$or"] = [
            {"sale_no": {"$regex": safe, "$options": "i"}},
            {"customer_name": {"$regex": safe, "$options": "i"}},
            {"customer_phone": {"$regex": safe, "$options": "i"}},
        ]
    if paginate:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        total = await db.sales.count_documents(query)
        skip = (page - 1) * page_size
        items = await db.sales.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(page_size).to_list(length=page_size)
        pages = (total + page_size - 1) // page_size if page_size else 0
        return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}
    # Backward-compat: plain list
    items = await db.sales.find(query, {"_id": 0}).sort("created_at", -1).to_list(length=max(1, min(limit, 2000)))
    return items


@api_router.get("/sales/{sale_id}")
async def sales_get(sale_id: str, user: dict = Depends(require_super_admin)):
    s = await db.sales.find_one({"id": sale_id}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    return s


async def _build_and_persist_sale(
    payload: SaleIn,
    user: dict,
    *,
    sale_no: Optional[str] = None,
    sale_id: Optional[str] = None,
    created_at_iso: Optional[str] = None,
    date_iso: Optional[str] = None,
    is_update: bool = False,
) -> Dict[str, Any]:
    """Compute + validate + persist a sale (create atau update).
    Untuk update, pastikan rollback stok+cash sudah dilakukan SEBELUM memanggil helper ini."""
    if not payload.items:
        raise HTTPException(status_code=400, detail="Item transaksi tidak boleh kosong")
    items_out: List[Dict[str, Any]] = []
    subtotal = 0.0
    stock_deductions: Dict[str, float] = {}
    material_cache: Dict[str, Dict[str, Any]] = {}

    async def _get_mat(mid: str) -> Dict[str, Any]:
        if mid in material_cache:
            return material_cache[mid]
        m = await db.materials.find_one({"id": mid})
        if not m:
            raise HTTPException(status_code=400, detail="Bahan tidak ditemukan")
        material_cache[mid] = m
        return m

    for it in payload.items:
        if it.quantity <= 0:
            raise HTTPException(status_code=400, detail=f"Qty {it.product_name} harus > 0")
        if it.product_id:
            prod = await db.products.find_one({"id": it.product_id}, {"_id": 0})
            if not prod:
                raise HTTPException(status_code=400, detail="Produk tidak ditemukan")
            components = prod.get("components") or []
            needs_dim = any(c.get("formula") in ("area", "length") for c in components)
            if needs_dim and (it.length_m <= 0 or it.width_m <= 0):
                bad = any(c.get("formula") == "area" for c in components) and (it.length_m <= 0 or it.width_m <= 0)
                bad_len = any(c.get("formula") == "length" for c in components) and it.length_m <= 0
                if bad or bad_len:
                    raise HTTPException(status_code=400, detail=f"Ukuran P×L wajib diisi untuk {it.product_name}")
            has_sizes = bool(prod.get("has_sizes"))
            size_tier = "A"
            size_used = None
            if has_sizes:
                if not it.size:
                    raise HTTPException(status_code=400, detail=f"Ukuran wajib dipilih untuk {it.product_name}")
                available = prod.get("sizes") or []
                if it.size not in available:
                    raise HTTPException(status_code=400, detail=f"Ukuran '{it.size}' tidak tersedia untuk {it.product_name}. Pilihan: {', '.join(available)}")
                size_used = it.size
                size_tier = _size_tier(it.size)
            pricing = prod.get("pricing_mode") or "fixed"
            if has_sizes:
                unit_price_use = float(prod.get("price_size_b", 0) if size_tier == "B" else prod.get("price_size_a", 0))
                if unit_price_use <= 0:
                    unit_price_use = float(prod.get("unit_price", 0))
            else:
                unit_price_use = float(it.unit_price if it.unit_price > 0 else prod.get("unit_price", 0))
            if pricing == "per_area":
                area_pc = float(it.length_m or 0) * float(it.width_m or 0)
                area_total = round(area_pc * int(it.quantity), 4)
                line_subtotal = round(area_total * unit_price_use, 2)
            else:
                area_pc = float(it.length_m or 0) * float(it.width_m or 0)
                area_total = round(area_pc * int(it.quantity), 4)
                line_subtotal = round(unit_price_use * int(it.quantity), 2)
            item_components = []
            for c in components:
                factor_use = float(c.get("quantity", 1) or 0)
                if has_sizes and size_tier == "B":
                    qsb = c.get("quantity_size_b")
                    if qsb is not None:
                        factor_use = float(qsb or 0)
                cons = _compute_component_consumption(
                    c["formula"], factor_use, it.length_m, it.width_m, it.quantity,
                )
                mat = await _get_mat(c["material_id"])
                stock_deductions[c["material_id"]] = stock_deductions.get(c["material_id"], 0) + cons
                item_components.append({
                    "material_id": c["material_id"],
                    "material_name": mat.get("name"),
                    "material_unit": mat.get("unit"),
                    "formula": c["formula"],
                    "factor": factor_use,
                    "consumption": cons,
                })
            items_out.append({
                "product_id": it.product_id,
                "product_code": prod.get("code"),
                "product_name": it.product_name or prod.get("name"),
                "product_pricing_mode": pricing,
                "length_m": float(it.length_m or 0),
                "width_m": float(it.width_m or 0),
                "quantity": int(it.quantity),
                "area_per_pc": round(area_pc, 4),
                "area_total": area_total,
                "unit_price": unit_price_use,
                "subtotal": line_subtotal,
                "components": item_components,
                "size": size_used,
                "size_tier": size_tier if has_sizes else None,
                "material_id": None,
                "material_name": ", ".join(c["material_name"] for c in item_components) or "-",
                "material_unit": item_components[0]["material_unit"] if item_components else "",
            })
            subtotal += line_subtotal
        else:
            if not it.material_id:
                raise HTTPException(status_code=400, detail=f"{it.product_name}: pilih Produk atau Bahan")
            if it.length_m <= 0 or it.width_m <= 0:
                raise HTTPException(status_code=400, detail=f"Ukuran P×L {it.product_name} harus > 0")
            mat = await _get_mat(it.material_id)
            area_per_pc = float(it.length_m) * float(it.width_m)
            area_total = round(area_per_pc * int(it.quantity), 4)
            line_subtotal = round(area_total * float(it.unit_price), 2)
            stock_deductions[it.material_id] = stock_deductions.get(it.material_id, 0) + area_total
            items_out.append({
                "material_id": it.material_id,
                "material_name": mat.get("name"),
                "material_unit": mat.get("unit"),
                "product_id": None,
                "product_name": it.product_name,
                "length_m": float(it.length_m),
                "width_m": float(it.width_m),
                "quantity": int(it.quantity),
                "area_per_pc": round(area_per_pc, 4),
                "area_total": area_total,
                "unit_price": float(it.unit_price),
                "subtotal": line_subtotal,
                "components": [{
                    "material_id": it.material_id,
                    "material_name": mat.get("name"),
                    "material_unit": mat.get("unit"),
                    "formula": "area",
                    "factor": 1.0,
                    "consumption": area_total,
                }],
            })
            subtotal += line_subtotal

    # Validasi stok
    for mid, total_needed in stock_deductions.items():
        mat = material_cache.get(mid) or await _get_mat(mid)
        current = float(mat.get("current_stock", 0))
        if total_needed > current + 1e-6:
            raise HTTPException(
                status_code=400,
                detail=f"Stok {mat.get('name')} tidak cukup (butuh {round(total_needed, 4)} {mat.get('unit')}, tersedia {round(current, 4)})",
            )

    discount = float(payload.discount or 0)
    total = round(subtotal - discount, 2)
    cash_paid = float(payload.cash_paid or 0)
    if cash_paid < 0:
        raise HTTPException(status_code=400, detail="Nominal diterima tidak boleh negatif")
    # DP support: jika cash_paid < total, sisanya jadi piutang (Sisa Tagihan)
    sisa_tagihan = round(max(0.0, total - cash_paid), 2)
    change = round(max(0.0, cash_paid - total), 2)
    payment_status = "dp" if sisa_tagihan > 0.01 else "paid"
    now = datetime.now(timezone.utc)
    final_sale_no = sale_no or await _next_sale_no()
    final_id = sale_id or str(uuid.uuid4())
    final_created = created_at_iso or now.isoformat()
    final_date = date_iso or now.date().isoformat()
    doc = {
        "id": final_id,
        "sale_no": final_sale_no,
        "date": final_date,
        "customer_name": (payload.customer_name or "Umum").strip() or "Umum",
        "customer_phone": (payload.customer_phone or "").strip(),
        "cashier": user.get("email"),
        "cashier_name": user.get("name") or user.get("email"),
        "branch": _sanitize_branch(user.get("branch")),
        "items": items_out,
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "total": total,
        "cash_paid": round(cash_paid, 2),
        "change": change,
        "sisa_tagihan": sisa_tagihan,
        "payment_method": payload.payment_method or "cash",
        "payment_bank": (payload.payment_bank or "").strip() or None,
        "payment_notes": (payload.payment_notes or "").strip() or None,
        "notes": payload.notes,
        "status": payment_status,  # "paid" (LUNAS) atau "dp"
        "created_at": final_created,
    }
    if is_update:
        doc["updated_at"] = now.isoformat()
        doc["updated_by"] = user.get("email")
        await db.sales.update_one({"id": final_id}, {"$set": doc})
    else:
        await db.sales.insert_one(doc)
    # Auto cash tx — akun tergantung metode pembayaran
    # Auto cash tx — akun tergantung metode pembayaran. Untuk DP, hanya cash_paid yg masuk.
    cash_recorded = round(min(cash_paid, total), 2)  # exclude kembalian dari kas
    try:
        acc_code, acc_label = _resolve_payment_account(payload.payment_method, payload.payment_bank)
        desc = f"Penjualan {final_sale_no} — {doc['customer_name']} · {acc_label}"
        if payment_status == "dp":
            desc += f" · DP (sisa Rp {sisa_tagihan:,.0f})"
        if doc.get("payment_notes"):
            desc += f" ({doc['payment_notes']})"
        if cash_recorded > 0:
            await _insert_cash_transaction(
                account_code=acc_code,
                description=desc,
                amount=cash_recorded,
                reference=final_sale_no,
                date_iso=doc["date"],
                auto=True,
                created_by=user.get("email"),
            )
    except Exception as ex:
        logger.warning(f"Cashbook auto-insert (sale) failed: {ex}")
    # Apply stock deduction (net dari state saat ini)
    for mid, qty_used in stock_deductions.items():
        mat = material_cache.get(mid)
        if mat:
            new_stock = round(float(mat.get("current_stock", 0)) - float(qty_used), 4)
            await db.materials.update_one(
                {"id": mid},
                {"$set": {"current_stock": new_stock, "updated_at": now.isoformat()}},
            )
    doc.pop("_id", None)
    return doc


@api_router.post("/sales")
async def sales_create(payload: SaleIn, user: dict = Depends(require_super_admin)):
    return await _build_and_persist_sale(payload, user)


async def _rollback_sale_effects(sale: Dict[str, Any]) -> None:
    """Rollback stock deduction dan hapus auto cash transaction untuk sale ini."""
    rollback: Dict[str, float] = {}
    for it in sale.get("items") or []:
        comps = it.get("components")
        if comps:
            for c in comps:
                mid = c.get("material_id")
                if mid:
                    rollback[mid] = rollback.get(mid, 0) + float(c.get("consumption", 0))
        else:
            mid = it.get("material_id")
            if mid:
                rollback[mid] = rollback.get(mid, 0) + float(it.get("area_total", 0))
    now_iso = datetime.now(timezone.utc).isoformat()
    for mid, qty in rollback.items():
        mat = await db.materials.find_one({"id": mid})
        if mat:
            new_stock = round(float(mat.get("current_stock", 0)) + float(qty), 4)
            await db.materials.update_one(
                {"id": mid},
                {"$set": {"current_stock": new_stock, "updated_at": now_iso}},
            )
    try:
        # Hapus semua auto cash tx untuk sale ini (semua account_code payment method)
        payment_codes = list(PAYMENT_ACCOUNT_MAP.values())
        await db.cash_transactions.delete_many({
            "reference": sale.get("sale_no"),
            "auto": True,
            "account_code": {"$in": payment_codes},
        })
    except Exception as ex:
        logger.warning(f"Cashbook rollback (sale) failed: {ex}")


@api_router.put("/sales/{sale_id}")
async def sales_update(sale_id: str, payload: SaleIn, user: dict = Depends(require_super_admin)):
    existing = await db.sales.find_one({"id": sale_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    # 1. Rollback dulu (stok + cash tx)
    await _rollback_sale_effects(existing)
    # 2. Recompute + apply — preserve sale_no, id, created_at, date
    try:
        return await _build_and_persist_sale(
            payload, user,
            sale_no=existing.get("sale_no"),
            sale_id=existing.get("id"),
            created_at_iso=existing.get("created_at"),
            date_iso=existing.get("date"),
            is_update=True,
        )
    except HTTPException:
        # Reapply original stock deduction & cash tx supaya state konsisten
        try:
            # Deduct kembali stok
            rededuct: Dict[str, float] = {}
            for it in existing.get("items") or []:
                comps = it.get("components") or []
                if comps:
                    for c in comps:
                        mid = c.get("material_id")
                        if mid:
                            rededuct[mid] = rededuct.get(mid, 0) + float(c.get("consumption", 0))
                else:
                    mid = it.get("material_id")
                    if mid:
                        rededuct[mid] = rededuct.get(mid, 0) + float(it.get("area_total", 0))
            now_iso = datetime.now(timezone.utc).isoformat()
            for mid, qty in rededuct.items():
                mat = await db.materials.find_one({"id": mid})
                if mat:
                    new_stock = round(float(mat.get("current_stock", 0)) - float(qty), 4)
                    await db.materials.update_one({"id": mid}, {"$set": {"current_stock": new_stock, "updated_at": now_iso}})
            # Reinsert cash tx
            await _insert_cash_transaction(
                account_code="301",
                description=f"Penjualan {existing.get('sale_no')} — {existing.get('customer_name')}",
                amount=float(existing.get("total", 0)),
                reference=existing.get("sale_no"),
                date_iso=existing.get("date"),
                auto=True,
                created_by=user.get("email"),
            )
        except Exception as ex:
            logger.error(f"Rollback restore failed after update error: {ex}")
        raise


@api_router.delete("/sales/{sale_id}")
async def sales_delete(sale_id: str, user: dict = Depends(require_super_admin)):
    s = await db.sales.find_one({"id": sale_id})
    if not s:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    # Rollback stok + hapus semua auto cash tx (pakai helper konsisten dgn sales_update)
    await _rollback_sale_effects(s)
    await db.sales.delete_one({"id": sale_id})
    return {"ok": True}


@api_router.get("/sales/{sale_id}/receipt", response_class=HTMLResponse)
async def sales_receipt_html(sale_id: str, user: dict = Depends(require_super_admin)):
    s = await db.sales.find_one({"id": sale_id}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    ci = _company_info()
    def _idr(n):
        return f"Rp {float(n or 0):,.0f}".replace(",", ".")
    def _num(n):
        return f"{float(n or 0):.4f}".rstrip("0").rstrip(".") or "0"
    items_rows = ""
    for it in s.get("items") or []:
        pricing_mode = it.get("product_pricing_mode")
        is_product_fixed = it.get("product_id") and pricing_mode == "fixed"
        # Detail dimensi/qty
        if is_product_fixed:
            dim_line = f"<span>{int(it.get('quantity', 1))} pcs</span><span>@ {_idr(it.get('unit_price'))}</span>"
        else:
            dim_line = (
                f"<span>{_num(it.get('length_m'))}m × {_num(it.get('width_m'))}m × {int(it.get('quantity', 1))}</span>"
                f"<span>= {_num(it.get('area_total'))}m²</span>"
            )
            price_line = f"<span>@ {_idr(it.get('unit_price'))}/m²</span><span class='strong'>{_idr(it.get('subtotal'))}</span>"
        # Bahan breakdown (untuk BOM)
        mat_line = ""
        comps = it.get("components") or []
        if len(comps) > 1:
            mat_bits = " + ".join(f"{c.get('material_name', '-')} {_num(c.get('consumption'))}{c.get('material_unit', '')}" for c in comps)
            mat_line = f'<div class="mat">Bahan: {mat_bits}</div>'
        elif it.get("material_name"):
            mat_line = f'<div class="mat">{it.get("material_name")}</div>'

        if is_product_fixed:
            items_rows += f"""
        <div class="item">
          <div class="prod">{it.get('product_name', '')}</div>
          {mat_line}
          <div class="row">{dim_line}</div>
          <div class="row"><span></span><span class="strong">{_idr(it.get('subtotal'))}</span></div>
        </div>
        """
        else:
            items_rows += f"""
        <div class="item">
          <div class="prod">{it.get('product_name', '')}</div>
          {mat_line}
          <div class="row">{dim_line}</div>
          <div class="row">{price_line}</div>
        </div>
        """
    discount_row = ""
    if float(s.get("discount", 0)) > 0:
        discount_row = f"""<div class="row"><span>Diskon</span><span>- {_idr(s['discount'])}</span></div>"""
    date_str = s.get("date", "")
    created = s.get("created_at", "")[:19].replace("T", " ")
    customer_phone_row = f'<div class="line-sm">Telp: {s.get("customer_phone")}</div>' if s.get("customer_phone") else ""
    notes_row = f'<div class="notes">Catatan: {s.get("notes")}</div>' if s.get("notes") else ""
    sisa = float(s.get("sisa_tagihan") or 0)
    status = s.get("status") or ("dp" if sisa > 0.01 else "paid")
    sisa_row = f'<div class="row" style="color:#E81123;font-weight:bold;"><span>SISA TAGIHAN</span><span>{_idr(sisa)}</span></div>' if sisa > 0.01 else ""
    if status == "dp":
        status_row = '<div class="row" style="background:#FEF3C7;padding:4px 6px;margin-top:2px;font-weight:bold;color:#92400E;text-align:center;justify-content:center;">DP · Belum Lunas</div>'
    else:
        status_row = '<div class="row" style="background:#DCFCE7;padding:4px 6px;margin-top:2px;font-weight:bold;color:#166534;text-align:center;justify-content:center;">LUNAS</div>'
    html = f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="UTF-8"><title>Nota {s.get('sale_no')}</title>
<style>
  /* ===== Thermal 80mm (C80BT) - printable area ~72mm =====
     Semua teks WAJIB bold + hitam pekat agar tidak pudar
     saat dibakar oleh head printer thermal. Font sans-serif
     (Arial) lebih tebal & terbaca dibanding Courier. */
  @page {{ size: 80mm auto; margin: 0; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{ font-family: Arial, Helvetica, 'Liberation Sans', sans-serif; font-size: 13px; font-weight: 700; line-height: 1.35; color: #000; background: #eee; -webkit-font-smoothing: none; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .receipt {{ width: 72mm; max-width: 72mm; padding: 3mm 3mm 4mm 3mm; background: white; margin: 8px auto; box-shadow: 0 1px 6px rgba(0,0,0,0.08); word-wrap: break-word; overflow-wrap: break-word; color: #000; font-weight: 700; }}
  .receipt, .receipt * {{ color: #000 !important; }}
  h1, h2, h3, p {{ margin: 0; padding: 0; }}
  .center {{ text-align: center; }}
  .strong {{ font-weight: 800; }}
  .sep {{ border-top: 1px dashed #000; margin: 4px 0; }}
  .header {{ text-align: center; padding-bottom: 5px; border-bottom: 1px dashed #000; }}
  .header .name {{ font-size: 16px; font-weight: 900; letter-spacing: 0.3px; word-break: break-word; }}
  .header .addr {{ font-size: 12px; font-weight: 700; margin-top: 3px; line-height: 1.35; word-break: break-word; }}
  .meta {{ padding: 4px 0; border-bottom: 1px dashed #000; font-size: 12px; font-weight: 700; }}
  .meta .row {{ display: flex; justify-content: space-between; gap: 4px; padding: 1px 0; }}
  .meta .row > span:last-child {{ text-align: right; word-break: break-all; }}
  .items {{ padding: 4px 0; border-bottom: 1px dashed #000; }}
  .item {{ padding: 4px 0; }}
  .item + .item {{ border-top: 1px dashed #000; }}
  .item .prod {{ font-weight: 900; font-size: 13px; word-break: break-word; }}
  .item .mat {{ font-size: 11px; font-weight: 700; word-break: break-word; }}
  .item .row {{ display: flex; justify-content: space-between; font-size: 12px; font-weight: 700; margin-top: 2px; gap: 4px; }}
  .item .row > span:last-child {{ text-align: right; white-space: nowrap; }}
  .totals {{ padding: 4px 0; border-bottom: 1px dashed #000; font-size: 13px; font-weight: 700; }}
  .totals .row {{ display: flex; justify-content: space-between; padding: 2px 0; }}
  .totals .grand {{ font-size: 16px; font-weight: 900; padding: 4px 0; border-top: 2px solid #000; margin-top: 3px; }}
  .pay {{ padding: 4px 0; border-bottom: 1px dashed #000; font-size: 13px; font-weight: 700; }}
  .pay .row {{ display: flex; justify-content: space-between; padding: 2px 0; }}
  .footer {{ padding-top: 8px; text-align: center; font-size: 11px; font-weight: 700; line-height: 1.4; }}
  .notes {{ font-size: 11px; font-weight: 700; padding: 4px 0; border-bottom: 1px dashed #000; font-style: italic; word-break: break-word; }}
  .toolbar {{ max-width: 72mm; margin: 0 auto 8px; text-align: center; padding-top: 10px; }}
  .toolbar button {{ background: #002FA7; color: white; border: 0; padding: 10px 22px; font-family: Arial, sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.6px; cursor: pointer; text-transform: uppercase; }}
  .toolbar button:hover {{ background: #002080; }}
  .toolbar .hint {{ font-size: 11px; color: #333; margin-top: 6px; font-family: Arial, sans-serif; }}
  @media print {{
    html, body {{ background: white; width: 80mm; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .receipt {{ margin: 0 auto; box-shadow: none; padding: 2mm 3mm 3mm 3mm; width: 72mm; }}
    .toolbar {{ display: none; }}
  }}
</style></head><body>
<div class="toolbar">
  <button onclick="window.print()">🖨 Cetak Nota</button>
  <div class="hint">Thermal 80mm • Margin: None • Skala: 100% • Aktifkan "Background graphics"</div>
</div>
<div class="receipt">
  <div class="header">
    <div class="name">{ci['name'].upper()}</div>
    <div class="addr">{ci['address']}<br>HP : {ci['phone']}</div>
  </div>
  <div class="meta">
    <div class="row"><span>No. Nota</span><span class="strong">{s.get('sale_no', '')}</span></div>
    <div class="row"><span>Tanggal</span><span>{created}</span></div>
    <div class="row"><span>Kasir</span><span>{s.get('cashier_name', '')}</span></div>
    <div class="row"><span>Pelanggan</span><span>{s.get('customer_name', 'Umum')}</span></div>
    {customer_phone_row}
  </div>
  <div class="items">
    {items_rows}
  </div>
  <div class="totals">
    <div class="row"><span>Subtotal</span><span>{_idr(s.get('subtotal'))}</span></div>
    {discount_row}
    <div class="row grand"><span>TOTAL</span><span>{_idr(s.get('total'))}</span></div>
  </div>
  <div class="pay">
    <div class="row"><span>Metode</span><span class="strong">{(s.get('payment_method') or 'tunai').upper()}</span></div>
    <div class="row"><span>Bayar</span><span>{_idr(s.get('cash_paid'))}</span></div>
    {sisa_row}
    {status_row}
    <div class="row strong"><span>Kembali</span><span>{_idr(s.get('change'))}</span></div>
  </div>
  {notes_row}
  <div class="footer">
    Terima kasih atas kunjungan Anda<br>
    <span style="font-size:9px;">Simpan struk ini sebagai bukti pembayaran.</span>
  </div>
</div>
<script>
  // Auto-focus print dialog jika ada query ?auto=1
  if (new URLSearchParams(location.search).get('auto') === '1') {{
    setTimeout(() => window.print(), 400);
  }}
</script>
</body></html>"""
    return HTMLResponse(content=html)


@api_router.get("/sales/{sale_id}/invoice-pdf")
async def sales_invoice_pdf(sale_id: str, user: dict = Depends(require_super_admin)):
    """Cetak Nota A4 profesional (untuk customer korporat)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

    s = await db.sales.find_one({"id": sale_id}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    ci = _company_info()

    def _idr(n):
        return f"Rp {float(n or 0):,.0f}".replace(",", ".")

    def _num(n):
        return f"{float(n or 0):.4f}".rstrip("0").rstrip(".") or "0"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Nota {s.get('sale_no')}",
    )
    styles = getSampleStyleSheet()
    story = []

    # Company header
    company_style = ParagraphStyle("company", parent=styles["Normal"], fontSize=16, textColor=colors.HexColor("#002FA7"),
                                   alignment=TA_LEFT, spaceAfter=2, leading=18, fontName="Helvetica-Bold")
    story.append(Paragraph(ci["name"].upper(), company_style))
    story.append(Paragraph(f"{ci['address']}<br/>HP: {ci['phone']}", ParagraphStyle("addr", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#333333"), leading=12)))
    story.append(Spacer(1, 8 * mm))

    # Title
    story.append(Paragraph("<b>NOTA PENJUALAN</b>", ParagraphStyle("title", parent=styles["Normal"], fontSize=14, alignment=TA_CENTER, spaceAfter=6 * mm, fontName="Helvetica-Bold")))

    # Meta table (2 kolom: kiri = No/Tgl, kanan = Pelanggan)
    created = s.get("created_at", "")[:19].replace("T", " ")
    meta_data = [
        [Paragraph("<b>No. Nota</b>", styles["Normal"]), Paragraph(str(s.get("sale_no", "")), styles["Normal"]),
         Paragraph("<b>Pelanggan</b>", styles["Normal"]), Paragraph(str(s.get("customer_name", "Umum")), styles["Normal"])],
        [Paragraph("<b>Tanggal</b>", styles["Normal"]), Paragraph(created, styles["Normal"]),
         Paragraph("<b>Telp</b>", styles["Normal"]), Paragraph(str(s.get("customer_phone", "-") or "-"), styles["Normal"])],
        [Paragraph("<b>Kasir</b>", styles["Normal"]), Paragraph(str(s.get("cashier_name", "")), styles["Normal"]),
         Paragraph("<b>Metode</b>", styles["Normal"]), Paragraph((s.get("payment_method") or "tunai").upper(), styles["Normal"])],
    ]
    meta_tbl = Table(meta_data, colWidths=[28 * mm, 55 * mm, 25 * mm, 66 * mm])
    meta_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 6 * mm))

    # Items table
    right = ParagraphStyle("r", parent=styles["Normal"], alignment=TA_RIGHT)
    header_row = [
        Paragraph("<b>No</b>", ParagraphStyle("hn", parent=styles["Normal"], alignment=TA_CENTER, textColor=colors.white)),
        Paragraph("<b>Deskripsi</b>", ParagraphStyle("hd", parent=styles["Normal"], textColor=colors.white)),
        Paragraph("<b>Qty / Dim</b>", ParagraphStyle("hq", parent=styles["Normal"], alignment=TA_CENTER, textColor=colors.white)),
        Paragraph("<b>Harga</b>", ParagraphStyle("hp", parent=styles["Normal"], alignment=TA_RIGHT, textColor=colors.white)),
        Paragraph("<b>Subtotal</b>", ParagraphStyle("hs", parent=styles["Normal"], alignment=TA_RIGHT, textColor=colors.white)),
    ]
    rows = [header_row]
    for idx, it in enumerate(s.get("items") or [], 1):
        pricing_mode = it.get("product_pricing_mode")
        is_fixed = it.get("product_id") and pricing_mode == "fixed"
        name = it.get("product_name") or it.get("material_name") or "-"
        # Bahan breakdown
        comps = it.get("components") or []
        if len(comps) > 1:
            mat_bits = " + ".join(f"{c.get('material_name', '-')} {_num(c.get('consumption'))}{c.get('material_unit', '')}" for c in comps)
            desc = f"{name}<br/><font size=7 color='#666'>Bahan: {mat_bits}</font>"
        elif it.get("material_name") and not it.get("product_name"):
            desc = name
        elif comps:
            c = comps[0]
            desc = f"{name}<br/><font size=7 color='#666'>{c.get('material_name', '')}</font>"
        else:
            desc = name
        if is_fixed:
            qty_dim = f"{int(it.get('quantity', 1))} pcs"
            harga = f"{_idr(it.get('unit_price'))}"
        else:
            qty_dim = f"{_num(it.get('length_m'))}m × {_num(it.get('width_m'))}m × {int(it.get('quantity', 1))}<br/><font size=7 color='#666'>= {_num(it.get('area_total'))} m²</font>"
            harga = f"{_idr(it.get('unit_price'))}/m²"
        rows.append([
            Paragraph(str(idx), ParagraphStyle("n", parent=styles["Normal"], alignment=TA_CENTER)),
            Paragraph(desc, styles["Normal"]),
            Paragraph(qty_dim, ParagraphStyle("q", parent=styles["Normal"], alignment=TA_CENTER)),
            Paragraph(harga, right),
            Paragraph(_idr(it.get("subtotal")), right),
        ])
    items_tbl = Table(rows, colWidths=[10 * mm, 65 * mm, 34 * mm, 30 * mm, 35 * mm], repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#002FA7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 4 * mm))

    # Totals (kanan)
    total_rows = [
        [Paragraph("Subtotal", right), Paragraph(_idr(s.get("subtotal")), right)],
    ]
    if float(s.get("discount", 0)) > 0:
        total_rows.append([Paragraph("Diskon", right), Paragraph(f"- {_idr(s.get('discount'))}", right)])
    total_rows.append([
        Paragraph("<b><font size=12>TOTAL</font></b>", right),
        Paragraph(f"<b><font size=12 color='#002FA7'>{_idr(s.get('total'))}</font></b>", right),
    ])
    total_rows.append([Paragraph("Bayar (Tunai)", right), Paragraph(_idr(s.get("cash_paid")), right)])
    _sisa = float(s.get("sisa_tagihan") or 0)
    _status = s.get("status") or ("dp" if _sisa > 0.01 else "paid")
    if _sisa > 0.01:
        total_rows.append([
            Paragraph("<b><font color='#E81123'>SISA TAGIHAN</font></b>", right),
            Paragraph(f"<b><font color='#E81123'>{_idr(_sisa)}</font></b>", right),
        ])
    total_rows.append([Paragraph("Kembali", right), Paragraph(_idr(s.get("change")), right)])
    # Status badge
    if _status == "dp":
        total_rows.append([
            Paragraph("", right),
            Paragraph("<b><font color='#92400E' backcolor='#FEF3C7'>&nbsp;&nbsp;DP · BELUM LUNAS&nbsp;&nbsp;</font></b>", right),
        ])
    else:
        total_rows.append([
            Paragraph("", right),
            Paragraph("<b><font color='#166534' backcolor='#DCFCE7'>&nbsp;&nbsp;LUNAS&nbsp;&nbsp;</font></b>", right),
        ])
    total_tbl = Table(total_rows, colWidths=[100 * mm, 55 * mm], hAlign="RIGHT")
    total_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, -3), (-1, -3), 1.5, colors.HexColor("#002FA7")),
        ("LINEBELOW", (0, -3), (-1, -3), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(total_tbl)

    if s.get("notes"):
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(f"<b>Catatan:</b> {s.get('notes')}", ParagraphStyle("notes", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#555"))))

    # Footer signatures
    story.append(Spacer(1, 15 * mm))
    sign_rows = [[
        Paragraph("<b>Pelanggan</b><br/><br/><br/><br/><br/>(_______________________)", ParagraphStyle("sc", parent=styles["Normal"], alignment=TA_CENTER, fontSize=9)),
        Paragraph("", styles["Normal"]),
        Paragraph(f"<b>Hormat kami</b><br/>{ci['name']}<br/><br/><br/><br/>(_______________________)", ParagraphStyle("ss", parent=styles["Normal"], alignment=TA_CENTER, fontSize=9)),
    ]]
    sign_tbl = Table(sign_rows, colWidths=[60 * mm, 30 * mm, 65 * mm])
    story.append(sign_tbl)

    doc.build(story)
    buf.seek(0)
    fname = f"Nota_{s.get('sale_no', 'penjualan').replace('/', '_')}.pdf"
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={fname}"},
    )


@api_router.get("/sales/report/pdf")
async def sales_report_pdf(
    user: dict = Depends(require_super_admin),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    month: Optional[str] = None,  # YYYY-MM (opsional, override date_from/to)
):
    """Laporan Penjualan PDF landscape untuk periode tertentu."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER

    # Tentukan range
    if month:
        try:
            year, m = month.split("-")
            date_from = f"{year}-{int(m):02d}-01"
            if int(m) == 12:
                date_to = f"{int(year)+1}-01-01"
            else:
                date_to = f"{year}-{int(m)+1:02d}-01"
        except Exception:
            raise HTTPException(status_code=400, detail="Format month salah, gunakan YYYY-MM")

    q = {}
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lt"] = date_to
    items = await db.sales.find(q, {"_id": 0}).sort("created_at", 1).to_list(length=20000)
    ci = _company_info()

    def _idr(n):
        return f"Rp {float(n or 0):,.0f}".replace(",", ".")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"Laporan Penjualan {date_from or ''} - {date_to or ''}",
    )
    styles = getSampleStyleSheet()
    story = []

    # Header
    story.append(Paragraph(ci["name"].upper(), ParagraphStyle("co", parent=styles["Normal"], fontSize=13, textColor=colors.HexColor("#002FA7"), fontName="Helvetica-Bold")))
    story.append(Paragraph(f"{ci['address']} · HP: {ci['phone']}", ParagraphStyle("addr", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#555"))))
    story.append(Spacer(1, 4 * mm))

    period_label = f"{date_from or '(awal)'} s/d {date_to or '(sekarang)'}"
    if month:
        period_label = f"Bulan {month}"
    story.append(Paragraph(f"<b>LAPORAN PENJUALAN</b>", ParagraphStyle("t", parent=styles["Normal"], fontSize=14, alignment=TA_CENTER, fontName="Helvetica-Bold")))
    story.append(Paragraph(f"Periode: <b>{period_label}</b> · Total transaksi: <b>{len(items)}</b>", ParagraphStyle("p", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER, textColor=colors.HexColor("#555"))))
    story.append(Spacer(1, 5 * mm))

    right = ParagraphStyle("r", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=9)
    center = ParagraphStyle("c", parent=styles["Normal"], alignment=TA_CENTER, fontSize=9)
    normal_sm = ParagraphStyle("ns", parent=styles["Normal"], fontSize=9)

    header_row = [
        Paragraph("<b>No</b>", ParagraphStyle("hn", parent=styles["Normal"], alignment=TA_CENTER, textColor=colors.white)),
        Paragraph("<b>Tanggal</b>", ParagraphStyle("hd", parent=styles["Normal"], alignment=TA_CENTER, textColor=colors.white)),
        Paragraph("<b>No. Nota</b>", ParagraphStyle("hno", parent=styles["Normal"], textColor=colors.white)),
        Paragraph("<b>Pelanggan</b>", ParagraphStyle("hc", parent=styles["Normal"], textColor=colors.white)),
        Paragraph("<b>Kasir</b>", ParagraphStyle("hk", parent=styles["Normal"], textColor=colors.white)),
        Paragraph("<b>Item</b>", ParagraphStyle("hi", parent=styles["Normal"], alignment=TA_CENTER, textColor=colors.white)),
        Paragraph("<b>Subtotal</b>", ParagraphStyle("hs", parent=styles["Normal"], alignment=TA_RIGHT, textColor=colors.white)),
        Paragraph("<b>Diskon</b>", ParagraphStyle("hd2", parent=styles["Normal"], alignment=TA_RIGHT, textColor=colors.white)),
        Paragraph("<b>Total</b>", ParagraphStyle("ht", parent=styles["Normal"], alignment=TA_RIGHT, textColor=colors.white)),
    ]
    rows = [header_row]
    total_subtotal = 0.0
    total_discount = 0.0
    total_grand = 0.0
    for idx, s in enumerate(items, 1):
        item_count = len(s.get("items") or [])
        rows.append([
            Paragraph(str(idx), center),
            Paragraph(str(s.get("date", "")), center),
            Paragraph(str(s.get("sale_no", "")), normal_sm),
            Paragraph(str(s.get("customer_name", "Umum") or "Umum")[:35], normal_sm),
            Paragraph(str(s.get("cashier_name", ""))[:20], normal_sm),
            Paragraph(f"{item_count}", center),
            Paragraph(_idr(s.get("subtotal")), right),
            Paragraph(_idr(s.get("discount")), right),
            Paragraph(_idr(s.get("total")), right),
        ])
        total_subtotal += float(s.get("subtotal", 0) or 0)
        total_discount += float(s.get("discount", 0) or 0)
        total_grand += float(s.get("total", 0) or 0)
    # Total row
    rows.append([
        Paragraph(""),
        Paragraph(""),
        Paragraph(""),
        Paragraph(""),
        Paragraph(""),
        Paragraph("<b>TOTAL</b>", ParagraphStyle("tt", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=10, fontName="Helvetica-Bold")),
        Paragraph(f"<b>{_idr(total_subtotal)}</b>", ParagraphStyle("ts", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=10, fontName="Helvetica-Bold")),
        Paragraph(f"<b>{_idr(total_discount)}</b>", ParagraphStyle("td", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=10, fontName="Helvetica-Bold")),
        Paragraph(f"<b>{_idr(total_grand)}</b>", ParagraphStyle("tg", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=10, fontName="Helvetica-Bold", textColor=colors.HexColor("#002FA7"))),
    ])

    tbl = Table(rows, colWidths=[10 * mm, 22 * mm, 30 * mm, 55 * mm, 30 * mm, 14 * mm, 32 * mm, 30 * mm, 35 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#002FA7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f8f8")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8ecf7")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#002FA7")),
    ]))
    story.append(tbl)

    if not items:
        story.append(Spacer(1, 10 * mm))
        story.append(Paragraph("<i>Belum ada transaksi pada periode ini.</i>", ParagraphStyle("empty", parent=styles["Normal"], alignment=TA_CENTER, textColor=colors.HexColor("#999"))))

    doc.build(story)
    buf.seek(0)
    fname_period = month or (f"{date_from}_sd_{date_to}" if (date_from or date_to) else "semua")
    fname = f"Laporan_Penjualan_{fname_period}.pdf"
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={fname}"},
    )


@api_router.get("/sales/report/excel")
async def sales_report_excel(
    user: dict = Depends(require_super_admin),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    customer: Optional[str] = None,
    month: Optional[str] = None,
):
    """Laporan Penjualan Excel — format persis seperti tabel Excel-style di UI.
    12 kolom utama + 6 grup pembayaran (Cash/BCA/Mandiri × Plaza/Kastem) masing-masing Nominal + Tanggal.
    """
    import pandas as pd
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    if month:
        try:
            year, m = month.split("-")
            date_from = f"{year}-{int(m):02d}-01"
            if int(m) == 12:
                date_to = f"{int(year)+1}-01-01"
            else:
                date_to = f"{year}-{int(m)+1:02d}-01"
        except Exception:
            raise HTTPException(status_code=400, detail="Format month salah, gunakan YYYY-MM")

    q: Dict[str, Any] = {"status": {"$nin": ["cancelled", "void", "voided", "canceled"]}}
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if customer:
        safe = re.escape(customer.strip())
        q["customer_name"] = {"$regex": safe, "$options": "i"}
    sales = await db.sales.find(q, {"_id": 0}).sort("created_at", 1).to_list(length=20000)
    ci = _company_info()

    # Preload maps (sama seperti analytics endpoint)
    customers = await db.customers.find({}, {"_id": 0, "name": 1, "address": 1}).to_list(length=5000)
    cust_addr_map = {(c.get("name") or "").strip().lower(): (c.get("address") or "").strip() for c in customers}
    products_p = await db.products.find({}, {"_id": 0, "name": 1, "length_meter": 1}).to_list(length=5000)
    prod_length_map = {(p.get("name") or "").strip().lower(): float(p.get("length_meter") or 0) for p in products_p}

    PAY_COLS = [
        ("cash_plaza", "Cash Plaza"),
        ("cash_kastem", "Cash Kastem"),
        ("bca_plaza", "BCA Plaza"),
        ("bca_kastem", "BCA Kastem"),
        ("mandiri_plaza", "Mandiri Plaza"),
        ("mandiri_kastem", "Mandiri Kastem"),
        ("shopee_plaza", "Shopee Plaza"),
        ("shopee_kastem", "Shopee Kastem"),
    ]

    # Flatten rows (mirror analytics endpoint)
    excel_rows = []
    row_no = 0
    for s in sales:
        s_date = s.get("date") or ""
        s_customer = s.get("customer_name") or "Umum"
        s_method = s.get("payment_method") or "cash"
        s_bank = s.get("payment_bank") or ""
        s_pnotes = s.get("payment_notes") or ""
        s_notes = s.get("notes") or ""
        s_total_after_disc = float(s.get("total") or 0)
        s_discount = float(s.get("discount") or 0)
        s_branch = _sanitize_branch(s.get("branch"))
        pay_col = _resolve_report_payment_col(s_method, s_bank, s_branch)
        s_alamat = cust_addr_map.get(s_customer.strip().lower(), "")
        first_item = True
        for it in (s.get("items") or []):
            row_no += 1
            name = it.get("product_name") or it.get("material_name") or "-"
            qty = int(it.get("quantity") or 0)
            unit_price = float(it.get("unit_price") or 0)
            length_m = prod_length_map.get(name.strip().lower(), 0.0)
            meter = round(qty * length_m, 4) if length_m > 0 else 0
            row = {
                "No": row_no,
                "Tanggal": s_date,
                "No. Nota": s.get("sale_no", ""),
                "Alamat": s_alamat,
                "Nama Barang": name,
                "Pcs": qty,
                "Meter": meter,
                "Harga": unit_price,
                "Disc": s_discount if first_item else 0,
                "Jumlah": round(unit_price * qty, 2),
                "Total": s_total_after_disc if first_item else 0,
                "Keterangan": s_pnotes or s_notes or "",
            }
            # Payment columns: 12 total (6 pairs × Nominal + Tanggal)
            for k, _ in PAY_COLS:
                row[f"{k}__n"] = 0
                row[f"{k}__d"] = ""
            if first_item and pay_col:
                row[f"{pay_col}__n"] = s_total_after_disc
                row[f"{pay_col}__d"] = s_date
            excel_rows.append(row)
            first_item = False

    # Build DataFrame with grouped columns
    if not excel_rows:
        excel_rows.append({
            "No": 1, "Tanggal": "", "No. Nota": "(Tidak ada transaksi)", "Alamat": "",
            "Nama Barang": "", "Pcs": 0, "Meter": 0, "Harga": 0, "Disc": 0,
            "Jumlah": 0, "Total": 0, "Keterangan": "",
            **{f"{k}__n": 0 for k, _ in PAY_COLS},
            **{f"{k}__d": "" for k, _ in PAY_COLS},
        })
    df = pd.DataFrame(excel_rows)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        sheet_name = f"Penjualan {month or 'periode'}"[:31]
        # Write starting from Excel row 6 (0-indexed=5) leaving rows 1-5 for company + column-group + sub-headers
        df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=5, header=False)
        ws = writer.sheets[sheet_name]

        # Row 1: Company name
        ws["A1"] = ci["name"].upper()
        ws["A1"].font = Font(bold=True, size=14, color="002FA7")
        # Row 2: Address
        ws["A2"] = f"{ci['address']} · HP: {ci['phone']}"
        ws["A2"].font = Font(size=9, italic=True, color="666666")
        # Row 3: Period info
        period_label = f"Bulan {month}" if month else f"{date_from or '(awal)'} s/d {date_to or '(sekarang)'}"
        ws["A3"] = f"Laporan Penjualan · Periode: {period_label} · {len(sales)} transaksi · {len(df)} item"
        ws["A3"].font = Font(bold=True, size=10)

        # Row 4: Grouped headers (12 main + 6 payment groups)
        MAIN_HEADERS = ["No", "Tanggal", "No. Nota", "Alamat", "Nama Barang", "Pcs", "Meter", "Harga", "Disc", "Jumlah", "Total", "Keterangan"]
        thin = Side(border_style="thin", color="333333")
        border = Border(top=thin, bottom=thin, left=thin, right=thin)
        header_fill = PatternFill("solid", fgColor="1F2937")
        header_font = Font(bold=True, color="FFFFFF", size=10)
        pay_fills = {
            "cash_plaza": "008A00",
            "cash_kastem": "34C759",
            "bca_plaza": "002FA7",
            "bca_kastem": "4A6FE0",
            "mandiri_plaza": "E81123",
            "mandiri_kastem": "FF6B6B",
            "shopee_plaza": "F97316",  # orange 500
            "shopee_kastem": "FDBA74", # orange 300
        }
        # Row 4 main headers span both header rows 4-5 (merged)
        for i, h in enumerate(MAIN_HEADERS, start=1):
            ws.cell(row=4, column=i, value=h)
            ws.merge_cells(start_row=4, start_column=i, end_row=5, end_column=i)
            c = ws.cell(row=4, column=i)
            c.font = header_font; c.fill = header_fill; c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True); c.border = border
        # Row 4 payment group headers (merged over 2 columns), Row 5 sub-headers Nominal/Tanggal
        col_cursor = len(MAIN_HEADERS) + 1
        for k, label in PAY_COLS:
            ws.merge_cells(start_row=4, start_column=col_cursor, end_row=4, end_column=col_cursor + 1)
            gh = ws.cell(row=4, column=col_cursor, value=label)
            gh.font = header_font
            gh.fill = PatternFill("solid", fgColor=pay_fills[k])
            gh.alignment = Alignment(horizontal="center", vertical="center")
            gh.border = border
            for j, sub in enumerate(("Nominal", "Tanggal")):
                sc = ws.cell(row=5, column=col_cursor + j, value=sub)
                sc.font = Font(bold=True, color="FFFFFF", size=9)
                sc.fill = header_fill
                sc.alignment = Alignment(horizontal="center", vertical="center")
                sc.border = border
            col_cursor += 2

        # Format data rows: number columns as currency for nominal cols
        n_rows_data = len(df)
        start_data_row = 6
        end_data_row = start_data_row + n_rows_data - 1
        currency_fmt = "#,##0"
        # Currency columns: Harga (8), Disc (9), Jumlah (10), Total (11) + all pay __n columns
        currency_cols = [8, 9, 10, 11]
        col_cursor = len(MAIN_HEADERS) + 1
        for _ in PAY_COLS:
            currency_cols.append(col_cursor)      # nominal
            col_cursor += 2
        for r in range(start_data_row, end_data_row + 1):
            for cc in currency_cols:
                cell = ws.cell(row=r, column=cc)
                cell.number_format = currency_fmt

        # Auto-width per column
        total_cols = len(MAIN_HEADERS) + len(PAY_COLS) * 2
        default_widths = {1: 6, 2: 12, 3: 16, 4: 24, 5: 28, 6: 6, 7: 8, 8: 12, 9: 10, 10: 12, 11: 14, 12: 22}
        for i in range(1, total_cols + 1):
            ws.column_dimensions[get_column_letter(i)].width = default_widths.get(i, 12)

        # Total footer row
        total_row = end_data_row + 2
        ws.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True, size=11, color="002FA7")
        # Sum Pcs (col 6), Meter (col 7), Disc (col 9), Jumlah (col 10), Total (col 11)
        if n_rows_data > 0:
            ws.cell(row=total_row, column=6, value=f"=SUM(F{start_data_row}:F{end_data_row})")
            ws.cell(row=total_row, column=7, value=f"=SUM(G{start_data_row}:G{end_data_row})")
            ws.cell(row=total_row, column=9, value=f"=SUM(I{start_data_row}:I{end_data_row})")
            ws.cell(row=total_row, column=10, value=f"=SUM(J{start_data_row}:J{end_data_row})")
            ws.cell(row=total_row, column=11, value=f"=SUM(K{start_data_row}:K{end_data_row})")
            # Sum each pay-nominal column
            col_cursor = len(MAIN_HEADERS) + 1
            for _ in PAY_COLS:
                col_letter = get_column_letter(col_cursor)
                ws.cell(row=total_row, column=col_cursor, value=f"=SUM({col_letter}{start_data_row}:{col_letter}{end_data_row})")
                col_cursor += 2
            # Bold + currency format
            for cc in currency_cols + [6, 7]:
                cell = ws.cell(row=total_row, column=cc)
                cell.font = Font(bold=True, size=11, color="1F2937")
                if cc in currency_cols:
                    cell.number_format = currency_fmt

        # Freeze panes below header row 5
        ws.freeze_panes = ws["A6"]

    buf.seek(0)
    fname_period = month or (f"{date_from}_sd_{date_to}" if (date_from or date_to) else "semua")
    fname = f"Laporan_Penjualan_{fname_period}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ---------------- Laporan Rincian Penjualan Online Shopee ----------------
@api_router.get("/sales/report/shopee-rincian")
async def sales_shopee_rincian(
    user: dict = Depends(require_super_admin),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Split per outlet (Plaza / Kastem) untuk transaksi Shopee."""
    q: Dict[str, Any] = {
        "status": {"$nin": ["cancelled", "void", "voided", "canceled"]},
        "payment_method": {"$in": ["shopee_plaza", "shopee_kastem"]},
    }
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    sales = await db.sales.find(q, {"_id": 0}).sort("created_at", 1).to_list(length=20000)

    products_p = await db.products.find({}, {"_id": 0, "name": 1, "length_meter": 1}).to_list(length=5000)
    prod_length_map = {(p.get("name") or "").strip().lower(): float(p.get("length_meter") or 0) for p in products_p}

    def _row_from_sale(s: Dict[str, Any]) -> Dict[str, Any]:
        items = s.get("items") or []
        pesanan_parts = []
        pcs = 0
        meter = 0.0
        harga_satuan = 0.0
        for it in items:
            name = (it.get("product_name") or it.get("material_name") or "-").strip()
            qty = int(it.get("quantity") or 0)
            up = float(it.get("unit_price") or 0)
            pesanan_parts.append(name)
            pcs += qty
            if harga_satuan == 0:
                harga_satuan = up
            length_m = prod_length_map.get(name.lower(), 0.0)
            if length_m > 0:
                meter += qty * length_m
        pesanan = " · ".join(pesanan_parts) if pesanan_parts else "-"
        jumlah = float(s.get("subtotal") or 0)
        saldo_masuk = s.get("saldo_masuk")
        if saldo_masuk is None or saldo_masuk == "":
            saldo_val = None
            potongan = None
            persentase = None
        else:
            saldo_val = float(saldo_masuk)
            potongan = round(jumlah - saldo_val, 2)
            persentase = round((potongan / jumlah * 100), 2) if jumlah > 0 else 0
        return {
            "id": s.get("id"),
            "sale_id": s.get("id"),
            "sale_no": s.get("sale_no"),
            "date": s.get("date"),
            "nama": s.get("customer_name") or "Umum",
            "pesanan": pesanan,
            "pcs": pcs,
            "meter": round(meter, 4),
            "harga_satuan": round(harga_satuan, 2),
            "jumlah": round(jumlah, 2),
            "saldo_masuk": saldo_val,
            "potongan": potongan,
            "persentase": persentase,
        }

    plaza_rows = []
    kastem_rows = []
    plaza_totals = {"jumlah": 0.0, "saldo_masuk": 0.0, "potongan": 0.0}
    kastem_totals = {"jumlah": 0.0, "saldo_masuk": 0.0, "potongan": 0.0}
    for s in sales:
        row = _row_from_sale(s)
        target = plaza_rows if s.get("payment_method") == "shopee_plaza" else kastem_rows
        totals = plaza_totals if s.get("payment_method") == "shopee_plaza" else kastem_totals
        target.append(row)
        totals["jumlah"] += float(row["jumlah"] or 0)
        totals["saldo_masuk"] += float(row["saldo_masuk"] or 0)
        totals["potongan"] += float(row["potongan"] or 0)
    for t in (plaza_totals, kastem_totals):
        for k in t:
            t[k] = round(t[k], 2)

    return {
        "plaza": {"rows": plaza_rows, "totals": plaza_totals, "count": len(plaza_rows)},
        "kastem": {"rows": kastem_rows, "totals": kastem_totals, "count": len(kastem_rows)},
    }


class SaldoMasukIn(BaseModel):
    saldo_masuk: Optional[float] = None  # None = clear


@api_router.patch("/sales/{sale_id}/saldo-masuk")
async def sales_update_saldo_masuk(sale_id: str, payload: SaldoMasukIn, user: dict = Depends(require_super_admin)):
    existing = await db.sales.find_one({"id": sale_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    val = payload.saldo_masuk
    if val is not None and float(val) < 0:
        raise HTTPException(status_code=400, detail="Saldo Masuk tidak boleh negatif")
    await db.sales.update_one(
        {"id": sale_id},
        {"$set": {
            "saldo_masuk": float(val) if val is not None else None,
            "saldo_masuk_updated_at": datetime.now(timezone.utc).isoformat(),
            "saldo_masuk_updated_by": user.get("email"),
        }},
    )
    return {"ok": True, "sale_id": sale_id, "saldo_masuk": val}


class PayRemainingIn(BaseModel):
    amount: float
    payment_method: str = "cash"  # cash | transfer | shopee_plaza | shopee_kastem
    payment_bank: Optional[str] = None  # bca | mandiri (jika transfer)
    date: Optional[str] = None  # YYYY-MM-DD (opsional, default hari ini)
    notes: Optional[str] = None


@api_router.post("/sales/{sale_id}/pay-remaining")
async def sales_pay_remaining(sale_id: str, payload: PayRemainingIn, user: dict = Depends(require_super_admin)):
    """Pelunasan sisa tagihan (DP → LUNAS). Otomatis catat ke Jurnal Kas."""
    existing = await db.sales.find_one({"id": sale_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    current_sisa = round(float(existing.get("sisa_tagihan") or 0), 2)
    current_status = existing.get("status") or ("dp" if current_sisa > 0.01 else "paid")
    if current_status != "dp" or current_sisa <= 0.01:
        raise HTTPException(status_code=400, detail="Transaksi ini sudah LUNAS")
    amount = round(float(payload.amount or 0), 2)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Nominal pembayaran harus > 0")
    # Toleransi kecil - allow overpay up to 1 rupiah untuk rounding
    if amount > current_sisa + 0.01:
        raise HTTPException(status_code=400, detail=f"Nominal melebihi sisa tagihan (Rp {current_sisa:,.0f})")
    pay_date = (payload.date or datetime.now(timezone.utc).date().isoformat())[:10]
    try:
        datetime.strptime(pay_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Format tanggal harus YYYY-MM-DD")

    new_sisa = round(max(0.0, current_sisa - amount), 2)
    new_status = "paid" if new_sisa <= 0.01 else "dp"
    new_cash_paid = round(float(existing.get("cash_paid") or 0) + amount, 2)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Log entry
    payment_entry = {
        "id": str(uuid.uuid4()),
        "amount": amount,
        "payment_method": payload.payment_method or "cash",
        "payment_bank": (payload.payment_bank or "").strip() or None,
        "date": pay_date,
        "notes": (payload.notes or "").strip() or None,
        "created_at": now_iso,
        "created_by": user.get("email"),
    }

    await db.sales.update_one(
        {"id": sale_id},
        {
            "$set": {
                "sisa_tagihan": new_sisa,
                "status": new_status,
                "cash_paid": new_cash_paid,
                "last_payment_at": now_iso,
                "last_payment_by": user.get("email"),
            },
            "$push": {"payments": payment_entry},
        },
    )

    # Auto insert Jurnal Kas
    try:
        acc_code, acc_label = _resolve_payment_account(payload.payment_method, payload.payment_bank)
        desc = f"Pelunasan {existing.get('sale_no')} — {existing.get('customer_name')} · {acc_label}"
        if new_status == "paid":
            desc += " · LUNAS"
        else:
            desc += f" · sisa Rp {new_sisa:,.0f}"
        if payment_entry["notes"]:
            desc += f" ({payment_entry['notes']})"
        await _insert_cash_transaction(
            account_code=acc_code,
            description=desc,
            amount=amount,
            reference=existing.get("sale_no"),
            date_iso=pay_date,
            auto=True,
            created_by=user.get("email"),
        )
    except Exception as ex:
        logger.warning(f"Cashbook auto-insert (pay-remaining) failed: {ex}")

    return {
        "ok": True,
        "sale_id": sale_id,
        "amount_paid": amount,
        "sisa_tagihan": new_sisa,
        "status": new_status,
        "cash_paid_total": new_cash_paid,
    }



@api_router.get("/sales/report/analytics")
async def sales_analytics(
    user: dict = Depends(require_super_admin),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    customer: Optional[str] = None,
):
    """Analytics untuk Laporan Penjualan (rows flatten per-item + summary + charts data)."""
    q: Dict[str, Any] = {"status": {"$nin": ["cancelled", "void", "voided", "canceled"]}}
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if customer:
        safe = re.escape(customer.strip())
        q["customer_name"] = {"$regex": safe, "$options": "i"}
    sales = await db.sales.find(q, {"_id": 0}).sort("created_at", 1).to_list(length=20000)

    # Preload customer address map (by name, case-insensitive) & product length_meter map (by name)
    customers = await db.customers.find({}, {"_id": 0, "name": 1, "address": 1}).to_list(length=5000)
    cust_addr_map = {(c.get("name") or "").strip().lower(): (c.get("address") or "").strip() for c in customers}
    products_p = await db.products.find({}, {"_id": 0, "name": 1, "length_meter": 1}).to_list(length=5000)
    prod_length_map = {(p.get("name") or "").strip().lower(): float(p.get("length_meter") or 0) for p in products_p}

    # Flatten per-item rows
    rows: List[Dict[str, Any]] = []
    product_totals: Dict[str, Dict[str, float]] = {}
    daily_series: Dict[str, float] = {}
    method_totals: Dict[str, float] = {}
    weekly_total = 0.0
    period_total = 0.0

    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())
    week_start_iso = week_start.isoformat()

    for s in sales:
        s_date = s.get("date") or ""
        s_customer = s.get("customer_name") or "Umum"
        s_method = s.get("payment_method") or "cash"
        s_bank = s.get("payment_bank") or ""
        s_pnotes = s.get("payment_notes") or ""
        s_notes = s.get("notes") or ""
        s_total_after_disc = float(s.get("total") or 0)
        s_discount = float(s.get("discount") or 0)
        s_subtotal = float(s.get("subtotal") or 0)
        s_branch = _sanitize_branch(s.get("branch"))  # "plaza" | "kastem" | None
        # DP: cash_paid = jumlah aktual diterima; sisa_tagihan = piutang
        s_cash_paid = float(s.get("cash_paid") or 0)
        s_sisa = float(s.get("sisa_tagihan") if s.get("sisa_tagihan") is not None else max(0, s_total_after_disc - s_cash_paid))
        # kolom pembayaran hanya menampilkan nominal aktual (tidak termasuk piutang)
        s_paid_amount = min(s_cash_paid, s_total_after_disc)
        s_status = s.get("status") or ("dp" if s_sisa > 0.01 else "paid")
        # Payment column key (Cash/BCA/Mandiri + Plaza/Kastem) — derived from method+bank+branch
        pay_col = _resolve_report_payment_col(s_method, s_bank, s_branch)
        # Alamat: prefer customer master lookup by name (case-insensitive)
        s_alamat = cust_addr_map.get(s_customer.strip().lower(), "")
        s_items = s.get("items") or []
        first_item = True
        for it in s_items:
            name = it.get("product_name") or it.get("material_name") or "-"
            qty = int(it.get("quantity") or 0)
            unit_price = float(it.get("unit_price") or 0)
            subtotal_item = float(it.get("subtotal") or (unit_price * qty))
            size = it.get("size") or "-"
            length_m = prod_length_map.get(name.strip().lower(), 0.0)
            meter = round(qty * length_m, 4) if length_m > 0 else 0.0
            rows.append({
                "date": s_date,
                "customer_name": s_customer,
                "alamat": s_alamat,
                "sale_no": s.get("sale_no"),
                "product_name": name,
                "size": size,
                "pcs": qty,
                "meter": meter,
                "quantity": qty,  # legacy alias
                "unit_price": unit_price,
                "total": subtotal_item,
                "sale_total": s_total_after_disc,
                "sale_subtotal": s_subtotal,
                "sale_discount": s_discount,
                "sale_cash_paid": s_cash_paid,
                "sale_sisa_tagihan": s_sisa,
                "sale_status": s_status,  # "paid" (LUNAS) atau "dp"
                "keterangan": s_pnotes or s_notes or "",
                "branch": s_branch,
                "payment_method": s_method,
                "payment_bank": s_bank,
                "payment_notes": s_pnotes,
                "payment_column": pay_col,  # e.g., "cash_plaza" / "bca_kastem" / None
                # Payment nominal appears on FIRST row of a sale only. Sekarang = cash_paid (aktual diterima), bukan total.
                "payment_nominal_on_row": s_paid_amount if first_item else 0,
                "payment_date_on_row": s_date if first_item else "",
                "is_first_item_of_sale": first_item,
            })
            first_item = False
            pk = name
            if pk not in product_totals:
                product_totals[pk] = {"qty": 0, "total": 0.0}
            product_totals[pk]["qty"] += qty
            product_totals[pk]["total"] += subtotal_item
        period_total += s_total_after_disc
        daily_series[s_date] = daily_series.get(s_date, 0) + s_total_after_disc
        mkey = s_method
        if s_method == "transfer" and s_bank:
            mkey = f"transfer_{s_bank.lower()}"
        method_totals[mkey] = method_totals.get(mkey, 0) + s_total_after_disc
        if s_date >= week_start_iso:
            weekly_total += s_total_after_disc

    top_products = sorted(
        [{"name": k, "qty": int(v["qty"]), "total": round(v["total"], 2)} for k, v in product_totals.items()],
        key=lambda x: x["total"], reverse=True,
    )
    top_product = top_products[0]["name"] if top_products else None
    daily_data = [{"date": d, "total": round(v, 2)} for d, v in sorted(daily_series.items())]

    return {
        "rows": rows,
        "summary": {
            "period_total": round(period_total, 2),
            "weekly_total": round(weekly_total, 2),
            "week_start": week_start_iso,
            "transaction_count": len(sales),
            "item_count": len(rows),
            "top_product": top_product,
        },
        "top_products": top_products[:10],
        "daily_series": daily_data,
        "method_breakdown": [
            {"method": k, "total": round(v, 2)} for k, v in sorted(method_totals.items(), key=lambda x: x[1], reverse=True)
        ],
    }


def _resolve_report_payment_col(payment_method: str, payment_bank: Optional[str], branch: Optional[str]) -> Optional[str]:
    """Map (payment_method, payment_bank, branch) -> report column key.
    Returns one of:
      cash_plaza, cash_kastem, bca_plaza, bca_kastem, mandiri_plaza, mandiri_kastem,
      shopee_plaza, shopee_kastem, or None.
    - Shopee: branch di-ambil dari payment_method (shopee_plaza / shopee_kastem).
    - Kolom lain (Cash/BCA/Mandiri): butuh sale.branch. Jika sale.branch kosong
      (transaksi lama pre-fitur cabang), default ke "plaza" agar nominal tetap muncul.
    """
    pm = (payment_method or "").lower()
    # Shopee columns — plaza/kastem sudah baked in payment_method
    if pm == "shopee_plaza":
        return "shopee_plaza"
    if pm == "shopee_kastem":
        return "shopee_kastem"
    # Kolom lain: default branch = plaza (fallback untuk data lama)
    b = (branch or "plaza").lower()
    if b not in ("plaza", "kastem"):
        b = "plaza"
    bank = (payment_bank or "").lower()
    if pm in ("cash", "tunai"):
        return f"cash_{b}"
    if pm == "transfer":
        if bank == "bca":
            return f"bca_{b}"
        if bank in ("mandiri", "mdr"):
            return f"mandiri_{b}"
        return None
    return None


@api_router.get("/sales/stats/today")
async def sales_stats_today(user: dict = Depends(require_super_admin)):
    today = datetime.now(timezone.utc).date().isoformat()
    items = await db.sales.find({"date": today}, {"_id": 0}).to_list(length=5000)
    total_today = sum(float(s.get("total", 0)) for s in items)
    # This month
    month_start = datetime.now(timezone.utc).date().replace(day=1).isoformat()
    month_items = await db.sales.find({"date": {"$gte": month_start}}, {"_id": 0, "total": 1}).to_list(length=20000)
    total_month = sum(float(s.get("total", 0)) for s in month_items)
    return {
        "date": today,
        "count_today": len(items),
        "total_today": round(total_today, 2),
        "count_month": len(month_items),
        "total_month": round(total_month, 2),
    }


# ================================================================
# ==================== KAS OPERASIONAL (Cash Book) ================
# ================================================================
# Chart of Accounts default (bisa di-extend via UI)
DEFAULT_CASH_ACCOUNTS = [
    # Pemasukan (income) — per metode pembayaran
    {"code": "301", "name": "Penjualan Tunai", "type": "in", "system": True},
    {"code": "301-BCA", "name": "Penjualan via Transfer BCA", "type": "in", "system": True},
    {"code": "301-MDR", "name": "Penjualan via Transfer Mandiri", "type": "in", "system": True},
    {"code": "301-SPP", "name": "Penjualan via Shopee Plaza", "type": "in", "system": True},
    {"code": "301-SPK", "name": "Penjualan via Shopee Kastem", "type": "in", "system": True},
    {"code": "302", "name": "Terima Piutang", "type": "in", "system": False},
    {"code": "303", "name": "Modal / Setoran Kas", "type": "in", "system": False},
    {"code": "304", "name": "Pendapatan Lain-lain", "type": "in", "system": False},
    # Kode Akun Akuntansi Standar (Assets & Expense) — permintaan user
    {"code": "101", "name": "Kas", "type": "in", "system": False},
    {"code": "103", "name": "Persediaan Barang", "type": "out", "system": False},
    {"code": "103-01", "name": "Bahan Baku Mesin", "type": "out", "system": False},
    {"code": "104", "name": "Perlengkapan Kantor", "type": "out", "system": False},
    {"code": "105", "name": "BBM dan Maintenance Kendaraan", "type": "out", "system": False},
    {"code": "106", "name": "Pengiriman Dokumen", "type": "out", "system": False},
    {"code": "108", "name": "Makan dan Entertainment", "type": "out", "system": False},
    # Pengeluaran (expense) — kode lama tetap kompatibel
    {"code": "201", "name": "Bayar Utang Usaha", "type": "out", "system": True},
    {"code": "401", "name": "Pembelian Bahan Baku", "type": "out", "system": False},
    {"code": "402", "name": "Perlengkapan Kantor", "type": "out", "system": False},
    {"code": "403", "name": "Alat Tulis Kantor", "type": "out", "system": False},
    {"code": "501", "name": "BBM, Parkir & Maintenance Kendaraan", "type": "out", "system": False},
    {"code": "502", "name": "Beban Listrik, Air, Telepon", "type": "out", "system": False},
    {"code": "503", "name": "Sewa Kendaraan", "type": "out", "system": False},
    {"code": "504", "name": "Sewa Bangunan / Mess", "type": "out", "system": False},
    {"code": "505", "name": "Gaji Karyawan", "type": "out", "system": False},
    {"code": "506", "name": "Makan & Entertainment", "type": "out", "system": False},
    {"code": "507", "name": "Pengiriman Dokumen / Barang", "type": "out", "system": False},
    {"code": "508", "name": "Promosi & Iklan", "type": "out", "system": False},
    {"code": "509", "name": "Percetakan", "type": "out", "system": False},
    {"code": "510", "name": "Jasa Freelancer", "type": "out", "system": False},
    {"code": "511", "name": "Biaya Administrasi Bank", "type": "out", "system": False},
    {"code": "512", "name": "Kasbon Karyawan", "type": "out", "system": False},
    {"code": "599", "name": "Lain-lain", "type": "out", "system": False},
]


async def _ensure_cash_accounts():
    """Seed default chart of accounts idempotently (per kode akun)."""
    for a in DEFAULT_CASH_ACCOUNTS:
        exists = await db.cash_accounts.find_one({"code": a["code"]})
        if exists:
            continue
        await db.cash_accounts.insert_one({
            "id": str(uuid.uuid4()),
            "code": a["code"],
            "name": a["name"],
            "type": a["type"],
            "system": a["system"],
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })


class CashAccountIn(BaseModel):
    code: str
    name: str
    type: str  # "in" | "out"
    active: bool = True


class CashTransactionIn(BaseModel):
    date: str  # YYYY-MM-DD
    account_code: str
    description: str
    amount: float
    # type di-derive dari account. Kalau bertentangan → validasi
    reference: Optional[str] = None  # e.g. "NOTA-xxx", "PO-xxx"


class CashSettingIn(BaseModel):
    opening_balance: float
    opening_date: Optional[str] = None  # YYYY-MM-DD (default: 1 Januari tahun ini)


async def _cash_setting() -> Dict[str, Any]:
    doc = await db.cash_settings.find_one({"key": "main"}, {"_id": 0})
    if not doc:
        default = {
            "key": "main",
            "opening_balance": 0.0,
            "opening_date": datetime.now(timezone.utc).date().replace(month=1, day=1).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.cash_settings.insert_one(default)
        default.pop("_id", None)
        return default
    return doc


async def _insert_cash_transaction(
    account_code: str,
    description: str,
    amount: float,
    reference: Optional[str] = None,
    date_iso: Optional[str] = None,
    auto: bool = False,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert satu transaksi kas. Return doc."""
    await _ensure_cash_accounts()
    acc = await db.cash_accounts.find_one({"code": account_code}, {"_id": 0})
    if not acc:
        raise HTTPException(status_code=404, detail=f"Akun {account_code} tidak ditemukan")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Jumlah harus > 0")
    doc = {
        "id": str(uuid.uuid4()),
        "date": date_iso or datetime.now(timezone.utc).date().isoformat(),
        "account_code": acc["code"],
        "account_name": acc["name"],
        "type": acc["type"],  # "in" atau "out"
        "description": description.strip(),
        "amount": round(float(amount), 2),
        "reference": reference,
        "auto": auto,
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.cash_transactions.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ---------- Endpoints ----------
@api_router.get("/cashbook/accounts")
async def cash_accounts_list(user: dict = Depends(require_super_admin)):
    await _ensure_cash_accounts()
    items = await db.cash_accounts.find({}, {"_id": 0}).sort("code", 1).to_list(length=500)
    return items


@api_router.post("/cashbook/accounts")
async def cash_account_create(payload: CashAccountIn, user: dict = Depends(require_super_admin)):
    if payload.type not in ("in", "out"):
        raise HTTPException(status_code=400, detail="Type harus 'in' atau 'out'")
    if not payload.code.strip() or not payload.name.strip():
        raise HTTPException(status_code=400, detail="Kode & nama akun wajib")
    exists = await db.cash_accounts.find_one({"code": payload.code.strip()})
    if exists:
        raise HTTPException(status_code=400, detail="Kode akun sudah ada")
    doc = {
        "id": str(uuid.uuid4()),
        "code": payload.code.strip(),
        "name": payload.name.strip(),
        "type": payload.type,
        "active": payload.active,
        "system": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.cash_accounts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.put("/cashbook/accounts/{account_id}")
async def cash_account_update(account_id: str, payload: CashAccountIn, user: dict = Depends(require_super_admin)):
    existing = await db.cash_accounts.find_one({"id": account_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    if existing.get("system") and payload.code != existing.get("code"):
        raise HTTPException(status_code=400, detail="Kode akun sistem tidak boleh diubah")
    await db.cash_accounts.update_one(
        {"id": account_id},
        {"$set": {"code": payload.code.strip(), "name": payload.name.strip(), "type": payload.type, "active": payload.active}},
    )
    return await db.cash_accounts.find_one({"id": account_id}, {"_id": 0})


@api_router.delete("/cashbook/accounts/{account_id}")
async def cash_account_delete(account_id: str, user: dict = Depends(require_super_admin)):
    existing = await db.cash_accounts.find_one({"id": account_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    if existing.get("system"):
        raise HTTPException(status_code=400, detail="Akun sistem tidak bisa dihapus")
    # Cek apakah masih dipakai
    used = await db.cash_transactions.count_documents({"account_code": existing["code"]})
    if used > 0:
        raise HTTPException(status_code=400, detail=f"Akun masih dipakai di {used} transaksi. Non-aktifkan saja.")
    await db.cash_accounts.delete_one({"id": account_id})
    return {"ok": True}


@api_router.get("/cashbook/settings")
async def cash_settings_get(user: dict = Depends(require_super_admin)):
    return await _cash_setting()


@api_router.put("/cashbook/settings")
async def cash_settings_update(payload: CashSettingIn, user: dict = Depends(require_super_admin)):
    upd = {"opening_balance": round(float(payload.opening_balance), 2)}
    if payload.opening_date:
        upd["opening_date"] = payload.opening_date
    upd["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.cash_settings.update_one({"key": "main"}, {"$set": upd}, upsert=True)
    return await _cash_setting()


@api_router.get("/cashbook/transactions")
async def cash_transactions_list(
    user: dict = Depends(require_super_admin),
    month: Optional[str] = None,  # YYYY-MM
    account_code: Optional[str] = None,
):
    q: Dict[str, Any] = {}
    if month:
        try:
            year, m = month.split("-")
            first = f"{year}-{int(m):02d}-01"
            # last day of month
            from calendar import monthrange
            last_day = monthrange(int(year), int(m))[1]
            last = f"{year}-{int(m):02d}-{last_day:02d}"
            q["date"] = {"$gte": first, "$lte": last}
        except Exception:
            raise HTTPException(status_code=400, detail="Format month harus YYYY-MM")
    if account_code:
        q["account_code"] = account_code
    items = await db.cash_transactions.find(q, {"_id": 0}).sort([("date", 1), ("created_at", 1)]).to_list(length=20000)
    # Compute running balance
    setting = await _cash_setting()
    opening_balance = float(setting.get("opening_balance", 0))
    opening_date = setting.get("opening_date")
    # Kalau filter bulan, hitung saldo awal bulan dari transaksi sebelumnya + opening
    if month:
        first_of_month = q["date"]["$gte"]
        last_of_month = q["date"]["$lte"]
        prev = await db.cash_transactions.find(
            {"date": {"$lt": first_of_month}}, {"_id": 0, "type": 1, "amount": 1},
        ).to_list(length=100000)
        # Include opening_balance selama opening_date jatuh <= akhir periode
        # yang dilihat. Jika opening_date di masa depan (setelah bulan ini),
        # baru diabaikan.
        if opening_date and opening_date > last_of_month:
            balance = 0.0
        else:
            balance = opening_balance
        for p in prev:
            balance += float(p["amount"]) if p["type"] == "in" else -float(p["amount"])
        opening_of_period = round(balance, 2)
    else:
        opening_of_period = opening_balance
        balance = opening_balance
    running = []
    for it in items:
        balance += float(it["amount"]) if it["type"] == "in" else -float(it["amount"])
        it2 = dict(it)
        it2["balance"] = round(balance, 2)
        running.append(it2)
    return {
        "opening_balance": round(opening_of_period, 2),
        "transactions": running,
        "closing_balance": round(balance, 2),
    }


@api_router.post("/cashbook/transactions")
async def cash_transaction_create(payload: CashTransactionIn, user: dict = Depends(require_super_admin)):
    if not payload.description.strip():
        raise HTTPException(status_code=400, detail="Keterangan wajib diisi")
    doc = await _insert_cash_transaction(
        account_code=payload.account_code,
        description=payload.description,
        amount=payload.amount,
        reference=payload.reference,
        date_iso=payload.date,
        auto=False,
        created_by=user.get("email"),
    )
    return doc


@api_router.put("/cashbook/transactions/{tx_id}")
async def cash_transaction_update(tx_id: str, payload: CashTransactionIn, user: dict = Depends(require_super_admin)):
    existing = await db.cash_transactions.find_one({"id": tx_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    if existing.get("auto"):
        raise HTTPException(status_code=400, detail="Transaksi otomatis (dari Sales/PO) tidak bisa diedit. Ubah di modul sumbernya.")
    acc = await db.cash_accounts.find_one({"code": payload.account_code}, {"_id": 0})
    if not acc:
        raise HTTPException(status_code=404, detail=f"Akun {payload.account_code} tidak ditemukan")
    upd = {
        "date": payload.date,
        "account_code": acc["code"],
        "account_name": acc["name"],
        "type": acc["type"],
        "description": payload.description.strip(),
        "amount": round(float(payload.amount), 2),
        "reference": payload.reference,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.cash_transactions.update_one({"id": tx_id}, {"$set": upd})
    return await db.cash_transactions.find_one({"id": tx_id}, {"_id": 0})


async def _is_cash_tx_orphaned(tx: Dict[str, Any]) -> bool:
    """Cek apakah cash transaction AUTO adalah orphan (sumbernya sudah tidak ada)."""
    if not tx.get("auto"):
        return False
    ref = tx.get("reference")
    if not ref:
        return False
    code = tx.get("account_code")
    # code 201 = auto dari PO payment (reference = po_no)
    if code == "201":
        po = await db.purchase_orders.find_one({"po_no": ref}, {"_id": 0, "id": 1})
        return po is None
    # code 301, 301-BCA, 301-MDR, 301-SPP, 301-SPK = auto dari Sales (reference = sale_no)
    if code in PAYMENT_ACCOUNT_MAP.values():
        sale = await db.sales.find_one({"sale_no": ref}, {"_id": 0, "id": 1})
        return sale is None
    # code 101 + reference KASBON-* = auto dari pelunasan kasbon
    if code == "101" and isinstance(ref, str) and ref.startswith("KASBON-"):
        kasbon_id = ref.replace("KASBON-", "", 1)
        kasbon = await db.kasbon_sementara.find_one({"id": kasbon_id}, {"_id": 0, "id": 1})
        return kasbon is None
    return False


def _cash_tx_source_type(tx: Dict[str, Any]) -> str:
    code = tx.get("account_code")
    ref = tx.get("reference") or ""
    if code == "201":
        return "PO"
    if code in PAYMENT_ACCOUNT_MAP.values():
        return "Penjualan"
    if code == "101" and ref.startswith("KASBON-"):
        return "Kasbon"
    return "Unknown"


@api_router.delete("/cashbook/transactions/{tx_id}")
async def cash_transaction_delete(tx_id: str, force: bool = False, user: dict = Depends(require_super_admin)):
    existing = await db.cash_transactions.find_one({"id": tx_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    if existing.get("auto") and not force:
        # Cek apakah orphan — kalau iya, izinkan hapus tanpa force
        orphan = await _is_cash_tx_orphaned(existing)
        if not orphan:
            raise HTTPException(status_code=400, detail="Transaksi otomatis tidak bisa dihapus dari sini. Batalkan di modul sumbernya.")
    await db.cash_transactions.delete_one({"id": tx_id})
    return {"ok": True, "was_orphan": existing.get("auto", False)}


@api_router.get("/cashbook/transactions/{tx_id}/orphan-check")
async def cash_transaction_orphan_check(tx_id: str, user: dict = Depends(require_super_admin)):
    """Cek apakah transaksi kas AUTO adalah orphan (sumbernya sudah dihapus)."""
    existing = await db.cash_transactions.find_one({"id": tx_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    if not existing.get("auto"):
        return {"is_auto": False, "is_orphan": False, "reference": existing.get("reference")}
    orphan = await _is_cash_tx_orphaned(existing)
    return {
        "is_auto": True,
        "is_orphan": orphan,
        "reference": existing.get("reference"),
        "account_code": existing.get("account_code"),
        "source_type": _cash_tx_source_type(existing),
    }


@api_router.get("/cashbook/balance")
async def cash_balance(user: dict = Depends(require_super_admin)):
    setting = await _cash_setting()
    txs = await db.cash_transactions.find({}, {"_id": 0, "type": 1, "amount": 1}).to_list(length=200000)
    total_in = sum(float(t["amount"]) for t in txs if t["type"] == "in")
    total_out = sum(float(t["amount"]) for t in txs if t["type"] == "out")
    balance = float(setting.get("opening_balance", 0)) + total_in - total_out
    return {
        "opening_balance": round(float(setting.get("opening_balance", 0)), 2),
        "opening_date": setting.get("opening_date"),
        "total_in": round(total_in, 2),
        "total_out": round(total_out, 2),
        "balance": round(balance, 2),
        "tx_count": len(txs),
    }


@api_router.get("/cashbook/summary")
async def cash_summary(
    user: dict = Depends(require_super_admin),
    month: Optional[str] = None,  # YYYY-MM
):
    if not month:
        month = datetime.now(timezone.utc).date().strftime("%Y-%m")
    try:
        year, m = month.split("-")
        from calendar import monthrange
        first = f"{year}-{int(m):02d}-01"
        last_day = monthrange(int(year), int(m))[1]
        last = f"{year}-{int(m):02d}-{last_day:02d}"
    except Exception:
        raise HTTPException(status_code=400, detail="Format month harus YYYY-MM")

    setting = await _cash_setting()
    opening_balance = float(setting.get("opening_balance", 0))
    opening_date = setting.get("opening_date") or ""

    # Opening balance per bulan = opening_balance + net transaksi sebelum first
    prev = await db.cash_transactions.find(
        {"date": {"$lt": first}}, {"_id": 0, "type": 1, "amount": 1},
    ).to_list(length=200000)
    prev_net = 0.0
    for p in prev:
        prev_net += float(p["amount"]) if p["type"] == "in" else -float(p["amount"])
    if opening_date and opening_date > last:
        opening_of_period = 0.0
    else:
        opening_of_period = opening_balance
    opening_of_period += prev_net

    # Transaksi bulan ini
    month_tx = await db.cash_transactions.find({"date": {"$gte": first, "$lte": last}}, {"_id": 0}).to_list(length=50000)
    total_in = sum(float(t["amount"]) for t in month_tx if t["type"] == "in")
    total_out = sum(float(t["amount"]) for t in month_tx if t["type"] == "out")
    closing = opening_of_period + total_in - total_out

    # Breakdown per kategori
    breakdown_in: Dict[str, Dict[str, Any]] = {}
    breakdown_out: Dict[str, Dict[str, Any]] = {}
    for t in month_tx:
        target = breakdown_in if t["type"] == "in" else breakdown_out
        key = t["account_code"]
        row = target.setdefault(key, {
            "account_code": key,
            "account_name": t.get("account_name", key),
            "amount": 0.0,
            "count": 0,
        })
        row["amount"] += float(t["amount"])
        row["count"] += 1
    for row in list(breakdown_in.values()) + list(breakdown_out.values()):
        row["amount"] = round(row["amount"], 2)

    return {
        "month": month,
        "period_start": first,
        "period_end": last,
        "opening_balance": round(opening_of_period, 2),
        "total_in": round(total_in, 2),
        "total_out": round(total_out, 2),
        "net": round(total_in - total_out, 2),
        "closing_balance": round(closing, 2),
        "tx_count": len(month_tx),
        "breakdown_in": sorted(breakdown_in.values(), key=lambda x: x["amount"], reverse=True),
        "breakdown_out": sorted(breakdown_out.values(), key=lambda x: x["amount"], reverse=True),
    }


@api_router.get("/cashbook/export")
async def cash_export(user: dict = Depends(require_super_admin), month: Optional[str] = None):
    """Export bulan tertentu ke Excel."""
    if not month:
        month = datetime.now(timezone.utc).date().strftime("%Y-%m")
    data = await cash_transactions_list(user=user, month=month)
    setting = await _cash_setting()
    import pandas as pd
    from io import BytesIO
    ci = _company_info()

    rows = []
    # Baris pembuka
    rows.append({
        "Tanggal": "",
        "Kode Akun": "",
        "Nama Akun": "SALDO AWAL",
        "Keterangan": f"Periode {month}",
        "Pemasukan": "",
        "Pengeluaran": "",
        "Saldo": data["opening_balance"],
    })
    for t in data["transactions"]:
        rows.append({
            "Tanggal": t["date"],
            "Kode Akun": t["account_code"],
            "Nama Akun": t["account_name"],
            "Keterangan": t.get("description", ""),
            "Pemasukan": t["amount"] if t["type"] == "in" else "",
            "Pengeluaran": t["amount"] if t["type"] == "out" else "",
            "Saldo": t["balance"],
        })
    rows.append({
        "Tanggal": "",
        "Kode Akun": "",
        "Nama Akun": "SALDO AKHIR",
        "Keterangan": f"Total {len(data['transactions'])} transaksi",
        "Pemasukan": "",
        "Pengeluaran": "",
        "Saldo": data["closing_balance"],
    })
    df = pd.DataFrame(rows)

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=f"Kas {month}")
        # Auto width
        ws = writer.sheets[f"Kas {month}"]
        for col_idx, col in enumerate(df.columns, 1):
            max_len = max((len(str(v)) for v in df[col].astype(str).values), default=10)
            max_len = max(max_len, len(str(col)))
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 60)
    buf.seek(0)
    fname = f"Kas_Operasional_{ci['name'].replace(' ', '_')}_{month}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ================================================================
# ==================== KASBON SEMENTARA (Cash Advance) ============
# ================================================================
class KasbonIn(BaseModel):
    date: str  # YYYY-MM-DD
    name: str
    description: Optional[str] = ""
    amount: float


@api_router.get("/cashbook/kasbon")
async def kasbon_list(
    user: dict = Depends(require_super_admin),
    month: Optional[str] = None,  # YYYY-MM (opsional)
    status: Optional[str] = None,  # "open" | "settled"
):
    q: Dict[str, Any] = {}
    if month:
        try:
            year, m = month.split("-")
            first = f"{year}-{int(m):02d}-01"
            if int(m) == 12:
                nxt = f"{int(year)+1}-01-01"
            else:
                nxt = f"{year}-{int(m)+1:02d}-01"
            q["date"] = {"$gte": first, "$lt": nxt}
        except Exception:
            raise HTTPException(status_code=400, detail="Format bulan salah, gunakan YYYY-MM")
    if status in ("open", "settled"):
        q["status"] = status
    items = await db.kasbon_sementara.find(q, {"_id": 0}).sort([("date", 1), ("created_at", 1)]).to_list(length=5000)
    total_open = sum(float(i.get("amount", 0)) for i in items if i.get("status") == "open")
    total_settled = sum(float(i.get("amount", 0)) for i in items if i.get("status") == "settled")
    total_all = sum(float(i.get("amount", 0)) for i in items)
    return {
        "items": items,
        "total_open": round(total_open, 2),
        "total_settled": round(total_settled, 2),
        "total_all": round(total_all, 2),
        "count": len(items),
    }


@api_router.post("/cashbook/kasbon")
async def kasbon_create(payload: KasbonIn, user: dict = Depends(require_super_admin)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Nama wajib diisi")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Jumlah harus > 0")
    doc = {
        "id": str(uuid.uuid4()),
        "date": payload.date,
        "name": payload.name.strip(),
        "description": (payload.description or "").strip(),
        "amount": round(float(payload.amount), 2),
        "status": "open",
        "settled_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user.get("email"),
    }
    await db.kasbon_sementara.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.put("/cashbook/kasbon/{kasbon_id}")
async def kasbon_update(kasbon_id: str, payload: KasbonIn, user: dict = Depends(require_super_admin)):
    existing = await db.kasbon_sementara.find_one({"id": kasbon_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Kasbon tidak ditemukan")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Nama wajib diisi")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Jumlah harus > 0")
    await db.kasbon_sementara.update_one(
        {"id": kasbon_id},
        {"$set": {
            "date": payload.date,
            "name": payload.name.strip(),
            "description": (payload.description or "").strip(),
            "amount": round(float(payload.amount), 2),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    doc = await db.kasbon_sementara.find_one({"id": kasbon_id}, {"_id": 0})
    return doc


def _kasbon_ref(kasbon_id: str) -> str:
    return f"KASBON-{kasbon_id}"


async def _kasbon_create_settlement_tx(kasbon: Dict[str, Any], user_email: Optional[str]) -> None:
    """Insert auto cash-out transaction on Akun 101 Kas untuk pelunasan kasbon.
    Bypass _insert_cash_transaction karena akun 101 default type=in; kita perlu type=out
    agar muncul di kolom DEBET dan mengurangi saldo Kas Utama.
    """
    await _ensure_cash_accounts()
    kas_acc = await db.cash_accounts.find_one({"code": "101"}, {"_id": 0})
    name = kasbon.get("name") or "-"
    desc_extra = (kasbon.get("description") or "").strip()
    description = f"Pelunasan Kasbon - {name}"
    if desc_extra:
        description += f" - {desc_extra}"
    tx_doc = {
        "id": str(uuid.uuid4()),
        "date": datetime.now(timezone.utc).date().isoformat(),
        "account_code": "101",
        "account_name": (kas_acc.get("name") if kas_acc else "Kas"),
        "type": "out",
        "description": description,
        "amount": round(float(kasbon.get("amount", 0)), 2),
        "reference": _kasbon_ref(kasbon.get("id", "")),
        "auto": True,
        "created_by": user_email,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.cash_transactions.insert_one(tx_doc)


async def _kasbon_delete_settlement_tx(kasbon_id: str) -> None:
    """Hapus semua auto cash-tx pelunasan yang dibuat untuk kasbon ini."""
    await db.cash_transactions.delete_many({
        "reference": _kasbon_ref(kasbon_id),
        "auto": True,
        "account_code": "101",
        "type": "out",
    })


@api_router.put("/cashbook/kasbon/{kasbon_id}/settle")
async def kasbon_settle(kasbon_id: str, user: dict = Depends(require_super_admin)):
    existing = await db.kasbon_sementara.find_one({"id": kasbon_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Kasbon tidak ditemukan")
    if existing.get("status") == "settled":
        raise HTTPException(status_code=400, detail="Kasbon sudah dilunaskan")
    settled_at = datetime.now(timezone.utc).isoformat()
    await db.kasbon_sementara.update_one(
        {"id": kasbon_id},
        {"$set": {"status": "settled", "settled_at": settled_at}},
    )
    # Auto-insert pengeluaran ke Jurnal Kas Utama (Akun 101, DEBET)
    try:
        # Bersihkan sisa tx lama (jika ada) sebelum insert baru — idempotent
        await _kasbon_delete_settlement_tx(kasbon_id)
        await _kasbon_create_settlement_tx(existing, user.get("email"))
    except Exception as ex:
        logger.warning(f"Cashbook auto-insert (kasbon settle) failed: {ex}")
    doc = await db.kasbon_sementara.find_one({"id": kasbon_id}, {"_id": 0})
    return doc


@api_router.put("/cashbook/kasbon/{kasbon_id}/reopen")
async def kasbon_reopen(kasbon_id: str, user: dict = Depends(require_super_admin)):
    existing = await db.kasbon_sementara.find_one({"id": kasbon_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Kasbon tidak ditemukan")
    await db.kasbon_sementara.update_one(
        {"id": kasbon_id},
        {"$set": {"status": "open", "settled_at": None}},
    )
    # Rollback auto cash-tx pelunasan
    try:
        await _kasbon_delete_settlement_tx(kasbon_id)
    except Exception as ex:
        logger.warning(f"Cashbook auto-delete (kasbon reopen) failed: {ex}")
    doc = await db.kasbon_sementara.find_one({"id": kasbon_id}, {"_id": 0})
    return doc


@api_router.delete("/cashbook/kasbon/{kasbon_id}")
async def kasbon_delete(kasbon_id: str, user: dict = Depends(require_super_admin)):
    res = await db.kasbon_sementara.delete_one({"id": kasbon_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Kasbon tidak ditemukan")
    # Cascade: hapus auto cash-tx pelunasan jika ada
    try:
        await _kasbon_delete_settlement_tx(kasbon_id)
    except Exception as ex:
        logger.warning(f"Cashbook auto-delete (kasbon delete) failed: {ex}")
    return {"ok": True}


# Include router
app.include_router(api_router)


# ---------------- RBAC Middleware ----------------
# Enforces per-menu access for role=admin_privileged based on request path prefix.
# Super admin, portal endpoints, and auth endpoints bypass this check.
@app.middleware("http")
async def rbac_middleware(request: Request, call_next):
    path = request.url.path
    # Only guard /api paths that aren't in bypass list
    if not path.startswith("/api"):
        return await call_next(request)
    if any(path.startswith(pref) for pref in RBAC_BYPASS_PREFIXES):
        return await call_next(request)

    # Extract token (cookie or bearer). No token -> let endpoint dep return 401.
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        return await call_next(request)

    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return await call_next(request)
        user_id = payload.get("sub")
    except jwt.PyJWTError:
        return await call_next(request)

    if not user_id:
        return await call_next(request)
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not u:
        return await call_next(request)

    role = u.get("role")
    if role == "admin":
        role = ROLE_SUPER_ADMIN
    if role == "hr_leave":
        role = ROLE_ADMIN_PRIVILEGED
    if role == ROLE_SUPER_ADMIN:
        return await call_next(request)
    if role != ROLE_ADMIN_PRIVILEGED:
        return await call_next(request)

    # admin_privileged → check menu perm
    menu = _menu_for_path(path)
    if menu is None:
        # Path not mapped to any menu → allow (fallthrough to endpoint auth)
        return await call_next(request)
    perms = u.get("permissions") or []
    if menu not in perms:
        from starlette.responses import JSONResponse
        return JSONResponse(
            status_code=403,
            content={"detail": f"Akses ditolak: Anda tidak memiliki izin untuk menu '{menu}'"},
        )
    return await call_next(request)


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
