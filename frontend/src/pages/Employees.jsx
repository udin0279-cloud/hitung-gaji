import { useEffect, useState } from "react";
import { api, formatIDR, formatApiError, API } from "../lib/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Search, Upload, Download } from "lucide-react";

const EMPTY = {
  nik: "",
  name: "",
  email: "",
  phone: "",
  position: "",
  department: "",
  join_date: new Date().toISOString().slice(0, 10),
  basic_salary: 0,
  fixed_allowance: 0,
  tunjangan_jabatan: 0,
  tunjangan_transport: 0,
  tunjangan_lainnya: 0,
  insentif_individu: 0,
  tunjangan_tidak_tetap: 0,
  tunjangan_wfh: 0,
  insentif_kolektif: 0,
  insentif_lain: 0,
  potongan_terlambat: 0,
  potongan_pulang_cepat: 0,
  loan_installment: 0,
  loan_total_amount: 0,
  loan_tenor_total: 0,
  loan_tenor_paid: 0,
  ptkp_status: "TK/0",
  npwp: "",
  has_npwp: true,
  bpjs_kesehatan: true,
  bpjs_ketenagakerjaan: true,
  bank_name: "",
  bank_account: "",
  bank_account_holder: "",
  employment_status: "tetap",
  status_start_date: "",
  status_end_date: "",
  active: true,
};

const PTKP_OPTIONS = ["TK/0", "TK/1", "TK/2", "TK/3", "K/0", "K/1", "K/2", "K/3"];

const EMPLOYMENT_STATUS_OPTIONS = [
  { value: "ojt", label: "OJT" },
  { value: "kontrak_6", label: "Kontrak 6 Bulan" },
  { value: "kontrak_12", label: "Kontrak 1 Tahun" },
  { value: "tetap", label: "Tetap" },
];
const EMPLOYMENT_STATUS_LABEL = Object.fromEntries(EMPLOYMENT_STATUS_OPTIONS.map((o) => [o.value, o.label]));

