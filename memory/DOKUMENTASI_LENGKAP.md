# 📋 Dokumentasi Lengkap Aplikasi HR Payroll — demoweb.biz

**Klien**: Sistem HR Payroll Indonesia  
**URL Production**: https://demoweb.biz  
**URL Preview**: https://hitung-gaji.preview.emergentagent.com  
**Domain**: demoweb.biz (Hostinger)  
**Platform Hosting**: Emergent Cloud (Kubernetes + MongoDB)  
**Tanggal Dokumentasi**: Februari 2026

---

## 🎯 Ringkasan Proyek

Aplikasi HR Payroll Indonesia yang dibangun dari nol dengan perhitungan otomatis lengkap sesuai regulasi Indonesia (UU HPP 2022, BPJS Rates 2024, PPh 21 Progresif). Dilengkapi dengan Employee Portal, Multi-Level Admin, Modul Izin & Cuti, dan integrasi email (Resend) + WhatsApp (Fonnte).

### Tech Stack
| Komponen | Teknologi |
|---|---|
| Frontend | React + TailwindCSS + shadcn/ui |
| Backend | FastAPI (Python) |
| Database | MongoDB |
| Auth | JWT + HTTP-only Cookies + bcrypt |
| PDF Generation | ReportLab |
| Excel Generation | openpyxl |
| Email | Resend (domain: payroll@demoweb.biz) |
| WhatsApp | Fonnte |
| Hosting | Emergent Cloud (Kubernetes) |

---

## 📅 Timeline Pembangunan

### 🚀 Fase 1: MVP Core (Awal — 2026-02)
**Fitur:**
- Autentikasi Admin (JWT + httpOnly cookie, 12h access token)
- Auto-seed admin user dari `.env`
- CRUD Karyawan (NIK unique, gaji pokok, tunjangan, BPJS, NPWP, PTKP)
- Perhitungan Payroll Otomatis:
  - Gaji Pokok pro-rata by days worked
  - Overtime (basic/173 × 1.5 per jam)
  - BPJS Kesehatan (1% karyawan / 4% perusahaan, cap 12jt)
  - BPJS Ketenagakerjaan (JHT 2%, JP 1%, JKK, JKM)
  - PPh 21 Progresif (5/15/25/30/35% sesuai UU HPP 2022)
  - PTKP Table (TK/0 s/d K/3)
  - Biaya Jabatan 5% (max 6jt/tahun)
  - Non-NPWP surcharge +20%
- Dashboard dengan hero stat + 12-month trend chart
- Payslip printable A4

**Screens:** `/login`, `/`, `/employees`, `/payroll`, `/payroll/:period`, `/payslip/:slipId`

---

### 📄 Fase 2: PDF & Bulk Import
**Fitur:**
- **PDF Payslip Export** via ReportLab (professional layout A4)
- **Bulk Import Karyawan** via CSV (dengan template download)
- **Import Fingerprint Attendance** dari file .xlsx/.xls/.csv (auto-aggregate days_worked + overtime hours per karyawan)

---

### 🎁 Fase 3: THR & Bank Transfer
**Fitur:**
- **Perhitungan THR** (13th month bonus untuk Idul Fitri):
  - Proporsional untuk masa kerja < 12 bulan
  - Perhitungan PPh 21 THR terpisah (metode isolasi)
- **Halaman `/thr`** — period picker + preview + run + history
- **Bank Transfer Export** dalam 5 format:
  - Generic CSV
  - BCA
  - Mandiri
  - BNI
  - BRI

---

### 📧 Fase 4: Email Integration (Resend)
**Fitur:**
- **Kirim Payslip via Email** (individual atau bulk)
- Endpoint: `POST /api/payroll/payslip/{id}/email`, `POST /api/payroll/runs/{period}/email-all`
- Attachment PDF payslip
- Fallback mock mode saat API key belum diset
- **Email Log** tersimpan di collection `email_logs`
- Domain custom **payroll@demoweb.biz** (setelah verifikasi DKIM + SPF + MX di Hostinger)

---

### 👥 Fase 5: Employee Portal + Magic Link Login
**Fitur:**
- **Portal Karyawan** di `/portal` — karyawan login lihat payslip sendiri
- **Magic Link Login** — karyawan input email/NIK, sistem kirim link login
- Halaman `/portal/payslip/:id` — lihat & download payslip pribadi

---

### 📊 Fase 6: Bukti Potong 1721-A1 (Pajak Tahunan)
**Fitur:**
- Generate Bukti Potong 1721-A1 (PDF)
- Dashboard Pajak Tahunan per karyawan
- Aggregate total pendapatan & PPh21 setahun

---

