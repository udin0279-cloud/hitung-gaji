import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { LayoutDashboard, Users as UsersIcon, Calculator, Settings as SettingsIcon, LogOut, Square, Gift, CalendarDays, UserCog, Menu, X as XIcon, Package, TrendingUp, ShoppingCart, ShoppingBag } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";

const ALL_NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard", roles: ["super_admin"] },
  { to: "/employees", label: "Karyawan", icon: UsersIcon, testId: "nav-employees", badgeKey: "contract_expiring", roles: ["super_admin"] },
  { to: "/payroll", label: "Payroll", icon: Calculator, testId: "nav-payroll", roles: ["super_admin"] },
  { to: "/inventory", label: "Inventory", icon: Package, testId: "nav-inventory", roles: ["super_admin"] },
  { to: "/purchasing", label: "Pembelian", icon: ShoppingCart, testId: "nav-purchasing", roles: ["super_admin"] },
  { to: "/sales", label: "Penjualan", icon: ShoppingBag, testId: "nav-sales", roles: ["super_admin"] },
  { to: "/reports", label: "Laba/Rugi", icon: TrendingUp, testId: "nav-reports", roles: ["super_admin"] },
  { to: "/thr", label: "THR", icon: Gift, testId: "nav-thr", roles: ["super_admin"] },
  { to: "/leave", label: "Izin & Cuti", icon: CalendarDays, testId: "nav-leave", badgeKey: "pending", roles: ["super_admin", "hr_leave"] },
  { to: "/users", label: "Kelola User", icon: UserCog, testId: "nav-users", roles: ["super_admin"] },
  { to: "/settings", label: "Konfigurasi", icon: SettingsIcon, testId: "nav-settings", roles: ["super_admin"] },
];

const ROLE_BADGE = {
  super_admin: { label: "Super Admin", color: "text-[#002FA7]" },
  hr_leave: { label: "HR Izin & Cuti", color: "text-emerald-700" },
};

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [pendingLeaves, setPendingLeaves] = useState(0);
  const [expiringContracts, setExpiringContracts] = useState(0);
  const [mobileOpen, setMobileOpen] = useState(false);

  const role = user?.role;
  const navItems = ALL_NAV.filter((n) => !n.roles || n.roles.includes(role));

  const loadStats = async () => {
    // Leave stats
    if (navItems.some((n) => n.badgeKey === "pending")) {
      try {
        const { data } = await api.get("/leave/stats");
        setPendingLeaves(data.pending || 0);
      } catch {
        // ignore
      }
    }
    // Contract expiring (only for super_admin)
    if (navItems.some((n) => n.badgeKey === "contract_expiring")) {
      try {
        const { data } = await api.get("/contracts/expiring?days=30");
        setExpiringContracts(data.count || 0);
      } catch {
        // ignore
      }
    }
  };

  useEffect(() => {
    loadStats();
    const t = setInterval(loadStats, 60000);
    return () => clearInterval(t);
  }, [role]);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const roleInfo = ROLE_BADGE[role];

  const SidebarContent = (
    <>
      <div className="px-5 py-6 border-b border-zinc-200 flex items-center justify-between">
        <Link to="/" onClick={() => setMobileOpen(false)} className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-[#002FA7] flex items-center justify-center">
            <Square className="w-4 h-4 text-white" strokeWidth={2.5} fill="white" />
          </div>
          <div>
            <div className="font-heading font-bold text-zinc-900 leading-none tracking-tight">PAYROLL.ID</div>
            <div className="text-[10px] text-zinc-500 uppercase tracking-widest mt-1">HR Console</div>
          </div>
        </Link>
        <button
          data-testid="close-mobile-menu"
          onClick={() => setMobileOpen(false)}
          className="md:hidden p-1.5 hover:bg-zinc-100"
          aria-label="Close menu"
        >
          <XIcon className="w-4 h-4" />
        </button>
      </div>

      <nav className="flex-1 py-4 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          const badgeCount =
            item.badgeKey === "pending"
              ? pendingLeaves
              : item.badgeKey === "contract_expiring"
              ? expiringContracts
              : 0;
          const badgeColor = item.badgeKey === "contract_expiring" ? "bg-amber-600" : "bg-rose-600";
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              data-testid={item.testId}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-5 py-2.5 text-sm font-medium border-l-2 transition-colors ${
                  isActive
                    ? "border-[#002FA7] bg-zinc-50 text-zinc-900"
                    : "border-transparent text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900"
                }`
              }
            >
              <Icon className="w-4 h-4" strokeWidth={2} />
              <span className="flex-1">{item.label}</span>
              {badgeCount > 0 && (
                <span
                  data-testid={`badge-${item.testId}`}
                  className={`${badgeColor} text-white text-[10px] font-bold px-1.5 py-0.5 min-w-[18px] text-center leading-none rounded-sm`}
                >
                  {badgeCount}
                </span>
              )}
            </NavLink>
          );
        })}
      </nav>

      <div className="border-t border-zinc-200 p-4">
        <div className="text-[11px] uppercase tracking-widest text-zinc-400 font-semibold">Signed in</div>
        <div className="mt-1 text-sm text-zinc-900 font-medium truncate">{user?.name || "Admin"}</div>
        <div className="text-xs text-zinc-500 truncate">{user?.email}</div>
        {roleInfo && (
          <div
            data-testid="user-role-badge"
            className={`mt-1.5 text-[10px] uppercase tracking-widest font-bold ${roleInfo.color}`}
          >
            {roleInfo.label}
          </div>
        )}
        <button
          data-testid="logout-button"
          onClick={handleLogout}
          className="mt-3 w-full inline-flex items-center justify-center gap-2 border border-zinc-300 hover:bg-zinc-900 hover:text-white text-zinc-900 px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" /> Keluar
        </button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen flex bg-zinc-50">
      {/* Mobile top bar (visible < md) */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-30 bg-white border-b border-zinc-200 flex items-center justify-between px-4 py-3 no-print">
        <button
          data-testid="open-mobile-menu"
          onClick={() => setMobileOpen(true)}
          className="p-1.5 -ml-1.5 hover:bg-zinc-100"
          aria-label="Open menu"
        >
          <Menu className="w-5 h-5 text-zinc-900" />
        </button>
        <Link to="/" className="flex items-center gap-2">
          <div className="w-6 h-6 bg-[#002FA7] flex items-center justify-center">
            <Square className="w-3 h-3 text-white" strokeWidth={2.5} fill="white" />
          </div>
          <div className="font-heading font-bold text-sm text-zinc-900 tracking-tight">PAYROLL.ID</div>
        </Link>
        <div className="w-8" />{/* spacer to balance */}
      </div>

      {/* Desktop Sidebar (visible >= md) */}
      <aside className="hidden md:flex w-60 bg-white border-r border-zinc-200 flex-col no-print shrink-0">
        {SidebarContent}
      </aside>

      {/* Mobile Sidebar Drawer */}
      {mobileOpen && (
        <>
          <div
            onClick={() => setMobileOpen(false)}
            className="md:hidden fixed inset-0 z-40 bg-zinc-900/50 no-print"
          />
          <aside className="md:hidden fixed top-0 left-0 bottom-0 z-50 w-64 bg-white border-r border-zinc-200 flex flex-col no-print shadow-2xl">
            {SidebarContent}
          </aside>
        </>
      )}

      {/* Main */}
      <main className="flex-1 min-w-0 pt-14 md:pt-0">
        <Outlet />
      </main>
    </div>
  );
}
