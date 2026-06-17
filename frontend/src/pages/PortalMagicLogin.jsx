import { useEffect, useState } from "react";
import { useSearchParams, useNavigate, Link } from "react-router-dom";
import { api, formatApiError } from "../lib/api";
import { usePortalAuth } from "../context/PortalAuthContext";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";

export default function PortalMagicLogin() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { setEmployee } = usePortalAuth() ?? {};
  const [status, setStatus] = useState("verifying"); // verifying | success | error
  const [message, setMessage] = useState("");

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setStatus("error");
      setMessage("Token tidak ditemukan dalam URL.");
      return;
    }
    (async () => {
      try {
        const { data } = await api.post(`/portal/magic-login?token=${encodeURIComponent(token)}`);
        if (setEmployee) setEmployee(data);
        setStatus("success");
        toast.success(`Selamat datang, ${data.name}`);
        // Full reload to /portal — ensures PortalAuthProvider re-fetches /portal/me with the new cookie
        setTimeout(() => { window.location.href = "/portal"; }, 600);
      } catch (err) {
        setStatus("error");
        setMessage(formatApiError(err.response?.data?.detail) || "Link tidak valid atau kedaluwarsa.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen bg-white flex items-center justify-center p-6">
      <div className="w-full max-w-sm text-center">
        {status === "verifying" && (
          <>
            <Loader2 className="w-8 h-8 mx-auto animate-spin text-[#002FA7]" />
            <div className="mt-4 text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Memverifikasi</div>
            <div className="font-heading text-xl font-bold text-zinc-900 mt-1">Sedang memproses link masuk…</div>
          </>
        )}
        {status === "success" && (
          <>
            <div className="text-[11px] uppercase tracking-widest text-[#008A00] font-semibold">Berhasil</div>
            <div className="font-heading text-xl font-bold text-zinc-900 mt-1">Mengarahkan ke portal…</div>
          </>
        )}
        {status === "error" && (
          <>
            <div className="text-[11px] uppercase tracking-widest text-[#E81123] font-semibold">Gagal</div>
            <div className="font-heading text-xl font-bold text-zinc-900 mt-1">{message}</div>
            <Link to="/portal/forgot" className="mt-4 inline-block text-sm font-semibold text-[#002FA7] hover:underline">Minta link baru →</Link>
          </>
        )}
      </div>
    </div>
  );
}