### 💾 Fase 7: Database Backup & Restore
**Fitur:**
- **Export Database** ke JSON (backup semua collection)
- **Import Database** dari JSON (restore)
- Menu di `Konfigurasi → Backup Database`

---

### 💬 Fase 8: WhatsApp Integration (Fonnte)
**Fitur:**
- **Kirim Payslip via WhatsApp** ke nomor karyawan
- Endpoint: `POST /api/payroll/payslip/{id}/whatsapp`, `POST /api/payroll/runs/{period}/whatsapp-all`
- Otomatis format nomor Indonesia (08... → 62...)
- Kirim link download PDF (bukan attachment karena limit WA)

---

### ⚙️ Fase 9: Editable Config (Settings)
**Fitur:**
- Halaman `/settings` untuk edit runtime config:
  - PPh21 progressive brackets (bisa update sesuai regulasi baru)
  - PTKP table
  - BPJS rates (Kesehatan/JHT/JP/JKK/JKM)
  - Biaya Jabatan rate & max
  - Standard workdays per month
  - Overtime multiplier

---

### 🗓️ Fase 10: Modul Izin & Cuti (2026-02)
**5 Jenis Izin:**
1. 🕐 **Datang Terlambat** — durasi menit (min 5 menit)
2. 🏃 **Pulang Awal** — input **jam pulang** (time picker), auto-hitung selisih dari 17:00
3. 🚫 **Tidak Masuk** — multi-day (tanggal mulai–selesai)
4. ❤️ **Sakit** — dengan opsi upload surat dokter (PDF/JPG, max 2MB)
5. ⚡ **Lembur** — jam mulai-selesai (auto cross-midnight), auto-hitung durasi

**Alur:**
- Karyawan submit dari `/portal/leave`
- HR review di `/leave` (approve/reject dengan catatan)
- Email notifikasi otomatis: ke HR saat submit, ke karyawan saat status berubah
- Sidebar badge real-time menampilkan jumlah pending (polling 60s)

**Export Laporan Bulanan:**
- **Excel (.xlsx)**: header bermerk + kolom lengkap + blok RINGKASAN
- **PDF landscape A4**: tabel berwarna per-status + tanda-tangan Direktur + HR untuk laporan resmi

---

### 🔐 Fase 11: Multi-Level Admin (Role-Based Access)
**Role:**
- 🔵 **Super Admin** — akses penuh (Dashboard, Karyawan, Payroll, THR, Izin & Cuti, Kelola User, Konfigurasi)
- 🟢 **HR Izin & Cuti** — hanya akses menu Izin & Cuti (approve/reject + export laporan)

**Fitur:**
- Halaman `/users` — CRUD user admin dengan role selector visual
- Backend role guards: `require_super_admin` + `require_leave_access`
- Login redirect cerdas: super_admin → `/`, hr_leave → `/leave`
- Safety guard: tidak bisa hapus akun sendiri & tidak bisa hapus Super Admin terakhir
- Auto-migration: legacy role `admin` → `super_admin` saat startup

---

### 💰 Fase 12: Komponen Payroll Baru
**Tambahan Fields di Data Karyawan:**
1. **Tunjangan Jabatan** — taxable (masuk base BPJS & PPh21)
2. **Tunjangan Transport** — non-taxable benefit (masuk gross, TIDAK masuk base)
3. **Tunjangan Lain-lain** — non-taxable benefit
4. **Potongan Pinjaman** — angsuran bulanan + tenor total + tenor sudah dibayar

**Loan Tracking Otomatis:**
- Auto-kurangi tiap payroll run
- Auto-berhenti saat `tenor_paid >= tenor_total`
- Auto-rollback saat payroll di-delete atau di-run ulang
- Info di payslip: "Angsuran 1/12, sisa 11 bulan"

**Rumus BPJS/PPh21:**
- Taxable base = basic + fixed_allowance + tunjangan_jabatan
- Non-taxable = tunjangan_transport + tunjangan_lainnya (hanya di gross, tidak di base)

---

### 📱 Fase 13: Mobile Responsive
**Fitur:**
- Sidebar desktop `hidden md:flex` — tampil ≥768px
- Top bar mobile dengan tombol hamburger untuk membuka drawer
- Drawer slide dari kiri saat hamburger diklik
- Padding halaman responsif: `p-4 sm:p-6 lg:p-10`
- Stat cards menggunakan `min-w-0 + truncate` supaya label tidak terpotong
- Export card layout `flex-col sm:flex-row` — stack vertikal di HP

---

## 🔗 Integrasi Pihak Ketiga

### 1. Resend (Email)
- **Fungsi**: Kirim payslip & notifikasi izin via email
- **Domain**: `payroll@demoweb.biz` (verified via DKIM/SPF/MX)
- **DNS Records ditambahkan di Hostinger**:
  - TXT `resend._domainkey` (DKIM)
  - TXT `send` (SPF: v=spf1 include:amazonses.com ~all)
  - MX `send` → feedback-smtp.us-east-1.amazonses.com (priority 10)
  - TXT `_dmarc` (DMARC: v=DMARC1; p=none;)
