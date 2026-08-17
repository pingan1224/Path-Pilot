import { useEffect, useRef, useState } from "react"
import {
  AlertCircle,
  AlertTriangle,
  BookOpen,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Compass,
  Info,
  Send,
  Sparkles,
} from "lucide-react"
import { api } from "@/api"
import { ArtifactCard } from "@/components/chat/cards"
import { describeDegradations } from "@/lib/degradations"
import { usePrefs } from "@/i18n"

/**
 * The conversation surface, wearing the source design's ChatView 1:1: header with a
 * status dot, sky disclaimer banner, avatar bubbles with bylines and confidence
 * badges, bouncing typing dots, "N sources used" disclosure, a right-hand Sources
 * panel, pill suggestion chips, and the growing composer with the round-cornered send
 * button.
 *
 * Everything the design scripted is real here. The design's choreographed demo (four
 * hardcoded messages, a staged error decode) is replaced by the actual agent loop:
 * answers arrive from /assistant/ask with decisions, citations, artifacts and degraded
 * modes; the badges map decisions, the SourceCards render what tools actually returned,
 * and the Sources panel is the audit trail (rule 7), not set dressing. The greeting is
 * computed, never generated; history is text-only, capped at 6 turns.
 */

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

/** Decision → the design's confidence-badge language. Icons echo the design's
 *  STATUS_CFG; the label still carries the meaning on its own. */
const DECISION_BADGE = {
  answered: { icon: CheckCircle, key: "kicker.answered", color: "var(--color-emerald)", bg: "var(--color-emerald-muted)" },
  answered_with_caveat: { icon: Clock, key: "kicker.caveat", color: "var(--color-amber)", bg: "var(--color-amber-muted)" },
  deferred: { icon: AlertCircle, key: "kicker.deferred", color: "var(--color-amber)", bg: "var(--color-amber-muted)" },
  refused: { icon: AlertTriangle, key: "kicker.refused", color: "var(--color-rose)", bg: "var(--color-rose-muted)" },
}

function timeString(at, locale) {
  return at.toLocaleTimeString(locale === "zh" ? "zh-Hans" : "en-US", {
    hour: "numeric",
    minute: "2-digit",
  })
}

function BotAvatar() {
  return (
    <div
      aria-hidden="true"
      className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
      style={{ background: "linear-gradient(135deg, var(--color-violet), var(--color-violet-dim))" }}
    >
      <Compass size={13} style={{ color: "var(--on-accent)" }} />
    </div>
  )
}

function UserAvatar({ initials }) {
  return (
    <div
      aria-hidden="true"
      className="mt-6 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
      style={{
        background: "var(--color-surface-3)",
        border: "1px solid var(--color-rail-strong)",
        color: "var(--color-ink-2)",
      }}
    >
      {initials}
    </div>
  )
}

/** The design's typing indicator — three bouncing dots — plus the one real number the
 *  wait has (elapsed seconds), kept because an honest wait outranks a cute one. */
function TypingDots({ t }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [])
  return (
    <div className="flex gap-3" role="status">
      <BotAvatar />
      <div className="min-w-0">
        <div
          className="flex items-center gap-1 rounded-2xl rounded-tl-sm px-4 py-3"
          style={{
            background: "var(--color-bubble-agent)",
            border: "1px solid var(--color-rail-strong)",
            width: "fit-content",
          }}
        >
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-1.5 w-1.5 rounded-full"
              style={{
                background: "var(--color-ink-3)",
                animation: `pp-dot 1.2s ease-in-out ${i * 0.18}s infinite`,
              }}
            />
          ))}
        </div>
        <div className="mt-1 text-[10px]" style={{ color: "var(--color-ink-3)" }}>
          {t("chat.thinking")}
          <span className="nx-figure">{seconds}s</span>
          {seconds > 20 ? t("chat.thinking.long") : ""}
        </div>
      </div>
    </div>
  )
}

/** The design's SourceCard, fed by real audit data: what a tool call was, what it
 *  returned, and whether the answer could cite it. */
