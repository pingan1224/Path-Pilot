import { useEffect, useMemo, useState } from "react"
import { api } from "@/api"
import { Finding } from "@/components/Finding"
import {
  ErrorNote,
  Eyebrow,
  INPUT_CLASS,
  Muted,
  ProgramNotice,
  Tone,
  isProgramIssue,
} from "@/components/nocturne"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

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
    <div className="flex flex-col gap-4">
      {error ? <ErrorNote>{error.message}</ErrorNote> : null}

      <CourseEditor courses={courses} onSave={saveCourse} onRemove={removeCourse} busy={busy} />

      <PlanCard
        plan={plan}
        includePlanned={includePlanned}
        onTogglePlanned={() => setIncludePlanned((v) => !v)}
      />

      <WhatIfCard />

      <HandoffCard courses={courses} plan={plan} />
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
    <Card aria-labelledby="record-heading">
      <CardHeader>
        <Eyebrow>Your record — self-reported</Eyebrow>
        <CardTitle id="record-heading">My courses</CardTitle>
        <CardDescription>
          Path Pilot cannot see Albert. Everything below is what you tell it, and the plan is only
          as accurate as this list.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
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
      </CardContent>
    </Card>
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
    <Card aria-labelledby="plan-heading">
      <CardHeader>
        <Eyebrow>Computed from published rules · checked {plan.rules_verified_on}</Eyebrow>
        <CardTitle id="plan-heading">{plan.program_name} — degree check</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <label className="flex items-center gap-2 text-body text-muted-foreground">
          <input type="checkbox" checked={includePlanned} onChange={onTogglePlanned} />
          Count planned &amp; in-progress courses
        </label>

        <p className="flex flex-wrap gap-x-4 gap-y-1 text-body">
          <span>
            <strong className="font-medium">{plan.credits_completed}</strong> completed
          </span>
          <span>
            <strong className="font-medium">{plan.credits_in_progress}</strong> in progress
          </span>
          <span>
            <strong className="font-medium">{plan.credits_planned}</strong> planned
          </span>
          <span className="text-muted-foreground">of {plan.credits_required} required</span>
        </p>

        <ul className="findings">
          {settled.map((f, i) => (
            <Finding key={i} finding={f} />
          ))}
        </ul>

        {forHumans.length > 0 ? (
          <>
            <div className="flex flex-col gap-1">
              <Eyebrow>Needs a human</Eyebrow>
              <Muted>
                These are the parts this tool cannot settle — which is exactly what to bring
                to your advisor.
              </Muted>
            </div>
            <ul className="findings">
              {forHumans.map((f, i) => (
                <Finding key={i} finding={f} />
              ))}
            </ul>
          </>
        ) : null}

        <p className="text-meta leading-relaxed text-subtle">{plan.disclaimer}</p>
      </CardContent>
    </Card>
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
    <Card aria-labelledby="whatif-heading">
      <CardHeader>
        <Eyebrow>Hypothetical — nothing is saved</Eyebrow>
        <CardTitle id="whatif-heading">What if I took…</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
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
      </CardContent>
    </Card>
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
    <Card aria-labelledby="handoff-heading">
      <CardHeader>
        <Eyebrow>For your advisor</Eyebrow>
        <CardTitle id="handoff-heading">Advisor handoff</CardTitle>
        <CardDescription>
          A ready-to-send summary of your record, what the rules say, and what only your
          advisor can answer. Copy it into an email — Path Pilot does not send anything for you.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
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
      </CardContent>
    </Card>
  )
}
