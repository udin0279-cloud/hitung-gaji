import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, API } from "../lib/api";
import { usePortalAuth } from "../context/PortalAuthContext";
import { LogOut, Square, ChevronLeft, Upload, X, Clock, CalendarOff, LogOut as LogOutIcon, Heart, Zap, Paperclip, Trash2 } from "lucide-react";
import { toast } from "sonner";

const LEAVE_TYPES = [
  { value: "terlambat", label: "Datang Terlambat", icon: Clock, desc: "Izin masuk lebih lambat dari jam kerja" },
  { value: "pulang_awal", label: "Pulang Awal", icon: LogOutIcon, desc: "Izin pulang lebih awal dari jam kerja" },
  { value: "tidak_masuk", label: "Tidak Masuk", icon: CalendarOff, desc: "Izin tidak hadir tanpa keterangan sakit" },
  { value: "sakit", label: "Sakit", icon: Heart, desc: "Izin sakit (disarankan lampirkan surat dokter)" },
  { value: "lembur", label: "Lembur", icon: Zap, desc: "Pengajuan kerja lembur di luar jam kerja" },
];

const STATUS_STYLE = {
  pending: "bg-amber-50 text-amber-800 border-amber-300",
  approved: "bg-emerald-50 text-emerald-800 border-emerald-300",
  rejected: "bg-rose-50 text-rose-800 border-rose-300",
};
const STATUS_LABEL = { pending: "Menunggu", approved: "Disetujui", rejected: "Ditolak" };

