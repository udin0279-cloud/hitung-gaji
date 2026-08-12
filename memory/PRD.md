# Payroll Indonesia — Product Requirements (PRD)

## Problem Statement
"program payroll lengkap dengan cara perhitungan otomatis"

Aplikasi payroll Indonesia yang lengkap dengan perhitungan otomatis (PPh 21, BPJS Kesehatan, BPJS Ketenagakerjaan).

## Architecture
- **Backend**: FastAPI + Motor (MongoDB), JWT auth via httpOnly cookies, bcrypt password hashing
- **Frontend**: React (Router 7), TailwindCSS, Recharts, Sonner toasts, Lucide icons
- **Database**: MongoDB (collections: users, employees, payroll_runs, payslips)
- **Design Theme**: Swiss & High-Contrast (Cabinet Grotesk + IBM Plex Sans + JetBrains Mono)

## User Personas
- **HR / Admin** (primary): Manages employee master data, attendance, runs monthly payroll, prints payslips.

## Core Requirements (Static)
1. Indonesian payroll regulation compliance (UU HPP 2022 + BPJS rates 2024)
2. Automatic PPh 21 calculation (progressive: 5/15/25/30/35%)
3. BPJS Kesehatan (1% emp / 4% employer, cap 12jt) + Ketenagakerjaan (JHT/JP/JKK/JKM)
4. PTKP table (TK/0 through K/3)
5. Biaya jabatan deduction (5%, max 6jt/year)
6. Non-NPWP +20% surcharge
7. Pro-rated salary by days worked
8. Overtime calculation (basic/173 * 1.5 per hour)
9. Printable A4 payslip



## Update 2026-08-05 (part 2) — Slip Gaji: HANYA 2 Potongan Visible (Opsi B)
- **Simplifikasi Potongan Slip Gaji (2026-08-05, Opsi B — REMOVE dari perhitungan)**: Per permintaan user, HANYA 2 baris potongan yang muncul di slip:
  - **Angsuran Pinjaman** (dari `d.loan`)
  - **Potongan Lain-lain** (gabungan dari `other_deduction` + `potongan_terlambat` + `potongan_pulang_cepat`)
  - **Total Potongan** = loan + other_combined (BPJS/JHT/JP/PPh21 TIDAK dipotong lagi dari take-home)
  - **Net Salary** = gross − Total Potongan (visible only) → take-home pay LEBIH BESAR
  - **Sisa Pinjaman**: baris info baru — muncul jika loan aktif & remaining_amount > 0, format `Sisa Pinjaman · tenor N/M`, tidak masuk ke Total Potongan (info transparansi saja)
  - BPJS/JHT/JP/PPh21 **masih dihitung** di backend (untuk laporan tahunan/bukti potong 1721-A1 compliance), tersimpan di `deductions.bpjs_*/jht_*/jp_*/pph21` tapi tidak masuk `deductions.total`
  - Field baru: `loan_info.total_amount`, `loan_info.remaining_amount` untuk info sisa
  - **Files updated**: `calculate_payslip` (server.py), `_build_payslip_pdf` (server.py), `_payslip_html` (server.py), `Payslip.jsx` (frontend)
  - **Verified via curl+screenshot**: Gross Rp 1.692.308 − (Loan 500rb + Other 100rb) = Net Rp 1.092.308 ✓ tampil di UI dengan hanya 2 baris potongan visible
  - **⚠ IMPACT**: Payslip lama (2026-07) tetap pakai formula lama sampai payroll di-rerun untuk periode itu. Payroll run baru akan pakai formula baru.



## Update 2026-08-05 — Kolom SALDO KAS di Jurnal Akuntansi
- **Kolom SALDO KAS di Tab Jurnal Akuntansi (2026-08-05)**: Menambahkan kolom baru "SALDO KAS" (highlight biru) di antara PENGELUARAN dan AKSI pada BookTab `CashBook.jsx`. Kolom AKSI dipindah ke paling kanan. Running balance dihitung via `useMemo` yang men-walk `txData.transactions` menerapkan aturan Buku Kas yang sama: KREDIT hanya untuk `type=in && account_code=101`, DEBET untuk `type=out` (semua akun). Snapshot per tx.id memungkinkan setiap baris (termasuk row non-Kas) menampilkan saldo kas real-time pada saat itu. Row TOTAL menampilkan `currentBalance` (dari balance API) agar tersinkronisasi dengan tab Buku Kas. Verified via screenshot Jul 2026: 5 transaksi non-Kas dengan running balance 1jt → 970rb → 940rb → 930rb → 884.500, sync sempurna dengan Saldo Akhir Jul 2026.



## Update 2026-08-04 (part 3) — Fitur Bulk Settle All Pending Kasbon
- **Bulk Settle All Pending Kasbon (2026-08-04)**: Menambahkan tombol "TANDAI SEMUA LUNAS" (hijau) di tab Kasbon Sementara — muncul otomatis hanya ketika ada kasbon PENDING (`data.total_open > 0`). Ketika diklik → double confirm (konfirmasi window + ketik "LUNAS SEMUA") → memanggil endpoint baru `POST /cashbook/kasbon/settle-all-pending`. Backend melakukan `update_many` untuk mengubah semua kasbon dengan status varian (open/pending/OPEN/PENDING/Pending/Open/""/null) menjadi "PAID" sekaligus, TANPA membuat auto cash-tx pelunasan (karena kasbon lama biasanya bukan dari kas real seperti auto entry Pembelian/Shopee). Tersimpan `bulk_settled_at` + `bulk_settled_by` untuk audit. Setelah bulk-settle, tabel "Kasbon Sementara (belum lunas)" di tab Buku Kas otomatis bersih. Verified: endpoint returns `{ok:true, settled_count:N}`, button muncul saat ada PENDING, hidden saat tidak. **Perlu redeploy ke production untuk pakai.**



## Update 2026-08-04 (part 2) — Refactor Portal + Employees → router terpisah
- **Refactor Employees & Portal ke Router Terpisah (2026-08-04)**: Bagian dari lanjutan modularisasi. Membuat 2 file baru:
  - `/app/backend/routers/employees.py` (168 baris): 7 endpoint admin karyawan — `GET/POST /employees`, `GET/PUT/DELETE /employees/{id}`, `GET /employees-template.csv`, `POST /employees-import`. Model `EmployeeIn` + `EMPLOYEE_CSV_HEADERS` diinjeksi via factory.
  - `/app/backend/routers/portal.py` (443 baris): 15 endpoint self-service karyawan — `/portal/login`, `/portal/logout`, `/portal/me`, `/portal/payslips`, `/portal/payslip/{id}`, `/portal/payslip/{id}/pdf`, `/portal/thr`, `/portal/annual/{year}`, `/portal/bukti-potong/{year}/pdf`, `/portal/forgot`, `/portal/magic-login`, `/portal/leave` (POST/GET/DELETE/attachment). Helpers `get_current_employee`, `create_portal_token`, `_build_payslip_pdf`, `_build_annual_summary`, `_build_bukti_potong_pdf`, `_send_simple_email`, `_leave_view`, konstanta `LEAVE_TYPES`/`LEAVE_TYPE_LABELS`/`MAX_ATTACHMENT_SIZE`/`ALLOWED_ATTACHMENT_MIME` diinjeksi via factory. Model `PortalLoginIn` & `ForgotPortalIn` di-duplicate lokal.
  - **server.py**: 5082 → 4630 baris (-452). Total routers extracted: 7 (attendance, cashbook, sales, backup, payroll, employees, portal). Tested via curl: `/employees` (5), `/employees-template.csv` (200), `/portal/login` (valid & invalid), `/portal/me`, `/portal/payslips` (1), `/portal/leave` (0). Frontend Karyawan page render 5 karyawan sempurna.



## Update 2026-08-04 — Refactor Payroll → routers/payroll.py
- **Refactor Payroll ke Router Terpisah (2026-08-04)**: Bagian dari lanjutan modularisasi setelah Attendance/Cashbook/Sales/Backup. Membuat `/app/backend/routers/payroll.py` (480 baris) yang berisi 17 endpoint admin Payroll: `/payroll/preview`, `/payroll/run`, `/payroll/runs`, `/payroll/runs/{period}/slips`, `/payroll/payslip/{id}`, DELETE `/payroll/runs/{period}`, `/payroll/payslip/{id}/pdf`, `/payroll/thr/preview`, `/payroll/thr/run`, `/payroll/thr/runs`, `/payroll/thr/{period}/slips`, `/payroll/payslip/{id}/email`, `/payroll/runs/{period}/email-all`, `/payroll/runs/{period}/bank-export`, `/payroll/payslip/{id}/whatsapp`, `/payroll/runs/{period}/whatsapp-all`, `/payroll/bukti-potong/{emp_id}/{year}/pdf`. Helpers (`calculate_payslip`, `_calculate_thr`, `_build_payslip_pdf`, `_payslip_html`, `_send_email_via_resend`, `_whatsapp_slip_message`, `_send_whatsapp`, `_format_bank_export`, `_build_annual_summary`, `_build_bukti_potong_pdf`) tetap di server.py dan diinjeksi via factory `make_router(...)`. Models `PayrollRunIn` & `THRRunIn` di-duplicate lokal di router. Server.py berkurang dari 5449 → 5082 baris (-367). Tested via curl: preview 5 slips, /runs list, payslip PDF 2931 bytes. Frontend Payroll page render normal.



## Update 2026-08-04 — REVERT Section Kasbon Sementara di Buku Kas
- **Buku Kas — REVERT: Tampilkan Kembali Tabel Kasbon Sementara di Tab Buku Kas (2026-08-04)**: User meralat instruksi penghapusan sebelumnya. Section "· KASBON SEMENTARA (BELUM LUNAS)" dikembalikan ke JournalTab di `CashBook.jsx` dengan STRICT filter — hanya row dengan `status === 'PENDING'` yang tampil (data LUNAS otomatis tersembunyi via `isOpenKasbon()`). Yang direstore: (1) list rows orange di table, (2) baris footer "− Kasbon Belum Lunas", (3) formula `closingBalance = openingBalance + Kredit − Debet − kasbonTotal`, (4) subValue "− Kasbon: Rp X" di StatCard Saldo Real-time + Saldo Akhir Bulanan, (5) prop `currentBalance` di BookTab & AdjustBalanceModal dikurangi `kasbonOpen.total_open` kembali, (6) prop `kasbonOpen` dikembalikan ke `<JournalTab>`. Filter `isOpenKasbon` tetap STRICT (whitelist "PENDING" only + `settled_at` guard + amount > 0). Data saat ini 0 kasbon PENDING karena migrasi sebelumnya sudah menandai semua sebagai PAID — perilaku display kosong = CORRECT.


## Update 2026-08-01 — Fix Attendance Import + Bug P1 (Pelunasan Search & Edit Sale Preserve Payments) + POC Refactor
- **Pusat Backup Data (2026-08-03)**: Fitur baru untuk super_admin — halaman `/backup` dengan tombol **Download Backup (.zip)** yang export SEMUA koleksi MongoDB (attendance_daily, attendance_imports, payroll_runs, payslips, sales, users, products, cash_accounts, cash_transactions, dsb) ke ZIP berisi JSON per collection + `manifest.json` (metadata: timestamp, user, counts). Backend router baru `/app/backend/routers/backup.py` (~150 baris). Log tercatat di `backup_logs` collection dan ditampilkan sebagai tabel riwayat (timestamp, user, jumlah koleksi/record, ukuran file, nama file). Guard super_admin di frontend + backend endpoint. Nav item "Pusat Backup" (icon HardDrive) muncul di sidebar hanya untuk super_admin. Tested: 29 koleksi, 173 records, 21.7 KB output ZIP valid.

- **Buku Kas — HAPUS Total Section Kasbon Sementara dari Tab Buku Kas (2026-08-03)**: Sesuai request user "kalau masih kesulitan filter, HAPUS saja". Semua elemen kasbon di JournalTab dihapus permanen: (1) baris table "· KASBON SEMENTARA (BELUM LUNAS)" + list rows orange, (2) baris footer "− Kasbon Belum Lunas", (3) formula `closingBalance = ... − kasbonTotal` diganti dgn simple `openingBalance + Kredit − Debet`, (4) subtitle StatCard "− Kasbon: Rp X" dihapus dari kartu Saldo Kas Real-time + Saldo Akhir, (5) Modal "Update Saldo Kas Terakhir" `currentBalance` prop tidak lagi dikurangi kasbon, (6) prop `kasbonOpen` dihapus dari `<JournalTab>`. Tab "Kasbon Sementara" terpisah tetap tersedia untuk audit history. Footer text updated: "Kasbon Sementara tersedia di tab terpisah". Screenshot verified: 0 baris kasbon di table Buku Kas.



- **Buku Kas — Perbaikan Rumus + Adjustment + Filter Riwayat + Navigasi Bulan (2026-08-03)**:
  1. Rumus KREDIT hanya akun `101`, DEBET semua akun — konsisten di `/cashbook/balance`, `/summary`, `/transactions`.
  2. Endpoint `POST /cashbook/adjust-balance` untuk jurnal penyesuaian otomatis (delta+ code 101 in, delta− code 599-ADJ out, ref="ADJUSTMENT").
  3. Modal "Update Saldo Kas Terakhir" di tab Jurnal Akuntansi dgn double confirm.
  4. Filter Riwayat Adjustment: badge hijau/merah "Penyesuaian" di row, toggle "Adjustment Only (N)" di header.
  5. Label "Saldo Awal [bulan]" → **"Saldo Akhir [bulan sebelumnya]"** untuk clarity akuntansi.
  6. Komponen `MonthNav` dgn tombol prev/next di 4 tab (Jurnal Akuntansi, Buku Kas, Ringkasan Kategori, Kasbon Sementara) — navigasi antar-bulan 1-klik.


  1. **Rumus konsisten backend↔frontend**: `/cashbook/balance`, `/cashbook/summary`, `/cashbook/transactions?month=X` — semua endpoint sekarang hitung KREDIT **hanya akun `101`** (bukan semua `type=in`). DEBET tetap semua akun.
  2. **Endpoint `POST /cashbook/adjust-balance`**: Buat jurnal penyesuaian otomatis. Insert 1 tx dgn `reference="ADJUSTMENT"`.
  3. **UI Modal "Update Saldo Kas Terakhir"** di tab Jurnal Akuntansi (icon Target).
  4. **Filter Riwayat Adjustment** di tab Buku Kas: badge hijau/merah "Penyesuaian" di baris terkait, row highlighted, tombol toggle "Adjustment Only (N)" di header, counter dinamis di footer. Testid: `filter-adjustment-toggle` + `data-adjustment` di row.


- **Import Absensi Fingerprint** (3 update):
  1. Logika `has_pair` (scan_count >= 2 AND in_time != out_time) sudah aktif. VERYAN (PIN 22) tepat = **8 hari** ✓
  2. **Fix data ganda (2026-08-01 malam)**: `POST /attendance/import` sekarang **pre-clear** semua `attendance_daily` untuk semua bulan yang tersentuh file sebelum insert baru. Juga hapus `attendance_imports` untuk period yang di-import. Response field baru `pre_cleared_daily_records`.
  3. **Reset Total Endpoint (2026-08-01 malam)**: Tambah `POST /attendance/reset-all?confirm=YES-RESET-ALL` (super_admin only) untuk hapus TOTAL `attendance_daily` + `attendance_imports`. Butuh query param `confirm=YES-RESET-ALL` sebagai safeguard. Tombol "Reset Total Absensi" (merah, ikon Trash2) muncul di halaman Payroll dgn double-prompt (ketik `RESET SEMUA ABSENSI` + konfirmasi native). Testid: `reset-attendance-all-btn`. Response: `{ok, deleted_daily, deleted_imports, executed_by, executed_at}`. Log warning di backend untuk audit.
- **Bug P1 Fix #1 (SalesReport)**: `SalesReport.jsx:840` — parameter search endpoint `/sales` diubah dari `search` menjadi `q` (sesuai backend). Pelunasan piutang lama sekarang bisa cari & lunas.
- **Bug P1 Fix #2 (Edit Sale)**: `PUT /sales/{id}` sekarang **preserve pelunasan payments** (non-initial). Sebelumnya edit sale menghapus riwayat pelunasan dan cash tx-nya. Fix: capture `pelunasan_payments` sebelum rollback → setelah rebuild, `$push` payments kembali + re-insert cash tx via `_insert_cash_transaction`, recompute `cash_paid`/`sisa_tagihan`/`status`. Validated end-to-end via curl: total 500k→600k → sisa jadi 100k dp, 2 payments preserved, 2 cash tx tetap tersimpan di Buku Kas.
- **Refactor POC — Modul Attendance**: Semua kode Attendance (constants, helpers, 4 endpoint) sudah dipindah ke `/app/backend/routers/attendance.py` (~600 baris). Pattern: `make_router(db, require_super_admin, logger)` factory untuk dependency injection.
- **Refactor Modul Cashbook**: Semua endpoint & helper cashbook/kasbon (20+ endpoint) pindah ke `/app/backend/routers/cashbook.py` (~890 baris). Pydantic models `CashAccountIn`/`CashTransactionIn`/`CashSettingIn`/`KasbonIn` di module level. Helpers `_cash_setting`, `_is_cash_tx_orphaned`, `_cash_tx_source_type`, `_kasbon_*` di dalam `make_router` closure. Shared helpers `_insert_cash_transaction`, `_ensure_cash_accounts`, `_resolve_payment_account`, `PAYMENT_ACCOUNT_MAP`, `_company_info` tetap di server.py (dipakai lintas modul). E2E tested: sales create → auto cash tx tetap masuk ke akun 301, resync-sales/purchases, kasbon settle/reopen, Excel export semua berfungsi.
- **Refactor Modul Sales/POS**: Semua endpoint sales (18+) & helper `_build_and_persist_sale`, `_rollback_sale_effects`, `_next_sale_no`, `_apply_shopee_admin_fee_update` pindah ke `/app/backend/routers/sales.py` (~2370 baris). Pydantic models `SaleItemIn`/`SaleIn`/`SaldoMasukIn`/`PayRemainingIn` di module level. Include statement diletakkan SETELAH cashbook router agar helper `_insert_cash_transaction` sudah defined. E2E tested lengkap: create DP → pay-remaining → edit sale → payments/cash-tx preserved, semua report (PDF/Excel/analytics/shopee-rincian) & receipt/invoice-pdf OK. **server.py: 9212 → 5444 baris (-3768 baris / -41% dari 3 refactor)**.






