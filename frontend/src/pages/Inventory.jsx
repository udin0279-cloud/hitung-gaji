import { useEffect, useMemo, useState } from "react";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Search, Package, TrendingDown, AlertTriangle, Boxes, ClipboardList, Scale, Download, MessageCircle, Send } from "lucide-react";

const CATEGORIES = [
  { value: "flexy", label: "Flexy" },
  { value: "sticker", label: "Sticker" },
  { value: "tinta", label: "Tinta" },
  { value: "lainnya", label: "Lainnya" },
];
const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.value, c.label]));

const UNITS = [
  { value: "meter", label: "Meter" },
  { value: "roll", label: "Roll" },
  { value: "liter", label: "Liter" },
  { value: "pcs", label: "Pcs" },
];

const WASTE_REASONS = [
  { value: "rusak", label: "Rusak" },
  { value: "rijek", label: "Rijek Produksi" },
  { value: "kadaluarsa", label: "Kadaluarsa" },
  { value: "lainnya", label: "Lainnya" },
];
const REASON_LABEL = Object.fromEntries(WASTE_REASONS.map((r) => [r.value, r.label]));

const inputCls = "rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none";

function formatNum(n) {
  if (n === null || n === undefined || n === "") return "0";
  return Number(n).toLocaleString("id-ID", { maximumFractionDigits: 4 });
}

