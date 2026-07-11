import { useEffect, useState } from "react";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import { Download, TrendingUp, TrendingDown, Wallet, Package as PackageIcon } from "lucide-react";

export default function Reports() {
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async (p) => {
    setLoading(true);
    try {
      const { data } = await api.get(`/reports/profit-loss/${p}`);
      setReport(data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat laporan");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(period); /* eslint-disable-next-line */ }, [period]);

  const isPositive = (report?.net_profit || 0) >= 0;

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Laporan</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Laba / Rugi Bulanan</h1>
          <p className="text-sm text-zinc-500 mt-1">Rekap otomatis: Penjualan − Bahan − Waste − Gaji.</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            data-testid="report-period"
            type="month"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono"
          />
          <a
            data-testid="download-pl-pdf"
            href={`${API}/reports/profit-loss/${period}/pdf`}
            target="_blank"
            rel="noreferrer"
            className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-3 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-50 inline-flex items-center gap-1.5"
          >
            <Download className="w-3.5 h-3.5" /> PDF
          </a>
        </div>
      </div>

      {loading || !report ? (
        <div className="py-12 text-center text-zinc-400 font-mono text-xs">Memuat…</div>
      ) : (
        <>
          {/* Hero card — Net profit */}
          <div className={`mt-8 border p-6 lg:p-8 ${isPositive ? "border-[#008A00] bg-[#008A00]/5" : "border-[#E81123] bg-[#E81123]/5"}`}>
            <div className="text-[11px] uppercase tracking-widest font-semibold text-zinc-500">Laba / Rugi Bersih — {period}</div>
            <div data-testid="net-profit" className={`font-mono text-5xl lg:text-6xl tracking-tighter font-semibold mt-3 ${isPositive ? "text-[#008A00]" : "text-[#E81123]"}`}>
              {formatIDR(report.net_profit)}
            </div>
            <div className="text-xs text-zinc-600 mt-2 font-mono">
              Net margin: <b>{report.net_margin_pct}%</b> · dari revenue {formatIDR(report.revenue)} ({report.order_count} order)
            </div>
          </div>

          {/* Waterfall breakdown */}
          <div className="mt-6 border border-zinc-200 bg-white p-6">
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold mb-4">Rincian Perhitungan</div>
            <div className="space-y-1">
              <Row label="Pendapatan Penjualan" value={report.revenue} desc={`${report.order_count} order`} color="text-[#008A00]" bold sign="+" testId="pl-revenue" />
              <Row label="Biaya Bahan Baku (COGS)" value={report.cogs} color="text-[#E81123]" sign="−" testId="pl-cogs" />
              <div className="pt-2 pb-2 border-t border-b border-zinc-300 my-1">
                <Row label={`LABA KOTOR (${report.gross_margin_pct}%)`} value={report.gross_profit} color={report.gross_profit >= 0 ? "text-[#008A00]" : "text-[#E81123]"} bold big testId="pl-gross-profit" />
              </div>
              <Row label="Kerugian Waste / Rijek" value={report.waste_loss} desc={`${report.waste_records} record`} color="text-[#E81123]" sign="−" testId="pl-waste" />
              <Row label="Biaya Gaji Karyawan" value={report.payroll_cost} desc={`${report.employee_count} karyawan`} color="text-[#E81123]" sign="−" testId="pl-payroll" />
              <div className="pt-2 border-t border-zinc-300 mt-1">
                <Row label="Total Beban Operasional" value={report.total_expenses} color="text-zinc-700" bold testId="pl-expenses" />
              </div>
              <div className={`p-4 mt-2 -mx-6 ${isPositive ? "bg-[#008A00]" : "bg-[#E81123]"}`}>
                <div className="flex items-center justify-between">
                  <div className="text-white font-heading font-bold text-lg tracking-tight uppercase">Laba / Rugi Bersih</div>
                  <div className="text-white font-mono text-2xl font-bold">{formatIDR(report.net_profit)}</div>
                </div>
              </div>
            </div>
          </div>

          {/* Stat cards */}
          <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
            <Stat label="Revenue" value={report.revenue} icon={TrendingUp} color="text-[#008A00]" />
            <Stat label="COGS + Waste" value={report.cogs + report.waste_loss} icon={PackageIcon} color="text-amber-700" />
            <Stat label="Beban Gaji" value={report.payroll_cost} icon={Wallet} color="text-zinc-900" />
            <Stat label="Net Profit" value={report.net_profit} icon={isPositive ? TrendingUp : TrendingDown} color={isPositive ? "text-[#008A00]" : "text-[#E81123]"} />
          </div>

          {/* Top customers */}
          {report.top_customers?.length > 0 && (
            <div className="mt-6 border border-zinc-200 bg-white p-6">
              <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold mb-4">Top Customer</div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="text-[11px] font-bold text-zinc-600 uppercase tracking-widest border-b border-zinc-200">
                      <th className="py-2 pr-4">#</th>
                      <th className="py-2 pr-4">Customer</th>
                      <th className="py-2 pr-4 text-right">Order</th>
                      <th className="py-2 pr-4 text-right">Revenue</th>
                      <th className="py-2 pr-4 text-right">Biaya Bahan</th>
                      <th className="py-2 pr-4 text-right">Margin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.top_customers.map((c, i) => (
                      <tr key={c.customer} data-testid="pl-top-customer-row" className="border-b border-zinc-100">
                        <td className="py-2 pr-4 font-mono text-xs text-zinc-500">{i + 1}</td>
                        <td className="py-2 pr-4 font-medium text-zinc-900">{c.customer}</td>
                        <td className="py-2 pr-4 font-mono text-right">{c.orders}</td>
                        <td className="py-2 pr-4 font-mono text-right text-zinc-900 font-semibold">{formatIDR(c.revenue)}</td>
                        <td className="py-2 pr-4 font-mono text-right text-zinc-700">{formatIDR(c.material_cost)}</td>
                        <td className={`py-2 pr-4 font-mono text-right font-bold ${c.margin >= 0 ? "text-[#008A00]" : "text-[#E81123]"}`}>{formatIDR(c.margin)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Row({ label, value, desc, color, bold, big, sign = "", testId }) {
  return (
    <div className="flex items-baseline justify-between py-2">
      <div className={`${bold ? "font-bold" : ""} ${big ? "text-base" : "text-sm"} text-zinc-800`}>
        {label}
        {desc && <span className="text-xs text-zinc-500 font-mono ml-2">({desc})</span>}
      </div>
      <div data-testid={testId} className={`font-mono ${big ? "text-xl" : "text-sm"} ${bold ? "font-bold" : ""} ${color || "text-zinc-900"}`}>
        {sign} {formatIDR(value)}
      </div>
    </div>
  );
}

function Stat({ label, value, icon: Icon, color }) {
  return (
    <div className="bg-white p-4 lg:p-5">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
        <Icon className={`w-3.5 h-3.5 ${color || "text-zinc-400"}`} />
      </div>
      <div className={`font-mono text-xl lg:text-2xl tracking-tight font-semibold mt-2 ${color || "text-zinc-900"}`}>
        {formatIDR(value)}
      </div>
    </div>
  );
}
