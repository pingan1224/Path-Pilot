import { useCallback, useEffect, useRef, useState } from "react"
import { api } from "@/api"
import { Finding } from "@/components/Finding"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { ErrorNote, Eyebrow, INPUT_CLASS, Muted, Tone, WarnNote } from "@/components/nocturne"

/**
 * The registration mission: a resumable task, shown as the five steps it actually is.
 *
 * The progress here is never computed in this file. Every mutation returns the whole
 * mission with its step states recomputed server-side, and this component renders what it
 * is given. That is deliberate — a client that derived "you are on step 4" from its own
 * copy of the data would eventually disagree with the server about whether a student is
 * ready to register, and the student would believe whichever one they were looking at.
 *
 * All five step panels stay visible rather than being revealed one at a time. A student who
 * comes back after two weeks needs to see the shape of the whole task and where they
 * stopped, and a wizard that hides the remaining work also hides how much is left.
 *
 * The assistant's suggestions render in the candidate list marked as suggestions, with
 * their reason, and they do not move the progress counter. That gap between "the assistant
 * put three courses in front of me" and "I have chosen three courses" is the product.
 *
 * First view rebuilt off the old App.css families (M-view migration, PRD §10.6 as the
 * checklist). Steps use the same row treatment and the same tones the shell's rail gives
 * this data — one representation of a mission step, wherever it appears.
 */

const STEP_META = {
  done: { tone: "good", label: "Done" },
  active: { tone: "warn", label: "Now" },
  blocked: { tone: "neutral", label: "Waiting" },
}

const TERM_SUGGESTIONS = ["Fall 2026", "Spring 2027", "Summer 2027"]

/**
 * Which step states changed since the last server answer.
 *
 * The mission's progress is derived server-side and arrives whole on every mutation, so a
 * student who confirms a course can have step 3 and step 4 both flip in one response —
 * two rows down the page from the button they pressed. Marking exactly those rows is the
 * "recompute on read" rule made visible; without it the click appears to do nothing.
 *
 * Nothing is marked on first load: an unchanged page has no news, and flashing every row
 * on arrival would teach the student to ignore the one that matters. The set clears
 * itself so a later re-render cannot replay an old change.
 */
function useSettledSteps(steps) {
  const [settled, setSettled] = useState(() => new Set())
  const previous = useRef(null)

  useEffect(() => {
    const now = new Map(steps.map((s) => [s.id, s.state]))
    const before = previous.current
    previous.current = now
    if (!before) return

    const changed = [...now]
      .filter(([id, state]) => before.has(id) && before.get(id) !== state)
      .map(([id]) => id)
    if (changed.length === 0) return

    setSettled(new Set(changed))
    const timer = setTimeout(() => setSettled(new Set()), 1000)
    return () => clearTimeout(timer)
  }, [steps])

  return settled
}

