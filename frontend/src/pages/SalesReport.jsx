import { useEffect, useMemo, useState, Fragment } from "react";
import { api, formatIDR, formatApiError } from "../lib/api";
import { toast } from "sonner";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { Search, TrendingUp, Package, Calendar, Award, Users, ChevronLeft, ChevronRight, FileSpreadsheet, Eye, EyeOff, AlertCircle } from "lucide-react";

const PAGE_SIZE_OPTIONS = [20, 50, 100, 500];
const HIDDEN_PAY_STORAGE_KEY = "salesReport.hiddenPayCols";

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
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [exporting, setExporting] = useState(false);
  const [hiddenPayCols, setHiddenPayCols] = useState(() => {
    try {
      const raw = localStorage.getItem(HIDDEN_PAY_STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch { return []; }
  });
  useEffect(() => {
    try { localStorage.setItem(HIDDEN_PAY_STORAGE_KEY, JSON.stringify(hiddenPayCols)); } catch { /* noop */ }
  }, [hiddenPayCols]);
  const togglePayCol = (key) => {
    setHiddenPayCols((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  };

  // Reset ke halaman 1 saat filter atau search berubah
  useEffect(() => { setPage(1); }, [searchRow, dateFrom, dateTo, customer, pageSize]);

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

  // Pagination (client-side) — max N baris per halaman
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(Math.max(1, page), totalPages);
  const pageStart = (safePage - 1) * pageSize;
  const pageEnd = Math.min(rows.length, pageStart + pageSize);
  const pagedRows = rows.slice(pageStart, pageEnd);

  const exportExcel = async () => {
    setExporting(true);
    try {
      const res = await api.get("/sales/report/excel", {
        params: {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          customer: customer.trim() || undefined,
        },
        responseType: "blob",
      });
      const blob = new Blob([res.data], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Laporan_Penjualan_${dateFrom || "all"}_${dateTo || "all"}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Excel berhasil diunduh");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal export Excel");
    } finally {
      setExporting(false);
    }
  };

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
  const uniqueSaleSisa = new Map();
  const uniqueSaleStatus = new Map();
  rows.forEach((r) => {
    if (!uniqueSaleTotals.has(r.sale_no)) {
      uniqueSaleTotals.set(r.sale_no, Number(r.sale_total || 0));
      uniqueSaleDiscounts.set(r.sale_no, Number(r.sale_discount || 0));
      uniqueSaleSisa.set(r.sale_no, Number(r.sale_sisa_tagihan || 0));
      uniqueSaleStatus.set(r.sale_no, r.sale_status || (Number(r.sale_sisa_tagihan || 0) > 0.01 ? "dp" : "paid"));
    }
  });
  // Total lain (Diskon, Sisa, DP count) tetap dari rows-dedup.
  // NB: totalRowsAmount (invoice total per sale) sengaja TIDAK dipakai lagi untuk chip/footer
  // agar Omzet konsisten dengan kartu ringkasan (Uang Diterima) dan Buku Kas.
  const totalRowsDisc = Array.from(uniqueSaleDiscounts.values()).reduce((s, v) => s + v, 0);
  const totalRowsSisa = Array.from(uniqueSaleSisa.values()).reduce((s, v) => s + v, 0);
  const dpCount = Array.from(uniqueSaleStatus.values()).filter((v) => v === "dp").length;
  const totalRowsItemsSubtotal = rows.reduce((s, r) => s + Number(r.total || 0), 0);

  // Payment column totals — sum by payment_column key (already normalized by backend)
  const PAY_COLS = [
    { key: "cash_plaza", label: "Cash Plaza", color: "bg-[#008A00]/80" },
    { key: "cash_kastem", label: "Cash Kastem", color: "bg-[#008A00]/60" },
    { key: "bca_plaza", label: "BCA Plaza", color: "bg-[#002FA7]/80" },
    { key: "bca_kastem", label: "BCA Kastem", color: "bg-[#002FA7]/60" },
    { key: "mandiri_plaza", label: "Mandiri Plaza", color: "bg-[#E81123]/80" },
    { key: "mandiri_kastem", label: "Mandiri Kastem", color: "bg-[#E81123]/60" },
    { key: "shopee_plaza", label: "Shopee Plaza", color: "bg-[#F97316]" },
    { key: "shopee_kastem", label: "Shopee Kastem", color: "bg-[#FDBA74] text-zinc-900" },
  ];
  const visiblePayCols = PAY_COLS.filter((c) => !hiddenPayCols.includes(c.key));
  // 12 main + 2 (sisa + status) + N pay cols × 2 = totalColSpan
  const totalColSpan = 14 + visiblePayCols.length * 2;
  const payTotals = Object.fromEntries(PAY_COLS.map((c) => [c.key, 0]));
  rows.forEach((r) => {
    // Count both DP awal (is_first_item_of_sale) and pelunasan rows
    if ((r.is_first_item_of_sale || r.is_pelunasan_row) && r.payment_column && payTotals[r.payment_column] !== undefined) {
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
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-px bg-zinc-200 border border-zinc-200 mt-6 max-w-7xl">
        <div className="bg-white p-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Omzet Periode Ini <span className="text-[9px] normal-case tracking-normal text-[#008A00]">(Uang Diterima)</span></div>
              <div data-testid="summary-period-total" className="font-mono text-2xl font-bold mt-1 text-[#002FA7]" title="OMZET = Uang yang sudah diterima (DP + Pelunasan) berdasarkan tanggal pembayaran. Piutang/sisa tagihan tidak dihitung. Untuk Shopee dipakai NETTO (Gross − Admin fee).">{formatIDR(data.summary?.period_total || 0)}</div>
              <div className="text-[10px] text-zinc-500 mt-1 font-mono">{data.summary?.transaction_count || 0} transaksi · {data.summary?.item_count || 0} item</div>
              {Number(data.summary?.shopee_admin_fee || 0) > 0 && (
                <div className="text-[10px] font-mono text-[#EE4D2D] mt-1 leading-tight">
                  Gross: {formatIDR(data.summary?.period_total_gross || 0)}<br/>
                  <span className="text-zinc-500">− Admin Shopee: {formatIDR(data.summary?.shopee_admin_fee || 0)}</span>
                </div>
              )}
            </div>
            <TrendingUp className="w-5 h-5 text-[#002FA7]/50" />
          </div>
        </div>
        <div className="bg-white p-4" data-testid="summary-piutang-card">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Piutang Aktif <span className="text-[9px] normal-case tracking-normal text-[#E81123]">(Belum Tertagih)</span></div>
              <div data-testid="summary-piutang-total" className={`font-mono text-2xl font-bold mt-1 ${totalRowsSisa > 0.01 ? "text-[#E81123]" : "text-zinc-400"}`} title="Total sisa tagihan pelanggan yang belum masuk kas. Angka ini SUDAH DIKELUARKAN dari Omzet.">
                {formatIDR(totalRowsSisa)}
              </div>
              <div className="text-[10px] text-zinc-500 mt-1 font-mono">
                {dpCount > 0 ? `${dpCount} transaksi DP` : "Semua transaksi LUNAS"}
              </div>
            </div>
            <AlertCircle className={`w-5 h-5 ${totalRowsSisa > 0.01 ? "text-[#E81123]/60" : "text-zinc-300"}`} />
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

      {/* Shopee Admin Fee Bulk Set */}
      <ShopeeAdminFeeControl dateFrom={dateFrom} dateTo={dateTo} onDone={load} summary={data.summary} />

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
          <div className="flex items-center gap-2 flex-wrap">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
              <input
                value={searchRow} onChange={(e) => setSearchRow(e.target.value)}
                placeholder="Cari produk / pelanggan / no.nota…"
                data-testid="report-row-search"
                className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-80 focus:border-[#002FA7] focus:outline-none"
              />
            </div>
            <button
              data-testid="report-export-excel"
              onClick={exportExcel}
              disabled={exporting || rows.length === 0}
              className="inline-flex items-center gap-1.5 border border-[#008A00] bg-[#008A00] text-white px-3 py-2 text-xs font-bold uppercase tracking-wider hover:bg-[#006D00] disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <FileSpreadsheet className="w-3.5 h-3.5" />
              {exporting ? "Memproses…" : "Export Excel"}
            </button>
            <div className="text-xs font-mono text-zinc-500">{rows.length} item · Total <b className="text-[#002FA7]" data-testid="chip-total-omzet">{formatIDR(data.summary?.period_total || 0)}</b></div>
          </div>
        </div>
        {/* Toolbar: Sembunyikan Kolom Pembayaran */}
        <div className="px-4 py-2.5 border-b border-zinc-200 bg-zinc-50/70 flex flex-wrap items-center gap-2">
          <div className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 mr-1">Kolom Pembayaran:</div>
          {PAY_COLS.map((c) => {
            const hidden = hiddenPayCols.includes(c.key);
            return (
              <button
                key={c.key}
                type="button"
                data-testid={`toggle-pay-${c.key}`}
                onClick={() => togglePayCol(c.key)}
                title={hidden ? "Klik untuk tampilkan" : "Klik untuk sembunyikan"}
                className={`inline-flex items-center gap-1.5 px-2 py-1 text-[10px] font-bold uppercase tracking-wider border transition-colors ${
                  hidden
                    ? "border-zinc-200 bg-white text-zinc-400 hover:bg-zinc-100"
                    : `border-transparent ${c.color} text-white`
                }`}
              >
                {hidden ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                {c.label}
              </button>
            );
          })}
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              data-testid="pay-cols-show-all"
              onClick={() => setHiddenPayCols([])}
              disabled={hiddenPayCols.length === 0}
              className="text-[10px] font-mono text-[#002FA7] hover:underline disabled:text-zinc-300 disabled:cursor-not-allowed"
            >
              Tampilkan Semua
            </button>
            <span className="text-zinc-300 text-xs">·</span>
            <button
              type="button"
              data-testid="pay-cols-hide-all"
              onClick={() => setHiddenPayCols(PAY_COLS.map((c) => c.key))}
              disabled={hiddenPayCols.length === PAY_COLS.length}
              className="text-[10px] font-mono text-zinc-600 hover:underline disabled:text-zinc-300 disabled:cursor-not-allowed"
            >
              Sembunyikan Semua
            </button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table data-testid="report-table" className="text-left text-sm" style={{ minWidth: Math.max(1200, 12 * 90 + visiblePayCols.length * 2 * 80) }}>
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
                <th rowSpan={2} className="px-2 py-2 text-right border-r border-zinc-700 whitespace-nowrap bg-yellow-500 text-zinc-900">Sisa Tagihan</th>
                <th rowSpan={2} className="px-2 py-2 text-center border-r border-zinc-700 whitespace-nowrap">Status</th>
                <th rowSpan={2} className="px-2 py-2 border-r border-zinc-700 min-w-[120px]">Keterangan</th>
                {/* Payment column groups — dynamic based on visiblePayCols */}
                {visiblePayCols.map((c) => (
                  <th key={c.key + "-grp"} colSpan={2} className={`px-2 py-1 text-center border-r border-b border-zinc-700 ${c.color}`}>{c.label}</th>
                ))}
              </tr>
              <tr className="bg-zinc-900 text-white text-[9px] font-bold uppercase tracking-wider">
                {visiblePayCols.map((c, i) => (
                  <Fragment key={c.key + "-h"}>
                    <th className="px-2 py-1 text-right border-r border-zinc-700 whitespace-nowrap bg-zinc-800/60">Nominal</th>
                    <th className={`px-2 py-1 text-center whitespace-nowrap bg-zinc-800/60 ${i < visiblePayCols.length - 1 ? "border-r border-zinc-700" : ""}`}>Tanggal</th>
                  </Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={totalColSpan} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={totalColSpan} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada transaksi pada periode ini.</td></tr>
              )}
              {pagedRows.map((r, i) => {
                const idx = pageStart + i;
                const isFirst = !!r.is_first_item_of_sale;
                const isPelunasan = !!r.is_pelunasan_row;
                const rowPayCol = r.payment_column;
                const rowPayNominal = Number(r.payment_nominal_on_row || 0);
                const rowPayDate = r.payment_date_on_row || "";
                const rowDisc = isFirst ? Number(r.sale_discount || 0) : 0;
                const rowTotal = isFirst ? Number(r.sale_total || 0) : 0;
                const jumlah = Number(r.unit_price || 0) * Number(r.pcs || r.quantity || 0);
                return (
                  <tr
                    key={idx}
                    data-testid={isPelunasan ? "report-row-pelunasan" : "report-row"}
                    className={`border-b border-zinc-100 hover:bg-zinc-50 ${isPelunasan ? "bg-[#008A00]/5" : (isFirst ? "" : "bg-zinc-50/30")}`}
                  >
                    <td className="px-2 py-2 text-center font-mono text-[11px] font-bold text-zinc-500 border-r border-zinc-100">
                      {isPelunasan ? <span className="text-[#008A00]">↳</span> : idx + 1}
                    </td>
                    <td className="px-2 py-2 font-mono text-[11px] whitespace-nowrap border-r border-zinc-100">{r.date}</td>
                    <td className="px-2 py-2 font-mono text-[11px] border-r border-zinc-100">{r.sale_no}</td>
                    <td className="px-2 py-2 text-xs border-r border-zinc-100">{r.alamat || <span className="text-zinc-300">—</span>}</td>
                    <td className="px-2 py-2 text-xs border-r border-zinc-100">
                      {isPelunasan ? (
                        <span className="italic text-[#008A00] font-semibold">{r.product_name}</span>
                      ) : (
                        <>
                          {r.product_name}
                          {r.size && r.size !== "-" && (
                            <span className="ml-1.5 text-[9px] font-bold uppercase text-zinc-500">[{r.size}]</span>
                          )}
                        </>
                      )}
                    </td>
                    <td className="px-2 py-2 text-center font-mono text-xs border-r border-zinc-100">
                      {isPelunasan ? <span className="text-zinc-300">—</span> : (r.pcs || r.quantity)}
                    </td>
                    <td className="px-2 py-2 text-center font-mono text-xs border-r border-zinc-100">
                      {Number(r.meter || 0) > 0 ? Number(r.meter).toFixed(2) : <span className="text-zinc-300">—</span>}
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">
                      {isPelunasan ? <span className="text-zinc-300">—</span> : formatIDR(r.unit_price)}
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">
                      {rowDisc > 0 ? <span className="text-[#E81123] font-semibold">{formatIDR(rowDisc)}</span> : <span className="text-zinc-300">—</span>}
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">
                      {isPelunasan ? <span className="text-zinc-300">—</span> : formatIDR(jumlah)}
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-sm font-bold text-[#002FA7] bg-[#002FA7]/5 border-r border-zinc-100">
                      {isFirst ? formatIDR(rowTotal) : <span className="text-zinc-300">—</span>}
                    </td>
                    <td className="px-2 py-2 text-right font-mono text-xs bg-yellow-50 border-r border-zinc-100">
                      {isFirst && Number(r.sale_sisa_tagihan || 0) > 0.01 ? (
                        <span data-testid="report-sisa" className="text-[#E81123] font-bold">{formatIDR(r.sale_sisa_tagihan)}</span>
                      ) : (
                        <span className="text-zinc-300">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-center border-r border-zinc-100">
                      {isFirst ? (
                        (r.sale_status === "dp") ? (
                          <span data-testid="report-status-dp" className="inline-block bg-yellow-400 text-yellow-900 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest">DP</span>
                        ) : (
                          <span data-testid="report-status-lunas" className="inline-block bg-[#008A00]/15 text-[#008A00] border border-[#008A00]/30 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest">LUNAS</span>
                        )
                      ) : isPelunasan ? (
                        <span className="inline-block bg-[#008A00] text-white px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest">PELUNASAN</span>
                      ) : <span className="text-zinc-300">—</span>}
                    </td>
                    <td className="px-2 py-2 text-xs text-zinc-600 border-r border-zinc-100">
                      {r.keterangan ? <span title={r.keterangan}>{r.keterangan.slice(0, 40)}{r.keterangan.length > 40 ? "…" : ""}</span> : <span className="text-zinc-300">—</span>}
                    </td>
                    {visiblePayCols.map((c, i) => {
                      const matches = (isFirst || isPelunasan) && rowPayCol === c.key;
                      return (
                        <Fragment key={c.key + "-" + idx}>
                          <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">
                            {matches ? <span className={`font-bold ${isPelunasan ? "text-[#008A00]" : "text-zinc-900"}`}>{formatIDR(rowPayNominal)}</span> : <span className="text-zinc-200">—</span>}
                          </td>
                          <td className={`px-2 py-2 text-center font-mono text-[10px] ${i < visiblePayCols.length - 1 ? "border-r border-zinc-100" : ""}`}>
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
                  <td className="px-2 py-3 text-right font-mono font-bold text-lg text-[#002FA7] border-r border-zinc-200" data-testid="footer-total-omzet">{formatIDR(data.summary?.period_total || 0)}</td>
                  <td data-testid="footer-total-sisa" className="px-2 py-3 text-right font-mono font-bold text-[#E81123] bg-yellow-50 border-r border-zinc-200">{formatIDR(totalRowsSisa)}</td>
                  <td className="px-2 py-3 text-center text-[10px] font-bold text-zinc-500 border-r border-zinc-200">
                    {totalRowsSisa > 0.01 ? `${dpCount} DP` : "—"}
                  </td>
                  <td className="px-2 py-3 border-r border-zinc-200"></td>
                  {visiblePayCols.map((c, i) => (
                    <Fragment key={c.key + "-foot"}>
                      <td data-testid={`pay-total-${c.key}`} className="px-2 py-3 text-right font-mono font-bold text-xs text-zinc-900 border-r border-zinc-200">
                        {payTotals[c.key] > 0 ? formatIDR(payTotals[c.key]) : "—"}
                      </td>
                      <td className={`px-2 py-3 ${i < visiblePayCols.length - 1 ? "border-r border-zinc-200" : ""}`}></td>
                    </Fragment>
                  ))}
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Controls */}
        {!loading && rows.length > 0 && (
          <div data-testid="report-pagination" className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-zinc-200 bg-zinc-50/50">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="text-[11px] font-mono text-zinc-600">
                Menampilkan <b className="text-zinc-900">{pageStart + 1}</b>–<b className="text-zinc-900">{pageEnd}</b> dari <b className="text-zinc-900">{rows.length}</b> baris
                <span className="text-zinc-400"> · </span>
                Halaman <b className="text-[#002FA7]">{safePage}</b> / {totalPages}
              </div>
              <div className="flex items-center gap-2 border-l border-zinc-200 pl-3">
                <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Per Halaman</label>
                <select
                  data-testid="page-size-select"
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                  className="border border-zinc-300 bg-white px-2 py-1 text-xs font-mono focus:border-[#002FA7] focus:outline-none"
                >
                  {PAGE_SIZE_OPTIONS.map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                data-testid="pagination-first"
                onClick={() => setPage(1)}
                disabled={safePage <= 1}
                className="px-2.5 py-1.5 border border-zinc-300 bg-white text-xs font-mono hover:bg-zinc-900 hover:text-white hover:border-zinc-900 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-white disabled:hover:text-zinc-500"
                title="Halaman Pertama"
              >
                «
              </button>
              <button
                data-testid="pagination-prev"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={safePage <= 1}
                className="inline-flex items-center gap-1 px-3 py-1.5 border border-zinc-300 bg-white text-xs font-semibold uppercase tracking-wider hover:bg-zinc-900 hover:text-white hover:border-zinc-900 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-white disabled:hover:text-zinc-500"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> Previous
              </button>

              {/* Page number buttons (max 5 around current) */}
              {(() => {
                const buttons = [];
                const maxBtns = 5;
                let start = Math.max(1, safePage - 2);
                let end = Math.min(totalPages, start + maxBtns - 1);
                if (end - start + 1 < maxBtns) start = Math.max(1, end - maxBtns + 1);
                for (let p = start; p <= end; p++) {
                  buttons.push(
                    <button
                      key={p}
                      data-testid={`pagination-page-${p}`}
                      onClick={() => setPage(p)}
                      className={`min-w-[32px] px-2 py-1.5 border text-xs font-mono font-bold ${
                        p === safePage
                          ? "border-[#002FA7] bg-[#002FA7] text-white"
                          : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-900 hover:text-white hover:border-zinc-900"
                      }`}
                    >
                      {p}
                    </button>
                  );
                }
                return buttons;
              })()}

              <button
                data-testid="pagination-next"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={safePage >= totalPages}
                className="inline-flex items-center gap-1 px-3 py-1.5 border border-zinc-300 bg-white text-xs font-semibold uppercase tracking-wider hover:bg-zinc-900 hover:text-white hover:border-zinc-900 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-white disabled:hover:text-zinc-500"
              >
                Next <ChevronRight className="w-3.5 h-3.5" />
              </button>
              <button
                data-testid="pagination-last"
                onClick={() => setPage(totalPages)}
                disabled={safePage >= totalPages}
                className="px-2.5 py-1.5 border border-zinc-300 bg-white text-xs font-mono hover:bg-zinc-900 hover:text-white hover:border-zinc-900 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-white disabled:hover:text-zinc-500"
                title="Halaman Terakhir"
              >
                »
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


function ShopeeAdminFeeControl({ dateFrom, dateTo, onDone, summary }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("percent");
  const [value, setValue] = useState(5);
  const [busy, setBusy] = useState(false);
  const shopeeGross = Number(summary?.shopee_gross || 0);
  const currentFee = Number(summary?.shopee_admin_fee || 0);
  if (!open) {
    return (
      <div className="mt-4 border border-[#EE4D2D]/30 bg-[#EE4D2D]/5 p-3 max-w-7xl flex items-center justify-between gap-3">
        <div className="text-xs text-zinc-700">
          <span className="font-bold text-[#EE4D2D]">Biaya Admin Shopee (periode ini):</span>{" "}
          <span className="font-mono">Rp {currentFee.toLocaleString("id-ID")}</span>{" "}
          <span className="text-zinc-500">dari Gross Shopee Rp {shopeeGross.toLocaleString("id-ID")}</span>
        </div>
        <button
          data-testid="open-shopee-fee-modal"
          onClick={() => setOpen(true)}
          className="rounded-none bg-[#EE4D2D] text-white px-4 py-2 text-xs font-bold uppercase tracking-wider hover:bg-[#D63C1E] whitespace-nowrap"
        >
          Set / Hitung Ulang Fee
        </button>
      </div>
    );
  }
  const apply = async () => {
    const v = Number(value);
    if (isNaN(v) || v < 0) { toast.error("Nilai tidak valid"); return; }
    if (!window.confirm(
      `Terapkan biaya admin Shopee (${mode === "percent" ? v + "%" : "Rp " + v.toLocaleString("id-ID") + " flat"}) ke SEMUA transaksi Shopee di periode ${dateFrom} s/d ${dateTo}?\n\nBaris pengeluaran '502-SHP Biaya Admin Shopee' akan diperbarui otomatis di Buku Kas.\nLanjut?`
    )) return;
    setBusy(true);
    try {
      const res = await api.post("/sales/shopee/bulk-set-admin-fee", {
        date_from: dateFrom, date_to: dateTo, mode, value: v,
      });
      toast.success(`Berhasil update ${res.data.updated_count} transaksi Shopee. Total fee: Rp ${Number(res.data.total_fee).toLocaleString("id-ID")}`);
      setOpen(false);
      onDone?.();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal terapkan biaya admin");
    } finally { setBusy(false); }
  };
  return (
    <div className="mt-4 border border-[#EE4D2D] bg-[#EE4D2D]/5 p-4 max-w-7xl">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[10px] uppercase tracking-widest font-bold text-[#EE4D2D]">Set Biaya Admin Shopee</div>
          <div className="text-xs text-zinc-600 mt-0.5">Periode: {dateFrom} → {dateTo}</div>
        </div>
        <button onClick={() => setOpen(false)} className="text-xs text-zinc-500 hover:text-zinc-900">Tutup ✕</button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
        <div>
          <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1.5">Mode Perhitungan</label>
          <select data-testid="shopee-fee-mode" value={mode} onChange={(e) => setMode(e.target.value)}
            className="w-full rounded-none border border-zinc-300 px-3 py-2 text-sm">
            <option value="percent">Persentase (% dari Gross)</option>
            <option value="flat">Nominal Flat (Rp per transaksi)</option>
          </select>
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1.5">
            {mode === "percent" ? "Persentase (%)" : "Nominal (Rp)"}
          </label>
          <input data-testid="shopee-fee-value" type="number" min="0" step={mode === "percent" ? "0.1" : "100"} value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={mode === "percent" ? "5" : "5000"}
            className="w-full rounded-none border border-zinc-300 px-3 py-2 text-sm font-mono" />
        </div>
        <div>
          <button data-testid="apply-shopee-fee" onClick={apply} disabled={busy}
            className="w-full rounded-none bg-[#EE4D2D] text-white px-4 py-2.5 text-sm font-bold uppercase tracking-wider hover:bg-[#D63C1E] disabled:opacity-40">
            {busy ? "Menerapkan…" : "Terapkan ke Semua Shopee"}
          </button>
        </div>
      </div>
      <div className="mt-3 text-[10px] font-mono text-zinc-500">
        {mode === "percent" ? `Fee per tx = Gross × ${value || 0}%. Estimasi total fee (gross Rp ${shopeeGross.toLocaleString("id-ID")}) ≈ Rp ${Math.round(shopeeGross * Number(value || 0) / 100).toLocaleString("id-ID")}` : `Fee per tx = Rp ${Number(value || 0).toLocaleString("id-ID")} flat`}
      </div>
    </div>
  );
}
