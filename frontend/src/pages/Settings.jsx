import { useEffect, useState } from "react";
import { api, formatIDR } from "../lib/api";

export default function Settings() {
  const [config, setConfig] = useState(null);

  useEffect(() => {
    (async () => {
      const { data } = await api.get("/config/constants");
      setConfig(data);
    })();
  }, []);

  if (!config) return <div className="p-10 text-sm text-zinc-400 font-mono">Memuat…</div>;

  return (
    <div className="px-6 lg:px-10 py-8 max-w-7xl">
      <div className="pb-6 border-b border-zinc-200">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Referensi Regulasi</div>
        <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Konfigurasi Pajak & BPJS</h1>
        <p className="text-sm text-zinc-500 mt-1">Tarif yang digunakan sistem untuk perhitungan otomatis (UU HPP 2022 & Regulasi BPJS).</p>
      </div>

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* PPh 21 brackets */}
        <Section title="Tarif PPh 21 Progresif" sub="UU HPP 2022">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-zinc-50 text-[11px] uppercase tracking-widest text-zinc-600 font-bold">
                <th className="px-3 py-2 text-left">Lapisan PKP</th>
                <th className="px-3 py-2 text-right">Tarif</th>
              </tr>
            </thead>
            <tbody>
              {config.pph21_brackets.map((b, i) => (
                <tr key={i} className="border-t border-zinc-100">
                  <td className="px-3 py-2.5 font-mono text-zinc-900">{b.limit ? `s/d ${formatIDR(b.limit)}` : "di atas Rp 5 M"}</td>
                  <td className="px-3 py-2.5 font-mono text-right text-zinc-900">{(b.rate * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        {/* PTKP */}
        <Section title="PTKP Setahun" sub="Penghasilan Tidak Kena Pajak">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-zinc-50 text-[11px] uppercase tracking-widest text-zinc-600 font-bold">
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-right">PTKP/Tahun</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(config.ptkp_table).map(([k, v]) => (
                <tr key={k} className="border-t border-zinc-100">
                  <td className="px-3 py-2.5 font-mono text-zinc-900">{k}</td>
                  <td className="px-3 py-2.5 font-mono text-right text-zinc-900">{formatIDR(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        {/* BPJS */}
        <Section title="BPJS Kesehatan">
          <KV label="Iuran Karyawan" value={`${(config.bpjs.kesehatan_employee * 100).toFixed(0)}%`} />
          <KV label="Iuran Perusahaan" value={`${(config.bpjs.kesehatan_employer * 100).toFixed(0)}%`} />
          <KV label="Batas Upah" value={formatIDR(config.bpjs.kesehatan_max_base)} />
        </Section>

        <Section title="BPJS Ketenagakerjaan">
          <KV label="JHT — Karyawan" value={`${(config.bpjs.jht_employee * 100).toFixed(1)}%`} />
          <KV label="JHT — Perusahaan" value={`${(config.bpjs.jht_employer * 100).toFixed(2)}%`} />
          <KV label="JP — Karyawan" value={`${(config.bpjs.jp_employee * 100).toFixed(0)}%`} />
          <KV label="JP — Perusahaan" value={`${(config.bpjs.jp_employer * 100).toFixed(0)}%`} />
          <KV label="JP Batas Upah" value={formatIDR(config.bpjs.jp_max_base)} />
          <KV label="JKK — Perusahaan" value={`${(config.bpjs.jkk_employer * 100).toFixed(2)}%`} />
          <KV label="JKM — Perusahaan" value={`${(config.bpjs.jkm_employer * 100).toFixed(1)}%`} />
        </Section>

        <Section title="Biaya Jabatan" sub="Pengurang penghasilan bruto">
          <KV label="Tarif" value="5% dari Bruto" />
          <KV label="Maksimum/Tahun" value={formatIDR(config.biaya_jabatan_max_year)} />
        </Section>
      </div>

      <div className="mt-8 p-4 border border-zinc-200 bg-zinc-50">
        <div className="text-[11px] uppercase tracking-widest font-semibold text-zinc-500">Catatan</div>
        <p className="text-xs text-zinc-700 mt-2 leading-relaxed">
          Perhitungan PPh 21 menggunakan metode disetahunkan: <span className="font-mono">PKP = (Bruto Setahun − Biaya Jabatan − Iuran JHT/JP Karyawan) − PTKP</span>. PPh 21 setahun lalu dibagi 12 untuk pemotongan bulanan. Karyawan tanpa NPWP dikenakan tarif tambahan 20%.
        </p>
      </div>
    </div>
  );
}

function Section({ title, sub, children }) {
  return (
    <div className="border border-zinc-200 bg-white">
      <div className="px-4 py-3 border-b border-zinc-200">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{sub || "Tarif"}</div>
        <div className="font-heading text-lg font-bold text-zinc-900">{title}</div>
      </div>
      <div className="p-2">{children}</div>
    </div>
  );
}

function KV({ label, value }) {
  return (
    <div className="flex items-center justify-between px-2 py-2 border-b border-zinc-100 last:border-0">
      <span className="text-sm text-zinc-700">{label}</span>
      <span className="font-mono text-sm text-zinc-900">{value}</span>
    </div>
  );
}
