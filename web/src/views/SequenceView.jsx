import { useEffect, useState } from "react"
import {
  AlertTriangle,
  Calendar,
  CheckCircle,
  ChevronDown,
  Circle,
  GraduationCap,
  Info,
  Sparkles,
} from "lucide-react"
import { api } from "@/api"
import { Finding } from "@/components/Finding"
import {
  ErrorNote,
  INPUT_CLASS,
  Muted,
  ProgramNotice,
  WarnNote,
  isProgramIssue,
} from "@/components/nocturne"
import { Button } from "@/components/ui/button"
import { usePrefs } from "@/i18n"

/**
 * The sequence planner in the source design's term-column language (1:1 branch):
 * header with an on-track graduation card and the violet recompute button, amber
 * placement warning, sky assumptions disclosure, then terms side by side — Spring in
 * emerald, Fall in violet, each with a credits bar and course cards.
 *
 * What each element carries is real, and the differences from the design are all
 * data-honesty, not taste: the on-track card shows the solver's actual finish term;
 * "Recalculate" re-runs the real backtracking solve (no staged 1.6s theatre); the
 * assumptions list is the solver's own — the per-term credit cap is the student's
 * number, offerings the bulletin does not publish are guesses and each placement says
 * so on itself; and the design's drag-to-resequence is deliberately absent, because
 * dragging a course into a term is a claim about prerequisites and offerings that only
 * the solver can check — the honest lever is the constraint form, then re-solve.
 */

const CREDIT_CHOICES = [3, 6, 9, 12]

const SEM_STYLE = {
  Spring: { primary: "var(--color-emerald)", bg: "var(--color-emerald-muted)", border: "rgba(4,120,87,0.2)" },
  Fall: { primary: "var(--color-violet-light)", bg: "var(--color-violet-muted)", border: "rgba(124,58,237,0.25)" },
  Summer: { primary: "var(--color-amber)", bg: "var(--color-amber-muted)", border: "rgba(180,83,9,0.2)" },
}

const semesterOf = (term) => {
  const season = String(term).split(" ")[0]
  return SEM_STYLE[season] ?? SEM_STYLE.Fall
}

const BASIS_META = {
  published: { icon: CheckCircle, color: "var(--color-emerald)", label: "Published" },
  irregular: { icon: AlertTriangle, color: "var(--color-amber)", label: "Runs irregularly" },
  unstated: { icon: Circle, color: "var(--color-ink-3)", label: "Term is a guess" },
}

