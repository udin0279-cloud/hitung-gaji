from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
import uuid
import asyncio
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
import csv
import io

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

    gross = basic_paid + fixed_allowance + overtime_pay + bonus

    # BPJS Kesehatan (capped)
    bpjs_kes_base = min(basic_paid + fixed_allowance, CONFIG["bpjs_kesehatan_max_base"]) if employee.get("bpjs_kesehatan") else 0
    bpjs_kes_employee = bpjs_kes_base * CONFIG["bpjs_kesehatan_employee"]
    bpjs_kes_employer = bpjs_kes_base * CONFIG["bpjs_kesehatan_employer"]

    # BPJS Ketenagakerjaan
    has_btk = employee.get("bpjs_ketenagakerjaan", True)
    jht_base = basic_paid + fixed_allowance if has_btk else 0
    jp_base = min(basic_paid + fixed_allowance, CONFIG["jp_max_base"]) if has_btk else 0

    jht_employee = jht_base * CONFIG["jht_employee"]
    jht_employer = jht_base * CONFIG["jht_employer"]
    jp_employee = jp_base * CONFIG["jp_employee"]
    jp_employer = jp_base * CONFIG["jp_employer"]
    jkk_employer = jht_base * CONFIG["jkk_employer"]
    jkm_employer = jht_base * CONFIG["jkm_employer"]

    # Annual PPh21 calculation (gross-up method simplified)
    bruto_monthly = gross + bpjs_kes_employer + jkk_employer + jkm_employer
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
        ["Tunjangan Tetap", _format_idr(e["fixed_allowance"])],
        ["Lembur", _format_idr(e["overtime"])],
        ["Bonus", _format_idr(e["bonus"])],
        ["Total Bruto", _format_idr(e["gross"])],
    ]
    deduct_rows = [
        ["POTONGAN", ""],
        ["BPJS Kesehatan (1%)", _format_idr(d["bpjs_kesehatan_employee"])],
        ["JHT (2%)", _format_idr(d["jht_employee"])],
        ["JP (1%)", _format_idr(d["jp_employee"])],
        ["PPh 21", _format_idr(d["pph21"])],
        ["Potongan Lain", _format_idr(d["other_deduction"])],
        ["Total Potongan", _format_idr(d["total"])],
    ]
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
async def export_payslip_pdf(slip_id: str, user: dict = Depends(get_current_user)):
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
    "nik", "name", "email", "position", "department", "join_date",
    "basic_salary", "fixed_allowance", "ptkp_status", "npwp", "has_npwp",
    "bpjs_kesehatan", "bpjs_ketenagakerjaan", "bank_name", "bank_account",
]


def _parse_bool(v: str, default: bool = True) -> bool:
    if v is None or v == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "ya", "y")


@api_router.get("/employees-template.csv")
async def employee_template(user: dict = Depends(get_current_user)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EMPLOYEE_CSV_HEADERS)
    # example row
    writer.writerow([
        "EMP001", "Budi Santoso", "budi@company.id", "Software Engineer", "Engineering",
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
async def employees_import(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
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
    user: dict = Depends(get_current_user),
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
async def get_attendance(period: str, user: dict = Depends(get_current_user)):
    rec = await db.attendance_imports.find_one({"period": period}, {"_id": 0})
    if not rec:
        return {"period": period, "summary": {}, "matched_employees": 0, "total_scans": 0, "unmatched_niks": []}
    return rec


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
async def update_config(payload: ConfigUpdateIn, user: dict = Depends(get_current_user)):
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
async def thr_preview(payload: THRRunIn, user: dict = Depends(get_current_user)):
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
async def thr_run(payload: THRRunIn, user: dict = Depends(get_current_user)):
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
async def list_thr_runs(user: dict = Depends(get_current_user)):
    return await db.thr_runs.find({}, {"_id": 0}).sort("period", -1).to_list(length=200)


@api_router.get("/payroll/thr/{period}/slips")
async def thr_slips(period: str, user: dict = Depends(get_current_user)):
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


@api_router.post("/payroll/payslip/{slip_id}/email")
async def email_single_payslip(slip_id: str, user: dict = Depends(get_current_user)):
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
async def email_all_payslips(period: str, user: dict = Depends(get_current_user)):
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
        rows.append({
            "nik": s["nik"],
            "name": s["name"],
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
async def bank_export(period: str, format: str = "generic", user: dict = Depends(get_current_user)):
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
