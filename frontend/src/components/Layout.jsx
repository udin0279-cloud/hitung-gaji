import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { LayoutDashboard, Users, Calculator, Settings as SettingsIcon, LogOut, Square } from "lucide-react";
import { useAuth } from "../context/AuthContext";

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/employees", label: "Karyawan", icon: Users, testId: "nav-employees" },
  { to: "/payroll", label: "Payroll", icon: Calculator, testId: "nav-payroll" },
  { to: "/settings", label: "Konfigurasi", icon: SettingsIcon, testId: "nav-settings" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen flex bg-zinc-50">
      {/* Sidebar */}
      <aside className="w-60 bg-white border-r border-zinc-200 flex flex-col no-print">
        <div className="px-5 py-6 border-b border-zinc-200">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-[#002FA7] flex items-center justify-center">
              <Square className="w-4 h-4 text-white" strokeWidth={2.5} fill="white" />
            </div>
            <div>
              <div className="font-heading font-bold text-zinc-900 leading-none tracking-tight">PAYROLL.ID</div>
              <div className="text-[10px] text-zinc-500 uppercase tracking-widest mt-1">HR Console</div>
            </div>
          </Link>
        </div>

        <nav className="flex-1 py-4">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                data-testid={item.testId}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-5 py-2.5 text-sm font-medium border-l-2 transition-colors ${
                    isActive
                      ? "border-[#002FA7] bg-zinc-50 text-zinc-900"
                      : "border-transparent text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900"
                  }`
                }
              >
                <Icon className="w-4 h-4" strokeWidth={2} />
                {item.label}
              </NavLink>
            );
          })}
        </nav>

        <div className="border-t border-zinc-200 p-4">
          <div className="text-[11px] uppercase tracking-widest text-zinc-400 font-semibold">Signed in</div>
          <div className="mt-1 text-sm text-zinc-900 font-medium truncate">{user?.name || "Admin"}</div>
          <div className="text-xs text-zinc-500 truncate">{user?.email}</div>
          <button
            data-testid="logout-button"
            onClick={handleLogout}
            className="mt-3 w-full inline-flex items-center justify-center gap-2 border border-zinc-300 hover:bg-zinc-900 hover:text-white text-zinc-900 px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors"
          >
            <LogOut className="w-3.5 h-3.5" /> Keluar
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0">
        <Outlet />
      </main>
    </div>
  );
}
