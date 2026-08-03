import { useEffect, useState } from "react";
import { Download, HardDrive, ShieldCheck, Clock3, Users, Package, DollarSign, FileArchive, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import { useAuth } from "../context/AuthContext";

// Format tanggal ISO → "01 Agu 2026, 09:30"
function formatDT(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const mons = ["Jan","Feb","Mar","Apr","Mei","Jun","Jul","Agu","Sep","Okt","Nov","Des"];
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = mons[d.getMonth()];
    const yy = d.getFullYear();
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${dd} ${mm} ${yy}, ${hh}:${mi}`;
  } catch {
    return iso;
  }
}

function formatSize(bytes) {
  if (bytes == null) return "—";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(2)} MB`;
}

export default function BackupCenter() {
  const { user } = useAuth();
  const [logs, setLogs] = useState([]);
  const [totalLogs, setTotalLogs] = useState(0);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const loadLogs = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/backup/logs");
      setLogs(data.items || []);
      setTotalLogs(data.total || 0);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal memuat riwayat backup");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, []);

  const doBackup = async () => {
    if (!window.confirm("Buat backup semua data sekarang?\n\nSemua tabel akan diarsipkan ke file .zip berisi JSON per koleksi.")) return;
    setDownloading(true);
    try {
      const res = await api.post("/backup/download", null, { responseType: "blob" });
      // Extract filename from Content-Disposition
      const cd = res.headers?.["content-disposition"] || "";
      const match = cd.match(/filename=([^;]+)/i);
      const filename = match ? match[1].trim().replace(/"/g, "") : `backup_${new Date().toISOString().slice(0, 19).replace(/[:.]/g, "-")}.zip`;
      const totalRecords = res.headers?.["x-backup-total-records"];
      const totalCollections = res.headers?.["x-backup-total-collections"];

      const blob = new Blob([res.data], { type: "application/zip" });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      toast.success(`Backup berhasil: ${totalRecords} record dari ${totalCollections} koleksi (${filename})`);
      await loadLogs();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || "Gagal membuat backup";
      toast.error(typeof msg === "string" ? msg : "Gagal membuat backup");
    } finally {
      setDownloading(false);
    }
  };

  // Guard: hanya super_admin
  if (user?.role !== "super_admin") {
    return (
      <div className="px-4 sm:px-6 lg:px-10 py-8 max-w-4xl">
        <div className="border border-[#E81123] bg-[#E81123]/5 p-6">
          <div className="text-[11px] uppercase tracking-widest text-[#E81123] font-bold mb-1">Akses Ditolak</div>
          <h1 className="font-heading text-2xl font-bold text-zinc-900">Menu ini hanya untuk Super Admin</h1>
          <p className="text-sm text-zinc-600 mt-2">Silakan hubungi Super Admin bila membutuhkan backup data.</p>
        </div>
      </div>
    );
  }

  const lastBackup = logs[0];
  const totalRecordsAllBackups = logs.reduce((s, l) => s + (l.total_records || 0), 0);
  const totalBytesAllBackups = logs.reduce((s, l) => s + (l.file_size_bytes || 0), 0);

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl" data-testid="backup-center-page">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Administrasi · Super Admin Only</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1 flex items-center gap-3">
            <HardDrive className="w-8 h-8 text-[#002FA7]" />
            Pusat Backup Data
          </h1>
          <p className="text-sm text-zinc-500 mt-1">
            Arsipkan semua data database (attendance, payroll, sales, users, dst) ke file <code className="bg-zinc-100 px-1.5 py-0.5 rounded text-xs">.zip</code> berisi JSON per koleksi.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            data-testid="backup-refresh-logs"
            onClick={loadLogs}
            disabled={loading}
            className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-xs font-semibold uppercase tracking-wider text-zinc-700 hover:bg-zinc-50 inline-flex items-center gap-2 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Muat Ulang
          </button>
          <button
            data-testid="backup-download-btn"
            onClick={doBackup}
            disabled={downloading}
            className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-bold uppercase tracking-wider hover:bg-[#002FA7]/90 inline-flex items-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <Download className={`w-4 h-4 ${downloading ? "animate-pulse" : ""}`} />
            {downloading ? "Membuat Backup…" : "Download Backup (.zip)"}
          </button>
        </div>
      </div>

      {/* Info cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-6">
        <div className="border border-zinc-200 bg-white p-4" data-testid="stat-total-backups">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-bold text-zinc-500">
            <FileArchive className="w-3.5 h-3.5" /> Total Backup
          </div>
          <div className="font-heading text-3xl font-bold text-zinc-900 mt-2 font-mono">{totalLogs}</div>
          <div className="text-xs text-zinc-500 mt-1">seluruh riwayat</div>
        </div>
        <div className="border border-zinc-200 bg-white p-4" data-testid="stat-last-backup">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-bold text-zinc-500">
            <Clock3 className="w-3.5 h-3.5" /> Backup Terakhir
          </div>
          <div className="font-heading text-lg font-bold text-zinc-900 mt-2">
            {lastBackup ? formatDT(lastBackup.created_at) : "Belum ada"}
          </div>
          <div className="text-xs text-zinc-500 mt-1">
            {lastBackup ? `oleh ${lastBackup.created_by}` : "—"}
          </div>
        </div>
        <div className="border border-zinc-200 bg-white p-4" data-testid="stat-total-records">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-bold text-zinc-500">
            <DollarSign className="w-3.5 h-3.5" /> Record ter-arsip
          </div>
          <div className="font-heading text-3xl font-bold text-zinc-900 mt-2 font-mono">{totalRecordsAllBackups.toLocaleString("id-ID")}</div>
          <div className="text-xs text-zinc-500 mt-1">kumulatif seluruh backup</div>
        </div>
        <div className="border border-zinc-200 bg-white p-4" data-testid="stat-total-size">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-bold text-zinc-500">
            <HardDrive className="w-3.5 h-3.5" /> Total Ukuran File
          </div>
          <div className="font-heading text-3xl font-bold text-zinc-900 mt-2 font-mono">{formatSize(totalBytesAllBackups)}</div>
          <div className="text-xs text-zinc-500 mt-1">akumulasi semua ZIP</div>
        </div>
      </div>

      {/* Info box */}
      <div className="mt-6 border border-[#002FA7]/30 bg-[#002FA7]/5 p-4 text-xs text-zinc-700">
        <div className="flex items-start gap-2">
          <ShieldCheck className="w-4 h-4 text-[#002FA7] mt-0.5 shrink-0" />
          <div>
            <div className="font-bold text-[#002FA7] uppercase tracking-widest text-[10px] mb-1">Data yang di-backup</div>
            Semua koleksi database — termasuk <b>attendance_daily</b>, <b>attendance_imports</b>, <b>payroll_runs</b>, <b>payslips</b>, <b>sales</b>, <b>users</b>, <b>products</b>, <b>cash_accounts</b>, <b>cash_transactions</b>, dan lainnya.
            Struktur JSON dipertahankan agar bisa di-restore/import kembali.
            File akan otomatis ter-download ke device Anda. <b>Simpan di lokasi yang aman</b> (external drive / cloud storage).
          </div>
        </div>
      </div>

      {/* Log table */}
      <div className="mt-8">
        <div className="flex items-end justify-between mb-3">
          <div>
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Riwayat Backup</div>
            <h2 className="font-heading text-xl font-bold text-zinc-900">Log Aktivitas</h2>
          </div>
          <div className="text-xs text-zinc-500 font-mono">{totalLogs} entri tercatat</div>
        </div>

        <div className="border border-zinc-900 bg-white overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-zinc-900 text-white text-[11px] font-bold uppercase tracking-widest">
                <th className="px-3 py-3 border-r border-zinc-700">#</th>
                <th className="px-3 py-3 border-r border-zinc-700 whitespace-nowrap">Tanggal & Jam</th>
                <th className="px-3 py-3 border-r border-zinc-700">User</th>
                <th className="px-3 py-3 border-r border-zinc-700 text-right whitespace-nowrap">Koleksi</th>
                <th className="px-3 py-3 border-r border-zinc-700 text-right whitespace-nowrap">Record</th>
                <th className="px-3 py-3 border-r border-zinc-700 text-right whitespace-nowrap">Ukuran</th>
                <th className="px-3 py-3">Nama File</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={7} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>
              )}
              {!loading && logs.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-zinc-400 font-mono text-xs">
                  Belum ada backup. Klik <b className="text-[#002FA7]">Download Backup (.zip)</b> di kanan atas untuk memulai.
                </td></tr>
              )}
              {logs.map((l, idx) => (
                <tr key={l.id} data-testid={`backup-log-row-${l.id}`} className="border-b border-zinc-100 hover:bg-zinc-50">
                  <td className="px-3 py-2.5 font-mono text-xs text-zinc-500">{idx + 1}</td>
                  <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap">{formatDT(l.created_at)}</td>
                  <td className="px-3 py-2.5 text-xs">
                    <div className="font-semibold text-zinc-900">{l.created_by_name || "—"}</div>
                    <div className="text-zinc-500 font-mono text-[11px]">{l.created_by}</div>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs">{l.total_collections}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs font-bold text-zinc-900">{(l.total_records || 0).toLocaleString("id-ID")}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs">{formatSize(l.file_size_bytes)}</td>
                  <td className="px-3 py-2.5 text-xs font-mono text-zinc-600">{l.filename}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