- **Free tier**: 3.000 email/bulan (cukup untuk 100 karyawan × 1 payslip/bulan)
- **Env var**: `RESEND_API_KEY`, `SENDER_EMAIL=payroll@demoweb.biz`

### 2. Fonnte (WhatsApp Gateway)
- **Fungsi**: Kirim payslip via WhatsApp
- **Paket**: Personal Rp 60.000/bulan (unlimited messages)
- **Setup**: Scan QR di dashboard Fonnte pakai nomor WA perusahaan
- **Env var**: `FONNTE_TOKEN`
- **Website**: https://fonnte.com

---

## 📊 Struktur Database (MongoDB Collections)

| Collection | Isi |
|---|---|
| `users` | Admin/HR users (super_admin, hr_leave) |
| `employees` | Data karyawan (basic_salary, tunjangan, loan, PTKP, dll) |
| `payroll_runs` | Header per periode payroll |
| `payslips` | Detail slip gaji per karyawan per periode |
| `thr_runs` | Header per periode THR |
| `thr_slips` | Detail slip THR per karyawan |
| `attendance_imports` | Log import fingerprint |
| `app_config` | Runtime config (PPh21, PTKP, BPJS, dll) |
| `email_logs` | Log kirim email |
| `portal_reset_tokens` | Magic link tokens untuk portal karyawan |
| `leave_requests` | Pengajuan izin & cuti (5 jenis) |

---

## 🎯 API Endpoints Utama

### Authentication
- `POST /api/auth/register` — Daftar admin
- `POST /api/auth/login` — Login (setel cookie)
- `POST /api/auth/logout` — Logout (clear cookie)
- `GET /api/auth/me` — Info user saat ini

### Employee Management (Super Admin)
- `GET /api/employees` — List karyawan
- `POST /api/employees` — Tambah karyawan
- `PUT /api/employees/{id}` — Update karyawan
- `DELETE /api/employees/{id}` — Hapus karyawan
- `POST /api/employees-import` — Import CSV bulk

### Payroll
- `POST /api/payroll/preview` — Preview perhitungan (tidak simpan)
- `POST /api/payroll/run` — Jalankan payroll (simpan slip)
- `GET /api/payroll/runs` — History periode
- `GET /api/payroll/runs/{period}/slips` — Detail slip per periode
- `GET /api/payroll/payslip/{id}` — Detail 1 slip
- `GET /api/payroll/payslip/{id}/pdf` — PDF download
- `POST /api/payroll/payslip/{id}/email` — Kirim email
- `POST /api/payroll/payslip/{id}/whatsapp` — Kirim WA
- `POST /api/payroll/runs/{period}/email-all` — Kirim email ke semua
- `POST /api/payroll/runs/{period}/whatsapp-all` — Kirim WA ke semua
- `GET /api/payroll/runs/{period}/bank-export?format=` — Export bank transfer

### THR
- `POST /api/payroll/thr/preview` / `/run`
- `GET /api/payroll/thr/runs` / `/{period}/slips`

### Attendance
- `POST /api/attendance/import?period=` — Import fingerprint xlsx/csv

### Leave & Permission (Portal)
- `POST /api/portal/leave` — Ajukan izin (multipart)
- `GET /api/portal/leave` — Riwayat pengajuan sendiri
- `DELETE /api/portal/leave/{id}` — Batalkan (jika masih pending)
- `GET /api/portal/leave/{id}/attachment` — Download lampiran

### Leave & Permission (Admin — Super Admin + HR Leave)
- `GET /api/leave?status=&type=` — List semua pengajuan
- `GET /api/leave/stats` — Ringkasan pending/approved/rejected/total
- `PUT /api/leave/{id}/approve` — Setujui (kirim email ke karyawan)
- `PUT /api/leave/{id}/reject` — Tolak (wajib alasan, kirim email)
- `GET /api/leave/report/{period}/excel` — Export laporan bulanan Excel
- `GET /api/leave/report/{period}/pdf` — Export laporan bulanan PDF

### User Management (Super Admin only)
- `GET /api/users` — List admin users
- `POST /api/users` — Buat user baru
- `PUT /api/users/{id}` — Edit user (name/role/password)
- `DELETE /api/users/{id}` — Hapus user

### Configuration (Super Admin only)
- `GET /api/config/constants` — Baca runtime config
- `PUT /api/config/constants` — Update PPh21/PTKP/BPJS/dll

### Backup & Restore (Super Admin only)
- `GET /api/admin/export-database` — Export JSON
- `POST /api/admin/import-database` — Import JSON

