import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import { ChevronLeft, Eye, Mail, Download, MessageCircle } from "lucide-react";

export default function PayrollDetail() {
  const { period } = useParams();
  const [slips, setSlips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [emailing, setEmailing] = useState(false);
  const [emailResult, setEmailResult] = useState(null);
  const [bankFmt, setBankFmt] = useState("generic");
  const [waSending, setWaSending] = useState(false);
  const [waResult, setWaResult] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(`/payroll/runs/${period}/slips`);
        setSlips(data);
      } finally {
        setLoading(false);
      }
    })();
  }, [period]);

  const totals = slips.reduce(
    (acc, s) => ({
      gross: acc.gross + s.earnings.gross,
      net: acc.net + s.net_salary,
      pph: acc.pph + s.deductions.pph21,
      bpjs: acc.bpjs + s.deductions.bpjs_kesehatan_employee + s.deductions.jht_employee + s.deductions.jp_employee,
    }),
    { gross: 0, net: 0, pph: 0, bpjs: 0 }
  );

  const emailAll = async () => {
    if (!window.confirm(`Kirim slip gaji ke semua karyawan periode ${period}?`)) return;
    setEmailing(true);
    setEmailResult(null);
    try {
      const { data } = await api.post(`/payroll/runs/${period}/email-all`);
      setEmailResult(data);
      toast.success(`Email: ${data.sent} terkirim · ${data.mocked} mock · ${data.skipped_no_email} dilewati`);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal kirim");
    } finally {
      setEmailing(false);
    }
  };

  const sendWaAll = async () => {
    if (!window.confirm(`Kirim WhatsApp ke semua karyawan periode ${period}?\n\n(Pengiriman bertahap, ~0.3 detik per pesan untuk hormati limit Fonnte.)`)) return;
    setWaSending(true);
    setWaResult(null);
    try {
      const { data } = await api.post(`/payroll/runs/${period}/whatsapp-all`);
      setWaResult(data);
      toast.success(`WA: ${data.sent} terkirim · ${data.mocked} mock · ${data.skipped_no_phone} tanpa no.HP · ${data.failed} gagal`);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal kirim WhatsApp");
    } finally {
      setWaSending(false);
    }
  };

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
      <Link to="/payroll" className="inline-flex items-center gap-1 text-xs uppercase tracking-widest text-zinc-500 hover:text-zinc-900 font-semibold">
        <ChevronLeft className="w-3.5 h-3.5" /> Kembali ke Payroll
      </Link>
      <div className="mt-3 pb-6 border-b border-zinc-200 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Detail Periode</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Payroll {period}</h1>
          <p className="text-sm text-zinc-500 mt-1">{slips.length} slip gaji.</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="block">
            <span className="block text-[10px] font-semibold text-zinc-900 uppercase tracking-wider mb-1">Format Bank</span>
            <select
              data-testid="bank-format-select"
              value={bankFmt}
              onChange={(e) => setBankFmt(e.target.value)}
              className="rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
            >
              <option value="generic">Generik CSV</option>
              <option value="bca">BCA</option>
              <option value="mandiri">Mandiri</option>
              <option value="bni">BNI</option>
              <option value="bri">BRI</option>
            </select>
          </label>
          <a
            data-testid="bank-export-button"
            href={`${API}/payroll/runs/${period}/bank-export?format=${bankFmt}`}
            target="_blank"
            rel="noreferrer"
            className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-4 py-2 text-sm font-semibold hover:bg-zinc-50 inline-flex items-center gap-2"
          >
            <Download className="w-4 h-4" /> Export Bank
          </a>
          <button
            data-testid="email-all-button"
            onClick={emailAll}
            disabled={emailing}
            className="rounded-none bg-[#002FA7] text-white px-4 py-2 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2 disabled:opacity-60"
          >
            <Mail className="w-4 h-4" /> {emailing ? "Mengirim…" : "Kirim Email ke Semua"}
          </button>
          <button
            data-testid="wa-all-button"
            onClick={sendWaAll}
            disabled={waSending}
            className="rounded-none bg-[#25D366] text-white px-4 py-2 text-sm font-semibold hover:bg-[#25D366]/90 inline-flex items-center gap-2 disabled:opacity-60"
          >
            <MessageCircle className="w-4 h-4" /> {waSending ? "Mengirim…" : "Kirim WhatsApp ke Semua"}
          </button>
        </div>
      </div>

      {emailResult && (
        <div className="mt-4 p-4 border border-zinc-200 bg-zinc-50">
          <div className="text-[11px] uppercase tracking-widest font-semibold text-zinc-500">Hasil Kirim Email</div>
          <div className="font-mono text-sm text-zinc-900 mt-1">
            {emailResult.sent} terkirim · {emailResult.mocked} mock (key belum diatur) · {emailResult.failed} gagal · {emailResult.skipped_no_email} tanpa email
          </div>
          {emailResult.details?.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs cursor-pointer text-zinc-600 font-semibold">Lihat detail</summary>
              <ul className="mt-2 text-xs font-mono space-y-0.5 max-h-48 overflow-y-auto">
                {emailResult.details.map((d, i) => (
                  <li key={i} className={d.status === "sent" ? "text-[#008A00]" : d.status === "failed" ? "text-[#E81123]" : "text-zinc-600"}>
                    [{d.status}] {d.name} {d.email ? `· ${d.email}` : ""} {d.reason ? `· ${d.reason}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {waResult && (
        <div className="mt-4 p-4 border border-[#25D366]/30 bg-[#25D366]/5">
          <div className="text-[11px] uppercase tracking-widest font-semibold text-[#0a6b3a]">Hasil Kirim WhatsApp</div>
          <div className="font-mono text-sm text-zinc-900 mt-1">
            {waResult.sent} terkirim · {waResult.mocked} mock (Fonnte token belum diatur) · {waResult.failed} gagal · {waResult.skipped_no_phone} tanpa no.HP
          </div>
          {waResult.details?.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs cursor-pointer text-zinc-600 font-semibold">Lihat detail</summary>
              <ul className="mt-2 text-xs font-mono space-y-0.5 max-h-48 overflow-y-auto">
                {waResult.details.map((d, i) => (
                  <li key={i} className={d.status === "sent" ? "text-[#008A00]" : d.status === "failed" ? "text-[#E81123]" : "text-zinc-600"}>
                    [{d.status}] {d.name} {d.phone ? `· ${d.phone}` : ""} {d.reason ? `· ${d.reason}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <div className="mt-6 grid grid-cols-1 md:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
        <Stat label="Total Bruto" value={formatIDR(totals.gross)} />
        <Stat label="BPJS Karyawan" value={formatIDR(totals.bpjs)} />
        <Stat label="PPh 21" value={formatIDR(totals.pph)} />
        <Stat label="Take Home" value={formatIDR(totals.net)} highlight />
      </div>

      <div className="mt-6 border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">NIK</th>
              <th className="px-4 py-3">Karyawan</th>
              <th className="px-4 py-3">Departemen</th>
              <th className="px-4 py-3 text-right">Bruto</th>
              <th className="px-4 py-3 text-right">PPh 21</th>
              <th className="px-4 py-3 text-right">Take Home</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {slips.map((s) => (
              <tr key={s.id} className="border-b border-zinc-100 hover:bg-zinc-50/80">
                <td className="px-4 py-3 font-mono text-xs text-zinc-700">{s.nik}</td>
                <td className="px-4 py-3">
                  <div className="font-medium text-zinc-900">{s.name}</div>
                  <div className="text-xs text-zinc-500">{s.position} · {s.ptkp_status}</div>
                </td>
                <td className="px-4 py-3 text-zinc-700">{s.department}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900">{formatIDR(s.earnings.gross)}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(s.deductions.pph21)}</td>
                <td className="px-4 py-3 font-mono text-right font-semibold text-zinc-900">{formatIDR(s.net_salary)}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <Link
                      to={`/payslip/${s.id}`}
                      data-testid="view-payslip-button"
                      className="inline-flex items-center gap-1 px-2.5 py-1 border border-zinc-300 hover:border-zinc-900 hover:bg-zinc-900 hover:text-white text-xs font-semibold uppercase tracking-wider transition-colors"
                    >
                      <Eye className="w-3 h-3" /> Lihat
                    </Link>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, highlight }) {
  return (
    <div className="bg-white p-5">
      <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
      <div className={`font-mono mt-2 ${highlight ? "text-2xl font-semibold text-[#002FA7]" : "text-xl text-zinc-900"}`}>{value}</div>
    </div>
  );
}
