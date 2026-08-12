import { useEffect, useState } from "react";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import { Download, TrendingUp, TrendingDown, Wallet, Package as PackageIcon, ArrowUpDown } from "lucide-react";

export default function Reports() {
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [periodInitialized, setPeriodInitialized] = useState(false);
  const [report, setReport] = useState(null);
  const [margins, setMargins] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sortBy, setSortBy] = useState("revenue"); // revenue | margin | margin_pct

  const load = async (p) => {
    setLoading(true);
    try {
      const [pl, mr] = await Promise.all([
        api.get(`/reports/profit-loss/${p}`),
        api.get(`/reports/product-margin/${p}`),
      ]);
      setReport(pl.data);
      setMargins(mr.data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat laporan");
    } finally {
      setLoading(false);
    }
  };

  // Default period = bulan terakhir yg ada datanya (bukan bulan kalender sekarang).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get("/reports/profit-loss-latest-period");
        if (!cancelled && res.data?.period) {
          setPeriod(res.data.period);
        }
      } catch {
        /* fallback ke bulan sekarang */
      } finally {
        if (!cancelled) setPeriodInitialized(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!periodInitialized) return;
    load(period);
    /* eslint-disable-next-line */
  }, [period, periodInitialized]);

  const isPositive = (report?.net_profit || 0) >= 0;
  // "Belum ada data" = tidak ada order aktif, tidak ada waste, dan tidak ada biaya gaji.
  const hasNoData = report && report.order_count === 0 && report.waste_records === 0 && (report.payroll_cost || 0) === 0;

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
      ) : hasNoData ? (
        <div data-testid="pl-empty-state" className="mt-10 border border-dashed border-zinc-300 bg-zinc-50/40 py-16 px-6 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-zinc-100 mb-4">
            <TrendingUp className="w-6 h-6 text-zinc-400" />
          </div>
          <div className="font-heading text-xl font-bold text-zinc-900">Belum ada data untuk periode ini</div>
          <div className="text-sm text-zinc-500 mt-2 font-mono">
            Periode {period} belum punya penjualan aktif, waste, atau biaya gaji.
          </div>
          <div className="text-xs text-zinc-400 mt-4">
            Coba pilih bulan lain di kanan atas, atau input transaksi baru dulu.
          </div>
        </div>
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
          {/* Product Margin Report */}
          {margins && margins.products.length > 0 && (
            <ProductMarginPanel margins={margins} sortBy={sortBy} setSortBy={setSortBy} />
          )}
        </>
      )}
    </div>
  );
}

