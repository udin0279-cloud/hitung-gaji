import { useEffect, useState, Fragment } from "react";
import { api, formatIDR, formatApiError } from "../lib/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Search, ShoppingCart, Users as UsersIcon, TrendingUp, TrendingDown, PackageCheck, Wallet, Minus } from "lucide-react";

const PO_STATUS_LABEL = { draft: "Draft", diterima: "Diterima", batal: "Batal" };
const PO_STATUS_CLS = {
  draft: "border-amber-500 text-amber-700 bg-amber-50",
  diterima: "border-[#008A00] text-[#008A00] bg-[#008A00]/5",
  batal: "border-zinc-400 text-zinc-500 bg-zinc-50",
};
const PAY_LABEL = { belum_lunas: "Belum Lunas", sebagian: "Sebagian", lunas: "Lunas" };
const PAY_CLS = {
  belum_lunas: "border-[#E81123] text-[#E81123] bg-[#E81123]/5",
  sebagian: "border-amber-500 text-amber-700 bg-amber-50",
  lunas: "border-[#008A00] text-[#008A00] bg-[#008A00]/5",
};

const inputCls = "rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none";

function formatNum(n) {
  if (n === null || n === undefined || n === "") return "0";
  return Number(n).toLocaleString("id-ID", { maximumFractionDigits: 4 });
}

