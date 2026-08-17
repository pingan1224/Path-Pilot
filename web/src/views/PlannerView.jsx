import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, CheckCircle, Clock, GraduationCap, XCircle } from "lucide-react"
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
import {
  Accordion,
  CardHeading,
  Chip,
  Code,
  MakeCard,
  Sources,
  tone,
  useDisclosure,
} from "@/components/make"
import { useCountUp } from "@/hooks/useCountUp"
import { useCourseSearch } from "@/hooks/useCourseSearch"
import { usePrefs } from "@/i18n"

const STATE_LABEL = {
  completed: "Completed",
  in_progress: "Taking now",
  planned: "Planned",
}

export default function PlannerView({ onOpenProgram, onOpenMission }) {
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
            border: "1px solid var(--color-sky-edge)",
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
          busy={busy}
          onAdd={(code) => saveCourse({ course_code: code, state: "planned" })}
        />

        <CourseEditor
          courses={courses}
          onSave={saveCourse}
          onRemove={removeCourse}
          busy={busy}
          onOpenMission={onOpenMission}
        />

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
        {/* The figure sits in the ring's centre, not under it. The design's own markup
            stacks the text below the svg and pulls it up 8px, which lands it outside
            the ring — a donut's value belongs in the hole it leaves. Absolute centring
            over the same box, so the two stay locked together at any size. */}
        <div className="relative" style={{ width: 124, height: 124 }}>
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
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <div className="text-[28px] leading-none font-bold" style={{ color: "var(--color-ink)" }}>
            {ringAnimated ? Math.round((completed / TOTAL) * 100) : 0}%
          </div>
          <div className="mt-1 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
            {completed} of {TOTAL} cr
          </div>
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

function CourseEditor({ courses, onSave, onRemove, busy, onOpenMission }) {
  const { query, setQuery, results } = useCourseSearch()
  const [manualCode, setManualCode] = useState("")

  const held = new Set(courses.map((c) => c.course_code))

  return (
    <MakeCard delay={260} className="mb-4" aria-labelledby="record-heading">
      <CardHeading
        eyebrow="Your record — self-reported"
        title="My courses"
        titleId="record-heading"
        desc="Path Pilot cannot see Albert. Everything below is what you tell it, and the plan is only as accurate as this list."
      />
      <div className="flex flex-col gap-3">
        <input
          type="search"
          className={`${INPUT_CLASS} w-full`}
          placeholder="Search the SPS graduate catalog — code or title…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search the course catalog"
        />
        {results.length > 0 ? (
          <ul className="flex list-none flex-col gap-2">
            {results.map((r) => (
              <li
                key={r.code}
                className="flex flex-wrap items-center gap-2 rounded-xl p-3"
                style={{
                  background: "var(--color-surface-2)",
                  border: "1px solid var(--color-rail)",
                }}
              >
                <div
                  className="min-w-0 flex-1 text-[12px] leading-relaxed"
                  style={{ color: "var(--color-ink)" }}
                >
                  <Code>{r.code}</Code> {r.title}
                  <span style={{ color: "var(--color-ink-3)" }}> · {r.credits}cr</span>
                  {r.prerequisites_text ? (
                    <span className="block text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                      Prereq: {r.prerequisites_text}
                    </span>
                  ) : null}
                </div>
                {held.has(r.code) ? (
                  <span className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>added</span>
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

        <details
          className="rounded-xl p-3 text-[12px]"
          style={{ background: "var(--color-surface-2)", border: "1px solid var(--color-rail)" }}
        >
          <summary className="cursor-pointer" style={{ color: "var(--color-ink-3)" }}>
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
              <CourseRow
                key={c.course_code}
                course={c}
                busy={busy}
                onSave={onSave}
                onRemove={onRemove}
                onOpenMission={onOpenMission}
              />
            ))}
          </ul>
        )}
      </div>
    </MakeCard>
  )
}

/**
 * One course in the record editor.
 *
 * The grade is a local draft committed on blur or Enter, not a controlled field posted on
 * every keystroke. Saving per keystroke fought the typist three ways at once: the request
 * flipped a view-wide `busy` that disabled this very input, which blurred it mid-word; the
 * refetch that followed snapped the value back to whatever the server had; and a two-
 * character grade meant two writes, so `B+` could persist as `B` if the second keystroke
 * landed during the round trip. `maxLength` is 4, matching the column — 2 truncated the
 * off-scale marks the parser already recognises.
 *
 * Neither control sends `term`. Omitting a field now means "leave it alone" (see
 * services/profile.upsert_course), so re-asserting a value the student did not touch would
 * only add a way for a stale copy to overwrite a fresher one.
 */
function CourseRow({ course: c, busy, onSave, onRemove, onOpenMission }) {
  const [draft, setDraft] = useState(c.grade ?? "")
  const [seen, setSeen] = useState(c.grade ?? "")
  // Follow the server's value until the reader types over it; adopt it again when it
  // actually changes underneath them.
  if ((c.grade ?? "") !== seen) {
    setSeen(c.grade ?? "")
    setDraft(c.grade ?? "")
  }

  const commit = () => {
    const next = draft.trim().toUpperCase()
    if (next === (c.grade ?? "")) return
    setDraft(next)
    onSave({ course_code: c.course_code, state: c.state, grade: next || null })
  }

  return (
    <li
      className="flex flex-wrap items-center gap-2 rounded-xl p-3"
      style={{ background: "var(--color-surface-2)", border: "1px solid var(--color-rail)" }}
    >
      <Code>{c.course_code}</Code>
      <span
        className="min-w-0 flex-1 text-[12px] leading-snug"
        style={{ color: "var(--color-ink)" }}
      >
        {c.title ?? "Not in this catalog"}{" "}
        {!c.in_catalog ? <Tone tone="warn">unverified</Tone> : null}
      </span>
      {/* Confirmed on a mission, not typed here. It counts toward the totals above — it
          is on the plan — but the mission page is where it can be changed, and a second
          writable surface for one fact is how the two came to disagree in the first
          place. Shown rather than hidden: a credit total that includes courses missing
          from the list under it reads as an arithmetic error. */}
      {c.from_mission ? (
        <span className="flex flex-wrap items-center gap-1.5">
          <Tone tone="neutral">from {c.from_mission} mission</Tone>
          {onOpenMission ? (
            <Button size="xs" variant="outline" onClick={onOpenMission}>
              Open mission
            </Button>
          ) : null}
        </span>
      ) : (
      <span className="flex flex-wrap items-center gap-1.5">
        <select
          className="rounded-lg px-2 py-1 text-[12px]"
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-rail-strong)",
            color: "var(--color-ink)",
          }}
          value={c.state}
          disabled={busy}
          aria-label={`Status of ${c.course_code}`}
          onChange={(e) => onSave({ course_code: c.course_code, state: e.target.value })}
        >
          {Object.entries(STATE_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        {c.state === "completed" ? (
          <input
            className="w-16 rounded-lg px-2 py-1 text-[12px] uppercase"
            style={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-rail-strong)",
              color: "var(--color-ink)",
            }}
            value={draft}
            placeholder="grade"
            maxLength={4}
            aria-label={`Grade for ${c.course_code}`}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                e.preventDefault()
                commit()
              }
            }}
          />
        ) : null}
        <Button size="xs" variant="outline" disabled={busy} onClick={() => onRemove(c.course_code)}>
          Remove
        </Button>
      </span>
      )}
    </li>
  )
}

