import { useEffect, useState } from "react";
import { api, formatIDR } from "../lib/api";
import { Link } from "react-router-dom";
import { TrendingUp, Users, FileText, Receipt, ArrowUpRight } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid } from "recharts";

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/dashboard/stats");
        setStats(data);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const latest = stats?.latest_run;

  return (
    <div className="px-6 lg:px-10 py-8 max-w-7xl">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Overview</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Dashboard Payroll</h1>
          <p className="text-sm text-zinc-500 mt-1">Ringkasan operasi gaji, pajak PPh 21, dan iuran BPJS.</p>
        </div>
        <Link
          to="/payroll"
          data-testid="run-payroll-button"
          className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold transition-colors hover:bg-[#002FA7]/90 inline-flex items-center gap-2"
        >
          Jalankan Payroll <ArrowUpRight className="w-4 h-4" />
        </Link>
      </div>

      {/* Hero stat */}
      <div className="mt-8 border border-zinc-200 bg-white p-6 lg:p-8 fade-up">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Total Payroll {latest ? `Periode ${latest.period}` : "(Belum ada)"}</div>
        <div data-testid="stat-total-payroll" className="font-mono text-5xl lg:text-6xl tracking-tighter font-semibold text-zinc-900 mt-3">
          {formatIDR(latest?.total_net || 0)}
        </div>
        <div className="text-xs text-zinc-500 mt-2 font-mono">
          {latest ? `Gaji bersih untuk ${latest.employee_count} karyawan` : "Belum ada periode payroll yang dijalankan"}
        </div>
      </div>

      {/* Stat grid */}
      <div className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-px bg-zinc-200 border border-zinc-200">
        <StatCard
          testId="stat-total-employees"
          label="Karyawan Aktif"
          value={stats?.total_employees ?? 0}
          icon={Users}
          isCount
        />
        <StatCard
          testId="stat-total-gross"
          label="Total Bruto"
          value={latest?.total_gross || 0}
          icon={TrendingUp}
        />
        <StatCard
          testId="stat-tax-summary"
          label="PPh 21 Bulan Ini"
          value={latest?.total_pph21 || 0}
          icon={Receipt}
        />
        <StatCard
          testId="stat-bpjs-summary"
          label="BPJS Karyawan"
          value={latest?.total_bpjs_employee || 0}
          icon={FileText}
        />
      </div>

      {/* Trend chart */}
      <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 border border-zinc-200 bg-white p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Tren Payroll</div>
              <div className="font-heading text-lg font-bold text-zinc-900 mt-1">12 Periode Terakhir</div>
            </div>
          </div>
          <div className="h-64">
            {stats?.trend?.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={stats.trend} margin={{ top: 5, right: 10, bottom: 0, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" vertical={false} />
                  <XAxis dataKey="period" tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }} stroke="#a1a1aa" />
                  <YAxis tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }} stroke="#a1a1aa" tickFormatter={(v) => `${(v / 1_000_000).toFixed(0)}jt`} />
                  <Tooltip formatter={(v) => formatIDR(v)} contentStyle={{ borderRadius: 0, border: "1px solid #d4d4d8", fontFamily: "JetBrains Mono", fontSize: 12 }} />
                  <Line type="monotone" dataKey="total_net" stroke="#002FA7" strokeWidth={2} dot={{ r: 3, fill: "#002FA7" }} name="Net" />
                  <Line type="monotone" dataKey="total_gross" stroke="#a1a1aa" strokeWidth={1.5} strokeDasharray="4 4" dot={false} name="Gross" />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-sm text-zinc-400 font-mono">
                Belum ada data tren.
              </div>
            )}
          </div>
        </div>

        <div className="border border-zinc-200 bg-white p-6">
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Aksi Cepat</div>
          <div className="font-heading text-lg font-bold text-zinc-900 mt-1 mb-4">Mulai dari sini</div>
          <div className="space-y-2">
            <QuickLink to="/employees" label="Tambah Karyawan" desc="Kelola data NIK, gaji, PTKP" />
            <QuickLink to="/payroll" label="Generate Payroll" desc="Hitung gaji bulanan otomatis" />
            <QuickLink to="/settings" label="Lihat Konfigurasi" desc="PPh 21 brackets, BPJS rates" />
          </div>
        </div>
      </div>

      {loading && <div className="mt-6 text-xs text-zinc-400 font-mono">Memuat…</div>}
    </div>
  );
}

function StatCard({ label, value, icon: Icon, testId, isCount }) {
  return (
    <div className="bg-white p-5 lg:p-6">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{label}</div>
        <Icon className="w-3.5 h-3.5 text-zinc-400" />
      </div>
      <div data-testid={testId} className="font-mono text-2xl lg:text-3xl tracking-tight font-semibold text-zinc-900 mt-3">
        {isCount ? value : formatIDR(value)}
      </div>
    </div>
  );
}

function QuickLink({ to, label, desc }) {
  return (
    <Link to={to} className="block border border-zinc-200 hover:border-zinc-900 transition-colors p-3 group">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-zinc-900">{label}</div>
          <div className="text-xs text-zinc-500 mt-0.5">{desc}</div>
        </div>
        <ArrowUpRight className="w-4 h-4 text-zinc-400 group-hover:text-zinc-900 transition-colors" />
      </div>
    </Link>
  );
}
