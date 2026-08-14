import { AlertTriangle, CheckCircle, HelpCircle, XCircle } from "lucide-react"
import { Chip, Sources, tone } from "@/components/make"
import { verdictMeta } from "@/lib/verdicts"

/**
 * The finding card — this product's signature surface, in the design's card language.
 *
 * Everything Path Pilot does ends in one of these: a verdict, why, what to do next, and
 * the source it rests on. It was hand-rolled eight times across four views before it was
 * extracted, and the copies disagreed about the one thing that matters — three of them
 * shipped the verdict as colour and a glyph with no text label at all.
 *
 * The API is deliberately narrow. There is **no `tone` prop**: tone comes from the
 * verdict, because the callers that hardcoded a red border and a ✕ were writing a
 * verdict without saying so. `label` overrides only the wording, never the colour, for
 * the cases where the surrounding section already names the verdict ("Accepted
 * knowingly") and repeating it reads as a stutter.
 *
 * Pass `finding` when the server handed back its standard shape; pass the fields
 * explicitly for cards built from something else (a track that does not fit, a
 * sequencing assumption). Explicit fields win, so a caller can take the object and
 * correct one part of it.
 */

const VERDICT_ICON = {
  good: CheckCircle,
  danger: XCircle,
  warn: AlertTriangle,
  neutral: HelpCircle,
}

export function Finding({
  finding,
  verdict,
  summary,
  detail,
  nextStep,
  citations,
  label,
  children,
}) {
  const f = finding ?? {}
  const meta = verdictMeta(verdict ?? f.verdict)
  summary = summary ?? f.summary
  detail = detail ?? f.detail
  nextStep = nextStep ?? f.next_step
  citations = citations ?? f.citations

  const cfg = tone(meta.tone)
  const Icon = VERDICT_ICON[meta.tone] ?? HelpCircle

  return (
    <li
      className="overflow-hidden rounded-xl"
      style={{ background: "var(--color-surface-2)", border: `1px solid ${cfg.border}` }}
    >
      <div className="px-3.5 py-3">
        <div className="flex items-start gap-2.5">
          <Icon
            size={14}
            aria-hidden="true"
            style={{ color: cfg.color, flexShrink: 0, marginTop: 1 }}
          />
          <span
            className="min-w-0 flex-1 text-[13px] leading-snug font-semibold"
            style={{ color: "var(--color-ink)" }}
          >
            {summary}
          </span>
          <Chip toneName={meta.tone}>
            {label ?? meta.label}
            <span className="visually-hidden"> — {meta.action}</span>
          </Chip>
        </div>

        {detail ? (
          <p
            className="mt-1.5 pl-6 text-[12px] leading-relaxed"
            style={{ color: "var(--color-ink-2)" }}
          >
            {detail}
          </p>
        ) : null}
        {nextStep ? (
          <p className="mt-1.5 pl-6 text-[12px]" style={{ color: "var(--color-ink)" }}>
            → {nextStep}
          </p>
        ) : null}
        <div className="pl-6">
          <Sources citations={citations} />
        </div>
        {children ? <div className="mt-2.5 flex flex-wrap items-center gap-2 pl-6">{children}</div> : null}
      </div>
    </li>
  )
}

/**
 * A retrieved bulletin passage. Not a finding, though it was once rendered with the
 * finding classes: a finding is this system's judgement about the student, a passage is
 * somebody else's published text quoted verbatim. Giving them one look invited the
 * reader to trust both the same amount, and only one of them is a claim Path Pilot is
 * making — so this is a quote block, not a card.
 */
export function Passage({ title, text, source, office, fetchedOn, url }) {
  return (
    <li
      className="rounded-xl px-3.5 py-3"
      style={{ background: "var(--color-code-bg)", border: "1px solid var(--color-rail)" }}
    >
      <p className="text-[12px] font-medium" style={{ color: "var(--color-ink)" }}>
        {title}
      </p>
      <blockquote
        className="mt-1.5 border-l-2 pl-3 text-[12px] leading-relaxed"
        style={{ borderColor: "var(--color-rail-strong)", color: "var(--color-ink-2)" }}
      >
        {text}
      </blockquote>
      <p className="mt-2 text-[10px]" style={{ color: "var(--color-ink-3)" }}>
        {url ? (
          <a href={url} target="_blank" rel="noreferrer" className="underline">
            {source}
          </a>
        ) : (
          source
        )}
        {office ? ` · ${office.replace(/_/g, " ")}` : ""}
        {fetchedOn ? ` · fetched ${fetchedOn}` : ""}
      </p>
    </li>
  )
}
