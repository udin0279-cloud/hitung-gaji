"""Backup router — Pusat Backup Data untuk super_admin.

Endpoints:
  POST /backup/download   → Export SEMUA koleksi ke ZIP berisi JSON per collection.
                            Log entry ditulis ke `backup_logs`. Return file download.
  GET  /backup/logs       → Riwayat backup (paginated, latest first).

Format ZIP:
  backup_<YYYY-MM-DDTHHMMSS>.zip
    ├── manifest.json     (metadata: timestamp, user, counts, collections)
    ├── attendance_daily.json
    ├── attendance_imports.json
    ├── payroll_runs.json
    ├── payslips.json
    ├── sales.json
    ├── users.json
    ├── products.json
    ├── cash_accounts.json
    ├── cash_transactions.json
    └── ... (semua koleksi yang ada)
"""
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from bson import ObjectId


# Koleksi yang di-highlight di manifest (sesuai request user)
FEATURED_COLLECTIONS = [
    "attendance_daily",
    "attendance_imports",
    "payroll_runs",
    "payslips",
    "sales",
    "users",
    "products",
    "cash_accounts",
    "cash_transactions",
]


def _jsonable(v: Any) -> Any:
    """Convert Mongo values (ObjectId, datetime) ke JSON-serializable primitives."""
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_jsonable(item) for item in v]
    return v


def make_router(*, db, require_super_admin, logger):
    router = APIRouter()

    async def _list_collections() -> List[str]:
        """Return semua nama koleksi user (skip Mongo system collections)."""
        names = await db.list_collection_names()
        return sorted([n for n in names if not n.startswith("system.")])

    @router.post("/backup/download")
    async def backup_download(user: dict = Depends(require_super_admin)):
        """Export semua koleksi ke ZIP berisi JSON. Log ke `backup_logs`."""
        if user.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="Hanya Super Admin yang bisa membuat backup")

        now = datetime.now(timezone.utc)
        ts_iso = now.isoformat()
        ts_file = now.strftime("%Y-%m-%dT%H%M%S")
        collections = await _list_collections()

        buf = io.BytesIO()
        total_records = 0
        collection_stats: Dict[str, int] = {}

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for col_name in collections:
                # Skip backup_logs itself supaya tidak recursive noise
                if col_name == "backup_logs":
                    continue
                try:
                    docs = await db[col_name].find({}, {"_id": 0}).to_list(length=1000000)
                    docs_json = [_jsonable(d) for d in docs]
                    payload = json.dumps(docs_json, indent=2, ensure_ascii=False)
                    zf.writestr(f"{col_name}.json", payload)
                    collection_stats[col_name] = len(docs)
                    total_records += len(docs)
                except Exception as ex:
                    logger.warning(f"Backup: gagal export koleksi {col_name}: {ex}")
                    collection_stats[col_name] = -1  # error marker

            # Manifest
            manifest = {
                "backup_version": "1.0",
                "created_at": ts_iso,
                "created_by": user.get("email"),
                "created_by_name": user.get("name"),
                "total_collections": len([k for k, v in collection_stats.items() if v >= 0]),
                "total_records": total_records,
                "collection_stats": collection_stats,
                "featured_collections": FEATURED_COLLECTIONS,
                "app": "PLAZAKREASI HR & ERP",
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

        buf.seek(0)
        blob = buf.getvalue()
        file_size = len(blob)

        # Log entry
        log_doc = {
            "id": str(uuid.uuid4()),
            "created_at": ts_iso,
            "created_by": user.get("email"),
            "created_by_name": user.get("name"),
            "total_collections": len([k for k, v in collection_stats.items() if v >= 0]),
            "total_records": total_records,
            "file_size_bytes": file_size,
            "filename": f"backup_{ts_file}.zip",
            "collection_stats": collection_stats,
        }
        try:
            await db.backup_logs.insert_one(log_doc)
        except Exception as ex:
            logger.warning(f"Backup log insert failed: {ex}")

        logger.info(
            f"BACKUP created by {user.get('email')} · "
            f"{total_records} records · {file_size} bytes · {len(collections)} collections"
        )

        filename = f"backup_{ts_file}.zip"
        return Response(
            content=blob,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Backup-Total-Records": str(total_records),
                "X-Backup-Total-Collections": str(len(collections)),
            },
        )

    @router.get("/backup/logs")
    async def backup_logs_list(
        user: dict = Depends(require_super_admin),
        limit: int = 100,
    ):
        """Riwayat backup, latest first."""
        if user.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="Hanya Super Admin yang bisa melihat riwayat backup")
        items = await db.backup_logs.find({}, {"_id": 0}).sort("created_at", -1).to_list(length=max(1, min(int(limit), 500)))
        total = await db.backup_logs.count_documents({})
        return {"items": items, "total": total, "limit": limit}

    return router
