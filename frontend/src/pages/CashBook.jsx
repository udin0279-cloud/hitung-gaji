import { useEffect, useMemo, useState } from "react";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import {
  Plus, Trash2, X, Search, Wallet, TrendingUp, TrendingDown, Download,
  Pencil, ArrowUpCircle, ArrowDownCircle, Settings, ChevronRight, Lock,
} from "lucide-react";

const inputCls = "rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none";

function todayISO() { return new Date().toISOString().slice(0, 10); }
function currentMonth() { return new Date().toISOString().slice(0, 7); }
function monthLabel(m) {
  const [y, mm] = m.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"];
  return `${names[parseInt(mm, 10) - 1]} ${y}`;
}

export default function CashBook() {
  const [tab, setTab] = useState("book");
  const [month, setMonth] = useState(currentMonth());
  const [accounts, setAccounts] = useState([]);
  const [txData, setTxData] = useState({ opening_balance: 0, transactions: [], closing_balance: 0 });
  const [summary, setSummary] = useState(null);
  const [balance, setBalance] = useState(null);
  const [setting, setSetting] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [openTx, setOpenTx] = useState(false);
  const [editingTx, setEditingTx] = useState(null);
  const [openSetting, setOpenSetting] = useState(false);
  const [openAccounts, setOpenAccounts] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [a, tx, s, b, st] = await Promise.all([
        api.get("/cashbook/accounts"),
        api.get("/cashbook/transactions", { params: { month } }),
        api.get("/cashbook/summary", { params: { month } }),
        api.get("/cashbook/balance"),
        api.get("/cashbook/settings"),
      ]);
      setAccounts(a.data);
      setTxData(tx.data);
      setSummary(s.data);
      setBalance(b.data);
      setSetting(st.data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat data");
    } finally { setLoading(false); }
  };

  useEffect(() => { loadAll(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [month]);

  const filtered = txData.transactions.filter((t) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (t.description || "").toLowerCase().includes(q)
      || (t.account_name || "").toLowerCase().includes(q)
      || (t.account_code || "").toLowerCase().includes(q)
      || (t.reference || "").toLowerCase().includes(q);
  });

  const removeTx = async (t) => {
    if (t.auto) { toast.error("Transaksi otomatis dari Sales/PO — batalkan di modul sumbernya."); return; }
    if (!window.confirm(`Hapus transaksi "${t.description}"?`)) return;
    try { await api.delete(`/cashbook/transactions/${t.id}`); toast.success("Transaksi dihapus"); await loadAll(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  const exportExcel = async () => {
    try {
      const res = await api.get("/cashbook/export", { params: { month }, responseType: "blob" });
      const blob = new Blob([res.data], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Kas_Operasional_${month}.xlsx`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch { toast.error("Gagal export"); }
  };

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Modul</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Kas Operasional</h1>
          <p className="text-sm text-zinc-500 mt-1">Pencatatan kas harian dengan integrasi otomatis Penjualan & Pembelian.</p>
        </div>
        <div className="flex items-center gap-2">
          <button data-testid="cash-setting-button" onClick={() => setOpenSetting(true)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-4 py-2.5 text-sm hover:bg-zinc-50 inline-flex items-center gap-2" title="Saldo Awal">
            <Settings className="w-3.5 h-3.5" /> Saldo Awal
          </button>
          <button data-testid="cash-accounts-button" onClick={() => setOpenAccounts(true)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-4 py-2.5 text-sm hover:bg-zinc-50 inline-flex items-center gap-2">
            Kategori Akun
          </button>
          <button data-testid="cash-export-button" onClick={exportExcel} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-4 py-2.5 text-sm hover:bg-zinc-50 inline-flex items-center gap-2">
            <Download className="w-3.5 h-3.5" /> Export
          </button>
          <button data-testid="cash-tx-in-button" onClick={() => { setEditingTx({ type: "in" }); setOpenTx(true); }} className="rounded-none bg-[#008A00] text-white px-4 py-2.5 text-sm font-bold uppercase tracking-wider hover:bg-[#006D00] inline-flex items-center gap-2">
            <ArrowUpCircle className="w-4 h-4" /> Pemasukan
          </button>
          <button data-testid="cash-tx-out-button" onClick={() => { setEditingTx({ type: "out" }); setOpenTx(true); }} className="rounded-none bg-[#E81123] text-white px-4 py-2.5 text-sm font-bold uppercase tracking-wider hover:bg-[#C00E1F] inline-flex items-center gap-2">
            <ArrowDownCircle className="w-4 h-4" /> Pengeluaran
          </button>
        </div>
      </div>

      {/* Saldo Real-time */}
      <div className="mt-6 grid grid-cols-1 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
        <StatCard label="Saldo Kas Real-time" value={balance?.balance ?? 0} icon={Wallet} big positive={((balance?.balance ?? 0) >= 0)} testId="stat-balance" />
        <StatCard label={`Pemasukan ${monthLabel(month)}`} value={summary?.total_in ?? 0} icon={TrendingUp} positive testId="stat-in-month" />
        <StatCard label={`Pengeluaran ${monthLabel(month)}`} value={summary?.total_out ?? 0} icon={TrendingDown} danger testId="stat-out-month" />
        <StatCard label={`Saldo Akhir ${monthLabel(month)}`} value={summary?.closing_balance ?? 0} icon={Wallet} testId="stat-closing-month" positive={((summary?.closing_balance ?? 0) >= 0)} />
      </div>

      {/* Tabs */}
      <div className="mt-6 border-b border-zinc-200 flex items-center gap-1">
        <TabBtn active={tab === "book"} onClick={() => setTab("book")} testId="tab-book">Buku Kas</TabBtn>
        <TabBtn active={tab === "summary"} onClick={() => setTab("summary")} testId="tab-summary">Ringkasan Kategori</TabBtn>
      </div>

      <div className="mt-5">
        {tab === "book" ? (
          <BookTab
            month={month} setMonth={setMonth} search={search} setSearch={setSearch}
            txData={txData} filtered={filtered} loading={loading}
            onEdit={(t) => { setEditingTx(t); setOpenTx(true); }}
            onRemove={removeTx}
          />
        ) : (
          <SummaryTab summary={summary} month={month} setMonth={setMonth} />
        )}
      </div>

      {openTx && (
        <TxModal
          initial={editingTx}
          accounts={accounts}
          onClose={() => { setOpenTx(false); setEditingTx(null); }}
          onSaved={async () => { setOpenTx(false); setEditingTx(null); await loadAll(); }}
        />
      )}

      {openSetting && setting && (
        <SettingModal
          initial={setting}
          onClose={() => setOpenSetting(false)}
          onSaved={async () => { setOpenSetting(false); await loadAll(); }}
        />
      )}

      {openAccounts && (
        <AccountsModal
          accounts={accounts}
          onClose={() => setOpenAccounts(false)}
          onChanged={async () => { await loadAll(); }}
        />
      )}
    </div>
  );
}

function TabBtn({ active, onClick, children, testId }) {
  return (
    <button data-testid={testId} onClick={onClick} className={`px-5 py-2.5 text-sm font-semibold border-b-2 -mb-px transition-colors ${active ? "border-[#002FA7] text-[#002FA7]" : "border-transparent text-zinc-500 hover:text-zinc-900"}`}>
      {children}
    </button>
  );
}

function StatCard({ label, value, icon: Icon, positive, danger, testId, big }) {
  const color = danger ? "text-[#E81123]" : positive ? "text-[#008A00]" : "text-zinc-900";
  return (
    <div className="bg-white p-4 lg:p-5">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
        <Icon className="w-3.5 h-3.5 text-zinc-400" />
      </div>
      <div data-testid={testId} className={`font-mono ${big ? "text-2xl lg:text-3xl" : "text-xl lg:text-2xl"} tracking-tight font-bold mt-2 ${color}`}>
        {formatIDR(value)}
      </div>
    </div>
  );
}

/* ---------- Buku Kas Tab ---------- */
function BookTab({ month, setMonth, search, setSearch, txData, filtered, loading, onEdit, onRemove }) {
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <input
            type="month" value={month} onChange={(e) => setMonth(e.target.value)}
            data-testid="cash-month-filter"
            className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none"
          />
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Cari keterangan / akun / ref…"
              data-testid="cash-search"
              className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-72 focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
            />
          </div>
        </div>
        <div className="text-xs text-zinc-500 font-mono">
          {filtered.length} transaksi · Saldo Awal <b className="text-zinc-900">{formatIDR(txData.opening_balance)}</b> → Akhir <b className="text-zinc-900">{formatIDR(txData.closing_balance)}</b>
        </div>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-3 py-3">Tanggal</th>
              <th className="px-3 py-3">Kode</th>
              <th className="px-3 py-3">Nama Akun</th>
              <th className="px-3 py-3">Keterangan</th>
              <th className="px-3 py-3 text-right">Pemasukan</th>
              <th className="px-3 py-3 text-right">Pengeluaran</th>
              <th className="px-3 py-3 text-right">Saldo</th>
              <th className="px-3 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-zinc-200 bg-[#002FA7]/5">
              <td className="px-3 py-2.5 font-mono text-xs text-zinc-500">—</td>
              <td className="px-3 py-2.5" colSpan={3}>
                <span className="text-xs font-bold uppercase tracking-widest text-[#002FA7]">SALDO AWAL {monthLabel(month).toUpperCase()}</span>
              </td>
              <td className="px-3 py-2.5"></td>
              <td className="px-3 py-2.5"></td>
              <td className="px-3 py-2.5 text-right font-mono font-bold text-[#002FA7]">{formatIDR(txData.opening_balance)}</td>
              <td className="px-3 py-2.5"></td>
            </tr>
            {loading && <tr><td colSpan={8} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada transaksi bulan ini.</td></tr>
            )}
            {filtered.map((t) => (
              <tr key={t.id} data-testid="cash-tx-row" className={`border-b border-zinc-100 hover:bg-zinc-50/80 ${t.auto ? "bg-amber-50/30" : ""}`}>
                <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">{t.date}</td>
                <td className="px-3 py-2.5 font-mono text-xs text-zinc-500">{t.account_code}</td>
                <td className="px-3 py-2.5">
                  <div className="text-xs font-medium">{t.account_name}</div>
                  {t.auto && <div className="text-[9px] uppercase tracking-widest font-bold text-amber-700 mt-0.5 inline-flex items-center gap-1"><Lock className="w-2.5 h-2.5" /> Auto</div>}
                </td>
                <td className="px-3 py-2.5 text-xs">
                  <div>{t.description}</div>
                  {t.reference && <div className="text-[10px] font-mono text-zinc-400 mt-0.5">ref: {t.reference}</div>}
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-xs">{t.type === "in" ? <span className="text-[#008A00] font-bold">{formatIDR(t.amount)}</span> : ""}</td>
                <td className="px-3 py-2.5 text-right font-mono text-xs">{t.type === "out" ? <span className="text-[#E81123] font-bold">{formatIDR(t.amount)}</span> : ""}</td>
                <td className="px-3 py-2.5 text-right font-mono text-xs font-bold text-zinc-900">{formatIDR(t.balance)}</td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center justify-end gap-1">
                    <button data-testid="edit-tx-button" onClick={() => onEdit(t)} disabled={t.auto} className="p-1.5 hover:bg-zinc-100 text-zinc-700 disabled:opacity-30 disabled:cursor-not-allowed" title={t.auto ? "Transaksi otomatis" : "Edit"}><Pencil className="w-3.5 h-3.5" /></button>
                    <button data-testid="del-tx-button" onClick={() => onRemove(t)} disabled={t.auto} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123] disabled:opacity-30 disabled:cursor-not-allowed" title={t.auto ? "Transaksi otomatis" : "Hapus"}><Trash2 className="w-3.5 h-3.5" /></button>
                  </div>
                </td>
              </tr>
            ))}
            {!loading && filtered.length > 0 && (
              <tr className="border-t-2 border-zinc-900 bg-zinc-50">
                <td className="px-3 py-3" colSpan={4}>
                  <span className="text-xs font-bold uppercase tracking-widest text-zinc-900">SALDO AKHIR</span>
                </td>
                <td className="px-3 py-3"></td>
                <td className="px-3 py-3"></td>
                <td className="px-3 py-3 text-right font-mono font-bold text-lg text-zinc-900">{formatIDR(txData.closing_balance)}</td>
                <td className="px-3 py-3"></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------- Summary Tab (Breakdown per Kategori) ---------- */
function SummaryTab({ summary, month, setMonth }) {
  if (!summary) return <div className="text-zinc-400 text-sm">Memuat…</div>;
  const maxIn = Math.max(...(summary.breakdown_in || []).map((r) => r.amount), 1);
  const maxOut = Math.max(...(summary.breakdown_out || []).map((r) => r.amount), 1);
  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono" />
        <div className="text-xs text-zinc-500 font-mono ml-2">Periode: {summary.period_start} s/d {summary.period_end}</div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <BreakdownCard title="Pemasukan" color="#008A00" rows={summary.breakdown_in || []} total={summary.total_in} max={maxIn} />
        <BreakdownCard title="Pengeluaran" color="#E81123" rows={summary.breakdown_out || []} total={summary.total_out} max={maxOut} />
      </div>
      <div className="mt-6 bg-zinc-900 text-white p-6 font-mono grid grid-cols-2 md:grid-cols-4 gap-4">
        <SummaryStat label="Saldo Awal" value={summary.opening_balance} />
        <SummaryStat label="Pemasukan" value={summary.total_in} positive />
        <SummaryStat label="Pengeluaran" value={summary.total_out} negative />
        <SummaryStat label="Saldo Akhir" value={summary.closing_balance} big />
      </div>
    </div>
  );
}

function BreakdownCard({ title, color, rows, total, max }) {
  return (
    <div className="border border-zinc-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3 pb-2 border-b border-zinc-200">
        <div className="text-xs uppercase tracking-widest font-bold text-zinc-700">{title}</div>
        <div className="font-mono font-bold text-lg" style={{ color }}>{formatIDR(total)}</div>
      </div>
      {rows.length === 0 && <div className="text-zinc-400 text-xs font-mono py-6 text-center">Belum ada transaksi.</div>}
      <div className="space-y-2">
        {rows.map((r) => {
          const pct = (r.amount / max) * 100;
          return (
            <div key={r.account_code} data-testid="breakdown-row">
              <div className="flex justify-between text-xs mb-1">
                <span><span className="font-mono text-zinc-500 mr-2">{r.account_code}</span>{r.account_name}</span>
                <span className="font-mono font-bold text-zinc-900">{formatIDR(r.amount)}</span>
              </div>
              <div className="h-1.5 bg-zinc-100">
                <div className="h-full" style={{ width: `${pct}%`, backgroundColor: color, opacity: 0.85 }} />
              </div>
              <div className="text-[10px] text-zinc-400 font-mono mt-0.5">{r.count} transaksi</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SummaryStat({ label, value, positive, negative, big }) {
  const color = negative ? "text-[#ff9d9d]" : positive ? "text-[#4ade80]" : "text-white";
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-white/60 font-semibold">{label}</div>
      <div className={`${big ? "text-2xl" : "text-lg"} font-bold mt-1 ${color}`}>{formatIDR(value)}</div>
    </div>
  );
}

/* ---------- Transaction Modal ---------- */
function TxModal({ initial, accounts, onClose, onSaved }) {
  const isEdit = initial && initial.id;
  const forcedType = initial?.type;
  const eligible = accounts.filter((a) => a.active && a.type === forcedType);
  const [form, setForm] = useState({
    date: initial?.date || todayISO(),
    account_code: initial?.account_code || (eligible[0]?.code || ""),
    description: initial?.description || "",
    amount: initial?.amount || 0,
    reference: initial?.reference || "",
  });
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.description.trim()) { toast.error("Keterangan wajib diisi"); return; }
    if (Number(form.amount) <= 0) { toast.error("Jumlah harus > 0"); return; }
    setSaving(true);
    try {
      const payload = {
        date: form.date,
        account_code: form.account_code,
        description: form.description.trim(),
        amount: Number(form.amount),
        reference: form.reference.trim() || null,
      };
      if (isEdit) {
        await api.put(`/cashbook/transactions/${initial.id}`, payload);
        toast.success("Transaksi diperbarui");
      } else {
        await api.post("/cashbook/transactions", payload);
        toast.success("Transaksi ditambahkan");
      }
      await onSaved();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally { setSaving(false); }
  };

  const isIncome = forcedType === "in";
  const color = isIncome ? "#008A00" : "#E81123";

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white border border-zinc-300 w-full max-w-lg">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center" style={{ backgroundColor: color }}>
              {isIncome ? <ArrowUpCircle className="w-5 h-5 text-white" /> : <ArrowDownCircle className="w-5 h-5 text-white" />}
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{isEdit ? "Edit" : "Baru"}</div>
              <div className="font-heading text-xl font-bold text-zinc-900">{isIncome ? "Pemasukan Kas" : "Pengeluaran Kas"}</div>
            </div>
          </div>
          <button onClick={onClose} data-testid="close-tx-modal" className="p-1.5 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Tanggal">
              <input data-testid="tx-date" type="date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputCls + " font-mono"} />
            </Field>
            <Field label="Kategori Akun">
              <select data-testid="tx-account" required value={form.account_code} onChange={(e) => setForm({ ...form, account_code: e.target.value })} className={inputCls}>
                {eligible.map((a) => <option key={a.code} value={a.code}>{a.code} — {a.name}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Keterangan">
            <input data-testid="tx-desc" required value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder={isIncome ? "Terima setoran, jual barang…" : "Bayar listrik, beli bensin…"} className={inputCls} />
          </Field>
          <Field label={isIncome ? "Jumlah Pemasukan (Rp)" : "Jumlah Pengeluaran (Rp)"}>
            <input data-testid="tx-amount" type="number" min="1" step="0.01" required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className={inputCls + " font-mono text-lg font-bold"} style={{ color }} />
          </Field>
          <Field label="Referensi (Opsional)" hint="Contoh: no. nota, no. PO, no. faktur">
            <input data-testid="tx-reference" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} className={inputCls + " font-mono text-sm"} />
          </Field>
          <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
            <button type="button" onClick={onClose} className="rounded-none bg-white border border-zinc-300 px-5 py-2.5 text-sm hover:bg-zinc-50">Batal</button>
            <button data-testid="save-tx-button" type="submit" disabled={saving} className="rounded-none text-white px-8 py-3 text-sm font-bold uppercase tracking-wider disabled:opacity-40" style={{ backgroundColor: color }}>
              {saving ? "Menyimpan…" : "Simpan"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ---------- Setting Modal (Saldo Awal) ---------- */
function SettingModal({ initial, onClose, onSaved }) {
  const [form, setForm] = useState({
    opening_balance: initial.opening_balance || 0,
    opening_date: initial.opening_date || todayISO(),
  });
  const [saving, setSaving] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.put("/cashbook/settings", { opening_balance: Number(form.opening_balance), opening_date: form.opening_date });
      toast.success("Saldo awal diperbarui");
      await onSaved();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal");
    } finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white border border-zinc-300 w-full max-w-md">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200">
          <div className="font-heading text-xl font-bold">Saldo Awal Kas</div>
          <button onClick={onClose} className="p-1.5 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-4">
          <Field label="Tanggal Mulai" hint="Semua transaksi sebelum tanggal ini diabaikan">
            <input type="date" required data-testid="setting-date" value={form.opening_date} onChange={(e) => setForm({ ...form, opening_date: e.target.value })} className={inputCls + " font-mono"} />
          </Field>
          <Field label="Saldo Awal (Rp)">
            <input type="number" step="0.01" required data-testid="setting-balance" value={form.opening_balance} onChange={(e) => setForm({ ...form, opening_balance: e.target.value })} className={inputCls + " font-mono text-lg font-bold"} />
          </Field>
          <div className="flex justify-end gap-2 pt-3 border-t border-zinc-200">
            <button type="button" onClick={onClose} className="rounded-none bg-white border border-zinc-300 px-5 py-2.5 text-sm hover:bg-zinc-50">Batal</button>
            <button data-testid="save-setting-button" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-6 py-2.5 text-sm font-bold uppercase tracking-wider disabled:opacity-40">{saving ? "Menyimpan…" : "Simpan"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ---------- Accounts Modal (Kelola Kategori) ---------- */
function AccountsModal({ accounts, onClose, onChanged }) {
  const [openForm, setOpenForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ code: "", name: "", type: "out", active: true });
  const [saving, setSaving] = useState(false);

  const openAdd = () => { setEditing(null); setForm({ code: "", name: "", type: "out", active: true }); setOpenForm(true); };
  const openEdit = (a) => { setEditing(a); setForm({ code: a.code, name: a.name, type: a.type, active: a.active }); setOpenForm(true); };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editing) await api.put(`/cashbook/accounts/${editing.id}`, form);
      else await api.post("/cashbook/accounts", form);
      toast.success("Kategori tersimpan");
      setOpenForm(false);
      await onChanged();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal");
    } finally { setSaving(false); }
  };

  const remove = async (a) => {
    if (a.system) { toast.error("Akun sistem tidak bisa dihapus"); return; }
    if (!window.confirm(`Hapus kategori "${a.name}"?`)) return;
    try { await api.delete(`/cashbook/accounts/${a.id}`); toast.success("Kategori dihapus"); await onChanged(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white border border-zinc-300 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200 sticky top-0 bg-white">
          <div className="font-heading text-xl font-bold">Kategori Akun Kas</div>
          <button onClick={onClose} className="p-1.5 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5">
          <div className="flex justify-end mb-3">
            <button onClick={openAdd} data-testid="add-account-button" className="rounded-none bg-[#002FA7] text-white px-4 py-2 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2"><Plus className="w-3.5 h-3.5" /> Tambah</button>
          </div>
          <table className="w-full text-sm border border-zinc-200">
            <thead className="bg-zinc-50">
              <tr className="text-[10px] uppercase tracking-widest font-bold text-zinc-600">
                <th className="px-3 py-2 text-left">Kode</th>
                <th className="px-3 py-2 text-left">Nama Kategori</th>
                <th className="px-3 py-2 text-left">Tipe</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id} className="border-b border-zinc-100">
                  <td className="px-3 py-2 font-mono">{a.code}</td>
                  <td className="px-3 py-2">
                    {a.name}
                    {a.system && <span className="ml-2 text-[9px] uppercase tracking-widest bg-amber-100 text-amber-800 px-1.5 py-0.5">SYSTEM</span>}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`text-[10px] font-bold uppercase tracking-widest ${a.type === "in" ? "text-[#008A00]" : "text-[#E81123]"}`}>
                      {a.type === "in" ? "Pemasukan" : "Pengeluaran"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-zinc-500">{a.active ? "Aktif" : "Nonaktif"}</td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <button onClick={() => openEdit(a)} className="p-1.5 hover:bg-zinc-100 text-zinc-700"><Pencil className="w-3.5 h-3.5" /></button>
                      {!a.system && <button onClick={() => remove(a)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]"><Trash2 className="w-3.5 h-3.5" /></button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {openForm && (
          <div className="fixed inset-0 z-[60] bg-zinc-900/60 flex items-center justify-center p-4">
            <div className="bg-white border border-zinc-300 w-full max-w-md">
              <div className="flex items-center justify-between p-4 border-b border-zinc-200">
                <div className="font-heading font-bold">{editing ? "Edit Kategori" : "Kategori Baru"}</div>
                <button onClick={() => setOpenForm(false)} className="p-1.5 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
              </div>
              <form onSubmit={submit} className="p-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Kode Akun"><input required data-testid="acc-code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} className={inputCls + " font-mono"} placeholder="mis: 599" /></Field>
                  <Field label="Tipe">
                    <select required data-testid="acc-type" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className={inputCls}>
                      <option value="out">Pengeluaran</option>
                      <option value="in">Pemasukan</option>
                    </select>
                  </Field>
                </div>
                <Field label="Nama Kategori"><input required data-testid="acc-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputCls} /></Field>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
                  <span>Aktif</span>
                </label>
                <div className="flex justify-end gap-2 pt-2 border-t border-zinc-200">
                  <button type="button" onClick={() => setOpenForm(false)} className="rounded-none bg-white border border-zinc-300 px-4 py-2 text-sm hover:bg-zinc-50">Batal</button>
                  <button data-testid="save-account-button" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-6 py-2 text-sm font-bold uppercase tracking-wider disabled:opacity-40">{saving ? "…" : "Simpan"}</button>
                </div>
              </form>
            </div>
          </div>
        )}
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
