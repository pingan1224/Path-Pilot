import { useCallback, useEffect, useRef, useState } from "react"
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle,
  ChevronDown,
  Circle,
  GraduationCap,
  Info,
  RotateCcw,
  Sparkles,
} from "lucide-react"
import { api } from "@/api"
import { Finding } from "@/components/Finding"
import { Banner, Chip, Code, Muted } from "@/components/make"
import { ErrorNote, INPUT_CLASS, ProgramNotice, WarnNote, isProgramIssue } from "@/components/nocturne"
import { Button } from "@/components/ui/button"
import { usePrefs } from "@/i18n"

/**
 * The course planner — a what-if console, not a document.
 *
 * The screen it replaced showed one static column and a text field, and a student could
 * do nothing with either: a plan with one term left has nothing to drag, and typing a
 * term into a box produced no visible answer when the constraint did not bind. The
 * source design solves this with drag-and-drop between terms, which reads as editing a
 * schedule — and editing is the one thing this surface must not offer, because moving a
 * course is a claim about prerequisites, offerings and credit load that only the solver
 * can settle.
 *
 * So the gesture is kept and its meaning is corrected: **every control here poses a
 * question, and the answer is the finish date moving.**
 *
 *   Load      — the per-term credit cap is the student's own number, assumed rather than
 *               published (see CLAUDE.md), which makes it the most valuable input on the
 *               page. 3/6/9/12 re-solves instantly.
 *   Defer     — "what if this waits?" runs the solver's own counterfactual: the course is
 *               held out of the starting term and the whole thing is re-planned,
 *               concentration choice included. Dragging a card to the Later zone asks
 *               exactly this. The drop zone is labelled "later", never a named term,
 *               because where the course lands is the solver's answer, not the drag's.
 *   Deadline  — a date to finish by, answered as fits / does not fit with what binds.
 *
 * Nothing here is saved. `GET /sequence` computes and stores nothing, so a what-if is a
 * question asked, and the header says which answer is on screen.
 *
 * Delay costs were already computed for every course in the starting term and were only
 * ever shown in the chat. They belong here: they turn a list of courses into a priced
 * list, which is the difference between a schedule and a decision.
 */

const CREDIT_CHOICES = [3, 6, 9, 12]

const SEM_STYLE = {
  Spring: { primary: "var(--color-emerald)", bg: "var(--color-emerald-muted)", border: "rgba(4,120,87,0.2)" },
  Fall: { primary: "var(--color-violet-light)", bg: "var(--color-violet-muted)", border: "rgba(124,58,237,0.25)" },
  Summer: { primary: "var(--color-amber)", bg: "var(--color-amber-muted)", border: "rgba(180,83,9,0.2)" },
}
const semesterOf = (term) => SEM_STYLE[String(term).split(" ")[0]] ?? SEM_STYLE.Fall

const BASIS_META = {
  published: { icon: CheckCircle, toneName: "good", label: "Published" },
  irregular: { icon: AlertTriangle, toneName: "warn", label: "Runs irregularly" },
  unstated: { icon: Circle, toneName: "neutral", label: "Term is a guess" },
}

/** A placeholder requirement (an elective with no course chosen) cannot be deferred —
 *  there is no course to hold out. The solver names these in prose, not as a code. */
const isPlaceholder = (code) => /\(|\)/.test(code)

