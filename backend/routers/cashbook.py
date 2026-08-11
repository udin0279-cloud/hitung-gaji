"""Cashbook router — extracted from server.py (POC refactor 2026-08-01, part 2).

Endpoints:
  GET/POST/PUT/DELETE /cashbook/accounts
  GET/PUT             /cashbook/settings
  GET/POST/PUT/DELETE /cashbook/transactions
  GET                 /cashbook/transactions/{tx_id}/orphan-check
  GET                 /cashbook/balance
  GET                 /cashbook/summary
  GET                 /cashbook/export
  POST                /cashbook/resync-sales
  POST                /cashbook/resync-purchases
  GET/POST/PUT/DELETE /cashbook/kasbon
  PUT                 /cashbook/kasbon/{id}/settle
  PUT                 /cashbook/kasbon/{id}/reopen

Usage in server.py:
    from routers.cashbook import make_router as _make_cashbook_router
    api_router.include_router(_make_cashbook_router(
        db=db,
        require_super_admin=require_super_admin,
        logger=logger,
        _insert_cash_transaction=_insert_cash_transaction,
        _ensure_cash_accounts=_ensure_cash_accounts,
        _resolve_payment_account=_resolve_payment_account,
        PAYMENT_ACCOUNT_MAP=PAYMENT_ACCOUNT_MAP,
        _company_info=_company_info,
    ))
"""
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel


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
    reference: Optional[str] = None


class CashSettingIn(BaseModel):
    opening_balance: float
    opening_date: Optional[str] = None


class MonthlyOpeningIn(BaseModel):
    opening_balance: float


class KasbonIn(BaseModel):
    date: str  # YYYY-MM-DD
    name: str
    description: Optional[str] = ""
    amount: float