/* ---------------------------------------------------------------------------------- */

function PlanCard({ plan, includePlanned, onTogglePlanned, onAdd, busy }) {
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
          <GroupSection key={f.key} finding={f} defaultOpen={f.verdict !== "satisfied"} delay={400 + i * 70} onAdd={onAdd} busy={busy} />
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
          <GroupSection key={f.key} finding={f} defaultOpen delay={500 + i * 70} onAdd={onAdd} busy={busy} />
        ))}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

/**
 * One requirement finding as the shared accordion: verdict icon, summary, state word in
 * the header; detail, next step and the rule-2 citations in the body. The design's
 * per-course dot strip is absent because the plan's findings carry no per-course rows
 * to draw.
 */
const GROUP_TONE = {
  satisfied: { toneName: "good", icon: CheckCircle, label: "Met" },
  not_satisfied: { toneName: "danger", icon: XCircle, label: "Not met" },
  conditional: { toneName: "warn", icon: AlertTriangle, label: "Ask a human" },
  unverifiable: { toneName: "warn", icon: AlertTriangle, label: "Ask a human" },
}

function GroupSection({ finding, defaultOpen, delay, onAdd, busy }) {
  const [open, toggle] = useDisclosure(defaultOpen)
  const cfg = GROUP_TONE[finding.verdict] ?? GROUP_TONE.unverifiable
  const Icon = cfg.icon

  return (
    <Accordion
      open={open}
      onToggle={toggle}
      delay={delay}
      header={
        <>
          <Icon size={14} style={{ color: tone(cfg.toneName).color, flexShrink: 0 }} aria-hidden="true" />
          <span
            className="min-w-0 flex-1 text-[13px] font-semibold"
            style={{ color: "var(--color-ink)" }}
          >
            {finding.summary}
          </span>
          <Chip toneName={cfg.toneName}>{cfg.label}</Chip>
        </>
      }
    >
      <p className="mt-3 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-2)" }}>
        {finding.detail}
      </p>
      {finding.next_step ? (
        <p className="mt-1.5 text-[12px]" style={{ color: "var(--color-ink)" }}>
          → {finding.next_step}
        </p>
      ) : null}
      {finding.options?.length ? (
        <ElectiveOptions options={finding.options} onAdd={onAdd} busy={busy} />
      ) : null}
      <Sources citations={finding.citations} />
    </Accordion>
  )
}

