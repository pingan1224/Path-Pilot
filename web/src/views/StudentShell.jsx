import { useCallback, useEffect, useState } from "react"
import { api } from "@/api"
import AmbientBg from "@/components/AmbientBg"
import CommandPalette from "@/components/CommandPalette"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import MakeSidebar from "@/components/MakeSidebar"
import { ProgramNotice } from "@/components/nocturne"
import { usePrefs } from "@/i18n"
import ChatHome from "./ChatHome"
import DecoderView from "./DecoderView"
import IntakeView from "./IntakeView"
import MissionView from "./MissionView"
import PlannerView from "./PlannerView"
import ProgramView from "./ProgramView"
import SequenceView from "./SequenceView"
import StudentView from "./StudentView"

/**
 * The student app frame, in the source design's own shape (1:1 branch): a w-64 sidebar
 * owns brand, program, nav and preferences; the view fills the rest; ambient blobs
 * drift behind everything in dark; ⌘K opens the palette. The top header is gone — the
 * design has none, and everything it carried moved into the sidebar.
 *
 * What stayed PathPilot's regardless of the design:
 * - Views live in the URL and the browser's Back walks out of a tool page.
 * - The chat is hidden, not unmounted, when a tool page is open — the thread survives.
 * - Data is recomputed on every view change, and a failed read is a failed read: every
 *   live sidebar figure falls back to a static description rather than claiming empty.
 * - decoder / program / dashboard render inside this frame from deep links and in-app
 *   openers even though the design's nav has no slot for them.
 */