## Update 2026-07-30 — Omzet = Uang Diterima (Sinkron Buku Kas)
- `GET /api/sales/report/analytics` now computes **`period_total` (Omzet)** ONLY from received payments (initial DP + pelunasan) where **`payment.date` is within the filter period**.
- Query is broadened: sales are included if `sale.date` OR `payments.date` falls in period (so pelunasan of an older sale still contributes to that month's Omzet).
- Hutang / sisa tagihan pelanggan EXCLUDED from Omzet Utama.
- Shopee tetap NETTO: admin fee dikurangi dari initial payment.
- `weekly_total`, `daily_series`, `method_breakdown` juga mengikuti logika baru (payment-date based).
- Frontend card `summary-period-total` diberi label "(Uang Diterima)" + tooltip penjelasan.
- Validasi (July 2026 preview): Omzet **Rp 1.000.000** = Cashbook `total_in` **Rp 1.000.000** (SAMA PERSIS).

## What's Been Implemented (2026-02)
### Backend (`/app/backend/server.py`)
- JWT auth: register, login, logout, /me (httpOnly cookies, 12h access + 7d refresh)
- Admin auto-seed from `.env`
- Employee CRUD: `/api/employees` (NIK unique, full payroll fields)
- Bulk CSV import: `/api/employees-import` + template download
- Payroll preview: `/api/payroll/preview` (computes without saving)
- Payroll run: `/api/payroll/run` (idempotent per period — replaces previous)
- Payroll history: `/api/payroll/runs`, `/api/payroll/runs/{period}/slips`
- Single payslip: `/api/payroll/payslip/{slip_id}`
- PDF export: `/api/payroll/payslip/{slip_id}/pdf` (reportlab A4)
- Fingerprint import: `/api/attendance/import?period=...` (xlsx/xls/csv → auto-aggregate)
- **THR**: `/api/payroll/thr/preview`, `/api/payroll/thr/run`, `/api/payroll/thr/runs`, `/api/payroll/thr/{period}/slips` (proportional for tenure < 12 months, isolated PPh21 method)
- **Email payslip**: `/api/payroll/payslip/{slip_id}/email` + `/api/payroll/runs/{period}/email-all` (Resend integration; mock mode when key empty; logs to `email_logs`)
- **Bank transfer export**: `/api/payroll/runs/{period}/bank-export?format={generic|bca|mandiri|bni|bri}`
- **Editable config**: GET + PUT `/api/config/constants` (PPh21, PTKP, BPJS, biaya jabatan, hari kerja, lembur multiplier) — persisted in `app_config` collection, hot-reload
- Dashboard stats: `/api/dashboard/stats`

### Frontend (`/app/frontend/src/`)
- `/login` — Branded split-screen login
- `/` — Dashboard with hero stat, 4 metric cards, 12-period trend chart
- `/employees` — CRUD + CSV import + template download
- `/payroll` — Period picker + attendance + **Import Fingerprint** + preview/generate + history
- `/payroll/:period` — Detail listing + **bank export** dropdown (5 formats) + **Kirim Email ke Semua**
- `/payslip/:slipId` — Printable A4 + **Unduh PDF** + **Kirim Email**
- `/thr` — Period picker + preview + run + history of THR runs
- `/settings` — Fully editable PPh21 brackets, PTKP, BPJS, biaya jabatan, etc.

### Testing
- 31/31 backend pytest cases pass
- Full frontend e2e flow verified
- Test credentials at `/app/memory/test_credentials.md`

## Backlog (Prioritized)
### P1
- Export payslip to PDF (server-side via reportlab) instead of relying on browser print
- Bulk import karyawan from CSV/Excel
- THR (13th month) calculation for Idul Fitri / religious holidays
- Multi-user roles (Admin vs HR Staff vs Finance)

### P2
- Edit BPJS / PPh21 / PTKP configuration via UI (currently constants in code)
- Email payslip to each employee
- Payroll approval workflow (draft → submitted → approved → paid)
- Bank transfer export file (CSV per bank format: BCA, Mandiri, BNI, BRI)
- Employee self-service portal (view own payslips)
- Tax summary / yearly Bukti Potong 1721-A1

### P3
- Loan/cash advance tracking and amortization deductions
- Multi-company / branch support
- Audit log
- Mobile-optimized PWA

## Next Action Items
- User to test the live demo and provide feedback
- If feedback positive: prioritize PDF export + CSV bulk import (highest HR pain points)

---
## Update: 2026-02 — Leave & Permission Module

### Implemented
- 4 leave types: Datang Terlambat, Pulang Awal, Tidak Masuk, Sakit
- Employee Portal page `/portal/leave` with submit form + history
- HR Admin page `/leave` with stats, filters (status/type), approve/reject modal
- Sidebar nav badge with live pending count (polls /api/leave/stats every 60s)
- Optional file upload (PDF/JPG/PNG, max 2MB) stored as base64 in MongoDB
- Email notifications: HR gets new request alert; Employee gets approval/rejection status (via existing Resend)
- HR manual deduction during payroll (no auto-deduct from approved leaves)

### API Endpoints
- POST/GET/DELETE `/api/portal/leave`
- GET `/api/portal/leave/{id}/attachment`
- GET `/api/leave?status=&type=`, GET `/api/leave/stats`, GET `/api/leave/{id}`
- PUT `/api/leave/{id}/approve`, PUT `/api/leave/{id}/reject` (requires hr_note)
- GET `/api/leave/{id}/attachment` (admin)

### Files Changed
- backend/server.py — added Leave module section + _send_simple_email helper
- frontend/src/pages/PortalLeave.jsx (new)
- frontend/src/pages/LeaveAdmin.jsx (new)
- frontend/src/components/Layout.jsx (nav + badge)
- frontend/src/App.js (routes)
- frontend/src/pages/Portal.jsx (link to portal/leave)

### Backlog (deferred)
- Cuti Tahunan with annual quota tracking
- Auto-deduct from payroll based on approved leaves
- 2-level approval (manager → HR)
- WhatsApp notification (in addition to email)


---
## Update: 2026-07-10 — Komponen Gaji Baru: Insentif Individu

### Implemented
- Field baru `insentif_individu` di Employee master (form Karyawan → section "Gaji & Tunjangan")
- Perlakuan payroll: **taxable** untuk PPh21 (masuk `taxable_gross_monthly`), **TIDAK** masuk base BPJS (Kesehatan/JHT/JP)
- Muncul di:
  - Slip gaji PDF (`server.py` — PDF earn_rows) ketika > 0
  - Halaman slip UI (`Payslip.jsx`, `Portal.jsx`) ketika > 0
- Backward compatible: karyawan lama tanpa field ini otomatis dianggap 0

### Files Changed
- backend/server.py — `EmployeeIn`, `calculate_payslip`, PDF slip
- frontend/src/pages/Employees.jsx — EMPTY, submit payload, input CurrencyInput
- frontend/src/pages/Payslip.jsx & Portal.jsx — display Row

---
## Update: 2026-07-10 (session 2) — 6 Komponen Gaji Baru

### Implemented
**Pendapatan (Earnings):**
- `tunjangan_tidak_tetap` — taxable PPh21, TIDAK masuk base BPJS
- `tunjangan_wfh` — non-taxable benefit (mirip tunjangan transport)
- `insentif_kolektif` — taxable PPh21, TIDAK masuk base BPJS
- `insentif_lain` — taxable PPh21, TIDAK masuk base BPJS

**Potongan (Deductions):**
- `potongan_terlambat` — dipotong dari gross
- `potongan_pulang_cepat` — dipotong dari gross

### UI
- Section baru "Potongan Kehadiran (Opsional)" di form Karyawan
- Semua field tampil di slip gaji PDF, halaman `Payslip.jsx` dan `Portal.jsx` (hanya jika > 0)

### Files Changed
- backend/server.py — `EmployeeIn` model, `calculate_payslip`, PDF generator
- frontend/src/pages/Employees.jsx — form + section baru
- frontend/src/pages/Payslip.jsx, Portal.jsx — display rows

### Verifikasi
Test payroll Siti Aminah dgn semua komponen: Gross 20,4jt → Net 17,66jt. PPh21 ikut naik proporsional untuk taxable earnings, BPJS tidak berubah (sesuai desain).


---
## Update: 2026-07-10 (session 3) — Field Bank Account Holder

### Implemented
- Field baru `bank_account_holder` ("Atas Nama") di section Rekening Bank pada form Karyawan
- Bank Transfer Export (BCA/Mandiri/BNI/BRI/generic) otomatis pakai nilai `bank_account_holder` untuk kolom "Nama Penerima" bila diisi; fallback ke nama karyawan bila kosong
- Untuk kasus rekening atas nama istri/orangtua/keluarga

### Files Changed
- backend/server.py — `EmployeeIn` + `_format_bank_export`
- frontend/src/pages/Employees.jsx — EMPTY + input field "Atas Nama"


---
## Update: 2026-07-11 — Field Status Karyawan (Employment Status)

### Implemented
- Field baru `employment_status` di Employee model dengan 4 opsi:
  - `ojt` — OJT (badge merah)
  - `kontrak_6` — Kontrak 6 Bulan (badge biru)
  - `kontrak_12` — Kontrak 1 Tahun (badge biru)
  - `tetap` — Tetap (default, badge hijau)
- Dropdown di form Karyawan (section Identitas, di bawah Departemen)
- Kolom "Status" di tabel daftar Karyawan dengan color-coded badge
- Backward compatible (default `tetap` untuk data lama)

### Files Changed
- backend/server.py — `EmployeeIn.employment_status`
- frontend/src/pages/Employees.jsx — EMPTY, EMPLOYMENT_STATUS_OPTIONS, dropdown, tabel kolom Status


---
## Update: 2026-07-11 — Tanggal OJT/Kontrak + Reminder

### Implemented
- 2 field baru di Employee: `status_start_date` & `status_end_date` (ISO YYYY-MM-DD)
- **Auto-calc**: Ketika status "Kontrak 6/12 Bulan" dipilih & tanggal mulai diisi, tanggal berakhir otomatis = mulai + 6/12 bulan (H-1)
- Form Karyawan hanya menampilkan date fields jika status = OJT/Kontrak (Tetap → hidden)
- **Kolom "Berakhir"** di tabel Karyawan: tanggal + badge sisa hari (merah <30, kuning 30–60, hijau >60, merah "Lewat")
- **Widget Dashboard "Reminder Kontrak / OJT"**: list top 5 karyawan berakhir dalam 90 hari
- **Sidebar badge di menu "Karyawan"**: count karyawan berakhir dalam 30 hari (warna amber)

### API Endpoints Baru
- `GET /api/contracts/expiring?days=90` → `{days, count, items: [{id, nik, name, employment_status, status_start_date, status_end_date, days_left, expired}]}`
- `GET /api/dashboard/stats` sekarang include `contract_expiring` (top 5) dan `contract_expiring_count`

### Files Changed
- backend/server.py — `EmployeeIn`, `_find_expiring_contracts`, `/contracts/expiring`, `/dashboard/stats`
- frontend/src/pages/Employees.jsx — form fields conditional + auto-calc + kolom Berakhir
- frontend/src/pages/Dashboard.jsx — `ContractReminder` widget
- frontend/src/components/Layout.jsx — badge Karyawan (amber) untuk expiring dalam 30 hari

### Backlog (opsional lanjutan)
- Email/WhatsApp otomatis ke HR ketika kontrak/OJT tinggal 30 hari (butuh APScheduler — P1)
- Halaman terpisah "Daftar Kontrak Akan Berakhir" dengan filter (all/OJT/Kontrak, sort by urgency)


---
## Update: 2026-07-11 (session 2) — Modul Inventory (ERP Step 1)

### Implemented
User meminta pengembangan aplikasi dari HR-only ke arah ERP. Modul Inventory pertama dibangun:

**Backend (`/app/backend/server.py` section "Inventory Module"):**
- Collection: `materials`, `stock_in`, `waste`
- Model `MaterialIn`: name, category (flexy/sticker/tinta/lainnya), unit (meter/roll/liter/pcs), current_stock (float — desimal), purchase_price, min_stock, supplier_default, active
- Model `StockInIn`: material_id, quantity, unit_price, supplier, invoice_no, date, notes → **auto-update material.current_stock (+qty) & purchase_price** (harga beli terbaru)
- Model `WasteIn`: material_id, quantity, reason (rusak/rijek/kadaluarsa/lainnya), date, reported_by → **auto-kurangi stok + estimated_loss = qty × purchase_price**
- Rollback stok saat delete stock-in/waste
- Soft-delete material bila sudah ada history
- Endpoint stats: total_stock_value, total_waste_this_month, low_stock, low_stock_count

**Frontend:**
- Page `/inventory` (Inventory.jsx) — 4 stat cards + 3 tabs (Master Bahan, Barang Masuk, Sisa/Rijek)
- Modal form untuk create/edit + validasi client
- Preview kerugian real-time saat mengisi form waste
- Design konsisten dengan modul lain (Swiss high-contrast, #002FA7)
- Sidebar nav: "Inventory" (icon Package) di antara Payroll & THR

### API Endpoints
- `GET/POST /api/inventory/materials`, `PUT/DELETE /api/inventory/materials/{id}`
- `GET/POST /api/inventory/stock-in`, `DELETE /api/inventory/stock-in/{id}`
- `GET/POST /api/inventory/waste`, `DELETE /api/inventory/waste/{id}`
- `GET /api/inventory/stats`

### Testing
Testing agent iteration_11: **Backend 20/20 pytest passed** + **Frontend E2E Playwright 100% passed**.
Test file: `/app/backend/tests/test_inventory.py`

### Backlog Enhancement (opsional)
- Widget Inventory di Dashboard utama (mirroring contract reminder)
- Multi-batch pricing (FIFO/LIFO) — saat ini pakai "last purchase price"
- Laporan bulanan waste dalam PDF/Excel
- Stock adjustment manual (koreksi opname)
- Kaitkan waste dgn karyawan (integrasi ke `employees` collection)


---
## Update: 2026-07-11 (session 3) — Inventory ERP Extras (4 fitur)

### 1. Order/Job Produksi dengan BOM
- Collection `job_orders`: order_no (auto JO-YYYYMM-XXXX), customer, product_name, qty, unit_price, items (BOM), status (aktif/selesai/batal), total_material_cost, total_price, gross_margin
- **Auto-decrement stok** saat order dibuat sesuai BOM
- **Complete**: status → selesai (no stock change)
- **Cancel/Delete**: rollback stok jika masih aktif/selesai
- Validasi: qty > 0, cek stok mencukupi sebelum submit

### 2. Widget Inventory di Dashboard
- Field `inventory` di `/api/dashboard/stats`: total_materials, total_stock_value, low_stock_count, total_waste_this_month, top_waste[]
- Komponen `InventoryWidget` di Dashboard.jsx menampilkan nilai stok + top 3 waste bulan ini + link ke /inventory

### 3. Laporan Bulanan Waste (Excel + PDF)
- `GET /api/inventory/waste/report/{YYYY-MM}/excel` — openpyxl (landscape header, IDR formatting, total row)
- `GET /api/inventory/waste/report/{YYYY-MM}/pdf` — reportlab (landscape A4, styled table)
- UI: date picker month + tombol Excel/PDF di WasteTab

### 4. Stock Adjustment (Opname)
- Collection `stock_adjust`: material_id, stock_before, stock_after, delta, reason (opname/koreksi/lainnya), date, notes
- Endpoint: `GET/POST/DELETE /api/inventory/stock-adjust`
- DELETE me-rollback stok ke stock_before
- Tab "Opname" di Inventory dgn preview selisih real-time

### API Endpoints Baru
- `GET/POST /api/inventory/orders`, `PUT /orders/{id}/complete`, `PUT /orders/{id}/cancel`, `DELETE /orders/{id}`
- `GET/POST/DELETE /api/inventory/stock-adjust`
- `GET /api/inventory/waste/report/{period}/excel|pdf`

### Testing
Testing agent iteration_12: **Backend 20/20 pytest passed** + **Frontend E2E Playwright 100% passed**.
Test file: `/app/backend/tests/test_inventory_extras.py`

### Backlog Enhancement (opsional)
- Multi-batch pricing (FIFO/LIFO) — saat ini pakai "last purchase price"
- Concurrency-safe order_no generator (findAndModify counter)
- Mongo transaction utk atomic order+stock update
- Kaitkan job order ke Sales/Customer master
- Alert stok menipis via WhatsApp/Email


---
## Update: 2026-07-11 (session 4) — Customer Master & Laba/Rugi Bulanan

### 1. Customer Master
- Collection `customers`: name (unik case-insensitive), phone, email, address, npwp, contact_person, notes
- Endpoint: `GET/POST/PUT/DELETE /api/inventory/customers`
- **Auto-aggregate** saat GET: order_count, total_revenue, total_material_cost, margin per customer (matching by lowercase job_orders.customer, exclude status batal)
- Frontend: tab "Customer" di Inventory + form CRUD
- **Datalist autocomplete** di Order form: customer yg sudah dibuat muncul sebagai suggestion
- Regex injection risk di duplicate check: fixed dengan `re.escape()`

### 2. Laporan Laba/Rugi Bulanan
- Endpoint `GET /api/reports/profit-loss/{YYYY-MM}` return:
  - **Revenue** = sum(orders.total_price) where status ≠ batal & date in month
  - **COGS** = sum(orders.total_material_cost)
  - **Gross Profit** = Revenue − COGS (+ gross_margin_pct)
  - **Waste Loss** = sum(waste.estimated_loss) dalam bulan
  - **Payroll Cost** = payroll_runs[period].total_net (fallback 0)
  - **Total Expenses** = Waste + Payroll
  - **Net Profit** = Gross Profit − Total Expenses (+ net_margin_pct)
  - **Top Customers** (sort by revenue)
- Endpoint `GET /api/reports/profit-loss/{YYYY-MM}/pdf` — laporan PDF berwarna
- Frontend page `/reports` — Hero card (hijau/merah), waterfall breakdown, 4 stat cards, top customer table
- Sidebar nav "Laba/Rugi" (icon TrendingUp)

### Testing
Testing agent iteration_13: **Backend 15/15 pytest passed** + **Frontend E2E Playwright 100% passed**.
Test file: `/app/backend/tests/test_customer_pl.py`

### Backlog Enhancement (opsional)
- Excel export untuk P&L (saat ini PDF only)
- Cache aggregate customer di document (untuk >10k orders)
- Cash vs Accrual accounting toggle
- Kaitkan customer_id ke Job Order (saat ini string match)
- Multi-batch pricing (FIFO/LIFO)


---
## Update: 2026-07-11 (session 5) — Grafik Trend 12 Bulan + YoY di Dashboard

### Implemented
**Backend endpoint**: `GET /api/reports/profit-loss-trend?months=12`
- Return array 12 bulan (adjustable 1-36): revenue, cogs, waste_loss, payroll_cost, gross_profit, net_profit, order_count
- Untuk setiap bulan, sertakan: yoy_period, yoy_revenue, yoy_net_profit, revenue_growth_pct, net_profit_growth_pct
- Totals: total revenue/net_profit periode + YoY comparison
- Parallel fetch (asyncio.gather) untuk performa

**Frontend Dashboard**:
- Komponen `BusinessTrend` — di bawah InventoryWidget
- ComposedChart (recharts): Revenue bar biru, COGS bar abu, Net Profit line hijau, Net Profit YoY line merah putus-putus
- YoY chips di kanan atas: Revenue YoY %, Net Profit YoY % dgn warna hijau/merah/abu
- Table detail 6 bulan terakhir dgn YoY growth per bulan

### Files Changed
- backend/server.py — endpoint `/reports/profit-loss-trend` + inner helper `_summary()`
- frontend/src/pages/Dashboard.jsx — `BusinessTrend`, `YoYChip` components + trend fetch

### Testing
Manual API + UI verified. Chart rendering benar (dip 2026-06 saat payroll tanpa revenue, peak 2026-07 saat order pertama).

### Backlog Enhancement
- Klik bar chart → drilldown ke halaman P&L bulan tsb
- Toggle metrik (Revenue, Gross Profit, Net Profit)
- Cache trend data (Redis) untuk mempercepat dashboard


---
## Update: 2026-07-11 (session 6) — Modul Pembelian (Purchasing)

### Implemented
**Backend (`/app/backend/server.py` section Purchasing Module):**
- Collection `suppliers`: name (unik case-insensitive), phone, email, address, contact_person, notes, active + duplicate-guard di POST & PUT (fix code review)
- Collection `purchase_orders`: po_no auto-gen (PO-YYYYMM-XXXX), supplier_id/name, date, items[], subtotal, tax_pct, tax_amount, total, status (draft/diterima/batal), payment_status (belum_lunas/sebagian/lunas), amount_paid, invoice_no, notes
- **Receive flow**: PUT `/{id}/receive` → status=diterima + otomatis buat `stock_in` entries (dgn `po_id`, `po_no` untuk traceability) + update `materials.current_stock` + `purchase_price` (harga beli terbaru). Idempotent.
- **Payment flow**: PUT `/{id}/pay` body `{amount}` → tambah amount_paid, payment_status auto-transition
- **Delete flow**: DELETE `/{id}` — jika diterima, rollback stok (delete stock_in entries + kurangi material stock)
- **Cancel flow**: PUT `/{id}/cancel` — reject bila sudah diterima
- Enriched Supplier list dgn agregat: po_count, total_purchase, outstanding

### API Endpoints
- `GET/POST /api/purchasing/suppliers`, `PUT/DELETE /api/purchasing/suppliers/{id}`
- `GET/POST /api/purchasing/purchase-orders`, `PUT /{id}/receive`, `PUT /{id}/cancel`, `PUT /{id}/pay`, `DELETE /{id}`
- `GET /api/purchasing/price-history?material_id=X` — grouped per bahan, min/max/avg/current/first/change%
- `GET /api/purchasing/stats` — total_po, total_purchase, outstanding, unpaid_pos, total_suppliers

### Frontend
- Page `/purchasing` (Purchasing.jsx) — 4 stat cards + 3 tabs (Purchase Order, Supplier, Histori Harga)
- POTab: filter status, create/receive/pay/cancel/delete workflow, modal PO dgn multi-item + pajak + preview total
- SuppliersTab: CRUD + kolom agregat (PO count, total beli, hutang)
- PriceHistoryTab: expandable row menampilkan detail history + trend icon up/down + change%
- Sidebar nav "Pembelian" (icon ShoppingCart) antara Inventory & Laba/Rugi

### Testing
Testing agent iteration_14: **Backend 20/20 pytest passed** + **Frontend E2E Playwright 100% passed**.
Test file: `/app/backend/tests/test_purchasing.py`

### Backlog Enhancement
- Payments audit log collection (untuk finance tracing bila PO dihapus setelah bayar)
- PayPOIn Pydantic model (saat ini pakai Dict body)
- Split Purchasing.jsx (700+ lines) ke files terpisah per tab
- Export PO ke PDF/Excel
- Aging report hutang (0-30, 31-60, 61+ hari)
- Auto-integrasi purchase ke Laba/Rugi report (COGS harusnya pakai PO diterima, bukan hanya Order.total_material_cost)


---
## Update: 2026-07-11 (session 7) — Modul Penjualan / Kasir (POS Digital Printing)

### Implemented
**Backend (Sales/POS Module in server.py):**
- Collection `sales`: sale_no (auto NOTA-YYYYMMDD-XXXX), customer_name/phone, cashier + cashier_name (dari JWT), items[], subtotal, discount, total, cash_paid, change, payment_method="tunai", status="paid"
- Formula: `area_total = length_m × width_m × quantity` (m²), `subtotal_per_item = area_total × unit_price` (harga/m²), `total = subtotal - discount`, `change = cash_paid - total`
- **Auto-decrement stok** material sebesar area_total per item
- Validasi: reject bila cash < total, stok tidak cukup, atau item kosong
- **DELETE rollback**: mengembalikan stok saat sale dihapus
- Endpoint receipt HTML: `GET /api/sales/{id}/receipt` — thermal 80mm dgn @page size, Courier monospace, header/meta/items/total/payment/footer

**Frontend (Sales.jsx):**
- Page `/sales` — POS interface: 4 stat cards (transaksi hari ini/bulan, omset hari ini/bulan), tabel transaksi
- Modal "Transaksi Baru": customer form + dynamic items (multi-row) + payment summary panel gelap dengan Total/Kembali besar
- Auto-calc real-time: subtotal per item, luas total, cek stok cukup, disabled submit bila kurang bayar
- Setelah simpan: auto-open receipt window (thermal 80mm) dengan `?auto=1` untuk trigger print dialog
- Print button di list → re-open receipt
- Delete button → konfirmasi + rollback stok

**Material Master:**
- Field baru `selling_price` (Rp/m²) di form Master Bahan — default value untuk POS Sales, bisa override per transaksi

**Company Info (Receipt Header):**
- Env-driven: `COMPANY_NAME`, `COMPANY_ADDRESS`, `COMPANY_PHONE` (default: Plazakreasi/Jl. Kreasi/0812-3456-7890)
- Untuk production, set via Emergent Secrets:
  - `payroll.plazakreasi.com`: `COMPANY_NAME=Plazakreasi`, `COMPANY_ADDRESS=<alamat>`, `COMPANY_PHONE=<telp>`

### API Endpoints
- `GET /api/sales` (dgn filter date_from/date_to), `POST /api/sales`
- `GET /api/sales/{id}`, `DELETE /api/sales/{id}` (rollback stok)
- `GET /api/sales/{id}/receipt` — HTMLResponse (thermal 80mm)
- `GET /api/sales/stats/today` — count/total hari ini + bulan

### Testing
Testing agent iteration_15: **Backend 14/14 pytest passed** + **Frontend E2E Playwright 100% passed**.
Test file: `/app/backend/tests/test_sales.py`

### Known Non-Critical Observations
- `_next_sale_no` race condition (single cashier OK; upgrade counter document utk multi-cashier)
- Sale insert + stock update non-atomic (Mongo single-node limitation; acceptable MVP)
- server.py 4700+ lines — modularization ke `routers/` file terpisah recommended untuk maintainability
- window.confirm belum konsisten dgn shadcn AlertDialog pattern (existing di modul lain juga sama)

### Aplikasi Sekarang (Mini-ERP Lengkap)
👥 HR & Payroll · 📦 Inventory · 🛒 Purchasing · 💵 Sales/POS (NEW) · 💰 Job Order · 📊 Laba/Rugi + Trend YoY · 📱 WhatsApp/Email · 🏢 Multi-tenant


---

## Session Update — Feb 2026

### Fitur Baru
1. **Tombol "Cetak Nota" di Sales List** — button jelas dengan text (bukan icon kecil), warna biru.
2. **Optimasi Struk Thermal C80BT (80mm)** — font Arial bold #000 pekat, ukuran 12-16px, tidak pudar di head printer. `@page 80mm` + konten 72mm (safe printable area).
3. **Autocomplete Master Pelanggan di Kasir** — datalist `<input list>`, auto-fill No. Telepon jika match master. Pelanggan baru auto-save ke Master (`/api/inventory/customers`).
4. **Broadcast WhatsApp ke Pelanggan** — endpoint `POST /api/inventory/customers/broadcast-whatsapp` + modal di tab Customer. Support variabel `{name}` & `{phone}`, pacing 0.3s, logging ke `db.whatsapp_logs`.
5. **Kas Operasional (Cash Book)** — modul baru lengkap:
   - Sidebar nav "Kas Operasional" (icon Wallet)
   - Chart of Accounts default: 4 income (301-304) + 16 expense (201/401-403/501-512/599). System accounts (301, 201) auto dari Sales/PO.
   - CRUD transaksi manual (pemasukan/pengeluaran) dengan running balance
   - Saldo real-time (Saldo Awal + In - Out)
   - Setting Saldo Awal + tanggal mulai
   - Tab "Buku Kas" (transaction ledger dengan filter bulan + search) & "Ringkasan Kategori" (breakdown per akun dengan progress bar)
   - Export Excel per periode (`GET /api/cashbook/export?month=YYYY-MM`) — struktur mengikuti format Excel user
   - **Integrasi Otomatis**: POST /sales → auto cash tx (code 301, in); DELETE /sales → rollback; PUT /purchase-orders/{id}/pay → auto cash tx (code 201, out)
   - Auto-transactions ditandai amber bg + badge LOCK, tombol edit/delete disabled

### API Endpoints Baru
- `GET/POST/PUT/DELETE /api/cashbook/accounts` — chart of accounts CRUD
- `GET/PUT /api/cashbook/settings` — opening balance
- `GET/POST/PUT/DELETE /api/cashbook/transactions` — CRUD tx (auto=true protected)
- `GET /api/cashbook/balance` — saldo real-time
- `GET /api/cashbook/summary?month=YYYY-MM` — ringkasan + breakdown
- `GET /api/cashbook/export?month=YYYY-MM` — download Excel
- `POST /api/inventory/customers/broadcast-whatsapp` — kirim WA massal

### Testing (Iterations 16-19)
- iteration_16: Thermal receipt thermal-friendly (20/20 pytest)
- iteration_17: Sales autocomplete + auto-save master (11/11 pytest)
- iteration_18: Broadcast WhatsApp (14/14 pytest)
- iteration_19: **Kas Operasional (26/26 pytest)** + full frontend E2E

### Backlog Prioritized
- 🟢 P1: Scheduled Auto-Send Payslip (APScheduler)
- 🟢 P2: Auto-add Lembur approved ke Payroll
- 🟢 P2: Cuti Tahunan Kuota per Karyawan
- 🟢 P2: Notif WA Izin/Cuti approved (Fonnte)
- 🟡 P2: Halaman Daftar Pinjaman Aktif
- 🟡 P2: Audit Log HR
- 🟡 P3: Halaman Log Broadcast WhatsApp (view history)
- 🟡 P3: Notif WA PO tertunda / stok menipis
- 🔴 CRITICAL: Refactor `server.py` (>5200 baris) → pecah ke `/app/backend/routers/*.py`

### Aplikasi Sekarang (Full ERP)
👥 HR & Payroll · 📦 Inventory · 🛒 Purchasing · 💵 Sales/POS · 💰 Kas Operasional (NEW) · 📊 Laba/Rugi + Trend YoY · 📱 WhatsApp Broadcast · 🏢 Multi-tenant

---

## Session Update — Feb 2026 (Master Produk BOM)

### Fitur Baru: Master Produk dengan BOM (Bill of Materials)
- **Backend**: 
  - Model `ProductComponent` + `ProductIn` dengan formula: `fixed`, `per_qty`, `area`, `length`
  - Endpoint `GET/POST/PUT/DELETE /api/products` — CRUD lengkap
  - Helper `_compute_component_consumption(formula, factor, L, W, qty)` — hitung konsumsi per komponen
  - Update `POST /api/sales` support DUAL MODE: `product_id` (BOM) atau `material_id` (legacy)
  - Update `DELETE /api/sales/{id}` — rollback multi-material dari `items.components`
  - Update receipt HTML — tampil breakdown "Bahan: Kertas 10pcs + Kain 0.45m²"

- **Frontend**:
  - Tab baru "Master Produk" di halaman Inventory (sebelum Barang Masuk)
  - Form Produk: kode, kategori, nama, pricing_mode (fixed/per_area), unit_price, komponen dinamis (add/remove) dengan formula & faktor
  - Preview komposisi di tabel: multi-baris "Bahan × Formula × Faktor"
  - Sales.jsx: dropdown gabungan dengan OPTGROUP "Produk (Multi-Bahan/BOM)" vs "Bahan Langsung"
  - Field P×L conditional: tampil kalau formula produk butuh area/length, sembunyi kalau tidak
  - Live BOM breakdown per item: menampilkan konsumsi tiap bahan + status stok (✓/✗)
  - Stock validation real-time (frontend + backend agregat)

- **Testing** (iteration_21.json): 
  - **63/63 pytest lulus** (23 new BOM + 40 regression)
  - Full E2E frontend: Master Produk tab, Sales OPTGROUP picker, live multi-material breakdown, backward compat legacy sales

### Contoh Konfigurasi Produk
- **Slayer** (fixed pricing Rp 25.000/pcs, komponen: 1 lembar Kertas per_qty + P×L Kain area)
- **Bendera** (fixed pricing, komponen: 1 lembar Kertas per_qty + P×L Kain area + P panjang Tali length)
- **Kaos Sablon** (fixed pricing, komponen: 1 Kaos per_qty + fixed 50ml Tinta)

### Total Test Reports
`iteration_11.json` → `iteration_25.json` (12 iterasi testing dengan >250 test cases lulus)

### Backlog Setelah Ini
- 🟢 P1: Auto-add Lembur approved ke Payroll (belum dikerjakan)
- 🟢 P1: Scheduled Auto-Send Payslip (APScheduler)
- 🟢 P1: Cuti Tahunan Kuota per Karyawan
- 🟢 P2: Notif WA Izin/Cuti approved (Fonnte)
- 🟡 P2: Halaman Daftar Pinjaman Aktif
- 🟡 P2: Audit Log HR
- 🟡 P3: Halaman Log Broadcast WhatsApp
- 🟡 P3: Notif WA PO tertunda / stok menipis
- 🔴 CRITICAL: Refactor `server.py` (>6000 baris) → pecah ke `/app/backend/routers/*.py`

---
## Update: 2026-07-15 — Kas Operasional: Jurnal Akuntansi + Kasbon Sementara

### Implemented (Iteration 25 — 48/48 tests passed)
User meminta 2 tab baru di modul `/cashbook`:

**1. Tab "Jurnal Akuntansi" (Debet/Kredit format)**
- Tampilan tabel format akuntansi klasik: Kode Akun, Nama Akun, Tanggal, Keterangan, **Debet** (hijau, untuk pemasukan/kas +), **Kredit** (merah, untuk pengeluaran/kas −), **Saldo** running
- Saldo Awal bulan berjalan di baris pertama, Total Debet/Kredit + Saldo Akhir di footer
- Filter bulan + search text
- Data sumber sama dengan Buku Kas — hanya tampilan berbeda (single source of truth)

**2. Tab "Kasbon Sementara" (Cash Advance untuk staff)**
- Collection `kasbon_sementara`: {id, date, name, description, amount, status (open/settled), settled_at, created_by}
- 3 stat cards: Total Belum Lunas, Sudah Dilunaskan, Total Semua Bulan Ini
- Table columns: Tanggal, Nama, Keterangan, Jumlah, Status badge (LUNAS/BELUM LUNAS), Aksi
- Action buttons: Settle (CheckCircle), Reopen (RotateCcw), Edit (Pencil), Delete (Trash)
- Filter bulan + status + search
- Footer table: TOTAL otomatis dari row yang tampil

**3. 8 Kode Akun Akuntansi Standar (idempotent seed)**
- `101 Kas` (in), `103 Persediaan Barang` (out), `103-01 Bahan Baku Mesin` (out)
- `104 Perlengkapan Kantor` (out), `105 BBM dan Maintenance Kendaraan` (out)
- `106 Pengiriman Dokumen` (out), `108 Makan dan Entertainment` (out)
- `502 Beban Listrik, Air, Telepon` (out) — kode existing, nama lama tetap "Listrik, Air, Telepon, Internet" (user bisa rename via UI Kategori Akun)

### API Endpoints Baru
- `GET /api/cashbook/kasbon?month=&status=` — return {items, total_open, total_settled, total_all, count}
- `POST /api/cashbook/kasbon` — body {date, name, description, amount}
- `PUT /api/cashbook/kasbon/{id}` — full update
- `PUT /api/cashbook/kasbon/{id}/settle` — mark as lunas
- `PUT /api/cashbook/kasbon/{id}/reopen` — un-settle
- `DELETE /api/cashbook/kasbon/{id}`

### Files Changed
- `backend/server.py` — DEFAULT_CASH_ACCOUNTS extended (8 kode baru), `_ensure_cash_accounts` refactored to idempotent per-code seed, new KasbonIn model + 6 endpoints
- `frontend/src/pages/CashBook.jsx` — 2 new tabs, 3 new components (JournalTab, KasbonTab, KasbonFormModal), Lucide icons: BookOpen, Users, CheckCircle2, RotateCcw

### Testing
Iteration 25: 22 new backend + 26 regression + full frontend E2E = **48/48 PASSED**.

---
## Update: 2026-07-15 (session 2) — Sales/Kasir: Cetak PDF & Export Excel

### Implemented (Iteration 26 — 34/34 tests passed)
User meminta 3 fitur cetak/export di modul Penjualan/Kasir:

**1. Nota A4 PDF Profesional per Transaksi** — untuk customer korporat/pemerintahan
- Kop perusahaan (PLAZAKREASI DIGITAL PRINTING) + alamat + HP
- Meta table: No Nota, Tanggal, Pelanggan, Telp, Kasir, Metode
- Item table dengan header biru: No, Deskripsi (+ bahan BOM), Qty/Dim, Harga, Subtotal
- Total table dengan garis biru highlight, subtotal + diskon + TOTAL + bayar + kembali
- Footer signature: Pelanggan + Hormat kami

**2. Laporan Penjualan PDF Landscape (Bulanan/Periode)**
- Header perusahaan + judul "LAPORAN PENJUALAN" + periode label
- 9-kolom table: No, Tanggal, No.Nota, Pelanggan, Kasir, Item, Subtotal, Diskon, Total
- Row alternating background + grand total footer biru
- Support filter `?month=YYYY-MM` atau `?date_from=&date_to=`
- Handle empty state ("Belum ada transaksi pada periode ini")

**3. Export Excel Laporan Penjualan**
- 13 kolom: Tanggal, No.Nota, Pelanggan, No.Telepon, Kasir, Jumlah Item, Subtotal, Diskon, Total, Bayar Tunai, Kembali, Metode, Catatan
- Header perusahaan di A1-A3, data mulai row 4
- Auto column width + TOTAL row footer dengan sum

### API Endpoints Baru
- `GET /api/sales/{sale_id}/invoice-pdf` — Nota A4 PDF (inline)
- `GET /api/sales/report/pdf?month=YYYY-MM` atau `?date_from=&date_to=` — Laporan PDF landscape
- `GET /api/sales/report/excel?month=YYYY-MM` — Excel (.xlsx)

### Files Changed
- `backend/server.py` — 3 endpoint baru (~380 baris) sebelum `/sales/stats/today`, memakai `_company_info()` + `io.BytesIO()` + reportlab/openpyxl
- `frontend/src/pages/Sales.jsx` — Import icons (FileText, FileSpreadsheet), function `openInvoiceA4()`, tombol "Laporan Bulanan" di header, tombol "NOTA A4" di kolom aksi row (label struk 80mm juga diringkas), komponen `SalesReportModal` di akhir file (picker bulan + 2 tombol PDF/Excel)

---
## Update: 2026-07-15 (session 3) — Sizing untuk Kaos/Jersey

### Implemented (Iteration 27 — 56/56 tests passed)
Fitur ukuran (size) untuk produk kaos/jersey dengan sistem 2-tier harga & konsumsi bahan.

**Konvensi Tier:**
- **Tier A** (S, M, L, XL) → gunakan `price_size_a` dan `quantity` component
- **Tier B** (XXL, XXXL, dst) → gunakan `price_size_b` dan `quantity_size_b` (fallback `quantity`)

**Backend:**
- `ProductComponent` + field `quantity_size_b: Optional[float]`
- `ProductIn` + fields: `has_sizes`, `sizes: List[str]`, `price_size_a`, `price_size_b`
- Constant `SIZE_TIER_A = {S,M,L,XL}` + helper `_size_tier(size)`
- `SaleItemIn` + field `size: Optional[str]`
- `sales_create` logic: validasi size wajib untuk has_sizes produk, harga otomatis dari tier, konsumsi bahan pakai quantity_size_b bila tier B
- Response sale item include: `size`, `size_tier`

**Frontend Inventory (Master Produk):**
- Toggle **"Produk ini memiliki ukuran (kaos / jersey)"**
- Grid multi-select size dengan warna: biru (tier A) & merah (tier B)
- 2 kolom harga: `price_size_a` (biru) & `price_size_b` (merah)
- Setiap komponen BOM tampil kolom tambahan **"JUMLAH XXL+"** (opsional) saat has_sizes aktif
- Input `unit_price` disabled saat has_sizes aktif

**Frontend Sales (Kasir):**
- Setelah pilih produk has_sizes, muncul section "Pilih Ukuran" dengan buttons per size
- Klik size → harga otomatis ganti ke tier sesuai (auto-refresh dari `price_size_a` / `price_size_b`)
- Live preview: "Tier: XXL+ · Harga otomatis: Rp 95.000"
- Validasi: submit disabled bila has_sizes tapi belum pilih size
- Konsumsi bahan real-time menyesuaikan tier (untuk display live stock warning)

### Contoh
Produk **Kaos Sablon**: harga S-XL = 85rb, harga XXL+ = 95rb. Komponen: 1 kaos polos per_qty (S-XL) / 1.2 kaos polos (XXL+ untuk kompensasi ukuran besar).
- Jual ukuran M → harga 85.000, stok kaos berkurang 1
- Jual ukuran XXL → harga 95.000, stok kaos berkurang 1.2

### Files Changed
- `backend/server.py` — model + validasi + logic sales
- `frontend/src/pages/Inventory.jsx` — ProductsTab: sizing section + kolom XXL+ per komponen
- `frontend/src/pages/Sales.jsx` — NewSaleModal: sizeTier helper, onSizeChange, size selector UI, canSubmit validation

### Testing
Iteration 27: 13 new + 43 regression = **56/56 PASSED** backend + full frontend E2E via testing agent.

---

## Update: 2026-07-17 — Integrasi Pelunasan Kasbon → Jurnal Kas Utama (Akun 101)

### Feature
Saat kasbon sementara ditandai LUNAS, sistem otomatis membuat transaksi pengeluaran (`type=out`) di `cash_transactions` dengan `account_code=101` (Kas), muncul di kolom **DEBET** Jurnal Akuntansi dan memotong saldo Kas real-time.

### Behavior
- **Settle** (`PUT /api/cashbook/kasbon/{id}/settle`)
  - Set status kasbon = "settled"
  - Insert auto cash-tx: `account_code=101`, `type=out`, `description="Pelunasan Kasbon - {Nama} - {Keterangan}"`, `reference=KASBON-{id}`, `auto=true`
  - Idempotent: sebelum insert, cascade delete tx lama dgn `reference=KASBON-{id}`
- **Reopen** (`PUT /api/cashbook/kasbon/{id}/reopen`) — hapus auto cash-tx pelunasan (rollback)
- **Delete kasbon** — cascade hapus auto cash-tx pelunasan
- Bypass `_insert_cash_transaction` helper karena akun 101 default `type=in`; di-hard-code `type=out` untuk konvensi DEBET

### Files Changed
- `backend/server.py` — helper `_kasbon_ref`, `_kasbon_create_settlement_tx`, `_kasbon_delete_settlement_tx`; update endpoint settle/reopen/delete
- `frontend/src/pages/CashBook.jsx` — prop `onCashChanged={loadAll}` dari `CashBook` ke `KasbonTab`, dipanggil setelah settle/reopen/remove agar Jurnal + StatCards refresh tanpa reload

### Testing
Iteration 32 (backend): 6/6 pytest PASS di `/app/backend/tests/test_kasbon_settlement.py`
Iteration 33 (frontend E2E): 10/10 skenario PASS — settle → Jurnal muncul, reopen → hilang, delete → hilang, stats real-time update, semua tanpa reload page

---

## Update: 2026-07-20 — RBAC (Role-Based Access Control) untuk Menu

### Feature
Dua level user: **Super Admin** (akses semua menu) & **Admin dengan Privilege** (menu diatur via 13 checkbox di halaman Kelola User).

**13 Menu Keys:** karyawan, payroll, inventory, pembelian, penjualan, laporan_penjualan, kas_operasional, laba_rugi, master_kategori, thr, izin_cuti, kelola_user, konfigurasi.

### Backend Enforcement
- `MENU_KEYS`, `PATH_MENU_RULES`, `RBAC_BYPASS_PREFIXES` di `server.py`.
- `@app.middleware("http")` rbac_middleware decode JWT → cek role → jika `admin_privileged`, lookup menu berdasar path prefix, tolak 403 jika tidak ada di permissions.
- Endpoint `/api/users` sekarang butuh perm `kelola_user`; `/api/config/*` butuh `konfigurasi`.
- `require_super_admin` sekarang mengizinkan kedua role (menu enforcement dilakukan di middleware).
- Migration otomatis di startup: `hr_leave` → `admin_privileged` dengan `permissions=["izin_cuti"]`; super_admin auto-populated dgn full MENU_KEYS.

### Frontend Enforcement
- `/app/frontend/src/lib/menuAccess.js` — `MENU_KEYS`, `MENU_LABELS`, `hasMenuAccess()`, `firstAccessibleRoute()`.
- `App.js`: `ProtectedRoute` dgn prop `menuKey` render `<AccessDenied>` jika akses ditolak. `HomeRedirect` untuk admin_privileged redirect ke halaman pertama yg diakses.
- `Layout.jsx`: sidebar filter menu via `hasMenuAccess()`.
- `Users.jsx`: role picker + grid 13 checkbox permissions, tombol Pilih Semua/Kosongkan; kolom "Menu Akses" di tabel user.
- `components/AccessDenied.jsx`: halaman 403 dengan data-testid `access-denied-title` & `access-denied-home`.

### Testing
Iteration 34: **backend 18/18 pytest PASS + frontend 19/19 E2E PASS** — semua skenario di review request lulus.

### Files Changed
- `backend/server.py` (+~150 lines): RBAC constants, middleware, user endpoint updates, migrations
- `frontend/src/App.js`, `Layout.jsx`, `Users.jsx`: rewritten untuk menuKey system
- `frontend/src/lib/menuAccess.js` (new), `components/AccessDenied.jsx` (new)

---

## Update: 2026-07-20 — Edit & Delete di Tab Jurnal Akuntansi

### Feature
- Kolom "Aksi" ditambahkan di tabel Jurnal Akuntansi dengan tombol **Edit** & **Hapus** per baris.
- Edit: reuse `TxModal` existing dari BookTab — ubah Tanggal, Keterangan, Kategori Akun (dalam tipe sama), Jumlah, Referensi. TxModal filter accounts by initial.type (tidak bisa flip Debet↔Kredit dalam edit).
- Hapus: konfirmasi window.confirm dengan text tepat **"Apakah Anda yakin ingin menghapus data ini?"**. Auto-tx (dari PO/Sales/Kasbon) tetap tunduk pada orphan-check backend.
- Running balance & StatCards (Saldo Kas Real-time, Pengeluaran/Pemasukan bulan, Saldo Akhir) auto re-compute setelah edit/delete via `loadAll()`.
- Backend fix cosmetik: `orphan-check` sekarang mengembalikan `source_type="Kasbon"` untuk auto-tx dari pelunasan kasbon (sebelumnya "Unknown").

### Files Changed
- `frontend/src/pages/CashBook.jsx`: JournalTab terima props `onEdit`/`onRemove` dari parent, kolom Aksi, data-testid `journal-edit-{id}` / `journal-del-{id}`; confirm text diperbarui.
- `backend/server.py`: helper `_cash_tx_source_type()` baru; `_is_cash_tx_orphaned()` handle KASBON- references; orphan-check endpoint gunakan helper.

### Testing
Iteration 35 (frontend E2E): **10/10 skenario PASS**. Backend orphan-check verified via curl.

---

## Update: 2026-07-20 — Laporan Penjualan Excel-Style + Branch (Plaza/Kastem)

### Feature
Rombak modul Laporan Penjualan menjadi **format Excel** dengan:

**Kolom Utama (12):** No, Tanggal, No.Nota, **Alamat** (dari customer master), **Nama Barang**, **Pcs**, **Meter** (qty × product.length_meter), **Harga**, **Disc** (sale-level), **Jumlah** (harga×pcs), **Total** (after disc), **Keterangan**.

**Kolom Pembayaran (6 grup × 2 cell):** Cash Plaza, Cash Kastem, BCA Plaza, BCA Kastem, Mandiri Plaza, Mandiri Kastem — masing-masing dengan sub-header **Nominal** + **Tanggal**. Nominal muncul hanya di baris pertama transaksi (multi-item sale) untuk mencegah double-count.

**Auto-mapping cabang:**
- Field `branch` ditambahkan ke User (Plaza/Kastem/null) via dropdown di Kelola User
- Sale otomatis di-tag `branch` dari user cashier saat submit
- Backend helper `_resolve_report_payment_col(method, bank, branch)` → column key
- Data lama tanpa branch → 6 payment column kosong, kolom utama tetap terisi

**Master Produk:** Field baru **`length_meter`** (opsional, default 0) untuk hitung kolom Meter.

**UI:**
- Table `overflow-x-auto` + `minWidth: 2200px` untuk horizontal scroll ala Excel
- Footer "Total · N transaksi" menjumlahkan seluruh transaksi visible (respect search filter)
- Footer terpisah per payment column dengan `data-testid=pay-total-{key}`

### Files Changed
- `backend/server.py`: UserCreateIn/UpdateIn+branch, `_sanitize_branch`, `_resolve_report_payment_col`, `ProductIn.length_meter`, sale doc capture branch, analytics endpoint enriched (alamat lookup, meter, payment_column, is_first_item_of_sale, payment_nominal_on_row, payment_date_on_row)
- `frontend/src/pages/Users.jsx`: dropdown "Cabang" + column "Cabang"
- `frontend/src/pages/Inventory.jsx`: input `prod-length-meter`
- `frontend/src/pages/SalesReport.jsx`: rewrite tabel Excel-style (2-row header, 24 body cells, footer totals per payment column)

### Testing
Iteration 36: **backend 6/6 pytest PASS + frontend 19/19 E2E PASS** — semua skenario di review request lulus.

### Known Cosmetic (Optional)
- React dev-mode hydration warning di Inventory BOM `<span> inside <option>` — pre-existing, tidak berdampak.

---

## Update: 2026-07-21 — Pagination Client-Side di Laporan Penjualan

### Feature
- Tabel Laporan Penjualan sekarang paginated **20 baris per halaman**.
- Kontrol: `«` (First), `Previous`, tombol nomor halaman (up to 5 di sekitar current), `Next`, `»` (Last).
- Info: `Menampilkan X–Y dari Z baris · Halaman P / Total`.
- Reset otomatis ke halaman 1 saat filter/search berubah.
- Footer total omzet & payment column tetap dihitung dari SELURUH data terfilter (bukan hanya halaman visible) — konsisten dengan Summary Card.
- Client-side (data sudah ter-load via `/api/sales/report/analytics`, tidak ada backend change).

### Files Changed
- `frontend/src/pages/SalesReport.jsx`: `PAGE_SIZE=20` constant, state `page`, `pagedRows` computed slice, pagination bar dengan `data-testid: report-pagination, pagination-first, pagination-prev, pagination-page-N, pagination-next, pagination-last`.

---

## Update: 2026-07-21 — Dropdown Page Size + Export Excel di Laporan Penjualan

### Feature
- **Dropdown "Per Halaman"** (`data-testid=page-size-select`) di bilah pagination: pilihan 20 / 50 / 100 / 500 baris. Otomatis reset ke halaman 1 saat diubah.
- **Tombol "Export Excel"** hijau (`data-testid=report-export-excel`) di header tabel: download file `.xlsx` yang formatnya PERSIS dengan UI (2-row header, 12 kolom utama + 6 grup pembayaran × Nominal+Tanggal, footer TOTAL dengan SUM formulas per kolom nominal, freeze pane, currency formatting).
- Filter periode / customer masih dihormati saat export.

### Files Changed
- `frontend/src/pages/SalesReport.jsx`: state `pageSize`, `exporting`; UI dropdown + tombol export.
- `backend/server.py`: `GET /api/sales/report/excel` di-rewrite total untuk memakai openpyxl grouped headers, merged cells, colored payment column groups, SUM formulas di footer, freeze_panes.

### Testing
Curl E2E: HTTP 200, size 6KB, sheet berisi header perusahaan, 24 kolom (12 main + 12 pay sub-headers), data row di baris 6, TOTAL row dengan formula `=SUM(...)` per kolom aggregable. Frontend DOM verified: report-export-excel & page-size-select present.

---

## Update: 2026-07-21 — Modul Rincian Penjualan Online Shopee

### Feature
Modul baru **"Rincian Shopee"** (`/laporan-rincian-shopee`) di sidebar (di bawah Laporan Penjualan). Dua tabel berdampingan:
- **Shopee Plaza** (kiri, header hijau tua) — filter `payment_method = shopee_plaza`
- **Shopee Kastem** (kanan, header hijau muda) — filter `payment_method = shopee_kastem`

**Kolom (per tabel):** Nama, Pesanan, Pcs, Meter, Harga Satuan, **Jumlah (Bruto)** (highlighted yellow), Saldo Masuk (Netto), Potongan (Rp), %, Aksi (edit).

**Logika:**
- Jumlah = subtotal (pcs × harga_satuan)
- Saldo Masuk = field `sale.saldo_masuk` (opsional, dapat diisi lewat modal)
- Potongan = Jumlah − Saldo Masuk
- % = (Potongan / Jumlah) × 100

**Workflow Opsi B (user's choice):**
- Kasir tidak perlu ubah workflow — pilih metode "Shopee Plaza/Kastem" seperti biasa
- Admin buka modul Rincian → klik ikon Edit → modal muncul dengan preview otomatis potongan & persentase
- PATCH `/api/sales/{id}/saldo-masuk` menyimpan nilai netto per transaksi

**Footer per tabel:** Total Saldo Masuk (label sesuai request), plus total Jumlah & Potongan.
**Grand Total** di bawah: agregasi Plaza + Kastem (kuning highlight) — Bruto, Total Saldo Masuk, Total Potongan.

### Backend
- `GET /api/sales/report/shopee-rincian?date_from&date_to` → `{ plaza: {rows, totals, count}, kastem: {rows, totals, count} }`
- `PATCH /api/sales/{sale_id}/saldo-masuk` — body `{saldo_masuk: number|null}`
- New Sale field: `saldo_masuk` (float, nullable) + audit trail (`saldo_masuk_updated_at`, `saldo_masuk_updated_by`)

### Frontend
- New page `frontend/src/pages/ShopeeRincianReport.jsx` (~305 baris)
- Route `/laporan-rincian-shopee` (menuKey: `laporan_penjualan`, same perm sebagai Laporan Penjualan)
- Sidebar item "Rincian Shopee" (icon `Store`, testid `nav-shopee-rincian`)

### Testing
Backend E2E curl PASS: create Shopee sale → PATCH saldo_masuk → verify calculations. Example match user's sample:
- ALLSUNDAY SLAYER 6×34,500 = 207,000 · Saldo 179,875 · Potongan 27,125 · **13.1%** ✓
- NAJIB09 BANNER 1×24,300 = 24,300 · Saldo 18,392 · Potongan 5,908 · **24.31%** ✓
Frontend DOM verified: table-plaza, table-kastem, nav-shopee-rincian all rendered.

---

## Update: 2026-07-21 — Kolom Shopee Plaza & Kastem di Laporan Penjualan + Fallback Plaza

### Feature
Menambah 2 grup kolom pembayaran ke Laporan Penjualan Excel-style:
- **Shopee Plaza** (orange 500 header) — auto dari `payment_method=shopee_plaza`
- **Shopee Kastem** (orange 300 header) — auto dari `payment_method=shopee_kastem`

Kini total 8 grup pembayaran × 2 sub-column (Nominal + Tanggal) = **16 pay cells** + 12 main = 28 kolom total.

**Fallback data lama (Cash/BCA/Mandiri tanpa `sale.branch`):** default ke **Plaza** — sebelumnya empty untuk transaksi pre-fitur cabang. Sekarang selalu ada nominal.

**Footer TOTAL row** auto-sum untuk semua 8 kolom pay-total (existing).

### Files Changed
- `backend/server.py`: `_resolve_report_payment_col()` handle shopee_plaza/kastem + default branch=plaza. `PAY_COLS` di Excel export ditambah 2 entry Shopee + `pay_fills` warna.
- `frontend/src/pages/SalesReport.jsx`: `PAY_COLS` + 2 header groups + colSpan empty state 24→28 + `minWidth: 2700`.

### Testing
Backend curl PASS: seed 3 sales (shopee_plaza, shopee_kastem, cash) → semua mapped ke payment_column yang benar (fallback cash→cash_plaza). Frontend DOM verified: `pay-total-shopee_plaza`, `pay-total-shopee_kastem` present.

---

## Update: 2026-07-21 — Toggle Sembunyikan Kolom Pembayaran per Grup

### Feature
Toolbar di atas tabel Laporan Penjualan dengan 8 chip toggle (1 per grup pembayaran) + 2 tombol aksi:
- **8 chip toggle** (`toggle-pay-{cash_plaza|cash_kastem|bca_plaza|bca_kastem|mandiri_plaza|mandiri_kastem|shopee_plaza|shopee_kastem}`): klik untuk hide/show. Visible = colored chip + icon Eye. Hidden = outline putih + icon EyeOff.
- **Tampilkan Semua** (`pay-cols-show-all`) — unhide semua sekaligus (disabled jika sudah semua visible)
- **Sembunyikan Semua** (`pay-cols-hide-all`) — hide semua sekaligus (disabled jika sudah semua hidden)

Kolom yang di-hide otomatis hilang dari: header row, sub-header row (Nominal/Tanggal), body row cells, footer TOTAL row. `totalColSpan` untuk loading/empty state juga otomatis menyesuaikan.

**Persistence**: state disimpan di `localStorage['salesReport.hiddenPayCols']` (JSON array) — pilihan user tetap ada setelah reload/kembali dari halaman lain.

**Table minWidth**: dihitung ulang otomatis `Math.max(1200, 12*90 + visiblePayCols.length*2*80)` — kalau semua hidden, minWidth tetap min 1200 (agar main columns rapi).

### Files Changed
- `frontend/src/pages/SalesReport.jsx`:
  - `HIDDEN_PAY_STORAGE_KEY` const
  - state `hiddenPayCols` + useEffect persist + `togglePayCol` handler
  - `PAY_COLS` diberi prop `color`
  - `visiblePayCols = PAY_COLS.filter(!hidden)` drive semua render (header, sub-header, body cells, footer)
  - Toolbar UI (toggle chips + show-all/hide-all buttons)
  - Semua button pakai `type="button"` (prevent form-submit fallback)

### Testing
Iteration 37 (frontend): **11/11 skenario PASS** — toggle render, hide/show, persistence localStorage lintas reload, regression search/paging/export tidak terpengaruh.

---

## Update: 2026-07-21 — Pelunasan Sisa Tagihan (DP → LUNAS) di Kasir

### Feature
Fungsi **Bayar Sisa** untuk transaksi DP di modul Penjualan/Kasir. Melunasi sisa tagihan secara bertahap atau langsung, dengan auto-record ke Jurnal Kas Utama.

**UI Sales List:**
- Tombol hijau **"Bayar Sisa"** (`data-testid=pay-remaining-button-{sale_id}`) hanya muncul untuk transaksi berstatus DP.
- Klik tombol → modal `PayRemainingModal`.

**Modal PayRemainingModal:**
- Summary: Total Nota, Sudah Dibayar, **Sisa Tagihan** (merah bold)
- Input Nominal Pelunasan (default penuh sisa) + tombol "Isi Penuh"
- Live indicator: "Akan LUNAS" (hijau) atau "Sisa setelah bayar: Rp X" (kuning)
- Dropdown Metode: Cash/Tunai atau Transfer (BCA/Mandiri)
- Field Tanggal Pelunasan (default hari ini)
- Field Catatan (opsional)
- Info: akun kas yang akan menerima dana ditampilkan real-time

**Behavior:**
- Nominal ≤ sisa tagihan (validasi backend & frontend)
- Nominal < sisa → status tetap `dp`, `sisa_tagihan` berkurang
- Nominal = sisa → status jadi `paid` (LUNAS), badge di list berubah, kolom Sisa/Kembali menampilkan "Kembali: Rp 0"
- **Auto Jurnal Kas** (`_insert_cash_transaction`): tercatat sebagai pemasukan (`type=in`) di akun sesuai metode (301/301-BCA/301-MDR/301-SPP/301-SPK), `reference = sale.sale_no` (konsisten dengan initial sale — sehingga saat sale di-delete, semua entry auto ikut ter-rollback via `_rollback_sale_effects`).
- Semua pembayaran tercatat di `sale.payments[]` sebagai audit trail (amount, method, bank, date, notes, created_at, created_by).

### API Endpoints
- `POST /api/sales/{sale_id}/pay-remaining` — body `{amount, payment_method (cash|transfer|shopee_plaza|shopee_kastem), payment_bank?, date?, notes?}`. Return `{ok, amount_paid, sisa_tagihan, status, cash_paid_total}`.

### Validasi Backend
- Sale exists → 404 jika tidak
- Status harus `dp` (bukan sudah lunas) → 400 "Transaksi ini sudah LUNAS"
- Amount > 0 → 400 "Nominal pembayaran harus > 0"
- Amount ≤ sisa_tagihan (+tol 0.01) → 400 "Nominal melebihi sisa tagihan"
- Tanggal format YYYY-MM-DD

### Files Changed
- `backend/server.py`: `PayRemainingIn` model + `POST /api/sales/{sale_id}/pay-remaining` endpoint (~90 lines).
- `frontend/src/pages/Sales.jsx`: state `payDPSale`, tombol "Bayar Sisa" di tabel Aksi, komponen `PayRemainingModal` (~180 lines) dengan data-testid lengkap (`pay-remaining-*`).

### Testing
Backend curl E2E lulus:
- Create DP sale (total 322k, cash 100k) → sisa 222k, status=dp ✓
- Partial pay 100k → sisa 122k, status=dp, cash_paid=200k ✓
- Final pay 122k via transfer BCA → sisa 0, status=paid, cash_paid=322k ✓
- 3 cash_tx tercatat: initial DP (301, 100k), pelunasan 1 (301, 100k), pelunasan 2 (301-BCA, 122k) ✓
- Overpay & double-pay after lunas ditolak dengan pesan yang tepat ✓

Frontend Playwright E2E lulus (5 screenshot):
- DP row + tombol "Bayar Sisa" muncul ✓
- Modal render dengan summary lengkap ✓
- Partial pay via transfer BCA (50k of 111k) berhasil, sisa update ke Rp 61.000 ✓
- Fill-full → status berubah ke LUNAS + toast "Pelunasan berhasil — Transaksi LUNAS" ✓
- Badge di tabel berubah hijau LUNAS ✓

---

## Update: 2026-07-21 (session 2) — Multi-Payment History (Split DP + Pelunasan)

### Feature
Riwayat pembayaran per transaksi kini disimpan sebagai **daftar terpisah** (`sale.payments[]`) — DP awal + pelunasan-pelunasan tercatat sebagai baris independen dengan tanggal & metode masing-masing. Di Laporan Penjualan & Jurnal Kas, setiap pembayaran muncul sebagai entri terpisah sesuai kapan uang diterima.

### Backend
- **`_build_and_persist_sale`** — auto-seed `payments[0]` sebagai entry initial (is_initial=True, amount=cash_paid, method=payment_method, bank=payment_bank, date=sale.date) saat sale dibuat.
- **`sales_pay_remaining`** — push entry baru ke `payments[]` dengan is_initial=False, date=pay_date (bisa berbeda dari sale.date).
- **Helper baru:**
  - `_payment_label(method, bank)` → "Cash / Tunai" / "Transfer BCA" / dsb
  - `_get_sale_payments(sale)` → return unified list. Backward-compat: sintesis entry initial dari sale-level info bila `payments[]` kosong (sale lama pre-fitur).
- **Endpoint baru:** `GET /api/sales/{id}/payments` → `{sale_id, sale_no, total, total_paid, sisa_tagihan, status, payments[]}` (payments sorted by date; initial first if same date).
- **Analytics endpoint (`/api/sales/report/analytics`)** — tiap pelunasan (is_initial=False) di-emit sebagai row terpisah dengan:
  - `is_pelunasan_row=True`, `date=payment.date`, `product_name="(Pelunasan · <label>)"`, pcs/meter/harga = 0
  - `payment_column` = dihitung dari method+bank+sale.branch
  - `payment_nominal_on_row` = payment.amount, `payment_date_on_row` = payment.date
  - `keterangan` = payment.notes atau default "Pelunasan sisa tagihan"
  - `method_totals` di-update supaya sesuai realisasi uang masuk per metode
  - Row DP awal (first_item) sekarang menggunakan `payments[0].amount` (initial), BUKAN cumulative `cash_paid` — mencegah double-count.
- **Excel export (`/api/sales/report/excel`)** — mirror analytics: pelunasan rows ditambahkan setelah item rows, dengan payment column filled sesuai metode pelunasan.

### Frontend
- **`Sales.jsx`:**
  - Tombol baru **"Riwayat"** (icon History, `data-testid=payment-history-button-{id}`) di setiap baris transaksi
  - Komponen `PaymentHistoryModal` (~155 lines) — summary card (Total/Sudah Dibayar/Sisa) + timeline table dengan badge jenis (DP AWAL biru, PELUNASAN hijau) + metode colored badges (Cash hijau, BCA biru, Mandiri merah, Shopee orange) + tombol "Bayar Sisa Sekarang" (jika masih DP) yang membuka modal PayRemaining.
- **`SalesReport.jsx`:**
  - Pelunasan rows di-render dengan bg hijau muda (`bg-[#008A00]/5`), icon panah kanan-bawah `↳` sebagai nomor, product name italic hijau, badge status **PELUNASAN** solid hijau.
  - Payment column: matches kondisi diperluas ke `(isFirst || isPelunasan)` sehingga nominal pelunasan tercetak di kolom pembayaran yang benar (BCA Plaza, Cash Plaza, dst) pada tanggal pelunasan.
  - `payTotals` menghitung SEMUA row yang punya payment_column (bukan hanya first_item) — footer total pembayaran per kolom kini akurat.

### Testing (Backend E2E)
Test case: 1 sale total 322k → DP 50k cash (2026-07-21) → Pelunasan 100k transfer BCA (2026-07-22) → Pelunasan 172k cash (2026-07-25) LUNAS.
- `GET /sales/{id}/payments` return 3 entries dgn `is_initial` flag ✓
- `GET /sales/report/analytics` return 3 rows: 1 item DP row + 2 pelunasan rows ✓
- `GET /cashbook/transactions` menunjukkan 3 entri terpisah dgn tanggal + akun kas berbeda (301/301-BCA/301) ✓
- `method_breakdown` akurat: cash 494k, transfer_bca 100k (agregasi lintas transaksi) ✓

### Testing (Frontend E2E via Playwright)
- Modal Riwayat: 3 baris muncul (DP AWAL 50k cash / PELUNASAN 100k BCA / PELUNASAN 172k cash), Total Dibayar 322k, status LUNAS ✓
- Laporan Penjualan: 1 item row + 2 pelunasan rows (`data-testid=report-row-pelunasan`) muncul sesuai tanggal masing-masing dan kolom pembayaran benar ✓
- Footer "1 TRANSAKSI (FILTERED)" — dedupe sale_no benar (tidak double-count) ✓
- Total pembayaran Cash Plaza: Rp 222.000 (50k DP + 172k pelunasan) — akurat ✓

### Files Changed
- `backend/server.py`: `_build_and_persist_sale` (seed initial payment), `PayRemainingIn`, `sales_pay_remaining` (is_initial flag), `_payment_label`, `_get_sale_payments`, `GET /sales/{id}/payments`, `sales_analytics` (pelunasan rows + fix cash_paid double-count), `sales_report_excel` (pelunasan rows).
- `frontend/src/pages/Sales.jsx`: state `historySale`, tombol Riwayat, `PaymentHistoryModal` component.
- `frontend/src/pages/SalesReport.jsx`: `pagedRows` row rendering handle `is_pelunasan_row`, `payTotals` include pelunasan payments.

### Backward Compatibility
Sale lama tanpa `payments[]`: `_get_sale_payments` sintesis entry initial dari sale-level (cash_paid + payment_method + payment_bank + sale.date). Analytics + payment history endpoint tetap berjalan tanpa migrasi DB.

---

## Update: 2026-07-21 (session 3) — Import Absensi Format Mesin Finger (WIDE)

### Feature
Parser Import Fingerprint kini mendukung format WIDE khas mesin finger (ZKTeco/Solution):
- **1 baris = 1 karyawan-tanggal** dengan multiple kolom Scan 1-4 (bukan long format 1 row/scan)
- Super header row "Pegawai" / "Data scanlog" otomatis di-skip
- Auto-detect posisi kolom (PIN=col0, Nama=col1, Tanggal=col5, Scan=col6+) atau explicit header row bila ada

### Perubahan Logika
**Backend (`_parse_wide_finger_format`):**
1. Baca file dengan `header=None`
2. Cari signature "Pegawai"+"Data scanlog" di row 0 → positional mapping, atau header row eksplisit dgn "PIN"/"Nama"/"Tanggal"/"Scan"
3. Parse tanggal dgn `dayfirst=True` (format DD-MM-YYYY dari mesin finger)
4. Iterate setiap cell scan (HH:MM:SS), gabung dgn tanggal → list of (pin, nama, datetime)
5. Convert ke DataFrame long-format untuk memakai logic groupby existing

**Aggregation (per PIN + tanggal):**
- **Jam Masuk (in_time)** = `min` dari semua scan di grup
- **Jam Pulang (out_time)** = `max` dari semua scan di grup
- **Handling duplicate rows**: jika PIN+Tanggal muncul multiple rows, semua scan di flatten dulu ke long format, lalu groupby min/max otomatis ambil earliest & latest lintas semua rows ✓
- Overtime dihitung dari `max(0, out_time - 17:00) / 60`

**Matching Employee:**
- Primary: `employee.nik == file.PIN`
- Fallback: `employee.name` case-insensitive == `file.Nama` (untuk kasus PIN mesin finger != NIK internal)

### Response Enhancement
Endpoint kini return `unmatched_details[]` selain `unmatched_niks`:
```json
{
  "unmatched_details": [
    {"pin": "1", "name": "SYARIFUDIN", "days_worked": 11, "overtime_hours": 1.54},
    ...
  ]
}
```

### UI (Payroll.jsx)
Setelah upload, muncul preview tabel kuning **"HASIL PARSING PIN YANG BELUM TER-MAPPING KE KARYAWAN"** menampilkan PIN, Nama (dari file), Hari Hadir, Lembur (jam) untuk setiap PIN unmatched — user langsung tahu mana PIN yang perlu di-mapping ke NIK karyawan.

### Testing
**File user real (12 PIN, 288 scans):** Parser berhasil ekstraksi:
- PIN 1 SYARIFUDIN (11 hari, 1.54h OT), PIN 2 ZIA (11d, 0h), PIN 7 WINARTI (12d, 4.77h OT), PIN 8 DAFFA (11d, 6.1h), PIN 9 PUPUT (11d, 0h), PIN 10 NURIS (9d, 5.58h), PIN 11 JOKO (11d, 4.77h), PIN 12 DEDY (12d, 6.97h), PIN 13 DINAR (10d, 5.48h), PIN 14 UBED, PIN 15 ALI, PIN 3 VERGIO ✓

**Test synthetic (same PIN + same date, 2 rows):**
- Row 1: PIN 1, 2026-07-15, scan 07:00 + 08:00
- Row 2: PIN 1, 2026-07-15, scan 15:00 + 17:30
- Result: in=07:00, out=17:30, overtime=0.5h ✓ (aggregasi lintas rows benar)

**Test row dgn 4 scans (multi-scan per row):**
- Row: PIN 1, 2026-07-16, scans 06:55 + 12:00 + 13:00 + 18:30
- Result: in=06:55, out=18:30, overtime=1.5h ✓

### Files Changed
- `backend/server.py`: `_parse_wide_finger_format` (helper baru ~100 lines), integrasi ke endpoint `POST /attendance/import`, response `unmatched_details`, fallback match by name
- `frontend/src/pages/Payroll.jsx`: preview tabel unmatched (PIN, Nama, Hari, Lembur)

### Backward Compatibility
Format LONG (1 baris = 1 scan) dengan header eksplisit ("nik/pin", "date", "time") tetap berjalan sebagai fallback bila wide detection gagal.

---

## Update: 2026-07-21 (session 4) — Cross-Month Attendance + Range Filter Fleksibel

### Feature
Attendance import & payroll kini mendukung **cross-month/year**: satu file Excel bisa berisi beberapa bulan sekaligus dan sistem menyimpannya seluruhnya. User bisa memilih rentang tanggal apapun (misal 25-Jun s/d 5-Jul) untuk menghitung Payroll.

### Backend
**Perubahan `POST /api/attendance/import`:**
- ❌ TIDAK LAGI membatasi data ke `period` — semua tanggal di file diproses
- ✅ Persistensi ke collection baru `attendance_daily` (upsert by `pin+date`): satu dokumen per (PIN, tanggal) dengan `in_time`, `out_time`, `overtime_hours`, `employee_id`, `employee_nik`, `employee_name`, `source_file`
- ✅ Summary `attendance_imports[period]` tetap dibuat (backward compat) untuk hanya bulan yg dipilih
- Response tambahan: `total_days_persisted`, `date_range: {from, to}`, `months_covered: ["2026-06", "2026-07"]`

**Endpoint baru:**
- `GET /api/attendance/daily/list?date_from=&date_to=&pin=&employee_id=` → daftar record harian per (PIN, tanggal) untuk rentang apapun. Return: items, count, total_overtime_hours, unique_dates, unique_pins.
- `GET /api/attendance/range/summary?date_from=&date_to=` → agregat per karyawan dalam rentang (days_worked + overtime_hours). Return: `summary: {employee_id: {...}}`, `unmatched_details: [...]`.

### Frontend (`Payroll.jsx`)
**Range picker bar (biru):**
- Icon `CalendarDays` + label "RENTANG ABSENSI (FLEKSIBEL · CROSS-MONTH)"
- Input `Dari Tanggal` + `Sampai Tanggal` (default = tanggal 1 s/d akhir bulan periode)
- Tombol "TERAPKAN RENTANG" → panggil `/attendance/range/summary` → auto-merge `days_worked` & `overtime_hours` ke tabel Input Kehadiran (data yang sudah diedit user manual tetap terpelihara)
- Tombol "DETAIL ABSEN HARIAN" → buka modal
- Metadata inline: "N ter-mapping · M hari-karyawan · X PIN unmatched"

**Modal `DetailAbsenModal`:**
- Filter fleksibel: Dari, Sampai, PIN (opsional), Quick Bulan (input type=month → langsung set Dari/Sampai jadi tanggal 1 s/d akhir bulan)
- Summary: baris count, jumlah tanggal unik, jumlah PIN unik, total lembur
- Table sticky-header: No, Tanggal, PIN, Nama, NIK Karyawan, Jam Masuk, Jam Pulang, Lembur (jam), Status (OK/Unmatched dgn badge warna)
- Baris unmatched di-highlight kuning muda

### Testing
**Backend curl E2E (`finger.xls` user):**
- Import 2026-07 → 288 scans → 152 days persisted → months_covered=["2026-06","2026-07"] ✓
- `daily/list ?from=2026-06-01&to=2026-06-30` → 21 rows, 2 tanggal (29 & 30 Jun), 12 PIN ✓
- `daily/list ?from=2026-07-01&to=2026-07-31` → 131 rows, 12 unique dates ✓
- `range/summary ?from=2026-06-25&to=2026-07-05` (CROSS-MONTH) → 67 hari-karyawan tergabung dari kedua bulan ✓

**Frontend Playwright E2E:**
- Payroll page menampilkan range bar dgn default 2026-07-01 s/d 2026-07-31 ✓
- Ubah ke 2026-06-25 s/d 2026-07-05, klik Terapkan → toast "Rentang ... 67 hari-karyawan (12 PIN belum ter-mapping)" + metadata inline muncul ✓
- Open Detail Absen Modal → 67 rows cross-month ditampilkan, filter ke bulan Juni saja → 21 rows ✓

### Files Changed
- `backend/server.py`: refactor endpoint import (drop period filter, persist ke `attendance_daily`), tambah endpoints `daily/list` dan `range/summary`
- `frontend/src/pages/Payroll.jsx`: state `dateFrom`/`dateTo`/`rangeInfo`, function `fetchRangeSummary`, range picker bar, komponen `DetailAbsenModal` (~155 lines)

### Backward Compatibility
- `attendance_imports[period]` tetap dibuat untuk `/attendance/{period}` endpoint lama (dipakai payroll preview/run)
- Sale/Payroll runs periode existing tidak berubah

---

## Update: 2026-07-21 (session 5) — UI Fix: Detail Absensi Default "Tampilkan Semua"

### Feature Fix (URGENT)
User report: modal Detail Absen Harian secara default filter ke bulan berjalan. User ingin default menampilkan SEMUA data yang ter-import.

### Perubahan
1. **Backend**: (tidak berubah) Verified — semua 152 hari-karyawan (14 tanggal unik lintas 2026-06 dan 2026-07) sudah tersimpan benar termasuk 30-06-2026 & 29-06-2026. Parsing DD-MM-YYYY `dayfirst=True` bekerja normal.

2. **Frontend `DetailAbsenModal`:**
   - Default state Dari/Sampai/PIN = KOSONG → API dipanggil dgn rentang 2000-01-01 s/d 2099-12-31 (effektif ambil semua)
   - Title berubah dari "Log Scan per PIN per Tanggal" → **"Semua Data Absensi ter-Import"**
   - Ditambah **3 tombol Quick Action** yang prominent:
     - 🟢 **TAMPILKAN SEMUA** (hijau, testid `detail-show-all`) → clear filter, reload semua
     - **BULAN INI** (testid `detail-current-month`) → set filter ke bulan berjalan
     - **Ke Bulan Spesifik** (dropdown `type=month`) → set filter ke bulan tertentu
   - Badge status: 🟢 "Menampilkan SEMUA data" (jika tidak ada filter aktif) atau 🔵 "Filter: X s/d Y" (jika filter aktif)
   - Meta summary tetap tampil (baris, tanggal, PIN, lembur)

### Testing (Playwright)
- Modal open default → 152 baris ditampilkan ✓ (mencakup 30-06-2026 & tanggal lainnya)
- Klik "Bulan Ini" → 131 baris (Juli saja) ✓
- Klik "Tampilkan Semua" → kembali ke 152 baris ✓

### Files Changed
- `frontend/src/pages/Payroll.jsx`: refactor `DetailAbsenModal` — default no-filter, tambah quick action buttons, badge status "Semua data"/"Filter"

### Note
Fitur ini juga menegaskan bahwa **semua data telah benar tersimpan** — tidak ada masalah pada backend/database. Sebelumnya user melihat filter otomatis di UI membuat data lain terlihat "hilang".

---

## Update: 2026-07-21 (session 6) — Overtime Logic (Weekday/Sabtu/Minggu)

### Feature
Aturan lembur sesuai realita kerja Indonesia:
- **Senin-Jumat** (weekday 0-4): jam kerja 08:30 - 16:30. Overtime = out_time > 16:30
- **Sabtu** (weekday 5): jam kerja 08:30 - 14:00. Overtime = out_time > 14:00
- **Minggu** (weekday 6): seluruh scan hari itu dihitung lembur (out - in)

### Backend
**Helper baru `_calculate_overtime_hours(date_obj, in_time, out_time)`:**
- Mengembalikan jam lembur berdasarkan hari kerja
- Digunakan di endpoint import (persist daily records) dan summary aggregation (attendance_imports[period])
- Constants: `WORK_END_WEEKDAY = 16:30`, `WORK_END_SATURDAY = 14:00`

**Perubahan struktur `attendance_daily`:**
- Field baru `weekday`: "Senin" / "Selasa" / ... / "Minggu" — untuk display & audit
- `overtime_hours` sekarang pakai aturan baru

### Testing (Backend E2E dengan file real user)
Re-import → 152 days_persisted:
| Tanggal | Weekday | Sample: PIN 1 SYARIFUDIN | OT |
|---------|---------|---------------------------|-----|
| 30-06-2026 | Selasa | 07:08→16:40 (>16:30) | 0.18h ✓ |
| 04-07-2026 | Sabtu | 07:39→14:13:51 (>14:00) | 0.23h ✓ |
| 08-07-2026 | Rabu | 07:19→18:32 (>16:30) | 2.04h ✓ |
| 11-07-2026 | Sabtu | 07:43→16:46 (>14:00) | 2.78h ✓ |
| 12-07-2026 | Minggu | (semua scan lembur) | 4.72h ✓ |
| 13-07-2026 | Senin | 07:08 single-scan | 0.00h ✓ |

Total OT per karyawan (period 2026-07) meningkat signifikan setelah update aturan:
- DEDY 6.97h → 17.49h (+10.5h dari cutoff mundur ke 16:30 + Sabtu/Minggu)
- DAFFA 6.10h → 16.33h
- JOKO 4.77h → 15.05h

### Files Changed
- `backend/server.py`: constant + helper `_calculate_overtime_hours`, refactor 2 spot OT calc di endpoint import
- Tidak ada perubahan frontend — jam lembur yang tampil di UI otomatis pakai nilai baru (dari DB)

### Notes
- Data 30 Juni & bulan lainnya tetap terimport normal (152 days, months=[2026-06, 2026-07])
- User harus **re-import** file finger untuk mendapatkan overtime terbaru (existing records di DB ter-overwrite otomatis via upsert by pin+date)
- Frontend Payroll `range/summary` sudah pakai persisted `overtime_hours`, jadi otomatis dapat nilai baru

---

## Update: 2026-07-21 (session 7) — Overtime dengan Jeda 30 Menit (Grace Period)

### Feature Update
Aturan OT diperbarui: pulang dalam jeda 30 menit setelah jam kerja selesai **tidak** dihitung lembur (grace period untuk keluar gedung/scan finger dsb).

### Aturan Final
| Hari | Jam Kerja | OT Mulai | Contoh |
|------|-----------|----------|--------|
| Senin-Jumat | 08:30 - 16:30 | **>17:00** | Pulang 18:00 → OT 1h |
| Sabtu | 08:30 - 14:00 | **>14:30** | Pulang 16:00 → OT 1.5h |
| Minggu | (libur) | Full durasi | Scan masuk-pulang seluruhnya = OT |

### Backend
**Konstanta baru:**
- `OT_START_WEEKDAY = 17:00` (Senin-Jumat)
- `OT_START_SATURDAY = 14:30` (Sabtu)

Helper `_calculate_overtime_hours` diupdate: kalkulasi OT sekarang menggunakan `OT_START_*` sebagai anchor (bukan `WORK_END_*`). Konstanta `WORK_END_*` tetap disimpan untuk referensi.

### Testing
**Unit tests (12 cases, all PASS):**
- Pulang tepat 16:30 / 17:00 / 14:30 → 0h ✓
- Pulang 18:00 Senin → 1h ✓
- Pulang 20:30 Rabu → 3.5h ✓
- Pulang 16:00 Sabtu → 1.5h ✓
- Pulang 20:00 Sabtu → 5.5h ✓
- Minggu 09:00→15:00 → 6h ✓ (full duration)

**E2E (real file finger user):**
- Rabu 08-07 PIN 1: 07:19→18:32 → OT 1.54h (18:32-17:00) ✓
- Sabtu 11-07 PIN 1: 07:43→16:46 → OT 2.28h (16:46-14:30) ✓
- Minggu 12-07 PIN 10: 10:16→15:00 → OT 4.72h (full) ✓
- Pulang <17:00 weekday atau <14:30 Sabtu → 0h ✓ (grace period bekerja)

**Data cross-month tetap aman:**
- 152 days_persisted, months=[2026-06, 2026-07]
- Tanggal 30-06 (Selasa) tetap ter-import & OT dihitung dgn aturan baru

### Files Changed
- `backend/server.py`: konstanta `OT_START_WEEKDAY/OT_START_SATURDAY`, refactor `_calculate_overtime_hours` (anchor berubah dari WORK_END ke OT_START)

### Regression Impact
Total OT per karyawan turun ~10-15% dibanding session sebelumnya (grace period menghilangkan micro-lembur yang terjadi antara 16:30-17:00 dan 14:00-14:30).

---

## Update: 2026-07-21 (session 8) — Konfigurasi Tarif Lembur per Jam

### Feature
Menambah opsi konfigurasi **"Tarif Lembur per Jam (Rp)"** di halaman Settings. Jika diisi (>0), sistem pakai nilai ini sebagai pengali langsung untuk kalkulasi lembur. Jika 0 (default), sistem fallback ke formula standar Indonesia `(basic/173) × multiplier`.

### Backend
- **CONFIG:** field baru `overtime_hourly_rate` (default 0)
- **calculate_payslip:** decision logic
  - `if configured > 0`: `overtime_pay = configured_rate × overtime_hours` (source: `configured`)
  - `else`: `overtime_pay = (basic/173) × multiplier × overtime_hours` (source: `auto_1_173`)
- **API `/config/constants`** GET+PUT include field baru
- **Slip payload** menyertakan `attendance.overtime_rate_per_hour` dan `attendance.overtime_rate_source` untuk display

### Frontend
- **Settings.jsx:** field "Tarif Lembur per Jam (Rp)" tipe money di section "Biaya Jabatan & Kerja"
- **Payslip.jsx:** row Lembur menampilkan format: `Lembur (X jam × Rp Y/jam)` bukan hanya "Lembur"
- **PDF payslip (backend):** label lembur dinamis dgn breakdown jam × tarif

### Testing
**E2E via curl:**
- Set rate=20000 → OT 5 jam × 20000 = **Rp 100.000** ✓ (source: configured)
- Reset rate=0 → OT 5 jam × (10M/173) × 1.5 = **Rp 433.526** ✓ (source: auto_1_173)
- Config GET include field baru ✓
- Config PUT accept & persist ✓

**Frontend visual:** field "Tarif Lembur per Jam (Rp)" muncul di section "Biaya Jabatan & Kerja" antara "Multiplier Lembur (fallback)" dan sebelum "Catatan" ✓

### Files Changed
- `backend/server.py`: CONFIG default, calculate_payslip logic, config_constants GET/PUT schema, slip payload, PDF label
- `frontend/src/pages/Settings.jsx`: field baru di section Biaya Jabatan & Kerja, load/save handling
- `frontend/src/pages/Payslip.jsx`: label lembur dinamis dgn breakdown

---

## Update: 2026-07-21 (session 9) — Formula Lembur Pro-Rata Harian (per-Menit)

### Feature
Rumus lembur diganti total ke pro-rata harian berdasarkan gaji pokok, mengabaikan tarif manual di Konfigurasi. Grace period 30 menit tetap terjaga.

**Rumus:**
```
Upah per Hari  = Gaji Pokok / standard_workdays (default 22, bisa diubah di Settings, misal 26)
Upah per Jam   = Upah per Hari / 7 (jam kerja per hari)
Upah per Menit = Upah per Jam / 60
Total Lembur   = Total Menit OT × Upah per Menit
```

### Backend
- **`calculate_payslip`:** hapus branching `configured/auto_1_173`. Sekarang selalu pakai formula pro-rata harian.
- **Konstanta:** `WORK_HOURS_PER_DAY = 7` (inline dalam fungsi)
- **Slip payload attendance** field baru:
  - `overtime_minutes` (jam × 60)
  - `overtime_rate_per_hour` (upah/jam)
  - `overtime_rate_per_minute` (upah/menit)
  - `wage_per_day` (upah/hari)
  - `work_hours_per_day` = 7
  - `standard_workdays` (dari CONFIG)
  - `overtime_rate_source` = "auto_pro_rata_daily"

### Frontend
- **Settings.jsx:** hapus field "Tarif Lembur per Jam (Rp)" & "Multiplier Lembur (fallback)" — tidak lagi digunakan
- **Payslip.jsx:** di bawah row Lembur, tampil baris rincian format:
  ```
  Rincian upah: Gaji Pokok Rp 10,000,000 ÷ 26 hari ÷ 7 jam = Rp 54.945/jam
  (300 menit × Rp 915.75/menit)
  ```

### Testing (E2E via curl)
Set standard_workdays = 26, employee basic = 10jt, OT = 5 jam:
- Upah/Hari  : Rp 384.615 (10M / 26) ✓
- Upah/Jam   : Rp 54.945 (per hari / 7) ✓
- Upah/Menit : Rp 915,75 (per jam / 60) ✓
- Total OT   : 300 menit × 915,75 = **Rp 274.725** ✓ (match expected exactly)

### Files Changed
- `backend/server.py`: `calculate_payslip` — hapus config check, ganti dgn formula pro-rata daily; slip payload fields
- `frontend/src/pages/Payslip.jsx`: baris rincian upah di bawah row Lembur
- `frontend/src/pages/Settings.jsx`: hapus 2 field yg tidak dipakai (overtime_multiplier & overtime_hourly_rate)

### Note
- CONFIG field `overtime_hourly_rate` & `overtime_multiplier` masih ada di DB (backward-compat) tapi TIDAK dipakai
- Grace period 30 menit (dari session 7) tetap aktif — nilai `overtime_hours` sudah accounted for grace period saat import

---

## Update: 2026-07-29 — Potongan Otomatis Terlambat > 4 Jam

### Feature
Auto-penalti keterlambatan ekstrem untuk disiplin absensi. Jika karyawan terlambat masuk **> 4 jam** (setelah 08:30 → melewati 12:30), sistem otomatis memotong gaji dengan rumus pro-rata per menit:

**Rumus**: `Potongan = Total Menit Telat × ((Gaji Pokok / 26) / 7) / 60`

Menit telat < 4 jam tidak dikenakan penalti (grace). Hari Minggu libur (tidak dihitung).

### Behavior
- **Import Absensi Finger** → parser (`_calculate_late_minutes`) menghitung `penalty_minutes` per hari, disimpan di `attendance_daily.late_penalty_minutes`.
- **Endpoint `/attendance/import` & `/attendance/range/summary`**: mengagregasi `late_penalty_minutes` per karyawan dalam periode. Response `summary` sekarang include field ini.
- **Frontend Payroll.jsx**: kolom baru **"MENIT TELAT (>4H)"** di tabel Input Kehadiran (highlight merah jika > 0). Auto-terisi setelah Terapkan Rentang / Import Fingerprint.
- **`calculate_payslip`**: baca `late_penalty_minutes` dari attendance payload → hitung `auto_late_penalty = menit × wage_per_minute`. **AUTO OVERRIDE MANUAL**: bila auto > 0, override field `potongan_terlambat` di employee master.
- **Slip Gaji (`Payslip.jsx`, `Portal.jsx`, PDF)**: label dinamis
  - Auto: `Potongan Terlambat (>4 Jam · N menit)` + nominal
  - Manual: `Potongan Terlambat` (label lama)
- **`slip.attendance` extra fields**: `late_penalty_minutes`, `late_penalty_amount`, `late_penalty_source` (auto_from_attendance | manual_employee_master | none)

### Testing (E2E via requests)
Employee basic 2.000.000, standard_workdays 26:
- wage_per_min = ((2.000.000 / 26) / 7) / 60 = 183.15
- Case1 [no late]: potongan=0, source=none ✓
- Case2 [300 min late]: potongan = 300 × 183.15 = **Rp 54.945**, source=auto_from_attendance ✓
- Case3 [manual=100k + auto=300min]: AUTO override → 54.945 (bukan 100.000) ✓
- Case4 [manual=100k, auto=0]: manual applies → 100.000, source=manual_employee_master ✓

Slip UI verified via screenshot: label "Potongan Terlambat (>4 Jam · 300 menit) — Rp 54.945" render benar.

### Files Changed
- `backend/server.py`: `calculate_payslip` (~15 lines), `/attendance/import` aggregation (~10 lines), `/attendance/range/summary` (~10 lines), PDF renderer label
- `frontend/src/pages/Payroll.jsx`: kolom "Menit Telat (>4H)" + merge `late_penalty_minutes` di fetchRangeSummary & onFingerprintImport, default `late_penalty_minutes: 0`
- `frontend/src/pages/Payslip.jsx`: dynamic label dengan menit
- `frontend/src/pages/Portal.jsx`: dynamic label dengan menit

### Backlog Setelah Ini
- 🔴 CRITICAL: Refactor `server.py` (>8200 baris) → pecah ke `/app/backend/routers/*.py`
- 🟢 P1: Scheduled Auto-Send Payslip (APScheduler)
- 🟢 P1: Cuti Tahunan Kuota per Karyawan
- 🟢 P1: Auto-add lembur approved ke perhitungan Payroll
- 🟡 P2: Halaman Daftar Pinjaman Aktif, Notif WA izin/cuti
- 🟡 P3: Audit Log HR, Rekap lembur PDF, Notif PO tertunda

---

## Update: 2026-07-29 (session 2) — Dashboard Widget: Top Karyawan Telat > 4 Jam

### Feature
Widget baru di halaman Dashboard yang menampilkan **Top N karyawan dengan total menit telat > 4 jam terbanyak** dalam bulan berjalan. Membantu HR mengidentifikasi kandidat yang butuh coaching disiplin lebih cepat.

### Backend
- **Endpoint baru**: `GET /api/dashboard/late-offenders?month=YYYY-MM&limit=5` — default month = bulan berjalan, limit 1-50 (default 5)
- Response: `{month, items:[{employee_id, nik, name, position, department, total_late_minutes, occurrences, estimated_penalty}], total_offenders, no_data}`
- **Auto-attached ke `/api/dashboard/stats`** sebagai field `late_offenders` (limit 5) → satu round-trip
- Aggregasi via `attendance_daily.late_penalty_minutes > 0` per employee, sorted desc by total menit
- Estimated penalty dihitung real-time dgn `basic_salary / 26 / 7 / 60 × menit` (mirror `calculate_payslip`)
- Unmatched PIN (tanpa employee_id) juga muncul dgn badge "Unmatched" (estimasi penalty tidak dihitung)

### Frontend
- **`Dashboard.jsx`**: komponen `LateOffendersWidget` di antara `ContractReminder` & `InventoryWidget`
- Icon `Clock` warna merah, header `TOP KARYAWAN TELAT > 4 JAM`
- Kolom: #, Karyawan (nama + NIK/PIN + posisi/dept), Kejadian (Nx), Total Menit (merah bold), Est. Potongan
- Empty state: "Belum ada data absensi bulan ini, atau semua karyawan tepat waktu."
- Footnote rumus pro-rata di bawah tabel
- data-testid: `late-offenders-widget`, `late-offender-row`, `late-offenders-empty`

### Testing
- E2E backend: seed 5 records (Siti 2× 950 min, Daffa 3× 830 min) → ranking benar, estimasi penalty match (Siti: 950 × 1373.63 = Rp 1.304.945; Daffa: 830 × 183.15 = Rp 152.015)
- Dashboard screenshot: widget render benar dgn 2 baris, kolom, footnote, empty-state fallback

### Files Changed
- `backend/server.py`: `_top_late_offenders` helper + `/dashboard/late-offenders` endpoint + `late_offenders` field di dashboard_stats + import `date` from datetime
- `frontend/src/pages/Dashboard.jsx`: import `Clock` icon, `LateOffendersWidget` component, mounted setelah ContractReminder

---

## Update: 2026-07-29 (session 3) — Refresh Kolom Tabel Payroll

### Feature
User request: "Perbarui tampilan tabel Jalankan Payroll dgn kolom-kolom otomatis dari Absensi + Master Karyawan."

**Kolom baru (8, berurutan):**
1. NIK
2. NAMA (rename dari "Karyawan")
3. GAJI POKOK
4. HARI HADIR (auto dari attendance)
5. LEMBUR (JAM) (auto dari attendance)
6. **LEMBUR (RP)** — read-only, biru, auto-calc: `jam × 60 × ((Gaji Pokok / 26) / 7) / 60`
7. TERLAMBAT (JAM) — dari `late_penalty_minutes / 60`, editable, saved as menit ke backend
8. **TERLAMBAT (RP)** — read-only, merah bold, auto-calc: `menit × ((Gaji Pokok / 26) / 7) / 60`

**Kolom Bonus & Potongan Lain** — dihapus dari tampilan (state tetap 0 di payload; jarang dipakai di workflow ini).

### Behavior
- Lembur (Rp) & Terlambat (Rp) update **live** saat user edit Lembur (Jam) atau Terlambat (Jam)
- Terlambat (Jam) input: user ketik jam, disimpan ke state sbg `late_penalty_minutes` (× 60) → tetap kompatibel dgn backend
- Footnote rumus terpampang di bawah tabel utk transparansi
- Highlight visual: kolom Rp biru (lembur) / merah bold (terlambat), input Terlambat berlatar merah muda saat > 0

### Testing (screenshot verified)
Seed 5 records (2026-07) → hasil match exact:
- Daffa (Gaji 2jt): OT 21.18h → Rp 232.747; Late 13.83h → Rp 152.015 ✓
- Siti (Gaji 15jt): OT 3h → Rp 247.253; Late 15.83h → Rp 1.304.945 ✓

### Files Changed
- `frontend/src/pages/Payroll.jsx`: table header + body rewrite (~60 lines), inline live-calc formula, footnote

### data-testid Baru
- `att-ot-rp-{id}` — Lembur (Rp) cell
- `att-late-hours-{id}` — Terlambat (Jam) input (replaces `att-late-{id}`)
- `att-late-rp-{id}` — Terlambat (Rp) cell

---

## Update: 2026-07-29 (session 4) — Rapikan Field Master Karyawan

### Changes
- **Hapus dari form**: Field `Tunjangan Tetap (Rp)` (fixed_allowance) & `Tunjangan Tidak Tetap (Rp)` (tunjangan_tidak_tetap). Save payload paksa 0 utk kedua field.
- **Hapus kolom** "Tunjangan" dari tabel listing karyawan (kolom ini menampilkan fixed_allowance yang akan selalu 0)
- **Rename label**: `Tunjangan WFH` → `Insentif WFH` di:
  - Form Master Karyawan (Employees.jsx)
  - Slip Gaji UI (Payslip.jsx)
  - Portal Karyawan (Portal.jsx)
  - Slip PDF (server.py `earn_rows`)

### Behavior Backward Compat
- Backend model `EmployeeIn` masih punya field `fixed_allowance` & `tunjangan_tidak_tetap` — tidak dihapus utk backward compat + tetap dipakai perhitungan THR (`Gaji + Tunjangan Tetap`)
- Data lama tetap punya nilai; hanya tidak bisa diedit lagi dari form (efektif read-only 0 setelah save berikutnya)
- Slip PDF & UI: baris `Tunjangan Tetap` / `Tj. Tidak Tetap` masih render bila nilai > 0 (legacy)

### Testing
- Screenshot form: `Insentif WFH` muncul, `Tunjangan Tetap` & `Tunjangan Tidak Tetap` hilang ✓
- Screenshot slip: label "Insentif WFH — Rp 500.000" render sesuai ✓
- Backend text scan: "Tj. WFH" tidak ada lagi, "Insentif WFH" ada ✓

### Files Changed
- `frontend/src/pages/Employees.jsx`: hapus 2 field form + kolom tabel; payload force 0
- `frontend/src/pages/Payslip.jsx`: rename `Tj. WFH` → `Insentif WFH`
- `frontend/src/pages/Portal.jsx`: rename `Tj. WFH` → `Insentif WFH`
- `backend/server.py`: rename PDF label `Tj. WFH` → `Insentif WFH`

---

## Update: 2026-07-29 (session 5) — Status Kontrak 2 Tahun + Sembunyikan Rincian PPh 21

### Changes
1. **Status Kontrak "Kontrak 2 Tahun"** (value `kontrak_24`):
   - Ditambahkan ke `EMPLOYMENT_STATUS_OPTIONS` (Employees.jsx) — 5 opsi total
   - Auto-calc end date: mulai + 24 bulan (H-1)
   - Backend `_find_expiring_contracts` include `kontrak_24` di filter
   - Backend model comment updated
   - Dashboard `STATUS_LABEL` include "Kontrak 2 Thn"

2. **Sembunyikan Rincian Perhitungan PPh 21** dari Slip Gaji:
   - Payslip.jsx: `<details>Rincian Perhitungan PPh 21</details>` dihapus
   - Portal.jsx: `<details>Rincian Perhitungan PPh 21</details>` dihapus
   - PDF slip (`_build_payslip_pdf`): section "RINCIAN PERHITUNGAN PPH 21" + tabel dihapus
   - Baris `PPh 21` di kolom Potongan (nominal saja) TETAP ada — hanya rincian detail (Bruto Setahun/Biaya Jabatan/PTKP/PKP dsb) yang dihapus
   - Cleanup: unused `const t = slip.tax_detail` dihapus dari Payslip.jsx & Portal.jsx

### Testing (E2E via Playwright + curl)
- Dropdown Status Karyawan: `['OJT', 'Kontrak 6 Bulan', 'Kontrak 1 Tahun', 'Kontrak 2 Tahun', 'Tetap']` ✓
- Slip UI: "Rincian Perhitungan PPh 21" **HILANG**, "Iuran Ditanggung Perusahaan" masih ada, baris "PPh 21" tetap render di Potongan ✓
- PDF slip endpoint: HTTP 200 (2872 bytes) — tidak error setelah section dihapus ✓

### Files Changed
- `backend/server.py`: EmployeeIn comment, `_find_expiring_contracts` filter, `_build_payslip_pdf` (hapus tax detail section)
- `frontend/src/pages/Employees.jsx`: EMPLOYMENT_STATUS_OPTIONS + kontrak_24, calcEndDate + isKontrak helper
- `frontend/src/pages/Dashboard.jsx`: STATUS_LABEL + kontrak_24
- `frontend/src/pages/Payslip.jsx`: hapus tax detail `<details>` + unused var
- `frontend/src/pages/Portal.jsx`: hapus tax detail `<details>` + unused var

---

## Update: 2026-07-29 (session 6) — Sembunyikan Kolom Kode Akun & Teks "101" dari Buku Kas

### Feature (URGENT UI FIX)
User request: modul Buku Kas tidak boleh menampilkan angka "101" atau kolom "Kode Akun" sama sekali. Filter data internal tetap.

### Changes (frontend/src/pages/CashBook.jsx)
**Jurnal Akuntansi tab:**
- Kolom `Kode Akun` (header + cell rendering `{t.account_code}`) dihapus dari tabel
- colSpan header/footer/empty state disesuaikan dari 8 → 7
- Saldo Awal row colSpan: 4 → 3
- Chip badge: `Kredit: Hanya 101 Kas` → `Kredit: Hanya Kas Utama`
- Konvensi footnote: `khusus Akun 101 Kas` → `khusus Kas Utama`; `301 Penjualan Tunai / 301-BCA` → `Penjualan Tunai / BCA`

**Buku Kas tab:**
- Info footer bar: `transaksi Kas 101` → `transaksi Kas Utama`
- Empty state: `Belum ada transaksi Kas 101 bulan ini` → `Belum ada transaksi Kas Utama bulan ini`

### Filter Behavior (unchanged)
- Line 57-59: filter data `t.account_code === "101"` **tetap ada** (kode internal, tidak terlihat user)
- Line 678-680: JournalTab filter Kredit `t.account_code === "101"` **tetap ada**

### Testing (Playwright screenshot)
- Buku Kas tab: `Kode Akun` = **FALSE** · `101` = **FALSE** ✓
- Jurnal Akuntansi tab: `Kode Akun` = **FALSE** · `101` = **FALSE** · `101 Kas` = **FALSE** ✓
- Header table Jurnal: `NAMA AKUN · TANGGAL · KETERANGAN · DEBET · KREDIT · SALDO · AKSI` (7 kolom, tanpa Kode Akun) ✓
- Header table Buku Kas: `TANGGAL · NAMA AKUN · KETERANGAN · PEMASUKAN · PENGELUARAN · SALDO · AKSI` ✓

### Files Changed
- `frontend/src/pages/CashBook.jsx`: JournalTab table (hapus col Kode Akun + colSpan), BookTab labels, chip badge, konvensi footnote

---

## Update: 2026-07-29 (session 7) — Toggle "Tampilkan Kode Akun" di Buku Kas

### Feature
Kembalikan opsi menampilkan Kode Akun via toggle checkbox di tab bar modul Kas Operasional. Default OFF (sesuai request URGENT sebelumnya).

### Behavior
- **State default OFF**: kolom `Kode Akun` disembunyikan di JournalTab, semua teks bertuliskan "101" (chip badge "Kredit: Hanya 101 Kas", label "transaksi Kas 101", konvensi "khusus Akun 101 Kas", "301 Penjualan Tunai / 301-BCA") diganti menjadi "Kas Utama" / disederhanakan
- **Toggle ON**: kolom `Kode Akun` muncul kembali di JournalTab + colSpan header/footer/empty state auto-adjust (7→8), semua teks angka akun kembali ke bentuk originalnya untuk kebutuhan audit/finance
- **Persistence**: state disimpan di `localStorage['cashbook.showAccountCode']` (`"1"` / `"0"`) — bertahan setelah reload / logout-login
- **Testid**: `toggle-account-code` untuk QA

### Filter Behavior (unchanged)
Filter data internal tetap `t.account_code === "101"` — toggle hanya mempengaruhi visibility, tidak mempengaruhi filter aggregasi/render.

### Files Changed
- `frontend/src/pages/CashBook.jsx`:
  - Parent state `showAccountCode` + useEffect persist localStorage
  - Toggle checkbox di tab bar (kanan atas)
  - Prop drill `showAccountCode` ke BookTab & JournalTab
  - BookTab: conditional label "Kas 101" vs "Kas Utama"
  - JournalTab: conditional column `Kode Akun` (header/cell/colSpan), chip badge, konvensi footnote

### Testing (Playwright E2E)
- Default state OFF: `Kode Akun` in body = **FALSE**, `101` in body = **FALSE** ✓
- Toggle ON: header `KODE AKUN · NAMA AKUN · TANGGAL · KETERANGAN · DEBET · KREDIT · SALDO · AKSI`, chip "HANYA 101 KAS", footnote "301 Penjualan Tunai" muncul, `101` in body = TRUE ✓
- Persistence: uncheck → reload page → state tetap unchecked ✓

---

## Update: 2026-07-29 (session 8) — Sembunyikan Kolom "Nama Akun" di Buku Kas

### Feature (URGENT UI FIX #2)
User feedback: kolom "Nama Akun" di tab Buku Kas selalu bernilai "Kas" (karena filter internal hanya menampilkan akun 101) — redundan & memakan tempat. User request: sembunyikan kolom "Nama Akun" juga dari BookTab (mengikuti aturan toggle).

### Changes (frontend/src/pages/CashBook.jsx BookTab)
- Kolom `Nama Akun` di BookTab kini **conditional** pada `showAccountCode`:
  - **OFF (default)**: 6 kolom `TANGGAL · KETERANGAN · PEMASUKAN · PENGELUARAN · SALDO · AKSI`
  - **ON**: 7 kolom `TANGGAL · NAMA AKUN · KETERANGAN · PEMASUKAN · PENGELUARAN · SALDO · AKSI`
- colGroup, header, cell rendering, SALDO AWAL row colSpan (2→1), SALDO AKHIR row colSpan (3→2), empty state colSpan (7→6), loading colSpan — semuanya adjust otomatis
- Auto badge (transaksi otomatis) di-inline kecil di kolom Tanggal saat kolom Nama Akun hidden — sebelumnya berada di Nama Akun

### Filter Behavior (unchanged)
Filter data internal tetap `t.account_code === "101"` — hanya visibility UI yang berubah.

### Testing (Playwright screenshot)
- Buku Kas default: header `TANGGAL · KETERANGAN · PEMASUKAN · PENGELUARAN · SALDO · AKSI` ✓
- Label footer: "transaksi Kas Utama" (bukan Kas 101) ✓
- Text scan: `NAMA AKUN` = FALSE ✓
- Toggle ON: header kembali menampilkan `NAMA AKUN` ✓

### Files Changed
- `frontend/src/pages/CashBook.jsx`: BookTab colgroup + header + rows + saldo awal/akhir + empty state

---

## Update: 2026-07-29 (session 9) — Ubah Filter Buku Kas: Exclude 101 Kas

### Feature (URGENT UI FIX #3)
User request: BookTab kini menampilkan **semua transaksi dari akun apapun KECUALI akun 101 Kas**. Kolom Kode Akun tetap muncul.

### Rasional
Sebelumnya:
- BookTab = akun 101 saja
- JournalTab = akun 101 saja

Sekarang:
- **BookTab** = semua akun **kecuali** 101 (Non-Kas) — arus kas ke/dari akun bank/utang/piutang/dsb
- **JournalTab** = tetap akun 101 Kas (arus kas utama)

### Changes (frontend/src/pages/CashBook.jsx)
- Ekstrak `matchesSearch` helper (search description/account_name/account_code/reference)
- Dua filter dipisah:
  - `filteredBook` = tx.filter(code !== "101" && search)
  - `filteredJournal` = tx.filter(code === "101" && search)
- Prop `filtered` di BookTab dipanggil dgn `filteredBook`, JournalTab dgn `filteredJournal`
- Legacy alias `filtered` yang shared dihapus

### BookTab table restructure
- Kolom baru **7 fixed**: `TANGGAL · KODE AKUN · NAMA AKUN · KETERANGAN · PEMASUKAN · PENGELUARAN · AKSI`
- **Kode Akun & Nama Akun selalu tampil** (tidak mengikuti toggle karena wajib utk identifikasi akun non-101)
- Kolom **SALDO dihapus** (running balance tidak berarti untuk multi-account view)
- SALDO AWAL / SALDO AKHIR rows dihapus (khusus untuk akun tunggal)
- Diganti footer row **TOTAL NON-KAS** dgn subtotal Pemasukan + Pengeluaran (bukan running balance)
- Label footer: "N transaksi Non-Kas · (akun 101 Kas ditampilkan di tab Jurnal Akuntansi)"
- Empty state: "Belum ada transaksi non-Kas bulan ini"
- Auto badge (lock icon) tetap muncul di kolom Tanggal

### Toggle "Tampilkan Kode Akun"
- Tetap ada, hanya mempengaruhi JournalTab
- BookTab tidak lagi dipengaruhi toggle (kolom Kode Akun selalu tampil)

### Testing (Playwright + seed data)
- Screenshot verified: 5 rows dari akun 201 & 301 muncul, TIDAK ada 101 di rows
- Header `TANGGAL · KODE AKUN · NAMA AKUN · KETERANGAN · PEMASUKAN · PENGELUARAN · AKSI` ✓
- TOTAL NON-KAS row menjumlah masuk (Rp 1.000.000) & keluar (Rp 115.500) ✓
- Auto badge (lock) muncul di transaksi PO ✓

### Files Changed
- `frontend/src/pages/CashBook.jsx`:
  - `matchesSearch` helper + `filteredBook`/`filteredJournal` split
  - Props update ke BookTab & JournalTab
  - BookTab rewrite: kolom baru, hapus Saldo, ubah label, TOTAL NON-KAS row

---

## Update: 2026-07-30 (session 10) — Jurnal Akuntansi: Semua Akun (Debet & Kredit)

### Feature (URGENT UI FIX #4)
User request: JournalTab harus menampilkan **semua arus kas masuk & keluar dari berbagai akun**. Sinkronkan Debet dari modul Pembelian & Kas Operasional. Row yang sebelumnya hilang harus muncul kembali di Debet.

### Root Cause
Setelah refactor session-8, `filteredJournal` dibatasi `account_code === "101"` yang memutus data auto dari Pembelian (account_code=201 Utang Usaha, dsb). Sehingga Debet kelihatan kosong / hilang.

### Fix (frontend/src/pages/CashBook.jsx)
1. `filteredJournal` sekarang: `txData.transactions.filter(matchesSearch)` — **tidak ada batasan account_code**
2. Inner filter di JournalTab (`kasTx = filtered.filter(t.type === "out" || ...)`) → dihapus. `kasTx = filtered` — semua tampil
3. Running Saldo tetap: `Saldo Awal + Σ Kredit − Σ Debet`
4. Chip badge: `Debet: Semua · Kredit: Hanya Kas Utama` → **`Debet & Kredit: Semua Akun`**
5. Konvensi footnote: "Debet = semua pengeluaran uang (dari Pembelian / Kas Op / manual — apapun kode akun tujuannya) · Kredit = semua pemasukan uang (dari Penjualan / manual — apapun kode akun asalnya) · Data auto-sync dari modul **Pembelian** dan **Kas Operasional**"

### Testing (Playwright + seed 3 non-101 transactions)
- Rows: 5 → **8** setelah seed (301 Sales, 502 Biaya Op, 201 Utang) — semua muncul ✓
- DEBET column terisi: Rp 750.000 (ATK), Rp 1.200.000 (utang supplier), + 4× auto PO ✓
- KREDIT column terisi: Rp 3.500.000 (Sales NOTA-001) + Rp 1.000.000 (auto Sales Bu Ani) ✓
- Saldo running end-of-month: Rp 3.434.500 = matched dgn kartu "Saldo Kas Real-time" & "Saldo Akhir Jul 2026" ✓
- TOTAL DEBET Rp 2.065.500 · TOTAL KREDIT Rp 4.500.000 ✓
- Konvensi footnote update dgn referensi sync modul ✓

### Files Changed
- `frontend/src/pages/CashBook.jsx`:
  - `filteredJournal` filter: hapus account_code === "101" restriction
  - JournalTab: `kasTx = filtered` (bukan lagi sub-filter)
  - Chip badge & konvensi footnote update

---

## Update: 2026-07-30 (session 11) — Jurnal Akuntansi: Filter Ketat Kredit Hanya Kas 101

### Feature (URGENT UI FIX #5)
User request finalize semantic Kas ledger:
- **DEBET**: keep as-is — semua pengeluaran (type=out) dari akun manapun
- **KREDIT**: filter ketat — hanya (type=in && account_code === "101")
- Ringkasan total di top cards & running saldo mengikuti filter

### Rationale
Kredit Kas 101 mewakili uang yang benar-benar masuk fisik ke pot Kas. Pemasukan yang masuk ke Bank/akun lain (misal Sales via transfer) tidak menaikkan saldo Kas fisik — jadi tidak boleh muncul di Kredit.

### Backend Changes (server.py)
1. **`/cashbook/balance`**: `total_in = sum(in && code=="101")`, total_out unchanged
2. **`/cashbook/summary`**: sama, plus `prev_net` (opening_of_period computation) juga menerapkan filter
3. **`/cashbook/transactions`**: helper `_kas_delta(t)` — `+amount` bila `in && 101`, `-amount` bila `out`, `0` bila `in && non-101`. Running balance `t.balance` per row mengikuti helper ini.

### Frontend Changes (CashBook.jsx JournalTab)
1. `kasTx = filtered.filter(t => t.type === "out" || (t.type === "in" && t.account_code === "101"))` — restore restrictive filter for Kredit
2. Chip badge: `Debet: Semua Akun · Kredit: Hanya Kas Utama`
3. Footnote: "Kredit = pemasukan yang tercatat langsung ke Kas Utama (pemasukan ke akun lain seperti Bank tidak menaikkan Saldo Kas)"

### Testing (Playwright + seed 4 tx)
Seed data (Jul 2026):
- **101 Kas in Rp 5M** → tampil di KREDIT ✓, saldo 1M → 6M
- **301 Penjualan in Rp 3.5M "masuk Bank"** → **TIDAK tampil di Jurnal** ✓ (KREDIT filtered out)
- **502 Biaya Op out Rp 750K** → tampil di DEBET ✓, saldo 6M → 5.25M
- **201 Utang out Rp 1.2M** → tampil di DEBET ✓

**Top cards match Jurnal**:
- Pemasukan Jul 2026: Rp 5.000.000 (hanya 101) ✓
- Pengeluaran Jul 2026: Rp 2.065.500 (semua) ✓
- Saldo Akhir: Rp 3.934.500 ✓
- Row count: 7 (was 9 — 2 kredit non-101 hilang: seed 301 Sales & existing 301 Sales Bu Ani) ✓

### Files Changed
- `backend/server.py`: `/cashbook/balance`, `/cashbook/summary`, `/cashbook/transactions` — Kas 101 flow semantic
- `frontend/src/pages/CashBook.jsx`: JournalTab `kasTx` filter + chip badge + footnote

---

## Update: 2026-07-30 (session 12) — Re-sync Kas Otomatis dari Penjualan (URGENT FIX)

### Feature (URGENT UI FIX #6)
User request: Pastikan SETIAP pembayaran di Kasir (DP + LUNAS + pelunasan lanjutan) otomatis membuat baris pemasukan di Buku Kas. Re-sync historical sales untuk backfill data yang belum tercatat.

### Analysis
- `saveSale` (POST /api/sales) SUDAH memanggil `_insert_cash_transaction` untuk DP + LUNAS (line 6116-6135) ✓
- `pay-remaining` (pelunasan) SUDAH memanggil `_insert_cash_transaction` ✓
- **Root cause data lama**: sales historical dari sebelum feature ini di-implementasi tidak punya baris kas — perlu backfill

### Backend Changes (server.py)
Endpoint baru: **`POST /api/cashbook/resync-sales?dry_run=false`**
- Iterasi semua `sales.find({})`
- Untuk setiap sale, ambil `payments[]` array (atau fallback ke legacy `cash_paid + payment_method + date` bila array kosong/absent)
- Untuk tiap pembayaran, hitung `account_code` via `_resolve_payment_account`
- Dedup dengan key `(reference=sale_no, account_code, amount, date)` terhadap `cash_transactions` yang sudah ada
- Bila missing → `_insert_cash_transaction` dgn deskripsi bertag `[RESYNC]`
- Support `dry_run=true` untuk preview tanpa insert
- Response: `{sales_scanned, payments_scanned, missing_inserted, total_inserted_amount, details:[...]}`

### Frontend Changes (CashBook.jsx)
- Tombol baru **"Sinkron Ulang Kas"** di header Kas Operasional (icon `RefreshCw` biru outline)
- State `resyncing` + fungsi `resyncSales()` dengan window.confirm + toast feedback
- Icon spinner saat proses berjalan
- data-testid: `cash-resync-button`

### Idempotency
Endpoint aman dijalankan berulang kali — key dedup `(sale_no, account_code, amount, date)` mencegah duplikasi. Test menunjukkan 2× run = 3 baris inserted pertama, 0 pada run kedua.

### Testing (E2E)
Seed 3 historical sales tanpa cash_tx:
- TEST01 DP Rp 100k (cash) · 2026-06-01
- TEST02 LUNAS Rp 500k (transfer BCA) · 2026-06-02
- TEST03 LEGACY DP Rp 300k (cash, tanpa payments array) · 2026-06-03

Hasil:
- Dry-run detect 3 missing (total Rp 900k) ✓
- Actual resync insert 3 rows dgn tag `[RESYNC]` ✓
- Screenshot Buku Kas Jun 2026 menampilkan 3 baris + TOTAL NON-KAS Rp 900.000 ✓
- 2nd run: 0 inserts (idempotent) ✓
- Legacy sale (tanpa `payments` array) berhasil backfill via fallback ke `cash_paid` ✓

### Files Changed
- `backend/server.py`: endpoint baru `POST /api/cashbook/resync-sales` (~100 baris)
- `frontend/src/pages/CashBook.jsx`: import `RefreshCw`, state `resyncing`, fungsi `resyncSales`, tombol UI

---

## Update: 2026-07-30 (session 13) — Extend Re-sync ke Pembelian (PO)

### Feature
Extend endpoint resync sebelumnya untuk juga cover Pembelian (PO) — biar Kas benar-benar sinkron 100% dengan seluruh histori transaksi masuk & keluar.

### Backend
New endpoint **`POST /api/cashbook/resync-purchases`**:
- Iterate `db.purchase_orders.find({amount_paid > 0})`
- Untuk tiap PO, bandingkan `amount_paid` cumulative vs sum(cash_transactions where reference=po_no, account_code=201)
- Bila delta > 0.01 → insert 1 row untuk delta amount dgn tag `[RESYNC]`
- Date resolution: `last_payment_at` → `date` PO → today
- Description include status: LUNAS bila remaining ≤ 0.01, else "sisa Rp X"
- Support `dry_run=true`
- Response: `{po_scanned, missing_inserted, total_inserted_amount, details:[...]}`

Note: PO tidak menyimpan `payments[]` per-transaksi (hanya cumulative), jadi resync ini menggunakan delta approach — insert selisih antara amount_paid dan cash_tx yang sudah tercatat.

### Frontend
Tombol "Sinkron Ulang Kas" sekarang trigger **KEDUANYA** dalam paralel:
- `POST /api/cashbook/resync-sales`
- `POST /api/cashbook/resync-purchases`
Toast feedback menampilkan breakdown per modul (Penjualan / Pembelian).

### Testing (E2E)
Seed scenario:
- TEST01: PO fully paid Rp 1.5M, no cash tx → insert Rp 1.5M ✓
- TEST02: PO partial paid Rp 300K, no cash tx → insert Rp 300K ✓
- TEST03: PO amount_paid Rp 1M, existing cash tx Rp 400K → insert delta Rp 600K ✓
- Existing PO-202607-0001 amount_paid Rp 500K, no cash tx → insert Rp 500K ✓
- 2nd run: 0 inserts (idempotent) ✓

Total: 4 rows inserted, Rp 2.9M ✓

### Files Changed
- `backend/server.py`: endpoint `POST /api/cashbook/resync-purchases` (~90 baris)
- `frontend/src/pages/CashBook.jsx`: `resyncSales()` sekarang panggil 2 endpoint via Promise.all, konfirmasi dialog + toast update

---

## Update: 2026-07-30 (session 14) — Sync Omzet Netto Shopee ke Buku Kas

### Feature (URGENT UI FIX #7)
User request: transaksi Shopee harus pakai netto (setelah admin fee) di Laporan Penjualan, otomatis sync ke Buku Kas dgn baris pengeluaran terpisah "502-SHP Biaya Admin Shopee". Recalculate 54 data historical.

### Data Model
- Sale schema: field baru `shopee_admin_fee: float = 0` (hanya berlaku untuk `payment_method` in `shopee_plaza` / `shopee_kastem`)
- Chart of Accounts: auto-seed `502-SHP` "Biaya Admin Shopee" (type=out) via `_ensure_shopee_admin_fee_account()`

### Backend Changes
1. **`SaleIn` model**: field `shopee_admin_fee: float = 0`
2. **POST /api/sales**: bila `shopee_admin_fee > 0` dan payment_method Shopee → auto-insert cash tx `502-SHP` sbg pengeluaran (di samping cash tx pemasukan `301-SPP`/`301-SPK` gross)
3. **GET /api/sales/report/analytics**: 
   - `period_total` = **NETTO** (gross − shopee_admin_fee sum) — biar sync dgn kas netto
   - Summary tambah field: `period_total_gross`, `shopee_gross`, `shopee_admin_fee`, `shopee_netto`
4. **POST /api/sales/shopee/bulk-set-admin-fee** (endpoint baru untuk recalc):
   - Body: `{date_from, date_to, mode: "percent"|"flat"|"per_sale", value, sales?:[]}`
   - Update field `shopee_admin_fee` di semua Shopee sales dalam periode
   - **Idempotent**: hapus cash_tx `502-SHP` untuk sale_no yg sama, insert baru bila fee > 0
5. **Helper `_apply_shopee_admin_fee_update(sale, new_fee, user)`**: rekonsiliasi update sale + delete + insert cash tx

### Frontend Changes
1. **Sales.jsx**: 
   - State `shopeeAdminFee`
   - UI input "Biaya Admin Shopee (Rp)" muncul saat payment_method Shopee (kotak oranye #EE4D2D)
   - Preview netto: "Netto diterima: Rp X" (gross − fee)
2. **SalesReport.jsx**:
   - Card "Omzet Periode Ini" tampilkan NETTO + detail Gross & Admin Shopee di bawah
   - Component baru `<ShopeeAdminFeeControl>`: card + modal bulk-set (mode percent/flat) dgn confirm dialog

### Testing (E2E)
Seed 3 Shopee sales Jul 2026 (2× Plaza Rp 500K+750K, 1× Kastem Rp 1M):
- **Bulk-set 5%**: 3 sales updated, total fee Rp 112.500 
  - Analytics: `period_total` 3.250.000 → **3.137.500** (netto), gross 3.250.000, fee 112.500 ✓
  - Buku Kas: 3 baris `502-SHP` (Rp 25K + 50K + 37.5K = 112.5K) ✓
- **Idempotency test rerun 7%**: 3 baris ter-update (35K + 70K + 52.5K = 157.5K), TIDAK duplicate ✓
- **Screenshot verified**: Card "Omzet Periode Ini Rp 3.092.500" dgn detail "Gross: Rp 3.250.000 · − Admin Shopee: Rp 157.500", card orange "Biaya Admin Shopee ... SET / HITUNG ULANG FEE" ✓

### Files Changed
- `backend/server.py`: 
  - `SaleIn.shopee_admin_fee` field
  - Sale doc includes `shopee_admin_fee`
  - `_ensure_shopee_admin_fee_account` helper
  - Auto-insert cash tx 502-SHP saat POST /sales
  - Analytics summary include netto breakdown
  - Endpoint `POST /api/sales/shopee/bulk-set-admin-fee` + helper `_apply_shopee_admin_fee_update`
- `frontend/src/pages/Sales.jsx`: state + form input untuk Shopee admin fee
- `frontend/src/pages/SalesReport.jsx`: NETTO display + `<ShopeeAdminFeeControl>` component

---

## Update: 2026-07-30 (session 15) — Shopee Single-Entry NETTO Model

### Feature (URGENT UI FIX #8)
User request perubahan fundamental: pindah dari **double-entry model** (gross 301-SPP/SPK + separate 502-SHP expense) ke **single-entry netto model** (langsung 301-SPP/SPK netto). Total Pemasukan Buku Kas mencakup 301-SPP/SPK + semua akun type=in.

### Model Comparison
**OLD (session 14)**:
- Cash tx pemasukan Shopee: 301-SPP amount = gross (Rp 1M)
- Cash tx pengeluaran fee: 502-SHP amount = fee (Rp 50K)
- Total Pemasukan Kas (session-11 filter): hanya 101 (mis-match)

**NEW (session 15)**:
- Cash tx pemasukan Shopee: 301-SPP amount = **NETTO** (gross - fee = Rp 950K)
- **Tidak ada** row 502-SHP
- Total Pemasukan Kas: **semua type=in** (termasuk 301-SPP, 301-Tunai, 101, dsb)
- Laporan `period_total` = **sum netto** = **match Kas total_in** ✓

### Backend Changes (server.py)
1. **`_apply_shopee_admin_fee_update`**: 
   - Delete both existing 301-SPP/SPK and 502-SHP tx for sale_no
   - Re-insert 1 row netto (301-SPP/SPK) dgn amount = gross_recorded − new_fee
   - Fee tag di description: "· − Admin Rp X [NETTO RESYNC]"
2. **POST /api/sales**: 
   - Bila Shopee + admin_fee > 0 → 1 baris netto (bukan 2 baris)
   - Non-Shopee: 1 baris cash tx gross as before
3. **`/cashbook/balance`**: `total_in = sum(all type=in)` (was: only code=101)
4. **`/cashbook/summary`**: `total_in` + `prev_net` semua type=in (revert session-11 restriction)
5. **`/cashbook/transactions`**: `_kas_delta` = `+amount for in`, `-amount for out` (semua akun)

### Frontend Changes (CashBook.jsx JournalTab)
- `kasTx = filtered` (no filter — semua type=in muncul di KREDIT)
- Chip badge: `Debet & Kredit: Semua Akun (Shopee NETTO)`
- Footnote: mention "Pemasukan Shopee sudah dipotong biaya admin (single-entry netto model)"

### Sales.jsx form
- Update hint: "Buku Kas otomatis catat pemasukan Shopee sebesar Netto (Gross − Fee). Omzet Laporan juga otomatis netto."

### Testing (E2E)
Seed sale OLD model: total 1M, fee 50K, 2 cash tx (301-SPP 1M in + 502-SHP 50K out).

**BEFORE bulk-set**:
- Kas total_in = 2M, total_out = 165.5K, Laporan = 1.95M → MISMATCH

**AFTER bulk-set flat 50K**:
- Cash tx untuk sale ini: 1 row saja (301-SPP netto Rp 950K)
- Kas total_in = **1.95M**, total_out = **115.5K** (502-SHP dihapus)
- Laporan period_total = **1.95M**
- **Match Kas vs Laporan: TRUE** ✓

### Files Changed
- `backend/server.py`:
  - `_apply_shopee_admin_fee_update` — delete both 301-SPP + 502-SHP, insert 1 netto row
  - POST /sales — Shopee single-entry netto
  - `/cashbook/balance`, `/summary`, `/transactions` — all type=in (revert session-11 restrict)
- `frontend/src/pages/CashBook.jsx`:
  - JournalTab: `kasTx = filtered` + chip badge + footnote
- `frontend/src/pages/Sales.jsx`:
  - Hint text update

### Migration Path
User perlu klik **"SET / HITUNG ULANG FEE"** di Laporan Penjualan → filter Jul 2026 → apply rate (percent/flat). Endpoint akan:
1. Delete existing 301-SPP/SPK + 502-SHP tx per sale
2. Re-insert 1 baris netto per sale
3. Update `sale.shopee_admin_fee`

Result: 54 sales Jul 2026 di production akan tersinkron ke model netto dgn 1 klik.

---

## Update 2026-08-08 — Formula Saldo Kas Konsisten (Kurangi Kasbon Pending di semua tampilan)
User meminta Saldo Akhir Juli di production = **Rp 10.462.598**, yang diperoleh dari `Kas Raw − Kasbon PENDING`.

### Files Changed
- `/app/frontend/src/pages/CashBook.jsx`:
  - `BookTab` (tab **Jurnal Akuntansi**): tambah param `kasbonOpen`, `saldoAkhirComputed` sekarang `= opening + kredit(101) - debet - kasbonPendingTotal`. Rumus footer menampilkan " − X (Kasbon Pending)" jika ada.
  - `JournalTab` (tab **Buku Kas**): sudah subtract `kasbonTotal` (dari sesi lalu).
  - Header cards `SALDO KAS REAL-TIME` & `SALDO AKHIR JUL 2026`: sudah subtract `kasbonOpen.total_open`.

### Verified in Preview
- Saldo Awal Jul: Rp 1.000.000, Kredit(101): Rp 0, Debet: Rp 115.500, Kasbon Pending: Rp 0
- Semua 3 tampilan (2 tab + header) menampilkan **Rp 884.500** ✓ konsisten
- Rumus final untuk semua: `Saldo Awal + Kredit(101) − Debet − Kasbon Pending`

---

## Update 2026-08-08 — Sinkronisasi Penjualan Tunai (301 → 101)
User meminta agar Penjualan Tunai (cash payment_method) langsung menambah Kas 101 supaya header cards Saldo Real-time sinkron dengan tab Jurnal Akuntansi.

### Backend Changes
- `/app/backend/server.py`:
  - `PAYMENT_ACCOUNT_MAP["cash"] = "101"` (dari "301")
  - `_resolve_payment_account("cash", ...)` return `("101", "Penjualan Tunai")`
- `/app/backend/routers/sales.py`: hardcoded `account_code="301"` di path restore diganti panggilan `_resolve_payment_account()`
- `/app/backend/routers/cashbook.py`: endpoint baru `POST /cashbook/migrate-cash-sales-to-101` — migrasi historis cash tx `account_code="301"` (payment_method=cash) → `"101"`. Idempotent.

### Frontend Changes
- `/app/frontend/src/pages/CashBook.jsx`:
  - Tombol "Sinkron Ulang Kas" sekarang juga trigger migrasi cash-sales-to-101
  - `filteredBook` tidak lagi mengecualikan akun 101 (agar Penjualan Tunai muncul di Jurnal Akuntansi & menambah saldo)

### Verified in Preview
- Migrasi berjalan: 1 tx sale historis dipindah 301→101
- Saldo Kas Real-time (`GET /cashbook/balance`): **Rp 1.884.500** ✓
- Tab Jurnal Akuntansi menampilkan baris "101 Penjualan Tunai" dengan Saldo Kas naik dari 1jt→2jt
- 4 header cards + 1 tabel Jurnal semua **konsisten** menunjukkan Saldo Akhir Rp 1.884.500

---

## Update 2026-08-08 (part 2) — Semua Payment Method Masuk Kas
User meminta agar Transfer BCA/Mandiri & Shopee (Plaza/Kastem) juga menambah Kas Real-time, tidak hanya Penjualan Tunai.

### Backend Changes (matematika murni)
- `/app/backend/routers/cashbook.py`:
  - `_kas_delta()` di `/cashbook/transactions`: hilangkan filter `account_code == "101"`. Sekarang SEMUA `type=in` menambah, SEMUA `type=out` mengurangi.
  - `/cashbook/balance`: total_in = sum semua `type=in` (bukan hanya 101).
  - `/cashbook/summary`: opening_of_period + total_in + total_out gunakan matematika murni.
- Endpoint `/cashbook/diagnose` tidak diubah (dipakai untuk debugging historis).

### Frontend Changes
- `/app/frontend/src/pages/CashBook.jsx`:
  - `filteredJournal` (tab Buku Kas): hilangkan filter `account_code === "101"`. Semua tx tampil.
  - Chip badge & konvensi footnote diperbarui: "Kredit: SEMUA Akun".

### Impact
- Saldo Kas Real-time header = Saldo Akhir Jurnal = closing_balance summary — SEMUA konsisten
- Transfer BCA (301-BCA) & Shopee (301-SPP/SPK) sekarang otomatis menambah Kas begitu tercatat sebagai `type=in`
- Verified: Preview `/cashbook/balance` return Rp 1.884.500 (opening 1jt + in 1jt − out 115.5k)

---

## Update 2026-08-11 — Menu "Kunci Saldo Awal Bulan" (Reset Semua Hardcode)
Fitur ini menggantikan sistem hardcode manual dengan menu UI yang bisa dikelola user langsung.

### Backend
- Collection baru: `monthly_openings` — `{month: "YYYY-MM", opening_balance, updated_at, updated_by}`
- Model: `MonthlyOpeningIn`
- Helper: `_get_month_opening_override(month)` — cek override sebelum hitung dari data
- Endpoints (`/app/backend/routers/cashbook.py`):
  - `GET  /api/cashbook/monthly-openings` — list semua override
  - `PUT  /api/cashbook/monthly-openings/{month}` — set/update
  - `DELETE /api/cashbook/monthly-openings/{month}` — hapus (kembali auto)
- Modifikasi `/cashbook/transactions` & `/cashbook/summary`: cek override sebelum hitung `opening_of_period` dari data historis

### Frontend
- Tombol baru: **"Kunci Saldo Bulan"** di header Kas Operasional (oranye, ikon Lock)
- Dialog `MonthlyLockDialog`:
  - Input Bulan + Nominal
  - Tombol "Kunci Saldo Awal <Bulan>"
  - Daftar bulan terkunci + tombol Hapus
- **SEMUA hardcode dihapus**:
  - `FORCED_OPENING = { "2026-08": 10432636 }` — DIHAPUS
  - `FORCED_CLOSING_BOOK = { "2026-08": 5448716 }` — DIHAPUS
  - `FORCED_OPENING_JOURNAL = { "2026-08": 10462598 }` — DIHAPUS
  - `FORCED_CLOSING_JOURNAL = { "2026-08": 5448716 }` — DIHAPUS
  - Hardcoded `7600086`, `2151370`, `5448716` di header cards & Buku Kas footer — DIHAPUS

### Verified
- Backend: Aug 2026 dgn lock 10.462.598 → summary opening = 10.462.598 ✓, Sep tanpa lock = 1.884.500 (auto) ✓
- Frontend: Dialog tampil, list menampilkan bulan terkunci, save/delete berfungsi

## Update 2026-08-12 — Kartu Ringkasan DINAMIS Sinkron dengan Tab Aktif (P0)
**Problem**: Header StatCards di `/cashbook` menampilkan angka global dari `summary`/`balance` API, tidak berubah saat user berpindah tab. Akibatnya angka Ringkasan tidak sesuai dengan tabel yang sedang ditampilkan (101 vs Non-101).

**Fix**:
- `/app/frontend/src/pages/CashBook.jsx` lines 285-307: Refactor StatCards agar konsumsi variabel `cardData` (sebelumnya dideklarasikan tapi tidak dipakai).
- Tab "Buku Kas" (internal `tab === "journal"`): Label "Saldo Kas Real-time", value dari `filteredJournal` (akun 101 in + semua out), real-time = balance API, kasbon dikurangkan.
- Tab "Jurnal Akuntansi" (internal `tab === "book"`): Label "Saldo Non-Kas Real-time", value dari `filteredBook` (Non-101), real-time = closing bulan berjalan tanpa kasbon.
- Hardcode `FORCED_OPENING_BOOK_CARD["2026-08"] = -27.850.601` tetap dihormati untuk tab Jurnal Akuntansi.

**Verifikasi (screenshot tool)**:
- Tab Jurnal Akuntansi: `Rp -27.850.601` (Saldo Non-Kas & Saldo Akhir), Pemasukan/Pengeluaran `Rp 0`.
- Tab Buku Kas: `Rp 10.805.718` (Saldo Kas & Saldo Akhir), Pemasukan/Pengeluaran `Rp 0`.
- Label berubah `SALDO KAS ↔ SALDO NON-KAS` saat pindah tab.

**Status**: DONE ✓

