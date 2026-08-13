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
    const error = new Error(
      body?.error?.message ?? `Request failed (${response.status})`,
    );
    // The server's own code, carried through. Two 409s mean different things —
    // `program_not_stated` sends the student to the picker, `program_not_encoded` tells
    // them their (correct) answer is one this tool cannot audit — and a bare message
    // string forces callers to match on prose to tell them apart.
    error.code = body?.error?.code ?? null;
    error.status = response.status;
    throw error;
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
  // data — always the signed-in student's own record, scoped server-side by the session
  readiness: (id) => request(`/students/${id}/readiness`),
  // `history` is prior conversation text only — never tool results. Replaying a stale seat
  // count or hold status would put it in context looking as authoritative as this turn's
  // lookup; the server re-establishes every fact through tools scoped by the session.
  ask: (question, history = []) =>
    request("/assistant/ask", {
      method: "POST",
      body: JSON.stringify({ question, history }),
    }),
  // planner — always the signed-in user's own record
  catalogSearch: (q) => request(`/catalog/courses?q=${encodeURIComponent(q)}`),
  // Which programs a student can say they are in, and which one they picked. Only
  // `is_encoded` programs can be audited; the rest still get policy answers and error
  // decoding, and the picker says so rather than letting them find out from a refusal.
  programs: () => request("/catalog/programs"),
  program: () => request("/profile/program"),
  setProgram: (programCode) =>
    request("/profile/program", {
      method: "PUT",
      body: JSON.stringify({ program_code: programCode }),
    }),
  profileCourses: () => request("/profile/courses"),
  profilePut: (payload) =>
    request("/profile/courses", { method: "PUT", body: JSON.stringify(payload) }),
  profileDelete: (code) =>
    request(`/profile/courses/${encodeURIComponent(code)}`, { method: "DELETE" }),
  plan: (includePlanned) =>
    request(`/profile/plan?include_planned=${includePlanned ? "true" : "false"}`),
  whatIf: (courses) =>
    request("/profile/plan/what-if", { method: "POST", body: JSON.stringify({ courses }) }),
  // decoder — reads the pasted message; `answers` are replies to earlier follow-ups and
  // are classified together with it rather than tracked as server-side state
  decode: (text, answers = []) =>
    request("/decoder/decode", { method: "POST", body: JSON.stringify({ text, answers }) }),
  // intake — the upload is read and thrown away; nothing is written until confirm
  readTranscript: (file) => {
    const body = new FormData()
    body.append("file", file)
    // No Content-Type header on purpose: the browser must set the multipart boundary, and
    // the shared `request` helper would otherwise force application/json and break parsing.
    return request("/intake/transcript", { method: "POST", body, headers: {} })
  },
  confirmTranscript: (rows) =>
    request("/intake/confirm", { method: "POST", body: JSON.stringify({ rows }) }),
  // missions — every response is the whole mission with its recomputed step state, so the
  // client never derives progress itself and cannot disagree with the server about it
  missions: () => request("/missions"),
  createMission: (term) =>
    request("/missions", { method: "POST", body: JSON.stringify({ term }) }),
  mission: (id) => request(`/missions/${id}`),
  missionAddCandidate: (id, courseCode) =>
    request(`/missions/${id}/candidates`, {
      method: "POST",
      body: JSON.stringify({ course_code: courseCode }),
    }),
  missionDecideCandidate: (id, candidateId, confirm) =>
    request(`/missions/${id}/candidates/${candidateId}/decision`, {
      method: "POST",
      body: JSON.stringify({ confirm }),
    }),
  missionRemoveCandidate: (id, candidateId) =>
    request(`/missions/${id}/candidates/${candidateId}`, { method: "DELETE" }),
  missionAcknowledgeGaps: (id) =>
    request(`/missions/${id}/acknowledge-gaps`, { method: "POST" }),
  missionAcceptRisk: (id, payload) =>
    request(`/missions/${id}/accepted-risks`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  missionWithdrawRisk: (id, findingKey) =>
    request(`/missions/${id}/accepted-risks/${encodeURIComponent(findingKey)}`, {
      method: "DELETE",
    }),
  missionHandoff: (id, question) =>
    request(`/missions/${id}/handoff`, {
      method: "POST",
      body: JSON.stringify({ question: question || null }),
    }),
  // sequence — a GET because it computes and stores nothing; same inputs, same answer
  sequence: ({ startTerm, deadline, maxCredits } = {}) => {
    const params = new URLSearchParams();
    if (startTerm) params.set("start_term", startTerm);
    if (deadline) params.set("deadline", deadline);
    if (maxCredits) params.set("max_credits_per_term", String(maxCredits));
    const query = params.toString();
    return request(`/sequence${query ? `?${query}` : ""}`);
  },
  missionClose: (id, reason) =>
    request(`/missions/${id}/close`, {
      method: "POST",
      body: JSON.stringify({ reason: reason || null }),
    }),
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
