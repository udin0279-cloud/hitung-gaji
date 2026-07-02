import { useEffect, useMemo, useState } from "react";
import { api, formatIDR, formatApiError } from "../lib/api";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Calculator, ChevronRight, Eye, Trash2, ArrowRight, Fingerprint } from "lucide-react";

function defaultPeriod() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function Payroll() {
  const [period, setPeriod] = useState(defaultPeriod());
  const [employees, setEmployees] = useState([]);
  const [attendance, setAttendance] = useState({});
  const [preview, setPreview] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [fpImporting, setFpImporting] = useState(false);
  const [fpResult, setFpResult] = useState(null);
  const navigate = useNavigate();

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

      // initialize default attendance: 22 days
      const att = {};
      activeEmp.forEach((e) => {
        att[e.id] = { days_worked: 22, overtime_hours: 0, bonus: 0, deduction: 0 };
      });
      setAttendance(att);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

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
    if (!window.confirm(`Jalankan payroll untuk periode ${period}? Ini akan menggantikan data lama jika ada.`)) return;
    setRunning(true);
    try {
      await api.post("/payroll/run", { period, attendance });
      toast.success(`Payroll ${period} berhasil dijalankan`);
      navigate(`/payroll/${period}`);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menjalankan payroll");
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
            ...(next[empId] || { days_worked: 22, overtime_hours: 0, bonus: 0, deduction: 0 }),
            days_worked: v.days_worked,
            overtime_hours: v.overtime_hours,
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
            disabled={employees.length === 0}
            className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-5 py-2.5 text-sm font-semibold hover:bg-zinc-50 inline-flex items-center gap-2 disabled:opacity-50"
          >
            <Calculator className="w-4 h-4" /> Hitung Pratinjau
          </button>
          <button
            data-testid="generate-payroll-button"
            onClick={runFinal}
            disabled={running || employees.length === 0}
            className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 disabled:opacity-60 inline-flex items-center gap-2"
          >
            {running ? "Memproses…" : (<>Generate Slip <ArrowRight className="w-4 h-4" /></>)}
          </button>
        </div>
      </div>

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
            <div className="mb-3 p-3 border border-zinc-200 bg-zinc-50 flex items-start justify-between">
              <div className="text-xs">
                <div className="font-mono text-zinc-900">
                  <span className="font-semibold">{fpResult.matched_employees}</span> karyawan ter-update · <span className="font-semibold">{fpResult.total_scans}</span> scan diproses
                </div>
                {fpResult.unmatched_niks?.length > 0 && (
                  <div className="mt-1 text-[#E81123]">
                    NIK tidak ditemukan: <span className="font-mono">{fpResult.unmatched_niks.join(", ")}</span>
                  </div>
                )}
              </div>
              <button onClick={() => setFpResult(null)} className="text-zinc-400 hover:text-zinc-700 text-xs uppercase tracking-widest font-semibold">tutup</button>
            </div>
          )}

          <div className="border border-zinc-200 bg-white overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                  <th className="px-4 py-3">NIK</th>
                  <th className="px-4 py-3">Karyawan</th>
                  <th className="px-4 py-3 text-right">Gaji Pokok</th>
                  <th className="px-4 py-3 text-right">Hari Hadir</th>
                  <th className="px-4 py-3 text-right">Lembur (jam)</th>
                  <th className="px-4 py-3 text-right">Bonus</th>
                  <th className="px-4 py-3 text-right">Potongan Lain</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((emp) => {
                  const a = attendance[emp.id] || {};
                  return (
                    <tr key={emp.id} className="border-b border-zinc-100 hover:bg-zinc-50/80">
                      <td className="px-4 py-2.5 font-mono text-xs text-zinc-700">{emp.nik}</td>
                      <td className="px-4 py-2.5">
                        <div className="font-medium text-zinc-900">{emp.name}</div>
                        <div className="text-xs text-zinc-500">{emp.position} · {emp.ptkp_status}</div>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-right text-zinc-700">{formatIDR(emp.basic_salary)}</td>
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
                      <td className="px-4 py-2.5">
                        <input data-testid={`att-bonus-${emp.id}`} type="number" min="0" step="10000" value={a.bonus || 0}
                          onChange={(e) => updateAtt(emp.id, "bonus", e.target.value)}
                          className="w-28 rounded-none border border-zinc-300 px-2 py-1 text-sm font-mono text-right focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none ml-auto block" />
                      </td>
                      <td className="px-4 py-2.5">
                        <input data-testid={`att-deduct-${emp.id}`} type="number" min="0" step="10000" value={a.deduction || 0}
                          onChange={(e) => updateAtt(emp.id, "deduction", e.target.value)}
                          className="w-28 rounded-none border border-zinc-300 px-2 py-1 text-sm font-mono text-right focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none ml-auto block" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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