export default function SequenceView({ onOpenPlanner, onOpenProgram }) {
  const { t } = usePrefs()
  const [startTerm, setStartTerm] = useState("")
  const [deadline, setDeadline] = useState("")
  const [maxCredits, setMaxCredits] = useState("")
  // The server's own term vocabulary, so a picker cannot offer a value the solver would
  // reject; `prefs` is what the student has saved, shown beside the controls with the
  // date they said it — intent goes stale like any other source.
  const [terms, setTerms] = useState([])
  const [prefs, setPrefs] = useState(null)
  const [deferred, setDeferred] = useState(null)
  // Which concentration the student asked to look at, or null for the solver's own pick.
  const [track, setTrack] = useState(null)
  // Every concentration that fits, remembered from the last unnarrowed solve. Asking for
  // one narrows the search, so that response reports no alternatives — rendering the
  // chips from it would make the row vanish the moment a student used it, with no way
  // back. Same shape as `baseline` above: the comparison outlives the question.
  const [trackOptions, setTrackOptions] = useState(null)
  const [plan, setPlan] = useState(null)
  // `{ key, plan }` — the un-deferred answer plus the constraints it was solved under.
  // The ref mirrors it so `load` can read the current value without taking it as a
  // dependency and re-creating itself after every solve.
  const [baseline, setBaseline] = useState(null)
  const baselineRef = useRef(null)
  const rememberBaseline = (b) => {
    baselineRef.current = b
    setBaseline(b)
  }
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [showAssumptions, setShowAssumptions] = useState(false)
  const [dragging, setDragging] = useState(null)
  const [dragOver, setDragOver] = useState(false)

  /** One solve. `baseline` holds the un-deferred answer so the header can price the
   *  what-if against it — the student needs the comparison, not just the new date.
   *
   *  The baseline is tagged with the constraints it was solved under, and re-solved when
   *  they change. Keeping whatever the last un-deferred solve returned looked cheaper and
   *  priced the wrong thing: the credit-cap buttons and the deadline field carry an active
   *  deferral forward, so after "defer this, now try 12 credits" the banner was comparing
   *  a 12-credit deferred plan against a 9-credit un-deferred one and attributing the
   *  whole difference to the deferred course. When the larger cap pulled the finish date
   *  back it could read "this one can wait for free", which is the opposite of the truth,
   *  on the single question the screen exists to answer. The extra solve only happens when
   *  a constraint moves while a deferral is up. */
  const load = useCallback(async (overrides = {}) => {
    const next = {
      startTerm: overrides.startTerm ?? startTerm,
      deadline: overrides.deadline ?? deadline,
      maxCredits: overrides.maxCredits ?? maxCredits,
      defer: "defer" in overrides ? overrides.defer : deferred,
      track: "track" in overrides ? overrides.track : track,
    }
    const key = `${next.startTerm}|${next.deadline}|${next.maxCredits}`
    setBusy(true)
    setError(null)
    try {
      const result = await api.sequence(next)
      setPlan(result)
      if (!next.track && result.chosen_track) {
        setTrackOptions({
          chosen: result.chosen_track,
          chosenFinish: result.finish_term,
          alternatives: result.alternatives ?? [],
        })
      }
      if (!next.defer) {
        rememberBaseline({ key, plan: result })
      } else if (baselineRef.current?.key !== key) {
        // Constraints moved under an active deferral, so the stored comparison is no
        // longer like-for-like. Re-solve it rather than quoting a stale price.
        rememberBaseline({ key, plan: await api.sequence({ ...next, defer: null }) })
      }
      return result
    } catch (err) {
      setError(err)
      return null
    } finally {
      setBusy(false)
    }
  }, [startTerm, deadline, maxCredits, deferred, track])

  useEffect(() => {
    // Preferences first: the picker's options come from the server, and a saved target
    // has to be selectable or looking at the page would appear to clear it.
    api
      .preferences()
      .then((p) => {
        setPrefs(p)
        setTerms(p.selectable_terms ?? [])
      })
      .catch(() => setTerms([]))
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function ask(overrides) {
    if ("defer" in overrides) setDeferred(overrides.defer)
    if ("maxCredits" in overrides) setMaxCredits(overrides.maxCredits)
    if ("startTerm" in overrides) setStartTerm(overrides.startTerm)
    if ("track" in overrides) setTrack(overrides.track)
    if ("deadline" in overrides) setDeadline(overrides.deadline)
    await load(overrides)
  }

  /** Save one control's current value as the student's default.
   *
   * One field per call: the server reads an absent key as "unchanged", so saving a
   * credit cap cannot forget a finish term. Asking a what-if never writes — this is the
   * only path from this screen into preferences, and it is a button they press.
   */
  async function saveDefault(patch) {
    setBusy(true)
    try {
      setPrefs(await api.preferencesPut(patch))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

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

  const costByCode = Object.fromEntries((plan.delay_costs ?? []).map((c) => [c.code, c]))
  const guesses = plan.feasible
    ? plan.terms.flatMap((tm) => tm.courses).filter((c) => c.offering_basis !== "published").length
    : 0
  const cap = plan.max_credits_per_term
  // The what-if's price, against the answer without it.
  const movedBy =
    plan.deferred &&
    baseline?.plan?.finish_term &&
    plan.finish_term !== baseline.plan.finish_term
      ? { from: baseline.plan.finish_term, to: plan.finish_term }
      : null

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* The answer, as the headline. Every control below moves this line. */}
      <div
        className="pp-slide-down shrink-0 px-6 py-4"
        style={{ borderBottom: "1px solid var(--color-rail)", background: "var(--color-surface)" }}
      >
        <div className="flex flex-wrap items-start gap-4">
          <CalendarClock
            size={22}
            style={{ color: "var(--color-violet-light)", flexShrink: 0, marginTop: 2 }}
            aria-hidden="true"
          />
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-medium tracking-wide uppercase" style={{ color: "var(--color-ink-3)" }}>
              {t("nav.sequence")}
            </div>
            {plan.feasible ? (
              <h1
                key={plan.finish_term}
                className="pp-badge-pop text-[22px] leading-tight font-semibold"
                style={{ fontFamily: "var(--font-display)", color: "var(--color-ink)" }}
              >
                Finishing {plan.finish_term}
                <span className="ml-2 text-[13px] font-normal" style={{ color: "var(--color-ink-3)" }}>
                  · {plan.terms_needed} term{plan.terms_needed === 1 ? "" : "s"} left
                </span>
              </h1>
            ) : (
              <h1
                className="text-[22px] leading-tight font-semibold"
                style={{ fontFamily: "var(--font-display)", color: "var(--color-amber)" }}
              >
                No order fits your constraints
              </h1>
            )}
          </div>
          {busy ? (
            <Sparkles
              size={14}
              aria-hidden="true"
              style={{ color: "var(--color-violet-light)", animation: "pp-spinner 1s linear infinite" }}
            />
          ) : null}
        </div>

        {/* Load — the student's own number, and the fastest way to move the answer. */}
        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div>
            <div className="mb-1 text-[10px] font-medium tracking-wide uppercase" style={{ color: "var(--color-ink-3)" }}>
              {/* Three sources, three labels. "Assumed" is the product's own guess and
                  says so; "saved" is the student's decision and must not wear the guess's
                  hedge; a value named in this request needs neither. */}
              Credits per term
              {plan.credit_cap_source === "assumed" ? " · assumed, not a rule" : ""}
              {plan.credit_cap_source === "saved" ? " · saved" : ""}
            </div>
            <div
              className="flex items-center gap-0.5 rounded-lg p-0.5"
              style={{ background: "var(--color-surface-2)", border: "1px solid var(--color-rail-strong)" }}
              role="group"
              aria-label="Credits per term"
            >
              {CREDIT_CHOICES.map((n) => {
                const active = cap === n
                return (
                  <button
                    key={n}
                    type="button"
                    aria-pressed={active}
                    disabled={busy}
                    onClick={() => ask({ maxCredits: String(n) })}
                    className="rounded-md px-3 py-1 text-[12px] font-semibold"
                    style={{
                      background: active ? "var(--color-surface-3)" : "transparent",
                      color: active ? "var(--color-ink)" : "var(--color-ink-3)",
                      transition: "background 220ms ease, color 220ms ease",
                    }}
                  >
                    {n}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Start and finish are pickers over the server's own term list, not free text.
              Neither is visible the moment it is typed the way a mission's term is — they
              feed the solver and, once saved, only bite at the next solve — so a spelling
              the parser cannot read would fail quietly and days later. The list comes from
              the server so the picker cannot offer a value the solver would reject. */}
          <label className="flex flex-col gap-1 text-[10px] font-medium tracking-wide uppercase" style={{ color: "var(--color-ink-3)" }}>
            Starting term{plan.start_was_assumed ? " · assumed" : ""}
            <select
              className={INPUT_CLASS}
              value={startTerm}
              disabled={busy}
              onChange={(e) => ask({ startTerm: e.target.value })}
            >
              {/* "The next term you could register for" is the assumption when nothing is
                  chosen; naming it is what lets a student sitting out a term say so. */}
              <option value="">Next available ({plan.start_term})</option>
              {terms.map((term) => (
                <option key={term} value={term}>
                  {term}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-[10px] font-medium tracking-wide uppercase" style={{ color: "var(--color-ink-3)" }}>
            Finish by{plan.deadline_source === "saved" ? " · saved" : ""}
            <select
              className={INPUT_CLASS}
              value={deadline}
              disabled={busy}
              onChange={(e) => ask({ deadline: e.target.value })}
            >
              <option value="">
                {plan.deadline_source === "saved" ? `Saved: ${plan.deadline}` : "No deadline"}
              </option>
              {terms.map((term) => (
                <option key={term} value={term}>
                  {term}
                </option>
              ))}
            </select>
          </label>

          {/* The one write on this screen, and it is a button. Everything else here poses
              a question; saving turns this answer's constraints into the ones the next
              solve — and the assistant — will start from, which is a decision, not a
              side effect of exploring. */}
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-medium tracking-wide uppercase" style={{ color: "var(--color-ink-3)" }}>
              Defaults
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() =>
                  saveDefault({
                    max_credits_per_term: cap,
                    target_finish_term: deadline || plan.deadline || null,
                  })
                }
              >
                Save these as mine
              </Button>
              {prefs?.updated_at ? (
                <span className="text-[10px]" style={{ color: "var(--color-ink-3)" }}>
                  saved {new Date(prefs.updated_at).toLocaleDateString()}
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* Concentrations. A one_track requirement is a choice, not a constraint: the
          solver picks the soonest, but "soonest" is this product's tiebreak, not
          necessarily the student's reason. Each chip says what that choice costs in the
          unit they think in — terms — and, once they have stated a target, whether it
          still fits at all. Selecting one is a question, not a declaration: nothing is
          written, and the concentration is declared to the university, not here. */}
      {trackOptions && trackOptions.alternatives.length > 0 ? (
        <div className="shrink-0 px-6 pt-4">
          <div
            className="mb-1.5 text-[10px] font-medium tracking-wide uppercase"
            style={{ color: "var(--color-ink-3)" }}
          >
            Concentration · yours to choose
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {[
              { track: trackOptions.chosen, chosen: true },
              ...trackOptions.alternatives,
            ].map((option) => {
              const active = plan.track_requested
                ? plan.track_requested === option.track
                : option.chosen
              return (
                <button
                  key={option.track}
                  type="button"
                  aria-pressed={active}
                  disabled={busy}
                  onClick={() => ask({ track: option.chosen ? null : option.track })}
                  className="rounded-xl px-3 py-2 text-left"
                  style={{
                    background: active ? "var(--color-violet-muted)" : "var(--color-surface-2)",
                    border: `1px solid ${active ? "rgba(124,58,237,0.35)" : "var(--color-rail-strong)"}`,
                    transition: "background 200ms ease, border-color 200ms ease",
                  }}
                >
                  <div
                    className="text-[12px] font-medium"
                    style={{ color: active ? "var(--color-violet-light)" : "var(--color-ink)" }}
                  >
                    {option.track}
                  </div>
                  <div className="mt-0.5 text-[10px]" style={{ color: "var(--color-ink-3)" }}>
                    {option.chosen ? (
                      `Finishes ${trackOptions.chosenFinish ?? plan.finish_term ?? "—"} · soonest`
                    ) : (
                      <>
                        {`Finishes ${option.finish_term}`}
                        {option.terms_later > 0
                          ? ` · ${option.terms_later} term${option.terms_later === 1 ? "" : "s"} later`
                          : " · no later"}
                        {/* Only sayable once they have said when they want to finish. */}
                        {option.meets_deadline === false ? " · misses your target" : ""}
                        {option.meets_deadline === true ? " · still meets your target" : ""}
                      </>
                    )}
                  </div>
                </button>
              )
            })}
          </div>
          {plan.track_requested ? (
            <div className="mt-1.5 text-[10px]" style={{ color: "var(--color-ink-3)" }}>
              Showing {plan.track_requested} because you asked. The solver would pick{" "}
              {trackOptions.chosen}, which finishes soonest — but soonest is a tiebreak,
              not a recommendation about what to study. Nothing here is saved.
            </div>
          ) : null}
        </div>
      ) : null}

      {/* What-if banner: what was asked, what it costs, and the way back. */}
      <div className="shrink-0 space-y-2 px-6 pt-4">
        {error ? <ErrorNote>{error.message}</ErrorNote> : null}

        {plan.deferred ? (
          <div
            className="pp-slide-up flex flex-wrap items-center gap-3 rounded-xl px-4 py-3"
            style={{ background: "var(--color-violet-muted)", border: "1px solid rgba(124,58,237,0.25)" }}
          >
            <Sparkles size={13} style={{ color: "var(--color-violet-light)" }} aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <div className="text-[12px] font-semibold" style={{ color: "var(--color-violet-light)" }}>
                What if <Code>{plan.deferred}</Code> waits?
              </div>
              <div className="mt-0.5 text-[11px]" style={{ color: "var(--color-ink-2)" }}>
                {movedBy
                  ? `You would finish ${movedBy.to} instead of ${movedBy.from}.`
                  : "The finish date does not move — this one can wait for free."}{" "}
                Nothing is saved; this is a question, not a change to your plan.
              </div>
            </div>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => ask({ defer: null })}>
              <RotateCcw size={12} aria-hidden="true" />
              Reset
            </Button>
          </div>
        ) : null}

        {plan.feasible && plan.deadline ? (
          <Banner toneName="good" icon={GraduationCap}>
            Finishing {plan.finish_term} — inside your {plan.deadline} deadline.
          </Banner>
        ) : null}

        {guesses > 0 ? (
          <Banner toneName="warn">
            {guesses} placement{guesses === 1 ? "" : "s"} sit in a term the bulletin does not
            confirm — each is marked on its own card.
          </Banner>
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
                What this rests on — {plan.assumptions.length} assumption
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

      {/* The board. */}
      {plan.feasible ? (
        <div className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden px-6 pt-3 pb-6">
          <div className="flex h-full min-h-0 gap-4">
            {plan.terms.map((term, ti) => {
              const sc = semesterOf(term.term)
              const isNext = ti === 0
              return (
                <div
                  key={term.term}
                  className="pp-slide-up flex min-h-0 w-[280px] flex-none flex-col"
                  style={{ animationDelay: `${ti * 70 + 160}ms` }}
                >
                  <div
                    className="shrink-0 rounded-t-2xl px-4 py-3"
                    style={{ background: sc.bg, border: `1px solid ${sc.border}`, borderBottom: "none" }}
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-[13px] font-semibold" style={{ color: sc.primary }}>
                        {term.term}
                        {isNext ? (
                          <span className="ml-1.5 text-[10px] font-normal" style={{ color: "var(--color-ink-3)" }}>
                            next term
                          </span>
                        ) : null}
                      </span>
                      <span
                        className="text-[11px] font-semibold"
                        style={{ fontFamily: "var(--font-mono)", color: sc.primary }}
                      >
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
                    {term.courses.map((course, ci) => (
                      <CourseCard
                        key={course.course_code}
                        course={course}
                        cost={isNext ? costByCode[course.course_code] : undefined}
                        deferrable={isNext && !isPlaceholder(course.course_code) && !plan.deferred}
                        busy={busy}
                        index={ci}
                        onDefer={() => ask({ defer: course.course_code })}
                        onDragStart={() => setDragging(course.course_code)}
                        onDragEnd={() => {
                          setDragging(null)
                          setDragOver(false)
                        }}
                      />
                    ))}
                  </div>
                </div>
              )
            })}

            {/* The drop zone. Labelled "later", never a named term: where a deferred
                course lands is the solver's answer, and promising a term the drag cannot
                deliver would be the schedule lying about itself. */}
            {dragging ? (
              <div
                className="flex min-h-0 w-[280px] flex-none flex-col justify-center"
                onDragOver={(e) => {
                  e.preventDefault()
                  setDragOver(true)
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  const code = dragging
                  setDragging(null)
                  setDragOver(false)
                  if (code) ask({ defer: code })
                }}
              >
                <div
                  className="pp-fade-in flex h-40 flex-col items-center justify-center gap-2 rounded-2xl px-4 text-center"
                  style={{
                    border: `2px dashed ${dragOver ? "var(--color-violet)" : "var(--color-rail-strong)"}`,
                    background: dragOver ? "var(--color-violet-muted)" : "transparent",
                    transition: "background 160ms ease, border-color 160ms ease",
                  }}
                >
                  <ArrowRight size={16} style={{ color: "var(--color-violet-light)" }} aria-hidden="true" />
                  <span className="text-[12px] font-medium" style={{ color: "var(--color-violet-light)" }}>
                    Drop to ask “what if this waits?”
                  </span>
                  <span className="text-[10px]" style={{ color: "var(--color-ink-3)" }}>
                    The solver decides which term it lands in
                  </span>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="nx-scroll min-h-0 flex-1 overflow-y-auto px-6 pt-3 pb-6">
          <div
            className="pp-slide-up rounded-2xl p-4"
            style={{ background: "var(--color-surface)", border: "1px solid rgba(180,83,9,0.25)" }}
          >
            <p className="text-[12px] leading-relaxed" style={{ color: "var(--color-ink-2)" }}>
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
                <Muted>Each was established by removing it and re-solving — not inferred.</Muted>
              </div>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-2">
              {plan.deferred ? (
                <Button size="sm" variant="outline" disabled={busy} onClick={() => ask({ defer: null })}>
                  <RotateCcw size={12} aria-hidden="true" />
                  Undo the what-if
                </Button>
              ) : null}
              {onOpenPlanner ? (
                <Button size="sm" variant="outline" onClick={onOpenPlanner}>
                  Check my record →
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      )}

      {/* The concentrations that were tried and did not fit. A one_track requirement is a
          choice, not a constraint: the solver sequences each track separately, and naming
          only the winner hands the student a decision already made for them. "Risk
          Analytics fits your deadline and Business Analytics does not" is the sentence
          they need, and it is the one the API has been sending all along. */}
      {plan.rejected_tracks?.length ? (
        <div className="shrink-0 px-6 pb-3">
          <div
            className="pp-slide-up rounded-xl px-4 py-3"
            style={{ background: "var(--color-surface)", border: "1px solid var(--color-rail-strong)" }}
          >
            <div
              className="text-[10px] font-medium tracking-wide uppercase"
              style={{ color: "var(--color-ink-3)" }}
            >
              Concentrations that do not fit
            </div>
            <ul className="mt-2 space-y-1.5">
              {plan.rejected_tracks.map((r) => (
                <li
                  key={r.track}
                  className="text-[12px] leading-relaxed"
                  style={{ color: "var(--color-ink-2)" }}
                >
                  <span className="font-medium">{r.track}</span>
                  {r.why ? <span style={{ color: "var(--color-ink-3)" }}> — {r.why}</span> : null}
                </li>
              ))}
            </ul>
            <div className="mt-2">
              <Muted>
                You are free to change concentration, so each one was sequenced on its own.
                Which to take is your decision.
              </Muted>
            </div>
          </div>
        </div>
      ) : null}

      <p className="shrink-0 px-6 pb-4 text-[10px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
        {plan.disclaimer}
        {plan.chosen_track ? ` Concentration: ${plan.chosen_track}.` : ""}
      </p>
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

/**
 * One placement, priced. The delay cost is the reason this course is where it is, so it
 * renders on the card rather than under the board — a caveat averaged across a plan
 * tells the student nothing about which course to go and check.
 */
function CourseCard({ course, cost, deferrable, busy, index, onDefer, onDragStart, onDragEnd }) {
  const meta = BASIS_META[course.offering_basis] ?? BASIS_META.unstated
  const MetaIcon = meta.icon
  const shaky = course.offering_basis !== "published"

  return (
    <div
      draggable={deferrable}
      onDragStart={deferrable ? onDragStart : undefined}
      onDragEnd={deferrable ? onDragEnd : undefined}
      className="overflow-hidden rounded-xl"
      style={{
        border: `1px solid ${shaky ? "rgba(180,83,9,0.25)" : "var(--color-rail)"}`,
        background: shaky ? "var(--color-amber-muted)" : "var(--color-surface-2)",
        cursor: deferrable ? "grab" : "default",
        animation: `pp-slide-up 200ms cubic-bezier(0.22,1,0.36,1) ${index * 60}ms both`,
      }}
    >
      <div className="flex items-start gap-2.5 px-3 py-2.5">
        <MetaIcon
          size={13}
          style={{ color: meta.toneName === "good" ? "var(--color-emerald)" : meta.toneName === "warn" ? "var(--color-amber)" : "var(--color-ink-3)", flexShrink: 0, marginTop: 2 }}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <Code>{course.course_code}</Code>
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

      {/* The price of waiting — the answer to "why this one, why now". */}
      {cost ? (
        <div
          className="flex flex-wrap items-center gap-2 px-3 py-2"
          style={{
            borderTop: "1px solid var(--color-rail)",
            background: cost.breaks_plan ? "var(--color-rose-muted)" : "transparent",
          }}
        >
          {cost.breaks_plan ? (
            <Chip toneName="danger">Cannot wait</Chip>
          ) : cost.terms_lost > 0 ? (
            <Chip toneName="warn">
              +{cost.terms_lost} term{cost.terms_lost === 1 ? "" : "s"} if it waits
            </Chip>
          ) : (
            <Chip toneName="good">Can wait for free</Chip>
          )}
          {deferrable ? (
            <button
              type="button"
              disabled={busy}
              onClick={onDefer}
              className="ml-auto text-[11px] font-medium"
              style={{ color: "var(--color-violet-light)" }}
            >
              What if it waits? →
            </button>
          ) : null}
        </div>
      ) : null}

      {shaky ? (
        <div
          className="px-3 py-2"
          style={{ borderTop: "1px solid rgba(180,83,9,0.15)", background: "rgba(180,83,9,0.06)" }}
        >
          <p className="text-[11px] leading-snug" style={{ color: "var(--color-amber)" }}>
            {course.offering_note}
            {course.offering_source ? ` (“${course.offering_source}”)` : ""}
          </p>
        </div>
      ) : null}
    </div>
  )
}
