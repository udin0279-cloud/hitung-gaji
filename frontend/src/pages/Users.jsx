import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Plus, Trash2, Edit3, Shield, ShieldCheck, X, UserCog, CheckSquare, Square as SquareIcon } from "lucide-react";
import { toast } from "sonner";
import { MENU_KEYS, MENU_LABELS } from "../lib/menuAccess";

const ROLE_LABELS = {
  super_admin: { label: "Super Admin", desc: "Akses semua menu tanpa batasan.", color: "bg-[#002FA7] text-white" },
  admin_privileged: { label: "Admin dengan Privilege", desc: "Akses menu sesuai centang.", color: "bg-emerald-700 text-white" },
};

export default function Users() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(null); // null | "create" | userObj

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/users");
      setItems(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const remove = async (id, email) => {
    if (!confirm(`Hapus user ${email}?`)) return;
    try {
      await api.delete(`/users/${id}`);
      toast.success("User dihapus");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Gagal menghapus");
    }
  };

  return (
    <div className="min-h-screen p-4 sm:p-6 lg:p-10">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 font-semibold">Pengaturan</div>
          <h1 className="font-heading text-3xl lg:text-4xl font-bold tracking-tight text-zinc-900 mt-1">Kelola User Admin</h1>
          <p className="text-sm text-zinc-500 mt-2 max-w-xl">Tambah, edit, atau hapus akun admin. Atur hak akses menu untuk role <b>Admin dengan Privilege</b> lewat centang.</p>
        </div>
        <button
          data-testid="add-user-btn"
          onClick={() => setShowForm("create")}
          className="inline-flex items-center gap-2 bg-[#002FA7] text-white px-5 py-2.5 text-xs font-semibold uppercase tracking-wider hover:bg-[#002FA7]/90"
        >
          <Plus className="w-3.5 h-3.5" /> Tambah User
        </button>
      </div>

      {/* Role Legend */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
        <div className="border border-zinc-200 bg-white p-4 flex items-start gap-3">
          <ShieldCheck className="w-5 h-5 text-[#002FA7] mt-0.5" />
          <div>
            <div className="text-sm font-semibold text-zinc-900">Super Admin</div>
            <div className="text-xs text-zinc-500 mt-0.5">Akses penuh ke semua menu tanpa batasan.</div>
          </div>
        </div>
        <div className="border border-zinc-200 bg-white p-4 flex items-start gap-3">
          <Shield className="w-5 h-5 text-emerald-700 mt-0.5" />
          <div>
            <div className="text-sm font-semibold text-zinc-900">Admin dengan Privilege</div>
            <div className="text-xs text-zinc-500 mt-0.5">Menu yang bisa diakses ditentukan lewat centang di form edit user.</div>
          </div>
        </div>
      </div>

      {/* Users Table */}
      <div className="border border-zinc-200 bg-white overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-zinc-50 border-b border-zinc-200 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">
              <th className="px-4 py-3">Nama</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3 text-center">Role</th>
              <th className="px-4 py-3 text-center">Cabang</th>
              <th className="px-4 py-3">Menu Akses</th>
              <th className="px-4 py-3">Dibuat</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Memuat…</td></tr>}
            {!loading && items.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-10 text-center text-zinc-400 font-mono text-xs">Belum ada user.</td></tr>
            )}
            {items.map((u) => {
              const r = ROLE_LABELS[u.role] || { label: u.role, color: "bg-zinc-200 text-zinc-900" };
              const isSA = u.role === "super_admin";
              const permsLabel = isSA
                ? "Semua"
                : (u.permissions || []).length === 0
                  ? "—"
                  : (u.permissions || []).map((p) => MENU_LABELS[p] || p).join(", ");
              const branchLabel = u.branch === "plaza" ? "Plaza" : u.branch === "kastem" ? "Kastem" : "—";
              const branchColor = u.branch === "plaza" ? "bg-[#002FA7]/10 text-[#002FA7]" : u.branch === "kastem" ? "bg-[#E81123]/10 text-[#E81123]" : "text-zinc-400";
              return (
                <tr key={u.id} data-testid={`user-row-${u.id}`} className="border-b border-zinc-100 hover:bg-zinc-50/80">
                  <td className="px-4 py-3 font-semibold text-zinc-900">{u.name}</td>
                  <td className="px-4 py-3 font-mono text-zinc-700 text-xs">{u.email}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-block px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest ${r.color}`}>{r.label}</span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span data-testid={`user-branch-${u.id}`} className={`inline-block px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest ${branchColor}`}>
                      {branchLabel}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[11px] text-zinc-600 max-w-[320px] break-words">
                    {isSA ? (
                      <span className="text-[10px] font-bold uppercase tracking-widest text-[#002FA7]">Semua Menu</span>
                    ) : (
                      <span data-testid={`user-perms-${u.id}`}>{permsLabel}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-zinc-500 text-xs">{(u.created_at || "").slice(0, 10)}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button
                        data-testid={`edit-user-${u.id}`}
                        onClick={() => setShowForm(u)}
                        className="inline-flex items-center gap-1 text-[11px] border border-zinc-300 hover:bg-zinc-900 hover:text-white px-2 py-1"
                      >
                        <Edit3 className="w-3 h-3" /> Edit
                      </button>
                      <button
                        data-testid={`delete-user-${u.id}`}
                        onClick={() => remove(u.id, u.email)}
                        className="inline-flex items-center gap-1 text-[11px] bg-rose-600 text-white hover:bg-rose-700 px-2 py-1"
                      >
                        <Trash2 className="w-3 h-3" /> Hapus
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showForm && (
        <UserFormModal
          user={showForm === "create" ? null : showForm}
          onClose={() => setShowForm(null)}
          onSuccess={() => { setShowForm(null); load(); }}
        />
      )}
    </div>
  );
}

function UserFormModal({ user, onClose, onSuccess }) {
  const isEdit = !!user;
  const [name, setName] = useState(user?.name || "");
  const [email, setEmail] = useState(user?.email || "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(user?.role || "admin_privileged");
  const [permissions, setPermissions] = useState(
    user?.role === "super_admin"
      ? []
      : (user?.permissions || [])
  );
  const [branch, setBranch] = useState(user?.branch || "");
  const [submitting, setSubmitting] = useState(false);

  const togglePerm = (key) => {
    setPermissions((prev) =>
      prev.includes(key) ? prev.filter((p) => p !== key) : [...prev, key]
    );
  };

  const setAllPerms = (val) => {
    setPermissions(val ? [...MENU_KEYS] : []);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!isEdit && !password) { toast.error("Password wajib diisi"); return; }
    if (password && password.length < 6) { toast.error("Password minimal 6 karakter"); return; }
    setSubmitting(true);
    try {
      const payload = { name, role };
      if (role === "admin_privileged") payload.permissions = permissions;
      payload.branch = branch || null;
      if (password) payload.password = password;
      if (isEdit) {
        await api.put(`/users/${user.id}`, payload);
        toast.success("User diperbarui");
      } else {
        await api.post("/users", { email, ...payload, password });
        toast.success("User berhasil dibuat");
      }
      onSuccess();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal menyimpan");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-zinc-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white w-full max-w-xl border border-zinc-200 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200 sticky top-0 bg-white z-10">
          <div className="flex items-center gap-2">
            <UserCog className="w-4 h-4 text-[#002FA7]" />
            <h2 className="font-heading text-lg font-bold">{isEdit ? "Edit User" : "Tambah User Baru"}</h2>
          </div>
          <button onClick={onClose} data-testid="close-user-form" className="p-2 hover:bg-zinc-100"><X className="w-4 h-4" /></button>
        </div>
        <form onSubmit={submit} className="p-6 space-y-5">
          <div>
            <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">Nama Lengkap</label>
            <input
              data-testid="user-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full border border-zinc-300 px-3 py-2 text-sm focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">Email</label>
            <input
              type="email"
              data-testid="user-email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={isEdit}
              className="w-full border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none disabled:bg-zinc-100 disabled:text-zinc-500"
            />
            {isEdit && <div className="text-[10px] text-zinc-400 mt-1 font-mono">Email tidak dapat diubah</div>}
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">
              Password {isEdit && <span className="text-zinc-400 normal-case">(kosongkan jika tidak diubah)</span>}
            </label>
            <input
              type="password"
              data-testid="user-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required={!isEdit}
              placeholder={isEdit ? "••••••" : "Min. 6 karakter"}
              className="w-full border border-zinc-300 px-3 py-2 text-sm font-mono focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-2">Level Akses</label>
            <div className="grid grid-cols-1 gap-2">
              {Object.entries(ROLE_LABELS).map(([val, info]) => {
                const active = role === val;
                return (
                  <button
                    type="button"
                    key={val}
                    data-testid={`role-${val}`}
                    onClick={() => setRole(val)}
                    className={`text-left border p-3 transition-colors ${active ? "border-[#002FA7] bg-[#002FA7]/5" : "border-zinc-300 hover:border-zinc-400"}`}
                  >
                    <div className={`text-sm font-semibold ${active ? "text-[#002FA7]" : "text-zinc-900"}`}>{info.label}</div>
                    <div className="text-[11px] text-zinc-500 mt-0.5">{info.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-widest font-semibold text-zinc-600 mb-1.5">Cabang (Outlet)</label>
            <select
              data-testid="user-branch"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              className="w-full border border-zinc-300 px-3 py-2 text-sm bg-white focus:border-[#002FA7] focus:ring-1 focus:ring-[#002FA7] focus:outline-none"
            >
              <option value="">— Tidak ditentukan —</option>
              <option value="plaza">Plaza</option>
              <option value="kastem">Kastem</option>
            </select>
            <div className="text-[10px] font-mono text-zinc-500 mt-1">
              Cabang menentukan kolom Plaza/Kastem di Laporan Penjualan. Setiap transaksi yang dibuat oleh user ini otomatis tercatat pada cabang tersebut.
            </div>
          </div>

          {role === "admin_privileged" && (
            <div className="border border-zinc-200 bg-zinc-50/50 p-4">
              <div className="flex items-center justify-between mb-3">
                <label className="text-[11px] uppercase tracking-widest font-semibold text-zinc-700">Hak Akses Menu</label>
                <div className="flex items-center gap-2 text-[11px] font-mono">
                  <button type="button" onClick={() => setAllPerms(true)} data-testid="perms-select-all" className="text-[#002FA7] hover:underline">Pilih Semua</button>
                  <span className="text-zinc-300">·</span>
                  <button type="button" onClick={() => setAllPerms(false)} data-testid="perms-clear-all" className="text-zinc-500 hover:underline">Kosongkan</button>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {MENU_KEYS.map((k) => {
                  const active = permissions.includes(k);
                  return (
                    <label
                      key={k}
                      data-testid={`perm-check-${k}`}
                      onClick={(e) => { e.preventDefault(); togglePerm(k); }}
                      className={`flex items-center gap-2 border px-3 py-2 text-sm cursor-pointer select-none transition-colors ${
                        active
                          ? "border-[#002FA7] bg-[#002FA7]/5 text-zinc-900"
                          : "border-zinc-300 bg-white text-zinc-600 hover:border-zinc-400"
                      }`}
                    >
                      {active ? (
                        <CheckSquare className="w-4 h-4 text-[#002FA7]" strokeWidth={2.25} />
                      ) : (
                        <SquareIcon className="w-4 h-4 text-zinc-400" strokeWidth={2} />
                      )}
                      <span className={active ? "font-semibold" : ""}>{MENU_LABELS[k]}</span>
                    </label>
                  );
                })}
              </div>
              <div className="text-[10px] font-mono text-zinc-500 mt-3">
                {permissions.length} dari {MENU_KEYS.length} menu dicentang
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-200 sticky bottom-0 bg-white">
            <button type="button" onClick={onClose} className="border border-zinc-300 px-4 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-zinc-50">Batal</button>
            <button
              type="submit"
              data-testid="submit-user"
              disabled={submitting}
              className="bg-[#002FA7] text-white px-5 py-2 text-xs font-semibold uppercase tracking-wider hover:bg-[#002FA7]/90 disabled:opacity-50"
            >
              {submitting ? "Menyimpan…" : (isEdit ? "Simpan Perubahan" : "Buat User")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
