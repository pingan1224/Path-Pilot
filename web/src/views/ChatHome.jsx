import { useEffect, useRef, useState } from "react"
import { api } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DecodeCard, MissionCard, SequenceCard } from "@/components/chat/cards"
import { describeDegradations } from "@/lib/degradations"

/**
 * The chat, promoted from a floating corner panel to the student's front door.
 *
 * Three decisions define this surface:
 *
 * **Tool results become cards the student can act on, in place.** After each answer, the
 * tool trace says what the agent consulted; for the tools whose output is actionable or
 * worth seeing whole, this view re-fetches the authoritative state (the mission) or
 * re-runs the deterministic computation (sequence, decoder) and renders it as an inline
 * card with live buttons. Confirming a proposed course happens here, through the same
 * student-authenticated endpoint as the Mission page — not by being told to go find
 * another tab. Re-fetching rather than trusting a mid-conversation snapshot is the
 * mission engine's own rule applied to the UI: what the student acts on must be what is
 * true now.
 *
 * **The greeting is computed, not generated.** On load this view reads the profile and
 * missions and says where the student stands — instantly, deterministically, and without
 * spending an LLM call on "hello". The agent's budget goes to questions.
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

const DECISION_BADGE = {
  answered: { variant: "default", label: "Answered from verified sources" },
  answered_with_caveat: { variant: "secondary", label: "Answered — see caveats" },
  escalated: { variant: "secondary", label: "Routed to a human" },
  refused: { variant: "outline", label: "Outside what I can help with" },
}

const MISSION_TOOLS = ["get_mission_state", "propose_mission_candidates"]

function Thinking() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [])
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
      <span className="inline-block size-2 animate-pulse rounded-full bg-primary" />
      Working — checking your record, policy, and plans as needed… {seconds}s
      {seconds > 20 ? <span> (thorough answers take a moment)</span> : null}
    </div>
  )
}

/** Build the tool-result cards for one finished turn. Failures skip the card, never the answer. */
async function cardsForTurn(toolTrace) {
  const cards = []
  const tools = toolTrace.map((t) => t.tool)

  if (tools.some((t) => MISSION_TOOLS.includes(t))) {
    try {
      const missions = await api.missions()
      cards.push({ type: "mission", mission: missions[0] ?? null })
    } catch {
      /* staff or fetch failure — no card */
    }
  }

  const seen = new Set()
  for (const call of toolTrace.filter((t) => t.tool === "get_course_sequence")) {
    const key = JSON.stringify(call.args ?? {})
    if (seen.has(key)) continue
    seen.add(key)
    try {
      cards.push({
        type: "sequence",
        plan: await api.sequence({
          deadline: call.args?.finish_by,
          maxCredits: call.args?.max_credits_per_term,
        }),
      })
    } catch {
      /* skip */
    }
    if (seen.size === 2) break // two schedules is a comparison; more is noise
  }

  const decodeCall = toolTrace.find(
    (t) => t.tool === "decode_registration_error" && t.args?.error_text,
  )
  if (decodeCall) {
    try {
      cards.push({ type: "decode", decoded: await api.decode(decodeCall.args.error_text) })
    } catch {
      /* skip */
    }
  }

  return cards
}

function greetingFor(name, missions, profileCount) {
  const first = (name ?? "").split(" ")[0]
  const openMission = missions.find((m) => !m.complete)

  if (openMission) {
    const active = openMission.steps.find((s) => s.state === "active")
    return {
      text:
        `Hi ${first} — your ${openMission.term} registration mission is ` +
        `${openMission.steps.filter((s) => s.state === "done").length} of ${openMission.steps.length} steps done.` +
        (active?.what_now ? ` Next: ${active.what_now}` : ""),
      chips: ["Where am I in my registration prep?", "Suggest courses for my mission"],
    }
  }
  if (profileCount > 0) {
    return {
      text:
        `Hi ${first} — you have ${profileCount} course${profileCount === 1 ? "" : "s"} in your record. ` +
        "I can check what your degree still needs, sequence the remaining terms, or help you prepare to register.",
      chips: ["Plan my next semester", "Am I on track to graduate?"],
    }
  }
  return {
    text:
      `Hi ${first} — I can explain a registration error right away, nothing to set up. ` +
      "If you tell me what you've taken, I can also check your degree and plan your next term.",
    chips: ["What does ERR_PREREQ mean?", "What should I do first?"],
  }
}

