import { useEffect, useMemo, useState } from "react";
import { api, formatIDR, formatApiError } from "../lib/api";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Calculator, ChevronRight, Eye, Trash2, ArrowRight, Fingerprint, CalendarDays, X } from "lucide-react";

function defaultPeriod() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function firstAndLastOfMonth(period) {
  const [y, m] = period.split("-").map(Number);
  const first = `${y}-${String(m).padStart(2, "0")}-01`;
  const lastDay = new Date(y, m, 0).getDate();
  const last = `${y}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;
  return { first, last };
}

export default function Payroll() {
  const [period, setPeriod] = useState(defaultPeriod());
  const _def = firstAndLastOfMonth(defaultPeriod());
  const [dateFrom, setDateFrom] = useState(_def.first);
  const [dateTo, setDateTo] = useState(_def.last);
  const [rangeLoading, setRangeLoading] = useState(false);
  const [rangeInfo, setRangeInfo] = useState(null);  // { matched_employees, total_days, unmatched_details }
  const [showDetailAbsen, setShowDetailAbsen] = useState(false);
  const [employees, setEmployees] = useState([]);
  const [attendance, setAttendance] = useState({});
  const [preview, setPreview] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [fpImporting, setFpImporting] = useState(false);
  const [fpResult, setFpResult] = useState(null);
  const [draftLoaded, setDraftLoaded] = useState(false);  // apakah draft berhasil dimuat dari localStorage
  const [lastSavedAt, setLastSavedAt] = useState(null);   // waktu terakhir auto-save
  const navigate = useNavigate();

  // ---------- DRAFT AUTOSAVE ke localStorage per periode ----------
  const draftKey = (p) => `payroll_draft_${p}`;

  const loadDraft = (p) => {
    try {
      const raw = localStorage.getItem(draftKey(p));
      if (!raw) return null;
      return JSON.parse(raw);
    } catch { return null; }
  };

  const saveDraft = (p, att) => {
    try {
      localStorage.setItem(draftKey(p), JSON.stringify({ attendance: att, saved_at: Date.now() }));
      setLastSavedAt(Date.now());
    } catch { /* quota exceeded */ }
  };

  const clearDraft = (p) => {
    try { localStorage.removeItem(draftKey(p)); } catch { /* ignore */ }
  };

  const load = async () => {
    setLoading(true);
    try {
      const [emp, rns] = await Promise.all([
        api.get("/employees"),
        api.get("/payroll/runs"),
      ]);
      const activeEmp = emp.data.filter((e) => e.active !== false);
      setEmployees(activeEmp);
      setRuns(rns.data);

      // Initialize default attendance
      const defaults = {};
      activeEmp.forEach((e) => {
        defaults[e.id] = { days_worked: 22, overtime_hours: 0, bonus: 0, deduction: 0, late_penalty_minutes: 0 };
      });

      // Merge dengan draft dari localStorage (jika ada) untuk periode saat ini
      const draft = loadDraft(period);
      if (draft && draft.attendance) {
        const merged = { ...defaults };
        Object.entries(draft.attendance).forEach(([empId, val]) => {
          if (defaults[empId]) merged[empId] = { ...defaults[empId], ...val };
        });
        setAttendance(merged);
        setDraftLoaded(true);
        toast.info(`📥 Draft absensi periode ${period} dimuat kembali (tersimpan ${new Date(draft.saved_at).toLocaleString("id-ID")})`);
      } else {
        setAttendance(defaults);
        setDraftLoaded(false);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  // Autosave: setiap attendance/period berubah → simpan ke localStorage (debounced ~600ms)
  useEffect(() => {
    if (loading || employees.length === 0) return;
    const t = setTimeout(() => saveDraft(period, attendance), 600);
    return () => clearTimeout(t);
  }, [attendance, period, loading, employees.length]);

  // Saat period berubah manual: reload draft yg sesuai
  useEffect(() => {
    if (loading || employees.length === 0) return;
    const defaults = {};
    employees.forEach((e) => {
      defaults[e.id] = { days_worked: 22, overtime_hours: 0, bonus: 0, deduction: 0, late_penalty_minutes: 0 };
    });
    const draft = loadDraft(period);
    if (draft && draft.attendance) {
      const merged = { ...defaults };
      Object.entries(draft.attendance).forEach(([empId, val]) => {
        if (defaults[empId]) merged[empId] = { ...defaults[empId], ...val };
      });
      setAttendance(merged);
      setDraftLoaded(true);
    } else {
      setAttendance(defaults);
      setDraftLoaded(false);
    }
  }, [period]);  // eslint-disable-line

  // Auto-adjust default date range saat period berubah (kecuali user sudah customize)
  useEffect(() => {
    const { first, last } = firstAndLastOfMonth(period);
    setDateFrom(first);
    setDateTo(last);
  }, [period]);

  const fetchRangeSummary = async (from, to) => {
    if (!from || !to) return;
    setRangeLoading(true);
    try {
      const { data } = await api.get(`/attendance/range/summary?date_from=${from}&date_to=${to}`);
      setRangeInfo(data);
      // Merge ke attendance table
      setAttendance((curr) => {
        const next = { ...curr };
        Object.entries(data.summary || {}).forEach(([empId, v]) => {
          next[empId] = {
            ...(next[empId] || { days_worked: 22, overtime_hours: 0, bonus: 0, deduction: 0, late_penalty_minutes: 0 }),
            days_worked: v.days_worked,
            overtime_hours: v.overtime_hours,
            late_penalty_minutes: Number(v.late_penalty_minutes || 0),
          };
        });
        return next;
      });
      const msg = data.matched_employees > 0
        ? `${data.matched_employees} karyawan ter-update dari rentang ${from} s/d ${to} (${data.total_days} hari-karyawan)`
        : `Rentang ${from} s/d ${to} — ${data.total_days} hari-karyawan (${data.unmatched_details?.length || 0} PIN belum ter-mapping)`;
      toast.success(msg);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat rentang absensi");
    } finally {
      setRangeLoading(false);
    }
  };

  const updateAtt = (id, field, value) => {
    setAttendance((a) => ({ ...a, [id]: { ...a[id], [field]: Number(value) || 0 } }));
  };

  const runPreview = async () => {
    try {
      const { data } = await api.post("/payroll/preview", { period, attendance });
      setPreview(data);
      toast.success("Pratinjau dihitung");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal pratinjau");
    }
  };

  const runFinal = async () => {
    // Warning ringan (tidak memblokir) — user tetap bisa lanjut
    if (employees.length === 0) {
      toast.warning("⚠️ Tidak ada karyawan aktif — proses tetap dilanjutkan, tapi slip mungkin kosong");
    } else {
      const totalDays = Object.values(attendance).reduce((s, a) => s + Number(a?.days_worked || 0), 0);
      const totalOT = Object.values(attendance).reduce((s, a) => s + Number(a?.overtime_hours || 0), 0);
      if (totalDays === 0 && totalOT === 0) {
        toast.warning("⚠️ Semua Hari Hadir & Lembur = 0 — slip akan bernilai kosong. Proses tetap dilanjutkan.");
      }
    }
    if (!window.confirm(`Jalankan payroll untuk periode ${period}? Ini akan menggantikan data lama jika ada.`)) return;
    setRunning(true);
    try {
      const { data } = await api.post("/payroll/run", { period, attendance });
      toast.success(`✅ Payroll ${period} berhasil dijalankan — ${data.employee_count} slip generated (Total Net Rp ${Number(data.total_net || 0).toLocaleString("id-ID")})`);
      clearDraft(period);  // draft dibersihkan setelah berhasil generate
      navigate(`/payroll/${period}`);
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || "Kesalahan tidak diketahui";
      toast.error(`❌ Gagal menjalankan payroll: ${detail}`);
    } finally {
      setRunning(false);
    }
  };

  const deleteRun = async (p) => {
    if (!window.confirm(`Hapus payroll periode ${p}?`)) return;
    try {
      await api.delete(`/payroll/runs/${p}`);
      toast.success("Payroll dihapus");
      await load();
    } catch (err) {
      toast.error("Gagal menghapus");
    }
  };

  const onFingerprintImport = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setFpImporting(true);
    setFpResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post(`/attendance/import?period=${period}`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      // Merge into attendance: overwrite days_worked & overtime_hours for matched employees
      setAttendance((curr) => {
        const next = { ...curr };
        Object.entries(data.summary).forEach(([empId, v]) => {
          next[empId] = {
            ...(next[empId] || { days_worked: 22, overtime_hours: 0, bonus: 0, deduction: 0, late_penalty_minutes: 0 }),
            days_worked: v.days_worked,
            overtime_hours: v.overtime_hours,
            late_penalty_minutes: Number(v.late_penalty_minutes || 0),
          };
        });
        return next;
      });
      setFpResult(data);
      toast.success(`${data.matched_employees} karyawan ter-update dari ${data.total_scans} scan`);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal import fingerprint");
    } finally {
      setFpImporting(false);
    }
  };

  const totals = useMemo(() => {
    if (!preview) return null;
    return preview.totals;
  }, [preview]);

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Operasi</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Jalankan Payroll</h1>
          <p className="text-sm text-zinc-500 mt-1">Pilih periode, atur kehadiran/lembur, hitung otomatis lalu generate slip.</p>
        </div>
        <div className="flex items-end gap-3">
          <label className="block">
            <span className="block text-xs font-semibold text-zinc-900 uppercase tracking-wider mb-1.5">Periode</span>
            <input
              data-testid="payroll-period-select"
              type="month"
              value={period}
              onChange={(e) => { setPeriod(e.target.value); setPreview(null); }}
              className="rounded-none border border-zinc-300 px-3 py-2.5 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none font-mono"
            />
          </label>
          <button
            data-testid="preview-payroll-button"
            onClick={runPreview}
            title="Hitung pratinjau tanpa menyimpan"
            className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-5 py-2.5 text-sm font-semibold hover:bg-zinc-50 inline-flex items-center gap-2"
          >
            <Calculator className="w-4 h-4" /> Hitung Pratinjau
          </button>
          <button
            data-testid="generate-payroll-button"
            onClick={runFinal}
            title="Simpan payroll & generate slip gaji untuk semua karyawan"
            className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2 cursor-pointer"
          >
            {running ? "Memproses…" : (<>Generate Slip <ArrowRight className="w-4 h-4" /></>)}
          </button>
        </div>
      </div>

      {/* Autosave indicator */}
      {employees.length > 0 && !loading && (
        <div className="mt-2 flex items-center gap-3 text-[11px] text-zinc-500 font-mono">
          {lastSavedAt && (
            <span data-testid="autosave-indicator" className="inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 bg-[#008A00] rounded-full animate-pulse" />
              Draft tersimpan otomatis · {new Date(lastSavedAt).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          )}
          {draftLoaded && (
            <button
              data-testid="reset-draft-btn"
              onClick={() => {
                if (window.confirm("Reset semua input Hari Hadir/Lembur/Bonus/Potongan ke default?")) {
                  const defaults = {};
                  employees.forEach((e) => { defaults[e.id] = { days_worked: 22, overtime_hours: 0, bonus: 0, deduction: 0 }; });
                  setAttendance(defaults);
                  clearDraft(period);
                  setDraftLoaded(false);
                  toast.success("Draft di-reset ke default");
                }
              }}
              className="text-[#E81123] hover:underline uppercase tracking-widest font-bold"
            >
              Reset Draft
            </button>
          )}
        </div>
      )}

      {/* Helper hint saat tombol disabled atau kondisi tertentu */}
      {(() => {
        if (loading) return null;
        if (employees.length === 0) {
          return (
            <div data-testid="generate-hint-no-employees" className="mt-3 p-3 border-l-4 border-yellow-400 bg-yellow-50 text-sm">
              <b>Belum bisa Generate Slip:</b> Belum ada karyawan aktif. Silakan tambah karyawan di menu <Link to="/employees" className="text-[#002FA7] underline font-bold">Karyawan</Link>.
            </div>
          );
        }
        const totalDays = Object.values(attendance).reduce((s, a) => s + Number(a?.days_worked || 0), 0);
        const totalOT = Object.values(attendance).reduce((s, a) => s + Number(a?.overtime_hours || 0), 0);
        if (totalDays === 0 && totalOT === 0) {
          return (
            <div data-testid="generate-hint-no-attendance" className="mt-3 p-3 border-l-4 border-orange-400 bg-orange-50 text-sm">
              <b>⚠️ Absen belum diinput.</b> Semua karyawan memiliki Hari Hadir = 0 dan Lembur = 0. Silakan isi tabel kehadiran di bawah, atau import file finger, atau klik <b>Terapkan Rentang</b> untuk mengambil data absen dari periode terpilih.
            </div>
          );
        }
        return null;
      })()}

      {/* Range Absensi (Cross-Month Support) */}
      {employees.length > 0 && (
        <div className="mt-6 p-4 border border-zinc-200 bg-[#002FA7]/5 flex flex-wrap items-end gap-3">
          <div className="flex items-center gap-2 mr-2">
            <CalendarDays className="w-4 h-4 text-[#002FA7]" />
            <div className="text-xs font-bold uppercase tracking-widest text-[#002FA7]">Rentang Absensi (Fleksibel · Cross-Month)</div>
          </div>
          <label className="block">
            <span className="block text-[10px] font-bold text-zinc-700 uppercase tracking-wider mb-1">Dari Tanggal</span>
            <input
              data-testid="attendance-date-from"
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="rounded-none border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="block text-[10px] font-bold text-zinc-700 uppercase tracking-wider mb-1">Sampai Tanggal</span>
            <input
              data-testid="attendance-date-to"
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="rounded-none border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none"
            />
          </label>
          <button
            data-testid="apply-attendance-range"
            onClick={() => fetchRangeSummary(dateFrom, dateTo)}
            disabled={rangeLoading || !dateFrom || !dateTo}
            className="rounded-none bg-[#002FA7] text-white px-5 py-2 text-xs font-bold uppercase tracking-wider hover:bg-[#002080] disabled:opacity-50"
          >
            {rangeLoading ? "Memuat…" : "Terapkan Rentang"}
          </button>
          <button
            data-testid="open-detail-absen"
            onClick={() => setShowDetailAbsen(true)}
            className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-4 py-2 text-xs font-bold uppercase tracking-wider hover:bg-zinc-50 inline-flex items-center gap-2"
          >
            <Eye className="w-3.5 h-3.5" /> Detail Absen Harian
          </button>
          {rangeInfo && (
            <div className="text-[11px] font-mono text-zinc-600 ml-auto">
              {rangeInfo.matched_employees} ter-mapping · {rangeInfo.total_days} hari-karyawan · {rangeInfo.unmatched_details?.length || 0} PIN unmatched
            </div>
          )}
        </div>
      )}

      {employees.length === 0 && !loading && (
        <div className="mt-6 p-6 border border-zinc-200 bg-white">
          <div className="text-sm text-zinc-700">Belum ada karyawan aktif. Tambahkan karyawan terlebih dahulu.</div>
          <Link to="/employees" className="mt-3 inline-flex items-center gap-2 text-[#002FA7] font-semibold text-sm">
            Ke halaman Karyawan <ChevronRight className="w-4 h-4" />
          </Link>
        </div>
      )}

      {/* Attendance & Adjustments */}
      {employees.length > 0 && (
        <div className="mt-6">
          <div className="flex items-end justify-between mb-2">
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Input Kehadiran & Penyesuaian</div>
            <label
              data-testid="import-fingerprint-label"
              className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-50 inline-flex items-center gap-2 cursor-pointer"
            >
              <Fingerprint className="w-3.5 h-3.5" />
              {fpImporting ? "Mengimpor…" : "Import Fingerprint (XLSX/CSV)"}
              <input
                data-testid="import-fingerprint-input"
                type="file"
                accept=".xlsx,.xls,.csv"
                className="hidden"
                onChange={onFingerprintImport}
                disabled={fpImporting}
              />
            </label>
          </div>

          {fpResult && (
            <div className="mb-3 p-3 border border-zinc-200 bg-zinc-50">
              <div className="flex items-start justify-between">
                <div className="text-xs">
                  <div className="font-mono text-zinc-900">
                    <span className="font-semibold">{fpResult.matched_employees}</span> karyawan ter-update · <span className="font-semibold">{fpResult.total_scans}</span> scan diproses
                  </div>
                  {fpResult.unmatched_niks?.length > 0 && (
                    <div className="mt-1 text-[#E81123]">
                      PIN tidak cocok dengan NIK karyawan: <span className="font-mono">{fpResult.unmatched_niks.join(", ")}</span>
                    </div>
                  )}
                </div>
                <button onClick={() => setFpResult(null)} className="text-zinc-400 hover:text-zinc-700 text-xs uppercase tracking-widest font-semibold">tutup</button>
              </div>

              {fpResult.unmatched_details?.length > 0 && (
                <div className="mt-3 border border-zinc-200 bg-white overflow-x-auto">
                  <div className="px-3 py-2 bg-yellow-50 border-b border-zinc-200 text-[10px] uppercase tracking-widest font-bold text-yellow-900">
                    Hasil parsing PIN yang belum ter-mapping ke karyawan (silakan sesuaikan NIK karyawan)
                  </div>
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="bg-zinc-50 border-b border-zinc-200 text-[10px] font-bold text-zinc-600 uppercase tracking-widest">
                        <th className="px-3 py-2">PIN</th>
                        <th className="px-3 py-2">Nama (dari file)</th>
                        <th className="px-3 py-2 text-right">Hari Hadir</th>
                        <th className="px-3 py-2 text-right">Lembur (jam)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fpResult.unmatched_details.map((u) => (
                        <tr key={u.pin} data-testid={`unmatched-row-${u.pin}`} className="border-b border-zinc-100">
                          <td className="px-3 py-2 font-mono text-zinc-800">{u.pin}</td>
                          <td className="px-3 py-2 text-zinc-900">{u.name || <span className="text-zinc-400">—</span>}</td>
                          <td className="px-3 py-2 text-right font-mono">{u.days_worked}</td>
                          <td className="px-3 py-2 text-right font-mono">{u.overtime_hours}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <div className="border border-zinc-200 bg-white overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                  <th className="px-4 py-3">NIK</th>
                  <th className="px-4 py-3">Nama</th>
                  <th className="px-4 py-3 text-right">Gaji Pokok</th>
                  <th className="px-4 py-3 text-right">Hari Hadir</th>
                  <th className="px-4 py-3 text-right">Lembur (Jam)</th>
                  <th className="px-4 py-3 text-right text-[#002FA7]">Lembur (Rp)</th>
                  <th className="px-4 py-3 text-right" title="Total jam terlambat > 4 jam per hari (auto dari mesin finger). Input dalam jam; disimpan sebagai menit di backend.">Terlambat (Jam)</th>
                  <th className="px-4 py-3 text-right text-[#E81123]">Terlambat (Rp)</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((emp) => {
                  const a = attendance[emp.id] || {};
                  const basic = Number(emp.basic_salary || 0);
                  // Formula pro-rata: ((Gaji Pokok / 26) / 7) / 60
                  const wagePerMin = basic > 0 ? ((basic / 26) / 7) / 60 : 0;
                  const wagePerHour = wagePerMin * 60;
                  const otHours = Number(a.overtime_hours || 0);
                  const lateMin = Number(a.late_penalty_minutes || 0);
                  const lembRp = otHours * wagePerHour;
                  const lateHours = lateMin / 60;
                  const lateRp = lateMin * wagePerMin;
                  return (
                    <tr key={emp.id} className="border-b border-zinc-100 hover:bg-zinc-50/80">
                      <td className="px-4 py-2.5 font-mono text-xs text-zinc-700">{emp.nik}</td>
                      <td className="px-4 py-2.5">
                        <div className="font-medium text-zinc-900">{emp.name}</div>
                        <div className="text-xs text-zinc-500">{emp.position} · {emp.ptkp_status}</div>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-right text-zinc-700">{formatIDR(basic)}</td>
                      <td className="px-4 py-2.5">
                        <input data-testid={`att-days-${emp.id}`} type="number" min="0" max="31" value={a.days_worked || 0}
                          onChange={(e) => updateAtt(emp.id, "days_worked", e.target.value)}
                          className="w-20 rounded-none border border-zinc-300 px-2 py-1 text-sm font-mono text-right focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none ml-auto block" />
                      </td>
                      <td className="px-4 py-2.5">
                        <input data-testid={`att-ot-${emp.id}`} type="number" min="0" step="0.5" value={a.overtime_hours || 0}
                          onChange={(e) => updateAtt(emp.id, "overtime_hours", e.target.value)}
                          className="w-20 rounded-none border border-zinc-300 px-2 py-1 text-sm font-mono text-right focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none ml-auto block" />
                      </td>
                      <td data-testid={`att-ot-rp-${emp.id}`} className={`px-4 py-2.5 font-mono text-right text-xs ${lembRp > 0 ? "text-[#002FA7] font-bold" : "text-zinc-400"}`}>
                        {formatIDR(Math.round(lembRp))}
                      </td>
                      <td className="px-4 py-2.5">
                        <input data-testid={`att-late-hours-${emp.id}`} type="number" min="0" step="0.5" value={lateHours ? Number(lateHours.toFixed(2)) : 0}
                          onChange={(e) => updateAtt(emp.id, "late_penalty_minutes", (Number(e.target.value) || 0) * 60)}
                          title="Total jam terlambat > 4 jam. Otomatis dari import absensi. Bila > 0, memicu potongan otomatis."
                          className={`w-24 rounded-none border px-2 py-1 text-sm font-mono text-right focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none ml-auto block ${lateMin > 0 ? "border-red-400 bg-red-50 text-red-700" : "border-zinc-300"}`} />
                      </td>
                      <td data-testid={`att-late-rp-${emp.id}`} className={`px-4 py-2.5 font-mono text-right text-xs ${lateRp > 0 ? "text-[#E81123] font-bold" : "text-zinc-400"}`}>
                        {formatIDR(Math.round(lateRp))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="px-1 mt-2 text-[11px] text-zinc-500 font-mono">
            Kolom Rp otomatis dihitung dgn rumus pro-rata: <span className="font-bold">Upah/menit = ((Gaji Pokok / 26) / 7) / 60</span>. Lembur (Rp) = Jam × 60 × Upah/menit · Terlambat (Rp) = Jam × 60 × Upah/menit.
          </div>
        </div>
      )}

      {/* Preview */}
      {preview && (
        <div className="mt-8 fade-up">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
            <PreviewCard label="Karyawan" value={totals.count} mono />
            <PreviewCard label="Total Bruto" value={formatIDR(totals.gross)} />
            <PreviewCard label="Total PPh 21" value={formatIDR(totals.pph21)} />
            <PreviewCard label="Total Net (estimasi)" value={formatIDR(totals.net)} highlight />
          </div>

          <div className="mt-4 border border-zinc-200 bg-white overflow-x-auto">
            <div className="px-4 py-3 border-b border-zinc-200 flex items-center justify-between">
              <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Rincian Pratinjau — Periode {preview.period}</div>
              <div className="text-xs text-zinc-500 font-mono">Belum tersimpan</div>
            </div>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                  <th className="px-4 py-3">Karyawan</th>
                  <th className="px-4 py-3 text-right">Bruto</th>
                  <th className="px-4 py-3 text-right">BPJS Karyawan</th>
                  <th className="px-4 py-3 text-right">PPh 21</th>
                  <th className="px-4 py-3 text-right">Take Home</th>
                </tr>
              </thead>
              <tbody>
                {preview.slips.map((s) => {
                  const bpjs = s.deductions.bpjs_kesehatan_employee + s.deductions.jht_employee + s.deductions.jp_employee;
                  return (
                    <tr key={s.employee_id} className="border-b border-zinc-100">
                      <td className="px-4 py-2.5">
                        <div className="font-medium text-zinc-900">{s.name}</div>
                        <div className="text-xs text-zinc-500 font-mono">{s.nik} · {s.ptkp_status}</div>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-right text-zinc-900">{formatIDR(s.earnings.gross)}</td>
                      <td className="px-4 py-2.5 font-mono text-right text-zinc-700">{formatIDR(bpjs)}</td>
                      <td className="px-4 py-2.5 font-mono text-right text-zinc-700">{formatIDR(s.deductions.pph21)}</td>
                      <td className="px-4 py-2.5 font-mono text-right font-semibold text-zinc-900">{formatIDR(s.net_salary)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* History */}
      <div className="mt-10">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold mb-2">Riwayat Payroll</div>
        <div className="border border-zinc-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                <th className="px-4 py-3">Periode</th>
                <th className="px-4 py-3 text-right">Karyawan</th>
                <th className="px-4 py-3 text-right">Total Bruto</th>
                <th className="px-4 py-3 text-right">PPh 21</th>
                <th className="px-4 py-3 text-right">Total Net</th>
                <th className="px-4 py-3 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Belum ada periode yang dijalankan.</td></tr>
              )}
              {runs.map((r) => (
                <tr key={r.period} data-testid={`run-row-${r.period}`} className="border-b border-zinc-100 hover:bg-zinc-50/80">
                  <td className="px-4 py-3 font-mono text-zinc-900">{r.period}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-700">{r.employee_count}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(r.total_gross)}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(r.total_pph21)}</td>
                  <td className="px-4 py-3 font-mono text-right font-semibold text-zinc-900">{formatIDR(r.total_net)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <Link to={`/payroll/${r.period}`} className="p-1.5 hover:bg-zinc-100 text-zinc-700" title="Lihat detail">
                        <Eye className="w-4 h-4" />
                      </Link>
                      <button onClick={() => deleteRun(r.period)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {/* Detail Absen Modal */}
      {showDetailAbsen && (
        <DetailAbsenModal
          initialFrom={dateFrom}
          initialTo={dateTo}
          onClose={() => setShowDetailAbsen(false)}
        />
      )}
    </div>
  );
}

function DetailAbsenModal({ initialFrom, initialTo, onClose }) {
  // Default: no filter → tampilkan SEMUA data yang sudah diimport
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [pin, setPin] = useState("");
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async (params) => {
    setLoading(true);
    try {
      const p = params !== undefined ? params : { from, to, pin };
      const qs = new URLSearchParams();
      // Kalau kosong, kirim rentang super luas agar backend return semua
      qs.set("date_from", p.from || "2000-01-01");
      qs.set("date_to", p.to || "2099-12-31");
      if (p.pin) qs.set("pin", p.pin);
      const { data } = await api.get(`/attendance/daily/list?${qs.toString()}`);
      setItems(data.items || []);
      setMeta({
        count: data.count,
        total_overtime: data.total_overtime_hours,
        unique_dates: data.unique_dates,
        unique_pins: data.unique_pins,
      });
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat detail absen");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load({ from: "", to: "", pin: "" }); /* eslint-disable-next-line */ }, []);

  // Quick actions
  const showAll = () => { setFrom(""); setTo(""); setPin(""); load({ from: "", to: "", pin: "" }); };
  const applyMonth = (period) => {
    if (!period) return;
    const [y, m] = period.split("-").map(Number);
    const last = new Date(y, m, 0).getDate();
    const f = `${y}-${String(m).padStart(2, "0")}-01`;
    const t = `${y}-${String(m).padStart(2, "0")}-${String(last).padStart(2, "0")}`;
    setFrom(f); setTo(t);
    load({ from: f, to: t, pin });
  };
  const applyCurrentMonth = () => {
    const d = new Date();
    applyMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white border border-zinc-300 w-full max-w-6xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center bg-[#002FA7]">
              <CalendarDays className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Detail Absensi Harian</div>
              <h3 className="font-bold text-zinc-900 text-lg">Semua Data Absensi ter-Import</h3>
            </div>
          </div>
          <button data-testid="detail-absen-close" onClick={onClose} className="p-2 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
        </div>

        {/* Filter bar */}
        <div className="p-4 border-b border-zinc-200 bg-zinc-50 space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="block">
              <span className="block text-[10px] font-bold text-zinc-700 uppercase tracking-wider mb-1">Dari</span>
              <input data-testid="detail-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="rounded-none border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none" />
            </label>
            <label className="block">
              <span className="block text-[10px] font-bold text-zinc-700 uppercase tracking-wider mb-1">Sampai</span>
              <input data-testid="detail-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} className="rounded-none border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none" />
            </label>
            <label className="block">
              <span className="block text-[10px] font-bold text-zinc-700 uppercase tracking-wider mb-1">PIN (opsional)</span>
              <input data-testid="detail-pin" type="text" value={pin} onChange={(e) => setPin(e.target.value)} placeholder="1, 2, 10..." className="rounded-none border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none w-32" />
            </label>
            <button data-testid="detail-apply" onClick={() => load()} disabled={loading} className="rounded-none bg-[#002FA7] text-white px-4 py-2 text-xs font-bold uppercase tracking-wider hover:bg-[#002080] disabled:opacity-50">
              {loading ? "Memuat…" : "Terapkan Filter"}
            </button>
          </div>
          {/* Quick actions */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider mr-1">Cepat:</span>
            <button
              data-testid="detail-show-all"
              onClick={showAll}
              className="rounded-none bg-[#008A00] text-white px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider hover:bg-[#006D00]"
            >
              Tampilkan Semua
            </button>
            <button
              data-testid="detail-current-month"
              onClick={applyCurrentMonth}
              className="rounded-none bg-white border border-zinc-300 text-zinc-900 px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider hover:bg-zinc-50"
            >
              Bulan Ini
            </button>
            <label className="inline-flex items-center gap-1.5">
              <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider">Ke Bulan Spesifik:</span>
              <input data-testid="detail-month-quick" type="month" onChange={(e) => applyMonth(e.target.value)} className="rounded-none border border-zinc-300 px-2 py-1 text-xs font-mono focus:border-[#002FA7] focus:outline-none" />
            </label>
          </div>
          {meta && (
            <div className="flex flex-wrap gap-4 text-[11px] font-mono text-zinc-700 pt-1">
              <span><b className="text-zinc-900">{meta.count}</b> baris</span>
              <span><b className="text-zinc-900">{meta.unique_dates}</b> tanggal</span>
              <span><b className="text-zinc-900">{meta.unique_pins}</b> PIN</span>
              <span>Total lembur: <b className="text-[#002FA7]">{meta.total_overtime}</b> jam</span>
              {!from && !to && <span className="text-[#008A00] font-bold">· Menampilkan SEMUA data</span>}
              {(from || to) && <span className="text-[#002FA7]">· Filter: {from || "…"} s/d {to || "…"}</span>}
            </div>
          )}
        </div>

        {/* Table */}
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-zinc-100 border-b border-zinc-200">
              <tr className="text-[10px] font-bold text-zinc-600 uppercase tracking-widest">
                <th className="px-3 py-2 w-12 text-center">No</th>
                <th className="px-3 py-2">Tanggal</th>
                <th className="px-3 py-2">PIN</th>
                <th className="px-3 py-2">Nama</th>
                <th className="px-3 py-2">NIK Karyawan</th>
                <th className="px-3 py-2 text-center">Jam Masuk</th>
                <th className="px-3 py-2 text-center">Jam Pulang</th>
                <th className="px-3 py-2 text-right">Lembur (jam)</th>
                <th className="px-3 py-2 text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={9} className="px-4 py-8 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
              {!loading && items.length === 0 && (
                <tr><td colSpan={9} className="px-4 py-8 text-center text-zinc-400 font-mono text-xs">Tidak ada data pada rentang ini.</td></tr>
              )}
              {items.map((it, i) => {
                const matched = !!it.employee_id;
                return (
                  <tr key={`${it.pin}-${it.date}-${i}`} data-testid="detail-row" className={`border-b border-zinc-100 ${matched ? "" : "bg-yellow-50/50"}`}>
                    <td className="px-3 py-2 text-center font-mono text-[11px] text-zinc-500">{i + 1}</td>
                    <td className="px-3 py-2 font-mono text-xs text-zinc-900">{it.date}</td>
                    <td className="px-3 py-2 font-mono text-xs font-bold text-zinc-900">{it.pin}</td>
                    <td className="px-3 py-2 text-xs">{it.employee_name || <span className="text-zinc-300">—</span>}</td>
                    <td className="px-3 py-2 font-mono text-[11px] text-zinc-600">{it.employee_nik || <span className="text-zinc-300">—</span>}</td>
                    <td className="px-3 py-2 text-center font-mono text-xs">{it.in_time || <span className="text-zinc-300">—</span>}</td>
                    <td className="px-3 py-2 text-center font-mono text-xs">{it.out_time || <span className="text-zinc-300">—</span>}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{Number(it.overtime_hours || 0).toFixed(2)}</td>
                    <td className="px-3 py-2 text-center">
                      {matched ? (
                        <span className="inline-block bg-[#008A00]/15 text-[#008A00] border border-[#008A00]/30 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest">OK</span>
                      ) : (
                        <span className="inline-block bg-yellow-400 text-yellow-900 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest">Unmatched</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-end gap-2 p-3 border-t border-zinc-200 bg-zinc-50">
          <button data-testid="detail-close-btn" onClick={onClose} className="rounded-none bg-white border border-zinc-300 text-zinc-900 px-4 py-2 text-xs font-bold uppercase tracking-wider hover:bg-zinc-50">Tutup</button>
        </div>
      </div>
    </div>
  );
}

function PreviewCard({ label, value, highlight, mono }) {
  return (
    <div className={`bg-white p-5`}>
      <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
      <div className={`font-mono mt-2 ${highlight ? "text-2xl font-semibold text-[#002FA7]" : "text-xl text-zinc-900"}`}>{value}</div>
    </div>
  );
}
