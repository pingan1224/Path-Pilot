import { Banner, Chip } from "@/components/make"

/**
 * The small shared vocabulary of the views: an eyebrow, a toned chip, the notes, and the
 * one input style. Each is now a thin naming layer over the card language in make.jsx —
 * the shapes live there so every surface changes together, and these keep the names the
 * views already read by.
 *
 * `Tone` never decides meaning: callers pass the tone *and* the words, and the words must
 * carry the statement on their own — no colour-only signals, anywhere.
 */

/** Names the thing that follows. */
export function Eyebrow({ children }) {
  return (
    <p
      className="text-[10px] font-medium tracking-wide uppercase"
      style={{ color: "var(--color-ink-3)" }}
    >
      {children}
    </p>
  )
}

export function Tone({ tone = "neutral", children }) {
  return <Chip toneName={tone}>{children}</Chip>
}

export function ErrorNote({ children }) {
  return (
    <Banner toneName="danger" role="alert">
      {children}
    </Banner>
  )
}

export function WarnNote({ children }) {
  return <Banner toneName="warn">{children}</Banner>
}

export function Muted({ children }) {
  return (
    <p className="text-[12px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
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
    <div
      className="pp-slide-up flex flex-col items-start gap-3 rounded-2xl px-4 py-3.5"
      style={{ background: "var(--color-amber-muted)", border: "1px solid var(--color-amber-edge)" }}
    >
      <div>
        <p className="text-[13px] font-semibold" style={{ color: "var(--color-amber)" }}>
          {stated
            ? "Path Pilot does not know which program you are in."
            : "This is not available for your program."}
        </p>
        <p
          className="mt-1 max-w-[62ch] text-[12px] leading-relaxed"
          style={{ color: "var(--color-ink-2)" }}
        >
          {message}
        </p>
      </div>
      {onChooseProgram ? (
        <button
          type="button"
          className="rounded-xl px-3 py-2 text-[12px] font-medium"
          style={{
            background: "var(--color-surface-2)",
            color: "var(--color-ink-2)",
            border: "1px solid var(--color-rail-strong)",
          }}
          onClick={onChooseProgram}
        >
          {stated ? "Choose your program" : "Change your program"}
        </button>
      ) : null}
    </div>
  )
}

export const INPUT_CLASS =
  "min-w-0 flex-1 rounded-xl border px-3 py-2 text-[13px] outline-none transition-colors " +
  "border-[var(--color-rail-strong)] bg-[var(--color-surface-2)] text-[var(--color-ink)] " +
  "placeholder:text-[var(--color-ink-3)] focus-visible:border-[var(--color-violet)] " +
  "disabled:opacity-50"
