import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import {
  BarChart2,
  CalendarRange,
  CheckSquare,
  ChevronRight,
  Compass,
  FileText,
  MessageSquare,
} from "lucide-react"
import { api } from "@/api"
import { ProgramNotice } from "@/components/nocturne"
import { Button } from "@/components/ui/button"
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

// Five slots, in the order a student's question unfolds: ask → where do I stand → get
// ready → what the record holds → the terms ahead. This was eight; the three that left
// did not lose their function, they lost a *permanent* slot they were duplicating:
//   decoder   — the chat is its entry (paste the error text; the empty-record greeting
//               leads with a decoder question), and /decoder still deep-links for the
//               read-the-classification-myself path.
//   program   — the enrolled-program chip above the nav *is* the program surface;
//               clicking it opens the picker.
//   dashboard — the pre-shell demo overview; deep-link only.
// Ids only — labels and live sub-lines come from the dictionary at render time.
const NAV = ["chat", "planner", "mission", "intake", "sequence"]

// Icons name the tool's *input or output*, not an abstraction: progress is a bar chart,
// a transcript is a file, the sequence is a span of terms. The icon never carries the
// meaning alone — the two-line label next to it does.
const NAV_ICON = {
  chat: MessageSquare,
  planner: BarChart2,
  mission: CheckSquare,
  intake: FileText,
  sequence: CalendarRange,
}

const PANES = ["drawer", "focused", "audit"]

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
  const { t } = usePrefs()
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
  // Feeds the Degree-progress sub-line ("21 / 36 credits"). null is "no live figure" —
  // an unset program 409s here, and the nav falls back to the static description rather
  // than inventing a number.
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

  // A deep-linkable page deserves a nameable tab whether or not it holds a nav slot —
  // every view keeps its label key. The chat keeps the product name; it is the app,
  // not a section of it.
  useEffect(() => {
    document.title = view === "chat" ? "Path Pilot" : `${t(`nav.${view}`)} · Path Pilot`
  }, [view, t])

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
        {t("shell.skip")}
      </a>

      <header className="flex flex-none flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-2.5 sm:px-5">
        <div className="flex items-baseline gap-2">
          <span className="nx-statement text-title">{t("app.name")}</span>
          <span className="hidden nx-label sm:inline">{t("app.tagline")}</span>
        </div>

        <div className="mx-auto">
          {inChat ? (
            <div
              className="flex gap-1 rounded-[10px] border border-border p-[3px]"
              role="group"
              aria-label={t("pane.label")}
            >
              {PANES.map((id) => (
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
                  {t(`pane.${id}`)}
                </button>
              ))}
            </div>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setView("chat")}>
              {t("shell.back")}
            </Button>
          )}
        </div>

        <div className="flex items-center gap-3">
          <PrefsControls />
          <div className="text-right">
            <div className="text-body leading-tight">{me.full_name}</div>
            <div className="text-micro text-subtle">
              {me.student_number ?? me.role}
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={onSignOut}>
            {t("shell.signout")}
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
            onOpenView={setView}
            program={program === LOAD_FAILED ? null : program}
            programUnknown={program === null}
            plan={plan}
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
 * Theme and language, as two segmented switches — the control shape the source design
 * carries in its sidebar footer, relocated to the header because this shell's rail is
 * hideable ("Conversation only") and a preference control must not vanish with it.
 *
 * Theme is three segments, not the design's two: `auto` is the state where the
 * `prefers-color-scheme` block decides, and dropping it would silently disable the OS
 * preference — see the note in i18n/index.jsx. Each segment says its name in words;
 * `aria-pressed` carries the state.
 */
