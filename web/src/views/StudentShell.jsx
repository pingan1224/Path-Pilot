import { useCallback, useEffect, useMemo, useState } from "react"
import { api } from "@/api"
import { ProgramNotice } from "@/components/nocturne"
import { Button } from "@/components/ui/button"
import ChatHome from "./ChatHome"
import DecoderView from "./DecoderView"
import IntakeView from "./IntakeView"
import MissionView from "./MissionView"
import PlannerView from "./PlannerView"
import ProgramView from "./ProgramView"
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
  ["program", "Your program"],
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

// The view lives in the URL, by hand. Each tool page is a path (`/mission`, `/decoder`);
// the chat, being the app rather than a drawer of it, is `/`. Anything else — `/demo`
// left over from the door, a stale bookmark — lands on the chat instead of a blank frame.
// A router library would buy back exactly this function plus pushState, priced at a
// dependency; see the same call in App.jsx about the login doors.
const VIEW_PATHS = [
  "intake",
  "decoder",
  "mission",
  "sequence",
  "planner",
  "program",
  "dashboard",
]

function viewFromLocation() {
  const segment = window.location.pathname.split("/").filter(Boolean)[0] ?? ""
  return VIEW_PATHS.includes(segment) ? segment : "chat"
}

export default function StudentShell({ me, onSignOut }) {
  const [view, setViewState] = useState(viewFromLocation)
  const [pane, setPane] = useState("drawer")

  // Chosen views push history so the browser's Back walks out of a tool page instead of
  // out of the app; arriving by Back/Forward only syncs state, or every pop would push
  // the entry it just left.
  const setView = useCallback((next) => {
    setViewState(next)
    const path = next === "chat" ? "/" : `/${next}`
    if (window.location.pathname !== path) window.history.pushState(null, "", path)
  }, [])

  useEffect(() => {
    const onPop = () => setViewState(viewFromLocation())
    window.addEventListener("popstate", onPop)
    return () => window.removeEventListener("popstate", onPop)
  }, [])
  const [missions, setMissions] = useState(null)
  const [courses, setCourses] = useState(null)
  // null means "not stated yet", which is a real answer and not a failure — it is what a
  // new account looks like, and the rail says so rather than showing nothing.
  const [program, setProgram] = useState(null)

  const refresh = useCallback(() => {
    api.missions().then(setMissions).catch(() => setMissions(LOAD_FAILED))
    api.profileCourses().then(setCourses).catch(() => setCourses(LOAD_FAILED))
    api
      .program()
      .then(setProgram)
      .catch((err) =>
        setProgram(err.code === "program_not_stated" ? null : LOAD_FAILED),
      )
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

  const nav = useMemo(
    () => (me.student_id ? [...NAV, ["dashboard", "Dashboard (demo)"]] : NAV),
    [me.student_id],
  )

  // A deep-linkable page deserves a nameable tab. The chat keeps the product name — it
  // is the app, not a section of it.
  useEffect(() => {
    const label = nav.find(([id]) => id === view)?.[1]
    document.title =
      view === "chat" || !label ? "Path Pilot" : `${label} · Path Pilot`
  }, [nav, view])

  // Unmounting means signed out: the sign-in page must not sit under a tool's title any
  // more than under its path.
  useEffect(
    () => () => {
      document.title = "Path Pilot"
    },
    [],
  )

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <a className="skip" href="#main">
        Skip to content
      </a>

      <header className="flex flex-none flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-2.5 sm:px-5">
        <div className="flex items-baseline gap-2">
          <span className="nx-statement text-title">Path Pilot</span>
          <span className="hidden nx-label sm:inline">Registration readiness</span>
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
                  className={`rounded-md px-2.5 py-2 text-meta transition-colors md:py-1 ${
                    pane === id
                      ? "bg-accent font-medium text-accent-foreground"
                      : "text-muted-foreground hover:bg-secondary active:bg-secondary/70"
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
            program={program === LOAD_FAILED ? null : program}
            programUnknown={program === null}
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
              railVisible={railVisible}
              onOpenView={setView}
              onTurn={refresh}
            />
          </div>

          {!inChat ? (
            <div className="nx-scroll min-h-0 flex-1 overflow-auto">
              {/* Keyed so switching tools re-runs the arrival — the same movement a
                  message makes when it enters the thread. One kind of change, one
                  animation. The chat pane is exempt: it is revealed, not re-created,
                  because remounting it would cost the conversation. */}
              <div key={view} className="nx-view mx-auto w-full max-w-[920px] px-4 py-6 sm:px-6">
                {view === "intake" ? (
                  <IntakeView onOpenView={setView} />
                ) : view === "decoder" ? (
                  <DecoderView onOpenPlanner={() => setView("planner")} />
                ) : view === "mission" ? (
                  // Intercepted here rather than inside the view: `GET /missions` succeeds
                  // with an empty list for an unencoded program, so the view would offer to
                  // start one and only refuse after the student picked a term. Every step
                  // of a mission is computed from the program's requirements, so without
                  // them there is nothing to invite anyone into.
                  program && !program.is_encoded ? (
                    <ProgramNotice
                      code="program_not_encoded"
                      message={`Path Pilot has not transcribed the degree requirements for ${program.program_name}, so it cannot track a registration mission for it. Policy answers and registration error decoding still work for your program.`}
                      onChooseProgram={() => setView("program")}
                    />
                  ) : (
                    <MissionView
                      onOpenPlanner={() => setView("planner")}
                      onOpenProgram={() => setView("program")}
                    />
                  )
                ) : view === "sequence" ? (
                  <SequenceView
                    onOpenPlanner={() => setView("planner")}
                    onOpenProgram={() => setView("program")}
                  />
                ) : view === "program" ? (
                  <ProgramView
                    current={program === LOAD_FAILED ? null : program}
                    onChanged={async (updated) => {
                      setProgram(updated)
                      // The rail and every tool page read requirements for this program,
                      // so re-read rather than patching state locally.
                      refresh()
                    }}
                  />
                ) : view === "dashboard" && me.student_id ? (
                  <StudentView studentId={me.student_id} />
                ) : (
                  <PlannerView onOpenProgram={() => setView("program")} />
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
function Rail({
  mission,
  courseCount,
  ready,
  failed,
  onRetry,
  view,
  nav,
  onOpenView,
  program,
  programUnknown,
}) {
  const done = mission ? mission.steps.filter((s) => s.state === "done").length : 0
  const blockers = mission?.open_blockers ?? []
  const active = mission?.steps.find((s) => s.state === "active")

  return (
    /* Two zones, and only the top one scrolls.
       The rail used to be a single scrolling column with the tool nav at its foot. On a
       900px window a five-step mission overflows it, so clicking a tool scrolled the
       focused button into view and took the readiness state — the answer to the question
       this product exists for — off the top of the screen. Splitting them means status
       can be as long as it needs to be, and choosing a tool never hides where you stand. */
    <aside
      className="flex max-h-[40vh] w-full flex-none flex-col border-b border-border bg-well md:max-h-none md:w-[clamp(280px,30%,420px)] md:border-r md:border-b-0"
      aria-label="Registration readiness and tools"
    >
      <div className="nx-scroll min-h-0 flex-1 overflow-auto px-4 pt-5 pb-4 md:px-5">
      <div className="mb-3.5 nx-label">
        {mission ? `Registration readiness · ${mission.term}` : "Your record"}
      </div>

      {/* The program sits above readiness because it decides what readiness can even
          mean: three of the six tools evaluate rules that belong to one program, and
          without it they refuse. An unset program is "Action required" in words, not a
          coloured dot — the same rule every other state on this rail follows. */}
      {programUnknown ? (
        <div className="mb-3.5">
          <RowGroup>
            <StatusRow
              tone="warn"
              label="Tell us your program"
              meta="Degree progress, sequencing and missions need to know which rules apply to you."
              value="Action required"
            />
          </RowGroup>
          <Button
            variant="outline"
            size="sm"
            className="mt-2 w-full"
            onClick={() => onOpenView("program")}
          >
            Choose your program
          </Button>
        </div>
      ) : program ? (
        <div className="mb-3.5">
          <RowGroup>
            <StatusRow
              tone={program.is_encoded ? "good" : "warn"}
              label={program.program_name}
              meta={
                program.is_encoded
                  ? "Requirements encoded — degree progress available"
                  : "Requirements not encoded — policy answers and error decoding only"
              }
              value={program.is_encoded ? "Full support" : "Limited"}
            />
          </RowGroup>
        </div>
      ) : null}

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
        Recomputed on every read. Your completed courses are self-reported — Path Pilot cannot see
        Albert.
      </p>
      </div>

      {/* Kept deliberately tight. This is the way *out* of the current task, not the task;
          before it was trimmed it stood at 374px against the readiness zone's 472px, which
          is most of a column spent on secondary navigation. */}
      <div className="flex-none border-t border-border px-4 pt-3.5 pb-4 md:px-5">
        <div className="mb-1.5 nx-label">Records &amp; tools</div>
        <nav aria-label="Records and tools">
          <div className="flex flex-col">
            {nav.map(([id, label]) => (
              <button
                key={id}
                type="button"
                aria-current={view === id ? "page" : undefined}
                onClick={() => onOpenView(id)}
                /* Roomy for a thumb, tight for a cursor: the rail is a drawer on a phone
                   where these are touch targets, and a contested column on a desktop
                   where they are not.

                   Selected = a chip lifted off the well: fill, ink and weight all say it,
                   because the rail's left edge belongs to the verdict system and a lone
                   ring reads as an outline, not a place. */
                className={`flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left text-body transition-colors md:py-1 md:text-meta ${
                  view === id
                    ? "bg-card font-medium text-primary shadow-xs"
                    : "text-muted-foreground hover:bg-card/60 active:bg-card"
                }`}
              >
                {label}
                {/* The one nav entry with live state gets it, in words and figures — not
                    an icon. "blocked" outranks the count because a blocked mission's step
                    tally is not the news. */}
                {id === "mission" && mission ? (
                  <span
                    className={`nx-figure text-micro ${
                      blockers.length > 0 ? "text-destructive" : "text-subtle"
                    }`}
                  >
                    {blockers.length > 0
                      ? "blocked"
                      : `${done}/${mission.steps.length}`}
                  </span>
                ) : null}
              </button>
            ))}
          </div>
        </nav>

        {/* Two claims, and both have to survive being skimmed: this is not NYU, and the
            student data is invented while the policy text is really NYU's. */}
        <p className="mt-3 text-micro leading-relaxed text-subtle">
          Personal portfolio project — not an official NYU system. Students and records are
          fictional; policy text is quoted from public NYU bulletins with source links.
        </p>
      </div>
    </aside>
  )
}
