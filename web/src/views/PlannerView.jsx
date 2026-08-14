import { useEffect, useMemo, useRef, useState } from "react"
import {
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  Clock,
  GraduationCap,
  XCircle,
} from "lucide-react"
import { api } from "@/api"
import { Finding } from "@/components/Finding"
import {
  ErrorNote,
  INPUT_CLASS,
  Muted,
  ProgramNotice,
  Tone,
  isProgramIssue,
} from "@/components/nocturne"
import { Button } from "@/components/ui/button"
import { useCountUp } from "@/hooks/useCountUp"
import { usePrefs } from "@/i18n"

/** The design's card shell: rounded-2xl surface with a strong rail. */
function MakeCard({ children, delay = 0, className = "" }) {
  return (
    <div
      className={`pp-slide-up rounded-2xl p-4 ${className}`}
      style={{
        background: "var(--color-surface)",
        border: "1px solid var(--color-rail-strong)",
        animationDelay: `${delay}ms`,
      }}
    >
      {children}
    </div>
  )
}

function CardHeading({ eyebrow, title, desc }) {
  return (
    <div className="mb-3">
      {eyebrow ? (
        <div
          className="mb-1 text-[10px] font-medium tracking-wide uppercase"
          style={{ color: "var(--color-ink-3)" }}
        >
          {eyebrow}
        </div>
      ) : null}
      <div className="text-[14px] font-semibold" style={{ color: "var(--color-ink)" }}>
        {title}
      </div>
      {desc ? (
        <p className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
          {desc}
        </p>
      ) : null}
    </div>
  )
}

/**
 * The degree planner: self-reported record in, verdicts with citations out.
 *
 * Layout follows the trust model. The record editor sits first because everything below
 * is derived from it; the plan is labelled as computed from published rules; and the
 * verdicts a human must resolve are visually separated from the ones the engine settled.
 * The handoff generator is a pure template over the plan data — deterministic, instant,
 * and faithful, which matters more than prose polish in a document a student sends to
 * their advisor.
 */

const STATE_LABEL = {
  completed: "Completed",
  in_progress: "Taking now",
  planned: "Planned",
}