export default function ChatHome({ me, onOpenView }) {
  const [thread, setThread] = useState([])
  const [question, setQuestion] = useState("")
  const [chips, setChips] = useState([])
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.missions().catch(() => []),
      api.profileCourses().catch(() => []),
    ]).then(([missions, courses]) => {
      if (cancelled) return
      const greeting = greetingFor(me.full_name, missions, courses.length)
      setThread([{ kind: "assistant-note", text: greeting.text }])
      setChips(greeting.chips)
    })
    return () => {
      cancelled = true
    }
  }, [me.full_name])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [thread, busy])

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
      const cards = await cardsForTurn(result.tool_trace)
      setThread((t) => [...t, { kind: "assistant", result, cards }])
    } catch (err) {
      setThread((t) => [...t, { kind: "error", text: err.message }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex flex-col gap-4">
        {thread.map((entry, i) => {
          if (entry.kind === "user") {
            return (
              <div
                key={i}
                className="max-w-[85%] self-end rounded-xl rounded-br-sm bg-primary px-4 py-2.5 text-primary-foreground"
              >
                {entry.text}
              </div>
            )
          }
          if (entry.kind === "error") {
            return (
              <div key={i} className="text-sm text-destructive" role="alert">
                {entry.text}
              </div>
            )
          }
          if (entry.kind === "assistant-note") {
            return (
              <div key={i} className="max-w-[92%] self-start rounded-xl rounded-bl-sm border bg-card px-4 py-2.5">
                <p className="whitespace-pre-wrap leading-relaxed">{entry.text}</p>
              </div>
            )
          }

          const { result, cards } = entry
          const badge = DECISION_BADGE[result.decision] ?? DECISION_BADGE.answered
          const consulted = [
            ...new Set(result.tool_trace.map((t) => TOOL_LABEL[t.tool] ?? t.tool)),
          ]
          return (
            <div key={i} className="flex max-w-[92%] flex-col gap-2 self-start">
              <div className="rounded-xl rounded-bl-sm border bg-card px-4 py-3">
                <Badge variant={badge.variant}>{badge.label}</Badge>
                <p className="mt-2 whitespace-pre-wrap leading-relaxed">{result.answer}</p>

                {result.case_number ? (
                  <p className="mt-2 text-sm font-medium">
                    Case {result.case_number} has been opened — quote it when you contact
                    the office.
                  </p>
                ) : null}

                {result.degraded_modes.length > 0 ? (
                  <p className="mt-2 text-sm text-muted-foreground">
                    Heads up: {describeDegradations(result.degraded_modes)}.
                  </p>
                ) : null}

                {consulted.length > 0 ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Checked: {consulted.join(" · ")}
                  </p>
                ) : null}

                {result.citations.length > 0 ? (
                  <details className="mt-1 text-xs text-muted-foreground">
                    <summary className="cursor-pointer">
                      Sources ({result.citations.length})
                    </summary>
                    <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-4">
                      {result.citations.map((c, j) => (
                        <li key={j}>{c.claim}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </div>

              {cards.map((card, j) => {
                if (card.type === "mission") {
                  return <MissionCard key={j} mission={card.mission} onOpenView={onOpenView} />
                }
                if (card.type === "sequence") {
                  return <SequenceCard key={j} plan={card.plan} onOpenView={onOpenView} />
                }
                if (card.type === "decode") {
                  return <DecodeCard key={j} decoded={card.decoded} onOpenView={onOpenView} />
                }
                return null
              })}
            </div>
          )
        })}

        {busy ? <Thinking /> : null}
        <div ref={endRef} />
      </div>

      {chips.length > 0 && !busy ? (
        <div className="flex flex-wrap gap-2">
          {chips.map((chip) => (
            <Button key={chip} size="sm" variant="outline" onClick={() => ask(chip)}>
              {chip}
            </Button>
          ))}
        </div>
      ) : null}

      <form
        className="sticky bottom-4 flex gap-2 rounded-xl border bg-card p-2 shadow-sm"
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
          className="min-w-0 flex-1 bg-transparent px-2 outline-none placeholder:text-muted-foreground"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about errors, holds, courses, your degree, next term…"
          disabled={busy}
        />
        <Button type="submit" disabled={busy || !question.trim()}>
          Ask
        </Button>
      </form>

      <p className="text-center text-xs text-muted-foreground">
        Not an NYU system. Verify anything that affects registration in Albert.
      </p>
    </div>
  )
}
