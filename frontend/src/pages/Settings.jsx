import { useEffect, useState } from "react";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import { Save, RotateCcw, Download, Upload, Database } from "lucide-react";

const PTKP_KEYS = ["TK/0", "TK/1", "TK/2", "TK/3", "K/0", "K/1", "K/2", "K/3"];

const RATE_FIELDS = [
  { group: "BPJS Kesehatan", items: [
    { key: "bpjs_kesehatan_employee", label: "Iuran Karyawan", type: "pct" },
    { key: "bpjs_kesehatan_employer", label: "Iuran Perusahaan", type: "pct" },
    { key: "bpjs_kesehatan_max_base", label: "Batas Upah", type: "money" },
  ]},
  { group: "JHT", items: [
    { key: "jht_employee", label: "Karyawan", type: "pct" },
    { key: "jht_employer", label: "Perusahaan", type: "pct" },
  ]},
  { group: "JP", items: [
    { key: "jp_employee", label: "Karyawan", type: "pct" },
    { key: "jp_employer", label: "Perusahaan", type: "pct" },
    { key: "jp_max_base", label: "Batas Upah", type: "money" },
  ]},
  { group: "JKK & JKM", items: [
    { key: "jkk_employer", label: "JKK Perusahaan", type: "pct" },
    { key: "jkm_employer", label: "JKM Perusahaan", type: "pct" },
  ]},
  { group: "Biaya Jabatan & Kerja", items: [
    { key: "biaya_jabatan_rate", label: "Biaya Jabatan Rate", type: "pct" },
    { key: "biaya_jabatan_max_year", label: "Biaya Jabatan Max/Tahun", type: "money" },
    { key: "standard_workdays", label: "Hari Kerja Standar/Bulan", type: "num" },
    { key: "overtime_multiplier", label: "Multiplier Lembur", type: "num" },
  ]},
];

