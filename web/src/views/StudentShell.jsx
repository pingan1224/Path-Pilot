import { useCallback, useEffect, useState } from "react"
import { api } from "@/api"
import { Button } from "@/components/ui/button"
import ChatHome from "./ChatHome"
import DecoderView from "./DecoderView"
import IntakeView from "./IntakeView"
import MissionView from "./MissionView"
import PlannerView from "./PlannerView"
import SequenceView from "./SequenceView"
import StudentView from "./StudentView"

/**
 * The student app frame: a full-viewport two-pane workspace with the assistant as the
 * front door.
 *
 * The old shell gave the student seven equal tabs inside a 1080px column — a toolbox
 * with the chat as one of the drawers. This inverts it: the conversation owns the
 * screen, a left rail says where registration actually stands, and the tool pages open
 * *inside* the frame as drill-downs rather than as destinations of equal rank. The chat
 * stays mounted (hidden, not unmounted) while a tool page is open, so walking off to
 * confirm a course and coming back does not cost the thread.
 *
 * The rail is shell furniture, not chat furniture. It re-reads the mission and profile
 * on every view change because the tool pages write exactly the state it shows — the
 * same "recompute on read, never store a status" rule the mission engine runs on.
 */

const NAV = [
  ["chat", "Assistant"],
  ["intake", "Add from transcript"],
  ["decoder", "Decode an error"],
  ["mission", "Registration mission"],
  ["sequence", "Term sequence"],
  ["planner", "Degree planner"],
]

const PANES = [
  ["drawer", "Readiness"],
  ["focused", "Conversation only"],
  ["audit", "What was checked"],
]

// A failed read is its own state, never an empty array: the rail renders [] as "nothing
// in your record", and a dead API dressed up as an empty record is the silent failure
// rule 6 forbids. "No access" is not "no results".
const LOAD_FAILED = Symbol("load failed")

