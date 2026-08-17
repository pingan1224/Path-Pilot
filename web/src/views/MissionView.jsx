import { useCallback, useEffect, useState } from "react"
import {
  AlertTriangle,
  CheckCircle,
  Circle,
  Clock,
  Copy,
  Sparkles,
  User,
} from "lucide-react"
import { api } from "@/api"
import { Finding } from "@/components/Finding"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  ErrorNote,
  INPUT_CLASS,
  Muted,
  ProgramNotice,
  WarnNote,
  isProgramIssue,
} from "@/components/nocturne"
import { Accordion } from "@/components/make"
import { useCourseSearch } from "@/hooks/useCourseSearch"
import { usePrefs } from "@/i18n"

/**
 * The registration mission in the source design's timeline language (1:1 branch):
 * a display-face header with a term pill and a gradient progress bar, then five step
 * cards on an icon timeline — circled status icons, a connecting line that fills for
 * finished ground, one card expanded at a time, breathe on the active step and an
 * amber pulse where blockers stand.
 *
 * Everything inside the cards is PathPilot's real machinery, unchanged: progress is
 * never computed here (every mutation returns the whole mission recomputed
 * server-side); the assistant's suggestions render marked as suggestions and do not
 * move the counter; accepting a risk is per finding, by key; generating the handoff is
 * what completes the last step. The design's demo steps were hardcoded scenery — these
 * five expand into the actual work.
 */

const STEP_ICON = {
  done: { icon: CheckCircle, color: "var(--color-emerald)", bg: "var(--color-emerald-muted)" },
  active: { icon: Clock, color: "var(--color-violet-light)", bg: "var(--color-violet-muted)" },
  blocked: { icon: AlertTriangle, color: "var(--color-amber)", bg: "var(--color-amber-muted)" },
  pending: { icon: Circle, color: "var(--color-ink-3)", bg: "var(--color-surface-3)" },
}

const TERM_SUGGESTIONS = ["Fall 2026", "Spring 2027", "Summer 2027"]