export default function Employees() {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/employees");
      setList(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY);
    setOpen(true);
  };

  const openEdit = (emp) => {
    setEditing(emp);
    setForm({
      ...EMPTY,
      ...emp,
      status_start_date: emp.status_start_date ? String(emp.status_start_date).slice(0, 10) : "",
      status_end_date: emp.status_end_date ? String(emp.status_end_date).slice(0, 10) : "",
    });
    setOpen(true);
  };

  const close = () => {
    setOpen(false);
    setEditing(null);
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        ...form,
        status_start_date: form.status_start_date || null,
        status_end_date: form.status_end_date || null,
        basic_salary: Number(form.basic_salary) || 0,
        fixed_allowance: Number(form.fixed_allowance) || 0,
        tunjangan_jabatan: Number(form.tunjangan_jabatan) || 0,
        tunjangan_transport: Number(form.tunjangan_transport) || 0,
        tunjangan_lainnya: Number(form.tunjangan_lainnya) || 0,
        insentif_individu: Number(form.insentif_individu) || 0,
        tunjangan_tidak_tetap: Number(form.tunjangan_tidak_tetap) || 0,
        tunjangan_wfh: Number(form.tunjangan_wfh) || 0,
        insentif_kolektif: Number(form.insentif_kolektif) || 0,
        insentif_lain: Number(form.insentif_lain) || 0,
        potongan_terlambat: Number(form.potongan_terlambat) || 0,
        potongan_pulang_cepat: Number(form.potongan_pulang_cepat) || 0,
        loan_installment: Number(form.loan_installment) || 0,
        loan_total_amount: Number(form.loan_total_amount) || 0,
        loan_tenor_total: Number(form.loan_tenor_total) || 0,
        loan_tenor_paid: Number(form.loan_tenor_paid) || 0,
      };
      if (editing) {
        await api.put(`/employees/${editing.id}`, payload);
        toast.success("Karyawan diperbarui");
      } else {
        await api.post("/employees", payload);
        toast.success("Karyawan ditambahkan");
      }
      close();
      await load();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (emp) => {
    if (!window.confirm(`Hapus karyawan ${emp.name}?`)) return;
    try {
      await api.delete(`/employees/${emp.id}`);
      toast.success("Karyawan dihapus");
      await load();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menghapus");
    }
  };

  const onImportFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/employees-import", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setImportResult(data);
      toast.success(`${data.created} karyawan ditambahkan, ${data.skipped} dilewati`);
      await load();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal import");
    } finally {
      setImporting(false);
    }
  };

  const filtered = list.filter((e) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      e.name.toLowerCase().includes(q) ||
      e.nik.toLowerCase().includes(q) ||
      (e.department || "").toLowerCase().includes(q) ||
      (e.position || "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-6 sm:py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Master Data</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Karyawan</h1>
          <p className="text-sm text-zinc-500 mt-1">{list.length} karyawan terdaftar.</p>
        </div>
        <div className="flex items-center gap-2">
          <a
            data-testid="download-template-button"
            href={`${API}/employees-template.csv`}
            target="_blank"
            rel="noreferrer"
            className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-4 py-2.5 text-sm font-semibold hover:bg-zinc-50 inline-flex items-center gap-2"
          >
            <Download className="w-4 h-4" /> Template CSV
          </a>
          <label
            data-testid="import-csv-label"
            className="rounded-none border border-zinc-300 bg-white text-zinc-900 px-4 py-2.5 text-sm font-semibold hover:bg-zinc-50 inline-flex items-center gap-2 cursor-pointer"
          >
            <Upload className="w-4 h-4" /> {importing ? "Mengimpor…" : "Import CSV"}
            <input
              data-testid="import-csv-input"
              type="file"
              accept=".csv"
              className="hidden"
              onChange={onImportFile}
              disabled={importing}
            />
          </label>
          <button
            data-testid="add-employee-button"
            onClick={openCreate}
            className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2"
          >
            <Plus className="w-4 h-4" /> Tambah
          </button>
        </div>
      </div>

      {importResult && (
        <div className="mt-4 p-4 border border-zinc-200 bg-zinc-50">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[11px] uppercase tracking-widest font-semibold text-zinc-500">Hasil Import</div>
              <div className="font-mono text-sm text-zinc-900 mt-1">
                {importResult.created} ditambahkan · {importResult.skipped} dilewati
              </div>
            </div>
            <button onClick={() => setImportResult(null)} className="p-1 hover:bg-zinc-200"><X className="w-4 h-4" /></button>
          </div>
          {importResult.errors?.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-[#E81123] cursor-pointer font-semibold">Lihat {importResult.errors.length} error</summary>
              <ul className="mt-2 text-xs text-zinc-700 font-mono space-y-0.5 list-disc list-inside">
                {importResult.errors.map((er, i) => <li key={i}>{er}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}

      <div className="mt-6 flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            data-testid="employee-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Cari nama, NIK, departemen…"
            className="rounded-none border border-zinc-300 bg-white pl-10 pr-3 py-2 text-sm w-full focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
          />
        </div>
      </div>

      <div className="mt-4 border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">NIK</th>
              <th className="px-4 py-3">Nama</th>
              <th className="px-4 py-3">Jabatan</th>
              <th className="px-4 py-3">Departemen</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Berakhir</th>
              <th className="px-4 py-3">PTKP</th>
              <th className="px-4 py-3 text-right">Gaji Pokok</th>
              <th className="px-4 py-3 text-right">Tunjangan</th>
              <th className="px-4 py-3">1721-A1</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={11} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={11} className="px-4 py-12 text-center text-zinc-400">
                <div className="font-mono text-xs">Belum ada karyawan. Klik &ldquo;Tambah Karyawan&rdquo; untuk mulai.</div>
              </td></tr>
            )}
            {filtered.map((emp) => (
              <tr key={emp.id} data-testid="employee-row" className="border-b border-zinc-100 hover:bg-zinc-50/80 transition-colors">
                <td className="px-4 py-3 font-mono text-xs text-zinc-700">{emp.nik}</td>
                <td className="px-4 py-3">
                  <div className="font-medium text-zinc-900">{emp.name}</div>
                  <div className="text-xs text-zinc-500">{emp.email || "—"}</div>
                </td>
                <td className="px-4 py-3 text-zinc-700">{emp.position}</td>
                <td className="px-4 py-3 text-zinc-700">{emp.department}</td>
                <td className="px-4 py-3">
                  {(() => {
                    const s = emp.employment_status || "tetap";
                    const cls = s === "tetap"
                      ? "border-[#008A00] text-[#008A00] bg-[#008A00]/5"
                      : s === "ojt"
                      ? "border-[#E81123] text-[#E81123] bg-[#E81123]/5"
                      : "border-[#002FA7] text-[#002FA7] bg-[#002FA7]/5";
                    return (
                      <span className={`inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border ${cls}`}>
                        {EMPLOYMENT_STATUS_LABEL[s] || s}
                      </span>
                    );
                  })()}
                </td>
                <td className="px-4 py-3">
                  {(() => {
                    const s = emp.employment_status || "tetap";
                    if (s === "tetap" || !emp.status_end_date) {
                      return <span className="text-zinc-300 font-mono text-xs">—</span>;
                    }
                    const today = new Date(); today.setHours(0, 0, 0, 0);
                    const end = new Date(emp.status_end_date);
                    const daysLeft = Math.round((end - today) / (1000 * 60 * 60 * 24));
                    let cls = "border-[#008A00] text-[#008A00] bg-[#008A00]/5";
                    let label;
                    if (daysLeft < 0) {
                      cls = "border-[#E81123] text-[#E81123] bg-[#E81123]/5";
                      label = "Lewat";
                    } else if (daysLeft <= 30) {
                      cls = "border-[#E81123] text-[#E81123] bg-[#E81123]/5";
                      label = `${daysLeft} hari`;
                    } else if (daysLeft <= 60) {
                      cls = "border-amber-500 text-amber-700 bg-amber-50";
                      label = `${daysLeft} hari`;
                    } else {
                      label = `${daysLeft} hari`;
                    }
                    return (
                      <div className="flex flex-col gap-0.5">
                        <span className="font-mono text-[11px] text-zinc-700">{emp.status_end_date}</span>
                        <span className={`inline-flex w-fit items-center px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider border ${cls}`}>
                          {label}
                        </span>
                      </div>
                    );
                  })()}
                </td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border border-zinc-300 text-zinc-700 bg-zinc-50">{emp.ptkp_status}</span>
                </td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900">{formatIDR(emp.basic_salary)}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(emp.fixed_allowance)}</td>
                <td className="px-4 py-3">
                  <a
                    data-testid={`bp-${emp.id}`}
                    href={`${API}/payroll/bukti-potong/${emp.id}/${new Date().getFullYear()}/pdf`}
                    target="_blank"
                    rel="noreferrer"
                    title={`Bukti Potong ${new Date().getFullYear()}`}
                    className="inline-flex items-center gap-1 px-2 py-1 border border-zinc-300 hover:bg-zinc-900 hover:text-white text-[10px] font-bold uppercase tracking-wider transition-colors"
                  >
                    <Download className="w-3 h-3" /> {new Date().getFullYear()}
                  </a>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <button
                      data-testid="edit-employee-button"
                      onClick={() => openEdit(emp)}
                      className="p-1.5 hover:bg-zinc-100 text-zinc-700"
                      title="Edit"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button
                      data-testid="delete-employee-button"
                      onClick={() => remove(emp)}
                      className="p-1.5 hover:bg-[#E81123]/10 text-[#E81123]"
                      title="Hapus"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && (
        <EmployeeFormModal
          editing={editing}
          form={form}
          setForm={setForm}
          onClose={close}
          onSubmit={submit}
          saving={saving}
        />
      )}
    </div>
  );
}

function EmployeeFormModal({ editing, form, setForm, onClose, onSubmit, saving }) {
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const setNum = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const setBool = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.checked }));

  // Auto-calc tanggal berakhir berdasarkan status + tanggal mulai
  const calcEndDate = (start, status) => {
    if (!start) return "";
    if (status !== "kontrak_6" && status !== "kontrak_12") return "";
    const months = status === "kontrak_6" ? 6 : 12;
    const d = new Date(start);
    if (isNaN(d.getTime())) return "";
    d.setMonth(d.getMonth() + months);
    d.setDate(d.getDate() - 1);
    return d.toISOString().slice(0, 10);
  };

  const onStatusChange = (e) => {
    const newStatus = e.target.value;
    setForm((f) => {
      const next = { ...f, employment_status: newStatus };
      if (newStatus === "tetap") {
        next.status_end_date = "";
      } else if ((newStatus === "kontrak_6" || newStatus === "kontrak_12") && f.status_start_date) {
        next.status_end_date = calcEndDate(f.status_start_date, newStatus);
      }
      return next;
    });
  };

  const onStatusStartChange = (e) => {
    const newStart = e.target.value;
    setForm((f) => {
      const next = { ...f, status_start_date: newStart };
      if (f.employment_status === "kontrak_6" || f.employment_status === "kontrak_12") {
        next.status_end_date = calcEndDate(newStart, f.employment_status);
      }
      return next;
    });
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/50 backdrop-blur-sm flex items-center justify-center p-4 no-print">
      <div className="bg-white border border-zinc-300 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-zinc-200 sticky top-0 bg-white">
          <div>
            <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">{editing ? "Edit" : "Baru"}</div>
            <div className="font-heading text-xl font-bold text-zinc-900">{editing ? "Edit Karyawan" : "Tambah Karyawan"}</div>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-zinc-100" data-testid="close-employee-modal"><X className="w-4 h-4" /></button>
        </div>
        <form onSubmit={onSubmit} className="p-5 space-y-5">
          <SectionTitle>Identitas</SectionTitle>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="NIK">
              <input data-testid="emp-nik" required value={form.nik} onChange={set("nik")} className={inputCls} />
            </Field>
            <Field label="Nama Lengkap">
              <input data-testid="emp-name" required value={form.name} onChange={set("name")} className={inputCls} />
            </Field>
            <Field label="Email">
              <input data-testid="emp-email" type="email" value={form.email || ""} onChange={set("email")} className={inputCls} />
            </Field>
            <Field label="WhatsApp (08xx atau 62xx)">
              <input data-testid="emp-phone" value={form.phone || ""} onChange={set("phone")} placeholder="081234567890" className={inputCls + " font-mono"} />
            </Field>
            <Field label="Tanggal Masuk">
              <input data-testid="emp-join-date" type="date" required value={form.join_date} onChange={set("join_date")} className={inputCls} />
            </Field>
            <Field label="Jabatan">
              <input data-testid="emp-position" required value={form.position} onChange={set("position")} className={inputCls} />
            </Field>
            <Field label="Departemen">
              <input data-testid="emp-department" required value={form.department} onChange={set("department")} className={inputCls} />
            </Field>
            <Field label="Status Karyawan">
              <select data-testid="emp-employment-status" value={form.employment_status} onChange={onStatusChange} className={inputCls}>
                {EMPLOYMENT_STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </Field>
            {form.employment_status !== "tetap" && (
              <>
                <Field label="Tanggal Mulai Status" hint={form.employment_status === "ojt" ? "Awal masa OJT" : "Awal masa kontrak"}>
                  <input data-testid="emp-status-start" type="date" value={form.status_start_date || ""} onChange={onStatusStartChange} className={inputCls} />
                </Field>
                <Field
                  label="Tanggal Berakhir Status"
                  hint={
                    form.employment_status === "ojt"
                      ? "Isi manual sesuai durasi OJT"
                      : "Auto-hitung dari tanggal mulai (bisa diubah manual)"
                  }
                >
                  <input data-testid="emp-status-end" type="date" value={form.status_end_date || ""} onChange={set("status_end_date")} className={inputCls} />
                </Field>
              </>
            )}
          </div>

          <SectionTitle>Gaji & Tunjangan</SectionTitle>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Gaji Pokok (Rp)">
              <CurrencyInput testId="emp-basic-salary" value={form.basic_salary} onChange={(v) => setForm({ ...form, basic_salary: v })} />
            </Field>
            <Field label="Tunjangan Tetap (Rp)" hint="Legacy — dianggap taxable">
              <CurrencyInput testId="emp-allowance" value={form.fixed_allowance} onChange={(v) => setForm({ ...form, fixed_allowance: v })} />
            </Field>
            <Field label="Tunjangan Jabatan (Rp)" hint="Masuk base BPJS & PPh21">
              <CurrencyInput testId="emp-tj-jabatan" value={form.tunjangan_jabatan} onChange={(v) => setForm({ ...form, tunjangan_jabatan: v })} />
            </Field>
            <Field label="Tunjangan Transport (Rp)" hint="Non-taxable benefit">
              <CurrencyInput testId="emp-tj-transport" value={form.tunjangan_transport} onChange={(v) => setForm({ ...form, tunjangan_transport: v })} />
            </Field>
            <Field label="Tunjangan Lain-lain (Rp)" hint="Non-taxable benefit">
              <CurrencyInput testId="emp-tj-lainnya" value={form.tunjangan_lainnya} onChange={(v) => setForm({ ...form, tunjangan_lainnya: v })} />
            </Field>
            <Field label="Insentif Individu (Rp)" hint="Taxable PPh21, tidak masuk base BPJS">
              <CurrencyInput testId="emp-insentif-individu" value={form.insentif_individu} onChange={(v) => setForm({ ...form, insentif_individu: v })} />
            </Field>
            <Field label="Tunjangan Tidak Tetap (Rp)" hint="Taxable PPh21, tidak masuk base BPJS">
              <CurrencyInput testId="emp-tj-tidak-tetap" value={form.tunjangan_tidak_tetap} onChange={(v) => setForm({ ...form, tunjangan_tidak_tetap: v })} />
            </Field>
            <Field label="Tunjangan WFH (Rp)" hint="Non-taxable benefit">
              <CurrencyInput testId="emp-tj-wfh" value={form.tunjangan_wfh} onChange={(v) => setForm({ ...form, tunjangan_wfh: v })} />
            </Field>
            <Field label="Insentif Kolektif (Rp)" hint="Taxable PPh21, tidak masuk base BPJS">
              <CurrencyInput testId="emp-insentif-kolektif" value={form.insentif_kolektif} onChange={(v) => setForm({ ...form, insentif_kolektif: v })} />
            </Field>
            <Field label="Insentif Lain-lain (Rp)" hint="Taxable PPh21, tidak masuk base BPJS">
              <CurrencyInput testId="emp-insentif-lain" value={form.insentif_lain} onChange={(v) => setForm({ ...form, insentif_lain: v })} />
            </Field>
          </div>

          <SectionTitle>Potongan Kehadiran (Opsional)</SectionTitle>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Potongan Terlambat (Rp)" hint="Dipotong dari gross setiap payroll">
              <CurrencyInput testId="emp-potongan-terlambat" value={form.potongan_terlambat} onChange={(v) => setForm({ ...form, potongan_terlambat: v })} />
            </Field>
            <Field label="Potongan Pulang Cepat (Rp)" hint="Dipotong dari gross setiap payroll">
              <CurrencyInput testId="emp-potongan-pulang-cepat" value={form.potongan_pulang_cepat} onChange={(v) => setForm({ ...form, potongan_pulang_cepat: v })} />
            </Field>
          </div>

          <SectionTitle>Potongan Pinjaman (Opsional)</SectionTitle>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Total Pinjaman (Rp)" hint="Nilai pinjaman keseluruhan (untuk referensi)">
              <CurrencyInput testId="emp-loan-total" value={form.loan_total_amount} onChange={(v) => setForm({ ...form, loan_total_amount: v })} />
            </Field>
            <Field label="Angsuran / Bulan (Rp)" hint="Dipotong tiap payroll">
              <CurrencyInput testId="emp-loan-installment" value={form.loan_installment} onChange={(v) => setForm({ ...form, loan_installment: v })} />
            </Field>
            <Field label="Tenor Total (bulan)" hint="0 = pinjaman tanpa batas / manual stop">
              <input data-testid="emp-loan-tenor-total" type="number" min="0" value={form.loan_tenor_total} onChange={setNum("loan_tenor_total")} className={inputCls + " font-mono"} />
            </Field>
            <Field label="Tenor Sudah Dibayar" hint="Auto-increment saat payroll">
              <input data-testid="emp-loan-tenor-paid" type="number" min="0" value={form.loan_tenor_paid} onChange={setNum("loan_tenor_paid")} className={inputCls + " font-mono"} />
            </Field>
          </div>
          {(Number(form.loan_total_amount) > 0 || Number(form.loan_installment) > 0) && (
            <div className="mt-2 bg-zinc-50 border border-zinc-200 p-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <div>
                <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Total Pinjaman</div>
                <div className="font-mono text-zinc-900 mt-1">Rp {Number(form.loan_total_amount || 0).toLocaleString("id-ID")}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Sudah Dibayar</div>
                <div className="font-mono text-emerald-700 mt-1">Rp {(Number(form.loan_installment || 0) * Number(form.loan_tenor_paid || 0)).toLocaleString("id-ID")}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Sisa Pinjaman</div>
                <div className="font-mono text-rose-700 mt-1">Rp {Math.max(0, Number(form.loan_total_amount || 0) - Number(form.loan_installment || 0) * Number(form.loan_tenor_paid || 0)).toLocaleString("id-ID")}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Progress</div>
                <div className="font-mono text-[#002FA7] mt-1">
                  {Number(form.loan_tenor_total || 0) > 0
                    ? `${form.loan_tenor_paid}/${form.loan_tenor_total} bulan`
                    : "—"}
                </div>
              </div>
            </div>
          )}

          <SectionTitle>Pajak & BPJS</SectionTitle>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Status PTKP">
              <select data-testid="emp-ptkp" value={form.ptkp_status} onChange={set("ptkp_status")} className={inputCls}>
                {PTKP_OPTIONS.map((p) => <option key={p}>{p}</option>)}
              </select>
            </Field>
            <Field label="NPWP">
              <input data-testid="emp-npwp" value={form.npwp || ""} onChange={set("npwp")} className={inputCls + " font-mono"} placeholder="opsional" />
            </Field>
            <div className="md:col-span-2 grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
              <Toggle label="Punya NPWP" testId="emp-has-npwp" checked={form.has_npwp} onChange={setBool("has_npwp")} />
              <Toggle label="BPJS Kesehatan" testId="emp-bpjs-kes" checked={form.bpjs_kesehatan} onChange={setBool("bpjs_kesehatan")} />
              <Toggle label="BPJS Ketenagakerjaan" testId="emp-bpjs-tk" checked={form.bpjs_ketenagakerjaan} onChange={setBool("bpjs_ketenagakerjaan")} />
            </div>
          </div>

          <SectionTitle>Rekening Bank (Opsional)</SectionTitle>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Nama Bank">
              <input value={form.bank_name || ""} onChange={set("bank_name")} className={inputCls} />
            </Field>
            <Field label="Nomor Rekening">
              <input value={form.bank_account || ""} onChange={set("bank_account")} className={inputCls + " font-mono"} />
            </Field>
            <Field label="Atas Nama">
              <input data-testid="emp-bank-account-holder" value={form.bank_account_holder || ""} onChange={set("bank_account_holder")} className={inputCls} placeholder="Nama pemilik rekening" />
            </Field>
          </div>

          <div className="flex items-center justify-end gap-2 pt-4 border-t border-zinc-200">
            <button type="button" onClick={onClose} className="rounded-none bg-white text-zinc-900 border border-zinc-300 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50">Batal</button>
            <button
              data-testid="save-employee-button"
              type="submit"
              disabled={saving}
              className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 disabled:opacity-60"
            >{saving ? "Menyimpan…" : "Simpan"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

const inputCls = "rounded-none border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none w-full";

// Currency input with Indonesian thousand separator (300000 → 300.000)
function CurrencyInput({ value, onChange, testId, min = 0 }) {
  const formatted = Number(value || 0).toLocaleString("id-ID");
  const handleChange = (e) => {
    const raw = e.target.value.replace(/\D/g, ""); // strip non-digits
    const num = raw === "" ? 0 : Number(raw);
    if (num < min) return;
    onChange(num);
  };
  return (
    <input
      type="text"
      inputMode="numeric"
      data-testid={testId}
      value={formatted}
      onChange={handleChange}
      onFocus={(e) => e.target.select()}
      className={inputCls + " font-mono"}
    />
  );
}

function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="block text-xs font-semibold text-zinc-900 uppercase tracking-wider mb-1.5">{label}</span>
      {children}
      {hint && <span className="block text-[10px] text-zinc-500 mt-1 font-mono normal-case">{hint}</span>}
    </label>
  );
}

function SectionTitle({ children }) {
  return <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold pt-2 border-t border-zinc-100 -mx-5 px-5">{children}</div>;
}

function Toggle({ label, checked, onChange, testId }) {
  return (
    <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
      <input data-testid={testId} type="checkbox" checked={checked} onChange={onChange} className="w-4 h-4 accent-[#002FA7]" />
      <span className="text-zinc-700">{label}</span>
    </label>
  );
}
