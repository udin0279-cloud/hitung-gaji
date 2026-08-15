import { useEffect, useMemo, useState } from "react";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import {
  Plus, Trash2, X, Search, Wallet, TrendingUp, TrendingDown, Download,
  Pencil, ArrowUpCircle, ArrowDownCircle, Settings, ChevronRight, ChevronLeft, Lock,
  BookOpen, Users, CheckCircle2, RotateCcw, RefreshCw, Target,
} from "lucide-react";

const inputCls = "rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none";

function todayISO() { return new Date().toISOString().slice(0, 10); }
function currentMonth() { return new Date().toISOString().slice(0, 7); }
function monthLabel(m) {
  const [y, mm] = m.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"];
  return `${names[parseInt(mm, 10) - 1]} ${y}`;
}
// Filter permanen Buku Kas: STRICT — hanya kasbon dgn status === 'PENDING' (backend normalize).
// Semua status lain (PAID/LUNAS/settled/paid/dll) DITOLAK — HARAM tampil di tab Buku Kas.
function isOpenKasbon(k) {
  if (!k) return false;
  // WHITELIST STRICT: hanya terima "PENDING" exact match.
  // Backend endpoint /cashbook/kasbon selalu normalize status ke "PENDING" atau "PAID".
  // Toleransi tambahan untuk backward-compat: "open"/"pending" (lowercase) dari data lama.
  const s = String(k.status || "").trim();
  if (s !== "PENDING" && s.toLowerCase() !== "open" && s.toLowerCase() !== "pending") return false;
  // Extra guard: kalau timestamp pelunasan ada → BUKAN pending
  if (k.settled_at || k.paid_at || k.date_settled) return false;
  // Nominal harus > 0
  if (Number(k.amount || 0) <= 0) return false;
  return true;
}

function prevMonthLabel(m) {
  // "2026-08" → "Jul 2026"; "2026-01" → "Des 2025"
  const [y, mm] = m.split("-").map((v) => parseInt(v, 10));
  const prevY = mm === 1 ? y - 1 : y;
  const prevM = mm === 1 ? 12 : mm - 1;
  const names = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"];
  return `${names[prevM - 1]} ${prevY}`;
}
function shiftMonth(m, delta) {
  // shiftMonth("2026-08", -1) → "2026-07"; shiftMonth("2026-12", 1) → "2027-01"
  const [y, mm] = m.split("-").map((v) => parseInt(v, 10));
  const total = y * 12 + (mm - 1) + delta;
  const nY = Math.floor(total / 12);
  const nM = (total % 12) + 1;
  return `${nY.toString().padStart(4, "0")}-${nM.toString().padStart(2, "0")}`;
}

/** MonthNav — picker bulan + tombol prev/next.
 * Props: value (YYYY-MM), onChange (str), testIdPrefix (opsional). */
function MonthNav({ value, onChange, testIdPrefix = "cash-month" }) {
  return (
    <div className="inline-flex items-stretch border border-zinc-300 bg-white">
      <button
        type="button"
        data-testid={`${testIdPrefix}-prev`}
        onClick={() => onChange(shiftMonth(value, -1))}
        title={`Bulan Sebelumnya (${prevMonthLabel(value)})`}
        className="px-2 border-r border-zinc-300 text-zinc-600 hover:bg-[#002FA7] hover:text-white transition-colors flex items-center"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
      <input
        type="month"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={`${testIdPrefix}-filter`}
        className="border-none bg-transparent px-3 py-2 text-sm font-mono focus:outline-none focus:bg-[#002FA7]/5"
      />
      <button
        type="button"
        data-testid={`${testIdPrefix}-next`}
        onClick={() => onChange(shiftMonth(value, 1))}
        title={`Bulan Berikutnya (${(() => { const nm = shiftMonth(value, 1); return prevMonthLabel(shiftMonth(nm, 1)); })()})`}
        className="px-2 border-l border-zinc-300 text-zinc-600 hover:bg-[#002FA7] hover:text-white transition-colors flex items-center"
      >
        <ChevronRight className="w-4 h-4" />
      </button>
    </div>
  );
}

