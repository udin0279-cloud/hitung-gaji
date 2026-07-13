import { useEffect, useState } from "react";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import { Plus, Trash2, X, Search, ShoppingBag, Printer, Receipt, DollarSign, TrendingUp } from "lucide-react";

const inputCls = "rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none";

function formatNum(n, digits = 4) {
  if (n === null || n === undefined || n === "") return "0";
  return Number(n).toLocaleString("id-ID", { maximumFractionDigits: digits });
}

export default function Sales() {
  const [sales, setSales] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [openNew, setOpenNew] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [s, m, c, st] = await Promise.all([
        api.get("/sales"),
        api.get("/inventory/materials"),
        api.get("/inventory/customers"),
        api.get("/sales/stats/today"),
      ]);
      setSales(s.data);
      setMaterials(m.data);
      setCustomers(c.data);
      setStats(st.data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  const filtered = sales.filter((s) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (s.sale_no || "").toLowerCase().includes(q)
      || (s.customer_name || "").toLowerCase().includes(q)
      || (s.customer_phone || "").includes(q);
  });

  const openReceipt = (s, auto = false) => {
    const url = `${API}/sales/${s.id}/receipt${auto ? "?auto=1" : ""}`;
    window.open(url, "_blank", "width=380,height=650");
  };

  const remove = async (s) => {
    if (!window.confirm(`Hapus transaksi ${s.sale_no}? Stok akan dikembalikan.`)) return;
    try { await api.delete(`/sales/${s.id}`); toast.success("Transaksi dihapus, stok dikembalikan"); await loadAll(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Modul</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Penjualan / Kasir</h1>
          <p className="text-sm text-zinc-500 mt-1">POS digital printing — hitung otomatis berdasarkan luas (P×L×Qty) &amp; cetak struk thermal 80mm.</p>
        </div>
        <button data-testid="new-sale-button" onClick={() => setOpenNew(true)} className="rounded-none bg-[#002FA7] text-white px-6 py-3 text-sm font-bold uppercase tracking-wider hover:bg-[#002FA7]/90 inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> Transaksi Baru
        </button>
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
          <div className="text-sm text-zinc-500">{filtered.length} transaksi</div>
        </div>

        <div className="border border-zinc-200 bg-white overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                <th className="px-4 py-3">No. Nota</th>
                <th className="px-4 py-3">Pelanggan</th>
                <th className="px-4 py-3">Item</th>
                <th className="px-4 py-3">Kasir</th>
                <th className="px-4 py-3 text-right">Total</th>
                <th className="px-4 py-3 text-right">Kembali</th>
                <th className="px-4 py-3 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={7} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada transaksi. Klik &ldquo;Transaksi Baru&rdquo;.</td></tr>
              )}
              {filtered.map((s) => (
                <tr key={s.id} data-testid="sale-row" className="border-b border-zinc-100 hover:bg-zinc-50/80 align-top">
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
                  <td className="px-4 py-3 font-mono text-right text-zinc-900 font-bold">{formatIDR(s.total)}</td>
                  <td className="px-4 py-3 font-mono text-right text-zinc-500 text-xs">
                    <div>Bayar: {formatIDR(s.cash_paid)}</div>
                    <div className={s.change > 0 ? "text-[#008A00] font-semibold" : ""}>Kembali: {formatIDR(s.change)}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        data-testid="print-receipt-button"
                        onClick={() => openReceipt(s)}
                        className="inline-flex items-center gap-1.5 rounded-none border border-[#002FA7] bg-[#002FA7] text-white px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider hover:bg-[#002080] transition-colors"
                        title="Cetak Nota Thermal 80mm"
                      >
                        <Printer className="w-3.5 h-3.5" /> Cetak Nota
                      </button>
                      <button data-testid="delete-sale-button" onClick={() => remove(s)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123] border border-transparent hover:border-[#E81123]/30" title="Hapus"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {openNew && <NewSaleModal materials={materials} customers={customers} onClose={() => setOpenNew(false)} onSaved={async (created) => { setOpenNew(false); await loadAll(); openReceipt(created, true); }} />}
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
const EMPTY_ITEM = { material_id: "", product_name: "", length_m: 0, width_m: 0, quantity: 1, unit_price: 0 };

function NewSaleModal({ materials, customers, onClose, onSaved }) {
  const activeMats = materials.filter((m) => m.active !== false);
  const activeCustomers = (customers || []).filter((c) => c.active !== false);
  const [customer, setCustomer] = useState({ name: "", phone: "" });
  const [items, setItems] = useState([{ ...EMPTY_ITEM }]);
  const [discount, setDiscount] = useState(0);
  const [cashPaid, setCashPaid] = useState(0);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const addItem = () => setItems((arr) => [...arr, { ...EMPTY_ITEM }]);
  const removeItem = (idx) => setItems((arr) => arr.filter((_, i) => i !== idx));
  const updItem = (idx, key, val) => setItems((arr) => arr.map((it, i) => i === idx ? { ...it, [key]: val } : it));

  // Auto-fill phone jika nama pelanggan match dengan master
  const onCustomerNameChange = (val) => {
    const match = activeCustomers.find((c) => (c.name || "").toLowerCase() === val.trim().toLowerCase());
    setCustomer((c) => ({
      name: val,
      phone: match ? (match.phone || "") : c.phone,
    }));
  };

  const isExistingCustomer = () => {
    const n = customer.name.trim().toLowerCase();
    if (!n || n === "umum") return true; // "Umum" tidak perlu disimpan
    return activeCustomers.some((c) => (c.name || "").toLowerCase() === n);
  };

  const onMaterialPick = (idx, mid) => {
    const mat = materials.find((m) => m.id === mid);
    setItems((arr) => arr.map((it, i) => i === idx ? {
      ...it,
      material_id: mid,
      unit_price: mat?.selling_price > 0 ? mat.selling_price : it.unit_price,
      product_name: it.product_name || (mat?.name || ""),
    } : it));
  };

  // Perhitungan
  const rows = items.map((it) => {
    const mat = materials.find((m) => m.id === it.material_id);
    const area = Number(it.length_m || 0) * Number(it.width_m || 0);
    const area_total = area * Number(it.quantity || 0);
    const subtotal = area_total * Number(it.unit_price || 0);
    const stock_ok = mat ? Number(mat.current_stock || 0) >= area_total : false;
    return { it, mat, area, area_total, subtotal, stock_ok };
  });
  const subtotal = rows.reduce((s, r) => s + r.subtotal, 0);
  const total = Math.max(subtotal - Number(discount || 0), 0);
  const change = Math.max(Number(cashPaid || 0) - total, 0);
  const canSubmit = items.length > 0 && rows.every((r) => r.it.material_id && r.area_total > 0 && r.it.unit_price > 0 && r.stock_ok) && Number(cashPaid || 0) >= total && total > 0;

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
        payment_method: "tunai",
        notes: notes.trim() || null,
        items: items.map((it) => ({
          material_id: it.material_id,
          product_name: it.product_name || (materials.find((m) => m.id === it.material_id)?.name || "-"),
          length_m: Number(it.length_m) || 0,
          width_m: Number(it.width_m) || 0,
          quantity: Number(it.quantity) || 1,
          unit_price: Number(it.unit_price) || 0,
        })),
      };
      const { data } = await api.post("/sales", payload);
      toast.success(`Transaksi ${data.sale_no} berhasil`);
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
            <div className="font-heading text-xl font-bold text-zinc-900">Transaksi Baru</div>
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
              <div className="text-[11px] uppercase tracking-widest font-bold text-zinc-700">Detail Produk / Order</div>
              <button type="button" data-testid="add-sale-item" onClick={addItem} className="text-xs text-[#002FA7] hover:underline font-semibold">+ Tambah Item</button>
            </div>
            <div className="space-y-3">
              {items.map((it, idx) => {
                const r = rows[idx];
                return (
                  <div key={idx} className="border border-zinc-200 p-3 space-y-2 bg-zinc-50/40">
                    <div className="grid grid-cols-12 gap-2">
                      <div className="col-span-6">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Bahan</label>
                        <select data-testid={`sale-item-mat-${idx}`} required value={it.material_id} onChange={(e) => onMaterialPick(idx, e.target.value)} className={inputCls}>
                          <option value="">— pilih bahan —</option>
                          {activeMats.map((m) => (
                            <option key={m.id} value={m.id}>{m.name} (stok: {formatNum(m.current_stock)} {m.unit})</option>
                          ))}
                        </select>
                      </div>
                      <div className="col-span-5">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Nama Produk (untuk struk)</label>
                        <input data-testid={`sale-item-name-${idx}`} value={it.product_name} onChange={(e) => updItem(idx, "product_name", e.target.value)} placeholder="Banner, X-Banner, Spanduk…" className={inputCls} />
                      </div>
                      <div className="col-span-1 pt-6">
                        {items.length > 1 && (
                          <button type="button" onClick={() => removeItem(idx)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus"><X className="w-3.5 h-3.5" /></button>
                        )}
                      </div>
                    </div>
                    <div className="grid grid-cols-12 gap-2">
                      <div className="col-span-2">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Panjang (m)</label>
                        <input data-testid={`sale-item-length-${idx}`} type="number" step="0.01" min="0" required value={it.length_m} onChange={(e) => updItem(idx, "length_m", e.target.value)} className={inputCls + " font-mono"} />
                      </div>
                      <div className="col-span-2">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Lebar (m)</label>
                        <input data-testid={`sale-item-width-${idx}`} type="number" step="0.01" min="0" required value={it.width_m} onChange={(e) => updItem(idx, "width_m", e.target.value)} className={inputCls + " font-mono"} />
                      </div>
                      <div className="col-span-2">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Qty</label>
                        <input data-testid={`sale-item-qty-${idx}`} type="number" min="1" required value={it.quantity} onChange={(e) => updItem(idx, "quantity", e.target.value)} className={inputCls + " font-mono"} />
                      </div>
                      <div className="col-span-3">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Harga / m² (Rp)</label>
                        <input data-testid={`sale-item-price-${idx}`} type="number" step="0.01" min="0" required value={it.unit_price} onChange={(e) => updItem(idx, "unit_price", e.target.value)} className={inputCls + " font-mono"} />
                      </div>
                      <div className="col-span-3">
                        <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1">Subtotal</label>
                        <div data-testid={`sale-item-subtotal-${idx}`} className={`font-mono text-sm font-bold px-3 py-2 border ${r.stock_ok ? "border-zinc-200 bg-white" : "border-[#E81123] bg-[#E81123]/5 text-[#E81123]"}`}>
                          {formatIDR(r.subtotal)}
                        </div>
                      </div>
                    </div>
                    <div className="text-[10px] text-zinc-500 font-mono flex items-center justify-between">
                      <span>Luas total: <b>{formatNum(r.area_total)} m²</b> (= {formatNum(r.area)} × {it.quantity || 0})</span>
                      {r.mat && (
                        <span className={r.stock_ok ? "text-[#008A00]" : "text-[#E81123] font-bold"}>
                          {r.stock_ok ? `Stok cukup (${formatNum(r.mat.current_stock)} ${r.mat.unit})` : `Stok kurang! Tersedia ${formatNum(r.mat.current_stock)} ${r.mat.unit}`}
                        </span>
                      )}
                    </div>
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
              <Field label="Tunai Diterima (Rp)">
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
              <Row label="Bayar" value={formatIDR(cashPaid)} />
              <div className={`border-t border-white/30 pt-2 mt-2 ${change > 0 ? "text-[#4ade80]" : ""}`}>
                <Row label="KEMBALI" value={formatIDR(change)} bold big />
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
            <button type="button" onClick={onClose} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
            <button data-testid="save-sale-button" type="submit" disabled={saving || !canSubmit} className="rounded-none bg-[#002FA7] text-white px-8 py-3 text-sm font-bold uppercase tracking-wider hover:bg-[#002FA7]/90 disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-2">
              <Printer className="w-4 h-4" /> {saving ? "Menyimpan…" : "Bayar & Cetak Struk"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Row({ label, value, bold, big }) {
  return (
    <div className="flex justify-between items-baseline">
      <span className={`${bold ? "font-bold" : ""} ${big ? "text-sm uppercase tracking-wider" : "text-xs"}`}>{label}</span>
      <span className={`${bold ? "font-bold" : ""} ${big ? "text-xl" : "text-sm"}`}>{value}</span>
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
