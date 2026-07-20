import { Link } from "react-router-dom";
import { ShieldAlert } from "lucide-react";

export default function AccessDenied({ menuLabel }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-50 px-4">
      <div className="max-w-lg text-center border border-zinc-200 bg-white p-8 sm:p-12 shadow-sm">
        <div className="w-14 h-14 mx-auto bg-[#E81123]/10 flex items-center justify-center mb-5 border border-[#E81123]/30">
          <ShieldAlert className="w-7 h-7 text-[#E81123]" strokeWidth={2} />
        </div>
        <div className="text-[10px] uppercase tracking-widest font-bold text-[#E81123]">403</div>
        <h1 data-testid="access-denied-title" className="font-heading text-3xl font-bold text-zinc-900 mt-2">Akses Ditolak</h1>
        <p className="text-sm text-zinc-500 mt-3">
          Anda tidak memiliki hak akses untuk membuka {menuLabel ? <b>{menuLabel}</b> : "menu ini"}.
          Hubungi Super Admin untuk meminta akses.
        </p>
        <Link
          to="/"
          data-testid="access-denied-home"
          className="inline-block mt-6 border border-zinc-900 bg-zinc-900 text-white px-5 py-2.5 text-xs font-bold uppercase tracking-widest hover:bg-zinc-700"
        >
          Kembali ke Beranda
        </Link>
      </div>
    </div>
  );
}
