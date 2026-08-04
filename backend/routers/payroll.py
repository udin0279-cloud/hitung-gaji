"""Payroll router — Admin Payroll endpoints (Slip Gaji, THR, Email, WhatsApp, Bank Export, Bukti Potong).

Extracted from `server.py` (2026-08-04) — Bagian dari lanjutan refactor modularisasi
setelah Attendance, Cashbook, Sales, dan Backup.

Endpoints:
  POST   /payroll/preview
  POST   /payroll/run
  GET    /payroll/runs
  GET    /payroll/runs/{period}/slips
  GET    /payroll/payslip/{slip_id}
  DELETE /payroll/runs/{period}
  GET    /payroll/payslip/{slip_id}/pdf
  POST   /payroll/thr/preview
  POST   /payroll/thr/run
  GET    /payroll/thr/runs
  GET    /payroll/thr/{period}/slips
  POST   /payroll/payslip/{slip_id}/email
  POST   /payroll/runs/{period}/email-all
  GET    /payroll/runs/{period}/bank-export
  POST   /payroll/payslip/{slip_id}/whatsapp
  POST   /payroll/runs/{period}/whatsapp-all
  GET    /payroll/bukti-potong/{employee_id}/{year}/pdf

Semua helper (calculate_payslip, _build_payslip_pdf, _send_email_via_resend, dll.)
diinjeksikan lewat factory `make_router(...)` — tetap tinggal di server.py agar tidak
memutus dependency chain untuk endpoint Portal & Employee yang masih di server.py.
"""
import asyncio
import io
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


# --- Local Pydantic models (identik dengan versi di server.py sebelum extract) ---
class PayrollRunIn(BaseModel):
    period: str  # YYYY-MM
    attendance: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    overrides: Dict[str, Dict[str, float]] = Field(default_factory=dict)


class THRRunIn(BaseModel):
    period: str  # YYYY-MM (month THR is paid)


def make_router(
    *,
    db,
    require_super_admin,
    logger,
    calculate_payslip,
    _calculate_thr,
    _build_payslip_pdf,
    _payslip_html,
    _send_email_via_resend,
    _whatsapp_slip_message,
    _send_whatsapp,
    _format_bank_export,
    _build_annual_summary,
    _build_bukti_potong_pdf,
):
    router = APIRouter()

    # ---------------- Preview / Run ----------------
    @router.post("/payroll/preview")
    async def preview_payroll(payload: PayrollRunIn, user: dict = Depends(require_super_admin)):
        employees = await db.employees.find({"active": True}, {"_id": 0}).to_list(length=2000)
        slips = []
        for emp in employees:
            att = payload.attendance.get(emp["id"], {"days_worked": 22})
            ov = payload.overrides.get(emp["id"], {})
            slip = calculate_payslip(emp, att, ov)
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

    @router.post("/payroll/run")
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
            ov = payload.overrides.get(emp["id"], {})
            slip = calculate_payslip(emp, att, ov)
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

    @router.get("/payroll/runs")
    async def list_runs(user: dict = Depends(require_super_admin)):
        runs = await db.payroll_runs.find({}, {"_id": 0}).sort("period", -1).to_list(length=500)
        return runs

    @router.get("/payroll/runs/{period}/slips")
    async def list_run_slips(period: str, user: dict = Depends(require_super_admin)):
        slips = await db.payslips.find({"period": period}, {"_id": 0}).sort("name", 1).to_list(length=2000)
        if not slips:
            raise HTTPException(status_code=404, detail="Payroll untuk periode ini belum dijalankan")
        return slips

    @router.get("/payroll/payslip/{slip_id}")
    async def get_payslip(slip_id: str, user: dict = Depends(require_super_admin)):
        slip = await db.payslips.find_one({"id": slip_id}, {"_id": 0})
        if not slip:
            raise HTTPException(status_code=404, detail="Slip gaji tidak ditemukan")
        return slip

    @router.delete("/payroll/runs/{period}")
    async def delete_run(period: str, user: dict = Depends(require_super_admin)):
        # Rollback loan_tenor increments for any active loan deductions in this run
        old_slips = await db.payslips.find({"period": period}, {"_id": 0, "employee_id": 1, "loan_info": 1}).to_list(length=5000)
        for os_ in old_slips:
            if os_.get("loan_info", {}).get("active"):
                await db.employees.update_one({"id": os_["employee_id"]}, {"$inc": {"loan_tenor_paid": -1}})
        await db.payroll_runs.delete_one({"period": period})
        await db.payslips.delete_many({"period": period})
        return {"ok": True}

    # ---------------- Payslip PDF ----------------
    @router.get("/payroll/payslip/{slip_id}/pdf")
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

    # ---------------- THR ----------------
    @router.post("/payroll/thr/preview")
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

    @router.post("/payroll/thr/run")
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

    @router.get("/payroll/thr/runs")
    async def list_thr_runs(user: dict = Depends(require_super_admin)):
        return await db.thr_runs.find({}, {"_id": 0}).sort("period", -1).to_list(length=200)

    @router.get("/payroll/thr/{period}/slips")
    async def thr_slips(period: str, user: dict = Depends(require_super_admin)):
        rows = await db.thr_slips.find({"period": period}, {"_id": 0}).sort("name", 1).to_list(length=2000)
        if not rows:
            raise HTTPException(status_code=404, detail="THR untuk periode ini belum dijalankan")
        return rows

    # ---------------- Email ----------------
    @router.post("/payroll/payslip/{slip_id}/email")
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

    @router.post("/payroll/runs/{period}/email-all")
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

    # ---------------- Bank Export ----------------
    @router.get("/payroll/runs/{period}/bank-export")
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

    # ---------------- WhatsApp ----------------
    @router.post("/payroll/payslip/{slip_id}/whatsapp")
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

    @router.post("/payroll/runs/{period}/whatsapp-all")
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

    # ---------------- Bukti Potong (Admin) ----------------
    @router.get("/payroll/bukti-potong/{employee_id}/{year}/pdf")
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

    return router
