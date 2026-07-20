// Central RBAC config for menu-level access.
// Must stay in sync with backend server.py MENU_KEYS.

export const MENU_KEYS = [
  "karyawan",
  "payroll",
  "inventory",
  "pembelian",
  "penjualan",
  "laporan_penjualan",
  "kas_operasional",
  "laba_rugi",
  "master_kategori",
  "thr",
  "izin_cuti",
  "kelola_user",
  "konfigurasi",
];

export const MENU_LABELS = {
  karyawan: "Karyawan",
  payroll: "Payroll",
  inventory: "Inventory",
  pembelian: "Pembelian",
  penjualan: "Penjualan",
  laporan_penjualan: "Laporan Penjualan",
  kas_operasional: "Kas Operasional",
  laba_rugi: "Laba/Rugi",
  master_kategori: "Master Kategori",
  thr: "THR",
  izin_cuti: "Izin & Cuti",
  kelola_user: "Kelola User",
  konfigurasi: "Konfigurasi",
};

// True if `user` may access a page requiring `menuKey`.
export function hasMenuAccess(user, menuKey) {
  if (!user) return false;
  if (user.role === "super_admin") return true;
  if (user.role === "admin_privileged") {
    return Array.isArray(user.permissions) && user.permissions.includes(menuKey);
  }
  // legacy hr_leave -> only izin_cuti (auto migrated on backend but be defensive)
  if (user.role === "hr_leave") return menuKey === "izin_cuti";
  return false;
}

// Return first accessible route for a user, used for post-login redirect.
export function firstAccessibleRoute(user) {
  if (!user) return "/login";
  if (user.role === "super_admin") return "/";
  const perms = user.permissions || [];
  const routeMap = {
    karyawan: "/employees",
    payroll: "/payroll",
    inventory: "/inventory",
    pembelian: "/purchasing",
    penjualan: "/sales",
    laporan_penjualan: "/laporan-penjualan",
    kas_operasional: "/cashbook",
    laba_rugi: "/reports",
    master_kategori: "/categories",
    thr: "/thr",
    izin_cuti: "/leave",
    kelola_user: "/users",
    konfigurasi: "/settings",
  };
  for (const k of MENU_KEYS) {
    if (perms.includes(k) && routeMap[k]) return routeMap[k];
  }
  return "/no-access";
}
