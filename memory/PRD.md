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