/**
 * Courses that could fill a credits gap.
 *
 * The disclaimer sits with the list rather than in a page footer, because it is the
 * sentence that stops the list being read as "these count". Whether any of them counts is
 * the bulletin's judgement and the advisor's; every row here rests on something already
 * encoded — named by the requirement, or belonging to a concentration the student is not
 * taking — and says only what this tool can check.
 *
 * Sorted by code, which is not laziness: soonest-offered or fewest-prerequisites would
 * both read as a ranking, and there is no basis for one. Which elective to take is a
 * question about what the student wants to study.
 */
function ElectiveOptions({ options, onAdd, busy }) {
  const [open, toggle] = useDisclosure(false)
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="text-[11px] font-medium"
        style={{ color: "var(--color-violet-light)" }}
      >
        {open ? "Hide" : `Courses you could consider (${options.length})`}
      </button>
      {open ? (
        <div className="mt-2">
          <Muted>
            Courses this programme names for this requirement, plus the concentrations you
            are not taking. The bulletin allows more than this — other graduate programmes
            in the division, for instance — and whether any of them counts is a question
            for your advisor. Path Pilot only checked that you have not taken it and
            whether its prerequisites are met.
          </Muted>
          <ul className="mt-2 flex list-none flex-col gap-1.5">
            {options.map((o) => (
              <li
                key={o.code}
                className="flex flex-wrap items-center gap-2 rounded-xl px-3 py-2"
                style={{
                  background: "var(--color-surface-2)",
                  border: "1px solid var(--color-rail)",
                }}
              >
                <Code>{o.code}</Code>
                <span
                  className="min-w-0 flex-1 text-[12px] leading-snug"
                  style={{ color: "var(--color-ink)" }}
                >
                  {o.title}
                  <span style={{ color: "var(--color-ink-3)" }}>
                    {" · "}
                    {o.credits}cr
                    {o.source === "listed" ? " · listed elective" : ` · from ${o.source}`}
                    {o.typically_offered ? ` · ${o.typically_offered}` : " · term not stated"}
                  </span>
                </span>
                {/* A course whose prerequisites are unmet stays on the list, marked. It
                    may be exactly what they take next year, and dropping it silently is
                    the failure this product treats as worse than an unhelpful answer. */}
                {/* The audit counts a credits requirement from the courses it lists, and
                    nothing else. The bulletin's other allowances are prose the rule engine
                    cannot execute, so a course from another concentration is permitted and
                    will not move the total until an advisor confirms it. Said here, or a
                    student adds what this list suggested and watches the gap not move. */}
                {o.counts_automatically === false ? (
                  <Tone tone="warn">advisor confirms — won't count here</Tone>
                ) : null}
                {o.prerequisites_met === false ? (
                  <Tone tone="warn">needs {o.prerequisite_text ?? "prerequisites"}</Tone>
                ) : null}
                <Button
                  size="xs"
                  variant="outline"
                  disabled={busy}
                  onClick={() => onAdd(o.code)}
                >
                  Add as planned
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
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
      <CardHeading
        eyebrow="Hypothetical — nothing is saved"
        title="What if I took…"
        titleId="whatif-heading"
      />
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
        titleId="handoff-heading"
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
          className="nx-scroll w-full rounded-xl p-3 text-[11px] leading-relaxed outline-none"
          style={{
            background: "var(--color-code-bg)",
            border: "1px solid var(--color-rail)",
            color: "var(--color-ink-2)",
            fontFamily: "var(--font-mono)",
          }}
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
