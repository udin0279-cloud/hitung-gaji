import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { usePortalAuth } from "../context/PortalAuthContext";
import { toast } from "sonner";
import { formatApiError } from "../lib/api";
import { ArrowRight, IdCard } from "lucide-react";

export default function PortalLogin() {
  const { employee, login } = usePortalAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [nik, setNik] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => { if (employee) navigate("/portal"); }, [employee, navigate]);

  const onSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, nik);
      toast.success("Berhasil masuk");
      navigate("/portal");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal masuk");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-white">
      <div className="hidden lg:flex flex-col justify-between p-12 bg-[#002FA7] text-white relative overflow-hidden">
        <div className="absolute inset-0 opacity-10" style={{backgroundImage: "linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)", backgroundSize: "40px 40px"}} />
        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-white flex items-center justify-center">
              <IdCard className="w-4 h-4 text-[#002FA7]" />
            </div>
            <div>
              <div className="font-heading font-black text-xl tracking-tight">HRIS</div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-white/70">Employee Portal</div>
            </div>
          </div>
        </div>

        <div className="relative">
          <h1 className="font-heading text-5xl xl:text-6xl font-black tracking-tighter leading-[0.95]">
            Slip gaji<br />Anda,<br />
            <span className="text-white/70">kapan saja.</span>
          </h1>
          <p className="mt-6 text-white/80 text-sm max-w-md leading-relaxed">
            Akses seluruh riwayat slip gaji bulanan dan THR secara mandiri. Unduh PDF langsung tanpa harus menunggu dari HR.
          </p>
        </div>

        <div className="relative text-xs text-white/60">
          Portal khusus karyawan. HR/Admin → <Link to="/login" className="underline">login admin</Link>
        </div>
      </div>

      <div className="flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Portal Karyawan</div>
          <h2 className="font-heading text-3xl font-bold tracking-tight text-zinc-900 mt-2">Masuk dengan NIK</h2>
          <p className="text-sm text-zinc-500 mt-2">Gunakan email yang terdaftar di HR dan NIK Anda.</p>

          <form onSubmit={onSubmit} className="mt-8 space-y-5">
            <div>
              <label className="block text-xs font-semibold text-zinc-900 uppercase tracking-wider mb-1.5">Email</label>
              <input
                data-testid="portal-email-input"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="rounded-none border border-zinc-300 bg-white px-3 py-2.5 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none w-full"
                placeholder="anda@perusahaan.com"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-zinc-900 uppercase tracking-wider mb-1.5">NIK</label>
              <input
                data-testid="portal-nik-input"
                type="text"
                required
                value={nik}
                onChange={(e) => setNik(e.target.value)}
                className="rounded-none border border-zinc-300 bg-white px-3 py-2.5 text-sm font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none w-full"
                placeholder="EMP001"
              />
            </div>
            <button
              data-testid="portal-submit-button"
              type="submit"
              disabled={loading}
              className="rounded-none w-full bg-[#002FA7] text-white px-5 py-3 font-semibold hover:bg-[#002FA7]/90 inline-flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {loading ? "Memproses…" : (<>Masuk Portal <ArrowRight className="w-4 h-4" /></>)}
            </button>
          </form>

          <div className="mt-8 p-4 border border-zinc-200 bg-zinc-50">
            <div className="text-[10px] uppercase tracking-widest font-semibold text-zinc-500">Belum bisa masuk?</div>
            <div className="text-xs text-zinc-700 mt-1">Pastikan HR sudah mendaftarkan email Anda. Jika lupa NIK, hubungi tim HR.</div>
          </div>

          <div className="mt-4 text-center">
            <Link to="/portal/forgot" data-testid="forgot-nik-link" className="text-sm font-semibold text-[#002FA7] hover:underline">
              Lupa NIK? Kirim link via email →
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
