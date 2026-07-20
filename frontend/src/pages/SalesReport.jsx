import { useEffect, useMemo, useState, Fragment } from "react";
import { api, formatIDR, formatApiError } from "../lib/api";
import { toast } from "sonner";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { Search, TrendingUp, Package, Calendar, Award, Users } from "lucide-react";

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}
function firstDayOfMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}
function shortDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}`;
}

export default function SalesReport() {
  const [dateFrom, setDateFrom] = useState(firstDayOfMonth());
  const [dateTo, setDateTo] = useState(todayISO());
  const [customer, setCustomer] = useState("");
  const [data, setData] = useState({ rows: [], summary: {}, top_products: [], daily_series: [] });
  const [loading, setLoading] = useState(true);
  const [searchRow, setSearchRow] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get("/sales/report/analytics", {
        params: {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          customer: customer.trim() || undefined,
        },
      });
      setData(res.data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat laporan");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const rows = useMemo(() => {
    if (!searchRow.trim()) return data.rows;
    const q = searchRow.toLowerCase();
    return data.rows.filter((r) =>
      (r.product_name || "").toLowerCase().includes(q) ||
      (r.customer_name || "").toLowerCase().includes(q) ||
      (r.alamat || "").toLowerCase().includes(q) ||
      (r.sale_no || "").toLowerCase().includes(q)
    );
  }, [data.rows, searchRow]);

  const barData = (data.top_products || []).slice(0, 8).map((p) => ({
    name: p.name.length > 18 ? p.name.slice(0, 17) + "…" : p.name,
    full_name: p.name,
    qty: p.qty,
    total: p.total,
  }));
  const lineData = (data.daily_series || []).map((d) => ({
    date: shortDate(d.date),
    full_date: d.date,
    total: d.total,
  }));

  const totalRowsQty = rows.reduce((s, r) => s + Number(r.pcs || r.quantity || 0), 0);
  const totalRowsMeter = rows.reduce((s, r) => s + Number(r.meter || 0), 0);
  // Total Omzet Footer — SINKRON dengan summary.period_total:
  // dedupe berdasarkan sale_no (tiap transaksi hanya dihitung 1x pakai sale_total setelah diskon)
  const uniqueSaleTotals = new Map();
  const uniqueSaleDiscounts = new Map();
  rows.forEach((r) => {
    if (!uniqueSaleTotals.has(r.sale_no)) {
      uniqueSaleTotals.set(r.sale_no, Number(r.sale_total || 0));
      uniqueSaleDiscounts.set(r.sale_no, Number(r.sale_discount || 0));
    }
  });
  const totalRowsAmount = Array.from(uniqueSaleTotals.values()).reduce((s, v) => s + v, 0);
  const totalRowsDisc = Array.from(uniqueSaleDiscounts.values()).reduce((s, v) => s + v, 0);
  const totalRowsItemsSubtotal = rows.reduce((s, r) => s + Number(r.total || 0), 0);

  // Payment column totals — sum by payment_column key (already normalized by backend)
  const PAY_COLS = [
    { key: "cash_plaza", label: "Cash Plaza" },
    { key: "cash_kastem", label: "Cash Kastem" },
    { key: "bca_plaza", label: "BCA Plaza" },
    { key: "bca_kastem", label: "BCA Kastem" },
    { key: "mandiri_plaza", label: "Mandiri Plaza" },
    { key: "mandiri_kastem", label: "Mandiri Kastem" },
  ];
  const payTotals = Object.fromEntries(PAY_COLS.map((c) => [c.key, 0]));
  rows.forEach((r) => {
    if (r.is_first_item_of_sale && r.payment_column && payTotals[r.payment_column] !== undefined) {
      payTotals[r.payment_column] += Number(r.payment_nominal_on_row || 0);
    }
  });

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200 max-w-7xl">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Modul</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Laporan Penjualan</h1>
          <p className="text-sm text-zinc-500 mt-1">Format Excel-style dengan breakdown pembayaran per cabang (Plaza / Kastem).</p>
        </div>
      </div>

      {/* Filter */}
      <div className="mt-6 border border-zinc-200 bg-white p-4 grid grid-cols-1 sm:grid-cols-4 gap-3 items-end max-w-7xl">
        <div>
          <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1.5">Dari Tanggal</label>
          <input data-testid="report-date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            className="w-full rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none" />
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1.5">Sampai Tanggal</label>
          <input data-testid="report-date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            className="w-full rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none" />
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1.5">Nama Pelanggan</label>
          <input data-testid="report-customer-filter" value={customer} onChange={(e) => setCustomer(e.target.value)}
            placeholder="Kosongkan = semua"
            className="w-full rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm focus:border-[#002FA7] focus:outline-none" />
        </div>
        <div>
          <button data-testid="apply-filter-button" onClick={load} disabled={loading}
            className="w-full rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-bold uppercase tracking-wider hover:bg-[#001E7A] disabled:opacity-40">
            {loading ? "Memuat…" : "Terapkan Filter"}
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200 mt-6 max-w-7xl">
        <div className="bg-white p-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Omzet Periode Ini</div>
              <div data-testid="summary-period-total" className="font-mono text-2xl font-bold mt-1 text-[#002FA7]">{formatIDR(data.summary?.period_total || 0)}</div>
              <div className="text-[10px] text-zinc-500 mt-1 font-mono">{data.summary?.transaction_count || 0} transaksi · {data.summary?.item_count || 0} item</div>
            </div>
            <TrendingUp className="w-5 h-5 text-[#002FA7]/50" />
          </div>
        </div>
        <div className="bg-white p-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Omzet Minggu Ini</div>
              <div data-testid="summary-weekly-total" className="font-mono text-2xl font-bold mt-1 text-[#008A00]">{formatIDR(data.summary?.weekly_total || 0)}</div>
              <div className="text-[10px] text-zinc-500 mt-1 font-mono">Sejak {data.summary?.week_start || "-"}</div>
            </div>
            <Calendar className="w-5 h-5 text-[#008A00]/50" />
          </div>
        </div>
        <div className="bg-white p-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Produk Terlaris</div>
              <div data-testid="summary-top-product" className="font-bold mt-1 text-zinc-900 leading-tight" style={{ fontSize: 15 }}>{data.summary?.top_product || "—"}</div>
              <div className="text-[10px] text-zinc-500 mt-1 font-mono">
                {data.top_products?.[0] ? `${data.top_products[0].qty} pcs · ${formatIDR(data.top_products[0].total)}` : ""}
              </div>
            </div>
            <Award className="w-5 h-5 text-[#E81123]/50" />
          </div>
        </div>
        <div className="bg-white p-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Pelanggan Unik</div>
              <div className="font-mono text-2xl font-bold mt-1 text-zinc-900">
                {new Set(data.rows.map((r) => r.customer_name)).size}
              </div>
              <div className="text-[10px] text-zinc-500 mt-1 font-mono">pelanggan berbeda</div>
            </div>
            <Users className="w-5 h-5 text-zinc-400" />
          </div>
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-6 max-w-7xl">
        <div className="border border-zinc-200 bg-white p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Bar Chart</div>
              <div className="font-bold text-zinc-900">Produk Paling Laris</div>
            </div>
            <Package className="w-4 h-4 text-zinc-400" />
          </div>
          <div style={{ width: "100%", height: 280 }} data-testid="top-products-chart">
            <ResponsiveContainer>
              <BarChart data={barData} margin={{ top: 10, right: 10, left: -10, bottom: 30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-25} textAnchor="end" interval={0} height={60} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${(v/1000).toFixed(0)}rb` : v} />
                <Tooltip
                  formatter={(v, name) => name === "total" ? formatIDR(v) : `${v} pcs`}
                  labelFormatter={(l, payload) => payload?.[0]?.payload?.full_name || l}
                />
                <Legend />
                <Bar dataKey="total" fill="#002FA7" name="Omzet" />
                <Bar dataKey="qty" fill="#E81123" name="Qty (pcs)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          {barData.length === 0 && !loading && (
            <div className="text-center text-xs text-zinc-400 font-mono py-4">Belum ada produk terjual pada periode ini.</div>
          )}
        </div>
        <div className="border border-zinc-200 bg-white p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Line Chart</div>
              <div className="font-bold text-zinc-900">Tren Penjualan per Hari</div>
            </div>
            <TrendingUp className="w-4 h-4 text-zinc-400" />
          </div>
          <div style={{ width: "100%", height: 280 }} data-testid="daily-trend-chart">
            <ResponsiveContainer>
              <LineChart data={lineData} margin={{ top: 10, right: 10, left: -10, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${(v/1000).toFixed(0)}rb` : v} />
                <Tooltip
                  formatter={(v) => formatIDR(v)}
                  labelFormatter={(l, payload) => payload?.[0]?.payload?.full_date || l}
                />
                <Line type="monotone" dataKey="total" stroke="#002FA7" strokeWidth={2} dot={{ r: 4, fill: "#002FA7" }} activeDot={{ r: 6 }} name="Omzet Harian" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {lineData.length === 0 && !loading && (
            <div className="text-center text-xs text-zinc-400 font-mono py-4">Belum ada penjualan pada periode ini.</div>
          )}
        </div>
      </div>

      {/* Table Detail */}
      <div className="mt-6 border border-zinc-200 bg-white">
        <div className="p-4 border-b border-zinc-200 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Detail per Item</div>
            <div className="font-bold text-zinc-900">Daftar Transaksi</div>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
              <input
                value={searchRow} onChange={(e) => setSearchRow(e.target.value)}
                placeholder="Cari produk / pelanggan / no.nota…"
                data-testid="report-row-search"
                className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-80 focus:border-[#002FA7] focus:outline-none"
              />
            </div>
            <div className="text-xs font-mono text-zinc-500">{rows.length} item · Total <b className="text-[#002FA7]">{formatIDR(totalRowsAmount)}</b></div>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table data-testid="report-table" className="text-left text-sm" style={{ minWidth: 2200 }}>
            <thead>
              <tr className="bg-zinc-900 text-white text-[10px] font-bold uppercase tracking-wider">
                <th rowSpan={2} className="px-2 py-2 text-center border-r border-zinc-700 whitespace-nowrap w-10">No</th>
                <th rowSpan={2} className="px-2 py-2 border-r border-zinc-700 whitespace-nowrap">Tanggal</th>
                <th rowSpan={2} className="px-2 py-2 border-r border-zinc-700 whitespace-nowrap">No. Nota</th>
                <th rowSpan={2} className="px-2 py-2 border-r border-zinc-700 min-w-[160px]">Alamat</th>
                <th rowSpan={2} className="px-2 py-2 border-r border-zinc-700 min-w-[180px]">Nama Barang</th>
                <th rowSpan={2} className="px-2 py-2 text-center border-r border-zinc-700 whitespace-nowrap">Pcs</th>
                <th rowSpan={2} className="px-2 py-2 text-center border-r border-zinc-700 whitespace-nowrap">Meter</th>
                <th rowSpan={2} className="px-2 py-2 text-right border-r border-zinc-700 whitespace-nowrap">Harga</th>
                <th rowSpan={2} className="px-2 py-2 text-right border-r border-zinc-700 whitespace-nowrap">Disc</th>
                <th rowSpan={2} className="px-2 py-2 text-right border-r border-zinc-700 whitespace-nowrap">Jumlah</th>
                <th rowSpan={2} className="px-2 py-2 text-right border-r border-zinc-700 whitespace-nowrap bg-[#002FA7]">Total</th>
                <th rowSpan={2} className="px-2 py-2 border-r border-zinc-700 min-w-[120px]">Keterangan</th>
                {/* Payment column groups */}
                <th colSpan={2} className="px-2 py-1 text-center border-r border-b border-zinc-700 bg-[#008A00]/80">Cash Plaza</th>
                <th colSpan={2} className="px-2 py-1 text-center border-r border-b border-zinc-700 bg-[#008A00]/60">Cash Kastem</th>
                <th colSpan={2} className="px-2 py-1 text-center border-r border-b border-zinc-700 bg-[#002FA7]/80">BCA Plaza</th>
                <th colSpan={2} className="px-2 py-1 text-center border-r border-b border-zinc-700 bg-[#002FA7]/60">BCA Kastem</th>
                <th colSpan={2} className="px-2 py-1 text-center border-r border-b border-zinc-700 bg-[#E81123]/80">Mandiri Plaza</th>
                <th colSpan={2} className="px-2 py-1 text-center border-b border-zinc-700 bg-[#E81123]/60">Mandiri Kastem</th>
              </tr>
              <tr className="bg-zinc-900 text-white text-[9px] font-bold uppercase tracking-wider">
                {PAY_COLS.map((c, i) => (
                  <Fragment key={c.key + "-h"}>
                    <th className="px-2 py-1 text-right border-r border-zinc-700 whitespace-nowrap bg-zinc-800/60">Nominal</th>
                    <th className={`px-2 py-1 text-center whitespace-nowrap bg-zinc-800/60 ${i < PAY_COLS.length - 1 ? "border-r border-zinc-700" : ""}`}>Tanggal</th>
                  </Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={24} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={24} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada transaksi pada periode ini.</td></tr>
              )}
              {rows.map((r, idx) => {
                const isFirst = !!r.is_first_item_of_sale;
                const rowPayCol = r.payment_column;
                const rowPayNominal = Number(r.payment_nominal_on_row || 0);
                const rowPayDate = r.payment_date_on_row || "";
                const rowDisc = isFirst ? Number(r.sale_discount || 0) : 0;
                const rowTotal = isFirst ? Number(r.sale_total || 0) : 0;
                const jumlah = Number(r.unit_price || 0) * Number(r.pcs || r.quantity || 0);
                return (
                  <tr key={idx} data-testid="report-row" className={`border-b border-zinc-100 hover:bg-zinc-50 ${isFirst ? "" : "bg-zinc-50/30"}`}>
                    <td className="px-2 py-2 text-center font-mono text-[11px] font-bold text-zinc-500 border-r border-zinc-100">{idx + 1}</td>
                    <td className="px-2 py-2 font-mono text-[11px] whitespace-nowrap border-r border-zinc-100">{r.date}</td>
                    <td className="px-2 py-2 font-mono text-[11px] border-r border-zinc-100">{r.sale_no}</td>
                    <td className="px-2 py-2 text-xs border-r border-zinc-100">{r.alamat || <span className="text-zinc-300">—</span>}</td>
                    <td className="px-2 py-2 text-xs border-r border-zinc-100">
                      {r.product_name}
                      {r.size && r.size !== "-" && (
                        <span className="ml-1.5 text-[9px] font-bold uppercase text-zinc-500">[{r.size}]</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-center font-mono text-xs border-r border-zinc-100">{r.pcs || r.quantity}</td>
                    <td className="px-2 py-2 text-center font-mono text-xs border-r border-zinc-100">
                      {Number(r.meter || 0) > 0 ? Number(r.meter).toFixed(2) : <span className="text-zinc-300">—</span>}
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">{formatIDR(r.unit_price)}</td>
                    <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">
                      {rowDisc > 0 ? <span className="text-[#E81123] font-semibold">{formatIDR(rowDisc)}</span> : <span className="text-zinc-300">—</span>}
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">{formatIDR(jumlah)}</td>
                    <td className="px-2 py-2 text-right font-mono text-sm font-bold text-[#002FA7] bg-[#002FA7]/5 border-r border-zinc-100">
                      {isFirst ? formatIDR(rowTotal) : <span className="text-zinc-300">—</span>}
                    </td>
                    <td className="px-2 py-2 text-xs text-zinc-600 border-r border-zinc-100">
                      {r.keterangan ? <span title={r.keterangan}>{r.keterangan.slice(0, 40)}{r.keterangan.length > 40 ? "…" : ""}</span> : <span className="text-zinc-300">—</span>}
                    </td>
                    {PAY_COLS.map((c, i) => {
                      const matches = isFirst && rowPayCol === c.key;
                      return (
                        <Fragment key={c.key + "-" + idx}>
                          <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">
                            {matches ? <span className="font-bold text-zinc-900">{formatIDR(rowPayNominal)}</span> : <span className="text-zinc-200">—</span>}
                          </td>
                          <td className={`px-2 py-2 text-center font-mono text-[10px] ${i < PAY_COLS.length - 1 ? "border-r border-zinc-100" : ""}`}>
                            {matches ? rowPayDate : <span className="text-zinc-200">—</span>}
                          </td>
                        </Fragment>
                      );
                    })}
                  </tr>
                );
              })}
              {!loading && rows.length > 0 && (
                <tr className="border-t-2 border-zinc-900 bg-[#002FA7]/5">
                  <td colSpan={5} className="px-2 py-3 border-r border-zinc-200">
                    <span className="text-xs font-bold uppercase tracking-widest text-[#002FA7]">
                      Total · {uniqueSaleTotals.size} transaksi {searchRow ? "(Filtered)" : ""}
                    </span>
                  </td>
                  <td className="px-2 py-3 text-center font-mono font-bold text-zinc-900 border-r border-zinc-200">{totalRowsQty}</td>
                  <td className="px-2 py-3 text-center font-mono font-bold text-zinc-900 border-r border-zinc-200">
                    {totalRowsMeter > 0 ? totalRowsMeter.toFixed(2) : "—"}
                  </td>
                  <td className="px-2 py-3 border-r border-zinc-200"></td>
                  <td className="px-2 py-3 text-right font-mono font-bold text-[#E81123] border-r border-zinc-200">{formatIDR(totalRowsDisc)}</td>
                  <td className="px-2 py-3 text-right font-mono font-bold text-zinc-700 border-r border-zinc-200">{formatIDR(totalRowsItemsSubtotal)}</td>
                  <td className="px-2 py-3 text-right font-mono font-bold text-lg text-[#002FA7] border-r border-zinc-200">{formatIDR(totalRowsAmount)}</td>
                  <td className="px-2 py-3 border-r border-zinc-200"></td>
                  {PAY_COLS.map((c, i) => (
                    <Fragment key={c.key + "-foot"}>
                      <td data-testid={`pay-total-${c.key}`} className="px-2 py-3 text-right font-mono font-bold text-xs text-zinc-900 border-r border-zinc-200">
                        {payTotals[c.key] > 0 ? formatIDR(payTotals[c.key]) : "—"}
                      </td>
                      <td className={`px-2 py-3 ${i < PAY_COLS.length - 1 ? "border-r border-zinc-200" : ""}`}></td>
                    </Fragment>
                  ))}
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
