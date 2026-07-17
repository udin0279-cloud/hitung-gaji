import { useEffect, useState } from "react";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import { Plus, Trash2, X, Search, ShoppingBag, Printer, Receipt, DollarSign, TrendingUp, FileText, Download, FileSpreadsheet, Pencil } from "lucide-react";

const inputCls = "rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none";

function formatNum(n, digits = 4) {
  if (n === null || n === undefined || n === "") return "0";
  return Number(n).toLocaleString("id-ID", { maximumFractionDigits: digits });
}

export default function Sales() {
  const [sales, setSales] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [products, setProducts] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [openNew, setOpenNew] = useState(false);
  const [openReport, setOpenReport] = useState(false);
  const [editingSale, setEditingSale] = useState(null);
  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  const loadSales = async (pageArg = page, pageSizeArg = pageSize, qArg = search) => {
    try {
      const res = await api.get("/sales", {
        params: { paginate: true, page: pageArg, page_size: pageSizeArg, q: qArg.trim() || undefined },
      });
      setSales(res.data.items);
      setTotalItems(res.data.total || 0);
      setTotalPages(res.data.pages || 0);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat transaksi");
    }
  };

  const loadAll = async () => {
    setLoading(true);
    try {
      const [m, c, p, st] = await Promise.all([
        api.get("/inventory/materials"),
        api.get("/inventory/customers"),
        api.get("/products", { params: { only_active: true } }),
        api.get("/sales/stats/today"),
      ]);
      setMaterials(m.data);
      setCustomers(c.data);
      setProducts(p.data);
      setStats(st.data);
      await loadSales(page, pageSize, search);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); /* eslint-disable-next-line */ }, []);

  // Debounced search — reset ke page 1 saat search berubah
  useEffect(() => {
    const t = setTimeout(() => {
      setPage(1);
      loadSales(1, pageSize, search);
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line
  }, [search]);

  const goToPage = async (newPage) => {
    if (newPage < 1 || newPage > totalPages) return;
    setPage(newPage);
    await loadSales(newPage, pageSize, search);
  };
  const changePageSize = async (newSize) => {
    setPageSize(newSize);
    setPage(1);
    await loadSales(1, newSize, search);
  };

  const filtered = sales; // Server-side sudah filter

  const openReceipt = (s, auto = false) => {
    const url = `${API}/sales/${s.id}/receipt${auto ? "?auto=1" : ""}`;
    window.open(url, "_blank", "width=380,height=650");
  };

  const openInvoiceA4 = (s) => {
    const url = `${API}/sales/${s.id}/invoice-pdf`;
    window.open(url, "_blank");
  };

  const remove = async (s) => {
    if (!window.confirm(`Hapus transaksi ${s.sale_no}? Stok akan dikembalikan.`)) return;
    try { await api.delete(`/sales/${s.id}`); toast.success("Transaksi dihapus, stok dikembalikan"); await loadAll(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  // Refresh products & materials sebelum modal dibuka (defensive - biar tidak stale)
  const openNewSale = async () => {
    try {
      const [m, p] = await Promise.all([
        api.get("/inventory/materials"),
        api.get("/products", { params: { only_active: true } }),
      ]);
      setMaterials(m.data);
      setProducts(p.data);
    } catch (_err) { /* fallback tetap pakai state existing */ }
    setEditingSale(null);
    setOpenNew(true);
  };

  const openEditSale = async (s) => {
    try {
      const [m, p] = await Promise.all([
        api.get("/inventory/materials"),
        api.get("/products", { params: { only_active: true } }),
      ]);
      setMaterials(m.data);
      setProducts(p.data);
    } catch (_err) { /* keep existing */ }
    setEditingSale(s);
    setOpenNew(true);
  };

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Modul</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Penjualan / Kasir</h1>
          <p className="text-sm text-zinc-500 mt-1">POS digital printing — hitung otomatis berdasarkan luas (P×L×Qty) &amp; cetak struk thermal 80mm.</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button data-testid="open-sales-report-button" onClick={() => setOpenReport(true)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-4 py-2.5 text-sm hover:bg-zinc-50 inline-flex items-center gap-2">
            <FileText className="w-4 h-4" /> Laporan Bulanan
          </button>
          <button data-testid="new-sale-button" onClick={openNewSale} className="rounded-none bg-[#002FA7] text-white px-6 py-3 text-sm font-bold uppercase tracking-wider hover:bg-[#002FA7]/90 inline-flex items-center gap-2">
            <Plus className="w-4 h-4" /> Transaksi Baru
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
        <StatCard label="Transaksi Hari Ini" value={stats?.count_today ?? 0} icon={Receipt} isCount testId="stat-count-today" />
        <StatCard label="Omset Hari Ini" value={stats?.total_today ?? 0} icon={DollarSign} testId="stat-total-today" positive />
        <StatCard label="Transaksi Bulan Ini" value={stats?.count_month ?? 0} icon={ShoppingBag} isCount testId="stat-count-month" />
        <StatCard label="Omset Bulan Ini" value={stats?.total_month ?? 0} icon={TrendingUp} testId="stat-total-month" positive />
      </div>

      {/* Search + Table */}
      <div className="mt-8">
        <div className="flex items-center justify-between mb-4">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input data-testid="sales-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari No. Nota / nama pelanggan / telp…" className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none" />
          </div>
          <div className="text-sm text-zinc-500">
            {totalItems === 0 ? "0 transaksi" : (
              <>Menampilkan <b>{sales.length}</b> dari <b>{totalItems}</b> transaksi</>
            )}
          </div>
        </div>

        <div className="border border-zinc-200 bg-white overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                <th className="px-4 py-3 text-center w-12">No</th>
                <th className="px-4 py-3">No. Nota</th>
                <th className="px-4 py-3">Pelanggan</th>
                <th className="px-4 py-3">Item</th>
                <th className="px-4 py-3">Kasir</th>
                <th className="px-4 py-3">Bayar</th>
                <th className="px-4 py-3 text-right">Total</th>
                <th className="px-4 py-3 text-right">Kembali</th>
                <th className="px-4 py-3 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={9} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={9} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada transaksi. Klik &ldquo;Transaksi Baru&rdquo;.</td></tr>
              )}
              {filtered.map((s, idx) => (
                <tr key={s.id} data-testid="sale-row" className="border-b border-zinc-100 hover:bg-zinc-50/80 align-top">
                  <td className="px-4 py-3 text-center font-mono text-xs font-bold text-zinc-500">{(page - 1) * pageSize + idx + 1}</td>
                  <td className="px-4 py-3 font-mono text-xs">
                    <div className="font-semibold text-zinc-900">{s.sale_no}</div>
                    <div className="text-[10px] text-zinc-500 mt-0.5">{s.date}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-zinc-900">{s.customer_name}</div>
                    {s.customer_phone && <div className="text-xs text-zinc-500 font-mono">{s.customer_phone}</div>}
                  </td>
                  <td className="px-4 py-3 text-xs text-zinc-600">
                    {(s.items || []).map((it, i) => (
                      <div key={i}>
                        <div className="font-medium text-zinc-800">{it.product_name}</div>
                        <div className="font-mono text-[10px] text-zinc-500">{formatNum(it.length_m)}×{formatNum(it.width_m)}m × {it.quantity} = {formatNum(it.area_total)}m²</div>
                      </div>
                    ))}
                  </td>
                  <td className="px-4 py-3 text-xs text-zinc-700">{s.cashier_name || s.cashier}</td>
                  <td className="px-4 py-3">
                    <PaymentBadge sale={s} />
                  </td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-900 font-bold">{formatIDR(s.total)}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-500 text-xs">
                    <div>Bayar: {formatIDR(s.cash_paid)}</div>
                    <div className={s.change > 0 ? "text-[#008A00] font-semibold" : ""}>Kembali: {formatIDR(s.change)}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1.5 flex-wrap">
                      <button
                        data-testid="print-receipt-button"
                        onClick={() => openReceipt(s)}
                        className="inline-flex items-center gap-1.5 rounded-none border border-[#002FA7] bg-[#002FA7] text-white px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider hover:bg-[#002080] transition-colors"
                        title="Cetak Nota Thermal 80mm"
                      >
                        <Printer className="w-3.5 h-3.5" /> Struk 80mm
                      </button>
                      <button
                        data-testid="invoice-a4-button"
                        onClick={() => openInvoiceA4(s)}
                        className="inline-flex items-center gap-1.5 rounded-none border border-zinc-300 bg-white text-zinc-900 px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider hover:bg-zinc-50 transition-colors"
                        title="Nota A4 Profesional (PDF)"
                      >
                        <FileText className="w-3.5 h-3.5" /> Nota A4
                      </button>
                      <button
                        data-testid="edit-sale-button"
                        onClick={() => openEditSale(s)}
                        className="inline-flex items-center gap-1.5 rounded-none border border-zinc-300 bg-white text-zinc-900 px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider hover:bg-zinc-50 transition-colors"
                        title="Edit transaksi"
                      >
                        <Pencil className="w-3.5 h-3.5" /> Edit
                      </button>
                      <button data-testid="delete-sale-button" onClick={() => remove(s)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123] border border-transparent hover:border-[#E81123]/30" title="Hapus"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* Pagination Controls */}
        {totalItems > 0 && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border border-zinc-200 bg-white px-4 py-3">
            <div className="flex items-center gap-3 flex-wrap">
              <label className="flex items-center gap-2 text-xs text-zinc-600">
                <span className="uppercase tracking-widest font-bold">Per Halaman:</span>
                <select
                  data-testid="page-size-select"
                  value={pageSize}
                  onChange={(e) => changePageSize(Number(e.target.value))}
                  className="rounded-none border border-zinc-300 bg-white px-2 py-1 text-xs font-mono focus:border-[#002FA7] focus:outline-none"
                >
                  <option value={10}>10</option>
                  <option value={20}>20</option>
                  <option value={50}>50</option>
                </select>
              </label>
              <div className="text-xs text-zinc-500 font-mono">
                Halaman <b className="text-zinc-900">{page}</b> dari <b className="text-zinc-900">{totalPages || 1}</b>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                data-testid="pagination-first"
                onClick={() => goToPage(1)}
                disabled={page <= 1}
                className="rounded-none border border-zinc-300 bg-white text-zinc-700 px-3 py-1.5 text-xs font-bold uppercase tracking-wider hover:bg-zinc-50 disabled:opacity-30 disabled:cursor-not-allowed"
                title="Halaman pertama"
              >« First</button>
              <button
                data-testid="pagination-prev"
                onClick={() => goToPage(page - 1)}
                disabled={page <= 1}
                className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-4 py-1.5 text-xs font-bold uppercase tracking-wider hover:bg-zinc-50 disabled:opacity-30 disabled:cursor-not-allowed"
              >‹ Previous</button>
              <button
                data-testid="pagination-next"
                onClick={() => goToPage(page + 1)}
                disabled={page >= totalPages}
                className="rounded-none bg-[#002FA7] text-white px-4 py-1.5 text-xs font-bold uppercase tracking-wider hover:bg-[#001E7A] disabled:opacity-30 disabled:cursor-not-allowed"
              >Next ›</button>
              <button
                data-testid="pagination-last"
                onClick={() => goToPage(totalPages)}
                disabled={page >= totalPages}
                className="rounded-none border border-zinc-300 bg-white text-zinc-700 px-3 py-1.5 text-xs font-bold uppercase tracking-wider hover:bg-zinc-50 disabled:opacity-30 disabled:cursor-not-allowed"
                title="Halaman terakhir"
              >Last »</button>
            </div>
          </div>
        )}
      </div>

      {openNew && <NewSaleModal materials={materials} products={products} customers={customers} edit={editingSale} onClose={() => { setOpenNew(false); setEditingSale(null); }} onSaved={async (result) => { setOpenNew(false); setEditingSale(null); await loadAll(); if (result && !result._isUpdate) openReceipt(result, true); }} />}
      {openReport && <SalesReportModal onClose={() => setOpenReport(false)} />}
    </div>
  );
}

function SalesReportModal({ onClose }) {
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [downloading, setDownloading] = useState("");

  const download = async (format) => {
    setDownloading(format);
    try {
      const url = `/sales/report/${format}?month=${month}`;
      const res = await api.get(url, { responseType: "blob" });
      const mime = format === "pdf" ? "application/pdf" : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
      const blob = new Blob([res.data], { type: mime });
      const objUrl = window.URL.createObjectURL(blob);
      // PDF → open in new tab; Excel → download
      if (format === "pdf") {
        window.open(objUrl, "_blank");
      } else {
        const a = document.createElement("a");
        a.href = objUrl;
        a.download = `Laporan_Penjualan_${month}.xlsx`;
        document.body.appendChild(a); a.click(); a.remove();
        window.URL.revokeObjectURL(objUrl);
      }
      toast.success(`Laporan ${format.toUpperCase()} berhasil dibuat`);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal membuat laporan");
    } finally {
      setDownloading("");
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white border border-zinc-300 w-full max-w-lg">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center bg-[#002FA7]">
              <FileText className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Cetak / Export</div>
              <h3 className="font-bold text-zinc-900 text-lg">Laporan Penjualan Bulanan</h3>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 space-y-5">
          <div>
            <label className="block">
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 mb-1.5">Pilih Bulan</div>
              <input
                data-testid="sales-report-month"
                type="month" value={month} onChange={(e) => setMonth(e.target.value)}
                className="rounded-none border border-zinc-300 bg-white px-3 py-2.5 text-sm font-mono focus:border-[#002FA7] focus:outline-none w-full"
              />
            </label>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button
              data-testid="sales-report-pdf-btn"
              onClick={() => download("pdf")}
              disabled={!!downloading}
              className="rounded-none bg-[#E81123] hover:bg-[#c00e1f] disabled:opacity-40 text-white px-5 py-3 text-sm font-bold uppercase tracking-wider inline-flex items-center justify-center gap-2 transition-colors"
            >
              <FileText className="w-4 h-4" /> {downloading === "pdf" ? "Membuat…" : "Cetak PDF"}
            </button>
            <button
              data-testid="sales-report-excel-btn"
              onClick={() => download("excel")}
              disabled={!!downloading}
              className="rounded-none bg-[#008A00] hover:bg-[#006D00] disabled:opacity-40 text-white px-5 py-3 text-sm font-bold uppercase tracking-wider inline-flex items-center justify-center gap-2 transition-colors"
            >
              <FileSpreadsheet className="w-4 h-4" /> {downloading === "excel" ? "Membuat…" : "Export Excel"}
            </button>
          </div>
          <div className="text-[11px] text-zinc-500 bg-zinc-50 border border-zinc-200 p-3">
            <b>PDF:</b> Buka di tab baru untuk preview & cetak (landscape A4) · <b>Excel:</b> Otomatis diunduh (bisa diedit ulang).
            Laporan berisi kolom: Tanggal, No. Nota, Pelanggan, Kasir, Jumlah Item, Subtotal, Diskon, Total (+ grand total di footer).
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, isCount, testId, positive }) {
  return (
    <div className="bg-white p-4 lg:p-5">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
        <Icon className="w-3.5 h-3.5 text-zinc-400" />
      </div>
      <div data-testid={testId} className={`font-mono text-xl lg:text-2xl tracking-tight font-semibold mt-2 ${positive ? "text-[#008A00]" : "text-zinc-900"}`}>
        {isCount ? value : formatIDR(value)}
      </div>
    </div>
  );
}

/* ---------------- NEW SALE MODAL (POS) ---------------- */
// picker_id format: "prod:<id>" atau "mat:<id>"
const EMPTY_ITEM = { picker_id: "", product_id: null, material_id: null, product_name: "", length_m: 0, width_m: 0, quantity: 1, unit_price: 0, size: "" };

const TIER_A_SIZES = ["S", "M", "L", "XL"];
function sizeTier(size) {
  if (!size) return "A";
  return TIER_A_SIZES.includes(String(size).toUpperCase()) ? "A" : "B";
}

function computeConsumption(formula, factor, L, W, qty) {
  const f = Number(factor || 0);
  const q = Number(qty || 0);
  const l = Number(L || 0);
  const w = Number(W || 0);
  if (formula === "fixed") return f;
  if (formula === "per_qty") return f * q;
  if (formula === "area") return f * l * w * q;
  if (formula === "length") return f * l * q;
  return 0;
}

function NewSaleModal({ materials, products, customers, edit, onClose, onSaved }) {
  const activeMats = materials.filter((m) => m.active !== false);
  const activeProducts = (products || []).filter((p) => p.active !== false);
  const activeCustomers = (customers || []).filter((c) => c.active !== false);
  const isEdit = !!edit;

  // Initialize state from edit sale (jika ada)
  const buildInitialItems = () => {
    if (!edit || !edit.items || edit.items.length === 0) return [{ ...EMPTY_ITEM }];
    return edit.items.map((it) => ({
      picker_id: it.product_id ? `prod:${it.product_id}` : (it.material_id ? `mat:${it.material_id}` : ""),
      product_id: it.product_id || null,
      material_id: it.material_id || null,
      product_name: it.product_name || "",
      length_m: Number(it.length_m) || 0,
      width_m: Number(it.width_m) || 0,
      quantity: Number(it.quantity) || 1,
      unit_price: Number(it.unit_price) || 0,
      size: it.size || "",
    }));
  };

  const [customer, setCustomer] = useState({
    name: edit?.customer_name || "",
    phone: edit?.customer_phone || "",
  });
  const [items, setItems] = useState(buildInitialItems());
  const [discount, setDiscount] = useState(edit?.discount || 0);
  const [cashPaid, setCashPaid] = useState(edit?.cash_paid || 0);
  const [paymentMethod, setPaymentMethod] = useState(edit?.payment_method || "cash");
  const [paymentBank, setPaymentBank] = useState(edit?.payment_bank || "BCA");
  const [paymentNotes, setPaymentNotes] = useState(edit?.payment_notes || "");
  const [notes, setNotes] = useState(edit?.notes || "");
  const [saving, setSaving] = useState(false);

  const addItem = () => setItems((arr) => [...arr, { ...EMPTY_ITEM }]);
  const removeItem = (idx) => setItems((arr) => arr.filter((_, i) => i !== idx));
  const updItem = (idx, key, val) => setItems((arr) => arr.map((it, i) => i === idx ? { ...it, [key]: val } : it));

  const onCustomerNameChange = (val) => {
    const match = activeCustomers.find((c) => (c.name || "").toLowerCase() === val.trim().toLowerCase());
    setCustomer((c) => ({ name: val, phone: match ? (match.phone || "") : c.phone }));
  };

  const isExistingCustomer = () => {
    const n = customer.name.trim().toLowerCase();
    if (!n || n === "umum") return true;
    return activeCustomers.some((c) => (c.name || "").toLowerCase() === n);
  };

  const onPickerChange = (idx, picker_id) => {
    setItems((arr) => arr.map((it, i) => {
      if (i !== idx) return it;
      if (!picker_id) return { ...EMPTY_ITEM, quantity: it.quantity };
      const [kind, id] = picker_id.split(":");
      if (kind === "prod") {
        const p = activeProducts.find((x) => x.id === id);
        // Default size = first available size (kalau produk pakai sizing)
        const defaultSize = p?.has_sizes && (p.sizes || []).length > 0 ? p.sizes[0] : "";
        const tier = sizeTier(defaultSize);
        // Harga otomatis dari tier bila has_sizes, else pakai unit_price
        let price = p?.unit_price || 0;
        if (p?.has_sizes) {
          price = tier === "B" ? (p.price_size_b || p.price_size_a || 0) : (p.price_size_a || 0);
        }
        return {
          ...it,
          picker_id, product_id: id, material_id: null,
          product_name: p?.name || "",
          unit_price: price,
          length_m: 0, width_m: 0,
          size: defaultSize,
        };
      }
      if (kind === "mat") {
        const m = activeMats.find((x) => x.id === id);
        return {
          ...it,
          picker_id, material_id: id, product_id: null,
          product_name: it.product_name || m?.name || "",
          unit_price: m?.selling_price > 0 ? m.selling_price : it.unit_price,
          size: "",
        };
      }
      return it;
    }));
  };

  // Ketika user ubah size di kasir → auto-update harga dari tier
  const onSizeChange = (idx, size) => {
    setItems((arr) => arr.map((it, i) => {
      if (i !== idx) return it;
      const p = activeProducts.find((x) => x.id === it.product_id);
      if (!p || !p.has_sizes) return { ...it, size };
      const tier = sizeTier(size);
      const price = tier === "B" ? (p.price_size_b || p.price_size_a || 0) : (p.price_size_a || 0);
      return { ...it, size, unit_price: price };
    }));
  };

  // Perhitungan tiap row
  const rows = items.map((it) => {
    const product = it.product_id ? activeProducts.find((p) => p.id === it.product_id) : null;
    const material = it.material_id ? materials.find((m) => m.id === it.material_id) : null;
    const L = Number(it.length_m || 0), W = Number(it.width_m || 0), Q = Number(it.quantity || 0);
    const area = L * W;
    const area_total = area * Q;

    let subtotal = 0;
    let consumptions = []; // [{material_id, name, unit, consumption, stock, ok}]
    let requires_LW = true;
    let requires_L_only = false;
    let stock_ok = true;

    if (product) {
      const pricing = product.pricing_mode || "fixed";
      const price = Number(it.unit_price || 0);
      subtotal = pricing === "per_area" ? area_total * price : price * Q;
      requires_LW = (product.components || []).some((c) => c.formula === "area");
      requires_L_only = !requires_LW && (product.components || []).some((c) => c.formula === "length");
      const tier = product.has_sizes ? sizeTier(it.size) : "A";
      consumptions = (product.components || []).map((c) => {
        // Pakai quantity_size_b bila tier B & value ada
        let factorUse = Number(c.quantity || 0);
        if (tier === "B" && c.quantity_size_b !== null && c.quantity_size_b !== undefined && c.quantity_size_b !== "") {
          factorUse = Number(c.quantity_size_b);
        }
        const cons = computeConsumption(c.formula, factorUse, L, W, Q);
        const mat = materials.find((m) => m.id === c.material_id);
        const stock = mat ? Number(mat.current_stock || 0) : 0;
        const buy = mat ? Number(mat.purchase_price || 0) : 0;
        return {
          material_id: c.material_id,
          name: mat?.name || c.material_name || "-",
          unit: mat?.unit || c.material_unit || "",
          formula: c.formula,
          consumption: cons,
          stock,
          ok: cons <= stock,
          buy_price: buy,
          cost: cons * buy,
        };
      });
      stock_ok = consumptions.every((c) => c.ok);
    } else if (material) {
      subtotal = area_total * Number(it.unit_price || 0);
      const buy = Number(material.purchase_price || 0);
      consumptions = [{
        material_id: it.material_id,
        name: material.name,
        unit: material.unit,
        formula: "area",
        consumption: area_total,
        stock: Number(material.current_stock || 0),
        ok: area_total <= Number(material.current_stock || 0),
        buy_price: buy,
        cost: area_total * buy,
      }];
      stock_ok = consumptions[0].ok;
    }

    const cost = consumptions.reduce((s, c) => s + (c.cost || 0), 0);
    const margin = subtotal - cost;
    const margin_pct = subtotal > 0 ? (margin / subtotal) * 100 : 0;

    return { it, product, material, area, area_total, subtotal, cost, margin, margin_pct, consumptions, stock_ok, requires_LW, requires_L_only };
  });
  const subtotal = rows.reduce((s, r) => s + r.subtotal, 0);
  const total_cost = rows.reduce((s, r) => s + r.cost, 0);
  const gross_margin = subtotal - total_cost;
  const gross_margin_pct = subtotal > 0 ? (gross_margin / subtotal) * 100 : 0;
  const total = Math.max(subtotal - Number(discount || 0), 0);
  const net_margin = total - total_cost;
  const net_margin_pct = total > 0 ? (net_margin / total) * 100 : 0;
  const change = Math.max(Number(cashPaid || 0) - total, 0);
  const canSubmit = items.length > 0 && rows.every((r) => {
    if (!r.it.picker_id) return false;
    if (r.it.unit_price <= 0) return false;
    if (r.it.quantity <= 0) return false;
    if (r.product?.has_sizes && !r.it.size) return false;
    if (r.requires_LW && (r.it.length_m <= 0 || r.it.width_m <= 0)) return false;
    if (r.requires_L_only && r.it.length_m <= 0) return false;
    return r.subtotal > 0 && r.stock_ok;
  }) && Number(cashPaid || 0) >= total && total > 0;

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    try {
      const payload = {
        customer_name: customer.name.trim() || "Umum",
        customer_phone: customer.phone.trim(),
        discount: Number(discount) || 0,
        cash_paid: Number(cashPaid) || 0,
        payment_method: paymentMethod,
        payment_bank: paymentMethod === "transfer" ? paymentBank : null,
        payment_notes: paymentMethod === "transfer" ? (paymentNotes.trim() || null) : null,
        notes: notes.trim() || null,
        items: items.map((it) => ({
          material_id: it.material_id || null,
          product_id: it.product_id || null,
          product_name: it.product_name || "-",
          length_m: Number(it.length_m) || 0,
          width_m: Number(it.width_m) || 0,
          quantity: Number(it.quantity) || 1,
          unit_price: Number(it.unit_price) || 0,
          size: it.size || null,
        })),
      };
      let data;
      if (isEdit) {
        const res = await api.put(`/sales/${edit.id}`, payload);
        data = { ...res.data, _isUpdate: true };
        toast.success(`Transaksi ${data.sale_no} diperbarui`);
      } else {
        const res = await api.post("/sales", payload);
        data = res.data;
        toast.success(`Transaksi ${data.sale_no} berhasil`);
      }
      // Auto-save pelanggan baru ke Master (fire-and-forget)
      const nameClean = customer.name.trim();
      if (nameClean && nameClean.toLowerCase() !== "umum" && !isExistingCustomer()) {
        try {
          await api.post("/inventory/customers", {
            name: nameClean,
            phone: customer.phone.trim() || null,
            active: true,
          });
          toast.info(`Pelanggan "${nameClean}" tersimpan ke Master`);
        } catch (_err) { /* ignore, transaksi tetap sukses */ }
      }
      await onSaved(data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
      <div className="bg-white border border-zinc-300 w-full max-w-4xl max-h-[92vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200 sticky top-0 bg-white z-10">
          <div>
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Kasir</div>
            <div className="font-heading text-xl font-bold text-zinc-900">{isEdit ? `Edit Transaksi ${edit.sale_no}` : "Transaksi Baru"}</div>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-zinc-100" data-testid="close-new-sale-modal"><X className="w-4 h-4" /></button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-5">
          {/* Customer */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Nama Pelanggan" hint={activeCustomers.length > 0 ? `${activeCustomers.length} pelanggan di master — ketik untuk cari` : "Pelanggan baru akan otomatis tersimpan ke Master"}>
              <input
                data-testid="sale-customer-name"
                value={customer.name}
                onChange={(e) => onCustomerNameChange(e.target.value)}
                onBlur={(e) => onCustomerNameChange(e.target.value)}
                placeholder="Ketik nama / pilih dari daftar — kosongkan = Umum"
                list="sale-customers-list"
                autoComplete="off"
                className={inputCls}
              />
              <datalist id="sale-customers-list">
                {activeCustomers.map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.phone ? `${c.phone}` : ""}{c.contact_person ? ` • ${c.contact_person}` : ""}
                  </option>
                ))}
              </datalist>
              {customer.name.trim() && !isExistingCustomer() && (
                <div data-testid="new-customer-indicator" className="mt-1 text-[10px] font-bold uppercase tracking-widest text-[#008A00]">✓ Pelanggan baru — akan disimpan ke Master otomatis</div>
              )}
              {customer.name.trim() && isExistingCustomer() && customer.name.trim().toLowerCase() !== "umum" && (
                <div className="mt-1 text-[10px] font-bold uppercase tracking-widest text-[#002FA7]">◉ Pelanggan terdaftar</div>
              )}
            </Field>
            <Field label="No. Telepon (Opsional)">
              <input data-testid="sale-customer-phone" value={customer.phone} onChange={(e) => setCustomer((c) => ({ ...c, phone: e.target.value }))} placeholder="0812xxxx" className={inputCls + " font-mono"} />
            </Field>
          </div>

          {/* Items */}
          <div className="border-t border-zinc-200 pt-4">
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="text-[11px] uppercase tracking-widest font-bold text-zinc-700">Detail Produk / Order</div>
                <div className="text-[10px] text-zinc-500 font-mono mt-0.5">
                  <span data-testid="product-count-hint" className={activeProducts.length === 0 ? "text-amber-700 font-bold" : ""}>
                    {activeProducts.length} produk aktif
                  </span>
                  {" · "}
                  <span>{activeMats.length} bahan aktif</span>
                </div>
              </div>
              <button type="button" data-testid="add-sale-item" onClick={addItem} className="text-xs text-[#002FA7] hover:underline font-semibold">+ Tambah Item</button>
            </div>
            {activeProducts.length === 0 && (
              <div data-testid="no-products-hint" className="mb-3 border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
                ⚠ <b>Belum ada produk di Master Produk.</b> Buka menu <b>Inventory → Master Produk</b> untuk menambahkan produk (misal &ldquo;Cetak Brosur 120 gr&rdquo;) dengan komposisi bahan (BOM). Sementara ini kakak hanya bisa pilih dari &ldquo;Bahan Langsung&rdquo;.
              </div>
            )}
            <div className="space-y-3">
              {items.map((it, idx) => {
                const r = rows[idx];
                const isProduct = !!r.product;
                const showLW = r.requires_LW;
                const showLonly = r.requires_L_only;
                const pricingLabel = isProduct
                  ? (r.product.pricing_mode === "per_area" ? "Harga / m² (Rp)" : "Harga / pcs (Rp)")
                  : "Harga / m² (Rp)";
                return (
                  <div key={idx} className="border border-zinc-200 p-3 space-y-2 bg-zinc-50/40">
                    <div className="grid grid-cols-12 gap-2">
                      <div className="col-span-7">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Produk / Bahan</label>
                        <select data-testid={`sale-item-picker-${idx}`} required value={it.picker_id} onChange={(e) => onPickerChange(idx, e.target.value)} className={inputCls}>
                          <option value="">— pilih produk / bahan —</option>
                          {activeProducts.length > 0 && (
                            <optgroup label="Produk (Multi-Bahan / BOM)">
                              {activeProducts.map((p) => (
                                <option key={`prod-${p.id}`} value={`prod:${p.id}`}>
                                  {p.name}{p.code ? ` [${p.code}]` : ""} — {p.pricing_mode === "per_area" ? "per m²" : "per pcs"}
                                </option>
                              ))}
                            </optgroup>
                          )}
                          <optgroup label="Bahan Langsung">
                            {activeMats.map((m) => (
                              <option key={`mat-${m.id}`} value={`mat:${m.id}`}>{m.name} (stok: {formatNum(m.current_stock)} {m.unit})</option>
                            ))}
                          </optgroup>
                        </select>
                      </div>
                      <div className="col-span-4">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Nama Produk (untuk struk)</label>
                        <input data-testid={`sale-item-name-${idx}`} value={it.product_name} onChange={(e) => updItem(idx, "product_name", e.target.value)} placeholder={isProduct ? r.product?.name : "Banner, Spanduk…"} className={inputCls} />
                      </div>
                      <div className="col-span-1 pt-6">
                        {items.length > 1 && (
                          <button type="button" onClick={() => removeItem(idx)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus"><X className="w-3.5 h-3.5" /></button>
                        )}
                      </div>
                    </div>
                    {/* Size selector untuk produk kaos/jersey */}
                    {isProduct && r.product?.has_sizes && (r.product.sizes || []).length > 0 && (
                      <div className="bg-white border border-[#002FA7]/30 p-2.5">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-[#002FA7] block mb-1.5">Pilih Ukuran</label>
                        <div className="flex flex-wrap gap-1.5">
                          {(r.product.sizes || []).map((s) => {
                            const active = it.size === s;
                            const isTierB = !["S", "M", "L", "XL"].includes(s);
                            return (
                              <button
                                key={s}
                                type="button"
                                data-testid={`sale-item-size-${idx}-${s}`}
                                onClick={() => onSizeChange(idx, s)}
                                className={`rounded-none px-3 py-1.5 text-xs font-bold uppercase tracking-wider border transition-colors ${
                                  active
                                    ? isTierB ? "bg-[#E81123] text-white border-[#E81123]" : "bg-[#002FA7] text-white border-[#002FA7]"
                                    : "bg-white text-zinc-600 border-zinc-300 hover:border-zinc-500"
                                }`}
                              >
                                {s}
                              </button>
                            );
                          })}
                        </div>
                        {it.size && (
                          <div className="text-[10px] font-mono text-zinc-500 mt-1.5">
                            Tier: <b className={sizeTier(it.size) === "B" ? "text-[#E81123]" : "text-[#002FA7]"}>{sizeTier(it.size) === "B" ? "XXL+" : "S-XL"}</b> · Harga otomatis: <b className="text-zinc-900">{formatIDR(it.unit_price)}</b>
                          </div>
                        )}
                      </div>
                    )}
                    <div className="grid grid-cols-12 gap-2">
                      {showLW && (
                        <>
                          <div className="col-span-2">
                            <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Panjang (m)</label>
                            <input data-testid={`sale-item-length-${idx}`} type="number" step="0.01" min="0" required value={it.length_m} onChange={(e) => updItem(idx, "length_m", e.target.value)} className={inputCls + " font-mono"} />
                          </div>
                          <div className="col-span-2">
                            <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Lebar (m)</label>
                            <input data-testid={`sale-item-width-${idx}`} type="number" step="0.01" min="0" required value={it.width_m} onChange={(e) => updItem(idx, "width_m", e.target.value)} className={inputCls + " font-mono"} />
                          </div>
                        </>
                      )}
                      {showLonly && (
                        <div className="col-span-4">
                          <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Panjang (m)</label>
                          <input data-testid={`sale-item-length-${idx}`} type="number" step="0.01" min="0" required value={it.length_m} onChange={(e) => updItem(idx, "length_m", e.target.value)} className={inputCls + " font-mono"} />
                        </div>
                      )}
                      <div className={showLW || showLonly ? "col-span-2" : "col-span-4"}>
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Qty (pcs)</label>
                        <input data-testid={`sale-item-qty-${idx}`} type="number" min="1" required value={it.quantity} onChange={(e) => updItem(idx, "quantity", e.target.value)} className={inputCls + " font-mono"} />
                      </div>
                      <div className="col-span-3">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">{pricingLabel}</label>
                        <input data-testid={`sale-item-price-${idx}`} type="number" step="0.01" min="0" required value={it.unit_price} onChange={(e) => updItem(idx, "unit_price", e.target.value)} className={inputCls + " font-mono"} />
                      </div>
                      <div className="col-span-3">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Subtotal</label>
                        <div data-testid={`sale-item-subtotal-${idx}`} className={`font-mono text-sm font-bold px-3 py-2 border ${r.stock_ok ? "border-zinc-200 bg-white" : "border-[#E81123] bg-[#E81123]/5 text-[#E81123]"}`}>
                          {formatIDR(r.subtotal)}
                        </div>
                      </div>
                    </div>
                    {/* Bahan consumption breakdown */}
                    {it.picker_id && r.consumptions.length > 0 && (
                      <div data-testid={`sale-item-bom-${idx}`} className="text-[10px] text-zinc-600 font-mono border-t border-zinc-200 pt-2 mt-1">
                        <div className="font-bold uppercase tracking-widest text-zinc-500 mb-1 flex items-center justify-between">
                          <span>{isProduct ? `BOM (${r.consumptions.length} bahan)` : "Konsumsi Bahan"}:</span>
                          {r.subtotal > 0 && r.cost > 0 && (
                            <span data-testid={`sale-item-margin-${idx}`} className={`px-1.5 py-0.5 ${r.margin >= 0 ? "bg-[#008A00]/10 text-[#008A00]" : "bg-[#E81123]/10 text-[#E81123]"}`}>
                              Modal {formatIDR(r.cost)} · Margin {formatIDR(r.margin)} ({r.margin_pct.toFixed(1)}%)
                            </span>
                          )}
                        </div>
                        <div className="space-y-0.5">
                          {r.consumptions.map((c, ci) => (
                            <div key={ci} className="flex items-center justify-between">
                              <span>· <b>{c.name}</b> ({c.formula}) → {formatNum(c.consumption)} {c.unit}</span>
                              <span className={c.ok ? "text-[#008A00]" : "text-[#E81123] font-bold"}>
                                {c.ok ? `✓ (stok: ${formatNum(c.stock)})` : `✗ Kurang! stok: ${formatNum(c.stock)}`}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Payment */}
          <div className="border-t border-zinc-200 pt-4 grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-3">
              <Field label="Diskon (Rp)">
                <input data-testid="sale-discount" type="number" step="0.01" min="0" value={discount} onChange={(e) => setDiscount(e.target.value)} className={inputCls + " font-mono"} />
              </Field>
              <Field label="Metode Pembayaran">
                <select
                  data-testid="sale-payment-method"
                  value={paymentMethod}
                  onChange={(e) => setPaymentMethod(e.target.value)}
                  className={inputCls + " font-bold"}
                >
                  <option value="cash">💵 Cash (Uang Tunai)</option>
                  <option value="transfer">🏦 Transfer Bank</option>
                  <option value="shopee_plaza">🛒 Shopee Plaza</option>
                  <option value="shopee_kastem">🛒 Shopee Kastem</option>
                </select>
              </Field>
              {paymentMethod === "transfer" && (
                <div className="border border-[#002FA7]/30 bg-[#002FA7]/5 p-3 space-y-3">
                  <Field label="Bank Tujuan">
                    <div className="flex gap-2">
                      {["BCA", "Mandiri"].map((b) => (
                        <button
                          key={b}
                          type="button"
                          data-testid={`sale-bank-${b}`}
                          onClick={() => setPaymentBank(b)}
                          className={`flex-1 rounded-none px-4 py-2 text-sm font-bold uppercase tracking-wider border transition-colors ${
                            paymentBank === b
                              ? "bg-[#002FA7] text-white border-[#002FA7]"
                              : "bg-white text-zinc-700 border-zinc-300 hover:border-zinc-500"
                          }`}
                        >{b}</button>
                      ))}
                    </div>
                  </Field>
                  <Field label="Keterangan Transfer">
                    <input
                      data-testid="sale-payment-notes"
                      value={paymentNotes}
                      onChange={(e) => setPaymentNotes(e.target.value)}
                      placeholder="cth: An/n Budi, ref 20260717001"
                      className={inputCls}
                    />
                  </Field>
                </div>
              )}
              <Field label={paymentMethod === "cash" ? "Tunai Diterima (Rp)" : "Nominal Diterima (Rp)"}>
                <input data-testid="sale-cash-paid" type="number" step="0.01" min="0" required value={cashPaid} onChange={(e) => setCashPaid(e.target.value)} className={inputCls + " font-mono font-bold text-lg"} placeholder="0" />
              </Field>
              <Field label="Catatan (Opsional)">
                <input data-testid="sale-notes" value={notes} onChange={(e) => setNotes(e.target.value)} className={inputCls} />
              </Field>
            </div>
            <div className="bg-zinc-900 text-white p-5 space-y-2 font-mono">
              <Row label="Subtotal" value={formatIDR(subtotal)} />
              <Row label="Diskon" value={`- ${formatIDR(discount)}`} />
              <div className="border-t border-white/30 pt-2 mt-2">
                <Row label="TOTAL" value={formatIDR(total)} bold big />
              </div>
              {/* Estimator Order — margin/keuntungan */}
              {total_cost > 0 && (
                <div className="border-t border-white/20 mt-3 pt-2 space-y-1" data-testid="sale-estimator">
                  <div className="text-[9px] uppercase tracking-widest text-white/50 font-bold mb-1">Estimator Order (Modal & Keuntungan)</div>
                  <Row label="Modal Bahan" value={formatIDR(total_cost)} muted />
                  <Row
                    label="Margin Kotor"
                    value={`${formatIDR(gross_margin)} (${gross_margin_pct.toFixed(1)}%)`}
                    positive={gross_margin >= 0}
                    negative={gross_margin < 0}
                  />
                  {Number(discount) > 0 && (
                    <Row
                      label="Margin Bersih"
                      value={`${formatIDR(net_margin)} (${net_margin_pct.toFixed(1)}%)`}
                      positive={net_margin >= 0}
                      negative={net_margin < 0}
                    />
                  )}
                </div>
              )}
              <div className="border-t border-white/30 pt-2 mt-2">
                <Row label="Bayar" value={formatIDR(cashPaid)} />
              </div>
              <div className={`border-t border-white/30 pt-2 mt-2 ${change > 0 ? "text-[#4ade80]" : ""}`}>
                <Row label="KEMBALI" value={formatIDR(change)} bold big />
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
            <button type="button" onClick={onClose} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
            <button data-testid="save-sale-button" type="submit" disabled={saving || !canSubmit} className="rounded-none bg-[#002FA7] text-white px-8 py-3 text-sm font-bold uppercase tracking-wider hover:bg-[#002FA7]/90 disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-2">
              <Printer className="w-4 h-4" /> {saving ? "Menyimpan…" : (isEdit ? "Simpan Perubahan" : "Bayar & Cetak Struk")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Row({ label, value, bold, big, positive, negative, muted }) {
  const color = negative ? "text-[#ff9d9d]" : positive ? "text-[#4ade80]" : muted ? "text-white/60" : "";
  return (
    <div className="flex justify-between items-baseline">
      <span className={`${bold ? "font-bold" : ""} ${big ? "text-sm uppercase tracking-wider" : "text-xs"} ${color}`}>{label}</span>
      <span className={`${bold ? "font-bold" : ""} ${big ? "text-xl" : "text-sm"} ${color}`}>{value}</span>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 mb-1">{label}</div>
      {children}
      {hint && <div className="text-[10px] text-zinc-500 mt-1">{hint}</div>}
    </label>
  );
}

/* Helper: Payment method label + color */
export function formatPaymentMethod(sale) {
  const m = (sale.payment_method || "cash").toLowerCase();
  if (m === "cash" || m === "tunai") return { label: "Cash", short: "Cash", color: "bg-[#008A00]/10 text-[#008A00] border-[#008A00]/30" };
  if (m === "transfer") {
    const bank = sale.payment_bank || "Bank";
    return { label: `Transfer ${bank}`, short: `TF ${bank}`, color: "bg-[#002FA7]/10 text-[#002FA7] border-[#002FA7]/30" };
  }
  if (m === "shopee_plaza") return { label: "Shopee Plaza", short: "Shopee P", color: "bg-[#EE4D2D]/10 text-[#EE4D2D] border-[#EE4D2D]/30" };
  if (m === "shopee_kastem") return { label: "Shopee Kastem", short: "Shopee K", color: "bg-[#EE4D2D]/10 text-[#EE4D2D] border-[#EE4D2D]/30" };
  return { label: m, short: m, color: "bg-zinc-100 text-zinc-700 border-zinc-300" };
}

function PaymentBadge({ sale }) {
  const p = formatPaymentMethod(sale);
  return (
    <div className="flex flex-col gap-0.5">
      <span className={`inline-block rounded-none px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border w-fit ${p.color}`}>{p.short}</span>
      {sale.payment_notes && <div className="text-[10px] font-mono text-zinc-500 truncate max-w-[120px]" title={sale.payment_notes}>{sale.payment_notes}</div>}
    </div>
  );
}