function SourceCard({ entry, delay }) {
  const cfg =
    entry.tone === "danger"
      ? { icon: AlertCircle, color: "var(--color-rose)", bg: "var(--color-rose-muted)" }
      : entry.tone === "good"
        ? { icon: CheckCircle, color: "var(--color-emerald)", bg: "var(--color-emerald-muted)" }
        : entry.tone === "warn"
          ? { icon: Clock, color: "var(--color-amber)", bg: "var(--color-amber-muted)" }
          : { icon: Info, color: "var(--color-sky)", bg: "var(--color-sky-muted)" }
  const Icon = cfg.icon
  return (
    <div
      className="rounded-xl p-3"
      style={{
        background: "var(--color-surface-2)",
        border: "1px solid var(--color-rail-strong)",
        animation: `pp-slide-up 260ms cubic-bezier(0.22,1,0.36,1) ${delay}ms both`,
      }}
    >
      <div className="mb-2 text-[12px] leading-snug font-medium" style={{ color: "var(--color-ink)" }}>
        {entry.label}
      </div>
      <div className="flex items-center justify-between">
        <div
          className="flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium"
          style={{ background: cfg.bg, color: cfg.color }}
        >
          <Icon size={10} aria-hidden="true" />
          {entry.meta}
        </div>
      </div>
    </div>
  )
}

/** Where the student stands — computed, not generated; chips are dictionary keys. */
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
  return { status: t("greet.empty"), chips: ["chip.prereq", "chip.first"] }
}

