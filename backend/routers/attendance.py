"""Attendance router — extracted from server.py (POC refactor 2026-08-01).

Endpoints:
  POST /attendance/import
  GET  /attendance/{period}
  GET  /attendance/daily/list
  GET  /attendance/range/summary

Usage in server.py:
    from routers.attendance import make_router as _make_attendance_router
    api_router.include_router(_make_attendance_router(db, require_super_admin, logger))
"""
import io
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, time as dtime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile


# ---------------- Attendance Constants ----------------
NIK_COLS = {"nik", "pin", "userid", "user_id", "employee_id", "employee", "no_pegawai", "id"}
DATE_COLS = {"tanggal", "date", "tgl"}
TIME_COLS = {"jam", "time", "clock", "waktu", "jam_scan"}
DATETIME_COLS = {"datetime", "date_time", "tanggal_jam", "timestamp", "tgl_jam"}
STATUS_COLS = {"status", "verify", "io", "in_out"}

STANDARD_START_HOUR = 8
STANDARD_END_HOUR = 17
STANDARD_DAYS_DEFAULT = 22

# Jam kerja standar (untuk kalkulasi lembur & keterlambatan)
WORK_START = dtime(8, 30)         # Semua hari (Sen-Sabtu) — batas masuk normal
WORK_END_WEEKDAY = dtime(16, 30)  # Senin-Jumat — jam kerja selesai
WORK_END_SATURDAY = dtime(14, 0)  # Sabtu — jam kerja selesai
OT_START_WEEKDAY = dtime(17, 0)   # Senin-Jumat — OT mulai dihitung dari 17:00
OT_START_SATURDAY = dtime(14, 30) # Sabtu — OT mulai dihitung dari 14:30
# Minggu: seluruh scan dihitung lembur (tanpa jeda), dari scan masuk sampai scan pulang

# Penalti keterlambatan: berlaku jika telat > 4 jam (240 menit)
LATE_PENALTY_THRESHOLD_MIN = 240


# ---------------- Helpers ----------------
def _calculate_late_minutes(date_obj, in_time) -> Dict[str, float]:
    """Kalkulasi keterlambatan per hari.
    Return: {late_minutes: total menit telat dari 08:30, penalty_minutes: 0 jika ≤ 4 jam, atau total menit jika > 4 jam}
    Minggu (libur) tidak dihitung sebagai telat.
    """
    import pandas as pd
    if in_time is None:
        return {"late_minutes": 0, "penalty_minutes": 0}
    try:
        weekday = date_obj.weekday()
    except Exception:
        return {"late_minutes": 0, "penalty_minutes": 0}
    if weekday == 6:
        return {"late_minutes": 0, "penalty_minutes": 0}
    start_dt = pd.Timestamp.combine(date_obj, WORK_START)
    diff_min = (in_time - start_dt).total_seconds() / 60.0
    if diff_min <= 0:
        return {"late_minutes": 0, "penalty_minutes": 0}
    late_min = round(diff_min, 2)
    penalty_min = late_min if late_min > LATE_PENALTY_THRESHOLD_MIN else 0
    return {"late_minutes": late_min, "penalty_minutes": round(penalty_min, 2)}


def _calculate_overtime_hours(date_obj, in_time, out_time) -> float:
    """Kalkulasi lembur per hari berdasarkan aturan:
      - Senin-Jumat: jam kerja selesai 16:30. OT dihitung jika out > 17:00.
      - Sabtu:       jam kerja selesai 14:00. OT dihitung jika out > 14:30.
      - Minggu:      hari libur. OT = seluruh durasi (out - in).
    """
    import pandas as pd
    if in_time is None or out_time is None:
        return 0.0
    try:
        weekday = date_obj.weekday()
    except Exception:
        return 0.0

    if weekday == 6:
        diff_seconds = (out_time - in_time).total_seconds()
        return round(max(0.0, diff_seconds / 3600.0), 2)

    ot_start = OT_START_SATURDAY if weekday == 5 else OT_START_WEEKDAY
    ot_start_dt = pd.Timestamp.combine(date_obj, ot_start)
    diff_minutes = (out_time - ot_start_dt).total_seconds() / 60.0
    if diff_minutes <= 0:
        return 0.0
    return round(diff_minutes / 60.0, 2)