export default function Settings() {
  const [config, setConfig] = useState(null);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [importMode, setImportMode] = useState("merge");
  const [restoring, setRestoring] = useState(false);
  const [restoreResult, setRestoreResult] = useState(null);

  const load = async () => {
    const { data } = await api.get("/config/constants");
    setConfig(data);
    setDraft({
      ptkp_table: { ...data.ptkp_table },
      pph21_brackets: data.pph21_brackets.map((b) => [b.limit, b.rate]),
      bpjs_kesehatan_employee: data.bpjs.kesehatan_employee,
      bpjs_kesehatan_employer: data.bpjs.kesehatan_employer,
      bpjs_kesehatan_max_base: data.bpjs.kesehatan_max_base,
      jht_employee: data.bpjs.jht_employee,
      jht_employer: data.bpjs.jht_employer,
      jp_employee: data.bpjs.jp_employee,
      jp_employer: data.bpjs.jp_employer,
      jp_max_base: data.bpjs.jp_max_base,
      jkk_employer: data.bpjs.jkk_employer,
      jkm_employer: data.bpjs.jkm_employer,
      biaya_jabatan_rate: data.biaya_jabatan_rate,
      biaya_jabatan_max_year: data.biaya_jabatan_max_year,
      standard_workdays: data.standard_workdays,
      overtime_multiplier: data.overtime_multiplier,
    });
  };

  useEffect(() => { load(); }, []);

  if (!draft) return <div className="p-10 text-sm text-zinc-400 font-mono">Memuat…</div>;

  const setField = (k, v) => setDraft((d) => ({ ...d, [k]: v }));
  const setPtkp = (k, v) => setDraft((d) => ({ ...d, ptkp_table: { ...d.ptkp_table, [k]: Number(v) || 0 } }));
  const setBracket = (i, idx, v) => setDraft((d) => {
    const next = d.pph21_brackets.map((b) => [...b]);
    next[i][idx] = v === "" || v === null ? (idx === 0 ? null : 0) : Number(v);
    return { ...d, pph21_brackets: next };
  });

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        ...draft,
        // Convert numeric fields
        bpjs_kesehatan_employee: Number(draft.bpjs_kesehatan_employee),
        bpjs_kesehatan_employer: Number(draft.bpjs_kesehatan_employer),
        bpjs_kesehatan_max_base: Number(draft.bpjs_kesehatan_max_base),
        jht_employee: Number(draft.jht_employee),
        jht_employer: Number(draft.jht_employer),
        jp_employee: Number(draft.jp_employee),
        jp_employer: Number(draft.jp_employer),
        jp_max_base: Number(draft.jp_max_base),
        jkk_employer: Number(draft.jkk_employer),
        jkm_employer: Number(draft.jkm_employer),
        biaya_jabatan_rate: Number(draft.biaya_jabatan_rate),
        biaya_jabatan_max_year: Number(draft.biaya_jabatan_max_year),
        standard_workdays: Number(draft.standard_workdays),
        overtime_multiplier: Number(draft.overtime_multiplier),
      };
      await api.put("/config/constants", payload);
      toast.success("Konfigurasi tersimpan");
      await load();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  const reset = () => load();

  const onRestoreFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!window.confirm(`Restore database dengan mode '${importMode}'?\n\n${importMode === "replace" ? "MODE REPLACE: semua data lama akan dihapus dan diganti dengan backup." : "MODE MERGE: data backup di-upsert by ID, data lain tetap."}\n\nLanjutkan?`)) return;
    setRestoring(true);
    setRestoreResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post(`/admin/import-database?mode=${importMode}`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setRestoreResult(data);
      toast.success("Restore selesai");
      await load();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal restore");
    } finally {
      setRestoring(false);
    }
  };

  return (
    <div className="px-6 lg:px-10 py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Pengaturan</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Konfigurasi Pajak & BPJS</h1>
          <p className="text-sm text-zinc-500 mt-1">Edit tarif jika ada perubahan regulasi. Berlaku untuk perhitungan payroll selanjutnya.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            data-testid="reset-config-button"
            onClick={reset}
            className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-4 py-2.5 text-sm font-semibold hover:bg-zinc-50 inline-flex items-center gap-2"
          >
            <RotateCcw className="w-4 h-4" /> Reset
          </button>
          <button
            data-testid="save-config-button"
            onClick={save}
            disabled={saving}
            className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2 disabled:opacity-60"
          >
            <Save className="w-4 h-4" /> {saving ? "Menyimpan…" : "Simpan Perubahan"}
          </button>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* PPh 21 brackets */}
        <Section title="Tarif PPh 21 Progresif" sub="UU HPP 2022">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-zinc-50 text-[11px] uppercase tracking-widest text-zinc-600 font-bold">
                <th className="px-3 py-2 text-left">Lapisan PKP s/d</th>
                <th className="px-3 py-2 text-right">Tarif (%)</th>
              </tr>
            </thead>
            <tbody>
              {draft.pph21_brackets.map((b, i) => (
                <tr key={i} className="border-t border-zinc-100">
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      value={b[0] ?? ""}
                      placeholder={i === draft.pph21_brackets.length - 1 ? "tanpa batas" : ""}
                      onChange={(e) => setBracket(i, 0, e.target.value)}
                      className="w-full font-mono text-sm border border-zinc-300 px-2 py-1 focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      step="0.001"
                      value={b[1] * 100}
                      onChange={(e) => setBracket(i, 1, Number(e.target.value) / 100)}
                      className="w-full font-mono text-sm text-right border border-zinc-300 px-2 py-1 focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
                    />
                  </td>
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
                <th className="px-3 py-2 text-right">PTKP/Tahun (Rp)</th>
              </tr>
            </thead>
            <tbody>
              {PTKP_KEYS.map((k) => (
                <tr key={k} className="border-t border-zinc-100">
                  <td className="px-3 py-2 font-mono text-zinc-900">{k}</td>
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      value={draft.ptkp_table[k] || 0}
                      onChange={(e) => setPtkp(k, e.target.value)}
                      className="w-full font-mono text-sm text-right border border-zinc-300 px-2 py-1 focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        {RATE_FIELDS.map((g) => (
          <Section key={g.group} title={g.group}>
            {g.items.map((f) => (
              <div key={f.key} className="flex items-center justify-between gap-3 px-2 py-2 border-b border-zinc-100 last:border-0">
                <span className="text-sm text-zinc-700 flex-1">{f.label}</span>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    step={f.type === "pct" ? "0.0001" : "1"}
                    value={f.type === "pct" ? (draft[f.key] * 100).toFixed(4).replace(/\.?0+$/, "") : draft[f.key]}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setField(f.key, f.type === "pct" ? v / 100 : v);
                    }}
                    className="w-32 font-mono text-sm text-right border border-zinc-300 px-2 py-1 focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
                  />
                  <span className="text-xs text-zinc-500 w-6">{f.type === "pct" ? "%" : f.type === "money" ? "Rp" : ""}</span>
                </div>
              </div>
            ))}
          </Section>
        ))}
      </div>

      <div className="mt-8 p-4 border border-zinc-200 bg-zinc-50">
        <div className="text-[11px] uppercase tracking-widest font-semibold text-zinc-500">Catatan</div>
        <p className="text-xs text-zinc-700 mt-2 leading-relaxed">
          Perubahan disimpan ke database dan langsung dipakai untuk perhitungan payroll dan THR berikutnya. PPh 21 progresif:
          <span className="font-mono"> PKP = (Bruto Setahun − Biaya Jabatan − Iuran JHT/JP Karyawan) − PTKP</span>.
          Karyawan tanpa NPWP otomatis +20% PPh 21.
        </p>
      </div>

      {/* Database Backup & Restore */}
      <div className="mt-10 border border-zinc-200 bg-white">
        <div className="px-5 py-4 border-b border-zinc-200 flex items-center gap-2">
          <Database className="w-4 h-4 text-zinc-700" />
          <div>
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Database</div>
            <div className="font-heading text-lg font-bold text-zinc-900">Backup & Restore</div>
          </div>
        </div>
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Backup */}
          <div>
            <div className="text-sm font-semibold text-zinc-900">Backup Database</div>
            <p className="text-xs text-zinc-500 mt-1 leading-relaxed">
              Unduh seluruh data (karyawan, slip gaji, THR, konfigurasi, log email) sebagai 1 file JSON. Bisa diimport balik ke sistem ini, ke MongoDB Anda sendiri, atau MongoDB Atlas.
            </p>
            <a
              data-testid="backup-db-button"
              href={`${API}/admin/export-database`}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-flex items-center gap-2 bg-zinc-900 text-white px-4 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-800"
            >
              <Download className="w-3.5 h-3.5" /> Unduh Backup JSON
            </a>
          </div>

          {/* Restore */}
          <div>
            <div className="text-sm font-semibold text-zinc-900">Restore Database</div>
            <p className="text-xs text-zinc-500 mt-1 leading-relaxed">
              Upload file backup JSON. Gunakan <b>merge</b> untuk menambah/update data, <b>replace</b> untuk mengganti seluruh isi koleksi.
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <select
                data-testid="restore-mode-select"
                value={importMode}
                onChange={(e) => setImportMode(e.target.value)}
                className="rounded-none border border-zinc-300 px-3 py-2 text-xs focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
              >
                <option value="merge">Mode: Merge (upsert by id)</option>
                <option value="replace">Mode: Replace (DESTRUKTIF)</option>
              </select>
              <label
                data-testid="restore-db-label"
                className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-4 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-50 inline-flex items-center gap-2 cursor-pointer"
              >
                <Upload className="w-3.5 h-3.5" /> {restoring ? "Memproses…" : "Pilih File Backup"}
                <input data-testid="restore-db-input" type="file" accept=".json" className="hidden" onChange={onRestoreFile} disabled={restoring} />
              </label>
            </div>
            {restoreResult && (
              <div className="mt-3 p-3 border border-zinc-200 bg-zinc-50 text-xs font-mono">
                <div className="font-bold text-zinc-900 mb-1">Hasil ({restoreResult.mode}):</div>
                {Object.entries(restoreResult.restored || {}).map(([k, v]) => (
                  <div key={k} className="text-zinc-700">{k}: <span className="text-[#008A00]">{v}</span></div>
                ))}
                {restoreResult.errors?.length > 0 && (
                  <div className="mt-2 text-[#E81123]">
                    {restoreResult.errors.map((e, i) => <div key={i}>{e}</div>)}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="px-5 py-3 border-t border-zinc-200 bg-zinc-50">
          <div className="text-[10px] text-zinc-600 font-mono">
            Cara import ke MongoDB Anda sendiri: download JSON di atas, lalu jalankan <code>mongoimport --uri="mongodb://...&lt;db&gt;" --collection=&lt;col&gt; --file=&lt;col&gt;.json --jsonArray</code> per koleksi setelah memecah JSON. Atau pakai endpoint restore di MongoDB lain yang menjalankan app ini.
          </div>
        </div>
      </div>
    </div>
  );
}

function Section({ title, sub, children }) {
  return (
    <div className="border border-zinc-200 bg-white">
      <div className="px-4 py-3 border-b border-zinc-200">
        {sub && <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{sub}</div>}
        <div className="font-heading text-lg font-bold text-zinc-900">{title}</div>
      </div>
      <div className="p-2">{children}</div>
    </div>
  );
}
