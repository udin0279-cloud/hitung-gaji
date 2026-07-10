import { useEffect, useState } from "react";
import { useNavigate, Link, useParams } from "react-router-dom";
import { api, formatIDR, API } from "../lib/api";
import { usePortalAuth } from "../context/PortalAuthContext";
import { LogOut, Square, Download, FileText, Gift, ChevronLeft, Printer, Receipt, CalendarDays } from "lucide-react";

export function PortalDashboard() {
  const { employee, logout } = usePortalAuth();
  const navigate = useNavigate();
  const [payslips, setPayslips] = useState([]);
  const [thr, setThr] = useState([]);
  const [year, setYear] = useState(new Date().getFullYear());
  const [annual, setAnnual] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [p, t] = await Promise.all([api.get("/portal/payslips"), api.get("/portal/thr")]);
        setPayslips(p.data);
        setThr(t.data);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(`/portal/annual/${year}`);
        setAnnual(data);
      } catch {
        setAnnual(null);
      }
    })();
  }, [year]);

  const handleLogout = async () => {
    await logout();
    navigate("/portal/login");
  };

  if (!employee) return null;

  return (
    <div className="min-h-screen bg-zinc-50">
      <header className="bg-white border-b border-zinc-200">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/portal" className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-[#002FA7] flex items-center justify-center">
              <Square className="w-4 h-4 text-white" fill="white" />
            </div>
            <div>
              <div className="font-heading font-bold text-zinc-900 leading-none">PAYROLL.ID</div>
              <div className="text-[10px] text-zinc-500 uppercase tracking-widest mt-0.5">Employee Portal</div>
            </div>
          </Link>
          <button
            data-testid="portal-logout-button"
            onClick={handleLogout}
            className="inline-flex items-center gap-2 border border-zinc-300 hover:bg-zinc-900 hover:text-white px-3 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors"
          >
            <LogOut className="w-3.5 h-3.5" /> Keluar
          </button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">
        {/* Profile */}
        <div className="border border-zinc-200 bg-white p-6 lg:p-8">
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Selamat datang</div>
          <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900">{employee.name}</h1>
              <div className="text-sm text-zinc-500 mt-1">{employee.position} · {employee.department}</div>
            </div>
            <div className="text-right">
              <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">NIK</div>
              <div className="font-mono text-lg text-zinc-900">{employee.nik}</div>
            </div>
          </div>
          <div className="mt-6 pt-6 border-t border-zinc-200 flex flex-wrap gap-2">
            <Link
              data-testid="link-portal-leave"
              to="/portal/leave"
              className="inline-flex items-center gap-2 bg-[#002FA7] text-white px-4 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-[#002FA7]/90"
            >
              <CalendarDays className="w-3.5 h-3.5" /> Ajukan Cuti & Izin
            </Link>
          </div>
        </div>

        {/* Annual Tax Summary */}
        <div className="mt-8">
          <div className="flex items-end justify-between gap-3 mb-3 flex-wrap">
            <div className="flex items-center gap-2">
              <Receipt className="w-4 h-4 text-zinc-700" />
              <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Ringkasan Pajak Tahunan</div>
            </div>
            <div className="flex items-center gap-2">
              <select
                data-testid="annual-year-select"
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                className="rounded-none border border-zinc-300 px-3 py-1.5 text-xs font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
              >
                {[0, 1, 2].map((d) => {
                  const y = new Date().getFullYear() - d;
                  return <option key={y} value={y}>{y}</option>;
                })}
              </select>
              <a
                data-testid="bukti-potong-button"
                href={`${API}/portal/bukti-potong/${year}/pdf`}
                target="_blank"
                rel="noreferrer"
                className="bg-[#002FA7] text-white px-3 py-1.5 text-xs font-semibold uppercase tracking-wider hover:bg-[#002FA7]/90 inline-flex items-center gap-2"
              >
                <Download className="w-3.5 h-3.5" /> Unduh Bukti Potong 1721-A1
              </a>
            </div>
          </div>
          {annual && annual.months_count > 0 ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
              <Stat label="Total Bruto" value={formatIDR(annual.totals.gross)} sub={`${annual.months_count} bulan`} />
              <Stat label="Total PPh 21" value={formatIDR(annual.totals.pph21 + annual.totals.thr_pph21)} sub="termasuk THR" />
              <Stat label="Total BPJS" value={formatIDR(annual.totals.bpjs_employee)} sub="Kes + JHT + JP" />
              <Stat label="Take Home" value={formatIDR(annual.totals.net)} sub="setelah potongan" highlight />
            </div>
          ) : (
            <div className="p-4 border border-zinc-200 bg-zinc-50 text-sm text-zinc-500 font-mono">
              Belum ada penghasilan untuk tahun {year}.
            </div>
          )}
        </div>

        {/* Payslips */}
        <div className="mt-8">
          <div className="flex items-center gap-2 mb-3">
            <FileText className="w-4 h-4 text-zinc-700" />
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Slip Gaji Bulanan</div>
          </div>
          <div className="border border-zinc-200 bg-white overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                  <th className="px-4 py-3">Periode</th>
                  <th className="px-4 py-3 text-right">Bruto</th>
                  <th className="px-4 py-3 text-right">PPh 21</th>
                  <th className="px-4 py-3 text-right">Take Home</th>
                  <th className="px-4 py-3 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {loading && <tr><td colSpan={5} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
                {!loading && payslips.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Belum ada slip gaji.</td></tr>
                )}
                {payslips.map((s) => (
                  <tr key={s.id} data-testid={`portal-slip-${s.period}`} className="border-b border-zinc-100 hover:bg-zinc-50/80">
                    <td className="px-4 py-3 font-mono text-zinc-900">{s.period}</td>
                    <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(s.gross)}</td>
                    <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(s.pph21)}</td>
                    <td className="px-4 py-3 font-mono text-right font-semibold text-zinc-900">{formatIDR(s.net_salary)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <Link to={`/portal/payslip/${s.id}`} className="px-2.5 py-1 border border-zinc-300 hover:bg-zinc-900 hover:text-white text-xs font-semibold uppercase tracking-wider transition-colors">
                          Lihat
                        </Link>
                        <a
                          href={`${API}/portal/payslip/${s.id}/pdf`}
                          target="_blank"
                          rel="noreferrer"
                          className="p-1.5 border border-zinc-300 hover:bg-zinc-900 hover:text-white transition-colors"
                          title="Unduh PDF"
                        >
                          <Download className="w-3.5 h-3.5" />
                        </a>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* THR */}
        {thr.length > 0 && (
          <div className="mt-8">
            <div className="flex items-center gap-2 mb-3">
              <Gift className="w-4 h-4 text-zinc-700" />
              <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Tunjangan Hari Raya</div>
            </div>
            <div className="border border-zinc-200 bg-white overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                    <th className="px-4 py-3">Periode</th>
                    <th className="px-4 py-3">Formula</th>
                    <th className="px-4 py-3 text-right">THR Bruto</th>
                    <th className="px-4 py-3 text-right">PPh 21</th>
                    <th className="px-4 py-3 text-right">Net</th>
                  </tr>
                </thead>
                <tbody>
                  {thr.map((t) => (
                    <tr key={t.id} className="border-b border-zinc-100">
                      <td className="px-4 py-3 font-mono text-zinc-900">{t.period}</td>
                      <td className="px-4 py-3 text-xs text-zinc-600 font-mono">{t.formula}</td>
                      <td className="px-4 py-3 font-mono text-right">{formatIDR(t.thr_gross)}</td>
                      <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(t.pph21_thr)}</td>
                      <td className="px-4 py-3 font-mono text-right font-semibold">{formatIDR(t.thr_net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export function PortalPayslip() {
  const { slipId } = useParams();
  const [slip, setSlip] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(`/portal/payslip/${slipId}`);
        setSlip(data);
      } finally {
        setLoading(false);
      }
    })();
  }, [slipId]);

  if (loading) return <div className="p-10 text-sm text-zinc-400 font-mono">Memuat…</div>;
  if (!slip) return <div className="p-10 text-sm text-zinc-700">Slip tidak ditemukan</div>;

  const e = slip.earnings;
  const d = slip.deductions;
  const t = slip.tax_detail;

  return (
    <div className="min-h-screen bg-zinc-50">
      <div className="no-print bg-white border-b border-zinc-200 px-6 py-4 flex items-center justify-between">
        <Link to="/portal" className="inline-flex items-center gap-1 text-xs uppercase tracking-widest text-zinc-500 hover:text-zinc-900 font-semibold">
          <ChevronLeft className="w-3.5 h-3.5" /> Kembali
        </Link>
        <div className="flex items-center gap-2">
          <a
            data-testid="portal-download-pdf"
            href={`${API}/portal/payslip/${slip.id}/pdf`}
            target="_blank"
            rel="noreferrer"
            className="border border-zinc-300 px-4 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-50 inline-flex items-center gap-2"
          >
            <Download className="w-3.5 h-3.5" /> Unduh PDF
          </a>
          <button
            onClick={() => window.print()}
            className="bg-[#002FA7] text-white px-4 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-[#002FA7]/90 inline-flex items-center gap-2"
          >
            <Printer className="w-3.5 h-3.5" /> Cetak
          </button>
        </div>
      </div>

      <div className="print-area max-w-3xl mx-auto bg-white border border-zinc-200 my-8 p-10">
        <div className="flex items-start justify-between pb-6 border-b-2 border-zinc-900">
          <div>
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 bg-[#002FA7] flex items-center justify-center">
                <Square className="w-4 h-4 text-white" fill="white" />
              </div>
              <div className="font-heading font-black text-xl tracking-tight">PAYROLL.ID</div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Slip Gaji</div>
            <div className="font-heading text-2xl font-bold mt-1">Periode {slip.period}</div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-6 mt-6 pb-6 border-b border-zinc-200">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Nama</div>
            <div className="text-base font-semibold mt-0.5">{slip.name}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">NIK</div>
            <div className="font-mono text-sm mt-0.5">{slip.nik}</div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-6 mt-6">
          <div>
            <div className="text-[11px] uppercase tracking-widest font-bold text-[#008A00] pb-2 border-b border-zinc-300">Pendapatan</div>
            <Row label="Gaji Pokok" value={e.basic_salary} />
            {e.fixed_allowance > 0 && <Row label="Tunjangan Tetap" value={e.fixed_allowance} />}
            {e.tunjangan_jabatan > 0 && <Row label="Tj. Jabatan" value={e.tunjangan_jabatan} />}
            {e.tunjangan_transport > 0 && <Row label="Tj. Transport" value={e.tunjangan_transport} />}
            {e.tunjangan_lainnya > 0 && <Row label="Tj. Lain-lain" value={e.tunjangan_lainnya} />}
            {e.insentif_individu > 0 && <Row label="Insentif Individu" value={e.insentif_individu} />}
            {e.overtime > 0 && <Row label="Lembur" value={e.overtime} />}
            {e.bonus > 0 && <Row label="Bonus" value={e.bonus} />}
            <Row label="Total Bruto" value={e.gross} bold border />
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-widest font-bold text-[#E81123] pb-2 border-b border-zinc-300">Potongan</div>
            <Row label="BPJS Kesehatan" value={d.bpjs_kesehatan_employee} />
            <Row label="JHT" value={d.jht_employee} />
            <Row label="JP" value={d.jp_employee} />
            <Row label="PPh 21" value={d.pph21} />
            {d.loan > 0 && <Row label="Angsuran Pinjaman" value={d.loan} />}
            <Row label="Total Potongan" value={d.total} bold border />
          </div>
        </div>

        <div className="mt-8 bg-zinc-900 text-white p-6 flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-400 font-semibold">Take Home Pay</div>
            <div className="text-xs text-zinc-400 mt-1 font-mono">Hari kerja: {slip.attendance.days_worked} · Lembur: {slip.attendance.overtime_hours} jam</div>
          </div>
          <div className="font-mono text-3xl lg:text-4xl font-semibold tracking-tight">{formatIDR(slip.net_salary)}</div>
        </div>

        <details className="mt-6">
          <summary className="cursor-pointer text-[11px] uppercase tracking-widest font-semibold text-zinc-500 hover:text-zinc-900">Rincian Perhitungan PPh 21</summary>
          <div className="mt-3 p-4 border border-zinc-200 bg-zinc-50">
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
              <span className="text-zinc-600">Bruto Setahun</span>
              <span className="font-mono text-right">{formatIDR(t.bruto_yearly)}</span>
              <span className="text-zinc-600">Biaya Jabatan</span>
              <span className="font-mono text-right">- {formatIDR(t.biaya_jabatan_yearly)}</span>
              <span className="text-zinc-600">Netto Setahun</span>
              <span className="font-mono text-right">{formatIDR(t.netto_yearly)}</span>
              <span className="text-zinc-600">PTKP ({slip.ptkp_status})</span>
              <span className="font-mono text-right">- {formatIDR(t.ptkp)}</span>
              <span className="text-zinc-600">PKP</span>
              <span className="font-mono text-right">{formatIDR(t.pkp)}</span>
              <span className="text-zinc-600">PPh 21 Setahun</span>
              <span className="font-mono text-right font-semibold">{formatIDR(t.pph21_yearly)}</span>
            </div>
          </div>
        </details>
      </div>
    </div>
  );
}

function Row({ label, value, bold, border }) {
  return (
    <div className={`flex items-center justify-between py-1.5 ${border ? "border-t border-zinc-300 mt-1.5 pt-2" : ""}`}>
      <span className={`text-sm ${bold ? "font-semibold text-zinc-900" : "text-zinc-600"}`}>{label}</span>
      <span className={`font-mono text-sm ${bold ? "font-semibold text-zinc-900" : "text-zinc-900"}`}>{formatIDR(value)}</span>
    </div>
  );
}

function Stat({ label, value, sub, highlight }) {
  return (
    <div className="bg-white p-4">
      <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
      <div className={`font-mono mt-2 ${highlight ? "text-xl font-semibold text-[#002FA7]" : "text-lg text-zinc-900"}`}>{value}</div>
      {sub && <div className="text-[10px] text-zinc-500 mt-1 font-mono">{sub}</div>}
    </div>
  );
}