function PrefsControls() {
  const { locale, setLocale, theme, setTheme, t } = usePrefs()

  const segment = (active) =>
    `rounded-md px-2 py-1 text-micro font-medium transition-colors ${
      active
        ? "bg-card text-foreground shadow-xs"
        : "text-subtle hover:text-muted-foreground"
    }`

  return (
    <div className="hidden items-center gap-1.5 sm:flex">
      <div
        className="flex gap-0.5 rounded-lg border border-border bg-secondary p-0.5"
        role="group"
        aria-label={t("prefs.theme")}
      >
        {["auto", "light", "dark"].map((id) => (
          <button
            key={id}
            type="button"
            aria-pressed={theme === id}
            onClick={() => setTheme(id)}
            className={segment(theme === id)}
          >
            {t(`prefs.theme.${id}`)}
          </button>
        ))}
      </div>
      <div
        className="flex gap-0.5 rounded-lg border border-border bg-secondary p-0.5"
        role="group"
        aria-label={t("prefs.lang")}
      >
        {[
          ["en", "EN"],
          ["zh", "中文"],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={locale === id}
            onClick={() => setLocale(id)}
            className={segment(locale === id)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}

/**
 * The left rail, and the nav *is* the dashboard: five slots whose sub-lines are live
 * state — credits standing, mission step, record size — recomputed on every read like
 * everything else. The detail those figures summarise lives one click away in the full
 * pages; the rail stopped duplicating it. Where registration stands is still answered
 * at rest, just at nav altitude: the mission slot's sub-line goes red and says
 * "Blocked · N" the moment it is true.
 */
function Rail({
  mission,
  courseCount,
  ready,
  failed,
  onRetry,
  view,
  onOpenView,
  program,
  programUnknown,
  plan,
}) {
  const { t, locale } = usePrefs()
  const done = mission ? mission.steps.filter((s) => s.state === "done").length : 0
  const blockers = mission?.open_blockers ?? []
  const activeIndex = mission ? mission.steps.findIndex((s) => s.state === "active") : -1

  /** One slot's live sub-line. A failed or unfinished fetch asserts nothing: every slot
   *  falls back to its static description, and the failed strip above the nav says why —
   *  "no access" must never render as "no results". */
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
        if (blockers.length > 0) return t("nav.mission.sub.blocked", { count: blockers.length })
        if (mission.complete) return t("nav.mission.sub.ready", { term: mission.term })
        const step = activeIndex >= 0 ? activeIndex + 1 : Math.min(done + 1, mission.steps.length)
        return t("nav.mission.sub.step", {
          step,
          total: mission.steps.length,
          term: mission.term,
        })
      }
      case "intake":
        return t("nav.intake.sub.live", { count: courseCount })
      case "sequence":
        return mission
          ? t("nav.sequence.sub.live", { term: mission.term })
          : t("nav.sequence.sub")
      default:
        return t(`nav.${id}.sub`)
    }
  }

  // A slot whose live figure just *changed* settles (the accent edge, 1s) — the
  // recompute made news, and nx-settle is the vocabulary word for exactly that. Guards,
  // in order: the first read is arrival, not news; a locale flip rewrites every string
  // without any fact changing; and a fetch that failed reports nothing. Comparison is
  // per slot on the rendered string, so a mission moving settles the mission slot and
  // leaves the other four still.
  //
  // The changed set is *state* with a timed clear, not a value computed during render:
  // a refresh lands as three fetches settling separately, so the render after the one
  // that spotted the change arrives within milliseconds — a class that lives only for
  // the spotting render is removed mid-animation and the settle never visibly fires.
  const subs = NAV.map((id) => subFor(id))
  const [settled, setSettled] = useState(() => new Set())
  const prevSubs = useRef(null)
  const prevLocale = useRef(locale)
  const settleTimer = useRef(null)
  useEffect(() => {
    const fresh =
      prevSubs.current === null || prevLocale.current !== locale || !ready || failed
    const changed = fresh
      ? []
      : NAV.filter((id, i) => prevSubs.current[i] !== subs[i])
    prevSubs.current = subs
    prevLocale.current = locale
    if (changed.length > 0) {
      setSettled(new Set(changed))
      clearTimeout(settleTimer.current)
      // Past the animation's 1s: removing the class then swaps one settled end state
      // for another, invisibly. Clearing earlier truncates the mark it exists to make.
      settleTimer.current = setTimeout(() => setSettled(new Set()), 1100)
    }
  })
  useEffect(() => () => clearTimeout(settleTimer.current), [])

  // The shared nav marker. Measured, not styled per item: one tinted block travels to
  // the active tool (.nx-nav-slider owns the motion). Re-measured when the locale flips
  // — labels change length, and with them every item's offset. On a view without a nav
  // slot (decoder, program, dashboard) the marker fades out rather than squatting on
  // whichever slot was last active.
  const itemRefs = useRef(new Map())
  const sliderRef = useRef(null)
  const sliderSettled = useRef(false)
  useLayoutEffect(() => {
    const slider = sliderRef.current
    if (!slider) return
    const el = itemRefs.current.get(view)
    if (!el) {
      slider.style.opacity = "0"
      return
    }
    slider.style.opacity = "1"
    if (!sliderSettled.current) {
      // First paint lands in place; travel is for changes the student just made.
      slider.style.transition = "none"
    }
    slider.style.transform = `translateY(${el.offsetTop}px)`
    slider.style.height = `${el.offsetHeight}px`
    if (!sliderSettled.current) {
      sliderSettled.current = true
      // Reflow commits the jump before the class transition comes back.
      void slider.offsetHeight
      slider.style.transition = ""
    }
  }, [view, locale])

  return (
    /* Two zones, and only the top one scrolls.
       The rail used to be a single scrolling column with the tool nav at its foot. On a
       900px window a five-step mission overflows it, so clicking a tool scrolled the
       focused button into view and took the readiness state — the answer to the question
       this product exists for — off the top of the screen. Splitting them means status
       can be as long as it needs to be, and choosing a tool never hides where you stand. */
    <aside
      className="flex max-h-[40vh] w-full flex-none flex-col border-b border-border bg-well md:max-h-none md:w-[clamp(280px,30%,420px)] md:border-r md:border-b-0"
      aria-label={t("rail.aria")}
    >
      {/* Brand block — the design's anchor: a filled tile, the name, one quiet line.
          Desktop only: on a phone the rail is a 40vh drawer and the header already
          carries the name; spending drawer height restating it helps nobody. */}
      <div
        className="hidden flex-none items-center gap-2.5 border-b border-border px-4 pt-4 pb-3.5 md:flex md:px-5"
        aria-hidden="true"
      >
        <div
          className="grid size-9 flex-none place-items-center rounded-xl text-cta-foreground"
          style={{ background: "linear-gradient(135deg, var(--accent), var(--accent-fill))" }}
        >
          <Compass size={16} />
        </div>
        <div className="min-w-0">
          <div className="nx-statement text-body leading-tight">{t("app.name")}</div>
          <div className="mt-0.5 text-micro leading-none text-subtle">{t("app.tagline")}</div>
        </div>
      </div>

      {/* The program chip — and since the program tool left the nav, the chip *is* the
          program surface: clicking it opens the picker, and it reads aria-current when
          that page is open. The support badge is words, not a coloured dot, like every
          other state on this rail. The design's mouse-tracking spotlight is deliberately
          not reproduced: the motion contract bans animation that carries no meaning. */}
      <div className="flex-none border-b border-border px-4 py-3 md:px-5">
        <div className="nx-label mb-1.5">{t("rail.program.eyebrow")}</div>
        {programUnknown ? (
          <div className="rounded-lg border border-border bg-card px-3 py-2.5">
            <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
              <span className="text-body leading-snug">{t("rail.program.unset")}</span>
              <span className="rounded bg-warning-soft px-1.5 py-0.5 text-micro font-medium text-warning">
                {t("rail.program.unset.action")}
              </span>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mt-2 w-full"
              onClick={() => onOpenView("program")}
            >
              {t("rail.program.choose")}
            </Button>
          </div>
        ) : program ? (
          <button
            type="button"
            onClick={() => onOpenView("program")}
            aria-current={view === "program" ? "page" : undefined}
            title={t("rail.program.open")}
            className={`w-full rounded-lg border bg-card px-3 py-2.5 text-left transition-colors duration-(--motion-fast) hover:border-primary/40 ${
              view === "program" ? "border-primary/50" : "border-border"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 flex-1 text-body leading-snug">
                {program.program_name}
              </span>
              <span
                className={`rounded px-1.5 py-0.5 text-micro font-medium ${
                  program.is_encoded
                    ? "bg-success-soft text-success"
                    : "bg-warning-soft text-warning"
                }`}
              >
                {program.is_encoded ? t("rail.program.full") : t("rail.program.limited")}
              </span>
              <ChevronRight size={13} aria-hidden="true" className="flex-none text-subtle" />
            </div>
            <div className="mt-1 text-micro leading-snug text-subtle">
              {program.is_encoded
                ? t("rail.program.encoded")
                : t("rail.program.notEncoded")}
            </div>
          </button>
        ) : (
          <div className="rounded-lg border border-border bg-card px-3 py-2.5 text-body text-muted-foreground">
            …
          </div>
        )}
      </div>

      {/* The failed strip. A dead API dressed as an empty record is the silent failure
          rule 6 forbids — and with live sub-lines below, the stakes double: every slot
          falls back to its static description while this strip says why. */}
      {failed ? (
        <div className="mx-4 mt-3 flex-none rounded-lg border border-destructive/25 bg-destructive-soft px-3 py-2.5 md:mx-5">
          <div className="text-meta font-medium text-destructive">{t("rail.failed")}</div>
          <div className="mt-0.5 text-micro leading-relaxed text-muted-foreground">
            {t("rail.failed.meta")}
          </div>
          <Button variant="outline" size="sm" className="mt-2 w-full" onClick={onRetry}>
            {t("rail.failed.retry")}
          </Button>
        </div>
      ) : null}

      {/* The nav is the rail's body now, not its footer — five slots, each sub-line live
          state. Detail lives one click away in the page each slot opens; the rail
          stopped duplicating the mission page. The sub-line stays visible on a phone,
          unlike the old static descriptions: "Blocked · 1 blocker" is exactly what the
          drawer exists to say. */}
      <nav
        aria-label={t("nav.heading")}
        className="nx-scroll min-h-0 flex-1 overflow-auto px-2 py-2 md:px-3"
      >
        <div className="relative flex flex-col">
          {/* The shared marker: accent tint plus the verdict system's left edge,
              travelling to the chosen tool. Decoration only — aria-current on the
              button is the state, and the active item's own ink and weight still say
              it if this never paints. */}
          <div
            ref={sliderRef}
            aria-hidden="true"
            className="nx-nav-slider pointer-events-none absolute inset-x-0 top-0 h-0 rounded-md border border-primary/25 bg-accent"
          >
            <span className="absolute top-1/2 left-0 h-[60%] w-[3px] -translate-y-1/2 rounded-r-sm bg-primary" />
          </div>

          {NAV.map((id, navIndex) => {
            const Icon = NAV_ICON[id]
            const isActive = view === id
            const alarmed = id === "mission" && blockers.length > 0 && ready && !failed
            return (
              <button
                key={id}
                ref={(el) => {
                  if (el) itemRefs.current.set(id, el)
                  else itemRefs.current.delete(id)
                }}
                type="button"
                aria-current={isActive ? "page" : undefined}
                onClick={() => onOpenView(id)}
                /* Roomy for a thumb, tight for a cursor: the rail is a drawer on a
                   phone where these are touch targets. The nudge on hover is the
                   design's — 2px toward the tool, control feedback pace. */
                className={`relative flex w-full items-center gap-2.5 rounded-md px-2.5 py-2.5 text-left transition-[transform,color] duration-(--motion-fast) hover:translate-x-0.5 md:py-2 ${
                  isActive ? "font-medium text-primary" : "text-muted-foreground active:bg-card"
                } ${settled.has(id) ? "nx-settle" : ""}`}
              >
                <Icon
                  size={15}
                  aria-hidden="true"
                  className={`flex-none ${isActive ? "text-primary" : "text-subtle"}`}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-body leading-tight md:text-meta">
                    {t(`nav.${id}`)}
                  </span>
                  {/* The live figure. Red text, not a red dot, when the mission is
                      blocked — the state names itself in words wherever it appears. */}
                  <span
                    className={`nx-figure mt-0.5 block text-micro leading-tight font-normal ${
                      alarmed
                        ? "font-medium text-destructive"
                        : isActive
                          ? "text-muted-foreground"
                          : "text-subtle"
                    }`}
                  >
                    {subs[navIndex]}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      </nav>

      {/* Two claims and a promise, and all three have to survive being skimmed: state is
          recomputed on every read, this is not NYU, and the records are fictional while
          the policy text is really NYU's. */}
      <div className="flex-none border-t border-border px-4 pt-3 pb-4 md:px-5">
        <p className="text-micro leading-relaxed text-subtle">{t("rail.recomputed")}</p>
        <p className="mt-2 text-micro leading-relaxed text-subtle">{t("rail.disclaimer")}</p>
      </div>
    </aside>
  )
}