/* ---------- Product Margin Panel ---------- */
function ProductMarginPanel({ margins, sortBy, setSortBy }) {
  const sorted = [...margins.products].sort((a, b) => {
    if (sortBy === "margin") return b.margin - a.margin;
    if (sortBy === "margin_pct") return b.margin_pct - a.margin_pct;
    return b.revenue - a.revenue;
  });
  const top3 = [...margins.products].sort((a, b) => b.margin - a.margin).slice(0, 3);
  const bottom3 = [...margins.products].filter((p) => p.revenue > 0).sort((a, b) => a.margin_pct - b.margin_pct).slice(0, 3);
  const maxMargin = Math.max(...margins.products.map((p) => Math.abs(p.margin)), 1);

  return (
    <div className="mt-6 border border-zinc-200 bg-white p-6">
      <div className="flex items-end justify-between mb-4 flex-wrap gap-2">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Analytics</div>
          <div className="font-heading text-lg font-bold text-zinc-900">Margin per Produk</div>
        </div>
        <div className="text-xs text-zinc-500 font-mono">
          {margins.total_products} produk · Total Revenue <b className="text-zinc-900">{formatIDR(margins.total_revenue)}</b> · Modal <b className="text-zinc-900">{formatIDR(margins.total_cost)}</b> · Margin <b className={margins.total_margin >= 0 ? "text-[#008A00]" : "text-[#E81123]"}>{formatIDR(margins.total_margin)} ({margins.total_margin_pct}%)</b>
        </div>
      </div>

      {/* Top & Bottom */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <RankPanel title="🏆 Produk Paling Untung (by Margin Rp)" rows={top3} color="#008A00" />
        <RankPanel title="⚠ Produk Margin Tipis / Rugi (by %)" rows={bottom3} color="#E81123" isBottom />
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-[11px] font-bold text-zinc-600 uppercase tracking-widest border-b border-zinc-200">
              <th className="py-2 pr-4">#</th>
              <th className="py-2 pr-4">Produk</th>
              <th className="py-2 pr-4 text-right">Qty</th>
              <th className="py-2 pr-4 text-right">Order</th>
              <th onClick={() => setSortBy("revenue")} className={`py-2 pr-4 text-right cursor-pointer select-none ${sortBy === "revenue" ? "text-[#002FA7]" : ""}`}>
                <span className="inline-flex items-center gap-1">Revenue <ArrowUpDown className="w-3 h-3" /></span>
              </th>
              <th className="py-2 pr-4 text-right">Modal</th>
              <th onClick={() => setSortBy("margin")} className={`py-2 pr-4 text-right cursor-pointer select-none ${sortBy === "margin" ? "text-[#002FA7]" : ""}`}>
                <span className="inline-flex items-center gap-1">Margin Rp <ArrowUpDown className="w-3 h-3" /></span>
              </th>
              <th onClick={() => setSortBy("margin_pct")} className={`py-2 pr-4 text-right cursor-pointer select-none ${sortBy === "margin_pct" ? "text-[#002FA7]" : ""}`}>
                <span className="inline-flex items-center gap-1">Margin % <ArrowUpDown className="w-3 h-3" /></span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((p, i) => (
              <tr key={`${p.product_id || ""}::${p.product_name}`} data-testid="product-margin-row" className="border-b border-zinc-100 hover:bg-zinc-50/50 align-top">
                <td className="py-2 pr-4 font-mono text-xs text-zinc-500">{i + 1}</td>
                <td className="py-2 pr-4">
                  <div className="font-medium text-zinc-900">{p.product_name}</div>
                  {p.is_bom && (
                    <div className="text-[10px] text-zinc-500 font-mono mt-0.5">
                      BOM: {p.materials_used.map((m) => `${m.name} ${m.consumption.toFixed(2)}${m.unit}`).join(" + ")}
                    </div>
                  )}
                </td>
                <td className="py-2 pr-4 font-mono text-right">{p.qty_total}</td>
                <td className="py-2 pr-4 font-mono text-right">{p.sale_count}</td>
                <td className="py-2 pr-4 font-mono text-right text-zinc-900 font-semibold">{formatIDR(p.revenue)}</td>
                <td className="py-2 pr-4 font-mono text-right text-zinc-700">{formatIDR(p.cost)}</td>
                <td className={`py-2 pr-4 font-mono text-right font-bold ${p.margin >= 0 ? "text-[#008A00]" : "text-[#E81123]"}`}>{formatIDR(p.margin)}</td>
                <td className="py-2 pr-4 text-right">
                  <div className="inline-flex flex-col items-end gap-1">
                    <span className={`font-mono text-xs font-bold ${p.margin_pct >= 20 ? "text-[#008A00]" : p.margin_pct >= 5 ? "text-amber-600" : "text-[#E81123]"}`}>
                      {p.margin_pct}%
                    </span>
                    <div className="w-16 h-1 bg-zinc-100">
                      <div className="h-full" style={{ width: `${Math.min((Math.abs(p.margin) / maxMargin) * 100, 100)}%`, backgroundColor: p.margin >= 0 ? "#008A00" : "#E81123" }} />
                    </div>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-[10px] text-zinc-500 font-mono mt-3">
        Klik header <b>Revenue / Margin Rp / Margin %</b> untuk urutkan. Warna: <span className="text-[#008A00] font-bold">≥20% sehat</span> · <span className="text-amber-600 font-bold">5–19% tipis</span> · <span className="text-[#E81123] font-bold">&lt;5% waspada</span>
      </div>
    </div>
  );
}

function RankPanel({ title, rows, color, isBottom }) {
  return (
    <div className="border border-zinc-200 bg-zinc-50/30 p-4">
      <div className="text-xs font-bold text-zinc-700 mb-2 uppercase tracking-widest">{title}</div>
      {rows.length === 0 && <div className="text-zinc-400 font-mono text-xs py-2">—</div>}
      <div className="space-y-1.5">
        {rows.map((r, i) => (
          <div key={i} className="flex items-baseline justify-between text-sm">
            <div className="flex-1 truncate">
              <span className="font-mono text-[10px] text-zinc-500 mr-2">#{i + 1}</span>
              <span className="font-medium">{r.product_name}</span>
              <span className="text-[10px] text-zinc-500 font-mono ml-2">({r.sale_count}× · {r.qty_total} pcs)</span>
            </div>
            <div className="text-right ml-2">
              <div className="font-mono font-bold text-sm" style={{ color: r.margin >= 0 ? color : "#E81123" }}>
                {isBottom ? `${r.margin_pct}%` : formatIDR(r.margin)}
              </div>
              <div className="font-mono text-[9px] text-zinc-500">{isBottom ? formatIDR(r.margin) : `${r.margin_pct}%`}</div>
            </div>
          </div>
        ))}
      </div>
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
