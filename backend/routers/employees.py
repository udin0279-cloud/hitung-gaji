"""Employees router — Admin Karyawan CRUD + CSV template + import.

Extracted from `server.py` (2026-08-04).

Endpoints:
  GET    /employees
  POST   /employees
  GET    /employees/{employee_id}
  PUT    /employees/{employee_id}
  DELETE /employees/{employee_id}
  GET    /employees-template.csv
  POST   /employees-import

`EmployeeIn` Pydantic model + `EMPLOYEE_CSV_HEADERS` list diinjeksikan lewat factory
supaya schema tetap tunggal (didefinisikan di server.py).
"""
import csv
import io
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse


def _parse_bool(v: str, default: bool = True) -> bool:
    if v is None or v == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "ya", "y")


def make_router(
    *,
    db,
    require_super_admin,
    logger,
    EmployeeIn,
    EMPLOYEE_CSV_HEADERS,
):
    router = APIRouter()

    @router.get("/employees")
    async def list_employees(user: dict = Depends(require_super_admin)):
        cursor = db.employees.find({}, {"_id": 0}).sort("created_at", -1)
        items = await cursor.to_list(length=2000)
        return items

    @router.post("/employees")
    async def create_employee(payload: EmployeeIn, user: dict = Depends(require_super_admin)):
        if await db.employees.find_one({"nik": payload.nik}):
            raise HTTPException(status_code=400, detail="NIK sudah terdaftar")
        doc = payload.model_dump()
        doc["id"] = str(uuid.uuid4())
        doc["created_at"] = datetime.now(timezone.utc).isoformat()
        await db.employees.insert_one(doc)
        doc.pop("_id", None)
        return doc

    @router.get("/employees/{employee_id}")
    async def get_employee(employee_id: str, user: dict = Depends(require_super_admin)):
        emp = await db.employees.find_one({"id": employee_id}, {"_id": 0})
        if not emp:
            raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")
        return emp

    @router.put("/employees/{employee_id}")
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

    @router.delete("/employees/{employee_id}")
    async def delete_employee(employee_id: str, user: dict = Depends(require_super_admin)):
        res = await db.employees.delete_one({"id": employee_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")
        return {"ok": True}

    @router.get("/employees-template.csv")
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

    @router.post("/employees-import")
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

    return router
