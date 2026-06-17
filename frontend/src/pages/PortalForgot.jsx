import { useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiError } from "../lib/api";
import { toast } from "sonner";
import { ArrowRight, ChevronLeft, Mail } from "lucide-react";

export default function PortalForgot() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await api.post("/portal/forgot", { email });
      setSent(data);
      toast.success("Email link sudah dikirim (jika email terdaftar)");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal mengirim");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-white flex items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <Link to="/portal/login" className="inline-flex items-center gap-1 text-xs uppercase tracking-widest text-zinc-500 hover:text-zinc-900 font-semibold">
          <ChevronLeft className="w-3.5 h-3.5" /> Kembali ke Login
        </Link>

        <div className="mt-6">
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Lupa NIK?</div>
          <h2 className="font-heading text-3xl font-bold tracking-tight text-zinc-900 mt-2">Kirim Link Masuk</h2>
          <p className="text-sm text-zinc-500 mt-2">Masukkan email Anda yang terdaftar di HR. Kami akan kirim tautan masuk satu kali (berlaku 30 menit).</p>
        </div>

        {!sent && (
          <form onSubmit={submit} className="mt-8 space-y-5">
            <div>
              <label className="block text-xs font-semibold text-zinc-900 uppercase tracking-wider mb-1.5">Email Terdaftar</label>
              <input
                data-testid="forgot-email-input"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="rounded-none border border-zinc-300 bg-white px-3 py-2.5 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none w-full"
                placeholder="anda@perusahaan.com"
              />
            </div>
            <button
              data-testid="forgot-submit-button"
              type="submit"
              disabled={loading}
              className="rounded-none w-full bg-[#002FA7] text-white px-5 py-3 font-semibold hover:bg-[#002FA7]/90 inline-flex items-center justify-center gap-2 disabled:opacity-60"
            >
              <Mail className="w-4 h-4" /> {loading ? "Mengirim…" : "Kirim Tautan Masuk"} <ArrowRight className="w-4 h-4" />
            </button>
          </form>
        )}

        {sent && (
          <div className="mt-8 p-5 border border-zinc-200 bg-zinc-50">
            <div className="text-[11px] uppercase tracking-widest font-semibold text-[#008A00]">Tautan Terkirim</div>
            <p className="text-sm text-zinc-700 mt-2 leading-relaxed">
              Jika email Anda terdaftar, link masuk satu kali sudah dikirim. Cek inbox (atau folder spam) dan klik tombol "Masuk ke Portal" di email.
            </p>
            {sent.status === "mocked" && sent.magic_link_preview && (
              <div className="mt-4 p-3 border border-amber-300 bg-amber-50">
                <div className="text-[10px] uppercase tracking-widest font-bold text-amber-700">Mode Demo (API Email Belum Diatur)</div>
                <div className="mt-2 text-xs text-zinc-700">Klik link berikut untuk simulasi masuk:</div>
                <a
                  href={sent.magic_link_preview}
                  data-testid="mock-magic-link"
                  className="mt-2 inline-block text-xs text-[#002FA7] font-mono underline break-all"
                >{sent.magic_link_preview}</a>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
