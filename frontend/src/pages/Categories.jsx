import { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "../lib/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Search, Package, ShoppingBag, Factory, Users as UsersIcon, RefreshCw, Sparkles } from "lucide-react";

const TYPE_META = {
  material: { label: "Bahan", icon: Package, color: "#002FA7", hint: "Kategori bahan baku produksi (Flexy, Sticker, Tinta, dll)" },
  product: { label: "Produk", icon: ShoppingBag, color: "#008A00", hint: "Kategori produk jadi (Konveksi, Cetak, Merchandise, dll)" },
  supplier: { label: "Supplier", icon: Factory, color: "#F7630C", hint: "Kategori supplier (Distributor, Lokal, Impor, dll)" },
  customer: { label: "Pelanggan", icon: UsersIcon, color: "#8B44F7", hint: "Segmentasi pelanggan (Ritel, Corporate, Reseller, dll)" },
};

const inputCls = "rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none";

export default function Categories() {
  const [tab, setTab] = useState("material");
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [openForm, setOpenForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", description: "", color: "", active: true });
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [c, s] = await Promise.all([
        api.get("/categories"),
        api.get("/categories/stats"),
      ]);
      setItems(c.data);
      setStats(s.data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat data");
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => items.filter((c) => {
    if (c.type !== tab) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return c.name.toLowerCase().includes(q) || (c.description || "").toLowerCase().includes(q);
  }), [items, tab, search]);

  const openCreate = () => { setEditing(null); setForm({ name: "", description: "", color: "", active: true }); setOpenForm(true); };
  const openEdit = (c) => { setEditing(c); setForm({ name: c.name, description: c.description || "", color: c.color || "", active: c.active !== false }); setOpenForm(true); };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) { toast.error("Nama kategori wajib"); return; }
    setSaving(true);
    try {
      const payload = { ...form, type: tab, name: form.name.trim() };
      if (editing) await api.put(`/categories/${editing.id}`, payload);
      else await api.post("/categories", payload);
      toast.success(editing ? "Kategori diperbarui" : "Kategori ditambahkan");
      setOpenForm(false);
      await load();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal");
    } finally { setSaving(false); }
  };

  const remove = async (c) => {
    if (!window.confirm(`Hapus kategori "${c.name}"?`)) return;
    try { await api.delete(`/categories/${c.id}`); toast.success("Dihapus"); await load(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  const backfill = async () => {
    if (!window.confirm("Backfill akan scan Master Bahan/Produk/Supplier/Pelanggan lalu tambahkan kategori yang belum ada ke Master Kategori. Lanjutkan?")) return;
    try {
      const { data } = await api.post("/categories/backfill");
      toast.success(`${data.added} kategori berhasil di-import dari data existing (total sekarang ${data.total})`);
      await load();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal");
    }
  };

  const meta = TYPE_META[tab];

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Master Data</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Master Kategori</h1>
          <p className="text-sm text-zinc-500 mt-1">Kelola kategori untuk Bahan, Produk, Supplier, dan Pelanggan dari satu tempat.</p>
        </div>
        <div className="flex items-center gap-2">
          <button data-testid="cat-backfill-button" onClick={backfill} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-4 py-2.5 text-sm hover:bg-zinc-50 inline-flex items-center gap-2" title="Import kategori dari data existing">
            <Sparkles className="w-3.5 h-3.5" /> Import Otomatis
          </button>
          <button data-testid="cat-reload-button" onClick={load} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-3 py-2.5 text-sm hover:bg-zinc-50" title="Refresh"><RefreshCw className="w-3.5 h-3.5" /></button>
          <button data-testid="cat-add-button" onClick={openCreate} className="rounded-none text-white px-5 py-2.5 text-sm font-semibold hover:opacity-90 inline-flex items-center gap-2" style={{ backgroundColor: meta.color }}>
            <Plus className="w-4 h-4" /> Tambah {meta.label}
          </button>
        </div>
      </div>

      {/* Type Cards */}
      <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
        {Object.entries(TYPE_META).map(([t, m]) => {
          const Icon = m.icon;
          const s = stats[t] || {};
          const active = tab === t;
          return (
            <button
              key={t}
              data-testid={`cat-type-${t}`}
              onClick={() => setTab(t)}
              className={`bg-white p-4 lg:p-5 text-left transition ${active ? "ring-2 ring-inset" : "hover:bg-zinc-50"}`}
              style={active ? { "--tw-ring-color": m.color } : {}}
            >
              <div className="flex items-center justify-between">
                <div className="text-[10px] uppercase tracking-widest font-bold" style={{ color: m.color }}>{m.label}</div>
                <Icon className="w-4 h-4" style={{ color: m.color }} />
              </div>
              <div className="font-mono text-2xl font-bold text-zinc-900 mt-2">{s.active || 0}</div>
              <div className="text-[10px] text-zinc-500 font-mono mt-0.5">dari {s.total || 0} total</div>
            </button>
          );
        })}
      </div>

      {/* Search */}
      <div className="mt-6 flex items-center justify-between gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            data-testid="cat-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={`Cari kategori ${meta.label.toLowerCase()}…`}
            className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
          />
        </div>
        <div className="text-xs text-zinc-500 font-mono">{filtered.length} kategori · {meta.hint}</div>
      </div>

      {/* Table */}
      <div className="mt-4 border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Kategori</th>
              <th className="px-4 py-3">Deskripsi</th>
              <th className="px-4 py-3">Warna</th>
              <th className="px-4 py-3">Sumber</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={6} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">
                Belum ada kategori {meta.label}. Klik &ldquo;+ Tambah&rdquo; atau &ldquo;Import Otomatis&rdquo; untuk scan dari data existing.
              </td></tr>
            )}
            {filtered.map((c) => (
              <tr key={c.id} data-testid="cat-row" className="border-b border-zinc-100 hover:bg-zinc-50/70">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    {c.color && <span className="inline-block w-3 h-3 border border-zinc-300" style={{ backgroundColor: c.color }} />}
                    <span className="font-semibold text-zinc-900">{c.name}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-xs text-zinc-600">{c.description || "—"}</td>
                <td className="px-4 py-3">
                  {c.color ? <span className="font-mono text-[10px] text-zinc-500">{c.color}</span> : <span className="text-zinc-300">—</span>}
                </td>
                <td className="px-4 py-3">
                  {c.auto_created ? (
                    <span className="text-[10px] font-bold uppercase tracking-widest text-amber-700 bg-amber-100 px-1.5 py-0.5">AUTO-IMPORT</span>
                  ) : (
                    <span className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">MANUAL</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <span className={`text-[10px] font-bold uppercase tracking-widest ${c.active !== false ? "text-[#008A00]" : "text-zinc-400"}`}>
                    {c.active !== false ? "Aktif" : "Nonaktif"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex justify-end gap-1">
                    <button data-testid="cat-edit-button" onClick={() => openEdit(c)} className="p-1.5 hover:bg-zinc-100 text-zinc-700"><Pencil className="w-3.5 h-3.5" /></button>
                    <button data-testid="cat-delete-button" onClick={() => remove(c)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]"><Trash2 className="w-3.5 h-3.5" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {openForm && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white border border-zinc-300 w-full max-w-md">
            <div className="flex items-center justify-between p-5 border-b border-zinc-200">
              <div>
                <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{editing ? "Edit" : "Baru"} — Kategori {meta.label}</div>
                <div className="font-heading text-xl font-bold text-zinc-900">{editing ? "Edit Kategori" : "Tambah Kategori"}</div>
              </div>
              <button onClick={() => setOpenForm(false)} data-testid="close-cat-modal" className="p-1.5 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-4">
              <label className="block">
                <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 mb-1">Nama Kategori</div>
                <input required data-testid="cat-form-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputCls} placeholder={
                  tab === "material" ? "Flexy, Sticker, Tinta…" :
                  tab === "product" ? "Konveksi, Cetak, Merchandise…" :
                  tab === "supplier" ? "Distributor, Lokal, Impor…" :
                  "Ritel, Corporate, Reseller…"
                } />
              </label>
              <label className="block">
                <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 mb-1">Deskripsi (opsional)</div>
                <input data-testid="cat-form-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className={inputCls} />
              </label>
              <label className="block">
                <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 mb-1">Warna (opsional)</div>
                <div className="flex items-center gap-2">
                  <input type="color" data-testid="cat-form-color" value={form.color || "#002FA7"} onChange={(e) => setForm({ ...form, color: e.target.value })} className="w-10 h-10 border border-zinc-300 rounded-none cursor-pointer" />
                  <input value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })} placeholder="#002FA7" className={inputCls + " font-mono"} />
                  {form.color && <button type="button" onClick={() => setForm({ ...form, color: "" })} className="text-xs text-zinc-500 hover:text-[#E81123]">clear</button>}
                </div>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
                <span>Aktif (muncul di dropdown form)</span>
              </label>
              <div className="flex justify-end gap-2 pt-3 border-t border-zinc-200">
                <button type="button" onClick={() => setOpenForm(false)} className="rounded-none bg-white border border-zinc-300 px-5 py-2.5 text-sm hover:bg-zinc-50">Batal</button>
                <button data-testid="cat-save-button" type="submit" disabled={saving} className="rounded-none text-white px-6 py-2.5 text-sm font-bold uppercase tracking-wider disabled:opacity-40" style={{ backgroundColor: meta.color }}>
                  {saving ? "Menyimpan…" : "Simpan"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
