import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { toast } from "sonner";
import { formatApiError } from "../lib/api";
import { ArrowRight, Square } from "lucide-react";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@payroll.id");
  const [password, setPassword] = useState("admin123");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (user) navigate("/");
  }, [user, navigate]);

  const onSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      toast.success("Berhasil masuk");
      navigate("/");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal masuk");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-white">
      {/* Left brand panel */}
      <div className="hidden lg:flex flex-col justify-between p-12 bg-zinc-900 text-white relative overflow-hidden">
        <div className="absolute inset-0 opacity-[0.04]" style={{backgroundImage: "linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)", backgroundSize: "40px 40px"}} />
        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-white flex items-center justify-center">
              <Square className="w-4 h-4 text-zinc-900" fill="currentColor" />
            </div>
            <div>
              <div className="font-heading font-black text-xl tracking-tight">PAYROLL.ID</div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-400">HR · Tax · BPJS Console</div>
            </div>
          </div>
        </div>

        <div className="relative">
          <h1 className="font-heading text-5xl xl:text-6xl font-black tracking-tighter leading-[0.95]">
            Hitung gaji<br />karyawan<br />
            <span className="text-[#7DD3FC]">otomatis.</span>
          </h1>
          <p className="mt-6 text-zinc-400 text-sm max-w-md leading-relaxed">
            Sistem payroll lengkap dengan perhitungan PPh 21 progresif, BPJS Kesehatan & Ketenagakerjaan, lembur, dan slip gaji siap cetak — sesuai regulasi Indonesia.
          </p>
        </div>

        <div className="relative grid grid-cols-3 gap-px bg-zinc-800 border border-zinc-800">
          {[
            { label: "PPh 21", value: "UU HPP" },
            { label: "BPJS", value: "Kes + TK" },
            { label: "PTKP", value: "2024" },
          ].map((s) => (
            <div key={s.label} className="bg-zinc-900 p-4">
              <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">{s.label}</div>
              <div className="font-mono text-sm mt-1 text-white">{s.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Right form */}
      <div className="flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Masuk ke sistem</div>
          <h2 className="font-heading text-3xl font-bold tracking-tight text-zinc-900 mt-2">HR Console</h2>
          <p className="text-sm text-zinc-500 mt-2">Gunakan kredensial admin yang sudah disediakan.</p>

          <form onSubmit={onSubmit} className="mt-8 space-y-5">
            <div>
              <label className="block text-xs font-semibold text-zinc-900 uppercase tracking-wider mb-1.5">Email</label>
              <input
                data-testid="login-email-input"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="rounded-none border border-zinc-300 bg-white px-3 py-2.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none w-full"
                placeholder="admin@payroll.id"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-zinc-900 uppercase tracking-wider mb-1.5">Password</label>
              <input
                data-testid="login-password-input"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-none border border-zinc-300 bg-white px-3 py-2.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none w-full"
                placeholder="••••••••"
              />
            </div>
            <button
              data-testid="login-submit-button"
              type="submit"
              disabled={loading}
              className="rounded-none w-full bg-[#002FA7] text-white px-5 py-3 font-semibold transition-colors hover:bg-[#002FA7]/90 focus:ring-2 focus:ring-[#002FA7]/30 focus:outline-none flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {loading ? "Memproses…" : (<>Masuk <ArrowRight className="w-4 h-4" /></>)}
            </button>
          </form>

          <div className="mt-8 p-4 border border-zinc-200 bg-zinc-50">
            <div className="text-[10px] uppercase tracking-widest font-semibold text-zinc-500">Demo Account</div>
            <div className="mt-1.5 font-mono text-xs text-zinc-700">admin@payroll.id / admin123</div>
          </div>

          <div className="mt-4 text-xs text-zinc-500 text-center">
            Karyawan? <Link to="/portal/login" data-testid="goto-portal-link" className="font-semibold text-[#002FA7] hover:underline">Masuk Portal Karyawan →</Link>
          </div>
        </div>
      </div>
    </div>
  );
}
