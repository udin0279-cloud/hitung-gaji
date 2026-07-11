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
import Layout from "@/components/Layout";
import PortalLogin from "@/pages/PortalLogin";
import PortalForgot from "@/pages/PortalForgot";
import PortalMagicLogin from "@/pages/PortalMagicLogin";
import { PortalDashboard, PortalPayslip } from "@/pages/Portal";
import PortalLeave from "@/pages/PortalLeave";

function ProtectedRoute({ children, allowedRoles }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-zinc-400 font-mono text-sm">Memuat…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    // Redirect role to their primary screen
    return <Navigate to={user.role === "hr_leave" ? "/leave" : "/"} replace />;
  }
  return children;
}

function HomeRedirect() {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-zinc-400 font-mono text-sm">Memuat…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role === "hr_leave") return <Navigate to="/leave" replace />;
  return <Dashboard />;
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
              <Route path="/employees" element={<ProtectedRoute allowedRoles={["super_admin"]}><Employees /></ProtectedRoute>} />
              <Route path="/payroll" element={<ProtectedRoute allowedRoles={["super_admin"]}><Payroll /></ProtectedRoute>} />
              <Route path="/payroll/:period" element={<ProtectedRoute allowedRoles={["super_admin"]}><PayrollDetail /></ProtectedRoute>} />
              <Route path="/payslip/:slipId" element={<ProtectedRoute allowedRoles={["super_admin"]}><Payslip /></ProtectedRoute>} />
              <Route path="/thr" element={<ProtectedRoute allowedRoles={["super_admin"]}><THR /></ProtectedRoute>} />
              <Route path="/leave" element={<ProtectedRoute allowedRoles={["super_admin", "hr_leave"]}><LeaveAdmin /></ProtectedRoute>} />
              <Route path="/users" element={<ProtectedRoute allowedRoles={["super_admin"]}><Users /></ProtectedRoute>} />
              <Route path="/inventory" element={<ProtectedRoute allowedRoles={["super_admin"]}><Inventory /></ProtectedRoute>} />
              <Route path="/settings" element={<ProtectedRoute allowedRoles={["super_admin"]}><Settings /></ProtectedRoute>} />
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
