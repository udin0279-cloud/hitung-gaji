import { useEffect, useState } from "react";
import { api, API } from "../lib/api";
import { Calendar, FileCheck, FileX, Paperclip, Filter, Check, X as XIcon, Download, FileSpreadsheet, FileText } from "lucide-react";
import { toast } from "sonner";

const STATUS_STYLE = {
  pending: "bg-amber-50 text-amber-800 border-amber-300",
  approved: "bg-emerald-50 text-emerald-800 border-emerald-300",
  rejected: "bg-rose-50 text-rose-800 border-rose-300",
};
const STATUS_LABEL = { pending: "Menunggu", approved: "Disetujui", rejected: "Ditolak" };

const TYPE_OPTIONS = [
  { value: "", label: "Semua Jenis" },
  { value: "terlambat", label: "Datang Terlambat" },
  { value: "pulang_awal", label: "Pulang Awal" },
  { value: "tidak_masuk", label: "Tidak Masuk" },
  { value: "sakit", label: "Sakit" },
  { value: "lembur", label: "Lembur" },
];

export default function LeaveAdmin() {
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState({ pending: 0, approved: 0, rejected: 0, total: 0 });
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState("pending");
  const [filterType, setFilterType] = useState("");
  const [reviewing, setReviewing] = useState(null); // {item, action: "approve"|"reject"}
  const [reportMonth, setReportMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });

  const load = async () => {
    setLoading(true);
    try {
      const params = {};
      if (filterStatus) params.status = filterStatus;
      if (filterType) params.type = filterType;
      const [list, st] = await Promise.all([
        api.get("/leave", { params }),
        api.get("/leave/stats"),
      ]);
      setItems(list.data);
      setStats(st.data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [filterStatus, filterType]);

  return (
    <div className="min-h-screen p-4 sm:p-6 lg:p-10">
      <div className="mb-6 lg:mb-8">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Manajemen</div>
        <h1 className="font-heading text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Pengajuan Izin Karyawan</h1>
        <p className="text-sm text-zinc-500 mt-2">Tinjau dan setujui/tolak pengajuan izin dari karyawan.</p>
      </div>

      {/* Monthly Report Export */}
      <div className="mb-6 border border-zinc-200 bg-white p-4 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Export Laporan Bulanan</div>
          <p className="text-xs text-zinc-500 mt-1">Pilih periode dan unduh laporan untuk audit / lapor ke direksi.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="month"
            data-testid="report-month-input"
            value={reportMonth}
            onChange={(e) => setReportMonth(e.target.value)}
            className="border border-zinc-300 px-3 py-1.5 text-xs font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none min-w-0"
          />
          <a
            data-testid="export-excel-button"
            href={`${API}/leave/report/${reportMonth}/excel`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 bg-emerald-700 text-white px-3 py-1.5 text-xs font-semibold uppercase tracking-wider hover:bg-emerald-800"
          >
            <FileSpreadsheet className="w-3.5 h-3.5" /> Excel
          </a>
          <a
            data-testid="export-pdf-button"
            href={`${API}/leave/report/${reportMonth}/pdf`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 bg-rose-700 text-white px-3 py-1.5 text-xs font-semibold uppercase tracking-wider hover:bg-rose-800"
          >
            <FileText className="w-3.5 h-3.5" /> PDF
          </a>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200 mb-6">
        <StatCard label="Menunggu" value={stats.pending} icon={Calendar} color="#d97706" testId="stat-pending" />
        <StatCard label="Disetujui" value={stats.approved} icon={FileCheck} color="#059669" testId="stat-approved" />
        <StatCard label="Ditolak" value={stats.rejected} icon={FileX} color="#dc2626" testId="stat-rejected" />
        <StatCard label="Total" value={stats.total} icon={Filter} color="#002FA7" testId="stat-total" />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 sm:gap-3 mb-4">
        <div className="flex items-center gap-1">
          {["pending", "approved", "rejected", ""].map((s) => (
            <button
              key={s || "all"}
              data-testid={`filter-status-${s || "all"}`}
              onClick={() => setFilterStatus(s)}
              className={`px-3 py-1.5 text-xs font-semibold uppercase tracking-wider border transition-colors ${
                filterStatus === s ? "bg-zinc-900 text-white border-zinc-900" : "border-zinc-300 text-zinc-700 hover:bg-zinc-50"
              }`}
            >
              {s ? STATUS_LABEL[s] : "Semua"}
            </button>
          ))}
        </div>
        <select
          data-testid="filter-type"
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="border border-zinc-300 px-3 py-1.5 text-xs font-semibold focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
        >
          {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      {/* Table */}
      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Karyawan</th>
              <th className="px-4 py-3">Jenis</th>
              <th className="px-4 py-3">Tanggal</th>
              <th className="px-4 py-3">Alasan</th>
              <th className="px-4 py-3 text-center">Lampiran</th>
              <th className="px-4 py-3 text-center">Status</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {!loading && items.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Tidak ada pengajuan.</td></tr>
            )}
            {items.map((x) => (
              <tr key={x.id} data-testid={`admin-leave-row-${x.id}`} className="border-b border-zinc-100 hover:bg-zinc-50/80 align-top">
                <td className="px-4 py-3">
                  <div className="font-semibold text-zinc-900">{x.employee_name}</div>
                  <div className="text-[11px] text-zinc-500 font-mono">{x.employee_nik}{x.department ? ` · ${x.department}` : ""}</div>
                </td>
                <td className="px-4 py-3">
                  <div className="text-zinc-900">{x.type_label}</div>
                  {x.type === "pulang_awal" && x.time_end ? (
                    <div className="text-[11px] text-zinc-500 font-mono">
                      Pulang {x.time_end} ({x.time_minutes}m lebih awal)
                    </div>
                  ) : x.time_start && x.time_end ? (
                    <div className="text-[11px] text-zinc-500 font-mono">
                      {x.time_start}–{x.time_end} ({Math.floor((x.time_minutes || 0) / 60)}j {(x.time_minutes || 0) % 60}m)
                    </div>
                  ) : x.time_minutes ? (
                    <div className="text-[11px] text-zinc-500 font-mono">{x.time_minutes} menit</div>
                  ) : null}
                </td>
                <td className="px-4 py-3 font-mono text-zinc-700 text-xs">
                  {x.date_start}
                  {x.date_end && x.date_end !== x.date_start && <> &rarr; {x.date_end}</>}
                </td>
                <td className="px-4 py-3 text-zinc-600 text-xs max-w-xs">
                  <div className="line-clamp-2">{x.reason || "—"}</div>
                  {x.hr_note && <div className="mt-1 text-[11px] text-zinc-500 italic">Catatan HR: {x.hr_note}</div>}
                </td>
                <td className="px-4 py-3 text-center">
                  {x.attachment ? (
                    <a
                      href={`${API}/leave/${x.id}/attachment`}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-[11px] text-[#002FA7] hover:underline"
                    >
                      <Paperclip className="w-3 h-3" /> Lihat
                    </a>
                  ) : <span className="text-zinc-300 text-xs">—</span>}
                </td>
                <td className="px-4 py-3 text-center">
                  <span className={`inline-block px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest border ${STATUS_STYLE[x.status]}`}>
                    {STATUS_LABEL[x.status]}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  {x.status === "pending" && (
                    <div className="inline-flex items-center gap-1">
                      <button
                        data-testid={`approve-${x.id}`}
                        onClick={() => setReviewing({ item: x, action: "approve" })}
                        className="inline-flex items-center gap-1 text-[11px] bg-emerald-600 text-white hover:bg-emerald-700 px-2 py-1"
                      >
                        <Check className="w-3 h-3" /> Setujui
                      </button>
                      <button
                        data-testid={`reject-${x.id}`}
                        onClick={() => setReviewing({ item: x, action: "reject" })}
                        className="inline-flex items-center gap-1 text-[11px] bg-rose-600 text-white hover:bg-rose-700 px-2 py-1"
                      >
                        <XIcon className="w-3 h-3" /> Tolak
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {reviewing && (
        <ReviewModal
          item={reviewing.item}
          action={reviewing.action}
          onClose={() => setReviewing(null)}
          onSuccess={() => { setReviewing(null); load(); }}
        />
      )}
    </div>
  );
}

function ReviewModal({ item, action, onClose, onSuccess }) {
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const isApprove = action === "approve";

  const submit = async () => {
    if (!isApprove && !note.trim()) { toast.error("Alasan penolakan wajib diisi"); return; }
    setSubmitting(true);
    try {
      await api.put(`/leave/${item.id}/${action}`, { hr_note: note });
      toast.success(isApprove ? "Pengajuan disetujui" : "Pengajuan ditolak");
      onSuccess();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Gagal memproses");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white w-full max-w-md border border-zinc-200">
        <div className="px-6 py-4 border-b border-zinc-200">
          <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">{isApprove ? "Setujui Pengajuan" : "Tolak Pengajuan"}</div>
          <h2 className="font-heading text-xl font-bold mt-0.5">{item.employee_name}</h2>
          <div className="text-xs text-zinc-500 mt-1 font-mono">{item.type_label} · {item.date_start}</div>
        </div>
        <div className="p-6">
          <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">
            Catatan HR {!isApprove && <span className="text-rose-600">*wajib untuk penolakan</span>}
          </label>
          <textarea
            data-testid="review-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={4}
            placeholder={isApprove ? "Opsional..." : "Jelaskan alasan penolakan..."}
            className="w-full border border-zinc-300 px-3 py-2 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
          />
        </div>
        <div className="px-6 py-4 border-t border-zinc-200 flex items-center justify-end gap-2">
          <button onClick={onClose} className="border border-zinc-300 px-4 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-50">Batal</button>
          <button
            data-testid="confirm-review"
            onClick={submit}
            disabled={submitting}
            className={`px-5 py-2 text-xs font-semibold uppercase tracking-wider text-white disabled:opacity-50 ${
              isApprove ? "bg-emerald-600 hover:bg-emerald-700" : "bg-rose-600 hover:bg-rose-700"
            }`}
          >
            {submitting ? "Memproses…" : (isApprove ? "Setujui & Kirim Email" : "Tolak & Kirim Email")}
          </button>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, color, testId }) {
  return (
    <div className="bg-white p-3 sm:p-4 min-w-0" data-testid={testId}>
      <div className="flex items-center gap-1.5 min-w-0">
        <Icon className="w-3.5 h-3.5 shrink-0" style={{ color }} />
        <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold truncate">{label}</div>
      </div>
      <div className="font-mono text-xl sm:text-2xl font-semibold mt-2" style={{ color }}>{value}</div>
    </div>
  );
}
