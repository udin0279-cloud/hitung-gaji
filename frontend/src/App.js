import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { PortalAuthProvider, usePortalAuth } from "@/context/PortalAuthContext";
import { Toaster } from "sonner";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Employees from "@/pages/Employees";
import Payroll from "@/pages/Payroll";
import PayrollDetail from "@/pages/PayrollDetail";
import Payslip from "@/pages/Payslip";
import THR from "@/pages/THR";
import Settings from "@/pages/Settings";
import LeaveAdmin from "@/pages/LeaveAdmin";
import Users from "@/pages/Users";
import Inventory from "@/pages/Inventory";
import Purchasing from "@/pages/Purchasing";
import Sales from "@/pages/Sales";
import Reports from "@/pages/Reports";
import SalesReport from "@/pages/SalesReport";
import ShopeeRincianReport from "@/pages/ShopeeRincianReport";
import CashBook from "@/pages/CashBook";
import Categories from "@/pages/Categories";
import Layout from "@/components/Layout";
import AccessDenied from "@/components/AccessDenied";
import PortalLogin from "@/pages/PortalLogin";
import PortalForgot from "@/pages/PortalForgot";
import PortalMagicLogin from "@/pages/PortalMagicLogin";
import { PortalDashboard, PortalPayslip } from "@/pages/Portal";
import PortalLeave from "@/pages/PortalLeave";
import { hasMenuAccess, firstAccessibleRoute, MENU_LABELS } from "@/lib/menuAccess";

function ProtectedRoute({ children, menuKey }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-zinc-400 font-mono text-sm">Memuat…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (menuKey && !hasMenuAccess(user, menuKey)) {
    return <AccessDenied menuLabel={MENU_LABELS[menuKey]} />;
  }
  return children;
}

function HomeRedirect() {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-zinc-400 font-mono text-sm">Memuat…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role === "super_admin") return <Dashboard />;
  // Admin dengan Privilege: redirect ke halaman pertama yang bisa diakses
  const first = firstAccessibleRoute(user);
  if (first === "/no-access" || first === "/") return <AccessDenied menuLabel="Beranda" />;
  return <Navigate to={first} replace />;
}

function PortalProtected({ children }) {
  const { employee, loading } = usePortalAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-zinc-400 font-mono text-sm">Memuat…</div>;
  if (!employee) return <Navigate to="/portal/login" replace />;
  return children;
}

function App() {
  return (
    <AuthProvider>
      <PortalAuthProvider>
        <BrowserRouter>
          <Toaster position="top-right" />
          <Routes>
            {/* Admin */}
            <Route path="/login" element={<Login />} />
            <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
              <Route path="/" element={<HomeRedirect />} />
              <Route path="/employees" element={<ProtectedRoute menuKey="karyawan"><Employees /></ProtectedRoute>} />
              <Route path="/payroll" element={<ProtectedRoute menuKey="payroll"><Payroll /></ProtectedRoute>} />
              <Route path="/payroll/:period" element={<ProtectedRoute menuKey="payroll"><PayrollDetail /></ProtectedRoute>} />
              <Route path="/payslip/:slipId" element={<ProtectedRoute menuKey="payroll"><Payslip /></ProtectedRoute>} />
              <Route path="/thr" element={<ProtectedRoute menuKey="thr"><THR /></ProtectedRoute>} />
              <Route path="/leave" element={<ProtectedRoute menuKey="izin_cuti"><LeaveAdmin /></ProtectedRoute>} />
              <Route path="/users" element={<ProtectedRoute menuKey="kelola_user"><Users /></ProtectedRoute>} />
              <Route path="/inventory" element={<ProtectedRoute menuKey="inventory"><Inventory /></ProtectedRoute>} />
              <Route path="/purchasing" element={<ProtectedRoute menuKey="pembelian"><Purchasing /></ProtectedRoute>} />
              <Route path="/sales" element={<ProtectedRoute menuKey="penjualan"><Sales /></ProtectedRoute>} />
              <Route path="/cashbook" element={<ProtectedRoute menuKey="kas_operasional"><CashBook /></ProtectedRoute>} />
              <Route path="/categories" element={<ProtectedRoute menuKey="master_kategori"><Categories /></ProtectedRoute>} />
              <Route path="/reports" element={<ProtectedRoute menuKey="laba_rugi"><Reports /></ProtectedRoute>} />
              <Route path="/laporan-penjualan" element={<ProtectedRoute menuKey="laporan_penjualan"><SalesReport /></ProtectedRoute>} />
              <Route path="/laporan-rincian-shopee" element={<ProtectedRoute menuKey="laporan_penjualan"><ShopeeRincianReport /></ProtectedRoute>} />
              <Route path="/settings" element={<ProtectedRoute menuKey="konfigurasi"><Settings /></ProtectedRoute>} />
            </Route>

            {/* Employee Portal */}
            <Route path="/portal/login" element={<PortalLogin />} />
            <Route path="/portal/forgot" element={<PortalForgot />} />
            <Route path="/portal/magic-login" element={<PortalMagicLogin />} />
            <Route path="/portal" element={<PortalProtected><PortalDashboard /></PortalProtected>} />
            <Route path="/portal/payslip/:slipId" element={<PortalProtected><PortalPayslip /></PortalProtected>} />
            <Route path="/portal/leave" element={<PortalProtected><PortalLeave /></PortalProtected>} />

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </PortalAuthProvider>
    </AuthProvider>
  );
}

export default App;