export default function CashBook() {
  const [tab, setTab] = useState("book");
  const [month, setMonth] = useState(currentMonth());
  const [accounts, setAccounts] = useState([]);
  const [txData, setTxData] = useState({ opening_balance: 0, transactions: [], closing_balance: 0 });
  const [summary, setSummary] = useState(null);
  const [balance, setBalance] = useState(null);
  const [setting, setSetting] = useState(null);
  // Kasbon open (semua waktu) — dipakai untuk mengurangi Saldo Kas Real-time & Saldo Akhir bulan.
  const [kasbonOpen, setKasbonOpen] = useState({ items: [], total_open: 0 });
  const [cashPlaza, setCashPlaza] = useState({ amount: 0, count: 0 });
  // Baris virtual Cash Plaza untuk di-inject ke Jurnal Akuntansi (filteredBook).
  // Setiap baris = 1 payment cash/tunai di sale dengan branch=plaza + payment.date di bulan aktif.
  const [cashPlazaTxRows, setCashPlazaTxRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [openTx, setOpenTx] = useState(false);
  const [editingTx, setEditingTx] = useState(null);
  const [openSetting, setOpenSetting] = useState(false);
  const [openAccounts, setOpenAccounts] = useState(false);
  const [openAdjust, setOpenAdjust] = useState(false);
  const [openDiagnose, setOpenDiagnose] = useState(false);
  const [openMonthlyLock, setOpenMonthlyLock] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      // Compute first + last day of the month for Cash Plaza sales query.
      const [y, m] = month.split("-").map(Number);
      const first = `${y}-${String(m).padStart(2, "0")}-01`;
      const lastDay = new Date(y, m, 0).getDate();
      const last = `${y}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;

      const [a, tx, s, b, st, kb, sl] = await Promise.all([
        api.get("/cashbook/accounts"),
        api.get("/cashbook/transactions", { params: { month } }),
        api.get("/cashbook/summary", { params: { month } }),
        api.get("/cashbook/balance"),
        api.get("/cashbook/settings"),
        api.get("/cashbook/kasbon", { params: { status: "open" } }),
        api.get("/sales", { params: { date_from: first, date_to: last, limit: 5000 } }),
      ]);
      setAccounts(a.data);
      setTxData(tx.data);
      setSummary(s.data);
      setBalance(b.data);
      setSetting(st.data);
      // Cleanup: filter permanen — hanya kasbon dgn status open/pending yang dihitung.
      // Menangani data lama yang mungkin punya label status non-standard.
      const rawKasbon = kb.data.items || [];
      const openItems = rawKasbon.filter(isOpenKasbon);
      const openTotal = openItems.reduce((sum, k) => sum + Number(k.amount || 0), 0);
      setKasbonOpen({ items: openItems, total_open: openTotal });

      // Cash Plaza butuh fetch sales lebih luas: pelunasan bisa lintas bulan (nota bulan lalu, bayar cash bulan ini).
      // Fetch 6 bulan ke belakang dari akhir bulan aktif.
      const cpFetchFrom = new Date(y, m - 6, 1).toISOString().slice(0, 10);
      const cpFetchTo = last;
      const slBroad = await api.get("/sales", { params: { date_from: cpFetchFrom, date_to: cpFetchTo, limit: 10000 } });
      // Cash Plaza — DEFINISI SELARAS DENGAN KOLOM "CASH PLAZA NOMINAL" DI LAPORAN PENJUALAN.
      // Ambil dari `sale.payments[]` (record pembayaran granular), FILTER:
      //   - sale.branch === "plaza" (branch kosong dianggap "plaza")
      //   - payment.payment_method ∈ ["cash","tunai"]
      //   - payment.date jatuh dalam bulan aktif (untuk menangkap pelunasan lintas bulan)
      // Jumlahkan payment.amount. Sales dgn status apapun tetap ikut kalau punya payment cash di bulan itu.
      const salesRaw = Array.isArray(slBroad.data) ? slBroad.data : (slBroad.data.items || []);
      let cpAmount = 0, cpCount = 0;
      const _debug = [];
      const _cpVirtualTx = [];
      for (const x of salesRaw) {
        const branch = (x.branch || "plaza").toLowerCase();
        if (branch !== "plaza") continue;
        const payments = Array.isArray(x.payments) ? x.payments : [];
        let saleCp = 0;
        if (payments.length > 0) {
          for (const p of payments) {
            const pm = (p.payment_method || "").toLowerCase();
            if (pm !== "cash" && pm !== "tunai") continue;
            const pDate = (p.date || p.created_at || x.date || "").slice(0, 10);
            if (pDate < first || pDate > last) continue;
            const amt = Number(p.amount || 0);
            saleCp += amt;
            // Emit satu baris virtual Cash Plaza per payment (untuk Jurnal Akuntansi).
            _cpVirtualTx.push({
              id: `cp:${x.sale_no}:${pDate}:${_cpVirtualTx.length}`,
              date: pDate,
              account_code: "301-CP",
              account_name: "Cash Plaza",
              type: "in",
              description: `Cash Plaza — ${x.customer_name || x.sale_no}`,
              reference: x.sale_no,
              amount: amt,
              _virtual: true,
            });
          }
        } else {
          // Legacy: no payments[] tracking. Fallback ke sale.total bila:
          //   sale.date dalam bulan aktif DAN payment_method-nya cash/tunai.
          const sm = (x.payment_method || "").toLowerCase();
          const sDate = (x.date || "").slice(0, 10);
          if ((sm === "cash" || sm === "tunai") && sDate >= first && sDate <= last) {
            saleCp = Number(x.total || 0) - Number(x.sisa_tagihan || 0);
            if (saleCp > 0) {
              _cpVirtualTx.push({
                id: `cp:${x.sale_no}:${sDate}:legacy`,
                date: sDate,
                account_code: "301-CP",
                account_name: "Cash Plaza",
                type: "in",
                description: `Cash Plaza — ${x.customer_name || x.sale_no}`,
                reference: x.sale_no,
                amount: saleCp,
                _virtual: true,
              });
            }
          }
        }
        if (saleCp > 0) {
          cpAmount += saleCp;
          cpCount += 1;
          _debug.push({
            sale_no: x.sale_no, branch: x.branch, total: x.total, status: x.status,
            payments_count: payments.length, cash_paid_in_period: saleCp,
          });
        }
      }
      setCashPlazaTxRows(_cpVirtualTx);
      // eslint-disable-next-line no-console
      console.log("[CashPlaza]", { month, cpAmount, cpCount, samples: _debug.slice(0, 20), totalSalesFetched: salesRaw.length });
      setCashPlaza({ amount: cpAmount, count: cpCount });
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

  const filteredBook = [...txData.transactions, ...cashPlazaTxRows]
    .filter(t => t.account_code !== "101")
    .filter(matchesSearch)
    .sort((a, b) => (a.date || "").localeCompare(b.date || ""));
  // Tab Buku Kas (JournalTab):
  // - KREDIT: HANYA akun 101 (kas fisik masuk), + description tanpa keyword "penjualan"
  // - DEBET: SEMUA type=out (dari akun mana pun — semua uang keluar mengurangi kas)
  // - Akun 102-PTP (Piutang Perusahaan) DILARANG muncul di Buku Kas (khusus Jurnal Akuntansi).
  const filteredJournal = txData.transactions
    .filter(t => {
      if (t.account_code === "102-PTP") return false;
      if (t.type === "in") {
        return t.account_code === "101"
          && !(t.description || "").toLowerCase().includes("penjualan");
      }
      return t.type === "out";
    })
    .filter(matchesSearch);

  // Total Piutang Perusahaan (akun 102-PTP) — akumulatif dari semua transaksi bulan ini.
  const totalPiutangBulan = txData.transactions
    .filter(t => t.account_code === "102-PTP")
    .reduce((s, t) => s + (t.type === "in" ? Number(t.amount || 0) : -Number(t.amount || 0)), 0);

  // === Kartu Ringkasan DINAMIS mengikuti tab aktif ===
  // Buku Kas: totals dari filteredJournal (akun 101 in + all out). Opening = cascade dari backend.
  // Jurnal Akuntansi: totals dari filteredBook (akun non-101). Opening PAKSA = Rp 0 (permintaan user 2026-08-12).
  //   Rationale: Non-Kas / Jurnal Akuntansi tidak boleh cascade dari bulan sebelumnya —
  //   setiap bulan mulai bersih dari Rp 0.
  const _sumIn = (arr) => arr.reduce((s, t) => s + (t.type === "in" ? Number(t.amount || 0) : 0), 0);
  const _sumOut = (arr) => arr.reduce((s, t) => s + (t.type === "out" ? Number(t.amount || 0) : 0), 0);
  const bukuKasIn = _sumIn(filteredJournal);
  const bukuKasOut = _sumOut(filteredJournal);
  const bukuKasOpening = Number(txData.opening_balance || 0);
  const bukuKasClosing = bukuKasOpening + bukuKasIn - bukuKasOut;
  const jurnalIn = _sumIn(filteredBook);
  const jurnalOut = _sumOut(filteredBook);
  const jurnalOpening = 0; // Selalu Rp 0 di Jurnal Akuntansi — tidak cascade.
  const jurnalClosing = jurnalOpening + jurnalIn - jurnalOut;
  const cardData = tab === "book"
    ? { in: jurnalIn, out: jurnalOut, closing: jurnalClosing, realtime: jurnalClosing, showKasbon: false }
    : { in: bukuKasIn, out: bukuKasOut, closing: bukuKasClosing, realtime: (balance?.balance ?? 0), showKasbon: true };

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

  const [resyncing, setResyncing] = useState(false);
  const resyncSales = async () => {
    if (!window.confirm(
      "Sinkron Ulang Kas dari Penjualan + Pembelian?\n\nAksi ini akan:\n• Migrasi Penjualan Tunai historis (akun 301 → 101 Kas Utama)\n• Scan semua transaksi Penjualan (DP + LUNAS + pelunasan)\n• Scan semua PO Pembelian (bandingkan amount_paid vs cash tx tercatat)\n• Insert baris kas yang belum tercatat di Buku Kas\n• Data yang sudah ada akan di-skip (idempotent)\n\nLanjutkan?"
    )) return;
    setResyncing(true);
    try {
      const [migRes, salesRes, poRes] = await Promise.all([
        api.post("/cashbook/migrate-cash-sales-to-101"),
        api.post("/cashbook/resync-sales"),
        api.post("/cashbook/resync-purchases"),
      ]);
      const md = migRes.data;
      const sd = salesRes.data;
      const pd = poRes.data;
      const totalInserted = sd.missing_inserted + pd.missing_inserted;
      const totalAmount = Number(sd.total_inserted_amount) + Number(pd.total_inserted_amount);
      const migMsg = md.migrated > 0 ? ` · Migrasi 301→101: ${md.migrated} tx` : "";
      if (totalInserted === 0) {
        toast.success(
          `Sudah sinkron. Penjualan: ${sd.sales_scanned} sales · ${sd.payments_scanned} bayar · PO: ${pd.po_scanned} PO.${migMsg}`
        );
      } else {
        toast.success(
          `Berhasil sinkron ${totalInserted} baris (total Rp ${Number(totalAmount).toLocaleString("id-ID")}). Penjualan: ${sd.missing_inserted} · Pembelian: ${pd.missing_inserted}.${migMsg}`
        );
      }
      await loadAll();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal sinkron");
    } finally {
      setResyncing(false);
    }
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
          <button data-testid="cash-monthly-lock-button" onClick={() => setOpenMonthlyLock(true)} className="rounded-none bg-white text-[#F97316] border border-[#F97316]/40 px-4 py-2.5 text-sm hover:bg-[#F97316]/5 inline-flex items-center gap-2" title="Kunci Saldo Awal Bulan tertentu — override angka otomatis dengan angka pencatatan manual Anda">
            <Lock className="w-3.5 h-3.5" /> Kunci Saldo Bulan
          </button>
          <button data-testid="cash-diagnose-button" onClick={() => setOpenDiagnose(true)} className="rounded-none bg-white text-[#002FA7] border border-[#002FA7]/40 px-4 py-2.5 text-sm hover:bg-[#002FA7]/5 inline-flex items-center gap-2" title="Verifikasi rumus saldo — breakdown per akun untuk deteksi anomali">
            <Target className="w-3.5 h-3.5" /> Diagnose Saldo
          </button>
          <button data-testid="cash-accounts-button" onClick={() => setOpenAccounts(true)} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-4 py-2.5 text-sm hover:bg-zinc-50 inline-flex items-center gap-2">
            Kategori Akun
          </button>
          <button data-testid="cash-export-button" onClick={exportExcel} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-4 py-2.5 text-sm hover:bg-zinc-50 inline-flex items-center gap-2">
            <Download className="w-3.5 h-3.5" /> Export
          </button>
          <button data-testid="cash-resync-button" onClick={resyncSales} disabled={resyncing} className="rounded-none bg-white text-[#002FA7] border border-[#002FA7] px-4 py-2.5 text-sm hover:bg-[#002FA7]/5 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2" title="Backfill pembayaran dari Penjualan (DP/LUNAS) & Pembelian (PO) ke Buku Kas untuk data lama yang belum tercatat">
            <RefreshCw className={`w-3.5 h-3.5 ${resyncing ? "animate-spin" : ""}`} /> {resyncing ? "Menyinkron…" : "Sinkron Ulang Kas"}
          </button>
          <button data-testid="cash-tx-in-button" onClick={() => { setEditingTx({ type: "in" }); setOpenTx(true); }} className="rounded-none bg-[#008A00] text-white px-4 py-2.5 text-sm font-bold uppercase tracking-wider hover:bg-[#006D00] inline-flex items-center gap-2">
            <ArrowUpCircle className="w-4 h-4" /> Pemasukan
          </button>
          <button data-testid="cash-tx-out-button" onClick={() => { setEditingTx({ type: "out" }); setOpenTx(true); }} className="rounded-none bg-[#E81123] text-white px-4 py-2.5 text-sm font-bold uppercase tracking-wider hover:bg-[#C00E1F] inline-flex items-center gap-2">
            <ArrowDownCircle className="w-4 h-4" /> Pengeluaran
          </button>
        </div>
      </div>

      {/* Kartu Ringkasan — DINAMIS mengikuti tab aktif.
          Tab "Buku Kas" (journal): angka dari filteredJournal (Akun 101 + semua OUT). Real-time = saldo kas fisik dari backend.
          Tab "Jurnal Akuntansi" (book): angka dari filteredBook (Non-101). Real-time = closing bulan berjalan (tanpa balance API). */}
      <div className="mt-6 grid grid-cols-1 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
        <StatCard
          label={tab === "book" ? "Saldo Non-Kas Real-time" : "Saldo Kas Real-time"}
          value={cardData.showKasbon ? (cardData.realtime - kasbonOpen.total_open) : cardData.realtime}
          icon={Wallet}
          big
          positive={((cardData.showKasbon ? (cardData.realtime - kasbonOpen.total_open) : cardData.realtime) >= 0)}
          testId="stat-balance"
          subValue={cardData.showKasbon && kasbonOpen.total_open > 0 ? `− Kasbon: ${formatIDR(kasbonOpen.total_open)}` : null}
        />
        <StatCard label={`Pemasukan ${monthLabel(month)}`} value={cardData.in} icon={TrendingUp} positive testId="stat-in-month" />
        <StatCard label={`Pengeluaran ${monthLabel(month)}`} value={cardData.out} icon={TrendingDown} danger testId="stat-out-month" />
        <StatCard
          label={`Saldo Akhir ${monthLabel(month)}`}
          value={cardData.showKasbon ? (cardData.closing - kasbonOpen.total_open) : cardData.closing}
          icon={Wallet}
          testId="stat-closing-month"
          positive={((cardData.showKasbon ? (cardData.closing - kasbonOpen.total_open) : cardData.closing) >= 0)}
          subValue={cardData.showKasbon && kasbonOpen.total_open > 0 ? `− Kasbon: ${formatIDR(kasbonOpen.total_open)}` : null}
        />
      </div>

      {/* Tabs */}
      <div className="mt-6 border-b border-zinc-200 flex items-center gap-1 flex-wrap">
        <TabBtn active={tab === "book"} onClick={() => setTab("book")} testId="tab-book">Jurnal Akuntansi</TabBtn>
        <TabBtn active={tab === "journal"} onClick={() => setTab("journal")} testId="tab-journal"><BookOpen className="w-3.5 h-3.5 inline -mt-0.5 mr-1" />Buku Kas</TabBtn>
        <TabBtn active={tab === "kasbon"} onClick={() => setTab("kasbon")} testId="tab-kasbon"><Users className="w-3.5 h-3.5 inline -mt-0.5 mr-1" />Kasbon Sementara</TabBtn>
        <TabBtn active={tab === "summary"} onClick={() => setTab("summary")} testId="tab-summary">Ringkasan Kategori</TabBtn>
      </div>

      <div className="mt-5">
        {tab === "book" && (
          <BookTab
            month={month} setMonth={setMonth} search={search} setSearch={setSearch}
            txData={txData} filtered={filteredBook} loading={loading}
            kasbonOpen={kasbonOpen}
            totalPiutang={totalPiutangBulan}
            onChanged={loadAll}
            onEdit={(t) => { setEditingTx(t); setOpenTx(true); }}
            onRemove={removeTx}
            onAdjustBalance={() => setOpenAdjust(true)}
            currentBalance={(balance?.balance ?? 0) - kasbonOpen.total_open}
          />
        )}
        {tab === "journal" && (
          <JournalTab
            month={month} setMonth={setMonth} search={search} setSearch={setSearch}
            txData={txData} filtered={filteredJournal} loading={loading}
            kasbonOpen={kasbonOpen}
            onCashChanged={loadAll}
            onEdit={(t) => { setEditingTx(t); setOpenTx(true); }}
            onRemove={removeTx}
          />
        )}
        {tab === "kasbon" && (
          <KasbonTab month={month} setMonth={setMonth} onCashChanged={loadAll} />
        )}
        {tab === "summary" && (
          <SummaryTab summary={summary} month={month} setMonth={setMonth} cashPlaza={cashPlaza} />
        )}
      </div>

      {openTx && (
        <TxModal
          initial={editingTx}
          accounts={accounts}
          currentTab={tab}
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

      {openAdjust && (
        <AdjustBalanceModal
          currentBalance={(balance?.balance ?? 0) - kasbonOpen.total_open}
          onClose={() => setOpenAdjust(false)}
          onSaved={async () => { setOpenAdjust(false); await loadAll(); }}
        />
      )}

      {openDiagnose && (
        <DiagnoseSaldoModal
          month={month}
          onClose={() => setOpenDiagnose(false)}
        />
      )}

      {openMonthlyLock && (
        <MonthlyLockDialog
          currentMonth={month}
          onClose={() => setOpenMonthlyLock(false)}
          onSaved={async () => { await loadAll(); }}
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

function StatCard({ label, value, icon: Icon, positive, danger, testId, big, subValue }) {
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
      {subValue && (
        <div className="mt-1 text-[10px] font-mono text-[#F97316] font-semibold" title="Kasbon karyawan yang belum lunas, dikurangi dari saldo untuk cerminan kas fisik">{subValue}</div>
      )}
    </div>
  );
}

/* ---------- Buku Kas Tab ---------- */
function BookTab({ month, setMonth, search, setSearch, txData, filtered, loading, onEdit, onRemove, onAdjustBalance, currentBalance, kasbonOpen, totalPiutang = 0, onChanged }) {
  const [openBayarPiutang, setOpenBayarPiutang] = useState(false);
  // === RUMUS MATEMATIKA MURNI (Jurnal Akuntansi) ===
  // Saldo Awal = Rp 0 SELALU (permintaan user 2026-08-12: Jurnal TIDAK cascade).
  // Setiap bulan mulai bersih dari 0, hanya akumulasi transaksi bulan berjalan.
  // (Buku Kas / Akun 101 TIDAK terpengaruh — tetap cascade seperti biasa.)
  const openingBalance = 0;

  // Total Pemasukan = SEMUA `in` (apapun akunnya)
  const totalPemasukan = filtered.reduce(
    (s, t) => s + (t.type === "in" ? Number(t.amount || 0) : 0),
    0
  );
  // Total Pengeluaran = SEMUA `out`
  const totalPengeluaran = filtered.reduce(
    (s, t) => s + (t.type === "out" ? Number(t.amount || 0) : 0),
    0
  );
  const saldoAkhirComputed = openingBalance + totalPemasukan - totalPengeluaran;

  // Running balance per baris: sequential, ADD semua in, SUBTRACT semua out
  const balanceByRowIndex = (() => {
    let running = openingBalance;
    return filtered.map((t) => {
      if (t.type === "in") running += Number(t.amount || 0);
      else if (t.type === "out") running -= Number(t.amount || 0);
      return running;
    });
  })();

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 md:gap-3 mb-4">
        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          <MonthNav value={month} onChange={setMonth} testIdPrefix="cash-month" />
          <div className="relative flex-1 md:flex-none">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Cari keterangan / akun / ref…"
              data-testid="cash-search"
              className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-full md:w-72 focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
            />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 md:gap-3 w-full md:w-auto justify-between md:justify-end">
          <div className="text-xs text-zinc-500 font-mono">
            {filtered.length} transaksi
          </div>
          <button
            type="button"
            data-testid="cash-adjust-balance-btn"
            onClick={onAdjustBalance}
            className="rounded-none border border-[#002FA7] bg-white text-[#002FA7] px-3 py-2 text-[11px] md:text-xs font-bold uppercase tracking-wider hover:bg-[#002FA7] hover:text-white inline-flex items-center gap-2"
            title="Bikin jurnal penyesuaian otomatis agar saldo kas real-time menjadi angka target."
          >
            <Target className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Update Saldo Kas Terakhir</span>
            <span className="sm:hidden">Update Saldo</span>
          </button>
        </div>
      </div>

      {/* Ringkasan Piutang Perusahaan (khusus Jurnal Akuntansi) */}
      <div data-testid="jurnal-piutang-card" className="mb-4 border border-[#002FA7]/20 bg-[#002FA7]/[0.03] px-4 py-3 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-[#002FA7]/80 font-bold">Total Piutang Perusahaan (Akun 102-PTP)</div>
          <div className="text-[10px] font-mono text-zinc-500 mt-0.5">Akumulasi net (in − out) transaksi bulan {monthLabel(month)}. Khusus Jurnal Akuntansi.</div>
        </div>
        <div className="flex items-center justify-between md:justify-end gap-3 md:gap-4">
          <div data-testid="jurnal-piutang-value" className={`font-mono text-xl md:text-2xl font-bold ${totalPiutang >= 0 ? "text-[#002FA7]" : "text-[#E81123]"}`}>
            {formatIDR(totalPiutang)}
          </div>
          <button
            type="button"
            data-testid="btn-bayar-piutang"
            onClick={() => setOpenBayarPiutang(true)}
            className="rounded-none bg-[#002FA7] text-white px-3 md:px-4 py-2 text-[11px] md:text-xs font-bold uppercase tracking-wider hover:bg-[#001F7A] inline-flex items-center gap-2 whitespace-nowrap"
            title="Catat pelunasan piutang perusahaan. Insert 1 baris transaksi type=out ke akun 102-PTP. Tidak menyentuh Buku Kas."
          >
            <ArrowDownCircle className="w-3.5 h-3.5" /> Bayar Piutang
          </button>
        </div>
      </div>

      {openBayarPiutang && (
        <PiutangBayarModal
          onClose={() => setOpenBayarPiutang(false)}
          onSaved={async () => { setOpenBayarPiutang(false); if (onChanged) await onChanged(); }}
        />
      )}

      <div className="hidden md:block border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm table-fixed">
          <colgroup>
            <col className="w-[110px]" />
            <col className="w-[90px]" />
            <col className="w-[180px]" />
            <col />
            <col className="w-[130px]" />
            <col className="w-[130px]" />
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
              <th className="px-4 py-3 text-right bg-[#002FA7]/5 text-[#002FA7]">Saldo Kas</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {/* Baris SALDO AWAL — selalu di atas sebagai titik awal perhitungan */}
            <tr data-testid="book-saldo-awal-row" className="bg-[#002FA7]/5 border-b-2 border-[#002FA7]/30">
              <td colSpan={6} className="px-4 py-3">
                <span className="text-xs font-bold uppercase tracking-widest text-[#002FA7]">
                  Saldo Awal {monthLabel(month)}
                </span>
                <span className="ml-2 text-[10px] text-zinc-500 font-mono">(pindahan bulan sebelumnya)</span>
              </td>
              <td className="px-4 py-3 text-right font-mono text-sm font-bold text-[#002FA7] bg-[#002FA7]/10 whitespace-nowrap" data-testid="book-saldo-awal-value">
                {formatIDR(openingBalance)}
              </td>
              <td className="px-4 py-3"></td>
            </tr>
            {loading && <tr><td colSpan={8} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada transaksi non-Kas bulan ini.</td></tr>
            )}
            {filtered.map((t, idx) => (
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
                <td data-testid="book-saldo-kas-cell" className="px-4 py-2.5 text-right font-mono text-xs font-bold text-[#002FA7] bg-[#002FA7]/5 whitespace-nowrap">{formatIDR(balanceByRowIndex[idx])}</td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center justify-end gap-1">
                    {t._virtual ? (
                      <span className="text-[10px] text-zinc-400 font-mono px-2" title="Cash Plaza — virtual dari koleksi Sales. Edit/hapus lewat modul Penjualan.">auto</span>
                    ) : (
                      <>
                        <button data-testid="edit-tx-button" onClick={() => onEdit(t)} disabled={t.auto} className="p-1.5 hover:bg-zinc-100 text-zinc-700 disabled:opacity-30 disabled:cursor-not-allowed" title={t.auto ? "Transaksi otomatis — edit di modul sumbernya" : "Edit"}><Pencil className="w-3.5 h-3.5" /></button>
                        <button data-testid="del-tx-button" onClick={() => onRemove(t)} className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]" title={t.auto ? "Coba hapus (sistem akan cek orphan)" : "Hapus"}><Trash2 className="w-3.5 h-3.5" /></button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!loading && filtered.length > 0 && (
              <tr className="border-t-2 border-zinc-900 bg-zinc-50">
                <td className="px-4 py-3" colSpan={4}>
                  <span className="text-xs font-bold uppercase tracking-widest text-zinc-900">Saldo Akhir {monthLabel(month)}</span>
                  <div className="text-[10px] font-mono text-zinc-500 mt-0.5">
                    Rumus: {formatIDR(openingBalance)} (Saldo Awal) + {formatIDR(totalPemasukan)} (Pemasukan) − {formatIDR(totalPengeluaran)} (Pengeluaran) = {formatIDR(saldoAkhirComputed)}
                  </div>
                </td>
                <td className="px-4 py-3 text-right font-mono font-bold text-[#008A00]">{formatIDR(totalPemasukan)}</td>
                <td className="px-4 py-3 text-right font-mono font-bold text-[#E81123]">{formatIDR(totalPengeluaran)}</td>
                <td className="px-4 py-3 text-right font-mono font-bold text-[#002FA7] bg-[#002FA7]/5 text-lg" data-testid="book-saldo-kas-total">{formatIDR(saldoAkhirComputed)}</td>
                <td className="px-4 py-3"></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Mobile card list */}
      <div className="md:hidden space-y-2">
        <div className="bg-[#002FA7]/5 border border-[#002FA7]/30 px-3 py-2.5">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[#002FA7] font-bold">Saldo Awal {monthLabel(month)}</div>
              <div className="text-[10px] text-zinc-500 font-mono">pindahan bulan sebelumnya</div>
            </div>
            <div className="font-mono font-bold text-sm text-[#002FA7]">{formatIDR(openingBalance)}</div>
          </div>
        </div>

        {loading && (
          <div className="text-center text-zinc-400 text-xs font-mono py-8">Memuat…</div>
        )}
        {!loading && filtered.length === 0 && (
          <div className="text-center text-zinc-400 text-xs font-mono py-8 border border-dashed border-zinc-200">
            Belum ada transaksi non-Kas bulan ini.
          </div>
        )}
        {!loading && filtered.map((t, idx) => (
          <div key={t.id} data-testid="mobile-tx-card" className={`border border-zinc-200 bg-white p-3 ${t._virtual ? "border-l-4 border-l-[#008A00]" : ""}`}>
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-mono text-[10px] text-zinc-500 whitespace-nowrap">{t.date}</span>
                <span className="font-mono text-[11px] font-bold text-zinc-800 bg-zinc-100 px-1.5 py-0.5">{t.account_code}</span>
              </div>
              {t._virtual ? (
                <span className="text-[9px] text-zinc-400 font-mono">auto</span>
              ) : (
                <div className="flex items-center gap-0.5">
                  <button onClick={() => onEdit(t)} disabled={t.auto} className="p-1 hover:bg-zinc-100 text-zinc-700 disabled:opacity-30" data-testid="edit-tx-button-mobile"><Pencil className="w-3.5 h-3.5" /></button>
                  <button onClick={() => onRemove(t)} className="p-1 hover:bg-[#E81123]/10 text-[#E81123]" data-testid="del-tx-button-mobile"><Trash2 className="w-3.5 h-3.5" /></button>
                </div>
              )}
            </div>
            <div className="text-sm font-semibold text-zinc-900">{t.account_name}</div>
            <div className="text-xs text-zinc-600 mt-0.5 break-words">{t.description}</div>
            {t.reference && (
              <div className="text-[10px] font-mono text-zinc-400 mt-0.5">ref: {t.reference}</div>
            )}
            <div className="grid grid-cols-3 gap-2 mt-2 pt-2 border-t border-zinc-100 text-[11px] font-mono">
              <div>
                <div className="text-[9px] uppercase text-zinc-400">In</div>
                <div className="text-[#008A00] font-bold">{t.type === "in" ? formatIDR(t.amount) : "—"}</div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-zinc-400">Out</div>
                <div className="text-[#E81123] font-bold">{t.type === "out" ? formatIDR(t.amount) : "—"}</div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-zinc-400">Saldo</div>
                <div className="text-[#002FA7] font-bold">{formatIDR(balanceByRowIndex[idx])}</div>
              </div>
            </div>
          </div>
        ))}

        {!loading && filtered.length > 0 && (
          <div className="bg-zinc-900 text-white p-3">
            <div className="text-[10px] uppercase tracking-widest text-zinc-300 font-bold">Saldo Akhir {monthLabel(month)}</div>
            <div className="text-[9px] font-mono text-zinc-400 mt-0.5 mb-2">
              {formatIDR(openingBalance)} + {formatIDR(totalPemasukan)} − {formatIDR(totalPengeluaran)}
            </div>
            <div className="grid grid-cols-3 gap-2 text-[11px] font-mono">
              <div>
                <div className="text-[9px] uppercase text-zinc-400">In</div>
                <div className="text-[#00c800] font-bold">{formatIDR(totalPemasukan)}</div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-zinc-400">Out</div>
                <div className="text-[#ff6b6b] font-bold">{formatIDR(totalPengeluaran)}</div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-zinc-400">Total</div>
                <div className="text-white font-bold text-sm">{formatIDR(saldoAkhirComputed)}</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------- Summary Tab (Breakdown per Kategori) ---------- */
function SummaryTab({ summary, month, setMonth, cashPlaza = { amount: 0, count: 0 } }) {
  if (!summary) return <div className="text-zinc-400 text-sm">Memuat…</div>;

  // ATURAN MUTLAK (permintaan user 2026-08-14, TIDAK BOLEH DIUBAH):
  //   PEMASUKAN hanya berisi 5 baris: 301-SPP, 301-BCA, 301-MDR, 301-SPK, Cash Plaza.
  //   Tidak ada baris "Di Luar Total". Tidak ada baris 101. Tidak ada BCA/Mandiri/Shopee family synthetic.
  //   Total Pemasukan = jumlah dari kelima baris tsb.
  const ALLOWED_CODES = ["301-SPP", "301-BCA", "301-MDR", "301-SPK"];
  const byCode = Object.fromEntries((summary.breakdown_in || []).map((r) => [r.account_code, r]));
  const inMain = ALLOWED_CODES
    .map((code) => byCode[code])
    .filter(Boolean);
  if (cashPlaza && cashPlaza.amount > 0) {
    inMain.push({
      account_code: "CASH-PLAZA",
      account_name: "Cash Plaza",
      amount: Number(cashPlaza.amount || 0),
      count: Number(cashPlaza.count || 0),
    });
  }
  const totalInAdjusted = inMain.reduce((s, r) => s + Number(r.amount || 0), 0);
  const maxIn = Math.max(...inMain.map((r) => r.amount), 1);
  const maxOut = Math.max(...(summary.breakdown_out || []).map((r) => r.amount), 1);
  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <MonthNav value={month} onChange={setMonth} testIdPrefix="summary-month" />
        <div className="text-xs text-zinc-500 font-mono ml-2">Periode: {summary.period_start} s/d {summary.period_end}</div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <BreakdownCard
          title="Pemasukan"
          color="#008A00"
          rows={inMain}
          total={totalInAdjusted}
          max={maxIn}
        />
        <BreakdownCard title="Pengeluaran" color="#E81123" rows={summary.breakdown_out || []} total={summary.total_out} max={maxOut} />
      </div>
      <div className="mt-6 bg-zinc-900 text-white p-6 font-mono grid grid-cols-2 md:grid-cols-4 gap-4">
        <SummaryStat label="Saldo Awal" value={summary.opening_balance} />
        <SummaryStat label="Pemasukan" value={totalInAdjusted} positive />
        <SummaryStat label="Pengeluaran" value={summary.total_out} negative />
        <SummaryStat label="Saldo Akhir" value={summary.closing_balance} big />
      </div>
    </div>
  );
}

function BreakdownCard({ title, color, rows, total, max, standaloneRows = [], standaloneNote = "" }) {
  return (
    <div className="border border-zinc-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3 pb-2 border-b border-zinc-200">
        <div className="text-xs uppercase tracking-widest font-bold text-zinc-700">{title}</div>
        <div data-testid={`breakdown-total-${title.toLowerCase()}`} className="font-mono font-bold text-lg" style={{ color }}>{formatIDR(total)}</div>
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

      {standaloneRows.length > 0 && (
        <div className="mt-4 pt-3 border-t border-dashed border-zinc-300">
          <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-bold mb-2">Di Luar Total</div>
          {standaloneNote && (
            <div className="text-[10px] font-mono text-zinc-500 mb-2 leading-relaxed">{standaloneNote}</div>
          )}
          <div className="space-y-2">
            {standaloneRows.map((r) => (
              <div key={r.account_code} data-testid="breakdown-standalone-row" className="flex justify-between text-xs items-baseline">
                <span><span className="font-mono text-zinc-500 mr-2">{r.account_code}</span>{r.account_name}</span>
                <span className="font-mono font-bold text-zinc-700">{formatIDR(r.amount)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
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
function TxModal({ initial, accounts, currentTab, onClose, onSaved }) {
  const isEdit = initial && initial.id;
  const forcedType = initial?.type;
  // Akun 102-PTP (Piutang Perusahaan) HANYA boleh dipakai saat tab aktif = Jurnal Akuntansi (tab==="book").
  // Di tab Buku Kas (tab==="journal") atau tab lain, sembunyikan dari picker.
  const eligible = accounts.filter((a) => {
    if (a.active === false) return false;
    if (a.type !== forcedType) return false;
    if (a.code === "102-PTP" && currentTab !== "book") return false;
    return true;
  });
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

/* ---------- Piutang Bayar Modal (KHUSUS Jurnal Akuntansi — akun 102-PTP) ---------- */
/* SATU-satunya efek: POST /cashbook/piutang/bayar → insert 1 baris tx type=out di akun 102-PTP.
   TIDAK menyentuh logic Buku Kas. Filter Buku Kas (`filteredJournal`) sudah exclude 102-PTP.  */
function PiutangBayarModal({ onClose, onSaved }) {
  const [form, setForm] = useState({
    date: todayISO(),
    amount: 0,
    description: "",
    reference: "",
  });
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (Number(form.amount) <= 0) { toast.error("Jumlah pelunasan harus > 0"); return; }
    setSaving(true);
    try {
      await api.post("/cashbook/piutang/bayar", {
        date: form.date,
        amount: Number(form.amount),
        description: form.description.trim() || "Pelunasan Piutang Perusahaan",
        reference: form.reference.trim() || null,
      });
      toast.success("Pelunasan piutang tercatat");
      await onSaved();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan pelunasan");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white border border-zinc-300 w-full max-w-lg" data-testid="piutang-bayar-modal">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 flex items-center justify-center bg-[#002FA7]">
              <ArrowDownCircle className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Jurnal Akuntansi</div>
              <div className="font-heading text-xl font-bold text-zinc-900">Bayar Piutang Perusahaan</div>
            </div>
          </div>
          <button onClick={onClose} data-testid="close-piutang-bayar-modal" className="p-1.5 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-4">
          <div className="text-[11px] font-mono text-zinc-500 bg-zinc-50 border border-zinc-200 p-2.5">
            <b className="text-zinc-900">102-PTP · Piutang Perusahaan</b><br/>
            Aksi ini insert 1 baris transaksi <b>type=out</b> ke akun ini. Menurunkan total piutang di Jurnal Akuntansi. Tidak muncul di Buku Kas.
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] uppercase tracking-widest text-zinc-500 font-semibold mb-1">Tanggal</label>
              <input
                type="date"
                value={form.date}
                onChange={(e) => setForm({ ...form, date: e.target.value })}
                data-testid="piutang-bayar-date"
                className="w-full rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-widest text-zinc-500 font-semibold mb-1">Jumlah (Rp)</label>
              <input
                type="number"
                min="0"
                step="1"
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                data-testid="piutang-bayar-amount"
                className="w-full rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
              />
            </div>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-widest text-zinc-500 font-semibold mb-1">Keterangan</label>
            <input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Pelunasan Piutang Perusahaan"
              data-testid="piutang-bayar-desc"
              className="w-full rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-widest text-zinc-500 font-semibold mb-1">Referensi (opsional)</label>
            <input
              value={form.reference}
              onChange={(e) => setForm({ ...form, reference: e.target.value })}
              placeholder="No. nota, no. bukti, dsb."
              data-testid="piutang-bayar-ref"
              className="w-full rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
            />
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="rounded-none border border-zinc-300 bg-white text-zinc-700 px-4 py-2 text-sm hover:bg-zinc-50" data-testid="piutang-bayar-cancel">Batal</button>
            <button type="submit" disabled={saving} className="rounded-none bg-[#002FA7] text-white px-4 py-2 text-sm font-bold uppercase tracking-wider hover:bg-[#001F7A] disabled:opacity-50" data-testid="piutang-bayar-submit">
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
function JournalTab({ month, setMonth, search, setSearch, txData, filtered, loading, onEdit, onRemove, kasbonOpen, onCashChanged }) {
  const [showAdjustOnly, setShowAdjustOnly] = useState(false);
  // Saldo Awal diambil dari backend (auto carry-over + override via menu "Kunci Saldo Bulan").
  // Kalau ada override langsung untuk bulan ini → pakai itu.
  // Kalau tidak → cascade otomatis dari closing bulan sebelumnya.
  const isForcedOpening = false; // dipertahankan untuk backward-compat rendering
  // Buku Kas (tab): HARD FILTER — hanya transaksi akun 101 Kas Utama.
  const kasTxAll = filtered;
  const openingBalance = Number(txData.opening_balance || 0);
  const adjustCount = kasTxAll.filter((t) => t.reference === "ADJUSTMENT").length;

  // Purge ALL adjustment transactions — nuclear cleanup.
  // Backend akan hapus semua cash_transactions dgn reference="ADJUSTMENT".
  const purgeAdjustments = async () => {
    if (adjustCount === 0) {
      toast.info("Tidak ada jurnal penyesuaian untuk dihapus.");
      return;
    }
    const msg1 = `HAPUS SEMUA transaksi penyesuaian saldo?\n\nAksi ini akan menghapus ${adjustCount} jurnal dengan ref='ADJUSTMENT' di bulan ini + bulan-bulan lain.\n\nSetelah dihapus, saldo real-time akan BERUBAH. Anda dapat set ulang Saldo Awal manual via tombol "Saldo Awal" di atas.\n\nLanjutkan?`;
    if (!window.confirm(msg1)) return;
    const c = window.prompt('Ketik "HAPUS PENYESUAIAN" untuk konfirmasi:');
    if (c !== "HAPUS PENYESUAIAN") { toast.error("Dibatalkan — konfirmasi tidak cocok."); return; }
    try {
      const res = await api.post("/cashbook/purge-adjustments");
      toast.success(`${res.data.deleted_count} jurnal penyesuaian dihapus. Silakan cek Saldo Awal.`);
      if (onCashChanged) await onCashChanged();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal");
    }
  };
  const kasTx = showAdjustOnly ? kasTxAll.filter((t) => t.reference === "ADJUSTMENT") : kasTxAll;
  // Recompute running balance: Saldo Awal + Kredit − Debet (per baris)
  // NOTE: Saldo dihitung dari FULL kasTxAll (bukan filtered) supaya angka Saldo tetap akurat
  //       ketika user filter "Adjustment Only".
  const jurnalAll = (() => {
    let running = openingBalance;
    return kasTxAll.map((t) => {
      running = t.type === "in" ? running + Number(t.amount || 0) : running - Number(t.amount || 0);
      return { ...t, balance: running };
    });
  })();
  const jurnal = showAdjustOnly ? jurnalAll.filter((t) => t.reference === "ADJUSTMENT") : jurnalAll;
  const totalKredit = kasTx.reduce((s, t) => s + (t.type === "in" ? Number(t.amount) : 0), 0);
  const totalDebet = kasTx.reduce((s, t) => s + (t.type === "out" ? Number(t.amount) : 0), 0);
  // Kasbon Belum Lunas — dianggap pengurang saldo kas nyata (uang sudah dikeluarkan tapi belum lunas).
  // STRICT filter via isOpenKasbon: hanya status === 'PENDING' (backend normalized).
  // Kasbon LUNAS/PAID otomatis tersembunyi — hanya BELUM LUNAS yang tampil di sini.
  const kasbonList = (kasbonOpen?.items || []).filter(isOpenKasbon).slice().sort((a, b) => (a.date || "").localeCompare(b.date || ""));
  const kasbonTotal = kasbonList.reduce((s, k) => s + Number(k.amount || 0), 0);
  const runningAfterTx = jurnal.length > 0 ? jurnal[jurnal.length - 1].balance : openingBalance;
  const kasbonRows = (() => {
    let running = runningAfterTx;
    return kasbonList.map((k) => {
      running = running - Number(k.amount || 0);
      return { ...k, running_balance: running };
    });
  })();
  const closingBalance = openingBalance + totalKredit - totalDebet - kasbonTotal;
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 md:gap-3 mb-4">
        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          <MonthNav value={month} onChange={setMonth} testIdPrefix="journal-month" />
          <div className="relative flex-1 md:flex-none">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Cari keterangan / akun / ref…"
              data-testid="journal-search"
              className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-full md:w-80 focus:border-[#002FA7] focus:outline-none"
            />
          </div>
          <span className="text-[10px] font-bold uppercase tracking-widest bg-[#002FA7]/10 text-[#002FA7] px-2.5 py-1.5 border border-[#002FA7]/30 whitespace-nowrap hidden md:inline">Kredit: Akun 101 · Debet: Semua Akun</span>
          {adjustCount > 0 && (
            <>
              <button
                type="button"
                data-testid="filter-adjustment-toggle"
                onClick={() => setShowAdjustOnly((v) => !v)}
                className={`text-[10px] font-bold uppercase tracking-widest px-2.5 py-1.5 border inline-flex items-center gap-1.5 whitespace-nowrap ${
                  showAdjustOnly
                    ? "bg-[#002FA7] text-white border-[#002FA7]"
                    : "bg-white text-[#002FA7] border-[#002FA7]/40 hover:bg-[#002FA7]/5"
                }`}
                title={showAdjustOnly ? "Klik untuk tampilkan semua transaksi" : "Filter hanya jurnal penyesuaian"}
              >
                <Target className="w-3 h-3" />
                {showAdjustOnly ? `Adjustment Only (${adjustCount})` : `Adjustment: ${adjustCount}`}
              </button>
              <button
                type="button"
                data-testid="purge-adjustments-btn"
                onClick={purgeAdjustments}
                className="text-[10px] font-bold uppercase tracking-widest px-2.5 py-1.5 border inline-flex items-center gap-1.5 whitespace-nowrap bg-white text-[#E81123] border-[#E81123]/40 hover:bg-[#E81123]/5"
                title="Hapus SEMUA jurnal penyesuaian"
              >
                <Trash2 className="w-3 h-3" /> <span className="hidden sm:inline">Hapus Semua Penyesuaian</span><span className="sm:hidden">Hapus Penyesuaian</span>
              </button>
            </>
          )}
        </div>
        <div className="text-[11px] md:text-xs text-zinc-500 font-mono w-full md:w-auto">
          {jurnal.length} jurnal{showAdjustOnly ? " (penyesuaian saja)" : ""} · Debet <b className="text-[#E81123]">{formatIDR(totalDebet)}</b> · Kredit <b className="text-[#008A00]">{formatIDR(totalKredit)}</b>
          {kasbonList.length > 0 && !showAdjustOnly && (
            <> · Kasbon <b className="text-[#F97316]">{formatIDR(kasbonTotal)}</b></>
          )}
        </div>
      </div>

      <div className="hidden md:block border border-zinc-900 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-900 text-white text-[11px] font-bold uppercase tracking-widest">
              <th className="px-3 py-3 border-r border-zinc-700">Kode Akun</th>
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
              <td colSpan={4} className="px-3 py-2.5">
                <span className="text-xs font-bold uppercase tracking-widest text-[#002FA7]">Saldo Akhir {prevMonthLabel(month)}</span>
              </td>
              <td className="px-3 py-2.5"></td>
              <td className="px-3 py-2.5"></td>
              <td className="px-3 py-2.5 text-right font-mono font-bold text-[#002FA7]" data-testid="prev-month-closing">
                {formatIDR(openingBalance)}
              </td>
              <td className="px-3 py-2.5"></td>
            </tr>
            {loading && <tr><td colSpan={8} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {!loading && jurnal.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada arus kas bulan ini.</td></tr>
            )}
            {jurnal.map((t) => {
              const isAdjustment = t.reference === "ADJUSTMENT";
              const rowBg = isAdjustment
                ? (t.type === "in" ? "bg-[#008A00]/10" : "bg-[#E81123]/10")
                : (t.auto ? "bg-amber-50/40" : "");
              return (
              <tr key={t.id} data-testid="journal-row" data-adjustment={isAdjustment ? "true" : "false"} className={`border-b border-zinc-100 hover:bg-zinc-50 ${rowBg}`}>
                <td className="px-3 py-2.5 font-mono text-xs font-bold text-zinc-700 whitespace-nowrap">{t.account_code}</td>
                <td className="px-3 py-2.5 text-xs">
                  {t.account_code === "101" ? "Kas" : t.account_name}
                  {t.auto && <span className="ml-2 text-[9px] uppercase tracking-widest font-bold text-amber-700 inline-flex items-center gap-1"><Lock className="w-2.5 h-2.5" /> Auto</span>}
                  {isAdjustment && (
                    <span className={`ml-2 text-[9px] uppercase tracking-widest font-bold inline-flex items-center gap-1 px-1.5 py-0.5 border ${
                      t.type === "in"
                        ? "bg-[#008A00] text-white border-[#008A00]"
                        : "bg-[#E81123] text-white border-[#E81123]"
                    }`}>
                      <Target className="w-2.5 h-2.5" /> Penyesuaian
                    </span>
                  )}
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
                    {t._virtual ? (
                      <span className="text-[10px] uppercase tracking-widest text-zinc-400 italic px-2">Sistem</span>
                    ) : (
                      <>
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
                      </>
                    )}
                  </div>
                </td>
              </tr>
              );
            })}
            {kasbonRows.length > 0 && (
              <>
                <tr className="border-t border-dashed border-[#F97316]/40 bg-[#F97316]/5">
                  <td colSpan={8} className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-[#F97316]">
                    · Kasbon Sementara (belum lunas)
                  </td>
                </tr>
                {kasbonRows.map((k) => (
                  <tr key={`kasbon-${k.id}`} data-testid="journal-kasbon-row" className="border-b border-zinc-100 hover:bg-[#F97316]/10 bg-[#F97316]/5">
                    <td className="px-3 py-2.5 font-mono text-xs font-bold text-[#F97316] whitespace-nowrap">KASBON</td>
                    <td className="px-3 py-2.5 text-xs">
                      Kasbon · {k.name}
                      <span className="ml-2 text-[9px] uppercase tracking-widest font-bold text-[#F97316]">pending</span>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">{k.date}</td>
                    <td className="px-3 py-2.5 text-xs">
                      <div className="text-zinc-700">{k.description || "Uang muka staff — belum dilunasi"}</div>
                      <div className="text-[10px] font-mono text-zinc-400 mt-0.5">ref: KASBON-{String(k.id).slice(0, 8)}</div>
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-xs bg-[#F97316]/10">
                      <span className="text-[#F97316] font-bold">{formatIDR(k.amount)}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-xs bg-[#008A00]/5">
                      <span className="text-zinc-300">—</span>
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-xs font-bold text-[#F97316]">{formatIDR(k.running_balance)}</td>
                    <td className="px-3 py-2.5 text-center">
                      <span className="text-[9px] font-mono uppercase text-zinc-400">tab Kasbon</span>
                    </td>
                  </tr>
                ))}
              </>
            )}
            {!loading && (jurnal.length > 0 || isForcedOpening) && (
              <>
                <tr className="border-t-2 border-zinc-900 bg-zinc-50">
                  <td colSpan={4} className="px-3 py-3">
                    <span className="text-xs font-bold uppercase tracking-widest text-zinc-900">Total Kas Utama (sebelum Kasbon)</span>
                  </td>
                  <td className="px-3 py-3 text-right font-mono font-bold text-[#E81123]">{formatIDR(totalDebet)}</td>
                  <td className="px-3 py-3 text-right font-mono font-bold text-[#008A00]">
                    {formatIDR(totalKredit + (isForcedOpening ? openingBalance : 0))}
                    {isForcedOpening && (
                      <div className="text-[10px] font-normal text-zinc-500 mt-0.5">
                        (Kredit {formatIDR(totalKredit)} + Saldo Awal {formatIDR(openingBalance)})
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-3 text-right font-mono font-bold text-zinc-900">
                    {formatIDR(openingBalance + totalKredit - totalDebet)}
                  </td>
                  <td className="px-3 py-3"></td>
                </tr>
                {kasbonTotal > 0 && (
                  <tr className="bg-[#F97316]/10 border-b border-[#F97316]/30">
                    <td colSpan={4} className="px-3 py-2.5">
                      <span className="text-xs font-bold uppercase tracking-widest text-[#F97316]">− Kasbon Belum Lunas</span>
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono font-bold text-[#F97316]">{formatIDR(kasbonTotal)}</td>
                    <td className="px-3 py-2.5"></td>
                    <td className="px-3 py-2.5 text-right font-mono font-bold text-[#F97316]">−{formatIDR(kasbonTotal)}</td>
                    <td className="px-3 py-2.5"></td>
                  </tr>
                )}
                <tr className="border-t-2 border-zinc-900 bg-zinc-900 text-white">
                  <td colSpan={6} className="px-3 py-3">
                    <span className="text-xs font-bold uppercase tracking-widest">Saldo Akhir (setelah Kasbon)</span>
                  </td>
                  <td className="px-3 py-3 text-right font-mono font-bold text-lg" data-testid="journal-closing-balance">{formatIDR(closingBalance)}</td>
                  <td className="px-3 py-3"></td>
                </tr>
              </>
            )}
          </tbody>
        </table>
      </div>

      {/* Mobile card list */}
      <div className="md:hidden space-y-2">
        <div className="bg-[#002FA7]/5 border border-[#002FA7]/30 px-3 py-2.5">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[#002FA7] font-bold">Saldo Awal {monthLabel(month)}</div>
              <div className="text-[10px] text-zinc-500 font-mono">Akun 101 · pindahan dari bulan sebelumnya</div>
            </div>
            <div className="font-mono font-bold text-sm text-[#002FA7]">{formatIDR(openingBalance)}</div>
          </div>
        </div>

        {loading && (
          <div className="text-center text-zinc-400 text-xs font-mono py-8">Memuat…</div>
        )}
        {!loading && jurnal.length === 0 && (
          <div className="text-center text-zinc-400 text-xs font-mono py-8 border border-dashed border-zinc-200">
            Belum ada arus kas bulan ini.
          </div>
        )}
        {!loading && jurnal.map((t) => (
          <div key={t.id} data-testid="mobile-journal-card" className={`border border-zinc-200 bg-white p-3 ${t.reference === "ADJUSTMENT" ? "border-l-4 border-l-[#002FA7]" : ""}`}>
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-mono text-[10px] text-zinc-500 whitespace-nowrap">{t.date}</span>
                <span className="font-mono text-[11px] font-bold text-zinc-800 bg-zinc-100 px-1.5 py-0.5">{t.account_code}</span>
              </div>
              <div className="flex items-center gap-0.5">
                <button onClick={() => onEdit(t)} disabled={t.auto} className="p-1 hover:bg-zinc-100 text-zinc-700 disabled:opacity-30" data-testid="edit-journal-mobile"><Pencil className="w-3.5 h-3.5" /></button>
                <button onClick={() => onRemove(t)} className="p-1 hover:bg-[#E81123]/10 text-[#E81123]" data-testid="del-journal-mobile"><Trash2 className="w-3.5 h-3.5" /></button>
              </div>
            </div>
            <div className="text-sm font-semibold text-zinc-900">{t.account_name}</div>
            <div className="text-xs text-zinc-600 mt-0.5 break-words">{t.description}</div>
            {t.reference && (
              <div className="text-[10px] font-mono text-zinc-400 mt-0.5">ref: {t.reference}</div>
            )}
            <div className="grid grid-cols-3 gap-2 mt-2 pt-2 border-t border-zinc-100 text-[11px] font-mono">
              <div>
                <div className="text-[9px] uppercase text-zinc-400">Kredit</div>
                <div className="text-[#008A00] font-bold">{t.type === "in" ? formatIDR(t.amount) : "—"}</div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-zinc-400">Debet</div>
                <div className="text-[#E81123] font-bold">{t.type === "out" ? formatIDR(t.amount) : "—"}</div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-zinc-400">Saldo</div>
                <div className="text-zinc-900 font-bold">{formatIDR(t.balance)}</div>
              </div>
            </div>
          </div>
        ))}

        {!showAdjustOnly && kasbonRows.length > 0 && (
          <>
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#F97316] mt-2 mb-1">
              · Kasbon Sementara (belum lunas)
            </div>
            {kasbonRows.map((k) => (
              <div key={`m-kasbon-${k.id}`} data-testid="mobile-kasbon-card" className="border border-[#F97316]/40 bg-[#F97316]/5 p-3">
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-[#F97316] whitespace-nowrap">{k.date}</span>
                    <span className="font-mono text-[11px] font-bold text-[#F97316] bg-white px-1.5 py-0.5 border border-[#F97316]/30">KASBON</span>
                  </div>
                  <span className="text-[9px] uppercase tracking-widest font-bold text-[#F97316]">pending</span>
                </div>
                <div className="text-sm font-semibold text-zinc-900">Kasbon · {k.name}</div>
                <div className="text-xs text-zinc-600 mt-0.5 break-words">{k.description || "Uang muka staff — belum dilunasi"}</div>
                <div className="text-[10px] font-mono text-zinc-400 mt-0.5">ref: KASBON-{String(k.id).slice(0, 8)}</div>
                <div className="grid grid-cols-3 gap-2 mt-2 pt-2 border-t border-[#F97316]/20 text-[11px] font-mono">
                  <div>
                    <div className="text-[9px] uppercase text-zinc-400">Kasbon</div>
                    <div className="text-[#F97316] font-bold">{formatIDR(k.amount)}</div>
                  </div>
                  <div>
                    <div className="text-[9px] uppercase text-zinc-400">—</div>
                    <div className="text-zinc-300">—</div>
                  </div>
                  <div>
                    <div className="text-[9px] uppercase text-zinc-400">Saldo</div>
                    <div className="text-[#F97316] font-bold">{formatIDR(k.running_balance)}</div>
                  </div>
                </div>
              </div>
            ))}
          </>
        )}

        {!loading && jurnal.length > 0 && (
          <>
            <div className="bg-zinc-50 border-2 border-zinc-900 p-3 mt-2">
              <div className="text-[10px] uppercase tracking-widest text-zinc-800 font-bold mb-2">Total Kas Utama (sebelum Kasbon)</div>
              <div className="grid grid-cols-3 gap-2 text-[11px] font-mono">
                <div>
                  <div className="text-[9px] uppercase text-zinc-400">Debet</div>
                  <div className="text-[#E81123] font-bold">{formatIDR(totalDebet)}</div>
                </div>
                <div>
                  <div className="text-[9px] uppercase text-zinc-400">Kredit</div>
                  <div className="text-[#008A00] font-bold">{formatIDR(totalKredit)}</div>
                </div>
                <div>
                  <div className="text-[9px] uppercase text-zinc-400">Saldo</div>
                  <div className="text-zinc-900 font-bold">{formatIDR(runningAfterTx)}</div>
                </div>
              </div>
            </div>
            {kasbonRows.length > 0 && !showAdjustOnly && (
              <div className="bg-[#F97316]/10 border border-[#F97316]/30 p-3">
                <div className="flex items-center justify-between">
                  <div className="text-[10px] uppercase tracking-widest text-[#F97316] font-bold">− Kasbon Belum Lunas</div>
                  <div className="font-mono font-bold text-[#F97316]">−{formatIDR(kasbonTotal)}</div>
                </div>
              </div>
            )}
            <div className="bg-zinc-900 text-white p-3">
              <div className="text-[10px] uppercase tracking-widest text-zinc-300 font-bold">Saldo Akhir (setelah Kasbon)</div>
              <div className="font-mono font-bold text-lg mt-1" data-testid="mobile-journal-closing">{formatIDR(closingBalance)}</div>
            </div>
          </>
        )}
      </div>

      <div className="mt-3 text-[11px] text-zinc-500">
        <b>Konvensi:</b> Debet = pengeluaran · Kredit = pemasukan akun 101 · <b className="text-[#F97316]">Kasbon</b> = uang muka staff yg belum lunas (kas fisik berkurang meski belum jadi expense resmi). Rumus: <b>Saldo Akhir = Saldo Awal + Kredit − Debet − Kasbon Belum Lunas</b>.
        Auto-sync dari modul <b>Pembelian</b>, <b>Penjualan/Kasir</b>, <b>Kas Operasional</b>, dan <b>Kasbon Sementara</b>. Kasbon LUNAS tidak ditampilkan — kelola di tab <b>Kasbon Sementara</b>.
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

  const bulkSettleAll = async () => {
    const totalOpen = Number(data.total_open || 0);
    if (totalOpen <= 0) {
      toast.info("Tidak ada kasbon PENDING untuk dilunaskan.");
      return;
    }
    const msg1 = `Anda akan menandai SEMUA kasbon PENDING sebagai LUNAS sekaligus.\n\nTotal: ${formatIDR(totalOpen)}\n\nAksi ini TIDAK memotong kas otomatis (untuk data lama). Lanjutkan?`;
    if (!window.confirm(msg1)) return;
    const confirm2 = window.prompt('Ketik "LUNAS SEMUA" (huruf besar) untuk konfirmasi:');
    if (confirm2 !== "LUNAS SEMUA") {
      toast.error("Dibatalkan — konfirmasi tidak cocok.");
      return;
    }
    try {
      const res = await api.post("/cashbook/kasbon/settle-all-pending");
      toast.success(`${res.data.settled_count} kasbon ditandai LUNAS`);
      await load();
      if (onCashChanged) await onCashChanged();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal");
    }
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

      <div className="flex flex-wrap items-center justify-between gap-2 md:gap-3 mb-4">
        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          <MonthNav value={month} onChange={setMonth} testIdPrefix="kasbon-month" />
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} data-testid="kasbon-status-filter"
            className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm focus:border-[#002FA7] focus:outline-none">
            <option value="">Semua Status</option>
            <option value="open">Belum Lunas</option>
            <option value="settled">Sudah Lunas</option>
          </select>
          <div className="relative flex-1 md:flex-none w-full md:w-auto">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama / keterangan…" data-testid="kasbon-search"
              className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-full md:w-72 focus:border-[#002FA7] focus:outline-none" />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          {Number(data.total_open || 0) > 0 && (
            <button
              data-testid="kasbon-bulk-settle-all"
              onClick={bulkSettleAll}
              className="rounded-none bg-white text-[#008A00] border border-[#008A00] px-3 md:px-4 py-2 md:py-2.5 text-[11px] md:text-sm font-bold uppercase tracking-wider hover:bg-[#008A00]/5 inline-flex items-center gap-2 flex-1 md:flex-none justify-center"
              title="Tandai SEMUA kasbon PENDING → LUNAS (tanpa memotong kas). Untuk membersihkan data lama."
            >
              <CheckCircle2 className="w-4 h-4" /> <span className="hidden sm:inline">Tandai Semua Lunas</span><span className="sm:hidden">Lunas Semua</span>
            </button>
          )}
          <button data-testid="kasbon-add-button" onClick={() => { setEditing(null); setOpenForm(true); }}
            className="rounded-none bg-[#002FA7] text-white px-3 md:px-5 py-2 md:py-2.5 text-[11px] md:text-sm font-bold uppercase tracking-wider hover:bg-[#001E7A] inline-flex items-center gap-2 flex-1 md:flex-none justify-center">
            <Plus className="w-4 h-4" /> Tambah Kasbon
          </button>
        </div>
      </div>

      {/* Desktop table */}
      <div className="hidden md:block border border-zinc-200 bg-white overflow-x-auto">
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
            {filtered.map((k) => {
              // Backend selalu normalize status ke "PENDING" (belum lunas) atau "PAID" (lunas).
              // Fallback: legacy value "open"/"settled" tetap didukung (case-insensitive).
              const _s = String(k.status || "").trim().toUpperCase();
              const isPaid = _s === "PAID" || _s === "SETTLED";
              return (
              <tr key={k.id} data-testid="kasbon-row" className={`border-b border-zinc-100 hover:bg-zinc-50 ${isPaid ? "opacity-60" : ""}`}>
                <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">{k.date}</td>
                <td className="px-3 py-2.5 text-sm font-semibold text-zinc-900">{k.name}</td>
                <td className="px-3 py-2.5 text-xs text-zinc-600">{k.description || "—"}</td>
                <td className="px-3 py-2.5 text-right font-mono text-sm font-bold text-zinc-900">{formatIDR(k.amount)}</td>
                <td className="px-3 py-2.5">
                  {isPaid ? (
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
                    {!isPaid ? (
                      <button data-testid="kasbon-settle-btn" onClick={() => settle(k)} className="p-1.5 hover:bg-[#008A00]/10 text-[#008A00] border border-[#008A00]/30 rounded" title="Tandai Lunas — ubah status jadi PAID">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      </button>
                    ) : (
                      <button data-testid="kasbon-reopen-btn" onClick={() => reopen(k)} className="p-1.5 hover:bg-amber-100 text-amber-700" title="Buka kembali (batalkan pelunasan)">
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
              );
            })}
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

      {/* Mobile card list */}
      <div className="md:hidden space-y-2">
        {loading && <div className="text-center text-zinc-400 text-xs font-mono py-8">Memuat…</div>}
        {!loading && filtered.length === 0 && (
          <div className="text-center text-zinc-400 text-xs font-mono py-8 border border-dashed border-zinc-200">Belum ada kasbon.</div>
        )}
        {!loading && filtered.map((k) => {
          const _s = String(k.status || "").trim().toUpperCase();
          const isPaid = _s === "PAID" || _s === "SETTLED";
          return (
            <div key={k.id} data-testid="mobile-kasbon-item" className={`border bg-white p-3 ${isPaid ? "border-zinc-200 opacity-70" : "border-l-4 border-l-[#F97316] border-zinc-200"}`}>
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono text-[10px] text-zinc-500 whitespace-nowrap">{k.date}</span>
                  {isPaid ? (
                    <span className="inline-flex items-center gap-1 text-[9px] uppercase tracking-widest font-bold text-[#008A00] bg-[#008A00]/10 px-1.5 py-0.5">
                      <CheckCircle2 className="w-2.5 h-2.5" /> Lunas
                    </span>
                  ) : (
                    <span className="text-[9px] uppercase tracking-widest font-bold text-[#E81123] bg-[#E81123]/10 px-1.5 py-0.5">Belum Lunas</span>
                  )}
                </div>
                <div className="flex items-center gap-0.5">
                  {!isPaid ? (
                    <button onClick={() => settle(k)} className="p-1 hover:bg-[#008A00]/10 text-[#008A00]" data-testid="kasbon-settle-mobile" title="Tandai Lunas"><CheckCircle2 className="w-3.5 h-3.5" /></button>
                  ) : (
                    <button onClick={() => reopen(k)} className="p-1 hover:bg-amber-100 text-amber-700" data-testid="kasbon-reopen-mobile" title="Buka kembali"><RotateCcw className="w-3.5 h-3.5" /></button>
                  )}
                  <button onClick={() => { setEditing(k); setOpenForm(true); }} className="p-1 hover:bg-zinc-100 text-zinc-700" data-testid="kasbon-edit-mobile"><Pencil className="w-3.5 h-3.5" /></button>
                  <button onClick={() => remove(k)} className="p-1 hover:bg-[#E81123]/10 text-[#E81123]" data-testid="kasbon-del-mobile"><Trash2 className="w-3.5 h-3.5" /></button>
                </div>
              </div>
              <div className="text-sm font-semibold text-zinc-900">{k.name}</div>
              <div className="text-xs text-zinc-600 mt-0.5 break-words">{k.description || "—"}</div>
              <div className="mt-2 pt-2 border-t border-zinc-100 flex items-center justify-between">
                <div className="text-[9px] uppercase text-zinc-400">Jumlah</div>
                <div className="font-mono font-bold text-base text-zinc-900">{formatIDR(k.amount)}</div>
              </div>
            </div>
          );
        })}
        {!loading && filtered.length > 0 && (
          <div className="bg-zinc-900 text-white p-3 mt-2">
            <div className="text-[10px] uppercase tracking-widest text-zinc-300 font-bold">
              TOTAL {filterStatus === "settled" ? "LUNAS" : filterStatus === "open" ? "BELUM LUNAS" : "SEMUA KASBON"}
            </div>
            <div className="font-mono font-bold text-lg mt-1">
              {formatIDR(filtered.reduce((s, k) => s + Number(k.amount || 0), 0))}
            </div>
          </div>
        )}
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


function AdjustBalanceModal({ currentBalance, onClose, onSaved }) {
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const numeric = Number(String(target).replace(/[^\d.-]/g, "")) || 0;
  const delta = Math.round((numeric - Number(currentBalance || 0)) * 100) / 100;

  const submit = async (e) => {
    e.preventDefault();
    if (!target || numeric <= 0) {
      toast.error("Isi target saldo (Rupiah)");
      return;
    }
    if (Math.abs(delta) < 0.01) {
      toast.info("Saldo saat ini sudah sama dengan target");
      return;
    }
    if (!window.confirm(
      `Buat jurnal penyesuaian ${delta > 0 ? "MASUK" : "KELUAR"} sebesar Rp ${Math.abs(delta).toLocaleString("id-ID")}?\n\n` +
      `Saldo saat ini: Rp ${Number(currentBalance).toLocaleString("id-ID")}\n` +
      `Target baru:   Rp ${numeric.toLocaleString("id-ID")}\n\n` +
      `Jurnal ini akan tercatat permanen di Buku Kas dengan referensi ADJUSTMENT.`
    )) return;
    setSaving(true);
    try {
      const { data } = await api.post("/cashbook/adjust-balance", { target_balance: numeric, note });
      if (data.no_op) {
        toast.info(data.message || "Tidak ada penyesuaian dibuat");
      } else {
        toast.success(
          `Saldo diperbarui: ${formatIDR(data.current_balance)} → ${formatIDR(data.new_balance)} (delta ${delta > 0 ? "+" : ""}${formatIDR(delta)})`
        );
      }
      await onSaved();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal update saldo");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" data-testid="adjust-balance-modal">
      <div className="bg-white w-full max-w-md p-6 border border-zinc-300">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-[#002FA7] font-bold flex items-center gap-1">
              <Target className="w-3 h-3" /> Jurnal Penyesuaian
            </div>
            <h2 className="font-heading text-xl font-bold text-zinc-900 mt-0.5">Update Saldo Kas Terakhir</h2>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-zinc-100" aria-label="Tutup"><X className="w-5 h-5" /></button>
        </div>

        <div className="bg-zinc-50 border border-zinc-200 p-3 mb-4">
          <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Saldo Kas Real-time Sekarang</div>
          <div className="font-heading text-2xl font-bold text-zinc-900 font-mono mt-1">{formatIDR(currentBalance)}</div>
          <div className="text-[11px] text-zinc-500 mt-1">Formula: Saldo Awal + Σ(Kredit akun 101) − Σ(Debet semua akun) − Kasbon Belum Lunas</div>
        </div>

        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="block text-[10px] uppercase tracking-widest text-zinc-500 font-bold mb-1">Target Saldo Baru (Rp)</label>
            <input
              type="number" step="1" min="0" required autoFocus
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="Contoh: 10921218"
              data-testid="adjust-balance-target"
              className={inputCls + " font-mono text-lg font-bold text-right"}
            />
            {target && (
              <div className={`mt-2 text-xs font-mono ${delta > 0 ? "text-[#008A00]" : delta < 0 ? "text-[#E81123]" : "text-zinc-500"}`}>
                Delta: {delta > 0 ? "+" : ""}{formatIDR(delta)} — Akan buat 1 jurnal {delta > 0 ? "MASUK (Kredit akun 101)" : delta < 0 ? "KELUAR (Debet akun 599-ADJ)" : "no-op"}
              </div>
            )}
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-widest text-zinc-500 font-bold mb-1">Catatan (opsional)</label>
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Contoh: Rekonsiliasi kas fisik tgl 3 Agu"
              data-testid="adjust-balance-note"
              className={inputCls}
            />
          </div>
          <div className="flex justify-end gap-2 pt-3 border-t border-zinc-200">
            <button type="button" onClick={onClose} className="rounded-none border border-zinc-300 bg-white px-4 py-2 text-sm hover:bg-zinc-50">Batal</button>
            <button type="submit" disabled={saving} data-testid="adjust-balance-submit" className="rounded-none bg-[#002FA7] text-white px-5 py-2 text-sm font-bold uppercase tracking-wider hover:bg-[#002FA7]/90 disabled:opacity-50 inline-flex items-center gap-2">
              <Target className="w-4 h-4" />
              {saving ? "Memproses…" : "Buat Jurnal Penyesuaian"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}


/* ================================================================
   ===== Modal Diagnose Saldo — Verifikasi rumus & breakdown =====
   Menampilkan detail: Opening + Total Kredit − Total Debet = Saldo
   Plus breakdown per akun untuk spot anomali (mis. penjualan yg
   masuk revenue tapi belum tarik ke kas → tidak menambah saldo).
   ================================================================ */
function DiagnoseSaldoModal({ month, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [mode, setMode] = useState("month");  // "month" | "all"

  useEffect(() => {
    (async () => {
      setLoading(true); setErr("");
      try {
        const params = mode === "month" ? { month } : {};
        const res = await api.get("/cashbook/diagnose", { params });
        setData(res.data);
      } catch (e) {
        setErr(formatApiError(e.response?.data?.detail) || "Gagal memuat");
      } finally { setLoading(false); }
    })();
  }, [mode, month]);

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white max-w-3xl w-full max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="p-6 border-b border-zinc-200 flex items-center justify-between sticky top-0 bg-white z-10">
          <div>
            <h2 className="text-xl font-bold text-zinc-900">Diagnose Saldo Kas</h2>
            <p className="text-xs text-zinc-500 mt-1">Verifikasi rumus: Opening + Total Kredit − Total Debet = Saldo</p>
          </div>
          <div className="flex items-center gap-2">
            {/* Toggle mode: Bulan ini vs All-time */}
            <div className="inline-flex border border-zinc-300 text-[10px] font-bold uppercase tracking-widest">
              <button
                data-testid="diagnose-mode-month"
                onClick={() => setMode("month")}
                className={`px-3 py-1.5 ${mode === "month" ? "bg-[#002FA7] text-white" : "bg-white text-zinc-700 hover:bg-zinc-50"}`}
              >
                {monthLabel(month)}
              </button>
              <button
                data-testid="diagnose-mode-all"
                onClick={() => setMode("all")}
                className={`px-3 py-1.5 border-l border-zinc-300 ${mode === "all" ? "bg-[#002FA7] text-white" : "bg-white text-zinc-700 hover:bg-zinc-50"}`}
              >
                All-Time
              </button>
            </div>
            <button data-testid="diagnose-close" onClick={onClose} className="text-zinc-500 hover:text-zinc-900 text-2xl leading-none">×</button>
          </div>
        </div>

        <div className="p-6 space-y-6">
          {loading && <div className="text-zinc-400 font-mono text-sm">Memuat…</div>}
          {err && <div className="p-3 bg-[#E81123]/10 border border-[#E81123]/30 text-[#E81123] text-sm">{err}</div>}
          {data && (
            <>
              {/* Ringkasan Rumus SEDERHANA (yg user minta) — Opening + SEMUA Kredit − SEMUA Debet */}
              {data.simple && (
                <div className="p-4 bg-[#008A00]/5 border-2 border-[#008A00]/50">
                  <div className="text-[10px] uppercase tracking-widest font-bold text-[#008A00] mb-2">
                    Rumus Sederhana {mode === "month" ? `Bulan ${monthLabel(month)}` : "(all-time)"}
                  </div>
                  <div className="font-mono text-sm text-zinc-800 mb-3">
                    Saldo Sederhana = {mode === "month" ? "Saldo Awal" : "Opening"} + <b className="text-[#008A00]">Semua Kredit</b> − <b className="text-[#E81123]">Semua Debet</b>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <div>
                      <div className="text-zinc-500 uppercase tracking-widest text-[10px]">
                        {mode === "month" ? "Saldo Awal" : "Opening"}
                      </div>
                      <div className="font-mono font-bold text-zinc-900 mt-1">{formatIDR(data.opening_balance)}</div>
                    </div>
                    <div>
                      <div className="text-zinc-500 uppercase tracking-widest text-[10px]">+ Semua Kredit</div>
                      <div className="font-mono font-bold text-[#008A00] mt-1">{formatIDR(data.simple.total_in_all)}</div>
                    </div>
                    <div>
                      <div className="text-zinc-500 uppercase tracking-widest text-[10px]">− Semua Debet</div>
                      <div className="font-mono font-bold text-[#E81123] mt-1">{formatIDR(data.simple.total_out_all)}</div>
                    </div>
                    <div className="border-l-2 border-[#008A00] pl-3">
                      <div className="text-zinc-500 uppercase tracking-widest text-[10px]">= Hasil</div>
                      <div data-testid="diagnose-simple-balance" className="font-mono font-bold text-lg text-[#008A00] mt-1">{formatIDR(data.simple.balance)}</div>
                    </div>
                  </div>
                </div>
              )}

              {/* Ringkasan Rumus KAS (yg dipakai backend untuk Saldo Real-time) */}
              <div className="p-4 bg-[#002FA7]/5 border border-[#002FA7]/30">
                <div className="text-[10px] uppercase tracking-widest font-bold text-[#002FA7] mb-2">
                  Rumus Kas (dipakai kartu Saldo Real-time) — {mode === "month" ? monthLabel(month) : "all-time"}
                </div>
                <div className="font-mono text-sm text-zinc-800 mb-3">
                  Saldo Kas = {mode === "month" ? "Saldo Awal" : "Opening"} + Kredit (HANYA akun 101) − Semua Debet
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                  <div>
                    <div className="text-zinc-500 uppercase tracking-widest text-[10px]">
                      {mode === "month" ? "Saldo Awal" : "Opening"}
                    </div>
                    <div className="font-mono font-bold text-zinc-900 mt-1">{formatIDR(data.opening_balance)}</div>
                  </div>
                  <div>
                    <div className="text-zinc-500 uppercase tracking-widest text-[10px]">+ Kredit (101)</div>
                    <div className="font-mono font-bold text-[#008A00] mt-1">{formatIDR(data.total_in_kas_101)}</div>
                  </div>
                  <div>
                    <div className="text-zinc-500 uppercase tracking-widest text-[10px]">− Debet</div>
                    <div className="font-mono font-bold text-[#E81123] mt-1">{formatIDR(data.total_out_all_accounts)}</div>
                  </div>
                  <div className="border-l-2 border-[#002FA7] pl-3">
                    <div className="text-zinc-500 uppercase tracking-widest text-[10px]">= Saldo Kas</div>
                    <div data-testid="diagnose-balance" className="font-mono font-bold text-lg text-[#002FA7] mt-1">{formatIDR(data.balance_calculated)}</div>
                  </div>
                </div>
                <div className="mt-3 text-[10px] text-zinc-500 font-mono">
                  {data.tx_count_total} transaksi{mode === "month" ? " di bulan ini" : " total"} · {data.tx_count_kredit_101} kredit ke 101 · {data.tx_count_debet_all} debet
                  {data.adjustment_count > 0 && (
                    <> · <span className="text-[#E81123] font-bold">{data.adjustment_count} jurnal ADJUSTMENT</span></>
                  )}
                </div>
              </div>

              {/* Delta antara 2 rumus — bantu user mengerti selisih */}
              {data.simple && Math.abs(data.simple.balance - data.balance_calculated) > 0.01 && (
                <div className="p-3 bg-amber-50 border border-amber-300 text-xs">
                  <div className="font-bold text-amber-800 mb-1">
                    ⚠ Selisih 2 rumus: {formatIDR(data.simple.balance - data.balance_calculated)}
                  </div>
                  <div className="text-amber-900">
                    Perbedaan = {formatIDR(data.ignored_in_non_101.total_amount)} dari <b>{data.ignored_in_non_101.count} transaksi Penjualan/Pemasukan yg masuk akun revenue (301, 302, dll)</b>, bukan akun Kas (101).
                    Rumus Sederhana menghitung ini sebagai kas masuk, sedangkan Rumus Kas tidak (karena uang belum benar-benar masuk kas fisik — masih di platform Shopee/Bank).
                  </div>
                </div>
              )}

              {/* Ignored In (revenue non-101) — biasanya sumber kebingungan */}
              {data.ignored_in_non_101.count > 0 && (
                <div className="p-4 bg-amber-50 border border-amber-300">
                  <div className="text-[10px] uppercase tracking-widest font-bold text-amber-700 mb-2">
                    ⚠ Transaksi type=in yang TIDAK menambah Saldo Kas ({data.ignored_in_non_101.count} tx · {formatIDR(data.ignored_in_non_101.total_amount)})
                  </div>
                  <div className="text-xs text-amber-900 mb-2">
                    Ini adalah penjualan/pemasukan yg masuk ke akun revenue (301, 302, dll) — <b>bukan kas fisik</b>.
                    Uang belum masuk kas sampai ditarik/disetor via akun 101. Cocok untuk Shopee/Bank Transfer yg saldonya masih di platform.
                  </div>
                  <div className="mt-2 max-h-40 overflow-y-auto border border-amber-200 bg-white">
                    <table className="w-full text-xs">
                      <thead className="bg-amber-100">
                        <tr>
                          <th className="px-2 py-1 text-left">Tanggal</th>
                          <th className="px-2 py-1 text-left">Akun</th>
                          <th className="px-2 py-1 text-right">Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.ignored_in_non_101.sample.map((s, i) => (
                          <tr key={i} className="border-t border-amber-100">
                            <td className="px-2 py-1 font-mono">{s.date}</td>
                            <td className="px-2 py-1">{s.code} · {s.name}</td>
                            <td className="px-2 py-1 text-right font-mono">{formatIDR(s.amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Kredit breakdown */}
              <div>
                <div className="text-[10px] uppercase tracking-widest font-bold text-[#008A00] mb-2">Breakdown Kredit (uang masuk kas 101)</div>
                {data.in_by_account.length === 0 ? (
                  <div className="text-zinc-400 text-xs font-mono">Tidak ada transaksi kredit ke akun 101.</div>
                ) : (
                  <div className="border border-zinc-200">
                    <table className="w-full text-xs">
                      <thead className="bg-zinc-50 text-[10px] uppercase tracking-widest">
                        <tr>
                          <th className="px-3 py-2 text-left">Akun</th>
                          <th className="px-3 py-2 text-right">Jumlah Tx</th>
                          <th className="px-3 py-2 text-right">Total</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.in_by_account.map((row, i) => (
                          <tr key={i} className="border-t border-zinc-100">
                            <td className="px-3 py-2 font-mono">{row.code} · {row.name}</td>
                            <td className="px-3 py-2 text-right font-mono">{row.count}</td>
                            <td className="px-3 py-2 text-right font-mono text-[#008A00] font-bold">{formatIDR(row.total)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Debet breakdown */}
              <div>
                <div className="text-[10px] uppercase tracking-widest font-bold text-[#E81123] mb-2">Breakdown Debet (uang keluar semua akun)</div>
                {data.out_by_account.length === 0 ? (
                  <div className="text-zinc-400 text-xs font-mono">Tidak ada transaksi debet.</div>
                ) : (
                  <div className="border border-zinc-200 max-h-60 overflow-y-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-zinc-50 text-[10px] uppercase tracking-widest sticky top-0">
                        <tr>
                          <th className="px-3 py-2 text-left">Akun</th>
                          <th className="px-3 py-2 text-right">Jumlah Tx</th>
                          <th className="px-3 py-2 text-right">Total</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.out_by_account.map((row, i) => (
                          <tr key={i} className="border-t border-zinc-100">
                            <td className="px-3 py-2 font-mono">{row.code} · {row.name}</td>
                            <td className="px-3 py-2 text-right font-mono">{row.count}</td>
                            <td className="px-3 py-2 text-right font-mono text-[#E81123] font-bold">{formatIDR(row.total)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Cleanup actions — bantu cari duplikat & purge settings ganda */}
              <div className="p-3 border border-zinc-200 bg-zinc-50">
                <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 mb-2">🔧 Cleanup Data</div>
                <div className="flex flex-wrap gap-2">
                  <button
                    data-testid="find-duplicate-tx-btn"
                    onClick={async () => {
                      try {
                        const params = mode === "month" ? { month } : {};
                        const r = await api.get("/cashbook/find-duplicate-tx", { params });
                        const dg = r.data.duplicate_groups;
                        if (dg === 0) {
                          toast.success("Tidak ada transaksi duplikat ditemukan.");
                        } else {
                          const sample = r.data.duplicates.slice(0, 3).map(d => `• ${d.date} ${d.description?.slice(0,30)} × ${d.count}`).join("\n");
                          toast.warning(`${dg} grup duplikat (${r.data.total_extra_txs} tx berlebih).\n\n${sample}`, { duration: 8000 });
                        }
                      } catch (e) { toast.error("Gagal cek duplikat"); }
                    }}
                    className="text-[10px] font-bold uppercase tracking-widest px-3 py-1.5 border border-amber-500 text-amber-700 bg-white hover:bg-amber-50"
                  >
                    Cari Duplikat Tx {mode === "month" ? monthLabel(month) : "All-Time"}
                  </button>
                  <button
                    data-testid="purge-cash-settings-btn"
                    onClick={async () => {
                      if (!window.confirm("Hapus dokumen cash_settings ganda? Yg dipertahankan = opening_balance tertinggi.")) return;
                      try {
                        const r = await api.post("/cashbook/purge-duplicate-cashbook-settings");
                        toast.success(`${r.data.deleted} duplicate settings dihapus. Opening tersisa: ${formatIDR(r.data.kept_opening_balance)}`);
                      } catch (e) { toast.error("Gagal cleanup"); }
                    }}
                    className="text-[10px] font-bold uppercase tracking-widest px-3 py-1.5 border border-[#E81123] text-[#E81123] bg-white hover:bg-[#E81123]/5"
                  >
                    Cleanup Setting Ganda
                  </button>
                </div>
              </div>

              {/* Notes */}
              <div className="text-[11px] text-zinc-500 border-t border-zinc-200 pt-3">
                {data.notes.map((n, i) => <div key={i}>• {n}</div>)}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function MonthlyLockDialog({ currentMonth, onClose, onSaved }) {
  const [items, setItems] = useState([]);
  const [month, setMonth] = useState(currentMonth);
  const [amount, setAmount] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get("/cashbook/monthly-openings");
      setItems(res.data.items || []);
      // Prefill amount jika bulan aktif sudah punya lock
      const existing = (res.data.items || []).find((x) => x.month === month);
      if (existing) setAmount(String(existing.opening_balance));
      else setAmount("");
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Gagal load kunci saldo");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);
  useEffect(() => {
    const existing = items.find((x) => x.month === month);
    setAmount(existing ? String(existing.opening_balance) : "");
  }, [month, items]);

  const save = async () => {
    const num = Number(String(amount).replace(/[^\d.-]/g, ""));
    if (!month || Number.isNaN(num)) {
      toast.error("Bulan dan Nominal wajib diisi");
      return;
    }
    setSaving(true);
    try {
      await api.put(`/cashbook/monthly-openings/${month}`, { opening_balance: num });
      toast.success(`Saldo Awal ${monthLabel(month)} dikunci ke ${formatIDR(num)}`);
      await load();
      await onSaved?.();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (m) => {
    if (!window.confirm(`Hapus kunci Saldo Awal ${monthLabel(m)}? Sistem akan kembali menghitung otomatis dari data.`)) return;
    try {
      await api.delete(`/cashbook/monthly-openings/${m}`);
      toast.success("Kunci dihapus. Sistem hitung otomatis.");
      await load();
      await onSaved?.();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Gagal hapus");
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white w-full max-w-2xl border border-zinc-900 shadow-2xl" data-testid="monthly-lock-dialog">
        <div className="border-b border-zinc-200 px-6 py-4 flex items-center justify-between bg-[#F97316]/5">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-[#F97316]">Override Saldo Awal</div>
            <h2 className="font-heading text-xl font-bold text-zinc-900 mt-0.5">Kunci Saldo Awal per Bulan</h2>
            <p className="text-xs text-zinc-500 mt-1">Angka ini akan dipakai sebagai Saldo Awal bulan itu. Pemasukan/Pengeluaran/Kasbon dihitung otomatis dari transaksi.</p>
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-900" data-testid="monthly-lock-close">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Bulan (YYYY-MM)">
              <input
                type="month"
                value={month}
                onChange={(e) => setMonth(e.target.value)}
                data-testid="monthly-lock-month-input"
                className="w-full border border-zinc-300 rounded-none px-3 py-2 text-sm font-mono focus:outline-none focus:border-[#F97316]"
              />
            </Field>
            <Field label="Nominal Saldo Awal (Rp)">
              <input
                type="text"
                inputMode="numeric"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="10462598"
                data-testid="monthly-lock-amount-input"
                className="w-full border border-zinc-300 rounded-none px-3 py-2 text-sm font-mono focus:outline-none focus:border-[#F97316]"
              />
            </Field>
          </div>
          <button
            onClick={save}
            disabled={saving}
            data-testid="monthly-lock-save-button"
            className="w-full bg-[#F97316] text-white px-4 py-3 text-sm font-bold uppercase tracking-wider hover:bg-[#EA6A0F] disabled:opacity-50 inline-flex items-center justify-center gap-2"
          >
            <Lock className="w-4 h-4" /> {saving ? "Menyimpan…" : `Kunci Saldo Awal ${monthLabel(month)}`}
          </button>

          <div className="border-t border-zinc-200 pt-4">
            <div className="text-xs font-bold uppercase tracking-widest text-zinc-500 mb-3">Daftar Bulan Terkunci</div>
            {loading ? (
              <div className="text-sm text-zinc-500">Loading…</div>
            ) : items.length === 0 ? (
              <div className="text-sm text-zinc-500 italic">Belum ada bulan yang dikunci. Sistem menghitung otomatis dari data.</div>
            ) : (
              <table className="w-full text-sm" data-testid="monthly-lock-list">
                <thead className="text-[10px] uppercase tracking-widest text-zinc-500 border-b border-zinc-200">
                  <tr>
                    <th className="text-left py-2">Bulan</th>
                    <th className="text-right py-2">Saldo Awal</th>
                    <th className="text-left py-2 pl-4">Update Terakhir</th>
                    <th className="text-right py-2">Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.month} className="border-b border-zinc-100">
                      <td className="py-2.5 font-mono font-semibold">{monthLabel(it.month)} <span className="text-zinc-400">({it.month})</span></td>
                      <td className="py-2.5 text-right font-mono font-bold text-[#002FA7]">{formatIDR(it.opening_balance)}</td>
                      <td className="py-2.5 pl-4 text-[11px] text-zinc-500 font-mono">
                        {it.updated_at ? new Date(it.updated_at).toLocaleString("id-ID") : "-"}
                        {it.updated_by && <div className="text-zinc-400">oleh {it.updated_by}</div>}
                      </td>
                      <td className="py-2.5 text-right">
                        <button onClick={() => remove(it.month)} data-testid={`monthly-lock-delete-${it.month}`} className="text-[#E81123] hover:underline text-xs font-semibold">Hapus</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

