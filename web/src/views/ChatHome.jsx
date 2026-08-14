import { useEffect, useRef, useState } from "react"
import { api } from "@/api"
import { Button } from "@/components/ui/button"
import { ArtifactCard } from "@/components/chat/cards"
import { describeDegradations } from "@/lib/degradations"
import { usePrefs } from "@/i18n"

/**
 * The conversation surface. StudentShell owns the frame around it — the readiness rail,
 * the pane switch, the tool pages — and this component owns one thing: the thread.
 *
 * Three decisions define it:
 *
 * **The server says what to render; this view renders it.** Each answer carries
 * `artifacts` under the Artifact Contract (api services/artifacts.py) — the server
 * re-reads authoritative state at answer time and hands over typed, versioned results.
 * This view maps them through the card registry and infers nothing from `tool_trace`,
 * which is the audit record, not a UI protocol. Confirming a proposed course happens in
 * the card, through the same student-authenticated endpoint as the Mission page — not by
 * being told to go find another tab.
 *
 * **The greeting is computed, not generated.** The shell reads the profile and missions;
 * the first time both arrive, this view says where the student stands — instantly,
 * deterministically, and without spending an LLM call on "hello". The greeting fires
 * once: the data refreshes after every turn, and re-greeting mid-conversation because a
 * mission moved would be the UI talking over the student. The one exception is a read
 * that failed and later succeeds — a greeting that had to say "I can't read your record"
 * gets a correction appended, because leaving it standing next to a rail showing the
 * real state would be the thread lying about the present.
 *
 * **The wait is honest.** No fake "step 2 of 5" theatre the backend cannot confirm; an
 * elapsed-seconds line while working, and the real list of what was consulted after.
 */

// Known tool names, so a label lookup can fall back to the raw name for a tool the
// dictionary has not met. Labels live in i18n/en.js under `tool.*`.
const KNOWN_TOOLS = [
  "search_policy",
  "get_course_info",
  "get_my_plan",
  "albert_checklist",
  "decode_registration_error",
  "get_mission_state",
  "propose_mission_candidates",
  "get_course_sequence",
]

const toolLabel = (t, name) => (KNOWN_TOOLS.includes(name) ? t(`tool.${name}`) : name)

/**
 * The kicker over each answer. `tone` drives the colour; the label key resolves to the
 * text that has to carry the same meaning on its own.
 * The boundary note (chat.boundary) is shown only on the turns where the boundary is the
 * point — a refusal, or a question handed to a person. Printing it under every answer
 * would train the student to stop reading it. Its wording is architecture rule 8.
 */
const DECISION_KICKER = {
  answered: { tone: "accent", label: "kicker.answered" },
  answered_with_caveat: { tone: "warn", label: "kicker.caveat" },
  escalated: { tone: "warn", label: "kicker.escalated" },
  refused: { tone: "danger", label: "kicker.refused" },
}

const TONE_TEXT = {
  accent: "text-primary",
  good: "text-success",
  warn: "text-warning",
  danger: "text-destructive",
  neutral: "text-subtle",
}

/* nx-pop, not nx-msg: the verdict badge is the one element that resolves with a spring —
   it lands just after the message's own rise and wants to be noticed once. */
function Kicker({ tone, children }) {
  return <div className={`nx-pop w-fit nx-label ${TONE_TEXT[tone]}`}>{children}</div>
}

/** A message's byline: who spoke and when, in the reader's locale. */
function Byline({ name, at, locale, alignEnd }) {
  return (
    <div
      className={`flex items-baseline gap-2 text-micro text-subtle ${alignEnd ? "justify-end" : ""}`}
    >
      <span className="font-medium text-muted-foreground">{name}</span>
      {at ? (
        <time className="nx-figure" dateTime={at.toISOString()}>
          {at.toLocaleTimeString(locale === "zh" ? "zh-Hans" : "en-US", {
            hour: "numeric",
            minute: "2-digit",
          })}
        </time>
      ) : null}
    </div>
  )
}

