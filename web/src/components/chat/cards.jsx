import { useState } from "react"
import { AlertTriangle, ArrowRight, Sparkles } from "lucide-react"
import { api } from "@/api"
import { Banner, Chip, Code, MakeCard, Muted } from "@/components/make"
import { Button } from "@/components/ui/button"

/**
 * Inline artifact cards for the chat surface, in the shared card language.
 *
 * The server's Artifact Contract decides what appears here: each answer carries
 * `artifacts`, each one re-read from authoritative state at answer time — never a
 * snapshot from mid-turn, and never inferred client-side from the audit trail the way
 * this file's first version did. That is the same "no stored status, recompute on read"
 * rule the mission engine lives by: a card the student acts on must never disagree with
 * the page they would see elsewhere.
 *
 * The type → component mapping below is this client's action registry. The server
 * describes what an artifact is; which endpoints its buttons call is decided here and
 * nowhere else — an artifact cannot smuggle in a URL. A type this build does not know
 * falls back to a plain note rather than failing the whole answer.
 *
 * And the buttons are real. "Add to my plan" calls the same student-authenticated
 * endpoint the Mission page uses, and the server's recomputed mission replaces the card
 * state.
 */

/** One artifact from the server, rendered by this client's registry — or the fallback. */
export function ArtifactCard({ artifact, onOpenView }) {
  switch (artifact.type) {
    case "mission_state":
      return <MissionCard mission={artifact.data} onOpenView={onOpenView} />
    case "course_sequence":
      return <SequenceCard plan={artifact.data} onOpenView={onOpenView} />
    case "decoder_result":
      return <DecodeCard decoded={artifact.data} onOpenView={onOpenView} />
    default:
      return (
        <MakeCard className="p-4">
          <Muted>
            The assistant produced a result ({artifact.type}) this version of the app
            cannot display. The answer above still stands on its own.
          </Muted>
        </MakeCard>
      )
  }
}

const TERM_SUGGESTIONS = ["Fall 2026", "Spring 2027", "Summer 2027"]

const STEP_LABEL = {
  profile: "Enter your record",
  gaps: "Review degree gaps",
  candidates: "Choose courses",
  open_items: "Settle open items",
  handoff: "Advisor handoff",
}

/** The card's footer link into the full page. */
function OpenLink({ children, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mt-3 flex items-center gap-1.5 text-[12px] font-medium"
      style={{ color: "var(--color-violet-light)" }}
    >
      {children}
      <ArrowRight size={12} aria-hidden="true" />
    </button>
  )
}

