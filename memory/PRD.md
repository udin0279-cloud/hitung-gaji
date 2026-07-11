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