/**
 * The assistant's mark: three rules — solid, dashed, dotted.
 *
 * It was a four-point sparkle, which is the one glyph every AI product on earth is
 * currently wearing and says nothing about this one. These three lines are the legend for
 * the verdict edge running down the side of every finding on the page: an observed claim,
 * a conditional one, and one that can only be projected. The thing the assistant actually
 * does, drawn at 16px.
 */
function MarkGlyph({ className }) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    >
      <path d="M2 4h12" />
      <path d="M2 8h12" strokeDasharray="3.2 2.6" />
      <path d="M2 12h9" strokeDasharray="0.1 3" />
    </svg>
  )
}

function BotAvatar() {
  return (
    <div
      aria-hidden="true"
      className="grid size-[30px] flex-none place-items-center rounded-[9px] bg-accent text-accent-foreground"
    >
      <MarkGlyph className="size-4" />
    </div>
  )
}

/**
 * The front door, before anything has been asked.
 *
 * What this replaced put a greeting at the top of roughly a thousand pixels of nothing,
 * with the composer pinned to the far bottom — a chat app with the chat missing. Two
 * things were wrong beyond the empty space. Most of the greeting restated what the rail
 * was already showing two hundred pixels to the left, and then listed the same three
 * options as the suggestion chips directly beneath it.
 *
 * So the centre column stops reporting status, which the rail owns, and says the thing
 * that actually separates this from asking a chatbot the same question: it reads
 * published rules and what the student entered, it cannot see Albert, and it will name
 * what it cannot check rather than fill the gap. That claim was previously a footnote
 * under the composer. It is the product's whole argument, so it goes at the top.
 *
 * The computed standing survives as one quiet line — it is genuinely useful for a student
 * returning to a half-finished mission, and it is the one part of the greeting the rail
 * does not already say in the same words.
 */
function LandingHero({ notes, railVisible, t }) {
  // The routine greeting restates the rail. Printed beside it, it reads as the screen
  // saying the same thing twice; with the rail closed it is the only place that says it.
  const shown = notes.filter((n) => !n.routine || !railVisible)

  return (
    <div className="nx-msg flex flex-col items-start gap-5">
      <div
        aria-hidden="true"
        className="grid size-12 place-items-center rounded-xl bg-accent text-accent-foreground"
      >
        <MarkGlyph className="size-6" />
      </div>

      {/* Was "What's in your way?" — the readiness question, when the product answered
          whether you were blocked. It plans a term now, so the front door asks the question
          the product can actually finish. */}
      <h1 className="nx-statement text-display">{t("chat.hero.title")}</h1>

      <p className="max-w-[54ch] text-lead leading-relaxed text-muted-foreground">
        {t("chat.hero.desc")}
      </p>

      {shown.map((note, i) => (
        <p key={i} className="max-w-[54ch] text-meta leading-relaxed text-subtle">
          {note.text}
        </p>
      ))}
    </div>
  )
}

/**
 * The wait, which is nine to twenty seconds and the most-looked-at state in the product.
 *
 * A sweep, not a bar that fills. There is no tool-event stream behind this yet, so a bar
 * travelling toward a target would be drawing progress the frontend cannot see — the same
 * "step 2 of 5" theatre this view has refused from the start. A sweep says work is
 * happening and claims nothing about how much is left, which is the whole of what is
 * known. The elapsed count is the one real number available, so it gets tabular figures
 * and stops jittering as it ticks.
 */
function Thinking({ t }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [])
  return (
    <div className="nx-msg flex gap-3.5" role="status">
      <BotAvatar />
      <div className="flex min-w-0 flex-1 flex-col gap-2 pt-2.5">
        <div className="nx-scan h-[2px] w-full max-w-[260px] rounded-full" aria-hidden="true" />
        <span className="text-meta leading-relaxed text-muted-foreground">
          {t("chat.thinking")}
          <span className="nx-figure">{seconds}s</span>
          {seconds > 20 ? t("chat.thinking.long") : ""}
        </span>
      </div>
    </div>
  )
}

