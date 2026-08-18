/**
 * The one verdict table.
 *
 * This existed three times — DecoderView, MissionView, PlannerView — and the copies had
 * already drifted: only PlannerView's carried a `label`, so in the other two views a
 * finding's verdict reached the reader as a coloured left border and a glyph and nothing
 * else. That is the "never colour alone" rule in ARCHITECTURE.md failing in two of the three
 * places it applies, caused by nothing but a copied object literal.
 *
 * `label` names the verdict; `action` is the phrase the UI principle requires each tone to
 * carry, kept beside the label rather than replacing it so a reader gets the specific word
 * ("Not met") and an assistive-tech user still gets the generic instruction
 * ("Action required"). `mark` is decoration and is always rendered aria-hidden — a screen
 * reader announcing "heavy multiplication x" is noise, not meaning.
 */
export const VERDICT_META = {
  satisfied: { mark: "✓", label: "Verified", action: "No immediate action", tone: "good" },
  conditional: { mark: "◐", label: "Holds if…", action: "Review recommended", tone: "warn" },
  unverifiable: { mark: "?", label: "Ask a human", action: "Review recommended", tone: "neutral" },
  not_satisfied: { mark: "✕", label: "Not met", action: "Action required", tone: "danger" },
};

export function verdictMeta(verdict) {
  return VERDICT_META[verdict] ?? VERDICT_META.unverifiable;
}
