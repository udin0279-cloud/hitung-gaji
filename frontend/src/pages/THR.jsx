import { useEffect, useState } from "react";
import { api, formatIDR, formatApiError } from "../lib/api";
import { toast } from "sonner";
import { Gift, ArrowRight } from "lucide-react";

function defaultPeriod() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function THR() {
  const [period, setPeriod] = useState(defaultPeriod());
  const [preview, setPreview] = useState(null);
  const [runs, setRuns] = useState([]);
  const [running, setRunning] = useState(false);

  const loadRuns = async () => {
    const { data } = await api.get("/payroll/thr/runs");
    setRuns(data);
  };

  useEffect(() => { loadRuns(); }, []);

  const previewThr = async () => {
    try {
      const { data } = await api.post("/payroll/thr/preview", { period });
      setPreview(data);
      toast.success("Pratinjau THR dihitung");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal pratinjau");
    }
  };

  const runThr = async () => {
    if (!window.confirm(`Jalankan THR untuk periode ${period}? Data lama (jika ada) akan diganti.`)) return;
    setRunning(true);
    try {
      await api.post("/payroll/thr/run", { period });
      toast.success(`THR ${period} berhasil disimpan`);
      await loadRuns();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menjalankan");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="px-6 lg:px-10 py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Hari Raya</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Perhitungan THR</h1>
          <p className="text-sm text-zinc-500 mt-1">Tunjangan Hari Raya: 1× (Gaji + Tunjangan Tetap) untuk masa kerja ≥ 12 bulan; proporsional untuk &lt; 12 bulan.</p>
        </div>
        <div className="flex items-end gap-3">
          <label className="block">
            <span className="block text-xs font-semibold text-zinc-900 uppercase tracking-wider mb-1.5">Periode Bayar THR</span>
            <input
              data-testid="thr-period"
              type="month"
              value={period}
              onChange={(e) => { setPeriod(e.target.value); setPreview(null); }}
              className="rounded-none border border-zinc-300 px-3 py-2.5 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none font-mono"
            />
          </label>
          <button
            data-testid="thr-preview-button"
            onClick={previewThr}
            className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-5 py-2.5 text-sm font-semibold hover:bg-zinc-50 inline-flex items-center gap-2"
          >
            <Gift className="w-4 h-4" /> Hitung Pratinjau
          </button>
          <button
            data-testid="thr-run-button"
            onClick={runThr}
            disabled={running}
            className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2 disabled:opacity-60"
          >
            {running ? "Memproses…" : (<>Simpan THR <ArrowRight className="w-4 h-4" /></>)}
          </button>
        </div>
      </div>

      {preview && (
        <div className="mt-6 fade-up">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-zinc-200 border border-zinc-200">
            <Stat label="Karyawan" value={preview.totals.count} count />
            <Stat label="Total THR Bruto" value={formatIDR(preview.totals.gross)} />
            <Stat label="Total THR Net" value={formatIDR(preview.totals.net)} highlight />
          </div>

          <div className="mt-4 border border-zinc-200 bg-white overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                  <th className="px-4 py-3">NIK</th>
                  <th className="px-4 py-3">Karyawan</th>
                  <th className="px-4 py-3 text-right">Masa Kerja (bln)</th>
                  <th className="px-4 py-3">Formula</th>
                  <th className="px-4 py-3 text-right">THR Bruto</th>
                  <th className="px-4 py-3 text-right">PPh 21</th>
                  <th className="px-4 py-3 text-right">THR Net</th>
                </tr>
              </thead>
              <tbody>
                {preview.items.map((it) => (
                  <tr key={it.employee_id} className="border-b border-zinc-100">
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-700">{it.nik}</td>
                    <td className="px-4 py-2.5">
                      <div className="font-medium text-zinc-900">{it.name}</div>
                      <div className="text-xs text-zinc-500">{it.position} · {it.ptkp_status}</div>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-right">{it.months_of_service.toFixed(0)}</td>
                    <td className="px-4 py-2.5 text-xs text-zinc-600 font-mono">{it.formula}</td>
                    <td className="px-4 py-2.5 font-mono text-right">{formatIDR(it.thr_gross)}</td>
                    <td className="px-4 py-2.5 font-mono text-right text-zinc-700">{formatIDR(it.pph21_thr)}</td>
                    <td className="px-4 py-2.5 font-mono text-right font-semibold">{formatIDR(it.thr_net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="mt-10">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold mb-2">Riwayat THR</div>
        <div className="border border-zinc-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                <th className="px-4 py-3">Periode</th>
                <th className="px-4 py-3 text-right">Karyawan</th>
                <th className="px-4 py-3 text-right">Total Bruto</th>
                <th className="px-4 py-3 text-right">PPh 21</th>
                <th className="px-4 py-3 text-right">Total Net</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 && <tr><td colSpan={5} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Belum ada THR yang dijalankan.</td></tr>}
              {runs.map((r) => (
                <tr key={r.period} className="border-b border-zinc-100 hover:bg-zinc-50/80">
                  <td className="px-4 py-3 font-mono text-zinc-900">{r.period}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-700">{r.employee_count}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(r.total_gross)}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(r.total_pph21)}</td>
                  <td className="px-4 py-3 font-mono text-right font-semibold text-zinc-900">{formatIDR(r.total_net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, highlight, count }) {
  return (
    <div className="bg-white p-5">
      <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
      <div className={`font-mono mt-2 ${highlight ? "text-2xl font-semibold text-[#002FA7]" : "text-xl text-zinc-900"}`}>{count ? value : value}</div>
    </div>
  );
}