export default function Purchasing() {
  const [tab, setTab] = useState("po");
  const [stats, setStats] = useState(null);
  const [pos, setPOs] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [priceHistory, setPriceHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [p, sp, m, s, ph] = await Promise.all([
        api.get("/purchasing/purchase-orders"),
        api.get("/purchasing/suppliers"),
        api.get("/inventory/materials"),
        api.get("/purchasing/stats"),
        api.get("/purchasing/price-history"),
      ]);
      setPOs(p.data);
      setSuppliers(sp.data);
      setMaterials(m.data);
      setStats(s.data);
      setPriceHistory(ph.data.items || []);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Modul</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Pembelian</h1>
          <p className="text-sm text-zinc-500 mt-1">Purchase Order, supplier, dan riwayat harga beli bahan.</p>
        </div>
      </div>

      {/* Stats */}
      <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
        <StatCard label="Total PO" value={stats?.total_po ?? 0} icon={ShoppingCart} isCount testId="stat-total-po" />
        <StatCard label="Total Pembelian" value={stats?.total_purchase ?? 0} icon={PackageCheck} testId="stat-total-purchase" />
        <StatCard label="Hutang Belum Lunas" value={stats?.outstanding ?? 0} icon={Wallet} testId="stat-outstanding" negative />
        <StatCard label="Supplier Aktif" value={stats?.total_suppliers ?? 0} icon={UsersIcon} isCount testId="stat-suppliers" />
      </div>

      {/* Tabs */}
      <div className="mt-8 border-b border-zinc-200">
        <div className="flex flex-wrap gap-1">
          <TabButton active={tab === "po"} onClick={() => setTab("po")} testId="tab-po">Purchase Order</TabButton>
          <TabButton active={tab === "suppliers"} onClick={() => setTab("suppliers")} testId="tab-suppliers">Supplier</TabButton>
          <TabButton active={tab === "history"} onClick={() => setTab("history")} testId="tab-history">Histori Harga</TabButton>
        </div>
      </div>

      <div className="mt-6">
        {loading ? (
          <div className="py-12 text-center text-zinc-400 font-mono text-xs">Memuat…</div>
        ) : tab === "po" ? (
          <POTab pos={pos} suppliers={suppliers} materials={materials} reload={loadAll} />
        ) : tab === "suppliers" ? (
          <SuppliersTab suppliers={suppliers} reload={loadAll} />
        ) : (
          <PriceHistoryTab history={priceHistory} />
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, isCount, testId, negative }) {
  const valueCls = negative && value > 0 ? "text-[#E81123]" : "text-zinc-900";
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
      className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${active ? "border-[#002FA7] text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-900"}`}
    >
      {children}
    </button>
  );
}

/* ---------------- PO TAB ---------------- */
const EMPTY_PO = {
  po_no: "", supplier_id: "", supplier_name: "",
  date: new Date().toISOString().slice(0, 10),
  items: [], tax_pct: 0, notes: "", invoice_no: "",
};

function POTab({ pos, suppliers, materials, reload }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_PO);
  const [saving, setSaving] = useState(false);
  const [payFor, setPayFor] = useState(null);
  const [payAmount, setPayAmount] = useState(0);
  const [statusFilter, setStatusFilter] = useState("all");

  const activeMaterials = materials.filter((m) => m.active !== false);
  const activeSuppliers = suppliers.filter((s) => s.active !== false);

  const filtered = pos.filter((p) => statusFilter === "all" || p.status === statusFilter);

  const openCreate = () => {
    const firstMat = activeMaterials[0];
    setForm({ ...EMPTY_PO, items: [{ material_id: firstMat?.id || "", quantity: 0, unit_price: firstMat?.purchase_price || 0 }] });
    setOpen(true);
  };

  const addItem = () => {
    const firstMat = activeMaterials[0];
    setForm((f) => ({ ...f, items: [...(f.items || []), { material_id: firstMat?.id || "", quantity: 0, unit_price: firstMat?.purchase_price || 0 }] }));
  };
  const removeItem = (idx) => setForm((f) => ({ ...f, items: f.items.filter((_, i) => i !== idx) }));
  const updItem = (idx, key, val) => setForm((f) => ({ ...f, items: f.items.map((it, i) => i === idx ? { ...it, [key]: val } : it) }));

  const onMaterialPick = (idx, mid) => {
    const mat = materials.find((m) => m.id === mid);
    setForm((f) => ({ ...f, items: f.items.map((it, i) => i === idx ? { ...it, material_id: mid, unit_price: mat?.purchase_price || it.unit_price } : it) }));
  };

  const onSupplierPick = (e) => {
    const sid = e.target.value;
    const sup = suppliers.find((s) => s.id === sid);
    setForm((f) => ({ ...f, supplier_id: sid, supplier_name: sup?.name || "" }));
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.supplier_id && !form.supplier_name.trim()) { toast.error("Pilih supplier atau isi nama"); return; }
    const items = form.items.filter((i) => i.material_id && Number(i.quantity) > 0).map((i) => ({
      material_id: i.material_id, quantity: Number(i.quantity), unit_price: Number(i.unit_price) || 0,
    }));
    if (items.length === 0) { toast.error("Tambahkan minimal 1 item bahan"); return; }
    setSaving(true);
    try {
      await api.post("/purchasing/purchase-orders", {
        ...form,
        supplier_id: form.supplier_id || null,
        supplier_name: form.supplier_id ? undefined : form.supplier_name.trim(),
        tax_pct: Number(form.tax_pct) || 0,
        items,
      });
      toast.success("Purchase Order dibuat");
      setOpen(false);
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally { setSaving(false); }
  };

  const receive = async (p) => {
    if (!window.confirm(`Terima PO ${p.po_no}? Stok bahan akan otomatis bertambah.`)) return;
    try { await api.put(`/purchasing/purchase-orders/${p.id}/receive`); toast.success("PO diterima, stok diperbarui"); await reload(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };
  const cancel = async (p) => {
    if (!window.confirm(`Batalkan PO ${p.po_no}?`)) return;
    try { await api.put(`/purchasing/purchase-orders/${p.id}/cancel`); toast.success("PO dibatalkan"); await reload(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };
  const remove = async (p) => {
    if (!window.confirm(`Hapus PO ${p.po_no}? ${p.status === "diterima" ? "Stok akan dikembalikan (rollback)." : ""}`)) return;
    try { await api.delete(`/purchasing/purchase-orders/${p.id}`); toast.success("PO dihapus"); await reload(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  const openPay = (p) => { setPayFor(p); setPayAmount(Math.max(Number(p.total || 0) - Number(p.amount_paid || 0), 0)); };
  const submitPay = async () => {
    if (payAmount <= 0) { toast.error("Jumlah bayar harus > 0"); return; }
    try {
      await api.put(`/purchasing/purchase-orders/${payFor.id}/pay`, { amount: Number(payAmount) });
      toast.success("Pembayaran dicatat");
      setPayFor(null); setPayAmount(0);
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal");
    }
  };

  const previewSubtotal = form.items.reduce((s, it) => s + Number(it.quantity || 0) * Number(it.unit_price || 0), 0);
  const previewTax = previewSubtotal * Number(form.tax_pct || 0) / 100;
  const previewTotal = previewSubtotal + previewTax;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <select data-testid="po-status-filter" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm">
            <option value="all">Semua Status</option>
            <option value="draft">Draft</option>
            <option value="diterima">Diterima</option>
            <option value="batal">Batal</option>
          </select>
          <div className="text-sm text-zinc-500">{filtered.length} PO</div>
        </div>
        <button data-testid="add-po-button" onClick={openCreate} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> Buat PO
        </button>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">No. PO</th>
              <th className="px-4 py-3">Supplier</th>
              <th className="px-4 py-3">Item</th>
              <th className="px-4 py-3 text-right">Total</th>
              <th className="px-4 py-3 text-right">Terbayar</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Pembayaran</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada PO.</td></tr>
            )}
            {filtered.map((p) => (
              <tr key={p.id} data-testid="po-row" className="border-b border-zinc-100 hover:bg-zinc-50/80 align-top">
                <td className="px-4 py-3 font-mono text-xs">
                  <div className="font-semibold text-zinc-900">{p.po_no}</div>
                  <div className="text-[10px] text-zinc-500 mt-0.5">{p.date}</div>
                  {p.invoice_no && <div className="text-[10px] text-zinc-500 mt-0.5">Inv: {p.invoice_no}</div>}
                </td>
                <td className="px-4 py-3 font-medium text-zinc-900">{p.supplier_name}</td>
                <td className="px-4 py-3 text-xs text-zinc-600">
                  {(p.items || []).map((it, i) => (
                    <div key={i} className="font-mono">{it.material_name}: {formatNum(it.quantity)} {it.material_unit} × {formatIDR(it.unit_price)}</div>
                  ))}
                </td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900 font-semibold">{formatIDR(p.total)}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(p.amount_paid || 0)}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border ${PO_STATUS_CLS[p.status] || ""}`}>{PO_STATUS_LABEL[p.status] || p.status}</span>
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border ${PAY_CLS[p.payment_status] || ""}`}>{PAY_LABEL[p.payment_status] || p.payment_status}</span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1 flex-wrap">
                    {p.status === "draft" && (
                      <button data-testid="receive-po-button" onClick={() => receive(p)} className="px-2 py-1 border border-[#008A00] text-[#008A00] hover:bg-[#008A00]/10 text-[10px] font-bold uppercase" title="Terima">Terima</button>
                    )}
                    {p.status !== "batal" && p.payment_status !== "lunas" && (
                      <button data-testid="pay-po-button" onClick={() => openPay(p)} className="px-2 py-1 border border-[#002FA7] text-[#002FA7] hover:bg-[#002FA7]/10 text-[10px] font-bold uppercase" title="Bayar">Bayar</button>
                    )}
                    {p.status === "draft" && (
                      <button data-testid="cancel-po-button" onClick={() => cancel(p)} className="px-2 py-1 border border-amber-500 text-amber-700 hover:bg-amber-50 text-[10px] font-bold uppercase" title="Batal">Batal</button>
                    )}
                    <button data-testid="delete-po-button" onClick={() => remove(p)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus"><Trash2 className="w-3.5 h-3.5" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Create PO Modal */}
      {open && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
          <div className="bg-white border border-zinc-300 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-5 border-b border-zinc-200 sticky top-0 bg-white">
              <div>
                <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Baru</div>
                <div className="font-heading text-xl font-bold text-zinc-900">Buat Purchase Order</div>
              </div>
              <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-zinc-100" data-testid="close-po-modal"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field label="Supplier">
                  {activeSuppliers.length > 0 ? (
                    <select data-testid="po-supplier" value={form.supplier_id} onChange={onSupplierPick} className={inputCls}>
                      <option value="">— pilih atau ketik manual —</option>
                      {activeSuppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  ) : (
                    <div className="text-xs text-amber-700 font-mono">Belum ada supplier — isi manual di bawah</div>
                  )}
                </Field>
                <Field label="Atau ketik nama supplier baru">
                  <input data-testid="po-supplier-name" value={form.supplier_name || ""} onChange={(e) => setForm((f) => ({ ...f, supplier_name: e.target.value, supplier_id: "" }))} className={inputCls} placeholder={form.supplier_id ? "(pakai supplier terpilih)" : "Nama supplier"} disabled={!!form.supplier_id} />
                </Field>
                <Field label="No. PO (Opsional)" hint="Auto-generate jika kosong">
                  <input data-testid="po-no" value={form.po_no || ""} onChange={(e) => setForm((f) => ({ ...f, po_no: e.target.value }))} className={inputCls + " font-mono"} />
                </Field>
                <Field label="Tanggal PO">
                  <input data-testid="po-date" type="date" required value={form.date} onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))} className={inputCls} />
                </Field>
                <Field label="Pajak (%)" hint="PPN 11 dsb.">
                  <input data-testid="po-tax" type="number" step="0.01" min="0" value={form.tax_pct} onChange={(e) => setForm((f) => ({ ...f, tax_pct: e.target.value }))} className={inputCls + " font-mono"} />
                </Field>
                <Field label="No. Invoice (Opsional)">
                  <input data-testid="po-invoice" value={form.invoice_no || ""} onChange={(e) => setForm((f) => ({ ...f, invoice_no: e.target.value }))} className={inputCls} />
                </Field>
              </div>

              <div className="border-t border-zinc-200 pt-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-[11px] uppercase tracking-widest font-bold text-zinc-700">Item Bahan</div>
                  <button type="button" data-testid="po-add-item" onClick={addItem} className="text-xs text-[#002FA7] hover:underline font-semibold">+ Tambah Item</button>
                </div>
                <div className="space-y-2">
                  {form.items.map((it, idx) => (
                    <div key={idx} className="grid grid-cols-12 gap-2 items-start">
                      <div className="col-span-5">
                        <select data-testid={`po-item-mat-${idx}`} required value={it.material_id} onChange={(e) => onMaterialPick(idx, e.target.value)} className={inputCls}>
                          <option value="">— pilih bahan —</option>
                          {activeMaterials.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.unit})</option>)}
                        </select>
                      </div>
                      <div className="col-span-2">
                        <input data-testid={`po-item-qty-${idx}`} type="number" step="0.0001" min="0.0001" required placeholder="Qty" value={it.quantity} onChange={(e) => updItem(idx, "quantity", e.target.value)} className={inputCls + " font-mono"} />
                      </div>
                      <div className="col-span-3">
                        <input data-testid={`po-item-price-${idx}`} type="number" step="0.01" min="0" required placeholder="Harga/unit" value={it.unit_price} onChange={(e) => updItem(idx, "unit_price", e.target.value)} className={inputCls + " font-mono"} />
                      </div>
                      <div className="col-span-1 text-xs text-zinc-500 pt-2 font-mono">
                        {formatIDR(Number(it.quantity || 0) * Number(it.unit_price || 0))}
                      </div>
                      <div className="col-span-1">
                        <button type="button" onClick={() => removeItem(idx)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]"><X className="w-3.5 h-3.5" /></button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <Field label="Catatan (Opsional)">
                <input data-testid="po-notes" value={form.notes || ""} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} className={inputCls} />
              </Field>

              <div className="p-3 bg-zinc-50 border border-zinc-200 space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-zinc-600">Subtotal:</span><span className="font-mono font-semibold">{formatIDR(previewSubtotal)}</span></div>
                <div className="flex justify-between"><span className="text-zinc-600">Pajak ({Number(form.tax_pct || 0)}%):</span><span className="font-mono">{formatIDR(previewTax)}</span></div>
                <div className="flex justify-between pt-1 border-t border-zinc-300 font-bold text-zinc-900">
                  <span>Total PO:</span><span className="font-mono">{formatIDR(previewTotal)}</span>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
                <button type="button" onClick={() => setOpen(false)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
                <button data-testid="save-po-button" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 disabled:opacity-60">{saving ? "Menyimpan…" : "Simpan (Draft)"}</button>
              </div>
              <div className="text-[10px] text-zinc-500 font-mono">Stok bahan hanya akan bertambah saat PO ditandai &ldquo;Diterima&rdquo;.</div>
            </form>
          </div>
        </div>
      )}

      {/* Pay Modal */}
      {payFor && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
          <div className="bg-white border border-zinc-300 w-full max-w-md">
            <div className="flex items-center justify-between p-5 border-b border-zinc-200">
              <div>
                <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Bayar PO</div>
                <div className="font-heading text-xl font-bold text-zinc-900">{payFor.po_no}</div>
              </div>
              <button onClick={() => setPayFor(null)} className="p-1.5 hover:bg-zinc-100" data-testid="close-pay-modal"><X className="w-4 h-4" /></button>
            </div>
            <div className="p-5 space-y-4">
              <div className="p-3 bg-zinc-50 border border-zinc-200 text-sm space-y-1">
                <div className="flex justify-between"><span className="text-zinc-600">Total PO:</span><span className="font-mono">{formatIDR(payFor.total)}</span></div>
                <div className="flex justify-between"><span className="text-zinc-600">Sudah dibayar:</span><span className="font-mono">{formatIDR(payFor.amount_paid || 0)}</span></div>
                <div className="flex justify-between pt-1 border-t border-zinc-300 font-bold text-[#E81123]">
                  <span>Sisa hutang:</span><span className="font-mono">{formatIDR(Number(payFor.total || 0) - Number(payFor.amount_paid || 0))}</span>
                </div>
              </div>
              <Field label="Jumlah Bayar (Rp)">
                <input data-testid="pay-amount" type="number" step="0.01" min="0" value={payAmount} onChange={(e) => setPayAmount(e.target.value)} className={inputCls + " font-mono"} autoFocus />
              </Field>
              <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
                <button type="button" onClick={() => setPayFor(null)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
                <button data-testid="save-pay-button" onClick={submitPay} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90">Simpan</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- SUPPLIERS TAB ---------------- */
const EMPTY_SUP = { name: "", phone: "", address: "", email: "", contact_person: "", notes: "", active: true };

function SuppliersTab({ suppliers, reload }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_SUP);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = suppliers.filter((s) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return s.name.toLowerCase().includes(q) || (s.phone || "").includes(q) || (s.contact_person || "").toLowerCase().includes(q);
  });

  const openCreate = () => { setEditing(null); setForm(EMPTY_SUP); setOpen(true); };
  const openEdit = (s) => { setEditing(s); setForm({ ...EMPTY_SUP, ...s }); setOpen(true); };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editing) {
        await api.put(`/purchasing/suppliers/${editing.id}`, form);
        toast.success("Supplier diperbarui");
      } else {
        await api.post("/purchasing/suppliers", form);
        toast.success("Supplier ditambahkan");
      }
      setOpen(false);
      await reload();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally { setSaving(false); }
  };

  const remove = async (s) => {
    if (!window.confirm(`Hapus supplier "${s.name}"?`)) return;
    try {
      const { data } = await api.delete(`/purchasing/suppliers/${s.id}`);
      toast.success(data.soft_deleted ? "Supplier dinonaktifkan (ada PO history)" : "Supplier dihapus");
      await reload();
    } catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input data-testid="sup-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama / telepon / contact…" className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none" />
        </div>
        <button data-testid="add-supplier-button" onClick={openCreate} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> Tambah Supplier
        </button>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Nama Supplier</th>
              <th className="px-4 py-3">Kontak</th>
              <th className="px-4 py-3">Alamat</th>
              <th className="px-4 py-3 text-right">PO</th>
              <th className="px-4 py-3 text-right">Total Beli</th>
              <th className="px-4 py-3 text-right">Hutang</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada supplier. Klik &ldquo;Tambah Supplier&rdquo;.</td></tr>
            )}
            {filtered.map((s) => (
              <tr key={s.id} data-testid="supplier-row" className="border-b border-zinc-100 hover:bg-zinc-50/80">
                <td className="px-4 py-3">
                  <div className="font-medium text-zinc-900">{s.name}</div>
                  {s.contact_person && <div className="text-xs text-zinc-500">CP: {s.contact_person}</div>}
                  {!s.active && <span className="inline-flex mt-1 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border border-zinc-400 text-zinc-500 bg-zinc-50">Non-aktif</span>}
                </td>
                <td className="px-4 py-3 text-xs">
                  {s.phone && <div className="font-mono text-zinc-700">{s.phone}</div>}
                  {s.email && <div className="text-zinc-500">{s.email}</div>}
                </td>
                <td className="px-4 py-3 text-xs text-zinc-600 max-w-xs">{s.address || "—"}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900">{s.po_count || 0}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(s.total_purchase || 0)}</td>
                <td className={`px-4 py-3 font-mono text-right font-bold ${Number(s.outstanding || 0) > 0 ? "text-[#E81123]" : "text-zinc-400"}`}>{formatIDR(s.outstanding || 0)}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <button data-testid="edit-supplier-button" onClick={() => openEdit(s)} className="p-1.5 hover:bg-zinc-100 text-zinc-700"><Pencil className="w-3.5 h-3.5" /></button>
                    <button data-testid="delete-supplier-button" onClick={() => remove(s)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]"><Trash2 className="w-3.5 h-3.5" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
          <div className="bg-white border border-zinc-300 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-5 border-b border-zinc-200 sticky top-0 bg-white">
              <div>
                <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{editing ? "Edit" : "Baru"}</div>
                <div className="font-heading text-xl font-bold text-zinc-900">{editing ? "Edit Supplier" : "Tambah Supplier"}</div>
              </div>
              <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-zinc-100" data-testid="close-supplier-modal"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={submit} className="p-5 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field label="Nama Supplier">
                  <input data-testid="sup-name" required value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className={inputCls} placeholder="PT Sumber Print" />
                </Field>
                <Field label="Contact Person">
                  <input data-testid="sup-cp" value={form.contact_person || ""} onChange={(e) => setForm((f) => ({ ...f, contact_person: e.target.value }))} className={inputCls} placeholder="Bapak Ali" />
                </Field>
                <Field label="Telepon">
                  <input data-testid="sup-phone" value={form.phone || ""} onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))} className={inputCls + " font-mono"} placeholder="0812xxxx" />
                </Field>
                <Field label="Email">
                  <input data-testid="sup-email" type="email" value={form.email || ""} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} className={inputCls} />
                </Field>
              </div>
              <Field label="Alamat">
                <textarea data-testid="sup-address" value={form.address || ""} onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))} className={inputCls} rows={2} />
              </Field>
              <Field label="Catatan (Opsional)">
                <input data-testid="sup-notes" value={form.notes || ""} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} className={inputCls} />
              </Field>
              <label className="inline-flex items-center gap-2 text-sm text-zinc-700">
                <input type="checkbox" checked={form.active} onChange={(e) => setForm((f) => ({ ...f, active: e.target.checked }))} className="w-4 h-4" />
                Supplier Aktif
              </label>
              <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
                <button type="button" onClick={() => setOpen(false)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
                <button data-testid="save-supplier-button" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 disabled:opacity-60">{saving ? "Menyimpan…" : "Simpan"}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- PRICE HISTORY TAB ---------------- */
function PriceHistoryTab({ history }) {
  const [expanded, setExpanded] = useState(null);
  const [search, setSearch] = useState("");
  const filtered = history.filter((h) => !search || h.material_name.toLowerCase().includes(search.toLowerCase()));

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input data-testid="ph-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama bahan…" className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none" />
        </div>
        <div className="text-sm text-zinc-500">{filtered.length} bahan tercatat</div>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Bahan</th>
              <th className="px-4 py-3 text-right">Harga Awal</th>
              <th className="px-4 py-3 text-right">Harga Terbaru</th>
              <th className="px-4 py-3 text-right">Min</th>
              <th className="px-4 py-3 text-right">Rata-rata</th>
              <th className="px-4 py-3 text-right">Max</th>
              <th className="px-4 py-3 text-right">Perubahan</th>
              <th className="px-4 py-3 text-right">Riwayat</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada data riwayat harga. Buat PO atau catat Barang Masuk untuk mulai tracking.</td></tr>
            )}
            {filtered.map((h) => {
              const isUp = h.change_pct > 0;
              const isDown = h.change_pct < 0;
              return (
                <Fragment key={h.material_id}>
                  <tr data-testid="price-history-row" className="border-b border-zinc-100 hover:bg-zinc-50/80">
                    <td className="px-4 py-3">
                      <div className="font-medium text-zinc-900">{h.material_name}</div>
                      <div className="text-xs text-zinc-500">{h.material_unit}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(h.first_price)}</td>
                    <td className="px-4 py-3 font-mono text-right text-zinc-900 font-semibold">{formatIDR(h.current_price)}</td>
                    <td className="px-4 py-3 font-mono text-right text-[#008A00]">{formatIDR(h.min_price)}</td>
                    <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(h.avg_price)}</td>
                    <td className="px-4 py-3 font-mono text-right text-[#E81123]">{formatIDR(h.max_price)}</td>
                    <td className="px-4 py-3 text-right">
                      <span className={`inline-flex items-center gap-1 font-mono text-xs font-bold ${isUp ? "text-[#E81123]" : isDown ? "text-[#008A00]" : "text-zinc-500"}`}>
                        {isUp ? <TrendingUp className="w-3 h-3" /> : isDown ? <TrendingDown className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
                        {h.change_pct > 0 ? "+" : ""}{h.change_pct}%
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button data-testid="expand-history-button" onClick={() => setExpanded(expanded === h.material_id ? null : h.material_id)} className="text-xs text-[#002FA7] hover:underline font-semibold">
                        {expanded === h.material_id ? "Tutup" : `${h.history.length} entri`}
                      </button>
                    </td>
                  </tr>
                  {expanded === h.material_id && (
                    <tr>
                      <td colSpan={8} className="px-4 py-3 bg-zinc-50">
                        <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-600 mb-2">Riwayat Detail</div>
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-[10px] font-bold text-zinc-600 uppercase tracking-widest border-b border-zinc-300">
                              <th className="py-1.5 pr-3">Tanggal</th>
                              <th className="py-1.5 pr-3">Supplier</th>
                              <th className="py-1.5 pr-3">Ref</th>
                              <th className="py-1.5 pr-3 text-right">Qty</th>
                              <th className="py-1.5 pr-3 text-right">Harga/Unit</th>
                            </tr>
                          </thead>
                          <tbody>
                            {h.history.map((row, i) => {
                              const prevPrice = i > 0 ? h.history[i - 1].unit_price : row.unit_price;
                              const diff = row.unit_price - prevPrice;
                              return (
                                <tr key={i} className="border-b border-zinc-200">
                                  <td className="py-1.5 pr-3 font-mono text-zinc-700">{row.date}</td>
                                  <td className="py-1.5 pr-3 text-zinc-700">{row.supplier || "—"}</td>
                                  <td className="py-1.5 pr-3 font-mono text-zinc-500">{row.po_no || row.invoice_no || "—"}</td>
                                  <td className="py-1.5 pr-3 font-mono text-right text-zinc-700">{formatNum(row.quantity)}</td>
                                  <td className="py-1.5 pr-3 font-mono text-right text-zinc-900 font-semibold">
                                    {formatIDR(row.unit_price)}
                                    {i > 0 && diff !== 0 && (
                                      <span className={`ml-2 text-[10px] ${diff > 0 ? "text-[#E81123]" : "text-[#008A00]"}`}>
                                        {diff > 0 ? "+" : ""}{formatIDR(diff)}
                                      </span>
                                    )}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
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