export default function SequenceView({ onOpenPlanner, onOpenProgram }) {
  const { t } = usePrefs()
  const [startTerm, setStartTerm] = useState("")
  const [deadline, setDeadline] = useState("")
  const [maxCredits, setMaxCredits] = useState("")
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [showAssumptions, setShowAssumptions] = useState(false)

  async function load(overrides = {}) {
    setBusy(true)
    setError(null)
    try {
      setPlan(
        await api.sequence({
          startTerm: overrides.startTerm ?? startTerm,
          deadline: overrides.deadline ?? deadline,
          maxCredits: overrides.maxCredits ?? maxCredits,
        }),
      )
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error && !plan) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-6">
        {isProgramIssue(error.code) ? (
          <ProgramNotice code={error.code} message={error.message} onChooseProgram={onOpenProgram} />
        ) : (
          <div className="flex flex-col items-start gap-3">
            <ErrorNote>Could not compute a sequence: {error.message}</ErrorNote>
            <Button variant="outline" size="sm" onClick={() => load()}>
              Try again
            </Button>
          </div>
        )}
      </div>
    )
  }
  if (!plan) {
    return (
      <p role="status" className="px-6 py-6 text-[13px]" style={{ color: "var(--color-ink-3)" }}>
        Solving your sequence…
      </p>
    )
  }

  const guesses = plan.feasible
    ? plan.terms.flatMap((tm) => tm.courses).filter((c) => c.offering_basis !== "published").length
    : 0

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header — the design's: icon, title, on-track card, violet recompute. */}
      <div
        className="pp-slide-down shrink-0 px-6 py-4"
        style={{ borderBottom: "1px solid var(--color-rail)", background: "var(--color-surface)" }}
      >
        <div className="flex flex-wrap items-center gap-4">
          <Calendar size={16} style={{ color: "var(--color-violet-light)" }} aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <div className="text-[14px] font-semibold" style={{ color: "var(--color-ink)" }}>
              {t("nav.sequence")}
            </div>
            <div className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
              Prerequisite order, published offerings, your credit load, one concentration in
              full, a term to finish by — solved together.
            </div>
          </div>
          {plan.feasible ? (
            <div
              className="flex items-center gap-2 rounded-xl px-3 py-2"
              style={{ background: "var(--color-emerald-muted)", border: "1px solid rgba(4,120,87,0.2)" }}
            >
              <GraduationCap size={13} style={{ color: "var(--color-emerald)" }} aria-hidden="true" />
              <div>
                <div className="text-[10px]" style={{ color: "var(--color-emerald)", opacity: 0.75 }}>
                  {plan.terms_needed} more term{plan.terms_needed === 1 ? "" : "s"}
                </div>
                <div className="text-[12px] font-semibold" style={{ color: "var(--color-emerald)" }}>
                  Finishing {plan.finish_term}
                </div>
              </div>
            </div>
          ) : null}
          <button
            type="button"
            onClick={() => load()}
            disabled={busy}
            className="flex items-center gap-2 rounded-xl px-3 py-2 text-[12px] font-medium"
            style={{
              background: busy ? "var(--color-surface-2)" : "var(--color-violet)",
              color: busy ? "var(--color-ink-3)" : "#fff",
              transition: "background 200ms ease, color 200ms ease",
              cursor: busy ? "not-allowed" : "pointer",
            }}
          >
            <Sparkles
              size={12}
              aria-hidden="true"
              style={{ animation: busy ? "pp-spinner 1s linear infinite" : "none" }}
            />
            {busy ? "Solving…" : "Recalculate"}
          </button>
        </div>

        {/* Constraint form — the honest lever the design's drag-and-drop is not. */}
        <form
          className="mt-3 flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            load()
          }}
        >
          <label className="flex min-w-[140px] flex-1 flex-col gap-1 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
            Starting term
            <input
              className={INPUT_CLASS}
              value={startTerm}
              onChange={(e) => setStartTerm(e.target.value)}
              placeholder={plan.start_term}
              disabled={busy}
            />
          </label>
          <label className="flex min-w-[140px] flex-1 flex-col gap-1 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
            Finish by (optional)
            <input
              className={INPUT_CLASS}
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
              placeholder="e.g. Spring 2028"
              disabled={busy}
            />
          </label>
          <label className="flex min-w-[120px] flex-col gap-1 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
            Credits per term
            <select
              className={INPUT_CLASS}
              value={maxCredits}
              onChange={(e) => {
                setMaxCredits(e.target.value)
                load({ maxCredits: e.target.value })
              }}
              disabled={busy}
            >
              <option value="">{plan.max_credits_per_term} (assumed)</option>
              {CREDIT_CHOICES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </form>
      </div>

      {/* Warnings + assumptions, the design's banner stack. */}
      <div className="shrink-0 space-y-2 px-6 pt-4 pb-0">
        {error ? <ErrorNote>{error.message}</ErrorNote> : null}
        {guesses > 0 ? (
          <div
            className="pp-slide-up flex items-start gap-2.5 rounded-xl px-4 py-2.5"
            style={{ background: "var(--color-amber-muted)", border: "1px solid rgba(180,83,9,0.2)" }}
          >
            <AlertTriangle size={12} style={{ color: "var(--color-amber)", flexShrink: 0, marginTop: 1.5 }} aria-hidden="true" />
            <p className="text-[12px] leading-snug" style={{ color: "var(--color-amber)" }}>
              {guesses} placement{guesses === 1 ? "" : "s"} sit in a term the bulletin does not
              confirm — each is marked on its own card below.
            </p>
          </div>
        ) : null}
        {plan.assumptions.length > 0 ? (
          <>
            <button
              type="button"
              onClick={() => setShowAssumptions((o) => !o)}
              className="flex w-full items-center gap-2 rounded-xl px-4 py-2.5 text-left"
              style={{ background: "var(--color-sky-muted)", border: "1px solid rgba(96,165,250,0.2)" }}
            >
              <Info size={12} style={{ color: "var(--color-sky)" }} aria-hidden="true" />
              <span className="flex-1 text-[12px]" style={{ color: "var(--color-sky)" }}>
                What this sequence rests on — {plan.assumptions.length} assumption
                {plan.assumptions.length === 1 ? "" : "s"}, none verifiable here
              </span>
              <ChevronDown
                size={12}
                aria-hidden="true"
                style={{
                  color: "var(--color-sky)",
                  transform: showAssumptions ? "rotate(180deg)" : "none",
                  transition: "transform 220ms ease",
                }}
              />
            </button>
            {showAssumptions ? (
              <div
                className="pp-slide-up rounded-xl px-4 py-3"
                style={{ background: "var(--color-sky-muted)", border: "1px solid rgba(96,165,250,0.2)" }}
              >
                <ul className="findings">
                  {plan.assumptions.map((a) => (
                    <Finding
                      key={a.subject}
                      verdict="unverifiable"
                      label="Assumed"
                      summary={a.subject}
                      detail={a.statement}
                      nextStep={a.check}
                    />
                  ))}
                </ul>
                {plan.unplaceable.length > 0 ? (
                  <div className="mt-2">
                    <WarnNote>
                      Left out entirely — not in the catalog Path Pilot has loaded:{" "}
                      {plan.unplaceable.join(", ")}.
                    </WarnNote>
                  </div>
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}
      </div>

      {/* Term columns, or the binding constraint where the grid would have been. */}
      {plan.feasible ? (
        <div className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden px-6 pt-3 pb-6">
          <div className="flex h-full min-h-0 gap-4">
            {plan.terms.map((term, ti) => {
              const sc = semesterOf(term.term)
              const cap = plan.max_credits_per_term
              return (
                <div
                  key={term.term}
                  className="pp-slide-up flex min-h-0 min-w-[240px] flex-1 flex-col"
                  style={{ animationDelay: `${ti * 70 + 160}ms` }}
                >
                  <div
                    className="shrink-0 rounded-t-2xl px-4 py-3"
                    style={{ background: sc.bg, border: `1px solid ${sc.border}`, borderBottom: "none" }}
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-[13px] font-semibold" style={{ color: sc.primary }}>
                        {term.term}
                      </span>
                      <span className="text-[11px] font-semibold" style={{ fontFamily: "var(--font-mono)", color: sc.primary }}>
                        {term.credits} / {cap} cr
                      </span>
                    </div>
                    <div className="h-1 overflow-hidden rounded-full" style={{ background: "rgba(0,0,0,0.12)" }}>
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.min((term.credits / cap) * 100, 100)}%`,
                          background: sc.primary,
                          transition: "width 400ms cubic-bezier(0.22,1,0.36,1)",
                        }}
                      />
                    </div>
                  </div>
                  <div
                    className="nx-scroll min-h-0 flex-1 space-y-1.5 overflow-y-auto rounded-b-2xl p-2.5"
                    style={{ background: "var(--color-surface)", border: `1px solid ${sc.border}` }}
                  >
                    {term.courses.map((course, ci) => {
                      const meta = BASIS_META[course.offering_basis] ?? BASIS_META.unstated
                      const MetaIcon = meta.icon
                      const shaky = course.offering_basis !== "published"
                      return (
                        <div
                          key={course.course_code}
                          className="overflow-hidden rounded-xl"
                          style={{
                            border: `1px solid ${shaky ? "rgba(180,83,9,0.25)" : "var(--color-rail)"}`,
                            background: shaky ? "var(--color-amber-muted)" : "var(--color-surface-2)",
                            animation: `pp-slide-up 200ms cubic-bezier(0.22,1,0.36,1) ${ci * 60}ms both`,
                          }}
                        >
                          <div className="flex items-start gap-2.5 px-3 py-2.5">
                            <MetaIcon size={13} style={{ color: meta.color, flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
                            <div className="min-w-0 flex-1">
                              <span className="text-[11px] font-medium" style={{ fontFamily: "var(--font-mono)", color: "var(--color-violet-light)" }}>
                                {course.course_code}
                              </span>
                              <div className="mt-0.5 text-[12px] leading-snug font-medium" style={{ color: "var(--color-ink)" }}>
                                {course.title}
                              </div>
                              <div className="mt-0.5 text-[10px]" style={{ color: "var(--color-ink-3)" }}>
                                {course.requirement ? `${course.requirement} · ` : ""}
                                {meta.label}
                              </div>
                            </div>
                            <span
                              className="shrink-0 rounded px-1.5 py-0.5 text-[11px]"
                              style={{ fontFamily: "var(--font-mono)", background: "var(--color-surface-3)", color: "var(--color-ink-3)" }}
                            >
                              {course.credits} cr
                            </span>
                          </div>
                          {shaky ? (
                            <div className="px-3 py-2" style={{ borderTop: "1px solid rgba(180,83,9,0.15)", background: "rgba(180,83,9,0.06)" }}>
                              <p className="text-[11px] leading-snug" style={{ color: "var(--color-amber)" }}>
                                {course.offering_note}
                                {course.offering_source ? ` (“${course.offering_source}”)` : ""}
                              </p>
                            </div>
                          ) : null}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        <div className="nx-scroll min-h-0 flex-1 overflow-y-auto px-6 pt-3 pb-6">
          <div
            className="pp-slide-up rounded-2xl p-4"
            style={{ background: "var(--color-surface)", border: "1px solid rgba(124,58,237,0.3)" }}
          >
            <div className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
              No order fits — what is standing in the way
            </div>
            <p className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-2)" }}>
              {plan.infeasibility?.explanation}
            </p>
            {plan.infeasibility?.binding_labels?.length ? (
              <div className="mt-3 space-y-2">
                <div className="text-[10px] font-medium tracking-wide uppercase" style={{ color: "var(--color-ink-3)" }}>
                  Any one of these would unblock it
                </div>
                <ul className="findings">
                  {plan.infeasibility.binding_labels.map((label, i) => (
                    <Finding
                      key={label}
                      verdict="conditional"
                      label="Binding"
                      summary={label}
                      detail={plan.infeasibility.remedies[i] ?? null}
                    />
                  ))}
                </ul>
                <Muted>
                  Each of these was established by removing it and re-solving — not inferred.
                </Muted>
              </div>
            ) : null}
            {onOpenPlanner ? (
              <div className="mt-3">
                <Button variant="outline" onClick={onOpenPlanner}>
                  Check my record →
                </Button>
              </div>
            ) : null}
          </div>

          {plan.rejected_tracks.length > 0 ? (
            <div
              className="pp-slide-up mt-4 rounded-2xl p-4"
              style={{ background: "var(--color-surface)", border: "1px solid var(--color-rail-strong)" }}
            >
              <div className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
                Concentrations that do not fit
              </div>
              <ul className="findings mt-2">
                {plan.rejected_tracks.map((track) => (
                  <Finding key={track.track} verdict="conditional" label="Does not fit" summary={track.track} detail={track.why} />
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}

      {/* Rejected tracks under a feasible grid ride below the columns. */}
      {plan.feasible && plan.rejected_tracks.length > 0 ? (
        <div className="shrink-0 px-6 pb-4">
          <details className="text-[12px]" style={{ color: "var(--color-ink-3)" }}>
            <summary className="cursor-pointer">
              {plan.rejected_tracks.length} other concentration
              {plan.rejected_tracks.length === 1 ? "" : "s"} could not be sequenced
            </summary>
            <ul className="findings mt-2">
              {plan.rejected_tracks.map((track) => (
                <Finding key={track.track} verdict="conditional" label="Does not fit" summary={track.track} detail={track.why} />
              ))}
            </ul>
          </details>
        </div>
      ) : null}

      <p className="shrink-0 px-6 pb-4 text-[10px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
        {plan.disclaimer}
        {plan.chosen_track ? ` Concentration: ${plan.chosen_track}.` : ""}
      </p>
    </div>
  )
}
