import { useEffect, useState } from "react";
import { api, formatIDR } from "../lib/api";
import { Link } from "react-router-dom";
import { TrendingUp, Users, FileText, Receipt, ArrowUpRight, AlertTriangle, Package, TrendingDown } from "lucide-react";
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
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
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

      {/* Reminder Kontrak/OJT */}
      <ContractReminder items={stats?.contract_expiring} total={stats?.contract_expiring_count} />

      {/* Inventory Widget */}
      <InventoryWidget inv={stats?.inventory} />

      {loading && <div className="mt-6 text-xs text-zinc-400 font-mono">Memuat…</div>}
    </div>
  );
}

function InventoryWidget({ inv }) {
  if (!inv) return null;
  return (
    <div data-testid="inventory-widget" className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-1 border border-zinc-200 bg-white p-6">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold flex items-center gap-2">
          <Package className="w-3.5 h-3.5" /> Inventory
        </div>
        <div className="mt-3 space-y-3">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Nilai Stok Total</div>
            <div data-testid="inv-stock-value" className="font-mono text-2xl font-semibold text-zinc-900 mt-1">{formatIDR(inv.total_stock_value || 0)}</div>
          </div>
          <div className="grid grid-cols-2 gap-3 pt-3 border-t border-zinc-200">
            <div>
              <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Bahan Aktif</div>
              <div className="font-mono text-lg font-semibold text-zinc-900 mt-1">{inv.total_materials || 0}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Stok Menipis</div>
              <div className={`font-mono text-lg font-semibold mt-1 ${inv.low_stock_count > 0 ? "text-amber-700" : "text-zinc-900"}`}>{inv.low_stock_count || 0}</div>
            </div>
          </div>
          <Link to="/inventory" className="mt-3 inline-flex items-center gap-1 text-xs text-[#002FA7] font-semibold hover:underline">
            Buka Inventory <ArrowUpRight className="w-3 h-3" />
          </Link>
        </div>
      </div>
      <div className="lg:col-span-2 border border-zinc-200 bg-white p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold flex items-center gap-2">
              <TrendingDown className="w-3.5 h-3.5 text-[#E81123]" /> Top Waste Bulan Ini
            </div>
            <div className="font-heading text-lg font-bold text-zinc-900 mt-1">
              Total: <span className="font-mono text-[#E81123]">{formatIDR(inv.total_waste_this_month || 0)}</span>
              <span className="text-xs text-zinc-500 font-mono ml-2">({inv.waste_records_this_month || 0} laporan)</span>
            </div>
          </div>
        </div>
        {(!inv.top_waste || inv.top_waste.length === 0) ? (
          <div className="text-sm text-zinc-400 font-mono py-4">Belum ada laporan waste bulan ini.</div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-[11px] font-bold text-zinc-600 uppercase tracking-widest border-b border-zinc-200">
                <th className="py-2 pr-4">Bahan</th>
                <th className="py-2 pr-4 text-right">Qty</th>
                <th className="py-2 pr-4 text-right">Kerugian</th>
              </tr>
            </thead>
            <tbody>
              {inv.top_waste.map((w, i) => (
                <tr key={i} data-testid="top-waste-row" className="border-b border-zinc-100">
                  <td className="py-2 pr-4 font-medium text-zinc-900">{w.material_name}</td>
                  <td className="py-2 pr-4 font-mono text-right text-zinc-700">{Number(w.qty).toLocaleString("id-ID", { maximumFractionDigits: 4 })} <span className="text-[10px] text-zinc-500 uppercase ml-0.5">{w.material_unit}</span></td>
                  <td className="py-2 pr-4 font-mono text-right text-[#E81123] font-bold">{formatIDR(w.loss)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function ContractReminder({ items, total }) {
  const list = items || [];
  const STATUS_LABEL = { ojt: "OJT", kontrak_6: "Kontrak 6 Bln", kontrak_12: "Kontrak 1 Thn" };
  return (
    <div data-testid="contract-reminder-widget" className="mt-6 border border-zinc-200 bg-white p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-600" /> Reminder Kontrak / OJT
          </div>
          <div className="font-heading text-lg font-bold text-zinc-900 mt-1">
            {total > 0 ? `${total} karyawan akan berakhir dalam 90 hari` : "Tidak ada kontrak/OJT yang akan segera berakhir"}
          </div>
        </div>
        {total > 5 && (
          <Link to="/employees" className="text-xs text-[#002FA7] font-semibold hover:underline">
            Lihat semua →
          </Link>
        )}
      </div>
      {list.length === 0 ? (
        <div className="text-sm text-zinc-400 font-mono py-4">Belum ada data yang perlu ditindaklanjuti.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-[11px] font-bold text-zinc-600 uppercase tracking-widest border-b border-zinc-200">
                <th className="py-2 pr-4">NIK</th>
                <th className="py-2 pr-4">Nama</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Berakhir</th>
                <th className="py-2 pr-4 text-right">Sisa Waktu</th>
              </tr>
            </thead>
            <tbody>
              {list.map((e) => {
                const days = e.days_left;
                let color = "text-[#008A00]";
                if (days < 0) color = "text-[#E81123] font-bold";
                else if (days <= 30) color = "text-[#E81123] font-bold";
                else if (days <= 60) color = "text-amber-700 font-bold";
                return (
                  <tr key={e.id} data-testid="reminder-row" className="border-b border-zinc-100 hover:bg-zinc-50/60">
                    <td className="py-2.5 pr-4 font-mono text-xs text-zinc-700">{e.nik}</td>
                    <td className="py-2.5 pr-4">
                      <div className="font-medium text-zinc-900">{e.name}</div>
                      <div className="text-xs text-zinc-500">{e.position} · {e.department}</div>
                    </td>
                    <td className="py-2.5 pr-4">
                      <span className="inline-flex items-center px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border border-[#002FA7] text-[#002FA7] bg-[#002FA7]/5">
                        {STATUS_LABEL[e.employment_status] || e.employment_status}
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 font-mono text-xs text-zinc-700">{e.status_end_date}</td>
                    <td className={`py-2.5 pr-4 text-right font-mono ${color}`}>
                      {days < 0 ? `Lewat ${Math.abs(days)} hari` : `${days} hari lagi`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
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