def _normalize_col(c):
    return str(c).strip().lower().replace(" ", "_") if c is not None else ""


def _find_col(cols, candidates):
    for c in cols:
        if _normalize_col(c) in candidates:
            return c
    return None


def _parse_wide_finger_format(df_raw):
    """Parse "wide" fingerprint export (satu baris = satu PIN-tanggal, banyak kolom Scan).
    Return: list of dicts {pin, nama, dt, date} atau None jika bukan format wide.
    """
    import pandas as pd
    from datetime import time as dtime_cls
    if df_raw is None or len(df_raw) == 0:
        return None

    ncols = df_raw.shape[1]

    pin_col_idx: Optional[int] = None
    nama_col_idx: Optional[int] = None
    date_col_idx: Optional[int] = None
    scan_col_indices: List[int] = []
    data_start_row: int = 0

    header_row_idx: Optional[int] = None
    for i in range(min(6, len(df_raw))):
        cells = [str(v).strip().lower() if pd.notna(v) else "" for v in df_raw.iloc[i].values]
        if "pin" in cells and ("nama" in cells or "name" in cells) and ("tanggal" in cells or "date" in cells or "tgl" in cells):
            header_row_idx = i
            break

    if header_row_idx is not None:
        for idx, v in enumerate(df_raw.iloc[header_row_idx].values):
            lc = str(v).strip().lower() if pd.notna(v) else ""
            if lc == "pin":
                pin_col_idx = idx
            elif lc in ("nama", "name"):
                nama_col_idx = idx
            elif lc in ("tanggal", "date", "tgl"):
                date_col_idx = idx
            elif lc.startswith("scan"):
                scan_col_indices.append(idx)
        data_start_row = header_row_idx + 1
    else:
        row0_cells = [str(v).strip().lower() if pd.notna(v) else "" for v in df_raw.iloc[0].values]
        row0_joined = " ".join(c for c in row0_cells if c)
        if "pegawai" in row0_joined and "scanlog" in row0_joined:
            pin_col_idx = 0
            nama_col_idx = 1
            date_col_idx = 5 if ncols >= 6 else None
            scan_col_indices = list(range(6, min(ncols, 10)))
            data_start_row = 1
        else:
            return None

    if pin_col_idx is None or date_col_idx is None or not scan_col_indices:
        return None

    records: List[Dict[str, Any]] = []
    for i in range(data_start_row, len(df_raw)):
        row = df_raw.iloc[i].values
        pin_raw = row[pin_col_idx] if pin_col_idx < len(row) else None
        if pin_raw is None or (isinstance(pin_raw, float) and pd.isna(pin_raw)):
            continue
        pin = str(pin_raw).strip()
        if not pin or pin.lower() in ("nan", "none", "pegawai"):
            continue
        try:
            f = float(pin)
            if f.is_integer():
                pin = str(int(f))
        except (ValueError, TypeError):
            pass

        nama = ""
        if nama_col_idx is not None and nama_col_idx < len(row):
            v = row[nama_col_idx]
            if pd.notna(v):
                nama = str(v).strip()

        date_raw = row[date_col_idx] if date_col_idx < len(row) else None
        if date_raw is None or (isinstance(date_raw, float) and pd.isna(date_raw)):
            continue
        date_str = str(date_raw).strip()
        try:
            d_ts = pd.to_datetime(date_str, dayfirst=True, errors="coerce")
            if pd.isna(d_ts):
                d_ts = pd.to_datetime(date_str, errors="coerce")
            if pd.isna(d_ts):
                continue
            date_only = d_ts.date()
        except Exception:
            continue

        for sc_idx in scan_col_indices:
            if sc_idx >= len(row):
                continue
            sv = row[sc_idx]
            if sv is None or (isinstance(sv, float) and pd.isna(sv)):
                continue
            sv_str = str(sv).strip()
            if not sv_str or sv_str.lower() in ("nan", "nat", "none"):
                continue
            t_ts = None
            if isinstance(sv, (int, float)) and not (isinstance(sv, float) and pd.isna(sv)):
                try:
                    f = float(sv)
                    if 0 <= f < 1:
                        secs = int(round(f * 86400))
                        h = min(23, secs // 3600); mm = (secs % 3600) // 60; s = secs % 60
                        t_ts = dtime_cls(hour=h, minute=mm, second=s)
                    elif 1 <= f < 100000:
                        frac = f - int(f)
                        secs = int(round(frac * 86400))
                        h = min(23, secs // 3600); mm = (secs % 3600) // 60; s = secs % 60
                        t_ts = dtime_cls(hour=h, minute=mm, second=s)
                except (ValueError, TypeError):
                    pass
            if t_ts is None:
                for fmt in ("%H:%M:%S", "%H:%M"):
                    try:
                        t_ts = datetime.strptime(sv_str, fmt).time()
                        break
                    except ValueError:
                        continue
            if t_ts is None and sv_str:
                try:
                    f = float(sv_str)
                    if 0 <= f < 1:
                        secs = int(round(f * 86400))
                        h = min(23, secs // 3600); mm = (secs % 3600) // 60; s = secs % 60
                        t_ts = dtime_cls(hour=h, minute=mm, second=s)
                except (ValueError, TypeError):
                    pass
            if t_ts is None:
                try:
                    parsed = pd.to_datetime(sv_str, errors="coerce")
                    if pd.notna(parsed):
                        t_ts = parsed.time()
                except Exception:
                    pass
            if t_ts is None:
                continue
            dt = datetime.combine(date_only, t_ts)
            records.append({"pin": pin, "nama": nama, "dt": dt, "date": date_only})

    return records if records else None


# ---------------- Router Factory ----------------
def make_router(db, require_super_admin, logger):
    """Build the attendance sub-router using injected dependencies (avoids circular imports)."""
    import pandas as pd

    router = APIRouter()

    @router.post("/attendance/import")
    async def attendance_import(
        period: str,
        file: UploadFile = File(...),
        user: dict = Depends(require_super_admin),
    ):
        """Import fingerprint export (xlsx/xls/csv).
        Aggregate per (NIK, tanggal). "Hari Hadir" hanya dihitung bila ada scan IN dan OUT di hari sama.
        """
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

        # --- WIDE FORMAT ---
        wide_records = None
        try:
            if fname.endswith(".xlsx"):
                df_raw = pd.read_excel(io.BytesIO(raw), engine="openpyxl", header=None)
            elif fname.endswith(".xls"):
                df_raw = pd.read_excel(io.BytesIO(raw), engine="xlrd", header=None)
            elif fname.endswith(".csv"):
                try:
                    df_raw = pd.read_csv(io.BytesIO(raw), header=None)
                except Exception:
                    df_raw = pd.read_csv(io.BytesIO(raw), encoding="latin-1", header=None)
            else:
                df_raw = None
            if df_raw is not None:
                wide_records = _parse_wide_finger_format(df_raw)
        except Exception as ex:
            logger.warning(f"Wide finger parse skipped: {ex}")

        if wide_records:
            df = pd.DataFrame([
                {"_pin": r["pin"], "_nama": r["nama"], "_dt": r["dt"], "_date": r["date"]}
                for r in wide_records
            ])
            nik_col = "_pin"
            dt_col = "_dt"
            date_col = None
            time_col = None
            _is_wide = True
        else:
            _is_wide = False
            cols = list(df.columns)
            nik_col = _find_col(cols, NIK_COLS)
            dt_col = _find_col(cols, DATETIME_COLS)
            date_col = _find_col(cols, DATE_COLS)
            time_col = _find_col(cols, TIME_COLS)

            if not nik_col:
                raise HTTPException(status_code=400, detail=f"Kolom NIK/PIN tidak ditemukan. Kolom file: {cols}")
            if not dt_col and not (date_col and time_col) and not date_col:
                raise HTTPException(status_code=400, detail="Kolom tanggal/jam tidak ditemukan")

        def _try_parse(series, with_dayfirst):
            return pd.to_datetime(series, errors="coerce", dayfirst=with_dayfirst)

        def _best_parse(series):
            a = _try_parse(series, False)
            if a.isna().mean() < 0.3:
                return a
            b = _try_parse(series, True)
            return b if b.isna().mean() < a.isna().mean() else a

        if _is_wide:
            df["_nik"] = df[nik_col].astype(str).str.strip()
        else:
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
            df["_date"] = df["_dt"].dt.date
        df = df[df["_nik"] != ""]

        # Aggregate per (nik, date) -> earliest=IN, latest=OUT
        agg = df.groupby(["_nik", "_date"]).agg(in_time=("_dt", "min"), out_time=("_dt", "max"), scan_count=("_dt", "count")).reset_index()
        # has_pair = ada minimal 2 scan berbeda di hari sama (scan masuk & scan pulang)
        agg["has_pair"] = (agg["scan_count"] >= 2) & (agg["in_time"] != agg["out_time"])

        try:
            period_year, period_month = period.split("-")
            py, pm = int(period_year), int(period_month)
        except Exception:
            raise HTTPException(status_code=400, detail="Periode harus format YYYY-MM")

        employees = await db.employees.find({}, {"_id": 0}).to_list(length=5000)
        emp_by_nik = {e["nik"]: e for e in employees}
        emp_by_name_lc: Dict[str, Dict[str, Any]] = {}
        for e in employees:
            nm = (e.get("name") or "").strip().lower()
            if nm:
                emp_by_name_lc[nm] = e
        pin_to_name: Dict[str, str] = {}
        if _is_wide and "_nama" in df.columns:
            for pin_v, nama_v in df[["_nik", "_nama"]].dropna().itertuples(index=False):
                k = str(pin_v).strip()
                if k and k not in pin_to_name:
                    nm = str(nama_v).strip()
                    if nm:
                        pin_to_name[k] = nm

        now_iso = datetime.now(timezone.utc).isoformat()

        # ---- Pre-clear existing daily records ----
        # Untuk semua bulan yang tersentuh oleh file ini, hapus attendance_daily terlebih dulu
        # agar tidak menumpuk dgn data lama. Grouping (nik+date) di logic bawah menjamin
        # scan berulang di hari sama tetap terhitung 1 hari hadir.
        months_in_file = sorted({(d.year, d.month) for d in agg["_date"]})
        deleted_daily_count = 0
        for (yy, mm) in months_in_file:
            from calendar import monthrange
            first = f"{yy:04d}-{mm:02d}-01"
            last_day = monthrange(yy, mm)[1]
            last = f"{yy:04d}-{mm:02d}-{last_day:02d}"
            res = await db.attendance_daily.delete_many({"date": {"$gte": first, "$lte": last}})
            deleted_daily_count += res.deleted_count
        # Juga hapus attendance_imports untuk periode ini agar summary bersih
        # (akan di-replace by upsert di bawah, tapi eksplisit lebih aman)
        await db.attendance_imports.delete_many({"period": period})
        logger.info(f"Attendance import: pre-cleared {deleted_daily_count} daily records for months {months_in_file}")

        # 1) Persist per-day records
        daily_ops: List[Any] = []
        date_range: List[Any] = []
        for _, r in agg.iterrows():
            nik_str = str(r["_nik"])
            d_ = r["_date"]
            in_t = r["in_time"]
            out_t = r["out_time"]
            overtime_h_day = _calculate_overtime_hours(d_, in_t, out_t)
            late_info = _calculate_late_minutes(d_, in_t)
            try:
                _WD = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
                weekday_name = _WD[d_.weekday()]
            except Exception:
                weekday_name = None
            emp_ = emp_by_nik.get(nik_str)
            if not emp_ and nik_str in pin_to_name:
                emp_ = emp_by_name_lc.get(pin_to_name[nik_str].lower())
            emp_id = emp_.get("id") if emp_ else None
            emp_name = emp_.get("name") if emp_ else pin_to_name.get(nik_str, "")
            emp_nik = emp_.get("nik") if emp_ else None
            date_iso = d_.isoformat() if hasattr(d_, "isoformat") else str(d_)
            doc_ = {
                "pin": nik_str,
                "date": date_iso,
                "weekday": weekday_name,
                "in_time": in_t.strftime("%H:%M:%S") if pd.notna(in_t) else None,
                "out_time": out_t.strftime("%H:%M:%S") if pd.notna(out_t) else None,
                "scan_count": int(r.get("scan_count") or 0),
                "has_pair": bool(r.get("has_pair") or False),
                "overtime_hours": overtime_h_day if bool(r.get("has_pair") or False) else 0,
                "late_minutes": late_info["late_minutes"] if bool(r.get("has_pair") or False) else 0,
                "late_penalty_minutes": late_info["penalty_minutes"] if bool(r.get("has_pair") or False) else 0,
                "employee_id": emp_id,
                "employee_nik": emp_nik,
                "employee_name": emp_name,
                "source_file": file.filename,
                "imported_at": now_iso,
                "imported_by": user.get("email"),
            }
            daily_ops.append({"filter": {"pin": nik_str, "date": date_iso}, "doc": doc_})
            date_range.append(d_)

        for op in daily_ops:
            await db.attendance_daily.update_one(op["filter"], {"$set": op["doc"]}, upsert=True)

        # 2) Summary untuk period yg dipilih
        period_mask = agg["_date"].apply(lambda d: d.year == py and d.month == pm)
        agg_period = agg[period_mask]
        summary: Dict[str, Dict[str, float]] = {}
        unmatched_details: List[Dict[str, Any]] = []
        total_scans = int(len(df))

        for nik, group in agg_period.groupby("_nik"):
            # HARI HADIR = hanya hari yg punya scan masuk DAN scan pulang (has_pair=True)
            valid_days = group[group["has_pair"] == True]  # noqa: E712
            days_worked = int(len(valid_days))
            overtime_hours_total = 0.0
            late_penalty_min_total = 0.0
            for _, r in valid_days.iterrows():
                overtime_hours_total += _calculate_overtime_hours(r["_date"], r["in_time"], r["out_time"])
                _lm = _calculate_late_minutes(r["_date"], r["in_time"])
                late_penalty_min_total += _lm["penalty_minutes"]
            overtime_hours = round(overtime_hours_total, 2)
            late_penalty_minutes = round(late_penalty_min_total, 2)

            nik_str = str(nik)
            emp = emp_by_nik.get(nik_str)
            if not emp and nik_str in pin_to_name:
                emp = emp_by_name_lc.get(pin_to_name[nik_str].lower())
            if not emp:
                unmatched_details.append({
                    "pin": nik_str,
                    "name": pin_to_name.get(nik_str, ""),
                    "days_worked": days_worked,
                    "overtime_hours": overtime_hours,
                    "late_penalty_minutes": late_penalty_minutes,
                })
                continue

            summary[emp["id"]] = {
                "nik": emp.get("nik") or nik_str,
                "pin": nik_str,
                "name": emp["name"],
                "days_worked": days_worked,
                "overtime_hours": overtime_hours,
                "late_penalty_minutes": late_penalty_minutes,
                "bonus": 0,
                "deduction": 0,
            }

        unmatched_nik = sorted([u["pin"] for u in unmatched_details])
        unmatched_details.sort(key=lambda u: (u["pin"]))

        if date_range:
            min_date = min(date_range).isoformat() if hasattr(min(date_range), "isoformat") else str(min(date_range))
            max_date = max(date_range).isoformat() if hasattr(max(date_range), "isoformat") else str(max(date_range))
        else:
            min_date = max_date = None
        months_covered = sorted({(d.year, d.month) for d in date_range})
        months_covered_str = [f"{y:04d}-{m:02d}" for (y, m) in months_covered]

        record = {
            "period": period,
            "uploaded_at": now_iso,
            "filename": file.filename,
            "summary": summary,
            "total_scans": total_scans,
            "matched_employees": len(summary),
            "unmatched_niks": unmatched_nik,
            "unmatched_details": unmatched_details,
            "date_range": {"from": min_date, "to": max_date},
            "months_covered": months_covered_str,
            "total_days_persisted": len(daily_ops),
        }
        await db.attendance_imports.replace_one({"period": period}, record, upsert=True)

        return {
            "period": period,
            "total_scans": total_scans,
            "matched_employees": len(summary),
            "unmatched_niks": unmatched_nik,
            "unmatched_details": unmatched_details,
            "summary": summary,
            "date_range": {"from": min_date, "to": max_date},
            "months_covered": months_covered_str,
            "total_days_persisted": len(daily_ops),
            "pre_cleared_daily_records": deleted_daily_count,
        }

    @router.get("/attendance/{period}")
    async def get_attendance(period: str, user: dict = Depends(require_super_admin)):
        rec = await db.attendance_imports.find_one({"period": period}, {"_id": 0})
        if not rec:
            return {"period": period, "summary": {}, "matched_employees": 0, "total_scans": 0, "unmatched_niks": []}
        return rec

    @router.get("/attendance/daily/list")
    async def attendance_daily_list(
        user: dict = Depends(require_super_admin),
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        pin: Optional[str] = None,
        employee_id: Optional[str] = None,
    ):
        """Daftar record absensi harian dgn filter fleksibel (cross-month/year OK)."""
        q: Dict[str, Any] = {}
        if date_from or date_to:
            q["date"] = {}
            if date_from:
                q["date"]["$gte"] = date_from
            if date_to:
                q["date"]["$lte"] = date_to
        if pin:
            q["pin"] = str(pin).strip()
        if employee_id:
            q["employee_id"] = employee_id
        items = await db.attendance_daily.find(q, {"_id": 0}).sort([("date", 1), ("pin", 1)]).to_list(length=20000)
        total_overtime = round(sum(float(i.get("overtime_hours") or 0) for i in items), 2)
        unique_dates = sorted({i.get("date") for i in items if i.get("date")})
        unique_pins = sorted({i.get("pin") for i in items if i.get("pin")})
        return {
            "items": items,
            "count": len(items),
            "total_overtime_hours": total_overtime,
            "unique_dates": len(unique_dates),
            "unique_pins": len(unique_pins),
            "date_from": date_from,
            "date_to": date_to,
        }

    @router.get("/attendance/range/summary")
    async def attendance_range_summary(
        user: dict = Depends(require_super_admin),
        date_from: str = "",
        date_to: str = "",
    ):
        """Ringkasan per-karyawan untuk rentang tanggal (bisa cross-month)."""
        if not date_from or not date_to:
            raise HTTPException(status_code=400, detail="date_from dan date_to wajib (format YYYY-MM-DD)")
        try:
            datetime.strptime(date_from, "%Y-%m-%d")
            datetime.strptime(date_to, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Format tanggal harus YYYY-MM-DD")
        if date_to < date_from:
            raise HTTPException(status_code=400, detail="date_to harus >= date_from")

        items = await db.attendance_daily.find(
            {"date": {"$gte": date_from, "$lte": date_to}},
            {"_id": 0},
        ).to_list(length=50000)

        summary: Dict[str, Dict[str, Any]] = {}
        unmatched_by_pin: Dict[str, Dict[str, Any]] = {}
        for it in items:
            emp_id = it.get("employee_id")
            pin = it.get("pin")
            ot = float(it.get("overtime_hours") or 0)
            lpm = float(it.get("late_penalty_minutes") or 0)
            if emp_id:
                entry = summary.setdefault(emp_id, {
                    "employee_id": emp_id,
                    "nik": it.get("employee_nik"),
                    "pin": pin,
                    "name": it.get("employee_name"),
                    "days_worked": 0,
                    "overtime_hours": 0.0,
                    "late_penalty_minutes": 0.0,
                    "bonus": 0,
                    "deduction": 0,
                })
                entry["days_worked"] += 1
                entry["overtime_hours"] = round(entry["overtime_hours"] + ot, 2)
                entry["late_penalty_minutes"] = round(entry["late_penalty_minutes"] + lpm, 2)
            else:
                key = pin or "-"
                entry = unmatched_by_pin.setdefault(key, {
                    "pin": key,
                    "name": it.get("employee_name") or "",
                    "days_worked": 0,
                    "overtime_hours": 0.0,
                    "late_penalty_minutes": 0.0,
                })
                entry["days_worked"] += 1
                entry["overtime_hours"] = round(entry["overtime_hours"] + ot, 2)
                entry["late_penalty_minutes"] = round(entry["late_penalty_minutes"] + lpm, 2)

        return {
            "date_from": date_from,
            "date_to": date_to,
            "summary": summary,
            "matched_employees": len(summary),
            "unmatched_details": sorted(unmatched_by_pin.values(), key=lambda x: x["pin"]),
            "total_days": len(items),
        }

    return router
