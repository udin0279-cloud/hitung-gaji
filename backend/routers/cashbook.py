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

    # ---------- Endpoints ----------
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
        # Compute running balance — Kas flow: SEMUA type=in menambah, SEMUA type=out mengurangi
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
            prev = await db.cash_transactions.find(
                {"date": {"$lt": first_of_month}}, {"_id": 0, "type": 1, "amount": 1},
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
        txs = await db.cash_transactions.find({}, {"_id": 0, "type": 1, "amount": 1}).to_list(length=200000)
        # Total pemasukan Kas = SEMUA type=in (termasuk 301-SPP/SPK Shopee netto, 301 Tunai, dsb)
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

        # Opening balance per bulan = opening_balance + net transaksi sebelum first
        # Total pemasukan Kas mencakup SEMUA type=in (termasuk 301-SPP/SPK Shopee)
        prev = await db.cash_transactions.find(
            {"date": {"$lt": first}}, {"_id": 0, "type": 1, "amount": 1},
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
        # Total Pemasukan (KREDIT) — SEMUA type=in
        total_in = sum(float(t["amount"]) for t in month_tx if t["type"] == "in")
        # Total Pengeluaran (DEBET) — semua akun
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


    @router.get("/cashbook/kasbon")
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
            "status": "open",
            "settled_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": user.get("email"),
        }
        await db.kasbon_sementara.insert_one(doc)
        doc.pop("_id", None)
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


    @router.put("/cashbook/kasbon/{kasbon_id}/reopen")
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

    return router
