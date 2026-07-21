import { useEffect, useState } from "react";
import { api, formatIDR, formatApiError } from "../lib/api";
import { toast } from "sonner";
import { Store, Edit3, X as XIcon, Save, Calendar } from "lucide-react";

function todayISO() { return new Date().toISOString().slice(0, 10); }
function firstDayOfMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

export default function ShopeeRincianReport() {
  const [dateFrom, setDateFrom] = useState(firstDayOfMonth());
  const [dateTo, setDateTo] = useState(todayISO());
  const [data, setData] = useState({
    plaza: { rows: [], totals: { jumlah: 0, saldo_masuk: 0, potongan: 0 }, count: 0 },
    kastem: { rows: [], totals: { jumlah: 0, saldo_masuk: 0, potongan: 0 }, count: 0 },
  });
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // { row, side }

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get("/sales/report/shopee-rincian", {
        params: {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
      });
      setData(res.data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memuat laporan");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200 max-w-7xl">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Modul</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Rincian Penjualan Online Shopee</h1>
          <p className="text-sm text-zinc-500 mt-1">Rekap netto & potongan per outlet — data dari transaksi kasir dengan metode Shopee Plaza / Shopee Kastem.</p>
        </div>
      </div>

      {/* Filter */}
      <div className="mt-6 border border-zinc-200 bg-white p-4 grid grid-cols-1 sm:grid-cols-4 gap-3 items-end max-w-3xl">
        <div>
          <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1.5">Dari Tanggal</label>
          <input data-testid="rincian-date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            className="w-full rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none" />
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-widest font-bold text-zinc-700 block mb-1.5">Sampai Tanggal</label>
          <input data-testid="rincian-date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            className="w-full rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:outline-none" />
        </div>
        <div className="col-span-2">
          <button data-testid="rincian-apply-filter" onClick={load} disabled={loading}
            className="w-full rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-bold uppercase tracking-wider hover:bg-[#001E7A] disabled:opacity-40">
            <Calendar className="w-3.5 h-3.5 inline-block mr-1.5" />{loading ? "Memuat…" : "Terapkan Filter"}
          </button>
        </div>
      </div>

      {/* Two side-by-side tables */}
      <div className="mt-6 grid grid-cols-1 xl:grid-cols-2 gap-4">
        <RincianTable
          title="Shopee Plaza"
          testid="table-plaza"
          headerColor="bg-[#008A00]"
          totalColor="bg-[#008A00]/10 text-[#008A00]"
          side="plaza"
          data={data.plaza}
          loading={loading}
          onEdit={(row) => setEditing({ row, side: "plaza" })}
        />
        <RincianTable
          title="Shopee Kastem"
          testid="table-kastem"
          headerColor="bg-[#34C759]"
          totalColor="bg-[#34C759]/10 text-emerald-700"
          side="kastem"
          data={data.kastem}
          loading={loading}
          onEdit={(row) => setEditing({ row, side: "kastem" })}
        />
      </div>

      {/* Grand total */}
      {!loading && (data.plaza.count > 0 || data.kastem.count > 0) && (
        <div data-testid="grand-total" className="mt-6 border border-zinc-900 bg-yellow-100 px-6 py-4 flex flex-wrap items-center gap-6 max-w-7xl">
          <div className="flex-1">
            <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-700">Total Keseluruhan Shopee (Plaza + Kastem)</div>
            <div className="text-[10px] font-mono text-zinc-500 mt-0.5">{data.plaza.count + data.kastem.count} transaksi</div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-widest text-zinc-600">Bruto</div>
            <div className="font-mono font-bold text-lg text-zinc-900" data-testid="grand-jumlah">{formatIDR((data.plaza.totals.jumlah || 0) + (data.kastem.totals.jumlah || 0))}</div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-widest text-zinc-600">Total Saldo Masuk</div>
            <div className="font-mono font-bold text-lg text-[#002FA7]" data-testid="grand-saldo">{formatIDR((data.plaza.totals.saldo_masuk || 0) + (data.kastem.totals.saldo_masuk || 0))}</div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-widest text-zinc-600">Total Potongan</div>
            <div className="font-mono font-bold text-lg text-[#E81123]" data-testid="grand-potongan">{formatIDR((data.plaza.totals.potongan || 0) + (data.kastem.totals.potongan || 0))}</div>
          </div>
        </div>
      )}

      {editing && (
        <SaldoMasukModal
          row={editing.row}
          side={editing.side}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
}

function RincianTable({ title, testid, headerColor, totalColor, side, data, loading, onEdit }) {
  const rows = data?.rows || [];
  const totals = data?.totals || { jumlah: 0, saldo_masuk: 0, potongan: 0 };
  return (
    <div data-testid={testid} className="border border-zinc-200 bg-white">
      <div className={`${headerColor} text-white px-4 py-2.5 flex items-center gap-2`}>
        <Store className="w-4 h-4" />
        <h2 className="font-heading text-sm font-bold tracking-wide uppercase">{title}</h2>
        <span className="text-[10px] font-mono ml-auto opacity-80">{data.count} baris</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm" style={{ minWidth: 900 }}>
          <thead>
            <tr className="bg-zinc-900 text-white text-[10px] font-bold uppercase tracking-wider">
              <th className="px-2 py-2 border-r border-zinc-700">Nama</th>
              <th className="px-2 py-2 border-r border-zinc-700">Pesanan</th>
              <th className="px-2 py-2 text-center border-r border-zinc-700">Pcs</th>
              <th className="px-2 py-2 text-center border-r border-zinc-700">Meter</th>
              <th className="px-2 py-2 text-right border-r border-zinc-700">Harga Satuan</th>
              <th className="px-2 py-2 text-right border-r border-zinc-700 bg-yellow-500 text-zinc-900">Jumlah</th>
              <th className="px-2 py-2 text-right border-r border-zinc-700">Saldo Masuk</th>
              <th className="px-2 py-2 text-right border-r border-zinc-700">Potongan (Rp)</th>
              <th className="px-2 py-2 text-center border-r border-zinc-700 whitespace-nowrap">%</th>
              <th className="px-2 py-2 text-center whitespace-nowrap">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={10} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={10} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">Belum ada transaksi Shopee {side === "plaza" ? "Plaza" : "Kastem"} pada periode ini.</td></tr>
            )}
            {rows.map((r) => (
              <tr key={r.id} data-testid={`row-${side}-${r.id}`} className="border-b border-zinc-100 hover:bg-zinc-50">
                <td className="px-2 py-2 text-xs font-semibold text-zinc-900 border-r border-zinc-100">{r.nama}</td>
                <td className="px-2 py-2 text-xs border-r border-zinc-100">{r.pesanan}</td>
                <td className="px-2 py-2 text-center font-mono text-xs border-r border-zinc-100">{r.pcs}</td>
                <td className="px-2 py-2 text-center font-mono text-xs border-r border-zinc-100">
                  {Number(r.meter || 0) > 0 ? Number(r.meter).toFixed(2) : <span className="text-zinc-300">—</span>}
                </td>
                <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">{formatIDR(r.harga_satuan)}</td>
                <td className="px-2 py-2 text-right font-mono text-xs font-bold bg-yellow-50 border-r border-zinc-100">{formatIDR(r.jumlah)}</td>
                <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">
                  {r.saldo_masuk !== null && r.saldo_masuk !== undefined ? (
                    <span className="text-[#002FA7] font-semibold">{formatIDR(r.saldo_masuk)}</span>
                  ) : (
                    <span className="text-zinc-300 italic">(belum diisi)</span>
                  )}
                </td>
                <td className="px-2 py-2 text-right font-mono text-xs border-r border-zinc-100">
                  {r.potongan !== null && r.potongan !== undefined ? (
                    <span className="text-[#E81123]">{formatIDR(r.potongan)}</span>
                  ) : (
                    <span className="text-zinc-300">—</span>
                  )}
                </td>
                <td className="px-2 py-2 text-center font-mono text-xs font-bold border-r border-zinc-100">
                  {r.persentase !== null && r.persentase !== undefined ? (
                    <span className={`px-1.5 py-0.5 ${r.persentase > 20 ? "bg-[#E81123]/10 text-[#E81123]" : "bg-zinc-100 text-zinc-700"}`}>{r.persentase}%</span>
                  ) : (
                    <span className="text-zinc-300">—</span>
                  )}
                </td>
                <td className="px-2 py-2 text-center">
                  <button
                    data-testid={`edit-saldo-${r.id}`}
                    onClick={() => onEdit(r)}
                    title="Edit Saldo Masuk"
                    className="p-1.5 hover:bg-[#002FA7]/10 text-[#002FA7]"
                  >
                    <Edit3 className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            ))}
            {!loading && rows.length > 0 && (
              <tr className={`border-t-2 border-zinc-900 ${totalColor}`}>
                <td colSpan={5} className="px-2 py-3">
                  <span className="text-xs font-bold uppercase tracking-widest">Total Saldo Masuk</span>
                </td>
                <td className="px-2 py-3 text-right font-mono font-bold text-xs">{formatIDR(totals.jumlah)}</td>
                <td data-testid={`total-saldo-${side}`} className="px-2 py-3 text-right font-mono font-bold text-base">{formatIDR(totals.saldo_masuk)}</td>
                <td className="px-2 py-3 text-right font-mono font-bold text-xs text-[#E81123]">{formatIDR(totals.potongan)}</td>
                <td className="px-2 py-3 text-center font-mono text-xs">
                  {totals.jumlah > 0 ? `${Math.round((totals.potongan / totals.jumlah) * 100)}%` : "—"}
                </td>
                <td></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SaldoMasukModal({ row, side, onClose, onSaved }) {
  const [val, setVal] = useState(row.saldo_masuk ?? "");
  const [submitting, setSubmitting] = useState(false);

  const jumlah = Number(row.jumlah || 0);
  const saldoNum = val === "" ? null : Number(val);
  const preview = saldoNum !== null && !isNaN(saldoNum) ? {
    potongan: jumlah - saldoNum,
    persen: jumlah > 0 ? ((jumlah - saldoNum) / jumlah * 100).toFixed(2) : 0,
  } : null;

  const save = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.patch(`/sales/${row.sale_id}/saldo-masuk`, {
        saldo_masuk: val === "" ? null : Number(val),
      });
      toast.success("Saldo Masuk tersimpan");
      onSaved();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal simpan");
    } finally { setSubmitting(false); }
  };

  const clear = async () => {
    if (!confirm("Kosongkan Saldo Masuk untuk transaksi ini?")) return;
    setSubmitting(true);
    try {
      await api.patch(`/sales/${row.sale_id}/saldo-masuk`, { saldo_masuk: null });
      toast.success("Saldo Masuk dikosongkan");
      onSaved();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal");
    } finally { setSubmitting(false); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white w-full max-w-md border border-zinc-200">
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200">
          <div>
            <div className="text-[10px] uppercase tracking-widest font-bold text-zinc-500">Shopee {side === "plaza" ? "Plaza" : "Kastem"}</div>
            <h2 className="font-heading text-lg font-bold">Edit Saldo Masuk</h2>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-zinc-100" data-testid="close-saldo-modal"><XIcon className="w-4 h-4" /></button>
        </div>
        <form onSubmit={save} className="p-6 space-y-4">
          <div className="text-xs space-y-1 border border-zinc-200 bg-zinc-50 p-3">
            <div className="flex justify-between"><span className="text-zinc-500">Nama:</span><span className="font-semibold">{row.nama}</span></div>
            <div className="flex justify-between"><span className="text-zinc-500">Pesanan:</span><span>{row.pesanan}</span></div>
            <div className="flex justify-between"><span className="text-zinc-500">No. Nota:</span><span className="font-mono">{row.sale_no}</span></div>
            <div className="flex justify-between"><span className="text-zinc-500">Jumlah (Bruto):</span><span className="font-mono font-bold text-zinc-900">{formatIDR(jumlah)}</span></div>
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">Saldo Masuk (Netto) — Rp</label>
            <input
              type="number"
              min="0"
              step="0.01"
              data-testid="saldo-masuk-input"
              value={val}
              onChange={(e) => setVal(e.target.value)}
              placeholder="Nominal aktual yang diterima setelah potongan Shopee"
              className="w-full border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
            />
            <div className="text-[10px] font-mono text-zinc-500 mt-1">Kosongkan untuk menghapus data.</div>
          </div>
          {preview && (
            <div className="border border-zinc-300 bg-yellow-50 p-3 text-xs space-y-1">
              <div className="flex justify-between"><span className="text-zinc-500">Potongan otomatis:</span><span className="font-mono font-bold text-[#E81123]">{formatIDR(preview.potongan)}</span></div>
              <div className="flex justify-between"><span className="text-zinc-500">Persentase potongan:</span><span className="font-mono font-bold">{preview.persen}%</span></div>
            </div>
          )}
          <div className="flex items-center justify-between gap-2 pt-2 border-t border-zinc-200">
            <button
              type="button"
              onClick={clear}
              disabled={submitting || row.saldo_masuk === null || row.saldo_masuk === undefined}
              className="text-xs text-[#E81123] hover:underline disabled:opacity-30 disabled:cursor-not-allowed"
              data-testid="clear-saldo"
            >
              Kosongkan
            </button>
            <div className="flex items-center gap-2">
              <button type="button" onClick={onClose} className="border border-zinc-300 px-4 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-50">Batal</button>
              <button
                type="submit"
                data-testid="save-saldo"
                disabled={submitting || val === ""}
                className="inline-flex items-center gap-1.5 bg-[#002FA7] text-white px-5 py-2 text-xs font-bold uppercase tracking-wider hover:bg-[#001E7A] disabled:opacity-40"
              >
                <Save className="w-3.5 h-3.5" />
                {submitting ? "Menyimpan…" : "Simpan"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