### Portal Karyawan
- `POST /api/portal/login` — Login (email + NIK)
- `POST /api/portal/magic-link` — Request magic link via email
- `GET /api/portal/magic-login?token=` — Verify magic link
- `GET /api/portal/payslips` — Riwayat payslip sendiri
- `GET /api/portal/bukti-potong/{year}/pdf` — Download Bukti Potong 1721-A1

---

## 🎨 Design System

**Theme**: Swiss Modernism + High-Contrast Klein Blue
- Primary color: **#002FA7** (Klein Blue)
- Fonts:
  - Heading: **Cabinet Grotesk**
  - Body: **IBM Plex Sans**
  - Mono: **JetBrains Mono**
- Layout: Clean sans-serif, uppercase micro labels, monospace numbers
- Icons: Lucide React

---

## 🔐 Kredensial Default

| Role | Email | Password |
|---|---|---|
| Super Admin | `admin@payroll.id` | `admin123` |
| HR Izin & Cuti | `hrcuti@payroll.id` | `cuti123` |
| Portal Karyawan | via email + NIK | Magic link |

⚠️ **Rekomendasi keamanan**: ganti password default setelah go-live!

---

## 💰 Struktur Biaya Bulanan

| Item | Provider | Biaya | Bayar Ke |
|---|---|---|---|
| Hosting App | Emergent | 50 credits/bln | Emergent |
| WhatsApp | Fonnte Personal | Rp 60.000 | fonnte.com |
| Email | Resend Free (≤3rb/bln) | Rp 0 | resend.com |
| Domain | Hostinger | Rp 15rb/bln (Rp 180rb/thn) | hostinger.com |

**Total estimasi UMKM (~30 karyawan): Rp 225-525rb/bulan**

---

## 🚀 Fitur Backlog (Belum Diimplementasi)

### Prioritas Tinggi (P1)
- Cuti Tahunan dengan kuota tracking
- Auto-add lembur approved ke Payroll bulan berikutnya
- Halaman "Daftar Pinjaman Aktif" (dashboard monitoring)

### Prioritas Menengah (P2)
- Audit Log HR (siapa approve/reject apa & kapan)
- 2-level approval (Atasan → HR)
- Notif WhatsApp untuk izin (selain email)
- Visual Attendance Dashboard (grafik kehadiran)
- Scheduled Auto-Send payslip (APScheduler tiap tanggal 25)
- Rekap lembur bulanan per karyawan di laporan PDF

### Prioritas Rendah (P3)
- PWA (Progressive Web App) install ke home screen
- Multi-company / multi-branch support
- Employee Profile Update di portal (karyawan ubah phone/email sendiri)

---

## 📞 Support & Kontak

- **Emergent Platform Support**: support@emergent.sh
- **Fonnte Support**: https://fonnte.com/help
- **Resend Support**: https://resend.com/support
- **Hostinger Support**: https://hostinger.com/contact

---

## 📝 Catatan Deployment

### Environment Variables (di Emergent Secrets)
```
MONGO_URL=<managed by Emergent>
DB_NAME=<managed by Emergent>
JWT_SECRET=<random string 32+ chars>
ADMIN_EMAIL=admin@payroll.id
ADMIN_PASSWORD=<strong password>
RESEND_API_KEY=<from resend.com dashboard>
SENDER_EMAIL=payroll@demoweb.biz
COMPANY_NAME=<Nama Perusahaan>
PUBLIC_APP_URL=https://demoweb.biz
FONNTE_TOKEN=<from fonnte.com dashboard>
FONNTE_BASE_URL=https://api.fonnte.com
CORS_ORIGINS=https://demoweb.biz
```

### Cara Re-deploy:
1. Login Emergent Dashboard
2. Klik project HR Payroll
3. Klik **"Re-deploy changes"**
4. Tunggu ~2-5 menit
5. Verify di https://demoweb.biz

### Cara Rollback (jika ada bug production):
1. Emergent Dashboard → project
2. Klik **"Deployments"** history
3. Pilih versi sebelumnya → **"Rollback"**

---

## ✅ Testing Coverage

Sepanjang pengembangan, sistem telah melewati testing komprehensif:
- **Iteration 1-7**: MVP + THR + Email + WhatsApp + Portal + Backup
- **Iteration 8**: Leave Module (Backend 20/20 + Frontend 15/15)
- **Iteration 9**: Multi-Level Admin (Backend 27/27 + Frontend 15/15)
- **Iteration 10**: Payroll Components (Backend 10/10 + Frontend UI verified)

Semua test report tersimpan di `/app/test_reports/`.

---

**Dokumen ini di-generate otomatis dari session pengembangan.**  
**Versi terakhir: Februari 2026**

