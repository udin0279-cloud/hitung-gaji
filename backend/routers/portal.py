"""Portal router — Employee self-service portal endpoints.

Extracted from `server.py` (2026-08-04).

Endpoints:
  POST   /portal/login
  POST   /portal/logout
  GET    /portal/me
  GET    /portal/payslips
  GET    /portal/payslip/{slip_id}
  GET    /portal/payslip/{slip_id}/pdf
  GET    /portal/thr
  GET    /portal/annual/{year}
  GET    /portal/bukti-potong/{year}/pdf
  POST   /portal/forgot
  POST   /portal/magic-login
  POST   /portal/leave                              (multipart)
  GET    /portal/leave
  DELETE /portal/leave/{leave_id}
  GET    /portal/leave/{leave_id}/attachment

Semua helper (JWT, PDF builder, annual summary, email sender, leave view) diinjeksi
via factory `make_router(...)` — tetap tinggal di server.py agar model & konstanta HR
tidak duplikasi.
"""
import asyncio
import base64
import io
import os
import secrets as pysecrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr


# --- Local Pydantic models (identik dengan versi di server.py sebelum extract) ---
class PortalLoginIn(BaseModel):
    email: EmailStr
    nik: str


class ForgotPortalIn(BaseModel):
    email: EmailStr


def make_router(
    *,
    db,
    logger,
    get_current_employee,
    create_portal_token,
    _build_payslip_pdf,
    _build_annual_summary,
    _build_bukti_potong_pdf,
    _send_simple_email,
    _leave_view,
    LEAVE_TYPES,
    LEAVE_TYPE_LABELS,
    MAX_ATTACHMENT_SIZE,
    ALLOWED_ATTACHMENT_MIME,
):
    router = APIRouter()

    # ---------------- Auth ----------------
    @router.post("/portal/login")
    async def portal_login(payload: PortalLoginIn, response: Response):
        email = payload.email.lower().strip()
        nik = payload.nik.strip()
        emp = await db.employees.find_one({"nik": nik, "active": True}, {"_id": 0})
        if not emp:
            raise HTTPException(status_code=401, detail="NIK atau email salah")
        if (emp.get("email") or "").lower() != email:
            raise HTTPException(status_code=401, detail="NIK atau email salah")
        token = create_portal_token(emp["id"], email)
        response.set_cookie("portal_token", token, httponly=True, secure=True, samesite="lax", max_age=86400, path="/")
        return {
            "id": emp["id"],
            "nik": emp["nik"],
            "name": emp["name"],
            "email": emp.get("email"),
            "position": emp["position"],
            "department": emp["department"],
        }

    @router.post("/portal/logout")
    async def portal_logout(response: Response):
        response.delete_cookie("portal_token", path="/")
        return {"ok": True}

    @router.get("/portal/me")
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

    # ---------------- Payslips ----------------
    @router.get("/portal/payslips")
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

    @router.get("/portal/payslip/{slip_id}")
    async def portal_payslip(slip_id: str, emp: dict = Depends(get_current_employee)):
        slip = await db.payslips.find_one({"id": slip_id, "employee_id": emp["id"]}, {"_id": 0})
        if not slip:
            raise HTTPException(status_code=404, detail="Slip tidak ditemukan")
        return slip

    @router.get("/portal/payslip/{slip_id}/pdf")
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

    # ---------------- THR / Annual / Bukti Potong ----------------
    @router.get("/portal/thr")
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

    @router.get("/portal/annual/{year}")
    async def portal_annual(year: int, emp: dict = Depends(get_current_employee)):
        return await _build_annual_summary(emp["id"], year)

    @router.get("/portal/bukti-potong/{year}/pdf")
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

    # ---------------- Magic Link (Forgot NIK) ----------------
    @router.post("/portal/forgot")
    async def portal_forgot(payload: ForgotPortalIn):
        """Generate one-time magic login token and email it. Always returns ok to avoid email enumeration."""
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

    @router.post("/portal/magic-login")
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
        response.set_cookie("portal_token", portal_token, httponly=True, secure=True, samesite="lax", max_age=86400, path="/")
        return {
            "id": emp["id"],
            "nik": emp["nik"],
            "name": emp["name"],
            "email": emp.get("email"),
            "position": emp["position"],
            "department": emp["department"],
        }

    # ---------------- Leave (Portal — karyawan) ----------------
    @router.post("/portal/leave")
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
            # File upload optional
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

    @router.get("/portal/leave")
    async def portal_leave_list(emp: dict = Depends(get_current_employee)):
        items = await db.leave_requests.find({"employee_id": emp["id"]}, {"_id": 0, "attachment.data_base64": 0}).sort("submitted_at", -1).to_list(length=500)
        return [_leave_view(x) for x in items]

    @router.delete("/portal/leave/{leave_id}")
    async def portal_leave_cancel(leave_id: str, emp: dict = Depends(get_current_employee)):
        doc = await db.leave_requests.find_one({"id": leave_id, "employee_id": emp["id"]})
        if not doc:
            raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")
        if doc.get("status") != "pending":
            raise HTTPException(status_code=400, detail="Pengajuan yang sudah diproses tidak dapat dibatalkan")
        await db.leave_requests.delete_one({"id": leave_id})
        return {"ok": True}

    @router.get("/portal/leave/{leave_id}/attachment")
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

    return router