/**
 * Where the student stands, without the salutation — the caller decides how it opens.
 * Chip *keys*, not chip text: the greeting is stored in the thread at one point in time,
 * but chips are live controls and must re-label when the locale flips.
 */
function greetingFor(missions, profileCount, t) {
  const openMission = missions.find((m) => !m.complete)

  if (openMission) {
    const active = openMission.steps.find((s) => s.state === "active")
    return {
      status: t("greet.mission", {
        term: openMission.term,
        done: openMission.steps.filter((s) => s.state === "done").length,
        total: openMission.steps.length,
        next: active?.what_now ?? "",
      }),
      chips: ["chip.next", "chip.suggest"],
    }
  }
  if (profileCount > 0) {
    return {
      status: t("greet.courses", { count: profileCount }),
      chips: ["chip.plan", "chip.delay"],
    }
  }
  return {
    status: t("greet.empty"),
    chips: ["chip.prereq", "chip.first"],
  }
}

/* ---------------------------------------------------------------------------------- */

/**
 * Right pane: what the agent actually did, per turn.
 *
 * Built from `tool_trace`, which carries `source_ids` per call — so a lookup that returned
 * nothing is visible as such rather than blending in with one that did. That distinction is
 * the whole reason the policy-search budget exists; showing it is cheap here and there is
 * no honest reason to hide it.
 */
