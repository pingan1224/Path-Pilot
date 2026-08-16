import { AlertTriangle, CheckCircle, ChevronDown, Info, XCircle } from "lucide-react"
import { useEffect, useRef, useState } from "react"

/**
 * The card language, defined once.
 *
 * Every surface in the app is built from these: the design's rounded-2xl card on
 * --color-surface with a rail, its rounded-xl tinted banner, its small tone chip, and
 * its measured accordion. They were being re-declared per view — PlannerView and
 * IntakeView each grew their own MakeCard — which is exactly how the pre-Figma codebase
 * ended up with eight hand-rolled finding cards that disagreed with each other. One
 * definition, so a change to the language reaches every screen at once.
 *
 * TONE is the whole colour vocabulary. Callers pass a tone and the words; the words must
 * carry the statement on their own, because nothing here is allowed to signal by colour
 * alone.
 */

export const TONE = {
  good: {
    icon: CheckCircle,
    color: "var(--color-emerald)",
    bg: "var(--color-emerald-muted)",
    border: "rgba(4,120,87,0.2)",
  },
  warn: {
    icon: AlertTriangle,
    color: "var(--color-amber)",
    bg: "var(--color-amber-muted)",
    border: "rgba(180,83,9,0.2)",
  },
  danger: {
    icon: XCircle,
    color: "var(--color-rose)",
    bg: "var(--color-rose-muted)",
    border: "rgba(190,18,60,0.2)",
  },
  info: {
    icon: Info,
    color: "var(--color-sky)",
    bg: "var(--color-sky-muted)",
    border: "rgba(96,165,250,0.2)",
  },
  accent: {
    icon: Info,
    color: "var(--color-violet-light)",
    bg: "var(--color-violet-muted)",
    border: "rgba(124,58,237,0.25)",
  },
  neutral: {
    icon: Info,
    color: "var(--color-ink-3)",
    bg: "var(--color-surface-3)",
    border: "var(--color-rail)",
  },
}

export const tone = (name) => TONE[name] ?? TONE.neutral

/** The card: a raised surface with a rail. `tone` tints the border when a card carries a
 *  verdict of its own; otherwise it is the neutral rail.
 *
 *  `pad` is a prop rather than something the caller appends to `className`, because
 *  Tailwind resolves conflicting utilities by source order, not by the order they appear
 *  in the attribute — a caller's `p-6` would not reliably beat a base `p-4`. It also
 *  carries the default: every card in the design is padded, and the shared shell losing
 *  the padding the two private copies had built in is exactly how the degree-progress
 *  page ended up flush to its own edges. */