export default function PlannerView({ onOpenProgram }) {
  const { t } = usePrefs()
  const [courses, setCourses] = useState(null)
  const [plan, setPlan] = useState(null)
  const [includePlanned, setIncludePlanned] = useState(false)
  // The whole error, not just its message: a program-shaped failure gets its own screen
  // rather than a generic note with a retry that cannot help.
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function refresh() {
    try {
      const [profile, planned] = await Promise.all([
        api.profileCourses(),
        api.plan(includePlanned),
      ])
      setCourses(profile)
      setPlan(planned)
      setError(null)
    } catch (err) {
      setError(err)
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includePlanned])

  async function saveCourse(payload) {
    setBusy(true)
    try {
      await api.profilePut(payload)
      await refresh()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function removeCourse(code) {
    setBusy(true)
    try {
      await api.profileDelete(code)
      await refresh()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  if (error && !plan) {
    // A program-shaped refusal is not a failure to retry — it is the product boundary,
    // and it gets a screen that says which of the two it is.
    return (
      <div className="flex flex-col items-start gap-3">
        {isProgramIssue(error.code) ? (
          <ProgramNotice
            code={error.code}
            message={error.message}
            onChooseProgram={onOpenProgram}
          />
        ) : (
          <>
            <ErrorNote>Could not read your plan: {error.message}</ErrorNote>
            <Button variant="outline" size="sm" onClick={refresh}>
              Try again
            </Button>
          </>
        )}
      </div>
    )
  }
  if (!courses || !plan) {
    return (
      <p role="status" className="text-body text-muted-foreground">
        Reading your plan…
      </p>
    )
  }

  return (
    <div className="nx-scroll h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-6">
        {/* Header — the design's, over the real program name. */}
        <div className="pp-slide-up mb-6 flex items-start gap-4">
          <GraduationCap
            size={22}
            style={{ color: "var(--color-violet-light)", flexShrink: 0, marginTop: 2 }}
            aria-hidden="true"
          />
          <div>
            <h1
              className="text-[22px] leading-tight font-semibold"
              style={{ fontFamily: "var(--font-display)", color: "var(--color-ink)" }}
            >
              {t("nav.planner")}
            </h1>
            <p className="mt-1 text-[13px]" style={{ color: "var(--color-ink-3)" }}>
              {plan.program_name} · checked {plan.rules_verified_on}
            </p>
          </div>
        </div>

        {error ? (
          <div className="mb-4">
            <ErrorNote>{error.message}</ErrorNote>
          </div>
        ) : null}

        <RingSummary plan={plan} />

        {/* Legend — the design's status strip, in the plan's own verdict language. */}
        <div
          className="pp-fade-in mb-5 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl px-4 py-2.5"
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-rail)",
            animationDelay: "320ms",
          }}
        >
          <span
            className="text-[11px] font-medium tracking-wide uppercase"
            style={{ color: "var(--color-ink-3)" }}
          >
            Status
          </span>
          {[
            { icon: CheckCircle, color: "var(--color-emerald)", label: "Verified met" },
            { icon: XCircle, color: "var(--color-rose)", label: "Not met" },
            { icon: AlertTriangle, color: "var(--color-amber)", label: "Ask a human" },
            { icon: Clock, color: "var(--color-violet-light)", label: "Counting in-progress" },
          ].map(({ icon: Icon, color, label }) => (
            <div key={label} className="flex items-center gap-1.5">
              <Icon size={12} style={{ color }} aria-hidden="true" />
              <span className="text-[11px]" style={{ color: "var(--color-ink-2)" }}>
                {label}
              </span>
            </div>
          ))}
        </div>

        {/* Disclaimer — the design's sky card, carrying the plan's real one. */}
        <div
          className="pp-fade-in mb-5 flex items-start gap-2.5 rounded-xl px-4 py-3"
          style={{
            background: "var(--color-sky-muted)",
            border: "1px solid rgba(96,165,250,0.2)",
            animationDelay: "360ms",
          }}
        >
          <GraduationCap
            size={13}
            style={{ color: "var(--color-sky)", flexShrink: 0, marginTop: 1 }}
            aria-hidden="true"
          />
          <div>
            <div className="text-[12px] font-medium" style={{ color: "var(--color-sky)" }}>
              Self-reported record
            </div>
            <div className="mt-0.5 text-[11px]" style={{ color: "var(--color-sky)", opacity: 0.7 }}>
              {plan.disclaimer}
            </div>
          </div>
        </div>

        <PlanCard
          plan={plan}
          includePlanned={includePlanned}
          onTogglePlanned={() => setIncludePlanned((v) => !v)}
        />

        <CourseEditor courses={courses} onSave={saveCourse} onRemove={removeCourse} busy={busy} />

        <WhatIfCard />

        <HandoffCard courses={courses} plan={plan} />
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

/**
 * The design's ring-and-stats block, on the real plan: SVG arcs animating to the
 * completed and in-progress shares, count-up figures, and a Planned tile where the
 * design showed a graduation date this product does not know (the sequence page owns
 * finish dates; inventing one here would be the exact claim the product refuses).
 */
function RingSummary({ plan }) {
  const [ringAnimated, setRingAnimated] = useState(false)
  useEffect(() => {
    const timer = setTimeout(() => setRingAnimated(true), 120)
    return () => clearTimeout(timer)
  }, [])

  const TOTAL = plan.credits_required || 1
  const completed = useCountUp(plan.credits_completed, 800, ringAnimated)
  const inProg = useCountUp(plan.credits_in_progress, 700, ringAnimated)
  const planned = useCountUp(plan.credits_planned, 750, ringAnimated)

  const circumference = 2 * Math.PI * 52
  const completedOffset = circumference * (1 - plan.credits_completed / TOTAL)
  const inProgOffset =
    circumference * (1 - (plan.credits_completed + plan.credits_in_progress) / TOTAL)

  const remaining = Math.max(
    plan.credits_required - plan.credits_completed - plan.credits_in_progress,
    0,
  )
  const remainingUp = useCountUp(remaining, 750, ringAnimated)

  const STATS = [
    { label: "Completed", value: completed, color: "var(--color-emerald)", bg: "var(--color-emerald-muted)" },
    { label: "In progress", value: inProg, color: "var(--color-violet-light)", bg: "var(--color-violet-muted)" },
    { label: "Remaining", value: remainingUp, color: "var(--color-ink-2)", bg: "var(--color-surface)" },
    { label: "Planned", value: planned, color: "var(--color-amber)", bg: "var(--color-amber-muted)" },
  ]

  return (
    <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
      <div
        className="pp-slide-up col-span-1 flex flex-col items-center justify-center rounded-2xl p-5"
        style={{
          background: "var(--color-surface)",
          border: "1px solid var(--color-rail-strong)",
          animationDelay: "60ms",
        }}
      >
        <svg width="124" height="124" viewBox="0 0 124 124" aria-hidden="true">
          <circle cx="62" cy="62" r="52" fill="none" stroke="var(--color-surface-2)" strokeWidth="10" />
          <circle
            cx="62" cy="62" r="52" fill="none"
            stroke="var(--color-violet)" strokeWidth="10" strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={ringAnimated ? completedOffset : circumference}
            transform="rotate(-90 62 62)"
            style={{ transition: "stroke-dashoffset 900ms cubic-bezier(0.22,1,0.36,1)" }}
          />
          <circle
            cx="62" cy="62" r="52" fill="none"
            stroke="var(--color-violet-light)" strokeWidth="10" strokeLinecap="round"
            strokeDasharray={
              ringAnimated
                ? `${circumference * (plan.credits_in_progress / TOTAL)} ${circumference}`
                : `0 ${circumference}`
            }
            strokeDashoffset={ringAnimated ? inProgOffset : circumference}
            transform="rotate(-90 62 62)"
            style={{
              opacity: 0.35,
              transition:
                "stroke-dasharray 800ms cubic-bezier(0.22,1,0.36,1) 100ms, stroke-dashoffset 800ms cubic-bezier(0.22,1,0.36,1) 100ms",
            }}
          />
        </svg>
        <div className="-mt-2 text-center">
          <div className="text-[28px] leading-none font-bold" style={{ color: "var(--color-ink)" }}>
            {ringAnimated ? Math.round((completed / TOTAL) * 100) : 0}%
          </div>
          <div className="mt-1 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
            {completed} of {TOTAL} cr
          </div>
        </div>
      </div>

      <div className="col-span-1 grid grid-cols-2 gap-3 sm:col-span-2">
        {STATS.map((stat, i) => (
          <div
            key={stat.label}
            className="pp-slide-up rounded-xl p-4"
            style={{
              background: stat.bg,
              border: "1px solid var(--color-rail-strong)",
              animationDelay: `${(i + 1) * 60 + 60}ms`,
            }}
          >
            <div
              className="mb-1 text-[10px] font-medium tracking-wide uppercase"
              style={{ color: "var(--color-ink-3)" }}
            >
              {stat.label}
            </div>
            <div className="text-[20px] leading-none font-bold" style={{ color: stat.color }}>
              {stat.value} <span className="text-[13px] font-medium">cr</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

function CourseEditor({ courses, onSave, onRemove, busy }) {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState([])
  const [manualCode, setManualCode] = useState("")

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([])
      return
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const found = await api.catalogSearch(query)
        if (!cancelled) setResults(found.slice(0, 8))
      } catch {
        /* search failures are non-fatal; the manual field still works */
      }
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query])

  const held = new Set(courses.map((c) => c.course_code))

  return (
    <MakeCard delay={260} className="mb-4" aria-labelledby="record-heading">
      <CardHeading
        eyebrow="Your record — self-reported"
        title="My courses"
        desc="Path Pilot cannot see Albert. Everything below is what you tell it, and the plan is only as accurate as this list."
      />
      <div className="flex flex-col gap-3">
        <input
          type="search"
          className={`${INPUT_CLASS} w-full`}
          placeholder="Search the MASY catalog — code or title…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search the course catalog"
        />
        {results.length > 0 ? (
          <ul className="flex list-none flex-col gap-2">
            {results.map((r) => (
              <li
                key={r.code}
                className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/40 p-2.5"
              >
                <div className="min-w-0 flex-1 text-body leading-relaxed">
                  <span className="font-mono">{r.code}</span> {r.title}
                  <span className="text-muted-foreground"> · {r.credits}cr</span>
                  {r.prerequisites_text ? (
                    <span className="block text-meta text-muted-foreground">
                      Prereq: {r.prerequisites_text}
                    </span>
                  ) : null}
                </div>
                {held.has(r.code) ? (
                  <span className="text-meta text-muted-foreground">added</span>
                ) : (
                  <span className="flex flex-wrap gap-1.5">
                    {["completed", "in_progress", "planned"].map((state) => (
                      <Button
                        key={state}
                        size="xs"
                        variant="outline"
                        disabled={busy}
                        onClick={() => {
                          onSave({ course_code: r.code, state })
                          setQuery("")
                        }}
                      >
                        {STATE_LABEL[state]}
                      </Button>
                    ))}
                  </span>
                )}
              </li>
            ))}
          </ul>
        ) : null}

        <details className="rounded-md border border-border bg-muted/40 p-2.5 text-body">
          <summary className="cursor-pointer text-muted-foreground">
            Course not in this catalog? Add it by code
          </summary>
          <div className="mt-2 flex flex-col gap-2">
            <Muted>
              Cross-school and outside-program courses are allowed by your elective rules, but
              this tool cannot verify them — they will show as “ask a human”.
            </Muted>
            <form
              className="flex flex-wrap items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                const code = manualCode.trim()
                if (code) {
                  onSave({ course_code: code, state: "planned" })
                  setManualCode("")
                }
              }}
            >
              <input
                className={INPUT_CLASS}
                value={manualCode}
                onChange={(e) => setManualCode(e.target.value)}
                placeholder="e.g. MKTG-GB 2350"
                aria-label="Course code"
              />
              <Button type="submit" variant="outline" disabled={busy}>
                Add as planned
              </Button>
            </form>
          </div>
        </details>

        {courses.length === 0 ? (
          <Muted>No courses yet — search above to start building your record.</Muted>
        ) : (
          <ul className="flex list-none flex-col gap-2">
            {courses.map((c) => (
              <li
                key={c.course_code}
                className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-card p-2.5"
              >
                <span className="font-mono text-sm">{c.course_code}</span>
                <span className="min-w-0 flex-1 text-body leading-snug">
                  {c.title ?? "Not in this catalog"}{" "}
                  {!c.in_catalog ? <Tone tone="warn">unverified</Tone> : null}
                </span>
                <span className="flex flex-wrap items-center gap-1.5">
                  <select
                    className="rounded-md border border-border bg-card px-2 py-1 text-body"
                    value={c.state}
                    disabled={busy}
                    aria-label={`Status of ${c.course_code}`}
                    onChange={(e) =>
                      onSave({ course_code: c.course_code, state: e.target.value, grade: c.grade })
                    }
                  >
                    {Object.entries(STATE_LABEL).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  {c.state === "completed" ? (
                    <input
                      className="w-16 rounded-md border border-border bg-card px-2 py-1 text-body uppercase"
                      value={c.grade ?? ""}
                      placeholder="grade"
                      maxLength={2}
                      disabled={busy}
                      aria-label={`Grade for ${c.course_code}`}
                      onChange={(e) =>
                        onSave({
                          course_code: c.course_code,
                          state: c.state,
                          grade: e.target.value || null,
                        })
                      }
                    />
                  ) : null}
                  <Button
                    size="xs"
                    variant="outline"
                    disabled={busy}
                    onClick={() => onRemove(c.course_code)}
                  >
                    Remove
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </MakeCard>
  )
}

/* ---------------------------------------------------------------------------------- */

function PlanCard({ plan, includePlanned, onTogglePlanned }) {
  const settled = plan.findings.filter(
    (f) => f.verdict === "satisfied" || f.verdict === "not_satisfied",
  )
  const forHumans = plan.findings.filter(
    (f) => f.verdict === "conditional" || f.verdict === "unverifiable",
  )

  return (
    <div className="mb-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div
            className="text-[10px] font-medium tracking-wide uppercase"
            style={{ color: "var(--color-ink-3)" }}
          >
            Computed from published rules · checked {plan.rules_verified_on}
          </div>
          <div className="text-[14px] font-semibold" style={{ color: "var(--color-ink)" }}>
            {plan.program_name} — degree check
          </div>
        </div>
        <label
          className="flex items-center gap-2 text-[12px]"
          style={{ color: "var(--color-ink-3)" }}
        >
          <input type="checkbox" checked={includePlanned} onChange={onTogglePlanned} />
          Count planned &amp; in-progress
        </label>
      </div>

      <div className="space-y-3">
        {settled.map((f, i) => (
          <GroupSection key={f.key} finding={f} defaultOpen={f.verdict !== "satisfied"} delay={400 + i * 70} />
        ))}
        {forHumans.length > 0 ? (
          <div
            className="mt-1 text-[10px] font-medium tracking-wide uppercase"
            style={{ color: "var(--color-amber)" }}
          >
            Needs a human — exactly what to bring to your advisor
          </div>
        ) : null}
        {forHumans.map((f, i) => (
          <GroupSection key={f.key} finding={f} defaultOpen delay={500 + i * 70} />
        ))}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

/**
 * The design's requirement-group accordion, one per finding. The verdict maps onto the
 * design's status vocabulary; the body holds what the engine actually said — detail,
 * next step, and the citations rule 2 requires. The design's per-course dot strip is
 * absent because the plan's findings carry no per-course rows to draw.
 */
const GROUP_ICON = {
  satisfied: { icon: CheckCircle, color: "var(--color-emerald)", label: "Met" },
  not_satisfied: { icon: XCircle, color: "var(--color-rose)", label: "Not met" },
  conditional: { icon: AlertTriangle, color: "var(--color-amber)", label: "Ask a human" },
  unverifiable: { icon: AlertTriangle, color: "var(--color-amber)", label: "Ask a human" },
}

function GroupSection({ finding, defaultOpen, delay }) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyRef = useRef(null)
  const cfg = GROUP_ICON[finding.verdict] ?? GROUP_ICON.unverifiable
  const Icon = cfg.icon

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.style.maxHeight = open ? `${el.scrollHeight}px` : "0px"
  })

  return (
    <div
      className="pp-slide-up overflow-hidden rounded-xl"
      style={{
        border: "1px solid var(--color-rail-strong)",
        background: "var(--color-surface)",
        animationDelay: `${delay}ms`,
      }}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3.5 text-left"
        style={{ transition: "background 140ms ease" }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "rgba(124,58,237,0.03)"
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = ""
        }}
      >
        <Icon size={14} style={{ color: cfg.color, flexShrink: 0 }} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <span className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
            {finding.summary}
          </span>
        </div>
        <span className="shrink-0 text-[11px] font-medium" style={{ color: cfg.color }}>
          {cfg.label}
        </span>
        <div
          style={{
            transform: open ? "rotate(0deg)" : "rotate(-90deg)",
            transition: "transform 220ms cubic-bezier(0.22,1,0.36,1)",
            color: "var(--color-ink-3)",
            flexShrink: 0,
          }}
        >
          <ChevronDown size={13} aria-hidden="true" />
        </div>
      </button>

      <div
        ref={bodyRef}
        className="overflow-hidden"
        style={{ maxHeight: 0, transition: "max-height 270ms cubic-bezier(0.22,1,0.36,1)" }}
      >
        <div className="px-4 pb-3.5" style={{ borderTop: "1px solid var(--color-rail)" }}>
          <p className="mt-3 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-2)" }}>
            {finding.detail}
          </p>
          {finding.next_step ? (
            <p className="mt-1.5 text-[12px]" style={{ color: "var(--color-ink)" }}>
              → {finding.next_step}
            </p>
          ) : null}
          {finding.citations?.length ? (
            <details className="mt-2 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
              <summary className="cursor-pointer">Source</summary>
              <ul className="mt-1 space-y-1">
                {finding.citations.map((c, i) => (
                  <li key={i}>
                    {c.url ? (
                      <a href={c.url} target="_blank" rel="noreferrer" className="underline">
                        {c.label}
                      </a>
                    ) : (
                      c.label
                    )}
                    {c.verified_on ? ` · checked ${c.verified_on}` : ""}
                    {c.quote ? (
                      <span
                        className="mt-0.5 block rounded px-2 py-1"
                        style={{ background: "var(--color-code-bg)", fontFamily: "var(--font-mono)" }}
                      >
                        {c.quote}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

function WhatIfCard() {
  const [code, setCode] = useState("")
  // The course the displayed result is about, which is not the same as whatever is
  // currently in the box once the student starts typing the next question.
  const [asked, setAsked] = useState("")
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function run(e) {
    e.preventDefault()
    const trimmed = code.trim()
    if (!trimmed) return
    setBusy(true)
    setError(null)
    try {
      setResult(await api.whatIf([{ course_code: trimmed, state: "planned" }]))
      setAsked(trimmed.toUpperCase())
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // Only findings that actually mention the course asked about. An earlier version also
  // swept in every unmet requirement, which answered "what if I took 2100" with a note
  // about the capstone — true, unasked, and enough noise to bury the real answer.
  const relevant = useMemo(() => {
    if (!result) return []
    const needle = (asked || "").toUpperCase()
    if (!needle) return []
    return result.findings.filter(
      (f) =>
        f.summary.toUpperCase().includes(needle) ||
        f.detail.toUpperCase().includes(needle),
    )
  }, [result, asked])

  return (
    <MakeCard delay={320} className="mb-4" aria-labelledby="whatif-heading">
      <CardHeading eyebrow="Hypothetical — nothing is saved" title="What if I took…" />
      <div className="flex flex-col gap-3">
        <form className="flex flex-wrap items-center gap-2" onSubmit={run}>
          <input
            className={INPUT_CLASS}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Course code, e.g. MASY1-GC 2100"
            aria-label="Course code to test"
          />
          <Button type="submit" disabled={busy || !code.trim()}>
            {busy ? "Checking…" : "Check"}
          </Button>
        </form>
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        {result ? (
          relevant.length > 0 ? (
            <>
              <Muted>Adding {asked} to your plan:</Muted>
              <ul className="findings">
                {relevant.map((f, i) => (
                  <Finding key={i} finding={f} />
                ))}
              </ul>
            </>
          ) : (
            <Muted>
              Nothing in the encoded rules blocks {asked}. Seat availability and any
              departmental approval still have to be checked in Albert.
            </Muted>
          )
        ) : null}
      </div>
    </MakeCard>
  )
}

/* ---------------------------------------------------------------------------------- */

function buildHandoff(courses, plan, question) {
  const byState = (state) =>
    courses
      .filter((c) => c.state === state)
      .map((c) => `  - ${c.course_code}${c.title ? ` (${c.title})` : ""}${c.grade ? ` — ${c.grade}` : ""}`)
      .join("\n") || "  (none)"

  const confirmed = plan.findings
    .filter((f) => f.verdict === "satisfied" || f.verdict === "not_satisfied")
    .map((f) => `  - ${f.verdict === "satisfied" ? "[met]" : "[not met]"} ${f.summary}`)
    .join("\n")

  const open = plan.findings
    .filter((f) => f.verdict === "conditional" || f.verdict === "unverifiable")
    .map((f) => `  - ${f.summary}: ${f.detail}`)
    .join("\n")

  const questions = plan.findings
    .filter((f) => f.next_step && f.verdict !== "satisfied")
    .map((f) => `  ${f.next_step}`)
    .filter((v, i, a) => a.indexOf(v) === i)
    .join("\n")

  return `Subject: Advising question — degree plan check

Hi,

${question.trim() || "I would like to review my degree plan and registration for next term."}

MY RECORD AS I UNDERSTAND IT (self-reported, please correct me if Albert says otherwise):

Completed:
${byState("completed")}

Taking now:
${byState("in_progress")}

Planning to take:
${byState("planned")}

WHAT THE PUBLISHED RULES SAY (checked against the ${plan.program_name} bulletin, ${plan.rules_verified_on}):
${confirmed}

WHAT I COULD NOT CONFIRM MYSELF:
${open || "  (nothing outstanding)"}

MY QUESTIONS:
${questions || "  Does this plan look right to you?"}

Generated with Path Pilot, an independent planning tool (not an NYU system). Everything above
should be verified against Albert.

Thanks!`
}

function HandoffCard({ courses, plan }) {
  const [question, setQuestion] = useState("")
  const [copied, setCopied] = useState(false)

  const text = useMemo(
    () => buildHandoff(courses, plan, question),
    [courses, plan, question],
  )

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      /* the textarea below remains selectable by hand */
    }
  }

  return (
    <MakeCard delay={380} aria-labelledby="handoff-heading">
      <CardHeading
        eyebrow="For your advisor"
        title="Advisor handoff"
        desc="A ready-to-send summary of your record, what the rules say, and what only your advisor can answer. Copy it into an email — Path Pilot does not send anything for you."
      />
      <div className="flex flex-col gap-3">
        <input
          className={INPUT_CLASS}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Your main question, in one sentence (optional)"
          aria-label="Your question for the advisor"
        />
        <textarea
          className="nx-scroll w-full rounded-md border border-border bg-card p-3 font-mono text-meta leading-relaxed outline-none"
          readOnly
          value={text}
          rows={14}
          aria-label="Generated advisor email"
        />
        <div>
          <Button onClick={copy}>{copied ? "Copied ✓" : "Copy to clipboard"}</Button>
        </div>
      </div>
    </MakeCard>
  )
}
