import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, formatIDR } from "../lib/api";
import { ChevronLeft, Eye, Printer } from "lucide-react";

export default function PayrollDetail() {
  const { period } = useParams();
  const [slips, setSlips] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(`/payroll/runs/${period}/slips`);
        setSlips(data);
      } finally {
        setLoading(false);
      }
    })();
  }, [period]);

  const totals = slips.reduce(
    (acc, s) => ({
      gross: acc.gross + s.earnings.gross,
      net: acc.net + s.net_salary,
      pph: acc.pph + s.deductions.pph21,
      bpjs: acc.bpjs + s.deductions.bpjs_kesehatan_employee + s.deductions.jht_employee + s.deductions.jp_employee,
    }),
    { gross: 0, net: 0, pph: 0, bpjs: 0 }
  );

  return (
    <div className="px-6 lg:px-10 py-8 max-w-7xl">
      <Link to="/payroll" className="inline-flex items-center gap-1 text-xs uppercase tracking-widest text-zinc-500 hover:text-zinc-900 font-semibold">
        <ChevronLeft className="w-3.5 h-3.5" /> Kembali ke Payroll
      </Link>
      <div className="mt-3 pb-6 border-b border-zinc-200">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Detail Periode</div>
        <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Payroll {period}</h1>
        <p className="text-sm text-zinc-500 mt-1">{slips.length} slip gaji.</p>
      </div>

      <div className="mt-6 grid grid-cols-1 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
        <Stat label="Total Bruto" value={formatIDR(totals.gross)} />
        <Stat label="BPJS Karyawan" value={formatIDR(totals.bpjs)} />
        <Stat label="PPh 21" value={formatIDR(totals.pph)} />
        <Stat label="Take Home" value={formatIDR(totals.net)} highlight />
      </div>

      <div className="mt-6 border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">NIK</th>
              <th className="px-4 py-3">Karyawan</th>
              <th className="px-4 py-3">Departemen</th>
              <th className="px-4 py-3 text-right">Bruto</th>
              <th className="px-4 py-3 text-right">PPh 21</th>
              <th className="px-4 py-3 text-right">Take Home</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {slips.map((s) => (
              <tr key={s.id} className="border-b border-zinc-100 hover:bg-zinc-50/80">
                <td className="px-4 py-3 font-mono text-xs text-zinc-700">{s.nik}</td>
                <td className="px-4 py-3">
                  <div className="font-medium text-zinc-900">{s.name}</div>
                  <div className="text-xs text-zinc-500">{s.position} · {s.ptkp_status}</div>
                </td>
                <td className="px-4 py-3 text-zinc-700">{s.department}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900">{formatIDR(s.earnings.gross)}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(s.deductions.pph21)}</td>
                <td className="px-4 py-3 font-mono text-right font-semibold text-zinc-900">{formatIDR(s.net_salary)}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <Link
                      to={`/payslip/${s.id}`}
                      data-testid="view-payslip-button"
                      className="inline-flex items-center gap-1 px-2.5 py-1 border border-zinc-300 hover:border-zinc-900 hover:bg-zinc-900 hover:text-white text-xs font-semibold uppercase tracking-wider transition-colors"
                    >
                      <Eye className="w-3 h-3" /> Lihat
                    </Link>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, highlight }) {
  return (
    <div className="bg-white p-5">
      <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
      <div className={`font-mono mt-2 ${highlight ? "text-2xl font-semibold text-[#002FA7]" : "text-xl text-zinc-900"}`}>{value}</div>
    </div>
  );
}
