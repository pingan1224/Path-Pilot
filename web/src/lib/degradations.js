// What a degraded turn looked like, said in words a student can act on.
//
// `degraded_modes` are audit keys — `keyword_fallback`, `tool_error:get_holds` — and
// printing them raw put strings like "retrieval_budget_exhausted" in front of students,
// which reads as an internal error rather than as the honest disclosure it is. The keys
// stay exactly as they are in the audit row; only the rendering changes.
//
// Unknown keys fall through to the key itself. A degradation that shows up unlabelled is
// ugly, and that is the right failure: silently dropping it would hide from the student
// that something ran differently than usual.
const LABELS = {
  keyword_fallback:
    "semantic search was unavailable, so policy results were ranked by keyword and may be less relevant",
  retrieval_budget_exhausted:
    "policy search reached its per-answer limit, so this answer rests on the passages already found",
  llm_error: "the assistant failed mid-answer and the question was routed to a human",
};

export function describeDegradation(mode) {
  if (LABELS[mode]) return LABELS[mode];
  // `tool_error:<name>` is generated per tool, so it cannot live in a fixed table.
  if (mode.startsWith("tool_error:")) {
    return `the ${mode.slice("tool_error:".length)} lookup failed, so it is not reflected here`;
  }
  return mode;
}

export function describeDegradations(modes) {
  return (modes || []).map(describeDegradation).join("; ");
}