export default function MissionView({ onOpenPlanner, onOpenProgram }) {
  const { t } = usePrefs()
  const [missions, setMissions] = useState(null)
  const [activeId, setActiveId] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    setError(null)
    api
      .missions()
      .then((list) => {
        setMissions(list)
        setActiveId((current) => current ?? (list.length > 0 ? list[0].id : null))
      })
      .catch((err) => setError(err))
  }, [])

  useEffect(load, [load])

  function replace(mission) {
    setMissions((list) => (list ?? []).map((m) => (m.id === mission.id ? mission : m)))
  }

  async function act(fn) {
    setBusy(true)
    setError(null)
    try {
      replace(await fn())
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  /** Close, then re-read: a closed mission drops out of `open_missions`, so the list this
   *  view holds is stale the moment the request lands. */
  async function closeMission(mission) {
    setBusy(true)
    setError(null)
    try {
      await api.missionClose(mission.id, null)
      const list = await api.missions()
      setMissions(list)
      setActiveId(list.length > 0 ? list[0].id : null)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function start(term) {
    setBusy(true)
    setError(null)
    try {
      const mission = await api.createMission(term)
      setMissions((list) => [mission, ...(list ?? []).filter((m) => m.id !== mission.id)])
      setActiveId(mission.id)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  if (error && !missions) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-6">
        {isProgramIssue(error.code) ? (
          <ProgramNotice code={error.code} message={error.message} onChooseProgram={onOpenProgram} />
        ) : (
          <div className="flex flex-col items-start gap-3">
            <ErrorNote>Could not read your missions: {error.message}</ErrorNote>
            <Button variant="outline" size="sm" onClick={load}>
              Try again
            </Button>
          </div>
        )}
      </div>
    )
  }
  if (!missions) {
    return (
      <p role="status" className="px-6 py-6 text-[13px]" style={{ color: "var(--color-ink-3)" }}>
        Reading your mission…
      </p>
    )
  }

  const mission = missions.find((m) => m.id === activeId) ?? null

  return (
    <div className="nx-scroll h-full overflow-y-auto">
      <div className="mx-auto max-w-2xl px-6 py-6">
      {error ? (
        <div className="mb-4">
          <ErrorNote>{error.message}</ErrorNote>
        </div>
      ) : null}

      {missions.length > 1 ? (
        <div className="mb-4 flex flex-wrap gap-1.5">
          {missions.map((m) => (
            <button
              key={m.id}
              type="button"
              aria-current={m.id === activeId ? "page" : undefined}
              onClick={() => setActiveId(m.id)}
              className="rounded-full px-3 py-1.5 text-[12px] font-medium"
              style={
                m.id === activeId
                  ? { background: "var(--color-violet-muted)", color: "var(--color-violet-light)" }
                  : { background: "var(--color-surface-2)", color: "var(--color-ink-3)" }
              }
            >
              {m.term}
            </button>
          ))}
        </div>
      ) : null}

      {mission ? (
        <Mission
          key={mission.id}
          mission={mission}
          busy={busy}
          act={act}
          onMission={replace}
          onClose={closeMission}
          onOpenPlanner={onOpenPlanner}
          t={t}
        />
      ) : null}

      <StartCard onStart={start} busy={busy} compact={missions.length > 0} />
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

function StartCard({ onStart, busy, compact }) {
  const [term, setTerm] = useState("")
  return (
    <div
      className="pp-slide-up mt-5 rounded-2xl p-4"
      style={{ background: "var(--color-surface)", border: "1px solid var(--color-rail-strong)" }}
    >
      <div className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
        {compact ? "Start a mission for another term" : "Which term are you preparing for?"}
      </div>
      {!compact ? (
        <p className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
          A mission walks you through getting ready to register. You can leave it
          half-finished and come back — nothing is lost.
        </p>
      ) : null}
      <form
        className="mt-3 flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (term.trim()) onStart(term.trim())
        }}
      >
        <input
          className={INPUT_CLASS}
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="e.g. Spring 2027"
          aria-label="Term"
          disabled={busy}
        />
        <Button type="submit" disabled={busy || !term.trim()}>
          Start
        </Button>
        {TERM_SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            disabled={busy}
            onClick={() => onStart(suggestion)}
            className="rounded-full px-3 py-1.5 text-[12px]"
            style={{
              background: "var(--color-surface-2)",
              border: "1px solid var(--color-rail-strong)",
              color: "var(--color-ink-2)",
            }}
          >
            {suggestion}
          </button>
        ))}
      </form>
    </div>
  )
}

function Mission({ mission, busy, act, onMission, onClose, onOpenPlanner, t }) {
  const done = mission.steps.filter((s) => s.state === "done").length
  const activeStep = mission.steps.find((s) => s.state === "active")
  const blockers = mission.open_blockers ?? []

  // One card open at a time, the design's pattern; default follows the active step.
  const [expanded, setExpanded] = useState(null)
  const shown = expanded ?? activeStep?.id ?? null
  const [confirmClose, setConfirmClose] = useState(false)

  return (
    <>
      {/* Header — display face, term pill, gradient progress. */}
      <div className="pp-slide-up mb-6">
        <div className="mb-1 flex items-center gap-2">
          <h1
            className="text-[22px] font-semibold"
            style={{ fontFamily: "var(--font-display)", color: "var(--color-ink)" }}
          >
            {t("nav.mission")}
          </h1>
          {/* Term *and* programme. A mission records the programme it was opened for and
              is evaluated against that one forever, so after a programme change the term
              alone cannot tell a student which set of rules they are looking at. */}
          <span
            className="rounded-full px-2 py-1 text-[11px] font-medium"
            style={{ background: "var(--color-violet-muted)", color: "var(--color-violet-light)" }}
          >
            {mission.term}
          </span>
          {mission.program_name ? (
            <span className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
              {mission.program_name}
            </span>
          ) : null}
          {mission.complete ? (
            <span
              className="pp-badge-pop rounded-full px-2 py-1 text-[11px] font-medium"
              style={{ background: "var(--color-emerald-muted)", color: "var(--color-emerald)" }}
            >
              Complete
            </span>
          ) : null}
        </div>
        <p className="text-[13px]" style={{ color: "var(--color-ink-3)" }}>
          {mission.complete
            ? "Every step is done. Take the handoff to your advisor, then register in Albert."
            : (activeStep?.what_now ?? "")}
        </p>
        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between">
            <span
              className="text-[11px] font-medium tracking-wide uppercase"
              style={{ color: "var(--color-ink-3)" }}
            >
              Progress
            </span>
            <span className="text-[11px] font-semibold" style={{ color: "var(--color-ink-2)" }}>
              Step {done} of {mission.steps.length} complete
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "var(--color-surface-3)" }}>
            <div
              className="h-full rounded-full"
              style={{
                width: `${(done / mission.steps.length) * 100}%`,
                background: "linear-gradient(90deg, var(--color-violet), var(--color-violet-light))",
                transition: "width 700ms cubic-bezier(0.22,1,0.36,1)",
              }}
            />
          </div>
        </div>
      </div>

      {/* The disclaimer rides the design's amber banner slot — a real claim. */}
      <div
        className="pp-slide-up mb-5 rounded-xl px-4 py-3"
        style={{
          background: "var(--color-amber-muted)",
          border: "1px solid var(--color-amber-edge)",
          animationDelay: "80ms",
        }}
      >
        <p className="text-[11px] leading-relaxed" style={{ color: "var(--color-amber)" }}>
          {mission.disclaimer}
        </p>
      </div>

      {/* Steps with connecting line */}
      <div>
        {mission.steps.map((step, i) => {
          const isLast = i === mission.steps.length - 1
          const isOpen = shown === step.id
          const blocked =
            step.state === "active" && step.id === "open_items" && blockers.length > 0
          const status =
            step.state === "done"
              ? "done"
              : blocked
                ? "blocked"
                : step.state === "active"
                  ? "active"
                  : "pending"
          const cfg = STEP_ICON[status]
          const Icon = cfg.icon
          const nextDone = !isLast && mission.steps[i + 1].state === "done"

          return (
            <div
              key={step.id}
              className="pp-slide-up flex gap-4"
              style={{ animationDelay: `${i * 60 + 120}ms` }}
            >
              {/* Left column: icon + connector */}
              <div className="flex flex-col items-center" style={{ width: 28, flexShrink: 0 }}>
                <div
                  className={`z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                    status === "active" ? "pp-breathe" : ""
                  } ${status === "blocked" ? "pp-amber-pulse" : ""}`}
                  style={{ background: cfg.bg, border: `1.5px solid ${cfg.color}`, marginTop: 14 }}
                >
                  <Icon size={13} style={{ color: cfg.color }} aria-hidden="true" />
                </div>
                {!isLast ? (
                  <div
                    className="relative w-0.5 flex-1 overflow-hidden"
                    style={{ background: "var(--color-surface-3)", minHeight: 16, marginTop: 4 }}
                  >
                    {step.state === "done" ? (
                      <div
                        className="absolute inset-0"
                        style={{
                          background: nextDone
                            ? "var(--color-emerald)"
                            : "linear-gradient(to bottom, var(--color-emerald) 60%, var(--color-surface-3))",
                          transformOrigin: "top",
                          animation: "pp-line-fill 500ms cubic-bezier(0.22,1,0.36,1) both",
                          animationDelay: `${i * 80 + 400}ms`,
                        }}
                      />
                    ) : null}
                  </div>
                ) : null}
              </div>

              {/* Right: step card */}
              <div className="mb-2 min-w-0 flex-1">
                <Accordion
                  open={isOpen}
                  onToggle={() => setExpanded(isOpen ? "" : step.id)}
                  toneName={
                    status === "done"
                      ? "good"
                      : status === "blocked"
                        ? "warn"
                        : status === "active"
                          ? "accent"
                          : undefined
                  }
                  header={
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className="text-[11px] font-semibold"
                          style={{ fontFamily: "var(--font-mono)", color: "var(--color-ink-3)" }}
                        >
                          {String(i + 1).padStart(2, "0")}
                        </span>
                        <span className="text-[13px] font-medium" style={{ color: "var(--color-ink)" }}>
                          {step.title}
                        </span>
                        <span
                          className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                          style={{ background: cfg.bg, color: cfg.color }}
                        >
                          {status === "done"
                            ? "Complete"
                            : status === "blocked"
                              ? "Blocked"
                              : status === "active"
                                ? "In progress"
                                : "Pending"}
                        </span>
                      </div>
                      {!isOpen ? (
                        <div className="mt-0.5 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                          {step.criterion}
                        </div>
                      ) : null}
                    </div>
                  }
                >
                  <p className="mt-3 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-2)" }}>
                    {step.criterion}
                  </p>
                  {step.evidence.map((line, j) => (
                    <p key={j} className="mt-1 text-[11px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
                      {line}
                    </p>
                  ))}
                  {step.what_now ? (
                    <p className="mt-1.5 text-[12px]" style={{ color: "var(--color-ink)" }}>
                      → {step.what_now}
                    </p>
                  ) : null}
                  {step.note ? (
                    <div className="mt-2">
                      <WarnNote>{step.note}</WarnNote>
                    </div>
                  ) : null}

                  {/* The real work each step expands into. */}
                  {step.id === "gaps" ? (
                    <GapsBody mission={mission} state={step.state} busy={busy} act={act} onOpenPlanner={onOpenPlanner} />
                  ) : step.id === "candidates" ? (
                    <CandidatesBody mission={mission} busy={busy} act={act} />
                  ) : step.id === "open_items" ? (
                    <OpenItemsBody mission={mission} busy={busy} act={act} />
                  ) : step.id === "albert_check" ? (
                    <AlbertBody mission={mission} busy={busy} act={act} />
                  ) : step.id === "handoff" ? (
                    <HandoffBody mission={mission} busy={busy} onMission={onMission} />
                  ) : null}
                </Accordion>
              </div>
            </div>
          )
        })}
      </div>

      {/* Closing has existed on the API since missions shipped and had no control at all,
          so a term the student abandoned — or opened under a programme they have since
          left — stayed in the rail forever with no way out but finishing it. Two-step
          rather than a dialog: it is reversible only by opening a new mission, and the
          decisions recorded inside it do not come back. */}
      <div className="mt-6 flex flex-wrap items-center gap-2">
        {confirmClose ? (
          <>
            <span className="text-[11px]" style={{ color: "var(--color-ink-2)" }}>
              Close {mission.term}? The steps and decisions on it stop being tracked.
            </span>
            <Button size="xs" variant="outline" disabled={busy} onClick={() => onClose(mission)}>
              Close it
            </Button>
            <Button size="xs" variant="outline" disabled={busy} onClick={() => setConfirmClose(false)}>
              Keep it
            </Button>
          </>
        ) : (
          <Button
            size="xs"
            variant="outline"
            disabled={busy}
            onClick={() => setConfirmClose(true)}
          >
            Close this mission
          </Button>
        )}
      </div>
    </>
  )
}

