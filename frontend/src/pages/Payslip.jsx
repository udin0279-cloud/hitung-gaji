import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, formatIDR } from "../lib/api";
import { ChevronLeft, Printer, Square } from "lucide-react";

export default function Payslip() {
  const { slipId } = useParams();
  const [slip, setSlip] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(`/payroll/payslip/${slipId}`);
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
  const ec = slip.employer_contributions;
  const t = slip.tax_detail;

  return (
    <div className="bg-zinc-50 min-h-screen">
      {/* Toolbar */}
      <div className="no-print px-6 lg:px-10 py-5 flex items-center justify-between border-b border-zinc-200 bg-white">
        <Link to={`/payroll/${slip.period}`} className="inline-flex items-center gap-1 text-xs uppercase tracking-widest text-zinc-500 hover:text-zinc-900 font-semibold">
          <ChevronLeft className="w-3.5 h-3.5" /> Kembali
        </Link>
        <button
          data-testid="export-payslip-button"
          onClick={() => window.print()}
          className="rounded-none bg-[#002FA7] text-white px-4 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-[#002FA7]/90 inline-flex items-center gap-2"
        >
          <Printer className="w-3.5 h-3.5" /> Cetak / PDF
        </button>
      </div>

      {/* Payslip */}
      <div data-testid="payslip-view-container" className="print-area max-w-3xl mx-auto bg-white border border-zinc-200 my-8 p-10">
        {/* Header */}
        <div className="flex items-start justify-between pb-6 border-b-2 border-zinc-900">
          <div>
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 bg-[#002FA7] flex items-center justify-center">
                <Square className="w-4 h-4 text-white" fill="white" />
              </div>
              <div className="font-heading font-black text-xl tracking-tight text-zinc-900">PAYROLL.ID</div>
            </div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500 mt-1">HR · Tax · BPJS</div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Slip Gaji</div>
            <div className="font-heading text-2xl font-bold text-zinc-900 mt-1">Periode {slip.period}</div>
            <div className="text-[10px] text-zinc-500 font-mono mt-1">No: {slip.id.slice(0, 8).toUpperCase()}</div>
          </div>
        </div>

        {/* Employee */}
        <div className="grid grid-cols-2 gap-6 mt-6 pb-6 border-b border-zinc-200">
          <div>
            <Label>Nama Karyawan</Label>
            <div className="text-base font-semibold text-zinc-900 mt-0.5">{slip.name}</div>
          </div>
          <div>
            <Label>NIK</Label>
            <div className="font-mono text-sm text-zinc-900 mt-0.5">{slip.nik}</div>
          </div>
          <div>
            <Label>Jabatan / Departemen</Label>
            <div className="text-sm text-zinc-900 mt-0.5">{slip.position} · {slip.department}</div>
          </div>
          <div>
            <Label>Status PTKP / NPWP</Label>
            <div className="text-sm text-zinc-900 mt-0.5 font-mono">{slip.ptkp_status} · {slip.has_npwp ? (slip.npwp || "Ya") : "Tidak"}</div>
          </div>
          {slip.bank_name && (
            <div className="col-span-2">
              <Label>Rekening</Label>
              <div className="text-sm text-zinc-900 mt-0.5 font-mono">{slip.bank_name} · {slip.bank_account}</div>
            </div>
          )}
        </div>

        {/* Two columns: Earnings & Deductions */}
        <div className="grid grid-cols-2 gap-6 mt-6">
          <div>
            <div className="text-[11px] uppercase tracking-widest font-bold text-[#008A00] pb-2 border-b border-zinc-300">Pendapatan</div>
            <Row label="Gaji Pokok" value={e.basic_salary} />
            <Row label="Tunjangan Tetap" value={e.fixed_allowance} />
            <Row label="Lembur" value={e.overtime} />
            <Row label="Bonus" value={e.bonus} />
            <Row label="Total Bruto" value={e.gross} bold border />
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-widest font-bold text-[#E81123] pb-2 border-b border-zinc-300">Potongan</div>
            <Row label="BPJS Kesehatan (1%)" value={d.bpjs_kesehatan_employee} />
            <Row label="JHT (2%)" value={d.jht_employee} />
            <Row label="JP (1%)" value={d.jp_employee} />
            <Row label="PPh 21" value={d.pph21} />
            <Row label="Potongan Lain" value={d.other_deduction} />
            <Row label="Total Potongan" value={d.total} bold border />
          </div>
        </div>

        {/* Take home */}
        <div className="mt-8 bg-zinc-900 text-white p-6 flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-400 font-semibold">Take Home Pay</div>
            <div className="text-xs text-zinc-400 mt-1 font-mono">Hari kerja: {slip.attendance.days_worked} · Lembur: {slip.attendance.overtime_hours} jam</div>
          </div>
          <div className="font-mono text-3xl lg:text-4xl font-semibold tracking-tight">{formatIDR(slip.net_salary)}</div>
        </div>

        {/* Tax detail */}
        <details className="mt-6">
          <summary className="cursor-pointer text-[11px] uppercase tracking-widest font-semibold text-zinc-500 hover:text-zinc-900">Rincian Perhitungan PPh 21</summary>
          <div className="mt-3 p-4 border border-zinc-200 bg-zinc-50">
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
              <span className="text-zinc-600">Bruto Setahun</span>
              <span className="font-mono text-right text-zinc-900">{formatIDR(t.bruto_yearly)}</span>
              <span className="text-zinc-600">Biaya Jabatan</span>
              <span className="font-mono text-right text-zinc-900">- {formatIDR(t.biaya_jabatan_yearly)}</span>
              <span className="text-zinc-600">Netto Setahun</span>
              <span className="font-mono text-right text-zinc-900">{formatIDR(t.netto_yearly)}</span>
              <span className="text-zinc-600">PTKP ({slip.ptkp_status})</span>
              <span className="font-mono text-right text-zinc-900">- {formatIDR(t.ptkp)}</span>
              <span className="text-zinc-600">PKP</span>
              <span className="font-mono text-right text-zinc-900">{formatIDR(t.pkp)}</span>
              <span className="text-zinc-600">PPh 21 Setahun</span>
              <span className="font-mono text-right font-semibold text-zinc-900">{formatIDR(t.pph21_yearly)}</span>
            </div>
          </div>
        </details>

        {/* Employer contributions */}
        <details className="mt-4">
          <summary className="cursor-pointer text-[11px] uppercase tracking-widest font-semibold text-zinc-500 hover:text-zinc-900">Iuran Ditanggung Perusahaan</summary>
          <div className="mt-3 p-4 border border-zinc-200 bg-zinc-50">
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
              <span className="text-zinc-600">BPJS Kesehatan (4%)</span>
              <span className="font-mono text-right text-zinc-900">{formatIDR(ec.bpjs_kesehatan_employer)}</span>
              <span className="text-zinc-600">JHT (3.7%)</span>
              <span className="font-mono text-right text-zinc-900">{formatIDR(ec.jht_employer)}</span>
              <span className="text-zinc-600">JP (2%)</span>
              <span className="font-mono text-right text-zinc-900">{formatIDR(ec.jp_employer)}</span>
              <span className="text-zinc-600">JKK (0.24%)</span>
              <span className="font-mono text-right text-zinc-900">{formatIDR(ec.jkk_employer)}</span>
              <span className="text-zinc-600">JKM (0.3%)</span>
              <span className="font-mono text-right text-zinc-900">{formatIDR(ec.jkm_employer)}</span>
            </div>
          </div>
        </details>

        {/* Footer */}
        <div className="mt-8 pt-4 border-t border-zinc-200 grid grid-cols-2 gap-6 text-[10px] uppercase tracking-widest text-zinc-500">
          <div>
            <div className="mb-12">Diterbitkan oleh HR</div>
            <div className="border-t border-zinc-300 pt-1 font-mono text-zinc-700 normal-case tracking-normal">HR Manager</div>
          </div>
          <div className="text-right">
            <div className="mb-12">Diterima oleh karyawan</div>
            <div className="border-t border-zinc-300 pt-1 font-mono text-zinc-700 normal-case tracking-normal">{slip.name}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Label({ children }) {
  return <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">{children}</div>;
}

function Row({ label, value, bold, border }) {
  return (
    <div className={`flex items-center justify-between py-1.5 ${border ? "border-t border-zinc-300 mt-1.5 pt-2" : ""}`}>
      <span className={`text-sm ${bold ? "font-semibold text-zinc-900" : "text-zinc-600"}`}>{label}</span>
      <span className={`font-mono text-sm ${bold ? "font-semibold text-zinc-900" : "text-zinc-900"}`}>{formatIDR(value)}</span>
    </div>
  );
}