export default function MissionView({ onOpenPlanner }) {
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
      .catch((err) => setError(err.message))
  }, [])

  useEffect(load, [load])

  /** Every mutation hands back the full mission; replace it wholesale. */
  function replace(mission) {
    setMissions((list) => (list ?? []).map((m) => (m.id === mission.id ? mission : m)))
  }

  async function act(fn) {
    setBusy(true)
    setError(null)
    try {
      replace(await fn())
    } catch (err) {
      setError(err.message)
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
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (error && !missions) {
    return (
      <div className="flex flex-col items-start gap-3">
        <ErrorNote>Could not read your missions: {error}</ErrorNote>
        <Button variant="outline" size="sm" onClick={load}>
          Try again
        </Button>
      </div>
    )
  }
  if (!missions) {
    return (
      <p role="status" className="text-body text-muted-foreground">
        Reading your mission…
      </p>
    )
  }

  const mission = missions.find((m) => m.id === activeId) ?? null

  return (
    <div className="flex flex-col gap-4">
      {error ? <ErrorNote>{error}</ErrorNote> : null}

      {missions.length === 0 ? (
        <StartCard onStart={start} busy={busy} />
      ) : (
        <>
          {missions.length > 1 ? (
            <nav
              className="flex flex-wrap gap-1 self-start rounded-[10px] border border-border p-[3px]"
              aria-label="Your missions"
            >
              {missions.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  aria-current={m.id === activeId ? "page" : undefined}
                  onClick={() => setActiveId(m.id)}
                  className={`rounded-md px-2.5 py-2 text-meta transition-colors md:py-1 ${
                    m.id === activeId
                      ? "text-primary shadow-[inset_0_0_0_1px_var(--accent)]"
                      : "text-muted-foreground hover:bg-secondary"
                  }`}
                >
                  {m.term}
                </button>
              ))}
            </nav>
          ) : null}

          {mission ? (
            <Mission
              mission={mission}
              busy={busy}
              act={act}
              onMission={replace}
              onOpenPlanner={onOpenPlanner}
            />
          ) : null}

          <StartCard onStart={start} busy={busy} compact />
        </>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

function StartCard({ onStart, busy, compact = false }) {
  const [term, setTerm] = useState("")

  return (
    <Card>
      <CardHeader>
        <Eyebrow>{compact ? "Another term" : "Get started"}</Eyebrow>
        <CardTitle>
          {compact ? "Start a mission for another term" : "Which term are you preparing for?"}
        </CardTitle>
        {!compact ? (
          <CardDescription>
            A mission walks you through getting ready to register: your record, where you
            stand, the courses you want, what is in the way, and a summary for your advisor.
            You can leave it half-finished and come back — nothing is lost.
          </CardDescription>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <form
          className="flex flex-wrap items-center gap-2"
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
        </form>
        <div className="flex flex-wrap gap-2">
          {TERM_SUGGESTIONS.map((t) => (
            <Button
              key={t}
              size="sm"
              variant="outline"
              className="rounded-full"
              onClick={() => onStart(t)}
              disabled={busy}
            >
              {t}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function Mission({ mission, busy, act, onMission, onOpenPlanner }) {
  const done = mission.steps.filter((s) => s.state === "done").length
  const stepState = (id) => mission.steps.find((s) => s.id === id)?.state
  const settled = useSettledSteps(mission.steps)

  return (
    <>
      <Card className={mission.complete ? "border-success/45" : "border-primary/30"}>
        <CardHeader>
          <Eyebrow>Registration mission</Eyebrow>
          {/* Expanded, but a step below the rail's readiness verdict. The rail answers
              "am I ready"; this only says which term — two peaks would be no peak. */}
          <CardTitle className="nx-statement flex flex-wrap items-center gap-2 text-title">
            {mission.term}
            {mission.complete ? <Badge>Complete</Badge> : null}
          </CardTitle>
          <CardDescription>
            {mission.complete
              ? "Every step is done. Take the handoff to your advisor, then register in Albert."
              : mission.steps.find((s) => s.state === "active")?.what_now}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <Progress value={(done / mission.steps.length) * 100} className="flex-1" />
            <span className="text-meta text-muted-foreground">
              {done}/{mission.steps.length}
            </span>
          </div>
          <p className="text-meta leading-relaxed text-subtle">{mission.disclaimer}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <Eyebrow>The steps</Eyebrow>
          <CardTitle>What finishing means</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="flex list-none flex-col gap-px overflow-hidden rounded-md bg-border">
            {mission.steps.map((step) => {
              const meta = STEP_META[step.state] ?? STEP_META.blocked
              return (
                <li
                  key={step.id}
                  className={`flex flex-col gap-1.5 bg-card px-3.5 py-3 ${
                    settled.has(step.id) ? "nx-settle" : ""
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className={`nx-dot nx-dot--${meta.tone}`} aria-hidden="true" />
                    <span className="min-w-0 flex-1 text-body leading-snug">
                      {step.title}
                    </span>
                    <Tone tone={meta.tone}>{meta.label}</Tone>
                  </div>
                  <p className="text-meta leading-relaxed text-muted-foreground">
                    {step.criterion}
                  </p>
                  {step.evidence.map((line, i) => (
                    <p key={i} className="text-meta leading-relaxed text-subtle">
                      {line}
                    </p>
                  ))}
                  {step.what_now ? (
                    <p className="text-meta leading-relaxed">→ {step.what_now}</p>
                  ) : null}
                  {step.note ? <WarnNote>{step.note}</WarnNote> : null}
                </li>
              )
            })}
          </ol>
        </CardContent>
      </Card>

      <GapsCard
        mission={mission}
        state={stepState("gaps")}
        busy={busy}
        act={act}
        onOpenPlanner={onOpenPlanner}
      />
      <CandidatesCard mission={mission} state={stepState("candidates")} busy={busy} act={act} />
      <OpenItemsCard mission={mission} state={stepState("open_items")} busy={busy} act={act} />
      <HandoffCard
        mission={mission}
        state={stepState("handoff")}
        busy={busy}
        onMission={onMission}
      />
    </>
  )
}

/** One step panel. The active step carries the accent border the chat cards use. */
function Panel({ state, eyebrow, title, children }) {
  return (
    <Card className={state === "active" ? "border-primary/45" : undefined}>
      <CardHeader>
        <Eyebrow>{eyebrow}</Eyebrow>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">{children}</CardContent>
    </Card>
  )
}

function GapsCard({ mission, state, busy, act, onOpenPlanner }) {
  return (
    <Panel state={state} eyebrow="Step 2" title="Where you stand on the degree">
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
      <div className="flex flex-wrap items-center gap-2">
        {state === "done" ? (
          <Tone tone="good">Reviewed</Tone>
        ) : (
          <Button
            disabled={busy}
            onClick={() => act(() => api.missionAcknowledgeGaps(mission.id))}
          >
            I have read these
          </Button>
        )}
        {onOpenPlanner ? (
          <Button variant="outline" onClick={onOpenPlanner}>
            Edit my record →
          </Button>
        ) : null}
      </div>
    </Panel>
  )
}

function CandidatesCard({ mission, state, busy, act }) {
  const [code, setCode] = useState("")
  const chosen = mission.candidates.filter((c) => c.state === "confirmed")
  const proposed = mission.candidates.filter((c) => c.state === "proposed")
  const declined = mission.candidates.filter((c) => c.state === "declined")

  return (
    <Panel state={state} eyebrow="Step 3" title={`Courses for ${mission.term}`}>
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (!code.trim()) return
          act(() => api.missionAddCandidate(mission.id, code.trim()))
          setCode("")
        }}
      >
        <input
          className={INPUT_CLASS}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Add a course by code, e.g. MASY1-GC 2100"
          aria-label="Course code"
          disabled={busy}
        />
        <Button type="submit" disabled={busy || !code.trim()}>
          Add
        </Button>
      </form>

      {proposed.length > 0 ? (
        <>
          <Eyebrow>Suggested by the assistant — your call</Eyebrow>
          <ul className="flex list-none flex-col gap-2">
            {proposed.map((c) => (
              <li
                key={c.id}
                className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/40 p-2.5"
              >
                <span className="font-mono text-sm">{c.course_code}</span>
                <Badge variant="outline">Suggestion</Badge>
                {c.rationale ? (
                  <span className="min-w-0 flex-1 basis-full text-body leading-relaxed text-muted-foreground sm:basis-auto">
                    {c.rationale}
                  </span>
                ) : null}
                <span className="flex gap-1.5">
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
                </span>
              </li>
            ))}
          </ul>
          <Muted>Suggestions do not count toward this step until you add one.</Muted>
        </>
      ) : null}

      <Eyebrow>Chosen ({chosen.length})</Eyebrow>
      {chosen.length === 0 ? (
        <Muted>Nothing chosen yet.</Muted>
      ) : (
        <ul className="flex list-none flex-col gap-2">
          {chosen.map((c) => (
            <li
              key={c.id}
              className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-card p-2.5"
            >
              <span className="font-mono text-sm">{c.course_code}</span>
              {c.proposed_by === "ai" ? (
                <Badge variant="outline">You accepted a suggestion</Badge>
              ) : null}
              <span className="ml-auto">
                <Button
                  size="xs"
                  variant="outline"
                  disabled={busy}
                  onClick={() => act(() => api.missionRemoveCandidate(mission.id, c.id))}
                >
                  Remove
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}

      {declined.length > 0 ? (
        <Muted>
          Declined: {declined.map((c) => c.course_code).join(", ")}. The assistant cannot
          re-add these.
        </Muted>
      ) : null}
    </Panel>
  )
}

function OpenItemsCard({ mission, state, busy, act }) {
  const [notes, setNotes] = useState({})

  return (
    <Panel state={state} eyebrow="Step 4" title="Open items on your chosen courses">
      {mission.open_blockers.length === 0 && mission.accepted_risks.length === 0 ? (
        <Muted>
          Nothing in the way of the courses you chose — as far as the published rules and
          what you entered can tell.
        </Muted>
      ) : null}

      {mission.open_blockers.length > 0 ? (
        <ul className="findings">
          {mission.open_blockers.map((f) => (
            /* A blocker is a `not_satisfied` verdict — it was written as a hardcoded red
               border and a ✕, which is the same statement with the label left off. */
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
          <Eyebrow>Accepted knowingly</Eyebrow>
          <ul className="findings">
            {mission.accepted_risks.map((r) => (
              /* Label overridden because the section heading above already says "Accepted
                 knowingly" — the default "Holds if…" would describe the blocker rather than
                 the student's decision about it. */
              <Finding
                key={r.finding_key}
                verdict="conditional"
                label="Accepted"
                summary={r.accepted_summary ?? r.finding_key}
                detail={r.note ? `Your note: ${r.note}` : null}
              >
                {r.reads_differently_now ? (
                  <WarnNote>
                    This now reads differently than when you accepted it. Worth a second
                    look — your acceptance still stands, but it was for the earlier version.
                  </WarnNote>
                ) : null}
                <Button
                  size="xs"
                  variant="outline"
                  disabled={busy}
                  onClick={() => act(() => api.missionWithdrawRisk(mission.id, r.finding_key))}
                >
                  Undo
                </Button>
              </Finding>
            ))}
          </ul>
        </>
      ) : null}
    </Panel>
  )
}

function HandoffCard({ mission, state, busy, onMission }) {
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
      // Generating the handoff is what completes the last step, so the response carries
      // the recomputed mission. Dropping it left the page showing step 5 as outstanding
      // after it had been satisfied — the same "your click worked and the screen says it
      // did not" failure the service layer had.
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
    <Panel state={state} eyebrow="Step 5" title="Summary for your advisor">
      <Muted>
        Everything you reported, what the rules say about it, what could not be confirmed,
        and the risks you decided to carry. Copy it into an email — UAX does not send
        anything for you.
      </Muted>
      <input
        className={INPUT_CLASS}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Your main question, in one sentence (optional)"
        aria-label="Your question for the advisor"
        disabled={busy || working}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={generate} disabled={busy || working}>
          {working ? "Building…" : text ? "Rebuild" : "Generate the summary"}
        </Button>
        {text ? (
          <Button variant="outline" onClick={copy}>
            {copied ? "Copied ✓" : "Copy to clipboard"}
          </Button>
        ) : null}
      </div>
      {error ? <ErrorNote>{error}</ErrorNote> : null}
      {text ? (
        <textarea
          className="nx-scroll w-full rounded-md border border-border bg-card p-3 font-mono text-meta leading-relaxed outline-none"
          readOnly
          value={text}
          rows={16}
          aria-label="Generated advisor email"
        />
      ) : null}
    </Panel>
  )
}
