import { useEffect, useMemo, useState } from "react";
import { api, formatIDR, formatApiError } from "../lib/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Search, Package, TrendingDown, AlertTriangle, Boxes } from "lucide-react";

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
  const [loading, setLoading] = useState(true);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [m, s, si, w] = await Promise.all([
        api.get("/inventory/materials"),
        api.get("/inventory/stats"),
        api.get("/inventory/stock-in"),
        api.get("/inventory/waste"),
      ]);
      setMaterials(m.data);
      setStats(s.data);
      setStockIn(si.data);
      setWaste(w.data);
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
        </div>
      </div>

      <div className="mt-6">
        {loading ? (
          <div className="py-12 text-center text-zinc-400 font-mono text-xs">Memuat…</div>
        ) : tab === "materials" ? (
          <MaterialsTab materials={materials} reload={loadAll} />
        ) : tab === "stock-in" ? (
          <StockInTab materials={materials} stockIn={stockIn} reload={loadAll} />
        ) : (
          <WasteTab materials={materials} waste={waste} reload={loadAll} />
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
  current_stock: 0, purchase_price: 0, min_stock: 0,
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
        <button data-testid="add-waste-button" onClick={openCreate} className="rounded-none bg-[#E81123] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#E81123]/90 inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> Lapor Waste / Rijek
        </button>
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
