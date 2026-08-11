/**
 * The small shared vocabulary of the migrated views: an eyebrow, a toned chip, an error
 * note, muted copy, and the one input style. Extracted the moment a second view needed
 * them — the finding card taught this codebase what a copied object literal does to a
 * verdict, and these are the same kind of thing one size smaller.
 *
 * `Tone` never decides meaning: callers pass the tone *and* the words, and the words must
 * carry the statement on their own — same rule as everywhere else, no colour-only signals.
 */

/** Names the thing that follows. Condensed and tracked — the label width of the scale. */
export function Eyebrow({ children }) {
  return <p className="nx-label">{children}</p>
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
      className={`rounded border px-2 py-0.5 text-micro ${TONE_TEXT[tone]} ${TONE_BORDER[tone]}`}
    >
      {children}
    </span>
  )
}

export function ErrorNote({ children }) {
  return (
    <p
      role="alert"
      className="rounded-md border border-destructive/45 px-3.5 py-2.5 text-meta leading-relaxed text-destructive"
    >
      {children}
    </p>
  )
}

/**
 * True when a failure is about which program the student is in, rather than a fault.
 * Callers branch on this to choose between ProgramNotice and their own error handling.
 */
export function isProgramIssue(code) {
  return code === "program_not_stated" || code === "program_not_encoded"
}

/**
 * The screen a student sees when a tool cannot serve their program.
 *
 * Two causes, and they are not the same message. `program_not_stated` means they have not
 * said what they study — one action fixes it. `program_not_encoded` means they said
 * something true and this tool has not transcribed that degree's requirements; there is
 * nothing for them to fix, and offering a "Try again" button would imply otherwise.
 *
 * Returns null for any other error so callers fall through to their own handling —
 * this component answers one question and must not swallow unrelated failures.
 */
export function ProgramNotice({ code, message, onChooseProgram }) {
  if (!isProgramIssue(code)) return null

  const stated = code === "program_not_stated"
  return (
    <div className="flex flex-col items-start gap-3 rounded-md border border-warning/45 px-4 py-3.5">
      <div>
        <p className="text-body">
          {stated
            ? "Path Pilot does not know which program you are in."
            : "This is not available for your program."}
        </p>
        <p className="mt-1 max-w-[62ch] text-meta leading-relaxed text-muted-foreground">
          {message}
        </p>
      </div>
      {onChooseProgram ? (
        <button
          type="button"
          className="rounded-md border border-border px-3 py-1.5 text-meta hover:bg-secondary"
          onClick={onChooseProgram}
        >
          {stated ? "Choose your program" : "Change your program"}
        </button>
      ) : null}
    </div>
  )
}

export function WarnNote({ children }) {
  return (
    <p className="rounded-md border border-warning/45 px-3 py-2 text-meta leading-relaxed text-muted-foreground">
      {children}
    </p>
  )
}

export function Muted({ children }) {
  return <p className="text-body leading-relaxed text-muted-foreground">{children}</p>
}

export const INPUT_CLASS =
  "min-w-0 flex-1 rounded-md border border-border bg-card px-3 py-2 text-lead " +
  "outline-none transition-colors placeholder:text-subtle hover:border-subtle " +
  "focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50"