def make_router(
    *,
    db,
    require_super_admin,
    logger,
    _insert_cash_transaction,
    _ensure_cash_accounts,
    _resolve_payment_account,
    PAYMENT_ACCOUNT_MAP,
    _company_info,
):
    """Build the cashbook sub-router using injected dependencies."""
    router = APIRouter()

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

    async def _get_month_opening_override(month: Optional[str]) -> Optional[float]:
        """Cek apakah user telah mengunci Saldo Awal untuk bulan ini.
        Return angka override jika ada, None jika tidak.
        """
        if not month:
            return None
        doc = await db.monthly_openings.find_one({"month": month}, {"_id": 0, "opening_balance": 1})
        if doc and "opening_balance" in doc:
            return float(doc["opening_balance"])
        return None

    # ---------- Endpoints ----------
    @router.get("/cashbook/monthly-openings")
    async def list_monthly_openings(user: dict = Depends(require_super_admin)):
        """Daftar semua Saldo Awal yang dikunci per bulan."""
        items = await db.monthly_openings.find({}, {"_id": 0}).sort("month", -1).to_list(length=500)
        return {"items": items}

    @router.put("/cashbook/monthly-openings/{month}")
    async def set_monthly_opening(
        month: str,
        payload: MonthlyOpeningIn,
        user: dict = Depends(require_super_admin),
    ):
        """Kunci Saldo Awal untuk bulan tertentu (YYYY-MM). Idempotent (upsert)."""
        try:
            y, m = month.split("-")
            int(y); int(m)
        except Exception:
            raise HTTPException(status_code=400, detail="Format bulan harus YYYY-MM")
        doc = {
            "month": month,
            "opening_balance": round(float(payload.opening_balance), 2),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": user.get("email"),
        }
        await db.monthly_openings.update_one({"month": month}, {"$set": doc}, upsert=True)
        return {"ok": True, "month": month, "opening_balance": doc["opening_balance"]}

    @router.delete("/cashbook/monthly-openings/{month}")
    async def delete_monthly_opening(month: str, user: dict = Depends(require_super_admin)):
        """Hapus kunci Saldo Awal — sistem kembali menghitung otomatis dari data."""
        result = await db.monthly_openings.delete_one({"month": month})
        return {"ok": True, "deleted": result.deleted_count}

    @router.get("/cashbook/accounts")
    async def cash_accounts_list(user: dict = Depends(require_super_admin)):
        await _ensure_cash_accounts()
        items = await db.cash_accounts.find({}, {"_id": 0}).sort("code", 1).to_list(length=500)
        return items


    @router.post("/cashbook/accounts")
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


    @router.put("/cashbook/accounts/{account_id}")
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


    @router.delete("/cashbook/accounts/{account_id}")
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


    @router.get("/cashbook/settings")
    async def cash_settings_get(user: dict = Depends(require_super_admin)):
        return await _cash_setting()


    @router.put("/cashbook/settings")
    async def cash_settings_update(payload: CashSettingIn, user: dict = Depends(require_super_admin)):
        upd = {"opening_balance": round(float(payload.opening_balance), 2)}
        if payload.opening_date:
            upd["opening_date"] = payload.opening_date
        upd["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.cash_settings.update_one({"key": "main"}, {"$set": upd}, upsert=True)
        return await _cash_setting()


    @router.get("/cashbook/transactions")
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
        # Compute running balance — matematika murni (2026-08-08):
        # SEMUA type=in menambah saldo, SEMUA type=out mengurangi — apapun akunnya.
        # Konsisten dgn tab Jurnal Akuntansi di frontend.
        setting = await _cash_setting()
        opening_balance = float(setting.get("opening_balance", 0))
        opening_date = setting.get("opening_date")

        def _kas_delta(t):
            if t["type"] == "in":
                return float(t["amount"])
            elif t["type"] == "out":
                return -float(t["amount"])
            return 0.0

        # Kalau filter bulan, hitung saldo awal bulan dari transaksi sebelumnya + opening
        if month:
            first_of_month = q["date"]["$gte"]
            last_of_month = q["date"]["$lte"]
            # Cek override Saldo Awal per bulan
            override = await _get_month_opening_override(month)
            if override is not None:
                opening_of_period = round(override, 2)
                balance = override
            else:
                prev = await db.cash_transactions.find(
                    {"date": {"$lt": first_of_month}}, {"_id": 0, "type": 1, "amount": 1, "account_code": 1},
                ).to_list(length=100000)
                # Include opening_balance selama opening_date jatuh <= akhir periode
                if opening_date and opening_date > last_of_month:
                    balance = 0.0
                else:
                    balance = opening_balance
                for p in prev:
                    balance += _kas_delta(p)
                opening_of_period = round(balance, 2)
        else:
            opening_of_period = opening_balance
            balance = opening_balance
        running = []
        for it in items:
            balance += _kas_delta(it)
            it2 = dict(it)
            it2["balance"] = round(balance, 2)
            running.append(it2)
        return {
            "opening_balance": round(opening_of_period, 2),
            "transactions": running,
            "closing_balance": round(balance, 2),
        }


    @router.post("/cashbook/transactions")
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


    @router.put("/cashbook/transactions/{tx_id}")
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


    @router.delete("/cashbook/transactions/{tx_id}")
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


    @router.get("/cashbook/transactions/{tx_id}/orphan-check")
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


    @router.get("/cashbook/balance")
    async def cash_balance(user: dict = Depends(require_super_admin)):
        setting = await _cash_setting()
        txs = await db.cash_transactions.find({}, {"_id": 0, "type": 1, "amount": 1, "account_code": 1}).to_list(length=200000)
        # Matematika murni (2026-08-08): SEMUA type=in menambah, SEMUA type=out mengurangi.
        # Cash sales, transfer BCA/Mandiri, Shopee — semua berkontribusi ke saldo Kas.
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


    @router.get("/cashbook/diagnose")
    async def cash_diagnose(
        user: dict = Depends(require_super_admin),
        month: Optional[str] = None,  # YYYY-MM — jika diisi, filter transaksi ke bulan itu saja
    ):
        """Diagnostik saldo kas dengan breakdown per akun.

        Bantu user verifikasi angka: Saldo Awal + Total Kredit − Total Debet = Saldo.
        Menunjukkan detail semua transaksi in/out per akun untuk deteksi anomali.

        Jika `month` diisi (YYYY-MM):
          - Opening = saldo awal bulan itu (= opening_balance + net txns sebelum bulan)
          - Kredit/Debet = HANYA transaksi di bulan itu
          - Saldo = Saldo Akhir bulan itu
        Jika `month` kosong: mode all-time (default), Opening = raw dari settings.
        """
        setting = await _cash_setting()
        opening_raw = float(setting.get("opening_balance", 0))
        opening_date = setting.get("opening_date")

        # ------ Build query berdasarkan mode (bulanan / all-time) ------
        q: Dict[str, Any] = {}
        opening_period = opening_raw
        period_label = "all-time"
        if month:
            try:
                year, m = month.split("-")
                from calendar import monthrange
                first = f"{year}-{int(m):02d}-01"
                last_day = monthrange(int(year), int(m))[1]
                last = f"{year}-{int(m):02d}-{last_day:02d}"
            except Exception:
                raise HTTPException(status_code=400, detail="Format month harus YYYY-MM")
            q["date"] = {"$gte": first, "$lte": last}
            period_label = month

            # Opening balance per bulan = opening_raw + net semua tx SEBELUM bulan itu
            # 2026-08-08: matematika murni — SEMUA in menambah, SEMUA out mengurangi.
            prev = await db.cash_transactions.find(
                {"date": {"$lt": first}}, {"_id": 0, "type": 1, "amount": 1, "account_code": 1},
            ).to_list(length=200000)
            prev_net = 0.0
            for p in prev:
                if p["type"] == "in":
                    prev_net += float(p["amount"])
                elif p["type"] == "out":
                    prev_net -= float(p["amount"])
            if opening_date and opening_date > last:
                opening_period = 0.0
            else:
                opening_period = opening_raw
            opening_period += prev_net

        txs = await db.cash_transactions.find(
            q, {"_id": 0, "type": 1, "amount": 1, "account_code": 1, "account_name": 1, "date": 1, "description": 1, "reference": 1},
        ).to_list(length=200000)

        # Breakdown per akun (in dan out)
        in_by_account = {}
        out_by_account = {}
        ignored_in = []  # type=in tapi bukan akun 101 → TIDAK menambah saldo kas
        # SEDERHANA totals — semua type=in dan type=out tanpa filter akun
        simple_total_in = 0.0
        simple_total_out = 0.0
        for t in txs:
            code = t.get("account_code") or "?"
            name = t.get("account_name") or ""
            amt = float(t.get("amount", 0))
            key = f"{code} · {name}"
            if t["type"] == "in":
                simple_total_in += amt
                if code == "101":
                    in_by_account[key] = in_by_account.get(key, {"code": code, "name": name, "count": 0, "total": 0.0})
                    in_by_account[key]["count"] += 1
                    in_by_account[key]["total"] += amt
                else:
                    # Type=in but not 101 — these are revenue accounts (301, 302, dll) yg TIDAK menambah kas fisik
                    ignored_in.append({"code": code, "name": name, "amount": amt, "date": t.get("date"), "desc": t.get("description")})
            elif t["type"] == "out":
                simple_total_out += amt
                out_by_account[key] = out_by_account.get(key, {"code": code, "name": name, "count": 0, "total": 0.0})
                out_by_account[key]["count"] += 1
                out_by_account[key]["total"] += amt

        total_in_kas = sum(v["total"] for v in in_by_account.values())
        total_out = sum(v["total"] for v in out_by_account.values())
        total_ignored = sum(x["amount"] for x in ignored_in)
        balance = opening_period + total_in_kas - total_out
        # SEDERHANA balance = Opening + semua type=in − semua type=out (tanpa filter akun)
        simple_balance = opening_period + simple_total_in - simple_total_out

        # Adjustment transactions detection
        adj_count = sum(1 for t in txs if t.get("reference") == "ADJUSTMENT")

        return {
            "period": period_label,
            "opening_balance": round(opening_period, 2),
            "opening_balance_raw_setting": round(opening_raw, 2),
            "opening_date": opening_date,
            "total_in_kas_101": round(total_in_kas, 2),
            "total_out_all_accounts": round(total_out, 2),
            "formula": f"Saldo{' Akhir ' + month if month else ' Real-time'} = {opening_period:,.0f} + {total_in_kas:,.0f} − {total_out:,.0f}",
            "balance_calculated": round(balance, 2),
            # SEDERHANA — Opening + SEMUA type=in − SEMUA type=out (tanpa filter akun)
            "simple": {
                "total_in_all": round(simple_total_in, 2),
                "total_out_all": round(simple_total_out, 2),
                "balance": round(simple_balance, 2),
                "formula": f"Saldo Sederhana = {opening_period:,.0f} + {simple_total_in:,.0f} − {simple_total_out:,.0f}",
            },
            "tx_count_total": len(txs),
            "tx_count_kredit_101": sum(v["count"] for v in in_by_account.values()),
            "tx_count_debet_all": sum(v["count"] for v in out_by_account.values()),
            "in_by_account": sorted(list(in_by_account.values()), key=lambda x: -x["total"]),
            "out_by_account": sorted(list(out_by_account.values()), key=lambda x: -x["total"]),
            "ignored_in_non_101": {
                "count": len(ignored_in),
                "total_amount": round(total_ignored, 2),
                "note": "Transaksi type=in dari akun ≠ 101 (misal 301-* Penjualan) TIDAK menambah Saldo Kas fisik. Ini sesuai konvensi Buku Kas — hanya uang yg benar-benar masuk kas tunai/rekening menambah saldo.",
                "sample": ignored_in[:10],
            },
            "adjustment_count": adj_count,
            "notes": [
                f"Mode: {'BULAN ' + month if month else 'ALL-TIME (total sejak awal)'}",
                "Formula: Saldo = Opening (bulan) + Σ(type=in & account=101) − Σ(type=out semua akun)",
                "Jika saldo tidak sesuai ekspektasi: (1) Cek Opening Balance, (2) Cek transaksi 'ignored_in' — mungkin ada penjualan yg belum masuk kas, (3) Cek 'adjustment_count' — hapus via tombol Hapus Semua Penyesuaian jika perlu.",
            ],
        }


    @router.get("/cashbook/find-duplicate-tx")
    async def cash_find_duplicate_tx(
        user: dict = Depends(require_super_admin),
        month: Optional[str] = None,
    ):
        """Cari transaksi yang terduplikasi berdasarkan (date + account_code + type + amount + description).

        Berguna untuk deteksi entri ganda akibat sync error atau input berulang.
        Jika `month` diisi (YYYY-MM), filter ke bulan itu saja.
        """
        q = {}
        if month:
            try:
                year, m = month.split("-")
                from calendar import monthrange
                first = f"{year}-{int(m):02d}-01"
                last_day = monthrange(int(year), int(m))[1]
                last = f"{year}-{int(m):02d}-{last_day:02d}"
                q["date"] = {"$gte": first, "$lte": last}
            except Exception:
                raise HTTPException(status_code=400, detail="Format month harus YYYY-MM")

        txs = await db.cash_transactions.find(q, {"_id": 0}).to_list(length=200000)
        # Kelompokkan berdasarkan signature
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for t in txs:
            sig = f"{t.get('date')}|{t.get('account_code')}|{t.get('type')}|{t.get('amount')}|{(t.get('description') or '').strip().lower()}"
            groups.setdefault(sig, []).append(t)

        # Ambil group yg lebih dari 1
        duplicates = []
        for sig, items in groups.items():
            if len(items) > 1:
                duplicates.append({
                    "signature": sig,
                    "count": len(items),
                    "amount": items[0].get("amount"),
                    "date": items[0].get("date"),
                    "account_code": items[0].get("account_code"),
                    "account_name": items[0].get("account_name"),
                    "type": items[0].get("type"),
                    "description": items[0].get("description"),
                    "items": [{"id": x.get("id"), "reference": x.get("reference"), "created_at": x.get("created_at")} for x in items],
                })
        duplicates.sort(key=lambda x: (x["date"] or "", -x["count"]))
        return {
            "period": month or "all-time",
            "duplicate_groups": len(duplicates),
            "total_extra_txs": sum(d["count"] - 1 for d in duplicates),
            "duplicates": duplicates,
        }


    @router.post("/cashbook/purge-duplicate-cashbook-settings")
    async def purge_duplicate_settings(user: dict = Depends(require_super_admin)):
        """Hapus dokumen cash_settings ganda — sisakan hanya satu dengan `key='main'`.

        Merge value: yang tertinggi opening_balance dipertahankan; sisanya dihapus.
        """
        all_settings = await db.cash_settings.find({}, {"_id": 1, "key": 1, "opening_balance": 1, "opening_date": 1}).to_list(length=1000)
        if len(all_settings) <= 1:
            return {"ok": True, "action": "no_duplicates", "count_before": len(all_settings)}

        # Pilih dokumen dengan opening_balance tertinggi (asumsi user paling recent = paling benar)
        best = max(all_settings, key=lambda s: float(s.get("opening_balance", 0)))
        # Set key='main' & pastikan hanya satu tersisa
        deleted = 0
        for s in all_settings:
            if s["_id"] != best["_id"]:
                await db.cash_settings.delete_one({"_id": s["_id"]})
                deleted += 1
        # Normalize key to 'main'
        await db.cash_settings.update_one(
            {"_id": best["_id"]},
            {"$set": {"key": "main"}},
        )
        logger.warning(
            f"CASHBOOK cleanup cash_settings by {user.get('email')} — kept {best['_id']} (opening={best.get('opening_balance')}), deleted {deleted}"
        )
        return {
            "ok": True,
            "count_before": len(all_settings),
            "deleted": deleted,
            "kept_opening_balance": float(best.get("opening_balance", 0)),
            "kept_opening_date": best.get("opening_date"),
        }


    @router.get("/cashbook/summary")
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

        # Opening balance per bulan = opening_balance + NET transaksi sebelum first
        # (kecuali user telah "mengunci" Saldo Awal bulan ini via override).
        override = await _get_month_opening_override(month)
        if override is not None:
            opening_of_period = float(override)
        else:
            prev = await db.cash_transactions.find(
                {"date": {"$lt": first}}, {"_id": 0, "type": 1, "amount": 1, "account_code": 1},
            ).to_list(length=200000)
            prev_net = 0.0
            for p in prev:
                if p["type"] == "in":
                    prev_net += float(p["amount"])
                elif p["type"] == "out":
                    prev_net -= float(p["amount"])
            if opening_date and opening_date > last:
                opening_of_period = 0.0
            else:
                opening_of_period = opening_balance
            opening_of_period += prev_net

        # Transaksi bulan ini
        month_tx = await db.cash_transactions.find({"date": {"$gte": first, "$lte": last}}, {"_id": 0}).to_list(length=50000)
        # === RUMUS MATEMATIKA MURNI (2026-08-08) ===
        # Total Pemasukan = SEMUA type=in (cash, transfer, shopee, adjustment) — semua menambah Kas.
        # Total Pengeluaran = SEMUA type=out.
        total_in = sum(float(t["amount"]) for t in month_tx if t["type"] == "in")
        total_out = sum(float(t["amount"]) for t in month_tx if t["type"] == "out")
        closing = opening_of_period + total_in - total_out
        # Alias untuk kompatibilitas UI lama
        total_in_all_accounts = total_in

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
            "total_in_all_accounts": round(total_in_all_accounts, 2),
            "tx_count": len(month_tx),
            "breakdown_in": sorted(breakdown_in.values(), key=lambda x: x["amount"], reverse=True),
            "breakdown_out": sorted(breakdown_out.values(), key=lambda x: x["amount"], reverse=True),
        }


    async def _ensure_adjustment_accounts():
        """Pastikan akun penyesuaian saldo kas exist."""
        for code, name, typ in [
            ("199-ADJ", "Penyesuaian Saldo Kas (Masuk)", "in"),
            ("599-ADJ", "Penyesuaian Saldo Kas (Keluar)", "out"),
        ]:
            exists = await db.cash_accounts.find_one({"code": code})
            if not exists:
                await db.cash_accounts.insert_one({
                    "id": str(uuid.uuid4()),
                    "code": code,
                    "name": name,
                    "type": typ,
                    "system": True,
                    "active": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })


    class AdjustBalanceIn(BaseModel):
        target_balance: float
        note: Optional[str] = ""

    @router.post("/cashbook/adjust-balance")
    async def cash_adjust_balance(payload: AdjustBalanceIn, user: dict = Depends(require_super_admin)):
        """Buat jurnal penyesuaian OTOMATIS agar saldo kas real-time menjadi `target_balance`.

        Formula konsisten dgn tampilan Buku Kas:
          current_balance = opening_balance + Σ(type=in, account=101) − Σ(type=out, semua akun)
          delta = target_balance − current_balance
          delta > 0: insert 1 tx type=in account=199-ADJ (Penyesuaian Kas Masuk) — TAPI account 199-ADJ pakai type=in
          delta < 0: insert 1 tx type=out account=599-ADJ (Penyesuaian Kas Keluar)

        Catatan: karena filter Buku Kas hanya menghitung KREDIT dari akun 101, kita buat akun penyesuaian
        khusus dengan code "101-ADJ" (type=in) supaya delta positif tetap menambah saldo Buku Kas.
        """
        # Pastikan akun penyesuaian ada (khusus 101-ADJ agar KREDIT dihitung Buku Kas via rule "in && 101*")
        # Kita override: akun 199-ADJ akan tetap type=in dan account_code akan diperlakukan sebagai 101
        # supaya masuk hitungan Buku Kas.
        # Alternative sederhana: pakai account_code="101" langsung supaya konsisten (dengan flag adjustment=True).
        setting = await _cash_setting()
        opening_balance = float(setting.get("opening_balance", 0))
        txs = await db.cash_transactions.find(
            {}, {"_id": 0, "type": 1, "amount": 1, "account_code": 1}
        ).to_list(length=200000)
        total_in_101 = sum(float(t["amount"]) for t in txs if t["type"] == "in" and t.get("account_code") == "101")
        total_out_all = sum(float(t["amount"]) for t in txs if t["type"] == "out")
        current_balance = round(opening_balance + total_in_101 - total_out_all, 2)

        target = round(float(payload.target_balance), 2)
        delta = round(target - current_balance, 2)

        if abs(delta) < 0.01:
            return {
                "ok": True,
                "no_op": True,
                "message": "Saldo saat ini sudah sama dengan target — tidak ada penyesuaian dibuat.",
                "current_balance": current_balance,
                "target_balance": target,
                "delta": 0.0,
            }

        # Bikin akun jika perlu — akun penyesuaian tetap pakai code 101/599-ADJ agar cocok dgn rule Buku Kas
        # Untuk delta positif → tx type=in account=101 (Kas) → masuk hitungan Buku Kas
        # Untuk delta negatif → tx type=out account=599-ADJ (Penyesuaian Keluar)
        await _ensure_cash_accounts()  # pastikan 101 ada
        if delta < 0:
            await _ensure_adjustment_accounts()

        note_txt = (payload.note or "").strip()
        base_desc = "Penyesuaian Saldo Kas — Update Manual"
        desc = f"{base_desc} · target Rp {int(target):,}".replace(",", ".") + (f" ({note_txt})" if note_txt else "")
        today_iso = datetime.now(timezone.utc).date().isoformat()

        if delta > 0:
            # Insert kredit ke akun 101 (uang masuk kas)
            inserted = await _insert_cash_transaction(
                account_code="101",
                description=desc,
                amount=abs(delta),
                reference="ADJUSTMENT",
                date_iso=today_iso,
                auto=False,
                created_by=user.get("email"),
            )
        else:
            # Insert debet ke akun 599-ADJ (uang keluar kas)
            inserted = await _insert_cash_transaction(
                account_code="599-ADJ",
                description=desc,
                amount=abs(delta),
                reference="ADJUSTMENT",
                date_iso=today_iso,
                auto=False,
                created_by=user.get("email"),
            )

        logger.info(
            f"SALDO KAS ADJUSTMENT by {user.get('email')} — "
            f"target={target}, current={current_balance}, delta={delta}, tx_id={inserted.get('id')}"
        )

        # Recompute after insertion untuk verifikasi
        new_balance = round(current_balance + delta, 2)
        return {
            "ok": True,
            "no_op": False,
            "current_balance": current_balance,
            "target_balance": target,
            "delta": delta,
            "new_balance": new_balance,
            "transaction": inserted,
        }


    @router.post("/cashbook/purge-adjustments")
    async def cash_purge_adjustments(user: dict = Depends(require_super_admin)):
        """Hapus SEMUA transaksi penyesuaian saldo (ref='ADJUSTMENT').

        Digunakan ketika user ingin membersihkan histori adjust-balance (mis. karena
        salah input atau ingin reset). Setelah dihapus, `Saldo Kas Real-time` akan
        berubah — user harus manual set `opening_balance` via PUT /cashbook/settings
        agar saldo kembali ke angka yang dikehendaki.
        """
        # Sample dulu utk audit log
        sample = await db.cash_transactions.find(
            {"reference": "ADJUSTMENT"},
            {"_id": 0, "id": 1, "date": 1, "type": 1, "amount": 1, "description": 1},
        ).sort("date", -1).to_list(length=200)
        total_amount_in = sum(float(t["amount"]) for t in sample if t.get("type") == "in")
        total_amount_out = sum(float(t["amount"]) for t in sample if t.get("type") == "out")

        result = await db.cash_transactions.delete_many({"reference": "ADJUSTMENT"})

        logger.warning(
            f"CASHBOOK PURGE ADJUSTMENTS by {user.get('email')} — "
            f"deleted {result.deleted_count} tx (in={total_amount_in}, out={total_amount_out})"
        )
        return {
            "ok": True,
            "deleted_count": result.deleted_count,
            "total_in_removed": round(total_amount_in, 2),
            "total_out_removed": round(total_amount_out, 2),
            "net_impact": round(total_amount_out - total_amount_in, 2),
            "sample": sample[:10],
        }

    @router.post("/cashbook/migrate-cash-sales-to-101")
    async def cash_migrate_cash_sales_to_101(user: dict = Depends(require_super_admin)):
        """Migrasi historis: Penjualan Tunai (cash) yang sebelumnya tercatat dengan
        account_code='301' → ubah ke '101' agar masuk ke Kas Utama Real-time.

        Aman dijalankan berkali-kali (idempotent) — hanya menyentuh cash_transactions
        yang direference oleh sale dgn payment_method='cash' & tercatat 301.
        """
        # Ambil semua sale_no dengan payment_method cash/tunai
        cash_sales_cursor = db.sales.find(
            {"payment_method": {"$in": ["cash", "tunai"]}},
            {"_id": 0, "sale_no": 1},
        )
        sale_nos = [s.get("sale_no") for s in await cash_sales_cursor.to_list(length=200000) if s.get("sale_no")]
        if not sale_nos:
            return {"ok": True, "migrated": 0, "note": "Tidak ada Penjualan Tunai historis."}

        # Update cash_transactions
        result = await db.cash_transactions.update_many(
            {
                "reference": {"$in": sale_nos},
                "account_code": "301",
                "type": "in",
            },
            {"$set": {"account_code": "101"}},
        )
        logger.warning(
            f"CASH SALES MIGRATE 301→101 by {user.get('email')} — updated {result.modified_count} tx"
        )
        return {
            "ok": True,
            "migrated": result.modified_count,
            "sale_count_scanned": len(sale_nos),
        }





    @router.get("/cashbook/export")
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
    @router.post("/cashbook/resync-sales")
    async def cashbook_resync_sales(
        user: dict = Depends(require_super_admin),
        dry_run: bool = False,
    ):
        """Re-sync semua pembayaran (DP + pelunasan) dari transaksi Penjualan ke Buku Kas.

        Backfill baris cash_transactions yang belum tercatat untuk historical sales.
        Match kriteria: (reference=sale_no, account_code, amount, date). Bila tidak ada match, insert.

        Response: {sales_scanned, payments_scanned, existing_matched, missing_inserted, total_inserted_amount, details:[]}
        """
        sales = await db.sales.find({}, {"_id": 0}).to_list(length=100000)
        # Preload semua existing auto cash tx dgn reference (untuk speed)
        existing = await db.cash_transactions.find(
            {"reference": {"$in": [s.get("sale_no") for s in sales if s.get("sale_no")]}},
            {"_id": 0, "reference": 1, "account_code": 1, "amount": 1, "date": 1},
        ).to_list(length=200000)
        # Key: (reference, account_code, round(amount,2), date)  → count occurrences
        existing_key = Counter()
        for e in existing:
            k = (e.get("reference"), e.get("account_code"), round(float(e.get("amount") or 0), 2), e.get("date"))
            existing_key[k] += 1

        inserted_details: List[Dict[str, Any]] = []
        payments_scanned = 0
        missing_inserted = 0
        total_inserted_amount = 0.0

        for s in sales:
            sale_no = s.get("sale_no")
            if not sale_no:
                continue
            # Ambil daftar pembayaran; fallback ke legacy field (cash_paid, payment_method, date)
            payments = s.get("payments") or []
            if not payments and float(s.get("cash_paid") or 0) > 0:
                payments = [{
                    "amount": min(float(s.get("cash_paid") or 0), float(s.get("total") or 0)),
                    "payment_method": s.get("payment_method") or "cash",
                    "payment_bank": s.get("payment_bank"),
                    "date": s.get("date"),
                    "notes": s.get("payment_notes"),
                    "is_initial": True,
                }]
            for p in payments:
                amt = round(float(p.get("amount") or 0), 2)
                if amt <= 0:
                    continue
                payments_scanned += 1
                pm = p.get("payment_method") or "cash"
                bank = p.get("payment_bank")
                acc_code, acc_label = _resolve_payment_account(pm, bank)
                p_date = (p.get("date") or s.get("date") or "")[:10]
                key = (sale_no, acc_code, amt, p_date)
                if existing_key.get(key, 0) > 0:
                    existing_key[key] -= 1  # consumed one match; leftover checked for duplicates
                    continue
                # Missing — insert
                is_initial = bool(p.get("is_initial"))
                sisa = round(float(s.get("sisa_tagihan") or 0), 2)
                status_at_time = s.get("status") or ("paid" if sisa <= 0.01 else "dp")
                if is_initial:
                    if status_at_time == "dp":
                        tag = f"DP (sisa Rp {sisa:,.0f})"
                    else:
                        tag = "LUNAS"
                else:
                    # Pelunasan lanjutan
                    if status_at_time == "paid":
                        tag = "Pelunasan · LUNAS"
                    else:
                        tag = f"Pelunasan · sisa Rp {sisa:,.0f}"
                desc = f"Penjualan {sale_no} — {s.get('customer_name') or 'Umum'} · {acc_label} · {tag} [RESYNC]"
                if p.get("notes"):
                    desc += f" ({p['notes']})"
                if dry_run:
                    inserted_details.append({
                        "sale_no": sale_no,
                        "customer": s.get("customer_name"),
                        "date": p_date,
                        "account_code": acc_code,
                        "account_label": acc_label,
                        "amount": amt,
                        "would_insert": True,
                    })
                else:
                    try:
                        await _insert_cash_transaction(
                            account_code=acc_code,
                            description=desc,
                            amount=amt,
                            reference=sale_no,
                            date_iso=p_date,
                            auto=True,
                            created_by=user.get("email"),
                        )
                        inserted_details.append({
                            "sale_no": sale_no,
                            "customer": s.get("customer_name"),
                            "date": p_date,
                            "account_code": acc_code,
                            "account_label": acc_label,
                            "amount": amt,
                        })
                    except Exception as ex:
                        logger.warning(f"Resync sale {sale_no} amount {amt} failed: {ex}")
                        continue
                missing_inserted += 1
                total_inserted_amount += amt

        return {
            "ok": True,
            "dry_run": dry_run,
            "sales_scanned": len(sales),
            "payments_scanned": payments_scanned,
            "missing_inserted": missing_inserted,
            "total_inserted_amount": round(total_inserted_amount, 2),
            "details": inserted_details[:100],  # cap 100 utk response size
            "details_total": len(inserted_details),
        }

    @router.post("/cashbook/resync-purchases")
    async def cashbook_resync_purchases(
        user: dict = Depends(require_super_admin),
        dry_run: bool = False,
    ):
        """Re-sync pembayaran PO (Pembelian) ke Buku Kas.

        PO tidak menyimpan history pembayaran per-transaksi, hanya cumulative `amount_paid`.
        Logika: untuk tiap PO, bandingkan `amount_paid` dgn total cash_tx yang sudah tercatat
        (reference=po_no, account_code=201). Bila `amount_paid` > existing_sum, insert delta.

        Response: {po_scanned, po_with_payment, missing_inserted, total_inserted_amount, details:[]}
        """
        pos = await db.purchase_orders.find(
            {"amount_paid": {"$gt": 0}},
            {"_id": 0, "id": 1, "po_no": 1, "supplier_name": 1, "amount_paid": 1, "total": 1, "date": 1, "last_payment_at": 1},
        ).to_list(length=100000)
        # Preload existing cash_tx dengan ref PO
        po_nos = [p.get("po_no") for p in pos if p.get("po_no")]
        existing = await db.cash_transactions.find(
            {"reference": {"$in": po_nos}, "account_code": "201"},
            {"_id": 0, "reference": 1, "amount": 1},
        ).to_list(length=200000)
        from collections import defaultdict
        existing_sum: Dict[str, float] = defaultdict(float)
        for e in existing:
            existing_sum[e.get("reference")] += float(e.get("amount") or 0)

        inserted_details: List[Dict[str, Any]] = []
        missing_inserted = 0
        total_inserted_amount = 0.0

        for p in pos:
            po_no = p.get("po_no")
            if not po_no:
                continue
            paid = round(float(p.get("amount_paid") or 0), 2)
            recorded = round(existing_sum.get(po_no, 0.0), 2)
            delta = round(paid - recorded, 2)
            if delta <= 0.01:  # tolerance floating point
                continue
            # Tanggal: pakai last_payment_at bila ada, else PO date, else today
            pdate = p.get("last_payment_at") or p.get("date") or ""
            if pdate:
                pdate = pdate[:10]
            else:
                pdate = datetime.now(timezone.utc).date().isoformat()

            supplier = p.get("supplier_name") or "-"
            total = round(float(p.get("total") or 0), 2)
            remaining = round(total - paid, 2)
            if remaining <= 0.01:
                tag = "LUNAS"
            else:
                tag = f"sisa Rp {remaining:,.0f}"
            desc = f"Bayar PO {po_no} — {supplier} · {tag} [RESYNC]"

            if dry_run:
                inserted_details.append({
                    "po_no": po_no, "supplier": supplier, "date": pdate,
                    "amount_paid_recorded": recorded, "amount_paid_actual": paid,
                    "delta_to_insert": delta, "would_insert": True,
                })
            else:
                try:
                    await _insert_cash_transaction(
                        account_code="201",
                        description=desc,
                        amount=delta,
                        reference=po_no,
                        date_iso=pdate,
                        auto=True,
                        created_by=user.get("email"),
                    )
                    inserted_details.append({
                        "po_no": po_no, "supplier": supplier, "date": pdate,
                        "amount_paid_recorded": recorded, "amount_paid_actual": paid,
                        "delta_to_insert": delta,
                    })
                except Exception as ex:
                    logger.warning(f"Resync PO {po_no} delta {delta} failed: {ex}")
                    continue
            missing_inserted += 1
            total_inserted_amount += delta

        return {
            "ok": True,
            "dry_run": dry_run,
            "po_scanned": len(pos),
            "po_with_missing_payment": missing_inserted,
            "missing_inserted": missing_inserted,
            "total_inserted_amount": round(total_inserted_amount, 2),
            "details": inserted_details[:100],
            "details_total": len(inserted_details),
        }


    def _normalize_kasbon_status(raw: Any) -> str:
        """Normalize kasbon status ke UPPERCASE canonical: 'PENDING' atau 'PAID'.

        Rules:
          - "open" / "pending" / "" / None → 'PENDING'
          - "settled" / "paid" / "lunas" / "closed" / "done" → 'PAID'
          - Lainnya → 'PENDING' (safe fallback, agar tidak lolos filter yang salah)
        """
        s = str(raw or "").strip().lower()
        if s in ("settled", "paid", "lunas", "closed", "done"):
            return "PAID"
        return "PENDING"

    @router.get("/cashbook/kasbon")
    async def kasbon_list(
        user: dict = Depends(require_super_admin),
        month: Optional[str] = None,  # YYYY-MM (opsional)
        status: Optional[str] = None,  # "open"/"PENDING" | "settled"/"PAID"
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
        # Filter status di DB level (menerima berbagai varian input)
        status_lc = (status or "").strip().lower()
        if status_lc in ("open", "pending"):
            # Data lama bisa punya value bervariasi — match beberapa varian
            q["status"] = {"$in": ["open", "pending", "OPEN", "PENDING", "Pending", "Open", "", None]}
        elif status_lc in ("settled", "paid", "lunas"):
            q["status"] = {"$in": ["settled", "paid", "lunas", "closed", "done", "SETTLED", "PAID", "LUNAS", "Settled", "Paid", "Lunas"]}
        items_raw = await db.kasbon_sementara.find(q, {"_id": 0}).sort([("date", 1), ("created_at", 1)]).to_list(length=5000)
        # Normalize status di setiap item agar frontend terima label seragam ("PENDING"/"PAID")
        items: List[Dict[str, Any]] = []
        for it in items_raw:
            it["status"] = _normalize_kasbon_status(it.get("status"))
            items.append(it)
        # Extra safety: jika client minta status=open/PENDING, filter lagi post-normalize
        if status_lc in ("open", "pending"):
            items = [it for it in items if it["status"] == "PENDING"]
        elif status_lc in ("settled", "paid", "lunas"):
            items = [it for it in items if it["status"] == "PAID"]
        total_open = sum(float(i.get("amount", 0)) for i in items if i["status"] == "PENDING")
        total_settled = sum(float(i.get("amount", 0)) for i in items if i["status"] == "PAID")
        total_all = sum(float(i.get("amount", 0)) for i in items)
        return {
            "items": items,
            "total_open": round(total_open, 2),
            "total_settled": round(total_settled, 2),
            "total_all": round(total_all, 2),
            "count": len(items),
        }


    @router.post("/cashbook/kasbon")
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
            "status": "open",  # simpan sbg "open" di DB (backward-compat); output di-normalize ke "PENDING"
            "settled_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": user.get("email"),
        }
        await db.kasbon_sementara.insert_one(doc)
        doc.pop("_id", None)
        # Normalize output status
        doc["status"] = _normalize_kasbon_status(doc["status"])
        return doc


    @router.put("/cashbook/kasbon/{kasbon_id}")
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
        if doc:
            doc["status"] = _normalize_kasbon_status(doc.get("status"))
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


    @router.put("/cashbook/kasbon/{kasbon_id}/settle")
    async def kasbon_settle(kasbon_id: str, user: dict = Depends(require_super_admin)):
        existing = await db.kasbon_sementara.find_one({"id": kasbon_id})
        if not existing:
            raise HTTPException(status_code=404, detail="Kasbon tidak ditemukan")
        # Normalisasi: cek semua varian PAID (settled/paid/lunas/dll — case-insensitive)
        _cur_status = str(existing.get("status") or "").strip().upper()
        if _cur_status in ("SETTLED", "PAID", "LUNAS", "CLOSED", "DONE"):
            raise HTTPException(status_code=400, detail="Kasbon sudah dilunaskan")
        settled_at = datetime.now(timezone.utc).isoformat()
        await db.kasbon_sementara.update_one(
            {"id": kasbon_id},
            {"$set": {"status": "PAID", "settled_at": settled_at}},
        )
        # Auto-insert pengeluaran ke Jurnal Kas Utama (Akun 101, DEBET)
        try:
            # Bersihkan sisa tx lama (jika ada) sebelum insert baru — idempotent
            await _kasbon_delete_settlement_tx(kasbon_id)
            await _kasbon_create_settlement_tx(existing, user.get("email"))
        except Exception as ex:
            logger.warning(f"Cashbook auto-insert (kasbon settle) failed: {ex}")
        doc = await db.kasbon_sementara.find_one({"id": kasbon_id}, {"_id": 0})
        if doc:
            doc["status"] = _normalize_kasbon_status(doc.get("status"))
        return doc


    @router.put("/cashbook/kasbon/{kasbon_id}/reopen")
    async def kasbon_reopen(kasbon_id: str, user: dict = Depends(require_super_admin)):
        existing = await db.kasbon_sementara.find_one({"id": kasbon_id})
        if not existing:
            raise HTTPException(status_code=404, detail="Kasbon tidak ditemukan")
        await db.kasbon_sementara.update_one(
            {"id": kasbon_id},
            {"$set": {"status": "PENDING", "settled_at": None, "paid_at": None, "date_settled": None}},
        )
        # Rollback auto cash-tx pelunasan
        try:
            await _kasbon_delete_settlement_tx(kasbon_id)
        except Exception as ex:
            logger.warning(f"Cashbook auto-delete (kasbon reopen) failed: {ex}")
        doc = await db.kasbon_sementara.find_one({"id": kasbon_id}, {"_id": 0})
        if doc:
            doc["status"] = _normalize_kasbon_status(doc.get("status"))
        return doc


    @router.delete("/cashbook/kasbon/{kasbon_id}")
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


    @router.post("/cashbook/kasbon/settle-all-pending")
    async def kasbon_settle_all_pending(user: dict = Depends(require_super_admin)):
        """Bulk-mark SEMUA kasbon status PENDING → PAID sekaligus.

        Nuclear option untuk membersihkan tabel "Kasbon Sementara (belum lunas)"
        di tab Buku Kas ketika ada banyak entri lama yang seharusnya sudah lunas
        tapi belum ditandai. TIDAK membuat auto cash-tx pelunasan (karena kasbon
        lama biasanya bukan berasal dari kas real — mis. entri auto dari
        Pembelian/Shopee).
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        # Match semua varian status yang dianggap PENDING (data lama tidak konsisten)
        q = {"status": {"$in": ["open", "pending", "OPEN", "PENDING", "Pending", "Open", "", None]}}
        result = await db.kasbon_sementara.update_many(
            q,
            {"$set": {
                "status": "PAID",
                "settled_at": now_iso,
                "bulk_settled_at": now_iso,
                "bulk_settled_by": user.get("email"),
            }},
        )
        logger.warning(
            f"KASBON BULK-SETTLE ALL PENDING by {user.get('email')} — "
            f"marked {result.modified_count} kasbon as PAID"
        )
        return {
            "ok": True,
            "settled_count": result.modified_count,
            "settled_at": now_iso,
        }


    @router.post("/cashbook/kasbon/migrate-status")
    async def kasbon_migrate_status(
        user: dict = Depends(require_super_admin),
        apply: bool = False,
    ):
        """One-time migration: normalize semua kasbon.status di DB ke canonical UPPERCASE.

        Args:
          apply: bool (default False) → dry-run mode. Set `?apply=true` untuk commit ke DB.

        Rules:
          - open/pending/empty/null → "PENDING"
          - settled/paid/lunas/closed/done (any case) → "PAID"

        Returns:
          {
            mode: "dry_run" | "applied",
            total_scanned, would_change|changed,
            by_status_before: {status_raw: count},
            by_status_after:  {PENDING: n, PAID: n},
            sample_changes: [{id, before, after, name}, ...] (max 10)
          }
        """
        if user.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="Hanya Super Admin yang bisa migrate")

        all_kasbon = await db.kasbon_sementara.find({}, {"_id": 0}).to_list(length=100000)
        by_before: Dict[str, int] = {}
        changes: List[Dict[str, Any]] = []
        after_pending = 0
        after_paid = 0

        for k in all_kasbon:
            raw = k.get("status")
            key = f"{raw!r}"
            by_before[key] = by_before.get(key, 0) + 1
            normalized = _normalize_kasbon_status(raw)
            if raw != normalized:
                changes.append({
                    "id": k.get("id"),
                    "name": k.get("name", ""),
                    "before": raw,
                    "after": normalized,
                })
            if normalized == "PENDING":
                after_pending += 1
            else:
                after_paid += 1

        applied_count = 0
        if apply and changes:
            # Bulk update: MongoDB update_many per status target
            for target_status in ["PENDING", "PAID"]:
                ids_for_target = [c["id"] for c in changes if c["after"] == target_status]
                if ids_for_target:
                    r = await db.kasbon_sementara.update_many(
                        {"id": {"$in": ids_for_target}},
                        {"$set": {"status": target_status, "status_migrated_at": datetime.now(timezone.utc).isoformat()}},
                    )
                    applied_count += r.modified_count
            logger.warning(
                f"KASBON STATUS MIGRATION applied by {user.get('email')} — "
                f"modified {applied_count} records"
            )

        return {
            "mode": "applied" if apply else "dry_run",
            "total_scanned": len(all_kasbon),
            "would_change" if not apply else "changed": len(changes) if not apply else applied_count,
            "by_status_before": by_before,
            "by_status_after": {"PENDING": after_pending, "PAID": after_paid},
            "sample_changes": changes[:10],
        }


    return router