/* ── Step bodies: the unchanged machinery, in the design's inner-card language ────── */

function GapsBody({ mission, state, busy, act, onOpenPlanner }) {
  return (
    <div className="mt-3 space-y-2.5">
      <Muted>
        These are about your degree overall, not about next term. None of them stops you
        registering — you just need to have seen them.
      </Muted>
      {mission.degree_findings.length === 0 ? (
        <Muted>Nothing outstanding at the degree level.</Muted>
      ) : (
        <ul className="findings">
          {mission.degree_findings.map((f) => (
            <Finding key={f.key} finding={f} />
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        {state === "done" ? (
          <span
            className="flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium"
            style={{ background: "var(--color-emerald-muted)", color: "var(--color-emerald)" }}
          >
            <CheckCircle size={10} aria-hidden="true" /> Reviewed
          </span>
        ) : (
          <Button size="sm" disabled={busy} onClick={() => act(() => api.missionAcknowledgeGaps(mission.id))}>
            I have read these
          </Button>
        )}
        {onOpenPlanner ? (
          <Button size="sm" variant="outline" onClick={onOpenPlanner}>
            Edit my record →
          </Button>
        ) : null}
      </div>
    </div>
  )
}

function CandidatesBody({ mission, busy, act }) {
  const [code, setCode] = useState("")
  const search = useCourseSearch({ limit: 6 })
  const chosen = mission.candidates.filter((c) => c.state === "confirmed")
  const proposed = mission.candidates.filter((c) => c.state === "proposed")
  const declined = mission.candidates.filter((c) => c.state === "declined")

  return (
    <div className="mt-3 space-y-2.5">
      {/* Search first, raw code second. The field used to take only a typed code with
          nothing checking it, so a typo became a candidate that looked exactly like a real
          course — and a mission candidate is what the handoff email ends up quoting. */}
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (!code.trim()) return
          act(() => api.missionAddCandidate(mission.id, code.trim()))
          setCode("")
          search.clear()
        }}
      >
        <input
          className={INPUT_CLASS}
          value={code}
          onChange={(e) => {
            setCode(e.target.value)
            search.setQuery(e.target.value)
          }}
          placeholder="Search by code or title, e.g. MASY1-GC 2100"
          aria-label="Course code or title"
          disabled={busy}
        />
        <Button type="submit" size="sm" disabled={busy || !code.trim()}>
          Add
        </Button>
      </form>
      {search.results.length > 0 ? (
        <ul className="flex list-none flex-col gap-1.5">
          {search.results.map((r) => (
            <li key={r.code}>
              <button
                type="button"
                disabled={busy}
                className="w-full rounded-xl px-3 py-2 text-left text-[12px] leading-snug"
                style={{
                  background: "var(--color-surface-2)",
                  border: "1px solid var(--color-rail)",
                  color: "var(--color-ink)",
                }}
                onClick={() => {
                  act(() => api.missionAddCandidate(mission.id, r.code))
                  setCode("")
                  search.clear()
                }}
              >
                <span
                  className="font-medium"
                  style={{ fontFamily: "var(--font-mono)", color: "var(--color-violet-light)" }}
                >
                  {r.code}
                </span>{" "}
                {r.title}
                <span style={{ color: "var(--color-ink-3)" }}> · {r.credits}cr</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {proposed.length > 0 ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium" style={{ color: "var(--color-violet-light)" }}>
            <Sparkles size={11} aria-hidden="true" /> Suggested by the assistant — your call
          </div>
          {proposed.map((c, i) => (
            <div
              key={c.id}
              className="pp-slide-up rounded-xl p-3"
              style={{
                background: "var(--color-violet-muted)",
                border: "1px solid var(--color-violet-edge)",
                animationDelay: `${i * 60}ms`,
              }}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-medium" style={{ fontFamily: "var(--font-mono)", color: "var(--color-violet-light)" }}>
                  {c.course_code}
                </span>
                <Badge variant="outline">Suggestion</Badge>
              </div>
              {c.rationale ? (
                <p className="mt-1 text-[11px] leading-relaxed" style={{ color: "var(--color-ink-2)" }}>
                  {c.rationale}
                </p>
              ) : null}
              <div className="mt-2 flex gap-1.5">
                <Button size="xs" disabled={busy} onClick={() => act(() => api.missionDecideCandidate(mission.id, c.id, true))}>
                  Add to my plan
                </Button>
                <Button size="xs" variant="outline" disabled={busy} onClick={() => act(() => api.missionDecideCandidate(mission.id, c.id, false))}>
                  No thanks
                </Button>
              </div>
            </div>
          ))}
          <Muted>Suggestions do not count toward this step until you add one.</Muted>
        </div>
      ) : null}

      <div className="text-[11px] font-medium tracking-wide uppercase" style={{ color: "var(--color-ink-3)" }}>
        Chosen ({chosen.length})
      </div>
      {chosen.length === 0 ? (
        <Muted>Nothing chosen yet.</Muted>
      ) : (
        <div className="space-y-1.5">
          {chosen.map((c) => (
            <div
              key={c.id}
              className="flex flex-wrap items-center gap-2 rounded-xl px-3 py-2.5"
              style={{ background: "var(--color-surface-2)", border: "1px solid var(--color-rail)" }}
            >
              <span className="text-[11px] font-medium" style={{ fontFamily: "var(--font-mono)", color: "var(--color-violet-light)" }}>
                {c.course_code}
              </span>
              {/* The title is what tells a student they typed the code they meant. When the
                  catalogue does not hold it the course is kept and marked, not refused — a
                  code from another school is legitimate and simply cannot be checked here. */}
              <span className="min-w-0 flex-1 text-[11px] leading-snug" style={{ color: "var(--color-ink-2)" }}>
                {c.title ?? (c.in_catalog ? null : <WarnNote>not in this catalog — check the code</WarnNote>)}
              </span>
              {c.proposed_by === "ai" ? <Badge variant="outline">You accepted a suggestion</Badge> : null}
              <span className="ml-auto">
                <Button size="xs" variant="outline" disabled={busy} onClick={() => act(() => api.missionRemoveCandidate(mission.id, c.id))}>
                  Remove
                </Button>
              </span>
            </div>
          ))}
        </div>
      )}

      {declined.length > 0 ? (
        <Muted>
          Declined: {declined.map((c) => c.course_code).join(", ")}. The assistant cannot re-add these.
        </Muted>
      ) : null}
    </div>
  )
}

function OpenItemsBody({ mission, busy, act }) {
  const [notes, setNotes] = useState({})
  return (
    <div className="mt-3 space-y-2.5">
      {mission.open_blockers.length === 0 && mission.accepted_risks.length === 0 ? (
        <Muted>
          Nothing in the way of the courses you chose — as far as the published rules and
          what you entered can tell.
        </Muted>
      ) : null}

      {mission.open_blockers.length > 0 ? (
        <ul className="findings">
          {mission.open_blockers.map((f) => (
            <Finding key={f.key} finding={f} verdict="not_satisfied">
              <label className="visually-hidden" htmlFor={`note-${f.key}`}>
                Why you are accepting this
              </label>
              <input
                id={`note-${f.key}`}
                className={INPUT_CLASS}
                value={notes[f.key] ?? ""}
                onChange={(e) => setNotes((n) => ({ ...n, [f.key]: e.target.value }))}
                placeholder="Why you are going ahead anyway (goes in the advisor summary)"
                disabled={busy}
              />
              <Button
                size="xs"
                variant="outline"
                disabled={busy}
                onClick={() =>
                  act(() =>
                    api.missionAcceptRisk(mission.id, {
                      finding_key: f.key,
                      finding_summary: f.summary,
                      note: notes[f.key] || null,
                    }),
                  )
                }
              >
                Accept as a known risk
              </Button>
            </Finding>
          ))}
        </ul>
      ) : null}

      {mission.accepted_risks.length > 0 ? (
        <>
          <div className="text-[11px] font-medium tracking-wide uppercase" style={{ color: "var(--color-ink-3)" }}>
            Accepted knowingly
          </div>
          <ul className="findings">
            {mission.accepted_risks.map((r) => (
              <Finding
                key={r.finding_key}
                verdict="conditional"
                label="Accepted"
                summary={r.accepted_summary ?? r.finding_key}
                detail={r.note ? `Your note: ${r.note}` : null}
              >
                {r.reads_differently_now ? (
                  <WarnNote>
                    This now reads differently than when you accepted it. Worth a second look —
                    your acceptance still stands, but it was for the earlier version.
                  </WarnNote>
                ) : null}
                <Button size="xs" variant="outline" disabled={busy} onClick={() => act(() => api.missionWithdrawRisk(mission.id, r.finding_key))}>
                  Undo
                </Button>
              </Finding>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  )
}

/** Step six: the things only Albert can answer, and what the student says they did.
 *
 *  Every sentence on this surface comes from the server (`item.status`), which is where the
 *  red-line probes read. Nothing is composed here, and that is the point: the two claims
 *  this product must never make — a tick with no date, and anything about what the record
 *  actually says — are unavailable to this component because it has no access to the words.
 *  There is no green tick either. A settled item says when it was settled, or it says
 *  nothing.
 */
function AlbertBody({ mission, busy, act }) {
  const items = mission.albert_items ?? []
  const outstanding = items.filter((i) => !i.settled)

  return (
    <div className="mt-3 space-y-2.5">
      <Muted>
        Path Pilot cannot see any of this. Open Albert, look, and record what you did — the
        record is your own, and it goes into the advisor summary in your words.
      </Muted>

      <ul className="findings">
        {items.map((item) => (
          <li
            key={item.key}
            className="rounded-xl p-3"
            style={{
              background: "var(--color-surface-2)",
              border: `1px solid ${item.settled ? "var(--color-rail)" : "var(--color-amber-edge)"}`,
            }}
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="text-[12px] font-medium" style={{ color: "var(--color-ink)" }}>
                {item.label}
              </span>
              {item.moves_fast ? (
                <span
                  className="rounded px-1.5 py-0.5 text-[10px]"
                  style={{ background: "var(--color-amber-muted)", color: "var(--color-amber)" }}
                >
                  Changes quickly
                </span>
              ) : null}
            </div>

            <p className="mt-1 text-[11px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
              {item.where} — {item.what}
            </p>

            {/* The status sentence, server-rendered. A skipped item is not styled as a
                success: it is a decision, and the handoff prints it as one. */}
            <p
              className="mt-1.5 text-[12px]"
              style={{
                color: item.settled && !item.skipped ? "var(--color-emerald)" : "var(--color-ink-2)",
              }}
            >
              {item.status}
            </p>

            <div className="mt-2 flex flex-wrap gap-2">
              {item.settled ? (
                <Button
                  size="xs"
                  variant="outline"
                  disabled={busy}
                  onClick={() => act(() => api.missionUndoAlbertCheck(mission.id, item.key))}
                >
                  Undo
                </Button>
              ) : (
                <>
                  <Button
                    size="xs"
                    disabled={busy}
                    onClick={() => act(() => api.missionAlbertCheck(mission.id, item.key, false))}
                  >
                    I checked this
                  </Button>
                  <Button
                    size="xs"
                    variant="outline"
                    disabled={busy}
                    onClick={() => act(() => api.missionAlbertCheck(mission.id, item.key, true))}
                  >
                    Skip for now
                  </Button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>

      {outstanding.length === 0 && items.length > 0 ? (
        <Muted>
          Everything on this list is settled. What you skipped is named in the advisor
          summary too — this records what you did, not what Albert said.
        </Muted>
      ) : null}
    </div>
  )
}

function HandoffBody({ mission, busy, onMission }) {
  const [question, setQuestion] = useState("")
  const [text, setText] = useState("")
  const [copied, setCopied] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState(null)

  async function generate() {
    setWorking(true)
    setError(null)
    try {
      const result = await api.missionHandoff(mission.id, question)
      setText(result.text)
      if (result.mission) onMission(result.mission)
    } catch (err) {
      setError(err.message)
    } finally {
      setWorking(false)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      /* the textarea stays selectable by hand */
    }
  }

  return (
    <div
      className="mt-3 rounded-xl px-4 py-3"
      style={{ background: "var(--color-surface-3)", border: "1px solid var(--color-rail)" }}
    >
      <div className="mb-2 flex items-center gap-2">
        <User size={13} style={{ color: "var(--color-ink-3)" }} aria-hidden="true" />
        <span className="text-[12px] font-medium" style={{ color: "var(--color-ink-2)" }}>
          Everything you reported, what the rules say, what could not be confirmed, and the
          risks you decided to carry. Copy it into an email — Path Pilot does not send
          anything for you.
        </span>
      </div>
      <input
        className={INPUT_CLASS}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Your main question, in one sentence (optional)"
        aria-label="Your question for the advisor"
        disabled={busy || working}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={generate} disabled={busy || working}>
          <Sparkles size={12} aria-hidden="true" />
          {working ? "Building…" : text ? "Rebuild" : "Generate the summary"}
        </Button>
        {text ? (
          <Button size="sm" variant="outline" onClick={copy}>
            <Copy size={12} aria-hidden="true" />
            {copied ? "Copied ✓" : "Copy to clipboard"}
          </Button>
        ) : null}
      </div>
      {error ? (
        <div className="mt-2">
          <ErrorNote>{error}</ErrorNote>
        </div>
      ) : null}
      {text ? (
        <textarea
          className="nx-scroll mt-2 w-full rounded-md p-3 text-[11px] leading-relaxed outline-none"
          style={{
            background: "var(--color-code-bg)",
            border: "1px solid var(--color-rail)",
            color: "var(--color-ink-2)",
            fontFamily: "var(--font-mono)",
          }}
          readOnly
          value={text}
          rows={16}
          aria-label="Generated advisor email"
        />
      ) : null}
    </div>
  )
}