export default function Inventory() {
  const [tab, setTab] = useState("materials");
  const [stats, setStats] = useState(null);
  const [materials, setMaterials] = useState([]);
  const [stockIn, setStockIn] = useState([]);
  const [waste, setWaste] = useState([]);
  const [orders, setOrders] = useState([]);
  const [adjusts, setAdjusts] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [m, s, si, w, o, adj, c] = await Promise.all([
        api.get("/inventory/materials"),
        api.get("/inventory/stats"),
        api.get("/inventory/stock-in"),
        api.get("/inventory/waste"),
        api.get("/inventory/orders"),
        api.get("/inventory/stock-adjust"),
        api.get("/inventory/customers"),
      ]);
      setMaterials(m.data);
      setStats(s.data);
      setStockIn(si.data);
      setWaste(w.data);
      setOrders(o.data);
      setAdjusts(adj.data);
      setCustomers(c.data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Modul</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Inventory Bahan Printing</h1>
          <p className="text-sm text-zinc-500 mt-1">Kelola stok Flexy, Sticker, Tinta &amp; bahan produksi lainnya.</p>
        </div>
      </div>

      {/* Stats */}
      <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
        <StatCard label="Total Bahan Aktif" value={stats?.total_materials ?? 0} icon={Package} isCount testId="stat-materials" />
        <StatCard label="Nilai Stok Total" value={stats?.total_stock_value || 0} icon={Boxes} testId="stat-stock-value" />
        <StatCard label="Waste Bulan Ini" value={stats?.total_waste_this_month || 0} icon={TrendingDown} testId="stat-waste-month" negative />
        <StatCard label="Stok Menipis" value={stats?.low_stock_count ?? 0} icon={AlertTriangle} isCount testId="stat-low-stock" warn />
      </div>

      {/* Low stock alert */}
      {stats?.low_stock?.length > 0 && (
        <div data-testid="low-stock-alert" className="mt-4 border-l-4 border-amber-500 bg-amber-50 p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-4 h-4 text-amber-700 mt-0.5 shrink-0" />
            <div className="flex-1">
              <div className="text-sm font-bold text-amber-900">Stok Menipis</div>
              <div className="text-xs text-amber-800 mt-1 font-mono">
                {stats.low_stock.map((l) => `${l.name} (${formatNum(l.current_stock)} ${l.unit})`).join(", ")}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="mt-8 border-b border-zinc-200">
        <div className="flex flex-wrap gap-1">
          <TabButton active={tab === "materials"} onClick={() => setTab("materials")} testId="tab-materials">Master Bahan</TabButton>
          <TabButton active={tab === "stock-in"} onClick={() => setTab("stock-in")} testId="tab-stock-in">Barang Masuk</TabButton>
          <TabButton active={tab === "waste"} onClick={() => setTab("waste")} testId="tab-waste">Sisa / Rijek</TabButton>
          <TabButton active={tab === "orders"} onClick={() => setTab("orders")} testId="tab-orders">Order Produksi</TabButton>
          <TabButton active={tab === "customers"} onClick={() => setTab("customers")} testId="tab-customers">Customer</TabButton>
          <TabButton active={tab === "opname"} onClick={() => setTab("opname")} testId="tab-opname">Opname</TabButton>
        </div>
      </div>

      <div className="mt-6">
        {loading ? (
          <div className="py-12 text-center text-zinc-400 font-mono text-xs">Memuat…</div>
        ) : tab === "materials" ? (
          <MaterialsTab materials={materials} reload={loadAll} />
        ) : tab === "stock-in" ? (
          <StockInTab materials={materials} stockIn={stockIn} reload={loadAll} />
        ) : tab === "waste" ? (
          <WasteTab materials={materials} waste={waste} reload={loadAll} />
        ) : tab === "orders" ? (
          <OrdersTab materials={materials} orders={orders} customers={customers} reload={loadAll} />
        ) : tab === "customers" ? (
          <CustomersTab customers={customers} reload={loadAll} />
        ) : (
          <OpnameTab materials={materials} adjusts={adjusts} reload={loadAll} />
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, isCount, testId, negative, warn }) {
  const valueCls = negative ? "text-[#E81123]" : warn ? "text-amber-700" : "text-zinc-900";
  return (
    <div className="bg-white p-4 lg:p-5">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
        <Icon className="w-3.5 h-3.5 text-zinc-400" />
      </div>
      <div data-testid={testId} className={`font-mono text-xl lg:text-2xl tracking-tight font-semibold mt-2 ${valueCls}`}>
        {isCount ? value : formatIDR(value)}
      </div>
    </div>
  );
}

function TabButton({ active, onClick, children, testId }) {
  return (
    <button
      data-testid={testId}
      onClick={onClick}
      className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
        active
          ? "border-[#002FA7] text-zinc-900"
          : "border-transparent text-zinc-500 hover:text-zinc-900"
      }`}
    >
      {children}
    </button>
  );
}

/* ---------------- MATERIALS TAB ---------------- */
const EMPTY_MAT = {
  name: "", category: "flexy", unit: "meter",
  current_stock: 0, purchase_price: 0, selling_price: 0, min_stock: 0,
  supplier_default: "", notes: "", active: true,
};

function MaterialsTab({ materials, reload }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_MAT);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [catFilter, setCatFilter] = useState("all");

  const filtered = useMemo(() => materials.filter((m) => {
    if (catFilter !== "all" && m.category !== catFilter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return m.name.toLowerCase().includes(q) || (m.supplier_default || "").toLowerCase().includes(q);
  }), [materials, catFilter, search]);

  const openCreate = () => { setEditing(null); setForm(EMPTY_MAT); setOpen(true); };
  const openEdit = (m) => { setEditing(m); setForm({ ...EMPTY_MAT, ...m }); setOpen(true); };
  const close = () => { setOpen(false); setEditing(null); };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        ...form,
        current_stock: Number(form.current_stock) || 0,
        purchase_price: Number(form.purchase_price) || 0,
        selling_price: Number(form.selling_price) || 0,
        min_stock: Number(form.min_stock) || 0,
      };
      if (editing) {
        await api.put(`/inventory/materials/${editing.id}`, payload);
        toast.success("Bahan diperbarui");
      } else {
        await api.post("/inventory/materials", payload);
        toast.success("Bahan ditambahkan");
      }
      close();
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (m) => {
    if (!window.confirm(`Hapus bahan "${m.name}"?`)) return;
    try {
      const { data } = await api.delete(`/inventory/materials/${m.id}`);
      toast.success(data.soft_deleted ? "Bahan dinonaktifkan (karena ada history)" : "Bahan dihapus");
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menghapus");
    }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input data-testid="material-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama bahan / supplier…" className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none" />
          </div>
          <select data-testid="material-cat-filter" value={catFilter} onChange={(e) => setCatFilter(e.target.value)} className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm">
            <option value="all">Semua Kategori</option>
            {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </div>
        <button data-testid="add-material-button" onClick={openCreate} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> Tambah Bahan
        </button>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Nama Bahan</th>
              <th className="px-4 py-3">Kategori</th>
              <th className="px-4 py-3 text-right">Stok</th>
              <th className="px-4 py-3">Satuan</th>
              <th className="px-4 py-3 text-right">Harga Beli</th>
              <th className="px-4 py-3 text-right">Nilai Stok</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada bahan. Klik &ldquo;Tambah Bahan&rdquo;.</td></tr>
            )}
            {filtered.map((m) => {
              const stockVal = Number(m.current_stock || 0) * Number(m.purchase_price || 0);
              const low = m.min_stock > 0 && Number(m.current_stock || 0) <= Number(m.min_stock || 0);
              return (
                <tr key={m.id} data-testid="material-row" className="border-b border-zinc-100 hover:bg-zinc-50/80">
                  <td className="px-4 py-3">
                    <div className="font-medium text-zinc-900">{m.name}</div>
                    {m.supplier_default && <div className="text-xs text-zinc-500">Supplier: {m.supplier_default}</div>}
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border border-zinc-300 text-zinc-700 bg-zinc-50">{CATEGORY_LABEL[m.category] || m.category}</span>
                  </td>
                  <td className={`px-4 py-3 font-mono text-right ${low ? "text-amber-700 font-bold" : "text-zinc-900"}`}>{formatNum(m.current_stock)}</td>
                  <td className="px-4 py-3 text-zinc-700 text-xs uppercase">{m.unit}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(m.purchase_price)}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-900 font-semibold">{formatIDR(stockVal)}</td>
                  <td className="px-4 py-3">
                    {!m.active
                      ? <span className="inline-flex px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border border-zinc-400 text-zinc-500 bg-zinc-50">Non-aktif</span>
                      : low
                      ? <span className="inline-flex px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border border-amber-500 text-amber-700 bg-amber-50">Menipis</span>
                      : <span className="inline-flex px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border border-[#008A00] text-[#008A00] bg-[#008A00]/5">Aman</span>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <button data-testid="edit-material-button" onClick={() => openEdit(m)} className="p-1.5 hover:bg-zinc-100 text-zinc-700" title="Edit"><Pencil className="w-3.5 h-3.5" /></button>
                      <button data-testid="delete-material-button" onClick={() => remove(m)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {open && <MaterialForm editing={editing} form={form} setForm={setForm} onClose={close} onSubmit={submit} saving={saving} />}
    </div>
  );
}

function MaterialForm({ editing, form, setForm, onClose, onSubmit, saving }) {
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const setBool = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.checked }));
  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
      <div className="bg-white border border-zinc-300 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200 sticky top-0 bg-white">
          <div>
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{editing ? "Edit" : "Baru"}</div>
            <div className="font-heading text-xl font-bold text-zinc-900">{editing ? "Edit Bahan" : "Tambah Bahan"}</div>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-zinc-100" data-testid="close-material-modal"><X className="w-4 h-4" /></button>
        </div>
        <form onSubmit={onSubmit} className="p-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Nama Bahan">
              <input data-testid="mat-name" required value={form.name} onChange={set("name")} className={inputCls} placeholder="Contoh: Flexy Frontlite 3m" />
            </Field>
            <Field label="Kategori">
              <select data-testid="mat-category" value={form.category} onChange={set("category")} className={inputCls}>
                {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </Field>
            <Field label="Satuan">
              <select data-testid="mat-unit" value={form.unit} onChange={set("unit")} className={inputCls}>
                {UNITS.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
              </select>
            </Field>
            <Field label="Harga Beli / Satuan (Rp)">
              <input data-testid="mat-price" type="number" step="0.01" min="0" value={form.purchase_price} onChange={set("purchase_price")} className={inputCls + " font-mono"} />
            </Field>
            <Field label="Harga Jual / m² (Rp)" hint="Untuk POS Penjualan (bila 0, isi manual saat transaksi)">
              <input data-testid="mat-selling-price" type="number" step="0.01" min="0" value={form.selling_price} onChange={set("selling_price")} className={inputCls + " font-mono"} />
            </Field>
            <Field label="Stok Awal" hint="Mendukung angka desimal (mis. 2.5 roll)">
              <input data-testid="mat-stock" type="number" step="0.0001" min="0" value={form.current_stock} onChange={set("current_stock")} className={inputCls + " font-mono"} />
            </Field>
            <Field label="Stok Minimum (Warning)" hint="0 = tidak ada peringatan">
              <input data-testid="mat-min-stock" type="number" step="0.0001" min="0" value={form.min_stock} onChange={set("min_stock")} className={inputCls + " font-mono"} />
            </Field>
            <Field label="Supplier Default (Opsional)">
              <input data-testid="mat-supplier" value={form.supplier_default || ""} onChange={set("supplier_default")} className={inputCls} />
            </Field>
            <Field label="Catatan (Opsional)">
              <input data-testid="mat-notes" value={form.notes || ""} onChange={set("notes")} className={inputCls} />
            </Field>
          </div>
          <label className="inline-flex items-center gap-2 text-sm text-zinc-700">
            <input type="checkbox" checked={form.active} onChange={setBool("active")} className="w-4 h-4" />
            Bahan Aktif
          </label>
          <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
            <button type="button" onClick={onClose} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
            <button data-testid="save-material-button" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 disabled:opacity-60">{saving ? "Menyimpan…" : "Simpan"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ---------------- STOCK IN TAB ---------------- */
const EMPTY_SI = {
  material_id: "", quantity: 0, unit_price: 0,
  supplier: "", invoice_no: "", date: new Date().toISOString().slice(0, 10), notes: "",
};

function StockInTab({ materials, stockIn, reload }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_SI);
  const [saving, setSaving] = useState(false);

  const openCreate = () => {
    const first = materials.find((m) => m.active !== false);
    setForm({ ...EMPTY_SI, material_id: first?.id || "", unit_price: first?.purchase_price || 0 });
    setOpen(true);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.material_id) { toast.error("Pilih bahan"); return; }
    setSaving(true);
    try {
      await api.post("/inventory/stock-in", {
        ...form,
        quantity: Number(form.quantity) || 0,
        unit_price: Number(form.unit_price) || 0,
      });
      toast.success("Barang masuk dicatat, stok diperbarui");
      setOpen(false);
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (row) => {
    if (!window.confirm(`Hapus data barang masuk ini? Stok akan dikembalikan.`)) return;
    try {
      await api.delete(`/inventory/stock-in/${row.id}`);
      toast.success("Barang masuk dihapus, stok dikembalikan");
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menghapus");
    }
  };

  const onMaterialChange = (e) => {
    const id = e.target.value;
    const mat = materials.find((m) => m.id === id);
    setForm((f) => ({ ...f, material_id: id, unit_price: mat?.purchase_price || f.unit_price }));
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-zinc-500">{stockIn.length} transaksi barang masuk tercatat.</div>
        <button data-testid="add-stock-in-button" onClick={openCreate} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> Catat Barang Masuk
        </button>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Tanggal</th>
              <th className="px-4 py-3">Bahan</th>
              <th className="px-4 py-3">Supplier</th>
              <th className="px-4 py-3">Invoice</th>
              <th className="px-4 py-3 text-right">Qty</th>
              <th className="px-4 py-3 text-right">Harga/Unit</th>
              <th className="px-4 py-3 text-right">Total</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {stockIn.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada barang masuk.</td></tr>
            )}
            {stockIn.map((s) => (
              <tr key={s.id} data-testid="stock-in-row" className="border-b border-zinc-100 hover:bg-zinc-50/80">
                <td className="px-4 py-3 font-mono text-xs text-zinc-700">{s.date}</td>
                <td className="px-4 py-3">
                  <div className="font-medium text-zinc-900">{s.material_name}</div>
                  <div className="text-xs text-zinc-500">{CATEGORY_LABEL[s.material_category] || s.material_category}</div>
                </td>
                <td className="px-4 py-3 text-zinc-700">{s.supplier || "—"}</td>
                <td className="px-4 py-3 text-zinc-500 font-mono text-xs">{s.invoice_no || "—"}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900">{formatNum(s.quantity)} <span className="text-[10px] text-zinc-500 uppercase ml-0.5">{s.material_unit}</span></td>
                <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(s.unit_price)}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900 font-semibold">{formatIDR(s.total_price)}</td>
                <td className="px-4 py-3 text-right">
                  <button data-testid="delete-stock-in-button" onClick={() => remove(s)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus"><Trash2 className="w-3.5 h-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
          <div className="bg-white border border-zinc-300 w-full max-w-2xl">
            <div className="flex items-center justify-between p-5 border-b border-zinc-200">
              <div className="font-heading text-xl font-bold text-zinc-900">Catat Barang Masuk</div>
              <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-zinc-100" data-testid="close-stock-in-modal"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field label="Bahan">
                  <select data-testid="si-material" required value={form.material_id} onChange={onMaterialChange} className={inputCls}>
                    <option value="">— pilih bahan —</option>
                    {materials.filter((m) => m.active !== false).map((m) => (
                      <option key={m.id} value={m.id}>{m.name} ({m.unit})</option>
                    ))}
                  </select>
                </Field>
                <Field label="Tanggal">
                  <input data-testid="si-date" type="date" required value={form.date} onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))} className={inputCls} />
                </Field>
                <Field label="Kuantitas" hint="Desimal didukung (mis. 2.5)">
                  <input data-testid="si-quantity" type="number" step="0.0001" min="0" required value={form.quantity} onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))} className={inputCls + " font-mono"} />
                </Field>
                <Field label="Harga Beli / Unit (Rp)">
                  <input data-testid="si-unit-price" type="number" step="0.01" min="0" required value={form.unit_price} onChange={(e) => setForm((f) => ({ ...f, unit_price: e.target.value }))} className={inputCls + " font-mono"} />
                </Field>
                <Field label="Supplier">
                  <input data-testid="si-supplier" value={form.supplier || ""} onChange={(e) => setForm((f) => ({ ...f, supplier: e.target.value }))} className={inputCls} />
                </Field>
                <Field label="No. Invoice (Opsional)">
                  <input data-testid="si-invoice" value={form.invoice_no || ""} onChange={(e) => setForm((f) => ({ ...f, invoice_no: e.target.value }))} className={inputCls} />
                </Field>
              </div>
              <Field label="Catatan (Opsional)">
                <input data-testid="si-notes" value={form.notes || ""} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} className={inputCls} />
              </Field>
              {form.quantity > 0 && form.unit_price > 0 && (
                <div className="p-3 bg-zinc-50 border border-zinc-200 text-sm">
                  <span className="text-zinc-600">Total: </span>
                  <span className="font-mono font-bold text-zinc-900">{formatIDR(Number(form.quantity) * Number(form.unit_price))}</span>
                </div>
              )}
              <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
                <button type="button" onClick={() => setOpen(false)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
                <button data-testid="save-stock-in-button" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 disabled:opacity-60">{saving ? "Menyimpan…" : "Simpan"}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- WASTE TAB ---------------- */
const EMPTY_W = {
  material_id: "", quantity: 0, reason: "rusak",
  date: new Date().toISOString().slice(0, 10), reported_by: "", notes: "",
};

function WasteTab({ materials, waste, reload }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_W);
  const [saving, setSaving] = useState(false);
  const [reportPeriod, setReportPeriod] = useState(new Date().toISOString().slice(0, 7));

  const totalLoss = useMemo(() => waste.reduce((s, w) => s + Number(w.estimated_loss || 0), 0), [waste]);

  const openCreate = () => {
    const first = materials.find((m) => m.active !== false);
    setForm({ ...EMPTY_W, material_id: first?.id || "" });
    setOpen(true);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.material_id) { toast.error("Pilih bahan"); return; }
    setSaving(true);
    try {
      await api.post("/inventory/waste", {
        ...form,
        quantity: Number(form.quantity) || 0,
      });
      toast.success("Waste dicatat, stok dikurangi");
      setOpen(false);
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (row) => {
    if (!window.confirm(`Hapus data waste ini? Stok akan dikembalikan.`)) return;
    try {
      await api.delete(`/inventory/waste/${row.id}`);
      toast.success("Waste dihapus, stok dikembalikan");
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menghapus");
    }
  };

  // Preview estimated loss saat mengisi form
  const previewLoss = useMemo(() => {
    const mat = materials.find((m) => m.id === form.material_id);
    if (!mat) return 0;
    return Number(form.quantity) * Number(mat.purchase_price || 0);
  }, [materials, form]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="text-sm text-zinc-500">
          {waste.length} laporan waste · <span className="text-[#E81123] font-semibold font-mono">Total kerugian: {formatIDR(totalLoss)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            data-testid="waste-report-period"
            type="month"
            value={reportPeriod}
            onChange={(e) => setReportPeriod(e.target.value)}
            className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono"
          />
          <a
            data-testid="download-waste-excel"
            href={`${API}/inventory/waste/report/${reportPeriod}/excel`}
            target="_blank"
            rel="noreferrer"
            className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-3 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-50 inline-flex items-center gap-1.5"
          >
            <Download className="w-3.5 h-3.5" /> Excel
          </a>
          <a
            data-testid="download-waste-pdf"
            href={`${API}/inventory/waste/report/${reportPeriod}/pdf`}
            target="_blank"
            rel="noreferrer"
            className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-3 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-50 inline-flex items-center gap-1.5"
          >
            <Download className="w-3.5 h-3.5" /> PDF
          </a>
          <button data-testid="add-waste-button" onClick={openCreate} className="rounded-none bg-[#E81123] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#E81123]/90 inline-flex items-center gap-2">
            <Plus className="w-4 h-4" /> Lapor Waste
          </button>
        </div>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Tanggal</th>
              <th className="px-4 py-3">Bahan</th>
              <th className="px-4 py-3">Alasan</th>
              <th className="px-4 py-3 text-right">Qty</th>
              <th className="px-4 py-3 text-right">Kerugian (Rp)</th>
              <th className="px-4 py-3">Pelapor</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {waste.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada laporan waste.</td></tr>
            )}
            {waste.map((w) => (
              <tr key={w.id} data-testid="waste-row" className="border-b border-zinc-100 hover:bg-zinc-50/80">
                <td className="px-4 py-3 font-mono text-xs text-zinc-700">{w.date}</td>
                <td className="px-4 py-3">
                  <div className="font-medium text-zinc-900">{w.material_name}</div>
                  <div className="text-xs text-zinc-500">{CATEGORY_LABEL[w.material_category] || w.material_category}</div>
                </td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border border-[#E81123] text-[#E81123] bg-[#E81123]/5">{REASON_LABEL[w.reason] || w.reason}</span>
                </td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900">{formatNum(w.quantity)} <span className="text-[10px] text-zinc-500 uppercase ml-0.5">{w.material_unit}</span></td>
                <td className="px-4 py-3 font-mono text-right text-[#E81123] font-bold">{formatIDR(w.estimated_loss)}</td>
                <td className="px-4 py-3 text-zinc-700 text-xs">{w.reported_by || "—"}</td>
                <td className="px-4 py-3 text-right">
                  <button data-testid="delete-waste-button" onClick={() => remove(w)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus"><Trash2 className="w-3.5 h-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
          <div className="bg-white border border-zinc-300 w-full max-w-2xl">
            <div className="flex items-center justify-between p-5 border-b border-zinc-200">
              <div className="font-heading text-xl font-bold text-zinc-900">Lapor Waste / Rijek</div>
              <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-zinc-100" data-testid="close-waste-modal"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field label="Bahan">
                  <select data-testid="w-material" required value={form.material_id} onChange={(e) => setForm((f) => ({ ...f, material_id: e.target.value }))} className={inputCls}>
                    <option value="">— pilih bahan —</option>
                    {materials.filter((m) => m.active !== false).map((m) => (
                      <option key={m.id} value={m.id}>{m.name} (stok: {formatNum(m.current_stock)} {m.unit})</option>
                    ))}
                  </select>
                </Field>
                <Field label="Tanggal">
                  <input data-testid="w-date" type="date" required value={form.date} onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))} className={inputCls} />
                </Field>
                <Field label="Kuantitas Rusak/Rijek">
                  <input data-testid="w-quantity" type="number" step="0.0001" min="0.0001" required value={form.quantity} onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))} className={inputCls + " font-mono"} />
                </Field>
                <Field label="Alasan">
                  <select data-testid="w-reason" value={form.reason} onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} className={inputCls}>
                    {WASTE_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                  </select>
                </Field>
                <Field label="Pelapor (Opsional)">
                  <input data-testid="w-reporter" value={form.reported_by || ""} onChange={(e) => setForm((f) => ({ ...f, reported_by: e.target.value }))} className={inputCls} placeholder="Nama operator/karyawan" />
                </Field>
                <Field label="Catatan (Opsional)">
                  <input data-testid="w-notes" value={form.notes || ""} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} className={inputCls} />
                </Field>
              </div>
              {previewLoss > 0 && (
                <div className="p-3 bg-[#E81123]/5 border border-[#E81123]/30 text-sm">
                  <span className="text-zinc-600">Estimasi kerugian: </span>
                  <span className="font-mono font-bold text-[#E81123]">{formatIDR(previewLoss)}</span>
                  <span className="text-xs text-zinc-500 ml-2">(qty × harga beli terakhir)</span>
                </div>
              )}
              <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
                <button type="button" onClick={() => setOpen(false)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
                <button data-testid="save-waste-button" type="submit" disabled={saving} className="rounded-none bg-[#E81123] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#E81123]/90 disabled:opacity-60">{saving ? "Menyimpan…" : "Simpan"}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}


/* ---------------- ORDERS (JOB PRODUKSI) TAB ---------------- */
const EMPTY_ORDER = {
  order_no: "", customer: "", product_name: "", quantity: 1, unit_price: 0,
  start_date: new Date().toISOString().slice(0, 10), due_date: "",
  items: [], notes: "",
};

const ORDER_STATUS_LABEL = { aktif: "Aktif", selesai: "Selesai", batal: "Batal" };
const ORDER_STATUS_CLS = {
  aktif: "border-[#002FA7] text-[#002FA7] bg-[#002FA7]/5",
  selesai: "border-[#008A00] text-[#008A00] bg-[#008A00]/5",
  batal: "border-zinc-400 text-zinc-500 bg-zinc-50",
};

function OrdersTab({ materials, orders, customers, reload }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_ORDER);
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState("all");

  const activeMaterials = materials.filter((m) => m.active !== false);

  const filtered = orders.filter((o) => filter === "all" || o.status === filter);

  const openCreate = () => {
    setForm({ ...EMPTY_ORDER, items: [{ material_id: activeMaterials[0]?.id || "", quantity: 0 }] });
    setOpen(true);
  };

  const addItem = () => {
    setForm((f) => ({ ...f, items: [...(f.items || []), { material_id: activeMaterials[0]?.id || "", quantity: 0 }] }));
  };
  const removeItem = (idx) => {
    setForm((f) => ({ ...f, items: f.items.filter((_, i) => i !== idx) }));
  };
  const updItem = (idx, key, val) => {
    setForm((f) => ({ ...f, items: f.items.map((it, i) => i === idx ? { ...it, [key]: val } : it) }));
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.customer || !form.product_name) { toast.error("Customer & produk wajib diisi"); return; }
    const items = (form.items || []).filter((i) => i.material_id && Number(i.quantity) > 0).map((i) => ({ material_id: i.material_id, quantity: Number(i.quantity) }));
    if (items.length === 0) { toast.error("Tambahkan minimal 1 bahan"); return; }
    setSaving(true);
    try {
      await api.post("/inventory/orders", {
        ...form,
        quantity: Number(form.quantity) || 1,
        unit_price: Number(form.unit_price) || 0,
        due_date: form.due_date || null,
        items,
      });
      toast.success("Order dibuat, stok bahan dikurangi otomatis");
      setOpen(false);
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  const complete = async (o) => {
    if (!window.confirm(`Tandai order ${o.order_no} sebagai SELESAI?`)) return;
    try { await api.put(`/inventory/orders/${o.id}/complete`); toast.success("Order diselesaikan"); await reload(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };
  const cancel = async (o) => {
    if (!window.confirm(`Batalkan order ${o.order_no}? Stok bahan akan dikembalikan.`)) return;
    try { await api.put(`/inventory/orders/${o.id}/cancel`); toast.success("Order dibatalkan, stok dikembalikan"); await reload(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };
  const remove = async (o) => {
    if (!window.confirm(`Hapus order ${o.order_no}? Stok akan dikembalikan jika masih aktif/selesai.`)) return;
    try { await api.delete(`/inventory/orders/${o.id}`); toast.success("Order dihapus"); await reload(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  // Preview estimasi biaya bahan
  const previewCost = useMemo(() => {
    return (form.items || []).reduce((s, it) => {
      const mat = materials.find((m) => m.id === it.material_id);
      return s + Number(it.quantity || 0) * Number(mat?.purchase_price || 0);
    }, 0);
  }, [form.items, materials]);
  const previewRevenue = Number(form.quantity || 0) * Number(form.unit_price || 0);
  const previewMargin = previewRevenue - previewCost;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <select data-testid="order-filter" value={filter} onChange={(e) => setFilter(e.target.value)} className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm">
            <option value="all">Semua Status</option>
            <option value="aktif">Aktif</option>
            <option value="selesai">Selesai</option>
            <option value="batal">Batal</option>
          </select>
          <div className="text-sm text-zinc-500">{filtered.length} order</div>
        </div>
        <button data-testid="add-order-button" onClick={openCreate} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> Buat Order
        </button>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">No. Order</th>
              <th className="px-4 py-3">Customer / Produk</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Biaya Bahan</th>
              <th className="px-4 py-3 text-right">Total Harga</th>
              <th className="px-4 py-3 text-right">Margin</th>
              <th className="px-4 py-3">Bahan</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada order.</td></tr>
            )}
            {filtered.map((o) => (
              <tr key={o.id} data-testid="order-row" className="border-b border-zinc-100 hover:bg-zinc-50/80 align-top">
                <td className="px-4 py-3 font-mono text-xs text-zinc-700">
                  {o.order_no}
                  <div className="text-[10px] text-zinc-500 mt-0.5">{o.start_date}</div>
                </td>
                <td className="px-4 py-3">
                  <div className="font-medium text-zinc-900">{o.customer}</div>
                  <div className="text-xs text-zinc-500">{o.product_name} × {o.quantity}</div>
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border ${ORDER_STATUS_CLS[o.status] || ""}`}>{ORDER_STATUS_LABEL[o.status] || o.status}</span>
                </td>
                <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(o.total_material_cost)}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900 font-semibold">{formatIDR(o.total_price)}</td>
                <td className={`px-4 py-3 font-mono text-right font-bold ${(o.gross_margin || 0) >= 0 ? "text-[#008A00]" : "text-[#E81123]"}`}>{formatIDR(o.gross_margin)}</td>
                <td className="px-4 py-3 text-xs text-zinc-600">
                  {(o.items || []).map((it, i) => (
                    <div key={i} className="font-mono">{it.material_name}: {formatNum(it.quantity)} {it.material_unit}</div>
                  ))}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    {o.status === "aktif" && (
                      <button data-testid="complete-order-button" onClick={() => complete(o)} className="px-2 py-1 border border-[#008A00] text-[#008A00] hover:bg-[#008A00]/10 text-[10px] font-bold uppercase" title="Selesai">Selesai</button>
                    )}
                    {(o.status === "aktif" || o.status === "selesai") && (
                      <button data-testid="cancel-order-button" onClick={() => cancel(o)} className="px-2 py-1 border border-amber-500 text-amber-700 hover:bg-amber-50 text-[10px] font-bold uppercase" title="Batal">Batal</button>
                    )}
                    <button data-testid="delete-order-button" onClick={() => remove(o)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus"><Trash2 className="w-3.5 h-3.5" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
          <div className="bg-white border border-zinc-300 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-5 border-b border-zinc-200 sticky top-0 bg-white">
              <div>
                <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Baru</div>
                <div className="font-heading text-xl font-bold text-zinc-900">Buat Order Produksi</div>
              </div>
              <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-zinc-100" data-testid="close-order-modal"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field label="Customer">
                  <input data-testid="order-customer" required list="customers-list" value={form.customer} onChange={(e) => setForm((f) => ({ ...f, customer: e.target.value }))} className={inputCls} placeholder="Ketik atau pilih customer" />
                  <datalist id="customers-list">
                    {(customers || []).map((c) => <option key={c.id} value={c.name} />)}
                  </datalist>
                </Field>
                <Field label="No. Order (Opsional)" hint="Auto-generate jika kosong">
                  <input data-testid="order-no" value={form.order_no || ""} onChange={(e) => setForm((f) => ({ ...f, order_no: e.target.value }))} className={inputCls + " font-mono"} />
                </Field>
                <Field label="Nama Produk">
                  <input data-testid="order-product" required value={form.product_name} onChange={(e) => setForm((f) => ({ ...f, product_name: e.target.value }))} className={inputCls} placeholder="Banner 3x2m" />
                </Field>
                <Field label="Qty Produk">
                  <input data-testid="order-qty" type="number" min="1" required value={form.quantity} onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))} className={inputCls + " font-mono"} />
                </Field>
                <Field label="Harga Jual / Produk (Rp)">
                  <input data-testid="order-unit-price" type="number" step="0.01" min="0" value={form.unit_price} onChange={(e) => setForm((f) => ({ ...f, unit_price: e.target.value }))} className={inputCls + " font-mono"} />
                </Field>
                <Field label="Tanggal Mulai">
                  <input data-testid="order-start" type="date" required value={form.start_date} onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))} className={inputCls} />
                </Field>
                <Field label="Deadline (Opsional)">
                  <input data-testid="order-due" type="date" value={form.due_date || ""} onChange={(e) => setForm((f) => ({ ...f, due_date: e.target.value }))} className={inputCls} />
                </Field>
              </div>

              <div className="border-t border-zinc-200 pt-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-[11px] uppercase tracking-widest font-bold text-zinc-700">Bill of Material (Bahan Terpakai)</div>
                  <button type="button" data-testid="order-add-item" onClick={addItem} className="text-xs text-[#002FA7] hover:underline font-semibold">+ Tambah Bahan</button>
                </div>
                <div className="space-y-2">
                  {(form.items || []).map((it, idx) => {
                    const mat = materials.find((m) => m.id === it.material_id);
                    return (
                      <div key={idx} className="grid grid-cols-12 gap-2 items-start">
                        <div className="col-span-6">
                          <select data-testid={`order-item-mat-${idx}`} required value={it.material_id} onChange={(e) => updItem(idx, "material_id", e.target.value)} className={inputCls}>
                            <option value="">— pilih bahan —</option>
                            {activeMaterials.map((m) => (
                              <option key={m.id} value={m.id}>{m.name} (stok: {formatNum(m.current_stock)} {m.unit})</option>
                            ))}
                          </select>
                        </div>
                        <div className="col-span-3">
                          <input data-testid={`order-item-qty-${idx}`} type="number" step="0.0001" min="0.0001" required placeholder="Qty" value={it.quantity} onChange={(e) => updItem(idx, "quantity", e.target.value)} className={inputCls + " font-mono"} />
                        </div>
                        <div className="col-span-2 text-xs text-zinc-500 pt-2 font-mono">
                          {mat ? formatIDR(Number(it.quantity || 0) * Number(mat.purchase_price || 0)) : "—"}
                        </div>
                        <div className="col-span-1">
                          <button type="button" onClick={() => removeItem(idx)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus"><X className="w-3.5 h-3.5" /></button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <Field label="Catatan (Opsional)">
                <input data-testid="order-notes" value={form.notes || ""} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} className={inputCls} />
              </Field>

              <div className="p-3 bg-zinc-50 border border-zinc-200 space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-zinc-600">Total Biaya Bahan:</span><span className="font-mono font-semibold">{formatIDR(previewCost)}</span></div>
                <div className="flex justify-between"><span className="text-zinc-600">Total Harga Jual:</span><span className="font-mono font-semibold">{formatIDR(previewRevenue)}</span></div>
                <div className={`flex justify-between pt-1 border-t border-zinc-300 font-bold ${previewMargin >= 0 ? "text-[#008A00]" : "text-[#E81123]"}`}>
                  <span>Estimasi Margin:</span><span className="font-mono">{formatIDR(previewMargin)}</span>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
                <button type="button" onClick={() => setOpen(false)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
                <button data-testid="save-order-button" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 disabled:opacity-60">{saving ? "Menyimpan…" : "Simpan & Kurangi Stok"}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- OPNAME / STOCK ADJUSTMENT TAB ---------------- */
const EMPTY_ADJ = {
  material_id: "", new_stock: 0, reason: "opname",
  date: new Date().toISOString().slice(0, 10), notes: "",
};

const ADJ_REASONS = [
  { value: "opname", label: "Opname Rutin" },
  { value: "koreksi", label: "Koreksi Selisih" },
  { value: "lainnya", label: "Lainnya" },
];

function OpnameTab({ materials, adjusts, reload }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_ADJ);
  const [saving, setSaving] = useState(false);

  const openCreate = () => {
    const first = materials.find((m) => m.active !== false);
    setForm({ ...EMPTY_ADJ, material_id: first?.id || "", new_stock: first?.current_stock || 0 });
    setOpen(true);
  };

  const onMatChange = (e) => {
    const id = e.target.value;
    const mat = materials.find((m) => m.id === id);
    setForm((f) => ({ ...f, material_id: id, new_stock: mat?.current_stock ?? 0 }));
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.material_id) { toast.error("Pilih bahan"); return; }
    setSaving(true);
    try {
      await api.post("/inventory/stock-adjust", { ...form, new_stock: Number(form.new_stock) });
      toast.success("Stok berhasil disesuaikan");
      setOpen(false);
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (a) => {
    if (!window.confirm("Hapus data opname ini? Stok akan dikembalikan ke nilai sebelum opname.")) return;
    try { await api.delete(`/inventory/stock-adjust/${a.id}`); toast.success("Opname dihapus, stok dikembalikan"); await reload(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  const selMat = materials.find((m) => m.id === form.material_id);
  const delta = selMat ? (Number(form.new_stock) - Number(selMat.current_stock || 0)) : 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-zinc-500">{adjusts.length} record opname / adjustment.</div>
        <button data-testid="add-adjust-button" onClick={openCreate} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> Opname / Adjustment
        </button>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Tanggal</th>
              <th className="px-4 py-3">Bahan</th>
              <th className="px-4 py-3">Alasan</th>
              <th className="px-4 py-3 text-right">Stok Sebelum</th>
              <th className="px-4 py-3 text-right">Stok Sesudah</th>
              <th className="px-4 py-3 text-right">Delta</th>
              <th className="px-4 py-3">Catatan</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {adjusts.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada record opname.</td></tr>
            )}
            {adjusts.map((a) => (
              <tr key={a.id} data-testid="adjust-row" className="border-b border-zinc-100 hover:bg-zinc-50/80">
                <td className="px-4 py-3 font-mono text-xs text-zinc-700">{a.date}</td>
                <td className="px-4 py-3">
                  <div className="font-medium text-zinc-900">{a.material_name}</div>
                  <div className="text-xs text-zinc-500">{a.material_unit}</div>
                </td>
                <td className="px-4 py-3 text-xs text-zinc-700 uppercase">{a.reason}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatNum(a.stock_before)}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900 font-semibold">{formatNum(a.stock_after)}</td>
                <td className={`px-4 py-3 font-mono text-right font-bold ${a.delta > 0 ? "text-[#008A00]" : a.delta < 0 ? "text-[#E81123]" : "text-zinc-500"}`}>
                  {a.delta > 0 ? "+" : ""}{formatNum(a.delta)}
                </td>
                <td className="px-4 py-3 text-xs text-zinc-600">{a.notes || "—"}</td>
                <td className="px-4 py-3 text-right">
                  <button data-testid="delete-adjust-button" onClick={() => remove(a)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus"><Trash2 className="w-3.5 h-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
          <div className="bg-white border border-zinc-300 w-full max-w-2xl">
            <div className="flex items-center justify-between p-5 border-b border-zinc-200">
              <div className="font-heading text-xl font-bold text-zinc-900">Opname / Adjustment Stok</div>
              <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-zinc-100" data-testid="close-adjust-modal"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field label="Bahan">
                  <select data-testid="adj-material" required value={form.material_id} onChange={onMatChange} className={inputCls}>
                    <option value="">— pilih bahan —</option>
                    {materials.filter((m) => m.active !== false).map((m) => (
                      <option key={m.id} value={m.id}>{m.name} (sistem: {formatNum(m.current_stock)} {m.unit})</option>
                    ))}
                  </select>
                </Field>
                <Field label="Tanggal">
                  <input data-testid="adj-date" type="date" required value={form.date} onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))} className={inputCls} />
                </Field>
                <Field label="Stok Aktual Hasil Opname" hint="Nilai yang benar (fisik)">
                  <input data-testid="adj-new-stock" type="number" step="0.0001" min="0" required value={form.new_stock} onChange={(e) => setForm((f) => ({ ...f, new_stock: e.target.value }))} className={inputCls + " font-mono"} />
                </Field>
                <Field label="Alasan">
                  <select data-testid="adj-reason" value={form.reason} onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} className={inputCls}>
                    {ADJ_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                  </select>
                </Field>
              </div>
              <Field label="Catatan (Opsional)">
                <input data-testid="adj-notes" value={form.notes || ""} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} className={inputCls} />
              </Field>
              {selMat && (
                <div className="p-3 bg-zinc-50 border border-zinc-200 text-sm space-y-1">
                  <div className="flex justify-between"><span className="text-zinc-600">Stok Sistem:</span><span className="font-mono">{formatNum(selMat.current_stock)} {selMat.unit}</span></div>
                  <div className="flex justify-between"><span className="text-zinc-600">Stok Aktual:</span><span className="font-mono">{formatNum(form.new_stock)} {selMat.unit}</span></div>
                  <div className={`flex justify-between pt-1 border-t border-zinc-300 font-bold ${delta > 0 ? "text-[#008A00]" : delta < 0 ? "text-[#E81123]" : "text-zinc-500"}`}>
                    <span>Selisih:</span><span className="font-mono">{delta > 0 ? "+" : ""}{formatNum(delta)} {selMat.unit}</span>
                  </div>
                </div>
              )}
              <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
                <button type="button" onClick={() => setOpen(false)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
                <button data-testid="save-adjust-button" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 disabled:opacity-60">{saving ? "Menyimpan…" : "Simpan"}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}


/* ---------------- CUSTOMERS TAB ---------------- */
const EMPTY_CUST = { name: "", phone: "", email: "", address: "", npwp: "", contact_person: "", notes: "", active: true };

function CustomersTab({ customers, reload }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_CUST);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [openBroadcast, setOpenBroadcast] = useState(false);

  const filtered = customers.filter((c) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return c.name.toLowerCase().includes(q) || (c.phone || "").toLowerCase().includes(q) || (c.email || "").toLowerCase().includes(q);
  });

  const withPhone = customers.filter((c) => (c.phone || "").trim() && c.active !== false).length;

  const openCreate = () => { setEditing(null); setForm(EMPTY_CUST); setOpen(true); };
  const openEdit = (c) => { setEditing(c); setForm({ ...EMPTY_CUST, ...c }); setOpen(true); };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editing) {
        await api.put(`/inventory/customers/${editing.id}`, form);
        toast.success("Customer diperbarui");
      } else {
        await api.post("/inventory/customers", form);
        toast.success("Customer ditambahkan");
      }
      setOpen(false);
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (c) => {
    if (!window.confirm(`Hapus customer "${c.name}"?`)) return;
    try { await api.delete(`/inventory/customers/${c.id}`); toast.success("Customer dihapus"); await reload(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input data-testid="cust-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama / telepon / email…" className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none" />
        </div>
        <div className="flex items-center gap-2">
          <button
            data-testid="broadcast-wa-button"
            onClick={() => setOpenBroadcast(true)}
            disabled={withPhone === 0}
            title={withPhone === 0 ? "Belum ada pelanggan dengan nomor WA" : `Kirim pesan ke ${withPhone} pelanggan`}
            className="rounded-none bg-[#008A00] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#006D00] inline-flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <MessageCircle className="w-4 h-4" /> Broadcast WA
            <span className="font-mono text-[10px] bg-white/20 px-1.5 py-0.5">{withPhone}</span>
          </button>
          <button data-testid="add-customer-button" onClick={openCreate} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2">
            <Plus className="w-4 h-4" /> Tambah Customer
          </button>
        </div>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Nama Customer</th>
              <th className="px-4 py-3">Kontak</th>
              <th className="px-4 py-3">NPWP</th>
              <th className="px-4 py-3 text-right">Order</th>
              <th className="px-4 py-3 text-right">Total Revenue</th>
              <th className="px-4 py-3 text-right">Total Margin</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada customer. Klik &ldquo;Tambah Customer&rdquo;.</td></tr>
            )}
            {filtered.map((c) => {
              const margin = Number(c.total_revenue || 0) - Number(c.total_material_cost || 0);
              return (
                <tr key={c.id} data-testid="customer-row" className="border-b border-zinc-100 hover:bg-zinc-50/80">
                  <td className="px-4 py-3">
                    <div className="font-medium text-zinc-900">{c.name}</div>
                    {c.contact_person && <div className="text-xs text-zinc-500">CP: {c.contact_person}</div>}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {c.phone && <div className="font-mono text-zinc-700">{c.phone}</div>}
                    {c.email && <div className="text-zinc-500">{c.email}</div>}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-zinc-500">{c.npwp || "—"}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-900">{c.order_count || 0}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-900 font-semibold">{formatIDR(c.total_revenue || 0)}</td>
                  <td className={`px-4 py-3 font-mono text-right font-bold ${margin >= 0 ? "text-[#008A00]" : "text-[#E81123]"}`}>{formatIDR(margin)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <button data-testid="edit-customer-button" onClick={() => openEdit(c)} className="p-1.5 hover:bg-zinc-100 text-zinc-700"><Pencil className="w-3.5 h-3.5" /></button>
                      <button data-testid="delete-customer-button" onClick={() => remove(c)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
          <div className="bg-white border border-zinc-300 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-5 border-b border-zinc-200 sticky top-0 bg-white">
              <div>
                <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{editing ? "Edit" : "Baru"}</div>
                <div className="font-heading text-xl font-bold text-zinc-900">{editing ? "Edit Customer" : "Tambah Customer"}</div>
              </div>
              <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-zinc-100" data-testid="close-customer-modal"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field label="Nama Customer">
                  <input data-testid="cust-name" required value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className={inputCls} placeholder="PT Contoh Advertising" />
                </Field>
                <Field label="Contact Person">
                  <input data-testid="cust-cp" value={form.contact_person || ""} onChange={(e) => setForm((f) => ({ ...f, contact_person: e.target.value }))} className={inputCls} placeholder="Bapak Budi" />
                </Field>
                <Field label="Telepon">
                  <input data-testid="cust-phone" value={form.phone || ""} onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))} className={inputCls + " font-mono"} placeholder="0812xxxx" />
                </Field>
                <Field label="Email">
                  <input data-testid="cust-email" type="email" value={form.email || ""} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} className={inputCls} />
                </Field>
                <Field label="NPWP (Opsional)">
                  <input data-testid="cust-npwp" value={form.npwp || ""} onChange={(e) => setForm((f) => ({ ...f, npwp: e.target.value }))} className={inputCls + " font-mono"} />
                </Field>
                <Field label="Alamat">
                  <input data-testid="cust-address" value={form.address || ""} onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))} className={inputCls} />
                </Field>
              </div>
              <Field label="Catatan (Opsional)">
                <input data-testid="cust-notes" value={form.notes || ""} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} className={inputCls} />
              </Field>
              <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
                <button type="button" onClick={() => setOpen(false)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
                <button data-testid="save-customer-button" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 disabled:opacity-60">{saving ? "Menyimpan…" : "Simpan"}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {openBroadcast && (
        <BroadcastWAModal customers={customers} onClose={() => setOpenBroadcast(false)} />
      )}
    </div>
  );
}

/* ---------------- Broadcast WhatsApp Modal ---------------- */
function BroadcastWAModal({ customers, onClose }) {
  const eligible = useMemo(
    () => customers.filter((c) => (c.phone || "").trim() && c.active !== false),
    [customers]
  );
  const [selectedIds, setSelectedIds] = useState(() => eligible.map((c) => c.id));
  const [message, setMessage] = useState(
    "Halo {name}, terima kasih sudah menjadi pelanggan setia kami. 🙏\n\nKami info: minggu ini promo cetak banner Flexy hanya Rp 20.000/m² (min 5m²). Info lebih lanjut hubungi kami ya.\n\n— Payroll Indonesia"
  );
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [search, setSearch] = useState("");

  const filtered = eligible.filter((c) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return c.name.toLowerCase().includes(q) || (c.phone || "").includes(q);
  });

  const toggleAll = (checked) => {
    setSelectedIds(checked ? filtered.map((c) => c.id) : []);
  };
  const toggleOne = (id, checked) => {
    setSelectedIds((arr) => (checked ? [...arr, id] : arr.filter((x) => x !== id)));
  };

  const send = async () => {
    if (!message.trim()) { toast.error("Pesan wajib diisi"); return; }
    if (selectedIds.length === 0) { toast.error("Pilih minimal 1 pelanggan"); return; }
    if (!window.confirm(`Kirim pesan WhatsApp ke ${selectedIds.length} pelanggan?`)) return;
    setSending(true);
    setResult(null);
    try {
      const { data } = await api.post("/inventory/customers/broadcast-whatsapp", {
        message: message.trim(),
        customer_ids: selectedIds,
      });
      setResult(data);
      const sentTotal = data.sent + data.mocked;
      if (data.mocked > 0) {
        toast.info(`${data.mocked} pesan MOCKED (Fonnte token belum diset). ${data.sent} sent, ${data.failed} failed.`);
      } else if (data.failed > 0) {
        toast.warning(`${sentTotal} terkirim, ${data.failed} gagal`);
      } else {
        toast.success(`${sentTotal} pesan berhasil dikirim`);
      }
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal broadcast");
    } finally {
      setSending(false);
    }
  };

  const preview = message.replace(/{name}/g, "Pak Budi");
  const allChecked = filtered.length > 0 && filtered.every((c) => selectedIds.includes(c.id));

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
      <div className="bg-white border border-zinc-300 w-full max-w-5xl max-h-[92vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200 sticky top-0 bg-white z-10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-[#008A00] flex items-center justify-center">
              <MessageCircle className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Marketing</div>
              <div className="font-heading text-xl font-bold text-zinc-900">Broadcast WhatsApp</div>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-zinc-100" data-testid="close-broadcast-modal"><X className="w-4 h-4" /></button>
        </div>

        {result ? (
          <div className="p-6 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
              <ResultCard label="Total" value={result.total} testId="broadcast-total" />
              <ResultCard label="Terkirim" value={result.sent} testId="broadcast-sent" positive />
              <ResultCard label="Gagal" value={result.failed} testId="broadcast-failed" danger />
              <ResultCard label="Mocked" value={result.mocked} testId="broadcast-mocked" />
            </div>
            {result.mocked > 0 && (
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 p-3 font-mono">
                ⚠ Token Fonnte belum di-set. Pesan hanya di-simulate (mocked). Set env FONNTE_TOKEN untuk mengaktifkan pengiriman.
              </div>
            )}
            <div className="border border-zinc-200 max-h-64 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="bg-zinc-50 border-b border-zinc-200 sticky top-0">
                  <tr className="text-[10px] uppercase tracking-widest text-zinc-600 font-bold">
                    <th className="px-3 py-2 text-left">Pelanggan</th>
                    <th className="px-3 py-2 text-left">Nomor</th>
                    <th className="px-3 py-2 text-left">Status</th>
                    <th className="px-3 py-2 text-left">Info</th>
                  </tr>
                </thead>
                <tbody>
                  {(result.results || []).map((r, i) => (
                    <tr key={i} data-testid="broadcast-result-row" className="border-b border-zinc-100">
                      <td className="px-3 py-2 font-medium">{r.name}</td>
                      <td className="px-3 py-2 font-mono text-xs text-zinc-600">{r.phone}</td>
                      <td className="px-3 py-2">
                        <span className={`text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 ${
                          r.status === "sent" ? "bg-[#008A00]/10 text-[#008A00]"
                          : r.status === "mocked" ? "bg-amber-100 text-amber-700"
                          : "bg-[#E81123]/10 text-[#E81123]"
                        }`}>{r.status}</span>
                      </td>
                      <td className="px-3 py-2 text-xs text-zinc-500 font-mono">{r.reason || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex justify-end gap-2 pt-2 border-t border-zinc-200">
              <button onClick={() => { setResult(null); }} className="rounded-none bg-white border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Kirim Lagi</button>
              <button onClick={onClose} className="rounded-none bg-[#002FA7] text-white px-6 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90">Tutup</button>
            </div>
          </div>
        ) : (
          <div className="p-5 grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Left: Message */}
            <div className="space-y-3">
              <Field label="Isi Pesan" hint="Gunakan {name} untuk mention nama pelanggan otomatis">
                <textarea
                  data-testid="broadcast-message"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  rows={9}
                  className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none font-mono"
                />
              </Field>
              <div className="text-[10px] text-zinc-500 font-mono flex justify-between">
                <span>{message.length} / 3000 karakter</span>
                <button
                  type="button"
                  onClick={() => setMessage(
                    "Halo {name}, terima kasih sudah menjadi pelanggan setia kami.\n\n[Isi pesan di sini]\n\n— Payroll Indonesia"
                  )}
                  className="text-[#002FA7] hover:underline"
                >Reset Template</button>
              </div>

              <div className="border-t border-zinc-200 pt-3">
                <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 mb-2">Preview Pesan</div>
                <div data-testid="broadcast-preview" className="bg-[#E9FFDC] border border-[#008A00]/30 p-3 text-sm text-zinc-800 whitespace-pre-wrap font-sans max-h-40 overflow-y-auto">
                  {preview}
                </div>
                <div className="text-[10px] text-zinc-500 mt-1">Contoh untuk pelanggan &ldquo;Pak Budi&rdquo;</div>
              </div>
            </div>

            {/* Right: Recipient list */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-700">
                  Penerima ({selectedIds.length} / {eligible.length})
                </div>
                <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={allChecked}
                    onChange={(e) => toggleAll(e.target.checked)}
                    data-testid="broadcast-select-all"
                  />
                  <span>Pilih Semua</span>
                </label>
              </div>
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Cari nama / nomor…"
                  className="rounded-none border border-zinc-300 bg-white pl-9 pr-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
                />
              </div>
              <div className="border border-zinc-200 max-h-80 overflow-y-auto">
                {filtered.length === 0 && (
                  <div className="p-8 text-center text-zinc-400 font-mono text-xs">
                    {eligible.length === 0 ? "Belum ada pelanggan dengan nomor WA aktif." : "Tidak ada hasil."}
                  </div>
                )}
                {filtered.map((c) => {
                  const checked = selectedIds.includes(c.id);
                  return (
                    <label key={c.id} data-testid="broadcast-recipient" className={`flex items-center gap-3 p-2.5 border-b border-zinc-100 cursor-pointer hover:bg-zinc-50 ${checked ? "bg-[#008A00]/5" : ""}`}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => toggleOne(c.id, e.target.checked)}
                      />
                      <div className="flex-1">
                        <div className="text-sm font-medium text-zinc-900">{c.name}</div>
                        <div className="text-xs font-mono text-zinc-500">{c.phone}</div>
                      </div>
                      <span className="text-[9px] font-mono text-zinc-400">{c.order_count || 0} order</span>
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="lg:col-span-2 flex items-center justify-between gap-2 pt-4 border-t border-zinc-200">
              <div className="text-xs text-zinc-500 font-mono">
                Pacing 0.3s/pesan · Fonnte Free Plan compatible
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={onClose} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
                <button
                  type="button"
                  data-testid="broadcast-send-button"
                  onClick={send}
                  disabled={sending || selectedIds.length === 0 || !message.trim()}
                  className="rounded-none bg-[#008A00] text-white px-8 py-3 text-sm font-bold uppercase tracking-wider hover:bg-[#006D00] disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-2"
                >
                  <Send className="w-4 h-4" /> {sending ? `Mengirim ${selectedIds.length}…` : `Kirim ke ${selectedIds.length}`}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ResultCard({ label, value, positive, danger, testId }) {
  return (
    <div className="bg-white p-4">
      <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
      <div data-testid={testId} className={`font-mono text-2xl font-bold mt-1 ${positive ? "text-[#008A00]" : danger ? "text-[#E81123]" : "text-zinc-900"}`}>
        {value}
      </div>
    </div>
  );
}

/* ---------------- Shared field/section ---------------- */
function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 mb-1">{label}</div>
      {children}
      {hint && <div className="text-[10px] text-zinc-500 mt-1">{hint}</div>}
    </label>
  );
}
