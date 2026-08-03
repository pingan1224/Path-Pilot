const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000/api/v1";

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
      ...options,
    });
  } catch {
    throw new Error("Cannot reach the API. Is the server running on port 8000?");
  }

  const body = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return body;
}

export const api = {
  ready: () => request("/health/ready"),
  students: () => request("/students"),
  readiness: (id) => request(`/students/${id}/readiness`),
  blockers: (id) => request(`/students/${id}/blockers`),
  advisors: () => request("/advisors"),
  advisorQueue: (id) => request(`/advisors/${id}/queue`),
  registrarPressure: () => request("/registrar/pressure"),
  cases: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return request(`/cases${query ? `?${query}` : ""}`);
  },
  createCase: (payload) =>
    request("/cases", { method: "POST", body: JSON.stringify(payload) }),
  updateCase: (id, payload) =>
    request(`/cases/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
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