export default function ChatHome({
  me,
  active,
  missions,
  courses,
  ready,
  loadFailed,
  onOpenView,
  onTurn,
}) {
  const { t, locale } = usePrefs()
  const [thread, setThread] = useState([])
  const [question, setQuestion] = useState("")
  const [chips, setChips] = useState([])
  const [busy, setBusy] = useState(false)
  const [sourcesOpen, setSourcesOpen] = useState({})
  const greeted = useRef(null)
  const endRef = useRef(null)

  const initials = (me.full_name ?? "?")
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase()

  useEffect(() => {
    if (greeted.current === "ready") return
    const first = (me.full_name ?? "").split(" ")[0]
    if (ready) {
      const recovering = greeted.current === "failed"
      greeted.current = "ready"
      const greeting = greetingFor(missions, courses.length, t)
      const note = {
        kind: "assistant-note",
        text: recovering
          ? t("greet.recovered", { status: greeting.status })
          : t("greet.hi", { name: first, status: greeting.status }),
      }
      setThread((prev) => (recovering ? [...prev, note] : [note]))
      setChips(greeting.chips)
    } else if (loadFailed && greeted.current === null) {
      greeted.current = "failed"
      setThread([{ kind: "assistant-note", text: t("greet.failed", { name: first }) }])
      setChips(["chip.prereq", "chip.holds"])
    }
  }, [ready, loadFailed, missions, courses, me.full_name, t])

  useEffect(() => {
    if (!active) return
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [thread, busy, active])

  async function ask(text) {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    setQuestion("")
    setChips([])
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
      onTurn?.()
    } catch (err) {
      setThread((prev) => [...prev, { kind: "error", text: trimmed, message: err.message }])
    } finally {
      setBusy(false)
    }
  }

  /** The audit trail, per turn, for the Sources panel — real rule-7 data. */
  const auditEntries = []
  thread.forEach((entry, turn) => {
    if (entry.kind !== "assistant") return
    entry.result.tool_trace.forEach((call, i) => {
      auditEntries.push({
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
      auditEntries.push({
        id: `${turn}-d${i}`,
        label: t("audit.degraded"),
        meta: describeDegradations([mode]),
        tone: "warn",
      })
    })
  })

  const landing = !busy && thread.every((e) => e.kind === "assistant-note")

  return (
    <div className="flex h-full overflow-hidden">
      {/* Thread */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Header — the design's, with a real status dot: emerald when the record read
            is healthy, rose when it failed. */}
        <div
          className="pp-slide-down flex shrink-0 items-center gap-3 px-6 py-4"
          style={{ borderBottom: "1px solid var(--color-rail)", background: "var(--color-surface)" }}
        >
          <Sparkles size={15} style={{ color: "var(--color-violet-light)" }} aria-hidden="true" />
          <div>
            <div className="text-[14px] font-semibold" style={{ color: "var(--color-ink)" }}>
              {t("nav.chat")}
            </div>
            <div className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
              {t("chat.subtitle")}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div
              className="h-2 w-2 rounded-full"
              style={{ background: loadFailed ? "var(--color-rose)" : "var(--color-emerald)" }}
              aria-hidden="true"
            />
            <span className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
              {loadFailed ? t("rail.failed") : t("chat.ready")}
            </span>
          </div>
        </div>

        {/* Messages */}
        <div className="nx-scroll flex-1 space-y-6 overflow-y-auto px-6 py-5">
          {/* Disclaimer banner — the design's sky card, carrying the real claim. */}
          <div
            className="pp-fade-in flex items-start gap-2.5 rounded-xl px-3 py-2.5"
            style={{
              background: "var(--color-sky-muted)",
              border: "1px solid var(--color-sky-edge)",
              animationDelay: "80ms",
            }}
          >
            <Info size={12} style={{ color: "var(--color-sky)", flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
            <p className="text-[12px] leading-relaxed" style={{ color: "var(--color-sky)" }}>
              {t("chat.disclaimer")}
            </p>
          </div>

          {thread.map((entry, i) => {
            if (entry.kind === "assistant-note") {
              return (
                <div key={i} className="pp-slide-up flex items-start gap-3">
                  <BotAvatar />
                  <div className="min-w-0 flex-1 space-y-1">
                    <span className="text-[12px] font-semibold" style={{ color: "var(--color-violet-light)" }}>
                      {t("chat.assistant")}
                    </span>
                    <div
                      className="rounded-2xl rounded-tl-sm px-4 py-3"
                      style={{
                        background: "var(--color-bubble-agent)",
                        border: "1px solid var(--color-rail-strong)",
                        width: "fit-content",
                        maxWidth: "100%",
                      }}
                    >
                      <p className="text-[13px] leading-relaxed whitespace-pre-wrap" style={{ color: "var(--color-ink)" }}>
                        {entry.text}
                      </p>
                    </div>
                  </div>
                </div>
              )
            }

            if (entry.kind === "user") {
              return (
                <div key={i} className="pp-slide-up flex items-start justify-end gap-3">
                  <div className="max-w-[72%]">
                    <div className="mb-1 flex items-center justify-end gap-2">
                      <span className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                        {timeString(entry.at, locale)}
                      </span>
                      <span className="text-[12px] font-semibold" style={{ color: "var(--color-ink-2)" }}>
                        {t("chat.you")}
                      </span>
                    </div>
                    <div
                      className="rounded-2xl rounded-tr-sm px-4 py-3"
                      style={{
                        background: "var(--color-violet-muted)",
                        border: "1px solid var(--color-violet-edge)",
                      }}
                    >
                      <p className="text-[13px] leading-relaxed whitespace-pre-wrap" style={{ color: "var(--color-ink)" }}>
                        {entry.text}
                      </p>
                    </div>
                  </div>
                  <UserAvatar initials={initials} />
                </div>
              )
            }

            if (entry.kind === "error") {
              return (
                <div key={i} className="pp-slide-up flex items-start gap-3" role="alert">
                  <BotAvatar />
                  <div className="min-w-0 flex-1 space-y-2">
                    <div
                      className="flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium"
                      style={{ background: "var(--color-rose-muted)", color: "var(--color-rose)", width: "fit-content" }}
                    >
                      <AlertTriangle size={10} aria-hidden="true" />
                      {t("chat.error.kicker")}
                    </div>
                    <p className="text-[13px] leading-relaxed" style={{ color: "var(--color-ink)" }}>
                      {entry.message}
                    </p>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => ask(entry.text)}
                      className="rounded-xl px-3 py-1.5 text-[12px] font-medium"
                      style={{
                        background: "var(--color-surface-2)",
                        color: "var(--color-ink-2)",
                        border: "1px solid var(--color-rail-strong)",
                      }}
                    >
                      {t("chat.error.retry")}
                    </button>
                  </div>
                </div>
              )
            }

            const { result } = entry
            const badge = DECISION_BADGE[result.decision] ?? DECISION_BADGE.answered
            const BadgeIcon = badge.icon
            const artifacts = result.artifacts ?? []
            const showBoundary =
              result.decision === "refused" || result.decision === "deferred"
            const turnSources = result.tool_trace.map((call, j) => ({
              id: `${i}-${j}`,
              label: toolLabel(t, call.tool),
              meta: call.failed
                ? t("audit.failed")
                : call.source_ids?.length
                  ? t("audit.sources", { count: call.source_ids.length })
                  : t("audit.noSources"),
              tone: call.failed ? "danger" : call.source_ids?.length ? "good" : "neutral",
            }))
            const open = sourcesOpen[i]

            return (
              <div key={i} className="pp-slide-up flex items-start gap-3">
                <BotAvatar />
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[12px] font-semibold" style={{ color: "var(--color-violet-light)" }}>
                      {t("chat.assistant")}
                    </span>
                    <span className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                      {timeString(entry.at, locale)}
                    </span>
                    <span
                      className="pp-badge-pop flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium"
                      style={{ background: badge.bg, color: badge.color }}
                    >
                      <BadgeIcon size={10} aria-hidden="true" />
                      {t(badge.key)}
                    </span>
                  </div>

                  <div
                    className="rounded-2xl rounded-tl-sm px-4 py-3"
                    style={{
                      background: "var(--color-bubble-agent)",
                      border: "1px solid var(--color-rail-strong)",
                    }}
                  >
                    <p
                      className="text-[13px] leading-relaxed whitespace-pre-wrap"
                      style={{ color: "var(--color-ink)" }}
                    >
                      {result.answer}
                    </p>
                  </div>

                  {/* Where the case-number chip used to be. A number implied someone had
                      received the question; nothing was ever submitted anywhere, so what
                      goes here instead is the thing the student can actually act on —
                      who owns it, and what to walk in with. */}
                  {result.referral ? (
                    <div
                      className="rounded-xl px-3 py-2.5 text-[12px] leading-relaxed"
                      style={{
                        background: "var(--color-violet-muted)",
                        border: "1px solid var(--color-violet-edge)",
                        color: "var(--color-ink)",
                      }}
                    >
                      <div className="font-medium" style={{ color: "var(--color-violet-light)" }}>
                        {t("chat.referral.title", {
                          office: t(`office.${result.referral.office}`),
                        })}
                      </div>
                      {result.referral.question ? (
                        <div className="mt-1">{result.referral.question}</div>
                      ) : null}
                      {result.referral.bring ? (
                        <div className="mt-1" style={{ color: "var(--color-ink-3)" }}>
                          {t("chat.referral.bring", { what: result.referral.bring })}
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {artifacts.length > 0 ? (
                    <div className="space-y-2">
                      {artifacts.map((artifact) => (
                        <ArtifactCard key={artifact.id} artifact={artifact} onOpenView={onOpenView} />
                      ))}
                    </div>
                  ) : null}

                  {result.degraded_modes.length > 0 ? (
                    <div
                      className="flex items-start gap-2 rounded-xl px-3 py-2.5"
                      style={{ background: "var(--color-amber-muted)", border: "1px solid var(--color-amber-edge)" }}
                    >
                      <AlertTriangle size={11} style={{ color: "var(--color-amber)", flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
                      <p className="text-[11px] leading-relaxed" style={{ color: "var(--color-amber)" }}>
                        <span className="font-semibold">{t("chat.degraded")}</span>
                        {describeDegradations(result.degraded_modes)}.
                      </p>
                    </div>
                  ) : null}

                  {showBoundary ? (
                    <div
                      className="rounded-xl px-3 py-2.5 text-[11px] leading-relaxed"
                      style={{
                        background: "var(--color-sky-muted)",
                        border: "1px solid var(--color-sky-edge)",
                        color: "var(--color-sky)",
                      }}
                    >
                      {t("chat.boundary")}
                    </div>
                  ) : null}

                  {/* The design's "N sources used" disclosure, on real trace data. */}
                  {turnSources.length > 0 ? (
                    <div className="space-y-1.5">
                      <button
                        type="button"
                        onClick={() => setSourcesOpen((s) => ({ ...s, [i]: !s[i] }))}
                        className="flex items-center gap-1.5 text-[12px]"
                        style={{ color: open ? "var(--color-violet-light)" : "var(--color-ink-3)" }}
                      >
                        <BookOpen size={12} aria-hidden="true" />
                        {t("chat.sourcesUsed", { count: turnSources.length })}
                        {open ? <ChevronUp size={12} aria-hidden="true" /> : <ChevronDown size={12} aria-hidden="true" />}
                      </button>
                      {open ? (
                        <div className="space-y-1.5">
                          {turnSources.map((s, j) => (
                            <SourceCard key={s.id} entry={s} delay={j * 50} />
                          ))}
                        </div>
                      ) : null}
                      {result.citations.length > 0 ? (
                        <details className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                          <summary className="cursor-pointer">
                            {t("chat.citations", { count: result.citations.length })}
                          </summary>
                          <ul className="mt-1 list-disc space-y-0.5 pl-4">
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

          {busy ? <TypingDots t={t} /> : null}
          <div ref={endRef} />
        </div>

        {/* Suggestions — the design's pills, staggered in. */}
        {chips.length > 0 && !busy ? (
          <div className="flex shrink-0 flex-wrap gap-2 px-6 py-2" style={{ borderTop: "1px solid var(--color-rail)" }}>
            {chips.map((chip, i) => (
              <button
                key={chip}
                type="button"
                onClick={() => ask(t(chip))}
                className="rounded-full px-3 py-1.5 text-[12px]"
                style={{
                  background: "var(--color-bubble-agent)",
                  border: "1px solid var(--color-rail-strong)",
                  color: "var(--color-ink-2)",
                  transition: "border-color 160ms ease, color 160ms ease, transform 160ms ease",
                  animation: `pp-slide-up 240ms cubic-bezier(0.22,1,0.36,1) ${i * 40 + (landing ? 400 : 0)}ms both`,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--color-violet-edge-strong)"
                  e.currentTarget.style.color = "var(--color-ink)"
                  e.currentTarget.style.transform = "translateY(-1px)"
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "var(--color-rail-strong)"
                  e.currentTarget.style.color = "var(--color-ink-2)"
                  e.currentTarget.style.transform = "translateY(0)"
                }}
              >
                {t(chip)}
              </button>
            ))}
          </div>
        ) : null}

        {/* Composer — the design's growing textarea and send tile. */}
        <div className="shrink-0 px-4 py-3" style={{ borderTop: "1px solid var(--color-rail)" }}>
          <form
            className="flex items-end gap-2 rounded-xl px-3 py-2"
            style={{ background: "var(--color-bubble-agent)", border: "1px solid var(--color-rail-strong)" }}
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
              value={question}
              disabled={busy}
              placeholder={t("chat.placeholder")}
              className="flex-1 resize-none bg-transparent py-1 text-[13px] leading-relaxed outline-none"
              style={{ color: "var(--color-ink)", maxHeight: 100 }}
              onChange={(e) => {
                setQuestion(e.target.value)
                e.target.style.height = "auto"
                e.target.style.height = `${Math.min(e.target.scrollHeight, 100)}px`
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  ask(question)
                  e.target.style.height = "auto"
                }
              }}
            />
            <button
              type="submit"
              disabled={busy || !question.trim()}
              aria-label={t("chat.send")}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
              style={{
                background: question.trim() ? "var(--color-violet)" : "var(--color-surface-3)",
                color: question.trim() ? "#fff" : "var(--color-ink-3)",
                transition: "background 160ms ease, color 160ms ease, transform 160ms ease",
              }}
              onMouseDown={(e) => {
                e.currentTarget.style.transform = "scale(0.92)"
              }}
              onMouseUp={(e) => {
                e.currentTarget.style.transform = "scale(1)"
              }}
            >
              <Send size={14} aria-hidden="true" />
            </button>
          </form>
          <div className="mt-1.5 text-center text-[10px]" style={{ color: "var(--color-ink-3)" }}>
            {t("chat.footer")}
          </div>
        </div>
      </div>

      {/* Sources panel — the design's right rail, holding the real audit trail. Appears
          once there is anything to show, like the design's post-answer state. */}
      {auditEntries.length > 0 ? (
        <div
          className="pp-slide-right hidden w-72 shrink-0 flex-col overflow-hidden lg:flex"
          style={{ borderLeft: "1px solid var(--color-rail)", background: "var(--color-surface)" }}
          aria-label={t("audit.aria")}
        >
          <div
            className="flex shrink-0 items-center justify-between px-4 py-3"
            style={{ borderBottom: "1px solid var(--color-rail)" }}
          >
            <div className="flex items-center gap-2">
              <BookOpen size={13} style={{ color: "var(--color-ink-3)" }} aria-hidden="true" />
              <span className="text-[12px] font-medium" style={{ color: "var(--color-ink-2)" }}>
                {t("chat.sources")}
              </span>
            </div>
          </div>
          <div className="nx-scroll flex-1 space-y-3 overflow-y-auto p-3">
            <p className="text-[11px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
              {t("audit.desc")}
            </p>
            {auditEntries.map((entry, i) => (
              <SourceCard key={entry.id} entry={entry} delay={i * 40} />
            ))}
            <div
              className="rounded-xl px-3 py-2.5"
              style={{ background: "var(--color-amber-muted)", border: "1px solid var(--color-amber-edge)" }}
            >
              <div className="flex items-start gap-2">
                <AlertTriangle size={11} style={{ color: "var(--color-amber)", flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
                <p className="text-[11px] leading-relaxed" style={{ color: "var(--color-amber)" }}>
                  {t("chat.footer")}
                </p>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