// A failed read is its own state, never an empty array: rendering [] as "nothing in
// your record" would dress a dead API as an empty record — the silent failure rule 6
// forbids. "No access" is not "no results".
const LOAD_FAILED = Symbol("load failed")

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
  const { t } = usePrefs()
  const [view, setViewState] = useState(viewFromLocation)
  const [cmdOpen, setCmdOpen] = useState(false)

  // Chosen views push history so Back walks out of a tool page instead of out of the
  // app; arriving by Back/Forward only syncs state, or every pop would push the entry
  // it just left.
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

  // ⌘K / Ctrl+K — the design's palette hotkey.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        setCmdOpen((o) => !o)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const [missions, setMissions] = useState(null)
  const [courses, setCourses] = useState(null)
  // null means "not stated yet", a real answer — what a new account looks like.
  const [program, setProgram] = useState(null)
  // Feeds the Degree-progress sub-line; null is "no live figure" (an unset program
  // 409s here) and the nav falls back to the static description.
  const [plan, setPlan] = useState(null)

  const refresh = useCallback(() => {
    api.missions().then(setMissions).catch(() => setMissions(LOAD_FAILED))
    api.profileCourses().then(setCourses).catch(() => setCourses(LOAD_FAILED))
    api
      .program()
      .then(setProgram)
      .catch((err) =>
        setProgram(err.code === "program_not_stated" ? null : LOAD_FAILED),
      )
    api.plan(false).then(setPlan).catch(() => setPlan(null))
  }, [])

  // On mount and on every view change: the tool pages write exactly the state the
  // sidebar's live figures show.
  useEffect(refresh, [refresh, view])

  // `program` is one of three things: a program object, null ("not stated yet", which is
  // a real answer and what a new account looks like), or the LOAD_FAILED sentinel. Only
  // the object can say anything about encoding, and the sentinel is truthy — so testing
  // `program && !program.is_encoded` read a failed fetch as "your degree is not encoded"
  // and printed `undefined` where the name goes. Derive the three cases once, here.
  const programFailed = program === LOAD_FAILED
  const programUnknown = program === null
  const programUnencoded = !programFailed && !programUnknown && !program.is_encoded

  const failed = missions === LOAD_FAILED || courses === LOAD_FAILED || programFailed
  const ready = Array.isArray(missions) && Array.isArray(courses)
  // Prefer a mission still in progress, but fall back to the newest one rather than to
  // nothing. Selecting only on `!complete` made `mission.complete` false by construction,
  // so the "Ready · <term>" sub-line below was unreachable and a student who finished
  // their only mission watched the whole mission card disappear from the rail — the one
  // moment the product exists to confirm, rendering as if nothing had ever been started.
  // `open_missions` already excludes closed ones and returns newest first.
  const mission = ready ? (missions.find((m) => !m.complete) ?? missions[0] ?? null) : null
  const blockers = mission?.open_blockers ?? []
  const inChat = view === "chat"

  /** The live sub-lines, shared by the sidebar and the palette. A failed or unfinished
   *  fetch asserts nothing: every slot falls back to its static description. */
  const subFor = (id) => {
    if (!ready || failed) return t(`nav.${id}.sub`)
    switch (id) {
      case "planner":
        return plan?.credits_required
          ? t("nav.planner.sub.live", {
              done: plan.credits_completed,
              total: plan.credits_required,
            })
          : t("nav.planner.sub")
      case "mission": {
        if (!mission) return t("nav.mission.sub")
        if (blockers.length > 0)
          return t("nav.mission.sub.blocked", { count: blockers.length })
        if (mission.complete) return t("nav.mission.sub.ready", { term: mission.term })
        const activeIndex = mission.steps.findIndex((s) => s.state === "active")
        const done = mission.steps.filter((s) => s.state === "done").length
        const step =
          activeIndex >= 0 ? activeIndex + 1 : Math.min(done + 1, mission.steps.length)
        return t("nav.mission.sub.step", {
          step,
          total: mission.steps.length,
          term: mission.term,
        })
      }
      case "intake":
        return t("nav.intake.sub.live", { count: courses.length })
      case "sequence":
        return mission
          ? t("nav.sequence.sub.live", { term: mission.term })
          : t("nav.sequence.sub")
      default:
        return t(`nav.${id}.sub`)
    }
  }
  const subs = Object.fromEntries(
    ["chat", "planner", "mission", "intake", "sequence"].map((id) => [id, subFor(id)]),
  )

  // A deep-linkable page deserves a nameable tab; the chat keeps the product name.
  useEffect(() => {
    document.title = view === "chat" ? "Path Pilot" : `${t(`nav.${view}`)} · Path Pilot`
  }, [view, t])
  useEffect(
    () => () => {
      document.title = "Path Pilot"
    },
    [],
  )

  return (
    <div
      className="relative flex h-dvh flex-col overflow-hidden md:flex-row"
      style={{ background: "var(--color-canvas)" }}
    >
      <a className="skip" href="#main">
        {t("shell.skip")}
      </a>
      <AmbientBg />

      <div className="relative flex h-full w-full min-h-0 flex-col md:flex-row" style={{ zIndex: 1 }}>
        <MakeSidebar
          view={view}
          onNavigate={setView}
          me={me}
          onSignOut={onSignOut}
          program={programFailed ? null : program}
          programUnknown={programUnknown}
          programFailed={programFailed}
          mission={mission}
          blockers={blockers}
          subs={subs}
          onOpenProgram={() => setView("program")}
        />

        <main id="main" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {/* The failed strip — real state the design never drew. */}
          {failed ? (
            <div
              className="mx-4 mt-3 flex-none rounded-xl px-4 py-2.5"
              style={{
                background: "var(--color-rose-muted)",
                border: "1px solid rgba(190,18,60,0.2)",
              }}
            >
              <span className="text-[12px] font-semibold" style={{ color: "var(--color-rose)" }}>
                {t("rail.failed")}
              </span>{" "}
              <span className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                {t("rail.failed.meta")}
              </span>
              <button
                type="button"
                onClick={refresh}
                className="ml-2 rounded px-2 py-0.5 text-[11px] font-medium"
                style={{
                  background: "var(--color-surface-2)",
                  color: "var(--color-ink-2)",
                  border: "1px solid var(--color-rail-strong)",
                }}
              >
                {t("rail.failed.retry")}
              </button>
            </div>
          ) : null}

          {/* Two boundaries, one per pane, not one around both.
              A single boundary renders its fallback *instead of* its children, so a throw
              anywhere under it unmounted the chat as well — and the thread is local state,
              so the conversation went with it. It failed in both directions: a fault in
              the hidden chat replaced the tool page the student was actually looking at,
              and `resetKey` could not clear that, because navigating re-rendered the same
              throwing chat and re-latched immediately.
              Scoped to the panes rather than the shell either way: a screen that throws
              leaves the sidebar standing, so the way out is a click, not a refresh. */}
          {/* `hidden`, not unmount: the thread survives a trip to a tool page. */}
          <div className={inChat ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
            <ErrorBoundary>
              <ChatHome
                me={me}
                active={inChat}
                missions={missions}
                courses={courses}
                ready={ready}
                loadFailed={failed}
                onOpenView={setView}
                onTurn={refresh}
              />
            </ErrorBoundary>
          </div>

          {!inChat ? (
          <ErrorBoundary resetKey={view}>
            {/* Keyed so switching tools re-runs the design's page-enter. The chat pane is
                exempt: it is revealed, not re-created. Views not yet rebuilt to the
                design's own full-height layouts ride in a scroll container the old shell
                used to provide. */}
            <div key={view} className="pp-page-enter min-h-0 flex-1 overflow-hidden">
              {/* Views rebuilt to the design's full-height layouts own their scroll;
                  the rest ride in the scroll container the old shell used to provide. */}
              {view === "mission" && !programUnencoded ? (
                <MissionView
                  onOpenPlanner={() => setView("planner")}
                  onOpenProgram={() => setView("program")}
                />
              ) : view === "planner" ? (
                <PlannerView
                  onOpenProgram={() => setView("program")}
                  onOpenMission={() => setView("mission")}
                />
              ) : view === "sequence" ? (
                <SequenceView
                  onOpenPlanner={() => setView("planner")}
                  onOpenProgram={() => setView("program")}
                />
              ) : (
              <div className="nx-scroll h-full overflow-y-auto">
                <div className="mx-auto w-full max-w-[920px] px-4 py-6 sm:px-6">
                  {view === "intake" ? (
                    <IntakeView onOpenView={setView} />
                  ) : view === "decoder" ? (
                    <DecoderView onOpenPlanner={() => setView("planner")} />
                  ) : view === "mission" ? (
                    <ProgramNotice
                      code="program_not_encoded"
                      message={`Path Pilot has not transcribed the degree requirements for ${program?.program_name}, so it cannot track a registration mission for it. Policy answers and registration error decoding still work for your program.`}
                      onChooseProgram={() => setView("program")}
                    />
                  ) : view === "program" ? (
                    <ProgramView
                      current={programFailed ? null : program}
                      onChanged={async (updated) => {
                        setProgram(updated)
                        refresh()
                      }}
                    />
                  ) : view === "dashboard" && me.student_id ? (
                    <StudentView studentId={me.student_id} />
                  ) : (
                    <PlannerView
                  onOpenProgram={() => setView("program")}
                  onOpenMission={() => setView("mission")}
                />
                  )}
                </div>
              </div>
              )}
            </div>
          </ErrorBoundary>
          ) : null}
        </main>
      </div>

      <CommandPalette
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        onNavigate={setView}
        subs={subs}
      />
    </div>
  )
}
