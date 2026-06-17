from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
import uuid
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

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
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


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
    position: str
    department: str
    join_date: str  # ISO date
    basic_salary: float
    fixed_allowance: float = 0  # tunjangan tetap (transportasi, makan, dll)
    ptkp_status: str = "TK/0"  # TK/0, K/0, K/1, K/2, K/3
    npwp: Optional[str] = None
    has_npwp: bool = True
    bpjs_kesehatan: bool = True
    bpjs_ketenagakerjaan: bool = True
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    active: bool = True


class EmployeeOut(EmployeeIn):
    id: str
    created_at: str


# Payroll
class PayrollRunIn(BaseModel):
    period: str  # YYYY-MM
    attendance: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    # attendance[employee_id] = {"days_worked": 22, "overtime_hours": 0, "bonus": 0, "deduction": 0}


# ---------------- Indonesian Payroll Constants (2024+) ----------------
PTKP_TABLE = {
    "TK/0": 54_000_000,
    "TK/1": 58_500_000,
    "TK/2": 63_000_000,
    "TK/3": 67_500_000,
    "K/0": 58_500_000,
    "K/1": 63_000_000,
    "K/2": 67_500_000,
    "K/3": 72_000_000,
}

# PPh 21 brackets (UU HPP 2022)
PPH21_BRACKETS = [
    (60_000_000, 0.05),
    (250_000_000, 0.15),
    (500_000_000, 0.25),
    (5_000_000_000, 0.30),
    (float("inf"), 0.35),
]

# BPJS rates
BPJS_KESEHATAN_EMPLOYEE = 0.01
BPJS_KESEHATAN_EMPLOYER = 0.04
BPJS_KESEHATAN_MAX_BASE = 12_000_000

JHT_EMPLOYEE = 0.02
JHT_EMPLOYER = 0.037

JP_EMPLOYEE = 0.01
JP_EMPLOYER = 0.02
JP_MAX_BASE = 10_042_300  # 2024 ceiling

JKK_EMPLOYER = 0.0024
JKM_EMPLOYER = 0.003

BIAYA_JABATAN_RATE = 0.05
BIAYA_JABATAN_MAX_YEAR = 6_000_000