function AuditPane({ thread, t }) {
  const entries = []
  thread.forEach((entry, turn) => {
    if (entry.kind !== "assistant") return
    entry.result.tool_trace.forEach((call, i) => {
      entries.push({
        id: `${turn}-${i}`,
        label: toolLabel(t, call.tool),
        meta: call.failed
          ? t("audit.failed")
          : call.source_ids?.length
            ? t("audit.sources", { count: call.source_ids.length })
            : t("audit.noSources"),
        tone: call.failed ? "danger" : call.source_ids?.length ? "good" : "neutral",
      })
    })
    entry.result.degraded_modes.forEach((mode, i) => {
      entries.push({
        id: `${turn}-d${i}`,
        label: t("audit.degraded"),
        meta: describeDegradations([mode]),
        tone: "warn",
      })
    })
  })

  return (
    <aside
      className="nx-scroll max-h-[45vh] w-full flex-none overflow-auto border-b border-border px-4 py-5 lg:order-last lg:max-h-none lg:w-[300px] lg:border-l lg:border-b-0 lg:px-5"
      aria-label={t("audit.aria")}
    >
      <div className="mb-1.5 nx-label">
        {t("audit.title")}
      </div>
      <p className="mb-4 text-meta leading-relaxed text-muted-foreground">
        {t("audit.desc")}
      </p>

      {entries.length === 0 ? (
        <p className="text-meta text-muted-foreground">
          {t("audit.empty")}
        </p>
      ) : (
        <div className="nx-cascade flex flex-col">
          {entries.map((e, i) => (
            <div key={e.id} className="flex gap-3">
              <div className="flex flex-none flex-col items-center">
                <span className={`nx-dot nx-dot--${e.tone} mt-1.5`} aria-hidden="true" />
                {i < entries.length - 1 ? <span className="w-px flex-1 bg-border" /> : null}
              </div>
              <div className="min-w-0 pb-4">
                <div className="text-meta leading-snug">{e.label}</div>
                <div className="mt-0.5 text-micro leading-snug text-muted-foreground">
                  {e.meta}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </aside>
  )
}

/* ---------------------------------------------------------------------------------- */

export default function ChatHome({
  me,
  active,
  missions,
  courses,
  ready,
  loadFailed,
  showAudit,
  railVisible,
  onOpenView,
  onTurn,
}) {
  const { t, locale } = usePrefs()
  const [thread, setThread] = useState([])
  const [question, setQuestion] = useState("")
  const [chips, setChips] = useState([])
  const [busy, setBusy] = useState(false)
  // null → not yet greeted · "failed" → greeted while the record was unreadable ·
  // "ready" → greeted from real data. A failed greeting is not final: it must not say
  // "nothing in your record" (a fetch failure is not an empty record), and once the
  // record does load the correction is appended, so the thread never keeps claiming
  // unreadability while the rail shows the real state.
  const greeted = useRef(null)
  const endRef = useRef(null)

  useEffect(() => {
    if (greeted.current === "ready") return
    const first = (me.full_name ?? "").split(" ")[0]
    if (ready) {
      const recovering = greeted.current === "failed"
      greeted.current = "ready"
      const greeting = greetingFor(missions, courses.length, t)
      const note = {
        kind: "assistant-note",
        // `routine` is what the rail is already saying in its own words. The recovery
        // note is not routine — "your record is readable again" is news, and it has to
        // reach a student who is looking at the conversation on its own.
        routine: !recovering,
        text: recovering
          ? t("greet.recovered", { status: greeting.status })
          : t("greet.hi", { name: first, status: greeting.status }),
      }
      setThread((prev) => (recovering ? [...prev, note] : [note]))
      setChips(greeting.chips)
    } else if (loadFailed && greeted.current === null) {
      greeted.current = "failed"
      setThread([
        {
          kind: "assistant-note",
          text: t("greet.failed", { name: first }),
        },
      ])
      setChips(["chip.prereq", "chip.holds"])
    }
  }, [ready, loadFailed, missions, courses, me.full_name, t])

  // `active` is in the deps because a hidden pane loses its scroll position: coming back
  // from a tool page must land on the latest turn, not the top of the thread.
  useEffect(() => {
    if (!active) return
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [thread, busy, active])

  async function ask(text) {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    setQuestion("")
    setChips([])
    // Prior turns as plain text, so "take that elective out" has something to resolve
    // against. The computed greeting is excluded — it is UI copy, not something the
    // student or the agent said.
    const history = thread
      .filter((e) => e.kind === "user" || e.kind === "assistant")
      .slice(-6)
      .map((e) => ({
        role: e.kind === "user" ? "user" : "assistant",
        content: e.kind === "user" ? e.text : e.result.answer,
      }))
    setThread((prev) => [...prev, { kind: "user", text: trimmed, at: new Date() }])
    setBusy(true)
    try {
      const result = await api.ask(trimmed, history)
      setThread((prev) => [...prev, { kind: "assistant", result, at: new Date() }])
      // The answer may have moved the mission; the shell's rail must not keep showing
      // the old one.
      onTurn?.()
    } catch (err) {
      setThread((prev) => [
        ...prev,
        { kind: "error", text: trimmed, message: err.message },
      ])
    } finally {
      setBusy(false)
    }
  }

  // Nothing has been asked yet: the greeting notes are UI copy, not conversation. The
  // hero and the composer centre as one group in that state, and the thread takes over
  // the moment there is anything to scroll.
  const landing = !busy && thread.every((e) => e.kind === "assistant-note")

  return (
    /* Stacks on a phone rather than hiding: the audit pane takes `order-last` at lg so it
       sits right of the conversation there while sitting above it when stacked. */
    <div className={`flex min-h-0 flex-1 flex-col ${showAudit ? "lg:flex-row" : ""}`}>
        <section
          aria-label="Conversation"
          /* min-h-0 is load-bearing, like every level of this flex chain: without it the
             section's minimum height is its content — the whole thread — and the column
             quietly grows past h-dvh instead of scrolling inside it. It held without the
             constraint on first render and broke after a hidden→shown round trip through
             a tool view, which is exactly the kind of history-dependent layout a missing
             explicit constraint produces. */
          className={`flex min-h-0 min-w-0 flex-1 flex-col ${landing ? "justify-center" : ""}`}
        >
          {/* Same element in the same position in both states, so switching out of the
              landing layout re-styles the column rather than remounting the composer
              below it and taking the caret with it. */}
          <div
            className={
              landing
                ? "px-4 pt-6 sm:px-7"
                : "nx-scroll flex-1 overflow-auto px-4 pt-6 pb-2 sm:px-7"
            }
          >
            <div className="mx-auto flex w-full max-w-[760px] flex-col gap-5">
              {landing ? <LandingHero notes={thread} railVisible={railVisible} t={t} /> : null}
              {landing ? null : thread.map((entry, i) => {
                if (entry.kind === "user") {
                  return (
                    <div key={i} className="nx-msg flex flex-col items-end gap-1">
                      <Byline name={t("chat.you")} at={entry.at} locale={locale} alignEnd />
                      {/* --ink on the accent tint, not --accent. The accent-on-its-own-tint
                          pair now clears AA in dark (4.67 after the palette promotion
                          lightened --accent, up from 4.43), but --ink measures 11.80 on the
                          same tint, and this is the student's own words being read back —
                          the one place in the thread with no reason to be near the floor. */}
                      <div className="max-w-[76%] rounded-[14px] rounded-tr-sm bg-accent px-4 py-2.5 text-lead leading-relaxed text-foreground">
                        {entry.text}
                      </div>
                    </div>
                  )
                }

                if (entry.kind === "error") {
                  return (
                    <div key={i} className="nx-msg flex gap-3.5" role="alert">
                      <BotAvatar />
                      <div className="flex min-w-0 flex-1 flex-col gap-2">
                        <Kicker tone="danger">{t("chat.error.kicker")}</Kicker>
                        <p className="text-lead leading-relaxed">{entry.message}</p>
                        <div>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            onClick={() => ask(entry.text)}
                          >
                            {t("chat.error.retry")}
                          </Button>
                        </div>
                      </div>
                    </div>
                  )
                }

                if (entry.kind === "assistant-note") {
                  return (
                    <div key={i} className="nx-msg flex gap-3.5">
                      <BotAvatar />
                      <p className="min-w-0 flex-1 pt-1 text-lead leading-relaxed whitespace-pre-wrap">
                        {entry.text}
                      </p>
                    </div>
                  )
                }

                const { result } = entry
                const artifacts = result.artifacts ?? []
                const kicker = DECISION_KICKER[result.decision] ?? DECISION_KICKER.answered
                const consulted = [
                  ...new Set(result.tool_trace.map((call) => toolLabel(t, call.tool))),
                ]
                const showBoundary =
                  result.decision === "refused" || result.decision === "escalated"

                return (
                  <div key={i} className="nx-msg flex gap-3.5">
                    <BotAvatar />
                    {/* nx-cascade: the answer's parts resolve in reading order — byline,
                        then the answer, then what it carries. Fade only; the row's own
                        rise is the movement. */}
                    <div className="nx-cascade flex min-w-0 flex-1 flex-col gap-1.5">
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <Byline name={t("chat.assistant")} at={entry.at} locale={locale} />
                        <Kicker tone={kicker.tone}>{t(kicker.label)}</Kicker>
                      </div>

                      {/* The answer rides in a bubble — the source design's message shape,
                          card surface on the ground, squared toward the avatar. Everything
                          the answer *carries* (cards, caveats, citations) stays outside
                          the bubble: evidence about the answer, not part of it. */}
                      <div className="w-fit max-w-full rounded-[14px] rounded-tl-sm border border-border bg-card px-4 py-3">
                        <p className="text-lead leading-relaxed whitespace-pre-wrap text-pretty">
                          {result.answer}
                        </p>
                      </div>

                      <div className="flex flex-col gap-2.5">
                      {result.case_number ? (
                        <div className="rounded-md border border-primary/45 bg-accent px-3.5 py-2.5 text-meta leading-relaxed">
                          {t("chat.case", { number: result.case_number })}
                        </div>
                      ) : null}

                      {artifacts.length > 0 ? (
                        <div className="flex flex-col gap-2.5">
                          {artifacts.map((artifact) => (
                            <ArtifactCard
                              key={artifact.id}
                              artifact={artifact}
                              onOpenView={onOpenView}
                            />
                          ))}
                        </div>
                      ) : null}

                      {result.degraded_modes.length > 0 ? (
                        <div className="rounded-md border border-warning/45 px-3.5 py-2.5 text-meta leading-relaxed text-muted-foreground">
                          <span className="font-medium text-warning">{t("chat.degraded")}</span>
                          {describeDegradations(result.degraded_modes)}.
                        </div>
                      ) : null}

                      {showBoundary ? (
                        <div className="rounded-md border border-primary/40 bg-accent px-3.5 py-2.5 text-meta leading-relaxed text-muted-foreground">
                          {t("chat.boundary")}
                        </div>
                      ) : null}

                      {consulted.length > 0 || result.citations.length > 0 ? (
                        <div className="flex flex-col gap-1 text-micro text-subtle">
                          {consulted.length > 0 ? (
                            <div>{t("chat.checked", { tools: consulted.join(" · ") })}</div>
                          ) : null}
                          {result.citations.length > 0 ? (
                            <details>
                              <summary className="cursor-pointer">
                                {t("chat.citations", { count: result.citations.length })}
                              </summary>
                              <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-4">
                                {result.citations.map((c, j) => (
                                  <li key={j}>{c.claim}</li>
                                ))}
                              </ul>
                            </details>
                          ) : null}
                        </div>
                      ) : null}
                      </div>
                    </div>
                  </div>
                )
                })}

              {busy ? <Thinking t={t} /> : null}
              <div ref={endRef} />
            </div>
          </div>

          <div className="px-4 pt-1 pb-4 sm:px-7">
            <div className="mx-auto flex max-w-[760px] flex-col gap-3">
              {chips.length > 0 && !busy ? (
                <div className="nx-cascade nx-scroll flex gap-2 overflow-x-auto pb-1">
                  {/* Chips hold dictionary keys, resolved here so a locale flip re-labels
                      them. The lift on hover is --motion-fast; asking sends the *resolved*
                      text, because the agent receives what the student read. Their
                      arrival cascades left to right — reading order, same rule as the
                      answer's parts. */}
                  {chips.map((chip) => (
                    <Button
                      key={chip}
                      size="sm"
                      variant="outline"
                      className="flex-none rounded-full whitespace-nowrap transition-transform hover:-translate-y-px"
                      onClick={() => ask(t(chip))}
                    >
                      {t(chip)}
                    </Button>
                  ))}
                </div>
              ) : null}

              {/* A textarea, not an input: a pasted Albert error is multi-line, and the
                  composer is the one place the product explicitly invites a paste. Grows
                  to four lines then scrolls; Enter sends, Shift+Enter breaks a line. */}
              <form
                className="flex items-end gap-2 rounded-lg border border-border bg-card py-1.5 pr-1.5 pl-3.5"
                onSubmit={(e) => {
                  e.preventDefault()
                  ask(question)
                }}
              >
                <label className="sr-only" htmlFor="chat-input">
                  {t("chat.ask.label")}
                </label>
                <textarea
                  id="chat-input"
                  rows={1}
                  className="nx-scroll max-h-28 min-w-0 flex-1 resize-none bg-transparent py-1.5 text-lead outline-none placeholder:text-subtle"
                  value={question}
                  onChange={(e) => {
                    setQuestion(e.target.value)
                    e.target.style.height = "auto"
                    e.target.style.height = `${Math.min(e.target.scrollHeight, 112)}px`
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault()
                      ask(question)
                      e.target.style.height = "auto"
                    }
                  }}
                  placeholder={t("chat.placeholder")}
                  disabled={busy}
                />
                <Button type="submit" disabled={busy || !question.trim()}>
                  {t("chat.ask")}
                </Button>
              </form>

              {/* The disclaimer sits with the advice, not only in the page footer — this is
                  the text a student screenshots and acts on. Set in --ink-2, not the subtle
                  step, so it clears AA at this size in both themes.
                  Hidden on the landing screen alone, where the hero above makes the same
                  claim in better words and printing it twice is how a warning stops being
                  read. It returns with the first answer, which is what it is for. */}
              {landing ? null : (
                <p className="text-meta leading-relaxed text-muted-foreground">
                  {t("chat.disclaimer")}
                </p>
              )}
            </div>
          </div>
        </section>

        {showAudit ? <AuditPane thread={thread} t={t} /> : null}
      </div>
  )
}
