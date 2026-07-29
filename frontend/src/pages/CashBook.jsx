import { useEffect, useMemo, useState } from "react";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import {
  Plus, Trash2, X, Search, Wallet, TrendingUp, TrendingDown, Download,
  Pencil, ArrowUpCircle, ArrowDownCircle, Settings, ChevronRight, Lock,
  BookOpen, Users, CheckCircle2, RotateCcw,
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
  // Toggle: sembunyikan kolom Kode Akun & teks angka akun di UI (default: tersembunyi)
  const [showAccountCode, setShowAccountCode] = useState(() => {
    try { return localStorage.getItem("cashbook.showAccountCode") === "1"; } catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem("cashbook.showAccountCode", showAccountCode ? "1" : "0"); } catch { /* ignore */ }
  }, [showAccountCode]);

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

  // Search helper reused across tabs
  const matchesSearch = (t) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (t.description || "").toLowerCase().includes(q)
      || (t.account_name || "").toLowerCase().includes(q)
      || (t.account_code || "").toLowerCase().includes(q)
      || (t.reference || "").toLowerCase().includes(q);
  };

  // BukuKas: SEMUA akun KECUALI 101 Kas (per request user)
  const filteredBook = txData.transactions.filter((t) => t.account_code !== "101" && matchesSearch(t));
  // Jurnal Akuntansi: hanya Kas 101 (arus kas utama)
  const filteredJournal = txData.transactions.filter((t) => t.account_code === "101" && matchesSearch(t));

  const removeTx = async (t) => {
    if (t.auto) {
      // Cek dulu apakah orphan (sumber PO/Sale sudah dihapus)
      try {
        const chk = await api.get(`/cashbook/transactions/${t.id}/orphan-check`);
        if (!chk.data.is_orphan) {
          toast.error(`Transaksi otomatis dari ${chk.data.source_type} ${chk.data.reference}. Batalkan / hapus di modul sumbernya.`);
          return;
        }
        // Orphan — konfirmasi khusus
        if (!window.confirm(
          `Transaksi ini dibuat otomatis dari ${chk.data.source_type} ${chk.data.reference}, tapi sumbernya sudah dihapus (orphan).\n\nHapus transaksi kas ini sekarang?`
        )) return;
      } catch (err) {
        toast.error("Gagal cek status transaksi");
        return;
      }
    } else {
      if (!window.confirm("Apakah Anda yakin ingin menghapus data ini?")) return;
    }
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
      <div className="mt-6 border-b border-zinc-200 flex items-center gap-1 flex-wrap">
        <TabBtn active={tab === "book"} onClick={() => setTab("book")} testId="tab-book">Buku Kas</TabBtn>
        <TabBtn active={tab === "journal"} onClick={() => setTab("journal")} testId="tab-journal"><BookOpen className="w-3.5 h-3.5 inline -mt-0.5 mr-1" />Jurnal Akuntansi</TabBtn>
        <TabBtn active={tab === "kasbon"} onClick={() => setTab("kasbon")} testId="tab-kasbon"><Users className="w-3.5 h-3.5 inline -mt-0.5 mr-1" />Kasbon Sementara</TabBtn>
        <TabBtn active={tab === "summary"} onClick={() => setTab("summary")} testId="tab-summary">Ringkasan Kategori</TabBtn>
        <div className="ml-auto">
          <label className="inline-flex items-center gap-2 text-[11px] uppercase tracking-widest font-semibold text-zinc-500 hover:text-zinc-900 cursor-pointer select-none pb-2" title="Tampilkan kolom Kode Akun & referensi angka akun (untuk finance/audit)">
            <input
              type="checkbox"
              data-testid="toggle-account-code"
              checked={showAccountCode}
              onChange={(e) => setShowAccountCode(e.target.checked)}
              className="rounded-none border border-zinc-400 w-3.5 h-3.5 accent-[#002FA7]"
            />
            Tampilkan Kode Akun
          </label>
        </div>
      </div>

      <div className="mt-5">
        {tab === "book" && (
          <BookTab
            month={month} setMonth={setMonth} search={search} setSearch={setSearch}
            txData={txData} filtered={filteredBook} loading={loading}
            showAccountCode={showAccountCode}
            onEdit={(t) => { setEditingTx(t); setOpenTx(true); }}
            onRemove={removeTx}
          />
        )}
        {tab === "journal" && (
          <JournalTab
            month={month} setMonth={setMonth} search={search} setSearch={setSearch}
            txData={txData} filtered={filteredJournal} loading={loading}
            showAccountCode={showAccountCode}
            onEdit={(t) => { setEditingTx(t); setOpenTx(true); }}
            onRemove={removeTx}
          />
        )}
        {tab === "kasbon" && (
          <KasbonTab month={month} setMonth={setMonth} onCashChanged={loadAll} />
        )}
        {tab === "summary" && (
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
          {filtered.length} transaksi Non-Kas · <span className="text-zinc-400">(akun 101 Kas ditampilkan di tab Jurnal Akuntansi)</span>
        </div>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm table-fixed">
          <colgroup>
            <col className="w-[110px]" />
            <col className="w-[90px]" />
            <col className="w-[180px]" />
            <col />
            <col className="w-[140px]" />
            <col className="w-[140px]" />
            <col className="w-[90px]" />
          </colgroup>
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Tanggal</th>
              <th className="px-4 py-3">Kode Akun</th>
              <th className="px-4 py-3">Nama Akun</th>
              <th className="px-4 py-3">Keterangan</th>
              <th className="px-4 py-3 text-right">Pemasukan</th>
              <th className="px-4 py-3 text-right">Pengeluaran</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada transaksi non-Kas bulan ini.</td></tr>
            )}
            {filtered.map((t) => (
              <tr key={t.id} data-testid="cash-tx-row" className={`border-b border-zinc-100 hover:bg-zinc-50/80 ${t.auto ? "bg-amber-50/30" : ""}`}>
                <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap">
                  {t.date}
                  {t.auto && (
                    <span className="ml-1 text-[9px] uppercase tracking-widest font-bold text-amber-700 inline-flex items-center gap-1 align-middle" title="Transaksi otomatis dari modul sumbernya"><Lock className="w-2.5 h-2.5" /></span>
                  )}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs font-bold text-zinc-700 whitespace-nowrap">{t.account_code}</td>
                <td className="px-4 py-2.5">
                  <div className="text-xs font-medium truncate" title={t.account_name}>{t.account_name}</div>
                </td>
                <td className="px-4 py-2.5 text-xs">
                  <div className="break-words">{t.description}</div>
                  {t.reference && <div className="text-[10px] font-mono text-zinc-400 mt-0.5">ref: {t.reference}</div>}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-xs">{t.type === "in" ? <span className="text-[#008A00] font-bold">{formatIDR(t.amount)}</span> : ""}</td>
                <td className="px-4 py-2.5 text-right font-mono text-xs">{t.type === "out" ? <span className="text-[#E81123] font-bold">{formatIDR(t.amount)}</span> : ""}</td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center justify-end gap-1">
                    <button data-testid="edit-tx-button" onClick={() => onEdit(t)} disabled={t.auto} className="p-1.5 hover:bg-zinc-100 text-zinc-700 disabled:opacity-30 disabled:cursor-not-allowed" title={t.auto ? "Transaksi otomatis — edit di modul sumbernya" : "Edit"}><Pencil className="w-3.5 h-3.5" /></button>
                    <button data-testid="del-tx-button" onClick={() => onRemove(t)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title={t.auto ? "Coba hapus (sistem akan cek orphan)" : "Hapus"}><Trash2 className="w-3.5 h-3.5" /></button>
                  </div>
                </td>
              </tr>
            ))}
            {!loading && filtered.length > 0 && (
              <tr className="border-t-2 border-zinc-900 bg-zinc-50">
                <td className="px-4 py-3" colSpan={4}>
                  <span className="text-xs font-bold uppercase tracking-widest text-zinc-900">TOTAL NON-KAS</span>
                </td>
                <td className="px-4 py-3 text-right font-mono font-bold text-[#008A00]">{formatIDR(filtered.filter(t => t.type === "in").reduce((s, t) => s + Number(t.amount || 0), 0))}</td>
                <td className="px-4 py-3 text-right font-mono font-bold text-[#E81123]">{formatIDR(filtered.filter(t => t.type === "out").reduce((s, t) => s + Number(t.amount || 0), 0))}</td>
                <td className="px-4 py-3"></td>
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
  const eligible = accounts.filter((a) => a.active !== false && a.type === forcedType);
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
  const resetToZero = async () => {
    if (!window.confirm("Reset Saldo Awal ke Rp 0? Aksi ini bisa dibatalkan dengan mengisi ulang saldo dan klik Simpan.")) return;
    setSaving(true);
    try {
      await api.put("/cashbook/settings", { opening_balance: 0, opening_date: form.opening_date });
      toast.success("Saldo awal berhasil di-reset ke Rp 0");
      await onSaved();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal reset");
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
          <div className="flex flex-wrap justify-between items-center gap-2 pt-3 border-t border-zinc-200">
            <button
              type="button"
              data-testid="reset-setting-button"
              onClick={resetToZero}
              disabled={saving}
              className="rounded-none bg-white border border-[#E81123] text-[#E81123] px-4 py-2.5 text-xs font-bold uppercase tracking-wider hover:bg-[#E81123]/5 disabled:opacity-40 inline-flex items-center gap-1.5"
              title="Reset Saldo Awal ke Rp 0"
            >
              <Trash2 className="w-3.5 h-3.5" /> Reset ke 0
            </button>
            <div className="flex gap-2">
              <button type="button" onClick={onClose} className="rounded-none bg-white border border-zinc-300 px-5 py-2.5 text-sm hover:bg-zinc-50">Batal</button>
              <button data-testid="save-setting-button" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-6 py-2.5 text-sm font-bold uppercase tracking-wider disabled:opacity-40">{saving ? "Menyimpan…" : "Simpan"}</button>
            </div>
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

/* ================================================================
   ============= TAB: JURNAL AKUNTANSI (Debet/Kredit) =============
   Konvensi kustom (permintaan user):
   - KREDIT = pemasukan / pengisian saldo kas (kas bertambah)
   - DEBET  = pengeluaran (kas berkurang)
   - Saldo berjalan = saldo sebelumnya + Kredit − Debet
   Data sumber sama dengan Buku Kas — hanya tampilan berbeda.
   ================================================================ */
function JournalTab({ month, setMonth, search, setSearch, txData, filtered, loading, onEdit, onRemove, showAccountCode }) {
  // KREDIT hanya untuk pemasukan yang masuk ke Akun 101 Kas (account_code === "101" & type=in)
  // DEBET: semua pengeluaran kas (type=out) — tidak difilter berdasarkan account_code
  const kasTx = filtered.filter((t) =>
    t.type === "out" || (t.type === "in" && t.account_code === "101")
  );
  // Recompute running balance dari saldo awal + Kredit − Debet
  const jurnal = (() => {
    let running = Number(txData.opening_balance || 0);
    return kasTx.map((t) => {
      running = t.type === "in" ? running + Number(t.amount || 0) : running - Number(t.amount || 0);
      return { ...t, balance: running };
    });
  })();
  const totalKredit = kasTx.reduce((s, t) => s + (t.type === "in" ? Number(t.amount) : 0), 0);
  const totalDebet = kasTx.reduce((s, t) => s + (t.type === "out" ? Number(t.amount) : 0), 0);
  const closingBalance = Number(txData.opening_balance || 0) + totalKredit - totalDebet;
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <input
            type="month" value={month} onChange={(e) => setMonth(e.target.value)}
            data-testid="journal-month-filter"
            className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none"
          />
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Cari keterangan…"
              data-testid="journal-search"
              className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-80 focus:border-[#002FA7] focus:outline-none"
            />
          </div>
          <span className="text-[10px] font-bold uppercase tracking-widest bg-[#002FA7]/10 text-[#002FA7] px-2.5 py-1.5 border border-[#002FA7]/30 whitespace-nowrap">Debet: Semua · Kredit: Hanya {showAccountCode ? "101 Kas" : "Kas Utama"}</span>
        </div>
        <div className="text-xs text-zinc-500 font-mono">
          {jurnal.length} jurnal · Debet <b className="text-[#E81123]">{formatIDR(totalDebet)}</b> · Kredit <b className="text-[#008A00]">{formatIDR(totalKredit)}</b>
        </div>
      </div>

      <div className="border border-zinc-900 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-900 text-white text-[11px] font-bold uppercase tracking-widest">
              {showAccountCode && <th className="px-3 py-3 border-r border-zinc-700">Kode Akun</th>}
              <th className="px-3 py-3 border-r border-zinc-700">Nama Akun</th>
              <th className="px-3 py-3 border-r border-zinc-700 whitespace-nowrap">Tanggal</th>
              <th className="px-3 py-3 border-r border-zinc-700">Keterangan</th>
              <th className="px-3 py-3 text-right border-r border-zinc-700 bg-[#E81123]/90">Debet</th>
              <th className="px-3 py-3 text-right border-r border-zinc-700 bg-[#008A00]/90">Kredit</th>
              <th className="px-3 py-3 text-right border-r border-zinc-700">Saldo</th>
              <th className="px-3 py-3 text-center whitespace-nowrap">Aksi</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-zinc-200 bg-[#002FA7]/5">
              <td colSpan={showAccountCode ? 4 : 3} className="px-3 py-2.5">
                <span className="text-xs font-bold uppercase tracking-widest text-[#002FA7]">Saldo Awal {monthLabel(month)}</span>
              </td>
              <td className="px-3 py-2.5"></td>
              <td className="px-3 py-2.5"></td>
              <td className="px-3 py-2.5 text-right font-mono font-bold text-[#002FA7]">{formatIDR(txData.opening_balance)}</td>
              <td className="px-3 py-2.5"></td>
            </tr>
            {loading && <tr><td colSpan={showAccountCode ? 8 : 7} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {!loading && jurnal.length === 0 && (
              <tr><td colSpan={showAccountCode ? 8 : 7} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada arus kas bulan ini.</td></tr>
            )}
            {jurnal.map((t) => (
              <tr key={t.id} data-testid="journal-row" className={`border-b border-zinc-100 hover:bg-zinc-50 ${t.auto ? "bg-amber-50/40" : ""}`}>
                {showAccountCode && (
                  <td className="px-3 py-2.5 font-mono text-xs font-bold text-zinc-700 whitespace-nowrap">{t.account_code}</td>
                )}
                <td className="px-3 py-2.5 text-xs">
                  {t.account_name}
                  {t.auto && <span className="ml-2 text-[9px] uppercase tracking-widest font-bold text-amber-700 inline-flex items-center gap-1"><Lock className="w-2.5 h-2.5" /> Auto</span>}
                </td>
                <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">{t.date}</td>
                <td className="px-3 py-2.5 text-xs">
                  <div>{t.description}</div>
                  {t.reference && <div className="text-[10px] font-mono text-zinc-400 mt-0.5">ref: {t.reference}</div>}
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-xs bg-[#E81123]/5">
                  {t.type === "out" ? <span className="text-[#E81123] font-bold">{formatIDR(t.amount)}</span> : <span className="text-zinc-300">—</span>}
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-xs bg-[#008A00]/5">
                  {t.type === "in" ? <span className="text-[#008A00] font-bold">{formatIDR(t.amount)}</span> : <span className="text-zinc-300">—</span>}
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-xs font-bold text-zinc-900">{formatIDR(t.balance)}</td>
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <div className="flex items-center justify-center gap-1">
                    <button
                      data-testid={`journal-edit-${t.id}`}
                      onClick={() => onEdit && onEdit(t)}
                      title={t.auto ? "Transaksi otomatis — edit tidak disarankan" : "Edit transaksi"}
                      className="p-1.5 hover:bg-[#002FA7]/10 text-[#002FA7]"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button
                      data-testid={`journal-del-${t.id}`}
                      onClick={() => onRemove && onRemove(t)}
                      title="Hapus transaksi"
                      className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!loading && jurnal.length > 0 && (
              <tr className="border-t-2 border-zinc-900 bg-zinc-50">
                <td colSpan={showAccountCode ? 4 : 3} className="px-3 py-3">
                  <span className="text-xs font-bold uppercase tracking-widest text-zinc-900">Total Debet / Kredit</span>
                </td>
                <td className="px-3 py-3 text-right font-mono font-bold text-[#E81123]">{formatIDR(totalDebet)}</td>
                <td className="px-3 py-3 text-right font-mono font-bold text-[#008A00]">{formatIDR(totalKredit)}</td>
                <td className="px-3 py-3 text-right font-mono font-bold text-lg text-zinc-900">{formatIDR(closingBalance)}</td>
                <td className="px-3 py-3"></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-3 text-[11px] text-zinc-500">
        <b>Konvensi:</b> Debet = pengeluaran kas (semua arus keluar) · Kredit = pemasukan kas <b>khusus {showAccountCode ? "Akun 101 Kas" : "Kas Utama"}</b> · Saldo = Saldo Awal + Kredit − Debet.
        Pemasukan dari akun lain (misal {showAccountCode ? "301 Penjualan Tunai / 301-BCA / Shopee" : "Penjualan Tunai / BCA / Shopee"}) <b>tidak masuk kredit di jurnal ini</b>. Untuk menambah transaksi, gunakan tombol <b>Pemasukan</b> / <b>Pengeluaran</b> di atas.
      </div>
    </div>
  );
}

/* ================================================================
   ================== TAB: KASBON SEMENTARA =======================
   Kasbon staff/karyawan pending — bisa dilunaskan atau dihapus.
   ================================================================ */
function KasbonTab({ month, setMonth, onCashChanged }) {
  const [data, setData] = useState({ items: [], total_open: 0, total_settled: 0, total_all: 0, count: 0 });
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState(""); // "" | "open" | "settled"
  const [search, setSearch] = useState("");
  const [openForm, setOpenForm] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const params = { month };
      if (filterStatus) params.status = filterStatus;
      const res = await api.get("/cashbook/kasbon", { params });
      setData(res.data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat kasbon");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [month, filterStatus]);

  const filtered = data.items.filter((k) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (k.name || "").toLowerCase().includes(q) || (k.description || "").toLowerCase().includes(q);
  });

  const settle = async (k) => {
    if (!window.confirm(`Tandai kasbon ${k.name} (${formatIDR(k.amount)}) sebagai LUNAS?`)) return;
    try {
      await api.put(`/cashbook/kasbon/${k.id}/settle`);
      toast.success("Kasbon dilunaskan · Kas otomatis terpotong");
      await load();
      if (onCashChanged) await onCashChanged();
    } catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };
  const reopen = async (k) => {
    try {
      await api.put(`/cashbook/kasbon/${k.id}/reopen`);
      toast.success("Kasbon dibuka kembali · Transaksi kas dibatalkan");
      await load();
      if (onCashChanged) await onCashChanged();
    } catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };
  const remove = async (k) => {
    if (!window.confirm(`Hapus kasbon ${k.name}?`)) return;
    try {
      await api.delete(`/cashbook/kasbon/${k.id}`);
      toast.success("Kasbon dihapus");
      await load();
      if (onCashChanged) await onCashChanged();
    } catch (err) { toast.error(formatApiError(err.response?.data?.detail) || "Gagal"); }
  };

  return (
    <div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-zinc-200 border border-zinc-200 mb-5">
        <div className="bg-white p-4">
          <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Kasbon Belum Lunas</div>
          <div data-testid="kasbon-total-open" className="font-mono text-2xl font-bold mt-1 text-[#E81123]">{formatIDR(data.total_open)}</div>
        </div>
        <div className="bg-white p-4">
          <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Sudah Dilunaskan</div>
          <div data-testid="kasbon-total-settled" className="font-mono text-2xl font-bold mt-1 text-[#008A00]">{formatIDR(data.total_settled)}</div>
        </div>
        <div className="bg-white p-4">
          <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Total Semua Kasbon Bulan Ini</div>
          <div className="font-mono text-2xl font-bold mt-1 text-zinc-900">{formatIDR(data.total_all)}</div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} data-testid="kasbon-month-filter"
            className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none" />
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} data-testid="kasbon-status-filter"
            className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm focus:border-[#002FA7] focus:outline-none">
            <option value="">Semua Status</option>
            <option value="open">Belum Lunas</option>
            <option value="settled">Sudah Lunas</option>
          </select>
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama / keterangan…" data-testid="kasbon-search"
              className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-72 focus:border-[#002FA7] focus:outline-none" />
          </div>
        </div>
        <button data-testid="kasbon-add-button" onClick={() => { setEditing(null); setOpenForm(true); }}
          className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-bold uppercase tracking-wider hover:bg-[#001E7A] inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> Tambah Kasbon
        </button>
      </div>

      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-3 py-3 whitespace-nowrap">Tanggal</th>
              <th className="px-3 py-3">Nama</th>
              <th className="px-3 py-3">Keterangan</th>
              <th className="px-3 py-3 text-right">Jumlah</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={6} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada kasbon.</td></tr>
            )}
            {filtered.map((k) => (
              <tr key={k.id} data-testid="kasbon-row" className={`border-b border-zinc-100 hover:bg-zinc-50 ${k.status === "settled" ? "opacity-60" : ""}`}>
                <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">{k.date}</td>
                <td className="px-3 py-2.5 text-sm font-semibold text-zinc-900">{k.name}</td>
                <td className="px-3 py-2.5 text-xs text-zinc-600">{k.description || "—"}</td>
                <td className="px-3 py-2.5 text-right font-mono text-sm font-bold text-zinc-900">{formatIDR(k.amount)}</td>
                <td className="px-3 py-2.5">
                  {k.status === "settled" ? (
                    <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-widest font-bold text-[#008A00] bg-[#008A00]/10 px-2 py-1">
                      <CheckCircle2 className="w-3 h-3" /> Lunas
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-widest font-bold text-[#E81123] bg-[#E81123]/10 px-2 py-1">
                      Belum Lunas
                    </span>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center justify-end gap-1">
                    {k.status === "open" ? (
                      <button data-testid="kasbon-settle-btn" onClick={() => settle(k)} className="p-1.5 hover:bg-[#008A00]/10 text-[#008A00]" title="Tandai lunas">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      </button>
                    ) : (
                      <button data-testid="kasbon-reopen-btn" onClick={() => reopen(k)} className="p-1.5 hover:bg-amber-100 text-amber-700" title="Buka kembali">
                        <RotateCcw className="w-3.5 h-3.5" />
                      </button>
                    )}
                    <button data-testid="kasbon-edit-btn" onClick={() => { setEditing(k); setOpenForm(true); }} className="p-1.5 hover:bg-zinc-100 text-zinc-700" title="Edit">
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button data-testid="kasbon-del-btn" onClick={() => remove(k)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title="Hapus">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!loading && filtered.length > 0 && (
              <tr className="border-t-2 border-zinc-900 bg-zinc-50">
                <td colSpan={3} className="px-3 py-3">
                  <span className="text-xs font-bold uppercase tracking-widest text-zinc-900">TOTAL {filterStatus === "settled" ? "LUNAS" : filterStatus === "open" ? "BELUM LUNAS" : "SEMUA KASBON"}</span>
                </td>
                <td className="px-3 py-3 text-right font-mono font-bold text-lg text-zinc-900">
                  {formatIDR(
                    filtered.reduce((s, k) => s + Number(k.amount || 0), 0)
                  )}
                </td>
                <td colSpan={2}></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {openForm && (
        <KasbonFormModal
          initial={editing}
          onClose={() => { setOpenForm(false); setEditing(null); }}
          onSaved={async () => { setOpenForm(false); setEditing(null); await load(); }}
        />
      )}
    </div>
  );
}

function KasbonFormModal({ initial, onClose, onSaved }) {
  const isEdit = initial && initial.id;
  const [form, setForm] = useState({
    date: initial?.date || todayISO(),
    name: initial?.name || "",
    description: initial?.description || "",
    amount: initial?.amount || 0,
  });
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) { toast.error("Nama wajib diisi"); return; }
    if (Number(form.amount) <= 0) { toast.error("Jumlah harus > 0"); return; }
    setSaving(true);
    try {
      const payload = {
        date: form.date,
        name: form.name.trim(),
        description: form.description.trim(),
        amount: Number(form.amount),
      };
      if (isEdit) {
        await api.put(`/cashbook/kasbon/${initial.id}`, payload);
        toast.success("Kasbon diperbarui");
      } else {
        await api.post("/cashbook/kasbon", payload);
        toast.success("Kasbon ditambahkan");
      }
      await onSaved();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white border border-zinc-300 w-full max-w-lg">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center bg-[#002FA7]">
              <Users className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Kasbon Sementara</div>
              <h3 className="font-bold text-zinc-900 text-lg">{isEdit ? "Edit Kasbon" : "Tambah Kasbon"}</h3>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-4">
          <Field label="Tanggal">
            <input data-testid="kasbon-form-date" type="date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputCls} />
          </Field>
          <Field label="Nama Penerima Kasbon">
            <input data-testid="kasbon-form-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="cth: Budi Santoso" className={inputCls} />
          </Field>
          <Field label="Keterangan">
            <input data-testid="kasbon-form-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Untuk keperluan..." className={inputCls} />
          </Field>
          <Field label="Jumlah (Rp)">
            <input data-testid="kasbon-form-amount" type="number" required min="0" step="0.01" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className={inputCls} />
          </Field>
          <div className="flex justify-end gap-2 pt-2 border-t border-zinc-200">
            <button type="button" onClick={onClose} className="rounded-none bg-white border border-zinc-300 px-4 py-2 text-sm hover:bg-zinc-50">Batal</button>
            <button data-testid="kasbon-form-save" type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-6 py-2 text-sm font-bold uppercase tracking-wider disabled:opacity-40">
              {saving ? "…" : "Simpan"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

