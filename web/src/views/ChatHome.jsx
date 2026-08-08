import { useEffect, useRef, useState } from "react"
import { api } from "@/api"
import { Button } from "@/components/ui/button"
import { ArtifactCard } from "@/components/chat/cards"
import { describeDegradations } from "@/lib/degradations"

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

const TOOL_LABEL = {
  search_policy: "policy search",
  get_holds: "your holds",
  get_degree_progress: "degree progress",
  get_registration_attempts: "registration history",
  get_course_info: "course catalog",
  get_my_plan: "your plan",
  albert_checklist: "where to look in Albert",
  decode_registration_error: "error decoder",
  get_mission_state: "mission state",
  propose_mission_candidates: "course suggestions",
  get_course_sequence: "term sequence",
}

/**
 * The kicker over each answer. `tone` drives the colour; the label is the text that has to
 * carry the same meaning on its own.
 */
const DECISION_KICKER = {
  answered: { tone: "accent", label: "Answered from verified sources" },
  answered_with_caveat: { tone: "warn", label: "Answered — read the caveats" },
  escalated: { tone: "warn", label: "Routed to a human" },
  refused: { tone: "danger", label: "Outside what I can verify" },
}

/**
 * What the assistant cannot do, said next to the answer rather than once in a footer.
 *
 * Shown on the turns where the boundary is the point — a refusal, or a question handed to
 * a person. Printing it under every answer would train the student to stop reading it,
 * which costs exactly the turns it exists for. The wording is architecture rule 8, not a
 * tone choice: the AI never mutates official records.
 */
const BOUNDARY_NOTE =
  "I can read published rules, explain what your entries imply, and open a case with the " +
  "right office. I cannot clear a hold, waive a prerequisite, approve an exception, or " +
  "change your enrollment — those stay with the offices that decide them."

const TONE_TEXT = {
  accent: "text-primary",
  good: "text-success",
  warn: "text-warning",
  danger: "text-destructive",
  neutral: "text-subtle",
}

function Kicker({ tone, children }) {
  return (
    <div className={`text-[10px] font-medium tracking-[0.13em] uppercase ${TONE_TEXT[tone]}`}>
      {children}
    </div>
  )
}

function BotAvatar() {
  return (
    <div
      aria-hidden="true"
      className="grid size-[30px] flex-none place-items-center rounded-[9px] bg-accent text-accent-foreground"
    >
      <svg viewBox="0 0 24 24" className="size-4" fill="currentColor">
        <path d="M12 2l1.9 5.6L19.5 9.5 13.9 11.4 12 17l-1.9-5.6L4.5 9.5l5.6-1.9L12 2zM18.5 14l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9.9-2.6z" />
      </svg>
    </div>
  )
}

function Thinking() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [])
  return (
    <div className="flex items-center gap-3.5" role="status">
      <BotAvatar />
      <div className="flex h-[30px] items-center gap-1.5">
        <span className="nx-tick size-1.5 rounded-full bg-primary" />
        <span className="nx-tick size-1.5 rounded-full bg-primary" />
        <span className="nx-tick size-1.5 rounded-full bg-primary" />
        <span className="ml-2 text-[11.5px] text-muted-foreground">
          Checking your record, policy, and plans as needed… {seconds}s
          {seconds > 20 ? " (thorough answers take a moment)" : ""}
        </span>
      </div>
    </div>
  )
}

