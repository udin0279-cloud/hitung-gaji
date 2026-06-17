import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

export function formatApiError(detail) {
  if (detail == null) return "Terjadi kesalahan. Coba lagi.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}

export function formatIDR(n) {
  if (n == null || isNaN(n)) return "Rp 0";
  return "Rp " + Math.round(n).toLocaleString("id-ID");
}

export function formatNumber(n) {
  if (n == null || isNaN(n)) return "0";
  return Math.round(n).toLocaleString("id-ID");
}
