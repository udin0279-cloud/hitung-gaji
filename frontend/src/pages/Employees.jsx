import { useEffect, useState } from "react";
import { api, formatIDR, formatApiError } from "../lib/api";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, X, Search } from "lucide-react";

const EMPTY = {
  nik: "",
  name: "",
  email: "",
  position: "",
  department: "",
  join_date: new Date().toISOString().slice(0, 10),
  basic_salary: 0,
  fixed_allowance: 0,
  ptkp_status: "TK/0",
  npwp: "",
  has_npwp: true,
  bpjs_kesehatan: true,
  bpjs_ketenagakerjaan: true,
  bank_name: "",
  bank_account: "",
  active: true,
};

const PTKP_OPTIONS = ["TK/0", "TK/1", "TK/2", "TK/3", "K/0", "K/1", "K/2", "K/3"];

export default function Employees() {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");

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
    setForm({ ...EMPTY, ...emp });
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
        basic_salary: Number(form.basic_salary) || 0,
        fixed_allowance: Number(form.fixed_allowance) || 0,
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
    <div className="px-6 lg:px-10 py-8 max-w-7xl">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-zinc-200">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Master Data</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Karyawan</h1>
          <p className="text-sm text-zinc-500 mt-1">{list.length} karyawan terdaftar.</p>
        </div>
        <button
          data-testid="add-employee-button"
          onClick={openCreate}
          className="rounded-none bg-[#002FA7] text-white px-5 py-2.5 text-sm font-semibold hover:bg-[#002FA7]/90 inline-flex items-center gap-2"
        >
          <Plus className="w-4 h-4" /> Tambah Karyawan
        </button>
      </div>

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
              <th className="px-4 py-3">PTKP</th>
              <th className="px-4 py-3 text-right">Gaji Pokok</th>
              <th className="px-4 py-3 text-right">Tunjangan</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={8} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-zinc-400">
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
                  <span className="inline-flex items-center px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider border border-zinc-300 text-zinc-700 bg-zinc-50">{emp.ptkp_status}</span>
                </td>
                <td className="px-4 py-3 font-mono text-right text-zinc-900">{formatIDR(emp.basic_salary)}</td>
                <td className="px-4 py-3 font-mono text-right text-zinc-700">{formatIDR(emp.fixed_allowance)}</td>
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
            <Field label="Tanggal Masuk">
              <input data-testid="emp-join-date" type="date" required value={form.join_date} onChange={set("join_date")} className={inputCls} />
            </Field>
            <Field label="Jabatan">
              <input data-testid="emp-position" required value={form.position} onChange={set("position")} className={inputCls} />
            </Field>
            <Field label="Departemen">
              <input data-testid="emp-department" required value={form.department} onChange={set("department")} className={inputCls} />
            </Field>
          </div>

          <SectionTitle>Gaji & Tunjangan</SectionTitle>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field label="Gaji Pokok (Rp)">
              <input data-testid="emp-basic-salary" type="number" min="0" required value={form.basic_salary} onChange={setNum("basic_salary")} className={inputCls + " font-mono"} />
            </Field>
            <Field label="Tunjangan Tetap (Rp)">
              <input data-testid="emp-allowance" type="number" min="0" value={form.fixed_allowance} onChange={setNum("fixed_allowance")} className={inputCls + " font-mono"} />
            </Field>
          </div>

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

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="block text-xs font-semibold text-zinc-900 uppercase tracking-wider mb-1.5">{label}</span>
      {children}
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
