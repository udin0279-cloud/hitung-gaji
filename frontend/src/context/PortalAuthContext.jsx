import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../lib/api";

const PortalContext = createContext(null);

export function PortalAuthProvider({ children }) {
  const [employee, setEmployee] = useState(null); // null=loading, false=unauth, obj=authed
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/portal/me");
        setEmployee(data);
      } catch {
        setEmployee(false);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const login = async (email, nik) => {
    const { data } = await api.post("/portal/login", { email, nik });
    setEmployee(data);
    return data;
  };

  const logout = async () => {
    try { await api.post("/portal/logout"); } catch { /* ignore */ }
    setEmployee(false);
  };

  return (
    <PortalContext.Provider value={{ employee, loading, login, logout }}>
      {children}
    </PortalContext.Provider>
  );
}

export const usePortalAuth = () => useContext(PortalContext);