export default function StudentShell({ me, onSignOut }) {
  const [view, setView] = useState("chat")
  const [pane, setPane] = useState("drawer")
  const [missions, setMissions] = useState(null)
  const [courses, setCourses] = useState(null)

  const refresh = useCallback(() => {
    api.missions().then(setMissions).catch(() => setMissions(LOAD_FAILED))
    api.profileCourses().then(setCourses).catch(() => setCourses(LOAD_FAILED))
  }, [])

  // On mount and on every view change: Intake writes the profile, Mission writes the
  // mission, and the rail must not keep showing the state from before the detour.
  useEffect(refresh, [refresh, view])

  const failed = missions === LOAD_FAILED || courses === LOAD_FAILED
  const ready = Array.isArray(missions) && Array.isArray(courses)
  const mission = ready ? (missions.find((m) => !m.complete) ?? null) : null
  const inChat = view === "chat"
  // In a tool view the rail is also the way around, so it stays; the pane switch is a
  // chat-reading preference, not app chrome.
  const railVisible = !inChat || pane === "drawer"

  const nav = me.student_id ? [...NAV, ["dashboard", "Dashboard (demo)"]] : NAV

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <a className="skip" href="#main">
        Skip to content
      </a>

      <header className="flex flex-none flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-2.5 sm:px-5">
        <div className="flex items-baseline gap-2">
          <span className="nx-statement text-title">UAX</span>
          <span className="hidden nx-label sm:inline">
            Unified Academic Experience
          </span>
        </div>

        <div className="mx-auto">
          {inChat ? (
            <div
              className="flex gap-1 rounded-[10px] border border-border p-[3px]"
              role="group"
              aria-label="Side pane"
            >
              {PANES.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={pane === id}
                  onClick={() => setPane(id)}
                  className={`rounded-md px-2.5 py-1 text-meta transition-colors ${
                    pane === id
                      ? "text-primary shadow-[inset_0_0_0_1px_var(--accent)]"
                      : "text-muted-foreground hover:bg-secondary"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setView("chat")}>
              ← Back to assistant
            </Button>
          )}
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-body leading-tight">{me.full_name}</div>
            <div className="text-micro text-subtle">
              {me.student_number ?? me.role}
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={onSignOut}>
            Sign out
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {railVisible ? (
          <Rail
            mission={mission}
            courseCount={ready ? courses.length : 0}
            ready={ready}
            failed={failed}
            onRetry={refresh}
            view={view}
            nav={nav}
            onOpenView={setView}
          />
        ) : null}

        <main id="main" className="flex min-h-0 min-w-0 flex-1 flex-col">
          {/* `hidden`, not unmount: the thread survives a trip to a tool page. */}
          <div className={inChat ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
            <ChatHome
              me={me}
              active={inChat}
              missions={missions}
              courses={courses}
              ready={ready}
              loadFailed={failed}
              showAudit={inChat && pane === "audit"}
              onOpenView={setView}
              onTurn={refresh}
            />
          </div>

          {!inChat ? (
            <div className="nx-scroll min-h-0 flex-1 overflow-auto">
              <div className="mx-auto w-full max-w-[920px] px-4 py-6 sm:px-6">
                {view === "intake" ? (
                  <IntakeView onOpenView={setView} />
                ) : view === "decoder" ? (
                  <DecoderView onOpenPlanner={() => setView("planner")} />
                ) : view === "mission" ? (
                  <MissionView onOpenPlanner={() => setView("planner")} />
                ) : view === "sequence" ? (
                  <SequenceView onOpenPlanner={() => setView("planner")} />
                ) : view === "dashboard" && me.student_id ? (
                  <StudentView studentId={me.student_id} />
                ) : (
                  <PlannerView />
                )}
              </div>
            </div>
          ) : null}
        </main>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

/**
 * One row of a status list: a dot, what it is, where it came from, and the value. The dot
 * is decoration; the value on the right is the same statement in words, because a 7px
 * circle is exactly the kind of colour-only signal this product does not ship.
 */
function StatusRow({ tone = "neutral", label, meta, value }) {
  return (
    <div className="flex items-center gap-3 bg-card px-3.5 py-2.5">
      <span className={`nx-dot nx-dot--${tone}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="text-body leading-snug">{label}</div>
        {meta ? <div className="text-micro text-subtle">{meta}</div> : null}
      </div>
      {value ? (
        <span className="shrink-0 text-right text-xs text-muted-foreground">{value}</span>
      ) : null}
    </div>
  )
}

function RowGroup({ children }) {
  return (
    /* `flex-none` is load-bearing: the rail is a flex column so its disclaimer can sit at
       the bottom, and without this a five-row group gets squeezed to the height of one. */
    <div className="flex flex-none flex-col gap-px overflow-hidden rounded-md bg-border">
      {children}
    </div>
  )
}

/**
 * The left rail: registration readiness first, then the way to every full page, then the
 * one sentence this portfolio project owes every screen. Readiness is re-read from the
 * server on each view change, never held from a previous turn.
 */
function Rail({ mission, courseCount, ready, failed, onRetry, view, nav, onOpenView }) {
  const done = mission ? mission.steps.filter((s) => s.state === "done").length : 0
  const blockers = mission?.open_blockers ?? []
  const active = mission?.steps.find((s) => s.state === "active")

  return (
    <aside
      className="nx-scroll flex max-h-[40vh] w-full flex-none flex-col overflow-auto border-b border-border px-4 py-5 md:max-h-none md:w-[clamp(280px,30%,420px)] md:border-r md:border-b-0 md:px-5"
      aria-label="Registration readiness and tools"
    >
      <div className="mb-3.5 nx-label">
        {mission ? `Registration readiness · ${mission.term}` : "Your record"}
      </div>

      {failed ? (
        <>
          <RowGroup>
            <StatusRow
              tone="danger"
              label="Couldn't read your record"
              meta="A failed read, not an empty record — nothing here is known right now."
              value="Action required"
            />
          </RowGroup>
          <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
            Retry reading your record
          </Button>
        </>
      ) : !ready ? (
        <p className="text-body text-muted-foreground">Reading your record…</p>
      ) : mission ? (
        <>
          <div className="mb-4 rounded-lg border border-border bg-card p-4">
            <div className="flex flex-wrap items-center gap-2.5">
              {/* The one statement on the screen: the answer to "am I ready to register?" */}
              <span className="nx-statement text-display">
                {blockers.length > 0 ? "Blocked" : mission.complete ? "Ready" : "In progress"}
              </span>
              <span
                className={`rounded border px-2 py-0.5 text-micro ${
                  blockers.length > 0
                    ? "border-destructive text-destructive"
                    : "border-primary text-primary"
                }`}
              >
                {blockers.length > 0
                  ? `${blockers.length} blocker${blockers.length === 1 ? "" : "s"} · action required`
                  : `${done} of ${mission.steps.length} steps done`}
              </span>
            </div>
            {active?.what_now ? (
              <p className="mt-2 text-body leading-relaxed text-muted-foreground">
                Next: {active.what_now}
              </p>
            ) : null}
          </div>

          <RowGroup>
            {mission.steps.map((step) => (
              <StatusRow
                key={step.id}
                tone={
                  step.state === "done" ? "good" : step.state === "active" ? "warn" : "neutral"
                }
                label={step.title}
                meta={step.criterion}
                value={
                  step.state === "done" ? "Done" : step.state === "active" ? "Now" : "Waiting"
                }
              />
            ))}
          </RowGroup>

          {blockers.length > 0 ? (
            <>
              <div className="mt-5 mb-2.5 nx-label">
                In the way
              </div>
              <RowGroup>
                {blockers.map((b) => (
                  <StatusRow key={b.key} tone="danger" label={b.summary} meta={b.next_step} />
                ))}
              </RowGroup>
            </>
          ) : null}
        </>
      ) : (
        <p className="text-body leading-relaxed text-muted-foreground">
          {courseCount > 0
            ? `${courseCount} course${courseCount === 1 ? "" : "s"} in your record and no open registration mission. Ask about your degree, or start preparing for a term.`
            : "Nothing in your record yet. Ask about a registration error — that needs nothing set up — or add your courses from a transcript."}
        </p>
      )}

      <p className="mt-4 text-meta leading-relaxed text-subtle">
        Recomputed on every read. Your completed courses are self-reported — UAX cannot see
        Albert.
      </p>

      <div className="mt-6 mb-2 nx-label">
        Records &amp; tools
      </div>
      <nav aria-label="Records and tools">
        <div className="flex flex-col gap-0.5">
          {nav.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-current={view === id ? "page" : undefined}
              onClick={() => onOpenView(id)}
              className={`rounded-md px-2.5 py-1.5 text-left text-body transition-colors ${
                view === id
                  ? "text-primary shadow-[inset_0_0_0_1px_var(--accent)]"
                  : "text-muted-foreground hover:bg-secondary"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>

      {/* Anchored to the foot of the rail rather than trailing the nav, so the space under
          a short record reads as a margin instead of the column having stopped. */}
      <p className="mt-auto border-t border-border pt-4 text-micro leading-relaxed text-subtle">
        Personal portfolio project. All students, records, and policies are fictional or
        quoted from public NYU bulletins with source links. Not an official NYU system —
        Albert is always authoritative.
      </p>
    </aside>
  )
}