/** Mission state with actionable proposals; also covers the "no mission yet" case. */
export function MissionCard({ mission: initial, onOpenView }) {
  const [mission, setMission] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function act(fn) {
    setBusy(true)
    setError(null)
    try {
      setMission(await fn())
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // No mission on the account. Starting one is a student action — the agent cannot do
  // this (see the mission service), so the card offers the click rather than doing it.
  if (!mission) {
    return (
      <MakeCard className="p-4">
        <div className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
          No registration mission yet
        </div>
        <p className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
          A mission tracks your preparation for one term — courses chosen, blockers
          settled, a summary for your advisor. Pick a term to start one.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {TERM_SUGGESTIONS.map((term) => (
            <button
              key={term}
              type="button"
              disabled={busy}
              onClick={() => act(() => api.createMission(term))}
              className="rounded-full px-3 py-1.5 text-[12px]"
              style={{
                background: "var(--color-surface-2)",
                border: "1px solid var(--color-rail-strong)",
                color: "var(--color-ink-2)",
              }}
            >
              {term}
            </button>
          ))}
        </div>
        {error ? (
          <div className="mt-2">
            <Banner toneName="danger" role="alert">
              {error}
            </Banner>
          </div>
        ) : null}
      </MakeCard>
    )
  }

  const done = mission.steps.filter((s) => s.state === "done").length
  const active = mission.steps.find((s) => s.state === "active")
  const proposals = mission.candidates.filter((c) => c.state === "proposed")
  const chosen = mission.candidates.filter((c) => c.state === "confirmed")

  return (
    <MakeCard className="p-4" toneName="accent">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
          Registration mission — {mission.term}
        </span>
        {mission.complete ? <Chip toneName="good">Complete</Chip> : null}
        {/* Badged so nobody is surprised to find a container they did not create. The
            term is the only thing the assistant chose, and it is changeable. */}
        {mission.created_by === "ai" ? <Chip toneName="accent">Started by the assistant</Chip> : null}
      </div>
      <p className="mt-1 text-[12px]" style={{ color: "var(--color-ink-3)" }}>
        {done} of {mission.steps.length} steps done
        {active ? ` · now: ${STEP_LABEL[active.id] ?? active.title}` : ""}
      </p>

      <div
        className="mt-3 h-1.5 overflow-hidden rounded-full"
        style={{ background: "var(--color-surface-3)" }}
      >
        <div
          className="h-full rounded-full"
          style={{
            width: `${(done / mission.steps.length) * 100}%`,
            background: "linear-gradient(90deg, var(--color-violet), var(--color-violet-light))",
            transition: "width 700ms cubic-bezier(0.22,1,0.36,1)",
          }}
        />
      </div>

      {proposals.length > 0 ? (
        <div className="mt-3 flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span
              className="flex items-center gap-1.5 text-[11px] font-medium"
              style={{ color: "var(--color-violet-light)" }}
            >
              <Sparkles size={11} aria-hidden="true" />
              Suggested — not in your plan until you confirm
            </span>
            {/* One click for a whole one-shot proposal. Still one deliberate act per
                batch, and each course keeps its own buttons for picking selectively —
                batching the click must not blur what was agreed to. */}
            {proposals.length > 1 ? (
              <Button
                size="xs"
                variant="outline"
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    let latest = mission
                    for (const c of proposals) {
                      latest = await api.missionDecideCandidate(mission.id, c.id, true)
                    }
                    return latest
                  })
                }
              >
                Add all {proposals.length}
              </Button>
            ) : null}
          </div>
          {proposals.map((c, i) => (
            <div
              key={c.id}
              className="pp-slide-up rounded-xl p-3"
              style={{
                background: "var(--color-violet-muted)",
                border: "1px solid rgba(124,58,237,0.25)",
                animationDelay: `${i * 60}ms`,
              }}
            >
              <Code>{c.course_code}</Code>
              {c.rationale ? (
                <p
                  className="mt-1 text-[11px] leading-relaxed"
                  style={{ color: "var(--color-ink-2)" }}
                >
                  {c.rationale}
                </p>
              ) : null}
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Button
                  size="xs"
                  disabled={busy}
                  onClick={() => act(() => api.missionDecideCandidate(mission.id, c.id, true))}
                >
                  Add to my plan
                </Button>
                <Button
                  size="xs"
                  variant="outline"
                  disabled={busy}
                  onClick={() => act(() => api.missionDecideCandidate(mission.id, c.id, false))}
                >
                  No thanks
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {chosen.length > 0 ? (
        <p className="mt-3 text-[11px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
          Chosen: {chosen.map((c) => c.course_code).join(", ")}
        </p>
      ) : null}

      {mission.open_blockers.length > 0 ? (
        <div className="mt-2">
          <Banner toneName="danger" icon={AlertTriangle}>
            {mission.open_blockers.length} unresolved blocker
            {mission.open_blockers.length === 1 ? "" : "s"} on your chosen courses.
          </Banner>
        </div>
      ) : null}

      {error ? (
        <div className="mt-2">
          <Banner toneName="danger" role="alert">
            {error}
          </Banner>
        </div>
      ) : null}

      <OpenLink onClick={() => onOpenView?.("mission")}>Open the full mission</OpenLink>
    </MakeCard>
  )
}

const BASIS_CHIP = {
  published: { toneName: "good", label: "Published" },
  irregular: { toneName: "warn", label: "Irregular — guess" },
  unstated: { toneName: "neutral", label: "Term is a guess" },
}

/** Compact term-by-term schedule, or the binding constraint when nothing fits. */
export function SequenceCard({ plan, onOpenView }) {
  if (!plan.feasible) {
    return (
      <MakeCard className="p-4">
        <div className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
          No sequence fits
        </div>
        <p className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
          {plan.infeasibility?.explanation}
        </p>
        {plan.infeasibility?.remedies?.length ? (
          <ul className="mt-2 space-y-1">
            {plan.infeasibility.remedies.map((remedy, i) => (
              <li key={i} className="text-[12px]" style={{ color: "var(--color-ink-2)" }}>
                • {remedy}
              </li>
            ))}
          </ul>
        ) : null}
        <OpenLink onClick={() => onOpenView?.("sequence")}>Adjust the constraints</OpenLink>
      </MakeCard>
    )
  }

  const guesses = plan.terms
    .flatMap((t) => t.courses)
    .filter((c) => c.offering_basis !== "published").length

  // What each of next term's courses costs if it waits, keyed for the row that names it.
  // The grid answers "in what order"; this answers "why this one, why now" — which is the
  // question the product is for, so it renders beside the course rather than under the
  // card.
  const costByCode = Object.fromEntries((plan.delay_costs ?? []).map((c) => [c.code, c]))

  return (
    <MakeCard className="p-4">
      <div className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
        {plan.terms_needed} term{plan.terms_needed === 1 ? "" : "s"}, finishing {plan.finish_term}
      </div>
      <p className="mt-1 text-[12px]" style={{ color: "var(--color-ink-3)" }}>
        {plan.chosen_track ? `Concentration: ${plan.chosen_track} · ` : ""}
        {plan.max_credits_per_term} credits/term
        {plan.credit_cap_was_assumed ? " (assumed)" : ""}
        {guesses > 0
          ? ` · ${guesses} placement${guesses === 1 ? "" : "s"} in unconfirmed terms`
          : ""}
      </p>

      <div className="mt-3 flex flex-col gap-2">
        {plan.terms.map((term, termIndex) => (
          <div
            key={term.term}
            className="rounded-xl p-3"
            style={{
              background: "var(--color-surface-2)",
              border: `1px solid ${termIndex === 0 ? "rgba(124,58,237,0.25)" : "var(--color-rail)"}`,
            }}
          >
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-[12px] font-semibold" style={{ color: "var(--color-ink)" }}>
                {term.term}
              </span>
              <span className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                · {term.credits} cr{termIndex === 0 ? " · next term" : ""}
              </span>
            </div>
            <div className="mt-1.5 flex flex-col gap-1.5">
              {term.courses.map((course) => {
                const chip = BASIS_CHIP[course.offering_basis] ?? BASIS_CHIP.unstated
                const cost = termIndex === 0 ? costByCode[course.course_code] : undefined
                return (
                  <div key={course.course_code} className="flex flex-col gap-0.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <Code>{course.course_code}</Code>
                      <Chip toneName={chip.toneName}>{chip.label}</Chip>
                      {cost?.breaks_plan ? (
                        <Chip toneName="danger">Cannot wait</Chip>
                      ) : cost?.terms_lost > 0 ? (
                        <Chip toneName="warn">
                          +{cost.terms_lost} term{cost.terms_lost === 1 ? "" : "s"} if it waits
                        </Chip>
                      ) : null}
                    </div>
                    {cost ? (
                      <p className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                        {cost.explanation}
                      </p>
                    ) : null}
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {plan.assumptions.length > 0 ? (
        <p className="mt-2 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
          Rests on {plan.assumptions.length} assumption
          {plan.assumptions.length === 1 ? "" : "s"} — check them before relying on this.
        </p>
      ) : null}

      <OpenLink onClick={() => onOpenView?.("sequence")}>Open the full sequence</OpenLink>
    </MakeCard>
  )
}

const OUTCOME_CHIP = {
  identified: { toneName: "good", label: "Cause identified" },
  ambiguous: { toneName: "warn", label: "Needs one more detail" },
  unrecognized: { toneName: "neutral", label: "Could not decode" },
}

/** Compact decoded-error result with the follow-up question when there is one. */
export function DecodeCard({ decoded, onOpenView }) {
  const chip = OUTCOME_CHIP[decoded.outcome] ?? OUTCOME_CHIP.unrecognized
  const followUp = decoded.follow_ups?.[0]

  return (
    <MakeCard className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
          {decoded.reason_label ?? "Registration error"}
        </span>
        <Chip toneName={chip.toneName}>{chip.label}</Chip>
      </div>
      {decoded.reading ? (
        <p className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
          {decoded.reading}
        </p>
      ) : null}

      <div className="mt-2 flex flex-col gap-2">
        {decoded.outcome === "ambiguous" && decoded.candidates?.length > 1 ? (
          <p className="text-[12px]" style={{ color: "var(--color-ink-2)" }}>
            Consistent with:{" "}
            {decoded.candidates
              .slice(0, 2)
              .map((c) => c.label)
              .join(" — or — ")}
          </p>
        ) : null}
        {followUp ? (
          <Banner toneName="accent" title="To narrow it down">
            {followUp.question}
          </Banner>
        ) : null}
        {decoded.responsible_office ? (
          <p className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
            Who can act: {decoded.responsible_office.replace(/_/g, " ")}
          </p>
        ) : null}
      </div>

      <OpenLink onClick={() => onOpenView?.("decoder")}>Open the full decoder</OpenLink>
    </MakeCard>
  )
}