/** Where the student stands, without the salutation — the caller decides how it opens. */
function greetingFor(missions, profileCount) {
  const openMission = missions.find((m) => !m.complete)

  if (openMission) {
    const active = openMission.steps.find((s) => s.state === "active")
    return {
      status:
        `your ${openMission.term} registration mission is ` +
        `${openMission.steps.filter((s) => s.state === "done").length} of ${openMission.steps.length} steps done.` +
        (active?.what_now ? ` Next: ${active.what_now}` : ""),
      chips: ["Where am I in my registration prep?", "Suggest courses for my mission"],
    }
  }
  if (profileCount > 0) {
    return {
      status:
        `you have ${profileCount} course${profileCount === 1 ? "" : "s"} in your record. ` +
        "I can check what your degree still needs, sequence the remaining terms, or help you prepare to register.",
      chips: ["Plan my next semester", "Am I on track to graduate?"],
    }
  }
  return {
    status:
      "I can explain a registration error right away, nothing to set up. " +
      "If you tell me what you've taken, I can also check your degree and plan your next term.",
    chips: ["What does ERR_PREREQ mean?", "What should I do first?"],
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
function AuditPane({ thread }) {
  const entries = []
  thread.forEach((entry, turn) => {
    if (entry.kind !== "assistant") return
    entry.result.tool_trace.forEach((call, i) => {
      entries.push({
        id: `${turn}-${i}`,
        label: TOOL_LABEL[call.tool] ?? call.tool,
        meta: call.failed
          ? "failed — not reflected in the answer"
          : call.source_ids?.length
            ? `${call.source_ids.length} source${call.source_ids.length === 1 ? "" : "s"} returned`
            : "returned no citable source",
        tone: call.failed ? "danger" : call.source_ids?.length ? "good" : "neutral",
      })
    })
    entry.result.degraded_modes.forEach((mode, i) => {
      entries.push({
        id: `${turn}-d${i}`,
        label: "Ran degraded",
        meta: describeDegradations([mode]),
        tone: "warn",
      })
    })
  })

  return (
    <aside
      className="nx-scroll max-h-[45vh] w-full flex-none overflow-auto border-b border-border px-4 py-5 lg:order-last lg:max-h-none lg:w-[300px] lg:border-l lg:border-b-0 lg:px-5"
      aria-label="What the assistant checked"
    >
      <div className="mb-1.5 text-[11px] font-medium tracking-[0.12em] text-subtle uppercase">
        What was checked
      </div>
      <p className="mb-4 text-[11.5px] leading-relaxed text-muted-foreground">
        Every lookup is scoped to your record before it runs, and written to the audit log.
      </p>

      {entries.length === 0 ? (
        <p className="text-[12.5px] text-muted-foreground">
          Nothing yet — this fills in as you ask.
        </p>
      ) : (
        <div className="flex flex-col">
          {entries.map((e, i) => (
            <div key={e.id} className="flex gap-3">
              <div className="flex flex-none flex-col items-center">
                <span className={`nx-dot nx-dot--${e.tone} mt-1.5`} aria-hidden="true" />
                {i < entries.length - 1 ? <span className="w-px flex-1 bg-border" /> : null}
              </div>
              <div className="min-w-0 pb-4">
                <div className="text-[12.5px] leading-snug">{e.label}</div>
                <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
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
  onOpenView,
  onTurn,
}) {
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
      const greeting = greetingFor(missions, courses.length)
      const note = {
        kind: "assistant-note",
        text: recovering
          ? `Your record is readable again — ${greeting.status}`
          : `Hi ${first} — ${greeting.status}`,
      }
      setThread((t) => (recovering ? [...t, note] : [note]))
      setChips(greeting.chips)
    } else if (loadFailed && greeted.current === null) {
      greeted.current = "failed"
      setThread([
        {
          kind: "assistant-note",
          text:
            `Hi ${first} — I couldn't read your record just now, so I can't say where your ` +
            "registration stands. That is a connection problem, not an empty record. I can " +
            "still explain registration errors and published policy — neither needs it.",
        },
      ])
      setChips(["What does ERR_PREREQ mean?", "How do registration holds work?"])
    }
  }, [ready, loadFailed, missions, courses, me.full_name])

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
    setThread((t) => [...t, { kind: "user", text: trimmed }])
    setBusy(true)
    try {
      const result = await api.ask(trimmed, history)
      setThread((t) => [...t, { kind: "assistant", result }])
      // The answer may have moved the mission; the shell's rail must not keep showing
      // the old one.
      onTurn?.()
    } catch (err) {
      setThread((t) => [...t, { kind: "error", text: trimmed, message: err.message }])
    } finally {
      setBusy(false)
    }
  }

  return (
    /* Stacks on a phone rather than hiding: the audit pane takes `order-last` at lg so it
       sits right of the conversation there while sitting above it when stacked. */
    <div className={`flex min-h-0 flex-1 flex-col ${showAudit ? "lg:flex-row" : ""}`}>
        <section aria-label="Conversation" className="flex min-w-0 flex-1 flex-col">
          <div className="nx-scroll flex-1 overflow-auto px-4 pt-6 pb-2 sm:px-7">
            <div className="mx-auto flex max-w-[760px] flex-col gap-5">
              {thread.map((entry, i) => {
                if (entry.kind === "user") {
                  return (
                    <div key={i} className="nx-msg flex justify-end">
                      {/* --ink on the accent tint, not --accent. The accent-on-its-own-tint
                          pair now clears AA in dark (4.67 after the palette promotion
                          lightened --accent, up from 4.43), but --ink measures 11.80 on the
                          same tint, and this is the student's own words being read back —
                          the one place in the thread with no reason to be near the floor. */}
                      <div className="max-w-[76%] rounded-[14px] rounded-br-sm bg-accent px-4 py-2.5 text-[14px] leading-relaxed text-foreground">
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
                        <Kicker tone="danger">Could not answer</Kicker>
                        <p className="text-[14.5px] leading-relaxed">{entry.message}</p>
                        <div>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            onClick={() => ask(entry.text)}
                          >
                            Ask again
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
                      <p className="min-w-0 flex-1 pt-1 text-[14.5px] leading-relaxed whitespace-pre-wrap">
                        {entry.text}
                      </p>
                    </div>
                  )
                }

                const { result } = entry
                const artifacts = result.artifacts ?? []
                const kicker = DECISION_KICKER[result.decision] ?? DECISION_KICKER.answered
                const consulted = [
                  ...new Set(result.tool_trace.map((t) => TOOL_LABEL[t.tool] ?? t.tool)),
                ]
                const showBoundary =
                  result.decision === "refused" || result.decision === "escalated"

                return (
                  <div key={i} className="nx-msg flex gap-3.5">
                    <BotAvatar />
                    <div className="flex min-w-0 flex-1 flex-col gap-2.5">
                      <Kicker tone={kicker.tone}>{kicker.label}</Kicker>

                      <p className="text-[14.5px] leading-relaxed whitespace-pre-wrap text-pretty">
                        {result.answer}
                      </p>

                      {result.case_number ? (
                        <div className="rounded-md border border-primary/45 bg-accent px-3.5 py-2.5 text-[12.5px] leading-relaxed">
                          Case <strong className="font-medium">{result.case_number}</strong> has
                          been opened — quote it when you contact the office.
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
                        <div className="rounded-md border border-warning/45 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
                          <span className="font-medium text-warning">Ran degraded — </span>
                          {describeDegradations(result.degraded_modes)}.
                        </div>
                      ) : null}

                      {showBoundary ? (
                        <div className="rounded-md border border-primary/40 bg-accent px-3.5 py-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
                          {BOUNDARY_NOTE}
                        </div>
                      ) : null}

                      {consulted.length > 0 || result.citations.length > 0 ? (
                        <div className="flex flex-col gap-1 text-[11px] text-subtle">
                          {consulted.length > 0 ? (
                            <div>Checked: {consulted.join(" · ")}</div>
                          ) : null}
                          {result.citations.length > 0 ? (
                            <details>
                              <summary className="cursor-pointer">
                                {result.citations.length} cited claim
                                {result.citations.length === 1 ? "" : "s"}
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
                )
              })}

              {busy ? <Thinking /> : null}
              <div ref={endRef} />
            </div>
          </div>

          <div className="px-4 pt-1 pb-4 sm:px-7">
            <div className="mx-auto flex max-w-[760px] flex-col gap-3">
              {chips.length > 0 && !busy ? (
                <div className="nx-scroll flex gap-2 overflow-x-auto pb-1">
                  {chips.map((chip) => (
                    <Button
                      key={chip}
                      size="sm"
                      variant="outline"
                      className="flex-none rounded-full whitespace-nowrap"
                      onClick={() => ask(chip)}
                    >
                      {chip}
                    </Button>
                  ))}
                </div>
              ) : null}

              <form
                className="flex items-center gap-2 rounded-lg border border-border bg-card py-1.5 pr-1.5 pl-3.5"
                onSubmit={(e) => {
                  e.preventDefault()
                  ask(question)
                }}
              >
                <label className="sr-only" htmlFor="chat-input">
                  Ask a question
                </label>
                <input
                  id="chat-input"
                  className="min-w-0 flex-1 bg-transparent py-1.5 text-[14px] outline-none placeholder:text-subtle"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Ask about holds, enrollment errors, courses, or your degree…"
                  disabled={busy}
                />
                <Button type="submit" variant="outline" disabled={busy || !question.trim()}>
                  Ask
                </Button>
              </form>

              {/* The disclaimer sits with the advice, not only in the page footer — this is
                  the text a student screenshots and acts on. Set in --ink-2, not the subtle
                  step, so it clears AA at this size in both themes. */}
              <p className="text-[11.5px] leading-relaxed text-muted-foreground">
                Answers cite what they rest on and say when something could not be verified.
                Not an NYU system, and it cannot see Albert — verify anything that affects
                registration there before you act on it.
              </p>
            </div>
          </div>
        </section>

        {showAudit ? <AuditPane thread={thread} /> : null}
      </div>
  )
}
