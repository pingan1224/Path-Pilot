/**
 * The small shared vocabulary of the migrated views: an eyebrow, a toned chip, an error
 * note, muted copy, and the one input style. Extracted the moment a second view needed
 * them — the finding card taught this codebase what a copied object literal does to a
 * verdict, and these are the same kind of thing one size smaller.
 *
 * `Tone` never decides meaning: callers pass the tone *and* the words, and the words must
 * carry the statement on their own — same rule as everywhere else, no colour-only signals.
 */

export function Eyebrow({ children }) {
  return (
    <p className="text-[11px] font-medium tracking-[0.12em] text-subtle uppercase">
      {children}
    </p>
  )
}

const TONE_TEXT = {
  good: "text-success",
  warn: "text-warning",
  danger: "text-destructive",
  neutral: "text-subtle",
}

const TONE_BORDER = {
  good: "border-success",
  warn: "border-warning",
  danger: "border-destructive",
  neutral: "border-border",
}

export function Tone({ tone = "neutral", children }) {
  return (
    <span
      className={`rounded border px-2 py-0.5 text-[11px] ${TONE_TEXT[tone]} ${TONE_BORDER[tone]}`}
    >
      {children}
    </span>
  )
}

export function ErrorNote({ children }) {
  return (
    <p
      role="alert"
      className="rounded-md border border-destructive/45 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-destructive"
    >
      {children}
    </p>
  )
}

export function WarnNote({ children }) {
  return (
    <p className="rounded-md border border-warning/45 px-3 py-2 text-[12px] leading-relaxed text-muted-foreground">
      {children}
    </p>
  )
}

export function Muted({ children }) {
  return <p className="text-[13px] leading-relaxed text-muted-foreground">{children}</p>
}

export const INPUT_CLASS =
  "min-w-0 flex-1 rounded-md border border-border bg-card px-3 py-2 text-[14px] " +
  "outline-none placeholder:text-subtle focus-visible:ring-2 focus-visible:ring-primary/40"