export default function PortalLeave() {
  const { employee, logout } = usePortalAuth();
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  const load = async () => {
    try {
      const { data } = await api.get("/portal/leave");
      setItems(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleLogout = async () => {
    await logout();
    navigate("/portal/login");
  };

  const cancel = async (id) => {
    if (!confirm("Batalkan pengajuan ini?")) return;
    try {
      await api.delete(`/portal/leave/${id}`);
      toast.success("Pengajuan dibatalkan");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Gagal membatalkan");
    }
  };

  if (!employee) return null;

  return (
    <div className="min-h-screen bg-zinc-50">
      <header className="bg-white border-b border-zinc-200">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/portal" className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-[#002FA7] flex items-center justify-center">
              <Square className="w-4 h-4 text-white" fill="white" />
            </div>
            <div>
              <div className="font-heading font-bold text-zinc-900 leading-none">PAYROLL.ID</div>
              <div className="text-[10px] text-zinc-500 uppercase tracking-widest mt-0.5">Employee Portal</div>
            </div>
          </Link>
          <button
            data-testid="portal-logout-button"
            onClick={handleLogout}
            className="inline-flex items-center gap-2 border border-zinc-300 hover:bg-zinc-900 hover:text-white px-3 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors"
          >
            <LogOut className="w-3.5 h-3.5" /> Keluar
          </button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">
        <div className="flex items-center justify-between mb-6">
          <Link to="/portal" className="inline-flex items-center gap-1 text-xs uppercase tracking-widest text-zinc-500 hover:text-zinc-900 font-semibold">
            <ChevronLeft className="w-3.5 h-3.5" /> Kembali ke Dashboard
          </Link>
        </div>

        <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
          <div>
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Pengajuan Saya</div>
            <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Cuti & Izin</h1>
            <p className="text-sm text-zinc-500 mt-2 max-w-xl">Ajukan izin datang terlambat, pulang awal, tidak masuk, atau sakit. Pengajuan akan diteruskan ke HR untuk persetujuan.</p>
          </div>
          <button
            data-testid="open-leave-form"
            onClick={() => setShowForm(true)}
            className="bg-[#002FA7] text-white px-5 py-2.5 text-xs font-semibold uppercase tracking-wider hover:bg-[#002FA7]/90 inline-flex items-center gap-2"
          >
            + Ajukan Izin Baru
          </button>
        </div>

        {/* History Table */}
        <div className="border border-zinc-200 bg-white overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
                <th className="px-4 py-3">Jenis</th>
                <th className="px-4 py-3">Tanggal</th>
                <th className="px-4 py-3">Alasan</th>
                <th className="px-4 py-3 text-center">Lampiran</th>
                <th className="px-4 py-3 text-center">Status</th>
                <th className="px-4 py-3 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={6} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
              {!loading && items.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Belum ada pengajuan.</td></tr>
              )}
              {items.map((x) => (
                <tr key={x.id} data-testid={`leave-row-${x.id}`} className="border-b border-zinc-100 hover:bg-zinc-50/80 align-top">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-zinc-900">{x.type_label}</div>
                    {x.time_minutes && !x.time_start ? <div className="text-[11px] text-zinc-500 font-mono mt-0.5">{x.time_minutes} menit</div> : null}
                    {x.time_start && x.time_end ? (
                      <div className="text-[11px] text-zinc-500 font-mono mt-0.5">
                        {x.time_start}–{x.time_end} ({Math.floor((x.time_minutes || 0) / 60)}j {(x.time_minutes || 0) % 60}m)
                      </div>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 font-mono text-zinc-700 text-xs">
                    {x.date_start}
                    {x.date_end && x.date_end !== x.date_start && <> &rarr; {x.date_end}</>}
                  </td>
                  <td className="px-4 py-3 text-zinc-600 text-xs max-w-xs">
                    <div className="line-clamp-2">{x.reason || "—"}</div>
                    {x.hr_note && (
                      <div className="mt-1 text-[11px] text-zinc-500 italic">Catatan HR: {x.hr_note}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {x.attachment ? (
                      <a
                        href={`${API}/portal/leave/${x.id}/attachment`}
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
                      <button
                        data-testid={`cancel-leave-${x.id}`}
                        onClick={() => cancel(x.id)}
                        className="inline-flex items-center gap-1 text-[11px] text-rose-700 hover:bg-rose-50 px-2 py-1 border border-rose-200"
                      >
                        <Trash2 className="w-3 h-3" /> Batalkan
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>

      {showForm && <LeaveFormModal onClose={() => setShowForm(false)} onSuccess={() => { setShowForm(false); load(); }} />}
    </div>
  );
}

function LeaveFormModal({ onClose, onSuccess }) {
  const [type, setType] = useState("terlambat");
  const [dateStart, setDateStart] = useState(new Date().toISOString().slice(0, 10));
  const [dateEnd, setDateEnd] = useState("");
  const [timeMinutes, setTimeMinutes] = useState(30);
  const [timeStart, setTimeStart] = useState("18:00");
  const [timeEnd, setTimeEnd] = useState("20:00");
  const [reason, setReason] = useState("");
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const isSimpleSingleDay = type === "terlambat" || type === "pulang_awal";
  const isLembur = type === "lembur";
  const singleDay = isSimpleSingleDay || isLembur;

  const computedLemburMinutes = (() => {
    if (!isLembur) return 0;
    try {
      const [sh, sm] = timeStart.split(":").map(Number);
      const [eh, em] = timeEnd.split(":").map(Number);
      let diff = (eh * 60 + em) - (sh * 60 + sm);
      if (diff <= 0) diff += 24 * 60;
      return diff;
    } catch {
      return 0;
    }
  })();

  const submit = async (e) => {
    e.preventDefault();
    if (!reason.trim()) { toast.error("Alasan / deskripsi wajib diisi"); return; }
    if (isLembur && computedLemburMinutes <= 0) { toast.error("Jam selesai harus lebih besar dari jam mulai"); return; }

    const fd = new FormData();
    fd.append("type", type);
    fd.append("date_start", dateStart);
    if (!singleDay && dateEnd) fd.append("date_end", dateEnd);
    if (isSimpleSingleDay) fd.append("time_minutes", String(timeMinutes));
    if (isLembur) {
      fd.append("time_start", timeStart);
      fd.append("time_end", timeEnd);
    }
    fd.append("reason", reason);
    if (file) fd.append("file", file);

    setSubmitting(true);
    try {
      await api.post("/portal/leave", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Pengajuan berhasil dikirim ke HR");
      onSuccess();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal mengajukan");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white w-full max-w-2xl border border-zinc-200 max-h-[92vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Form Pengajuan</div>
            <h2 className="font-heading text-xl font-bold mt-0.5">Izin Baru</h2>
          </div>
          <button onClick={onClose} data-testid="close-leave-form" className="p-2 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
        </div>

        <form onSubmit={submit} className="p-6 space-y-5">
          {/* Type Selection */}
          <div>
            <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-2">Jenis Izin</label>
            <div className="grid grid-cols-2 gap-2">
              {LEAVE_TYPES.map((t) => {
                const Icon = t.icon;
                const active = type === t.value;
                return (
                  <button
                    type="button"
                    key={t.value}
                    data-testid={`leave-type-${t.value}`}
                    onClick={() => setType(t.value)}
                    className={`text-left border p-3 transition-colors ${active ? "border-[#002FA7] bg-[#002FA7]/5" : "border-zinc-300 hover:border-zinc-400"}`}
                  >
                    <div className="flex items-center gap-2">
                      <Icon className={`w-4 h-4 ${active ? "text-[#002FA7]" : "text-zinc-600"}`} />
                      <div className={`text-sm font-semibold ${active ? "text-[#002FA7]" : "text-zinc-900"}`}>{t.label}</div>
                    </div>
                    <div className="text-[11px] text-zinc-500 mt-1">{t.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Date Inputs */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">
                {singleDay ? "Tanggal" : "Tanggal Mulai"}
              </label>
              <input
                type="date"
                data-testid="leave-date-start"
                value={dateStart}
                onChange={(e) => setDateStart(e.target.value)}
                required
                className="w-full border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
              />
            </div>
            {!singleDay && (
              <div>
                <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">Tanggal Selesai</label>
                <input
                  type="date"
                  data-testid="leave-date-end"
                  value={dateEnd}
                  onChange={(e) => setDateEnd(e.target.value)}
                  className="w-full border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
                />
              </div>
            )}
            {isSimpleSingleDay && (
              <div>
                <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">Durasi (menit)</label>
                <input
                  type="number"
                  min="1"
                  step="5"
                  data-testid="leave-time-minutes"
                  value={timeMinutes}
                  onChange={(e) => setTimeMinutes(Number(e.target.value))}
                  required
                  className="w-full border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
                />
              </div>
            )}
          </div>

          {isLembur && (
            <div>
              <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">Jam Lembur</label>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <input
                    type="time"
                    data-testid="leave-time-start"
                    value={timeStart}
                    onChange={(e) => setTimeStart(e.target.value)}
                    required
                    className="w-full border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
                  />
                  <div className="text-[10px] text-zinc-500 mt-1 font-mono">Mulai</div>
                </div>
                <div>
                  <input
                    type="time"
                    data-testid="leave-time-end"
                    value={timeEnd}
                    onChange={(e) => setTimeEnd(e.target.value)}
                    required
                    className="w-full border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
                  />
                  <div className="text-[10px] text-zinc-500 mt-1 font-mono">Selesai</div>
                </div>
              </div>
              <div className="mt-2 text-xs text-zinc-600 font-mono">
                Durasi: <span className="font-semibold text-[#002FA7]">{Math.floor(computedLemburMinutes / 60)}j {computedLemburMinutes % 60}m</span>
                {computedLemburMinutes > 0 && <span className="ml-2 text-zinc-400">({computedLemburMinutes} menit)</span>}
              </div>
            </div>
          )}

          {/* Reason */}
          <div>
            <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">
              {isLembur ? "Deskripsi Pekerjaan" : "Alasan"}
            </label>
            <textarea
              data-testid="leave-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              required
              placeholder={isLembur ? "Jelaskan pekerjaan yang akan dilembur..." : "Jelaskan alasan pengajuan..."}
              className="w-full border border-zinc-300 px-3 py-2 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
            />
          </div>

          {/* File Upload */}
          <div>
            <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">
              Lampiran <span className="text-zinc-400 normal-case">(opsional)</span>
              {type === "sakit" && <span className="ml-2 text-[10px] text-amber-700 normal-case">— surat dokter disarankan</span>}
            </label>
            <div className="flex items-center gap-2">
              <label className="inline-flex items-center gap-2 border border-zinc-300 px-3 py-2 text-xs uppercase tracking-wider hover:bg-zinc-50 cursor-pointer">
                <Upload className="w-3.5 h-3.5" /> Pilih File
                <input
                  type="file"
                  data-testid="leave-file-input"
                  accept="application/pdf,image/png,image/jpeg,image/jpg"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  className="hidden"
                />
              </label>
              {file ? (
                <div className="text-xs text-zinc-700 truncate">
                  <span className="font-mono">{file.name}</span>
                  <span className="text-zinc-400 ml-2">{(file.size / 1024).toFixed(0)} KB</span>
                </div>
              ) : (
                <div className="text-xs text-zinc-400 font-mono">Belum ada file</div>
              )}
            </div>
            <div className="text-[10px] text-zinc-500 mt-1.5 font-mono">PDF / JPG / PNG · maks 2MB</div>
          </div>

          <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
            <button type="button" onClick={onClose} className="border border-zinc-300 px-4 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-50">Batal</button>
            <button
              type="submit"
              data-testid="submit-leave"
              disabled={submitting}
              className="bg-[#002FA7] text-white px-5 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-[#002FA7]/90 disabled:opacity-50"
            >
              {submitting ? "Mengirim…" : "Kirim Pengajuan"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
