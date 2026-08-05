// Relative by default: the dev server and the production platform both proxy /api to the
// backend, keeping the session cookie same-origin. See vite.config.js.
const BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

/** Thrown on 401 so views can distinguish "signed out" from other failures. */
export class UnauthenticatedError extends Error {}

/**
 * Every response from this API is either data or `{ error: { code, message } }`.
 * Errors are thrown with the server's own message so views can show what actually went
 * wrong instead of a generic failure string.
 */
async function request(path, options) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      ...options,
    });
  } catch {
    throw new Error("Cannot reach the API. Is the server running?");
  }

  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);

  if (response.status === 401) {
    throw new UnauthenticatedError(body?.error?.message ?? "Not signed in.");
  }
  if (!response.ok) {
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return body;
}

export const api = {
  ready: () => request("/health/ready"),
  // auth
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request("/auth/logout", { method: "POST" }),
  me: () => request("/auth/me"),
  // data — all scoped server-side by the session
  students: () => request("/students"),
  readiness: (id) => request(`/students/${id}/readiness`),
  blockers: (id) => request(`/students/${id}/blockers`),
  advisorQueue: () => request("/advisors/queue"),
  registrarPressure: () => request("/registrar/pressure"),
  cases: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return request(`/cases${query ? `?${query}` : ""}`);
  },
  createCase: (payload) =>
    request("/cases", { method: "POST", body: JSON.stringify(payload) }),
  updateCase: (id, payload) =>
    request(`/cases/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  ask: (question) =>
    request("/assistant/ask", { method: "POST", body: JSON.stringify({ question }) }),
};

/** "3 hours ago" — the API gives us seconds, the UI needs words. */
export function humanizeAge(seconds) {
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) {
    const hours = Math.floor(seconds / 3600);
    return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  }
  const days = Math.floor(seconds / 86400);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

export function formatMoney(cents) {
  if (cents == null) return null;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    cents / 100,
  );
}

export function formatDate(value) {
  if (!value) return null;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}
