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
import Layout from "@/components/Layout";
import PortalLogin from "@/pages/PortalLogin";
import PortalForgot from "@/pages/PortalForgot";
import PortalMagicLogin from "@/pages/PortalMagicLogin";
import { PortalDashboard, PortalPayslip } from "@/pages/Portal";
import PortalLeave from "@/pages/PortalLeave";

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-zinc-400 font-mono text-sm">Memuat…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
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
              <Route path="/" element={<Dashboard />} />
              <Route path="/employees" element={<Employees />} />
              <Route path="/payroll" element={<Payroll />} />
              <Route path="/payroll/:period" element={<PayrollDetail />} />
              <Route path="/payslip/:slipId" element={<Payslip />} />
              <Route path="/thr" element={<THR />} />
              <Route path="/leave" element={<LeaveAdmin />} />
              <Route path="/settings" element={<Settings />} />
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