export function MakeCard({
  children,
  delay = 0,
  toneName,
  pad = "p-4",
  className = "",
  style,
  ...rest
}) {
  return (
    <div
      className={`pp-slide-up rounded-2xl ${pad} ${className}`}
      style={{
        background: "var(--color-surface)",
        border: `1px solid ${toneName ? tone(toneName).border : "var(--color-rail-strong)"}`,
        animationDelay: `${delay}ms`,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  )
}

/** Eyebrow / title / description, the design's card header stack. */
/**
 * `titleId` exists because the cards that use this are labelled by their own heading.
 * Extracting the heading out of shadcn's CardTitle dropped the id it used to carry while
 * the aria-labelledby attributes stayed behind, so three cards pointed at elements that
 * no longer existed — which is worse than no attribute, because a dangling reference
 * suppresses the fallback naming instead of falling back to it.
 */
export function CardHeading({ eyebrow, title, titleId, desc, right }) {
  return (
    <div className="mb-3 flex items-start justify-between gap-3">
      <div className="min-w-0">
        {eyebrow ? (
          <div
            className="mb-1 text-[10px] font-medium tracking-wide uppercase"
            style={{ color: "var(--color-ink-3)" }}
          >
            {eyebrow}
          </div>
        ) : null}
        {title ? (
          <div
            id={titleId}
            className="text-[14px] font-semibold"
            style={{ color: "var(--color-ink)" }}
          >
            {title}
          </div>
        ) : null}
        {desc ? (
          <p className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
            {desc}
          </p>
        ) : null}
      </div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </div>
  )
}

/**
 * The tinted banner: an icon, a bold line, and the body. Every note in the product is
 * one of these — the error, the caveat, the privacy disclosure, the boundary statement.
 * `role` is the caller's, because only they know whether a banner is an alert.
 */
export function Banner({ toneName = "info", title, children, icon, role, className = "" }) {
  const cfg = tone(toneName)
  const Icon = icon ?? cfg.icon
  return (
    <div
      role={role}
      className={`flex items-start gap-2.5 rounded-xl px-4 py-2.5 ${className}`}
      style={{ background: cfg.bg, border: `1px solid ${cfg.border}` }}
    >
      <Icon
        size={12}
        aria-hidden="true"
        style={{ color: cfg.color, flexShrink: 0, marginTop: 3 }}
      />
      <div className="min-w-0">
        {title ? (
          <div className="text-[12px] font-semibold" style={{ color: cfg.color }}>
            {title}
          </div>
        ) : null}
        <div
          className="text-[11px] leading-relaxed"
          style={{ color: cfg.color, opacity: title ? 0.8 : 1 }}
        >
          {children}
        </div>
      </div>
    </div>
  )
}

/** The small tone pill — a state named in words on its own tint. */
export function Chip({ toneName = "neutral", children, icon }) {
  const cfg = tone(toneName)
  const Icon = icon
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium"
      style={{ background: cfg.bg, color: cfg.color }}
    >
      {Icon ? <Icon size={10} aria-hidden="true" /> : null}
      {children}
    </span>
  )
}

/** A course code, wherever one appears. */
export function Code({ children }) {
  return (
    <span
      className="text-[11px] font-medium"
      style={{ fontFamily: "var(--font-mono)", color: "var(--color-violet-light)" }}
    >
      {children}
    </span>
  )
}

/**
 * The design's accordion: a header row that toggles, a body measured to its content.
 *
 * The body is watched rather than measured per render. Measuring in a dep-less effect
 * looked like it covered everything and covered less: a render is not what makes the body
 * taller. A native <details> opening inside it, a generated handoff summary arriving, or
 * the window being narrowed all change the height with no React render to notice, and the
 * frozen max-height clipped exactly the content the reader had just asked for — citations,
 * next steps. It also forced a synchronous reflow on every render of every instance.
 */
export function Accordion({ open, onToggle, header, children, toneName, delay = 0 }) {
  const bodyRef = useRef(null)
  useEffect(() => {
    const el = bodyRef.current
    if (!el) return undefined
    const measure = () => {
      el.style.maxHeight = open ? `${el.scrollHeight}px` : "0px"
    }
    measure()
    if (!open || typeof ResizeObserver === "undefined") return undefined
    const observer = new ResizeObserver(measure)
    // The inner wrapper is what grows; the observed element must not be the one whose
    // max-height we set, or the observer feeds itself.
    if (el.firstElementChild) observer.observe(el.firstElementChild)
    return () => observer.disconnect()
  }, [open, children])

  return (
    <div
      className="pp-slide-up overflow-hidden rounded-xl"
      style={{
        background: "var(--color-surface)",
        border: `1px solid ${toneName ? tone(toneName).border : "var(--color-rail-strong)"}`,
        animationDelay: `${delay}ms`,
      }}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-4 py-3.5 text-left"
        style={{ transition: "background 140ms ease" }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "rgba(124,58,237,0.03)"
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = ""
        }}
      >
        {header}
        <div
          style={{
            transform: open ? "rotate(0deg)" : "rotate(-90deg)",
            transition: "transform 220ms cubic-bezier(0.22,1,0.36,1)",
            color: "var(--color-ink-3)",
            flexShrink: 0,
          }}
        >
          <ChevronDown size={13} aria-hidden="true" />
        </div>
      </button>
      {/* `inert` while collapsed: max-height hides pixels, not focus. Without it every
          step body stays in the tab order and the accessibility tree, so a keyboard user
          tabs from a header straight into a course-code input they cannot see, and a
          screen reader reads every section as though it were expanded — contradicting the
          aria-expanded="false" on the header directly above. */}
      <div
        ref={bodyRef}
        className="pp-accordion"
        style={{ maxHeight: 0 }}
        inert={!open}
      >
        <div className="px-4 pb-3.5" style={{ borderTop: "1px solid var(--color-rail)" }}>
          {children}
        </div>
      </div>
    </div>
  )
}

/** A collapsed citation list — the reader who doubts a claim opens it. */
export function Sources({ citations }) {
  if (!citations?.length) return null
  return (
    <details className="mt-2 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
      <summary className="cursor-pointer">
        {citations.length === 1 ? "Source" : `${citations.length} sources`}
      </summary>
      <ul className="mt-1 space-y-1">
        {citations.map((c, i) => (
          <li key={i}>
            {c.url ? (
              <a href={c.url} target="_blank" rel="noreferrer" className="underline">
                {c.label}
              </a>
            ) : (
              c.label
            )}
            {c.verified_on ? ` · checked ${c.verified_on}` : ""}
            {c.quote ? (
              <span
                className="mt-0.5 block rounded px-2 py-1"
                style={{ background: "var(--color-code-bg)", fontFamily: "var(--font-mono)" }}
              >
                “{c.quote}”
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </details>
  )
}

/** Body copy inside a card. */
export function Muted({ children }) {
  return (
    <p className="text-[12px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
      {children}
    </p>
  )
}

/**
 * Open state that follows a prop until the reader overrides it, then follows it again the
 * next time the prop actually changes.
 *
 * `useState(defaultOpen)` read the prop once, which is not what the callers assume. The
 * planner keys each section on the finding key, which is deliberately stable across
 * re-evaluations and independent of the verdict, so nothing ever remounts: a requirement
 * that read "Met" (and therefore rendered collapsed) stayed collapsed after a refetch
 * flipped it to not met, hiding the new failure's detail, its next step and its citations
 * behind a closed row. Status hierarchy inverted exactly when a requirement broke.
 */
export function useDisclosure(defaultOpen) {
  const [state, setState] = useState({ open: defaultOpen, seen: defaultOpen })
  if (state.seen !== defaultOpen) setState({ open: defaultOpen, seen: defaultOpen })
  const open = state.seen === defaultOpen ? state.open : defaultOpen
  return [open, () => setState((s) => ({ ...s, open: !s.open }))]
}