def compute_pph21_annual(pkp: float) -> float:
    if pkp <= 0:
        return 0.0
    tax = 0.0
    prev_limit = 0.0
    for limit, rate in PPH21_BRACKETS:
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
    overtime_hours = float(attendance.get("overtime_hours", 0) or 0)
    bonus = float(attendance.get("bonus", 0) or 0)
    other_deduction = float(attendance.get("deduction", 0) or 0)
    days_worked = float(attendance.get("days_worked", 22) or 22)

    # Overtime rate: 1/173 * basic salary per hour (Indonesian standard)
    overtime_rate_per_hour = basic / 173 if basic else 0
    overtime_pay = overtime_rate_per_hour * overtime_hours * 1.5  # simplified

    # Pro-rate basic if days_worked < 22 (standard month)
    standard_days = 22
    prorate_factor = min(days_worked / standard_days, 1.0) if standard_days > 0 else 1.0
    basic_paid = basic * prorate_factor

    gross = basic_paid + fixed_allowance + overtime_pay + bonus

    # BPJS Kesehatan (capped)
    bpjs_kes_base = min(basic_paid + fixed_allowance, BPJS_KESEHATAN_MAX_BASE) if employee.get("bpjs_kesehatan") else 0
    bpjs_kes_employee = bpjs_kes_base * BPJS_KESEHATAN_EMPLOYEE
    bpjs_kes_employer = bpjs_kes_base * BPJS_KESEHATAN_EMPLOYER

    # BPJS Ketenagakerjaan
    has_btk = employee.get("bpjs_ketenagakerjaan", True)
    jht_base = basic_paid + fixed_allowance if has_btk else 0
    jp_base = min(basic_paid + fixed_allowance, JP_MAX_BASE) if has_btk else 0

    jht_employee = jht_base * JHT_EMPLOYEE
    jht_employer = jht_base * JHT_EMPLOYER
    jp_employee = jp_base * JP_EMPLOYEE
    jp_employer = jp_base * JP_EMPLOYER
    jkk_employer = jht_base * JKK_EMPLOYER
    jkm_employer = jht_base * JKM_EMPLOYER

    # Annual PPh21 calculation (gross-up method simplified)
    # Bruto setahun = (gross monthly) * 12 + employer BPJS Kes + JKK + JKM (treated as add-on)
    bruto_monthly = gross + bpjs_kes_employer + jkk_employer + jkm_employer
    bruto_yearly = bruto_monthly * 12

    biaya_jabatan_yearly = min(bruto_yearly * BIAYA_JABATAN_RATE, BIAYA_JABATAN_MAX_YEAR)
    iuran_pengurang_yearly = (jht_employee + jp_employee) * 12

    netto_yearly = bruto_yearly - biaya_jabatan_yearly - iuran_pengurang_yearly
    ptkp = PTKP_TABLE.get(employee.get("ptkp_status", "TK/0"), 54_000_000)
    pkp = max(0, netto_yearly - ptkp)
    # Round down PKP to thousands per UU HPP
    pkp = (pkp // 1000) * 1000

    pph21_yearly = compute_pph21_annual(pkp)
    # Non-NPWP surcharge: +20%
    if not employee.get("has_npwp", True):
        pph21_yearly *= 1.2
    pph21_monthly = pph21_yearly / 12

    total_deductions = bpjs_kes_employee + jht_employee + jp_employee + pph21_monthly + other_deduction
    net_salary = gross - total_deductions

    return {
        "earnings": {
            "basic_salary": round(basic_paid, 2),
            "fixed_allowance": round(fixed_allowance, 2),
            "overtime": round(overtime_pay, 2),
            "bonus": round(bonus, 2),
            "gross": round(gross, 2),
        },
        "deductions": {
            "bpjs_kesehatan_employee": round(bpjs_kes_employee, 2),
            "jht_employee": round(jht_employee, 2),
            "jp_employee": round(jp_employee, 2),
            "pph21": round(pph21_monthly, 2),
            "other_deduction": round(other_deduction, 2),
            "total": round(total_deductions, 2),
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


# ---------------- Employee Endpoints ----------------
@api_router.get("/employees")
async def list_employees(user: dict = Depends(get_current_user)):
    cursor = db.employees.find({}, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(length=2000)
    return items


@api_router.post("/employees")
async def create_employee(payload: EmployeeIn, user: dict = Depends(get_current_user)):
    if await db.employees.find_one({"nik": payload.nik}):
        raise HTTPException(status_code=400, detail="NIK sudah terdaftar")
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.get("/employees/{employee_id}")
async def get_employee(employee_id: str, user: dict = Depends(get_current_user)):
    emp = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")
    return emp


@api_router.put("/employees/{employee_id}")
async def update_employee(employee_id: str, payload: EmployeeIn, user: dict = Depends(get_current_user)):
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
async def delete_employee(employee_id: str, user: dict = Depends(get_current_user)):
    res = await db.employees.delete_one({"id": employee_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")
    return {"ok": True}


# ---------------- Payroll Endpoints ----------------
@api_router.post("/payroll/preview")
async def preview_payroll(payload: PayrollRunIn, user: dict = Depends(get_current_user)):
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
async def run_payroll(payload: PayrollRunIn, user: dict = Depends(get_current_user)):
    existing = await db.payroll_runs.find_one({"period": payload.period})
    if existing:
        # overwrite previous run for same period
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
async def list_runs(user: dict = Depends(get_current_user)):
    runs = await db.payroll_runs.find({}, {"_id": 0}).sort("period", -1).to_list(length=500)
    return runs


@api_router.get("/payroll/runs/{period}/slips")
async def list_run_slips(period: str, user: dict = Depends(get_current_user)):
    slips = await db.payslips.find({"period": period}, {"_id": 0}).sort("name", 1).to_list(length=2000)
    if not slips:
        raise HTTPException(status_code=404, detail="Payroll untuk periode ini belum dijalankan")
    return slips


@api_router.get("/payroll/payslip/{slip_id}")
async def get_payslip(slip_id: str, user: dict = Depends(get_current_user)):
    slip = await db.payslips.find_one({"id": slip_id}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Slip gaji tidak ditemukan")
    return slip


@api_router.delete("/payroll/runs/{period}")
async def delete_run(period: str, user: dict = Depends(get_current_user)):
    await db.payroll_runs.delete_one({"period": period})
    await db.payslips.delete_many({"period": period})
    return {"ok": True}


# ---------------- Dashboard ----------------
@api_router.get("/dashboard/stats")
async def dashboard_stats(user: dict = Depends(get_current_user)):
    total_employees = await db.employees.count_documents({"active": True})
    runs = await db.payroll_runs.find({}, {"_id": 0}).sort("period", -1).to_list(length=12)
    latest = runs[0] if runs else None
    trend = list(reversed([
        {"period": r["period"], "total_net": r["total_net"], "total_gross": r["total_gross"]}
        for r in runs
    ]))
    return {
        "total_employees": total_employees,
        "latest_run": latest,
        "trend": trend,
        "total_runs": await db.payroll_runs.count_documents({}),
    }


# ---------------- Config ----------------
@api_router.get("/config/constants")
async def config_constants(user: dict = Depends(get_current_user)):
    return {
        "ptkp_table": PTKP_TABLE,
        "pph21_brackets": [{"limit": b[0] if b[0] != float("inf") else None, "rate": b[1]} for b in PPH21_BRACKETS],
        "bpjs": {
            "kesehatan_employee": BPJS_KESEHATAN_EMPLOYEE,
            "kesehatan_employer": BPJS_KESEHATAN_EMPLOYER,
            "kesehatan_max_base": BPJS_KESEHATAN_MAX_BASE,
            "jht_employee": JHT_EMPLOYEE,
            "jht_employer": JHT_EMPLOYER,
            "jp_employee": JP_EMPLOYEE,
            "jp_employer": JP_EMPLOYER,
            "jp_max_base": JP_MAX_BASE,
            "jkk_employer": JKK_EMPLOYER,
            "jkm_employer": JKM_EMPLOYER,
        },
        "biaya_jabatan_max_year": BIAYA_JABATAN_MAX_YEAR,
    }


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

    admin_email = os.environ.get("ADMIN_EMAIL", "admin@payroll.id").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": "Admin HR",
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Seeded admin user: {admin_email}")
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}},
        )
        logger.info("Updated admin password from .env")


@app.on_event("shutdown")
async def shutdown():
    client.close()


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
