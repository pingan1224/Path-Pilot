import { useState } from "react"
import { api } from "@/api"
import { Finding, Passage } from "@/components/Finding"
import { ErrorNote, Eyebrow, INPUT_CLASS, Muted, Tone, WarnNote } from "@/components/nocturne"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

/**
 * The error decoder: paste what Albert said, get a reading with its evidence.
 *
 * Two layout decisions carry the trust model.
 *
 * The pasted message is echoed back with the matched words highlighted, above the verdict
 * rather than hidden behind a disclosure. A classifier that shows its trigger can be
 * checked by the person it is talking to: "requisites not met" lit up, so the prerequisite
 * reading is obviously right, and if the wrong words lit up the student sees that too.
 *
 * When the message is consistent with several causes, both readings render side by side
 * with the question that separates them, and neither is styled as the answer. The
 * temptation is to show the leading candidate and mention the other in small print; that
 * is a guess with a hedge attached, and a student in a hurry reads only the guess.
 */

const OUTCOME_META = {
  identified: { tone: "good", label: "Cause identified" },
  ambiguous: { tone: "warn", label: "Needs one more detail" },
  unrecognized: { tone: "neutral", label: "Could not decode this" },
}

const EVIDENCE_TITLE = {
  code: "Error code — written by the system, near-conclusive",
  phrase: "Phrase match",
  keyword: "Single suggestive word — not enough on its own",
}

const OFFICE_LABEL = {
  registrar: "Registrar",
  bursar: "Bursar",
  financial_aid: "Financial Aid",
  advising: "Academic advising",
  department: "The department or program",
  international: "Office of Global Services",
}

const SAMPLES = [
  "ERR_PREREQ: Requisites not met for this class",
  "ERR_HOLD_ACTIVE: Registration blocked (hold code SF2)",
  "ERR_RESERVE: Reserved capacity requirement not met",
]

/**
 * Split the text into highlighted and plain runs.
 *
 * Offsets come from the server and index `text_used`, which is why that string is
 * rendered here rather than the textarea's current contents — the student may have kept
 * typing, and a highlight computed against one string and painted onto another lands on
 * the wrong words.
 */
function segment(text, evidence) {
  const spans = [...evidence]
    .filter((e) => e.end > e.start)
    .sort((a, b) => a.start - b.start || b.end - a.end)

  const merged = []
  for (const span of spans) {
    const last = merged[merged.length - 1]
    if (last && span.start < last.end) {
      // Overlapping matches keep the stronger label: a keyword inside a phrase should
      // read as part of the phrase, not as independent evidence.
      last.end = Math.max(last.end, span.end)
      if (last.kind !== "code" && span.kind === "code") last.kind = "code"
      else if (last.kind === "keyword" && span.kind === "phrase") last.kind = "phrase"
      continue
    }
    merged.push({ ...span })
  }

  const out = []
  let at = 0
  for (const span of merged) {
    if (span.start > at) out.push({ text: text.slice(at, span.start), kind: null })
    out.push({ text: text.slice(span.start, span.end), kind: span.kind })
    at = span.end
  }
  if (at < text.length) out.push({ text: text.slice(at), kind: null })
  return out
}

export default function DecoderView({ onOpenPlanner }) {
  const [text, setText] = useState("")
  const [result, setResult] = useState(null)
  const [answers, setAnswers] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function run(message, replies = {}) {
    const trimmed = (message ?? "").trim()
    if (trimmed.length < 2 || busy) return
    setBusy(true)
    setError(null)
    try {
      const answerList = Object.values(replies).filter((a) => a && a.trim())
      setResult(await api.decode(trimmed, answerList))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function reset() {
    setResult(null)
    setAnswers({})
    setError(null)
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <Eyebrow>Registration error</Eyebrow>
          <CardTitle>What did Albert tell you?</CardTitle>
          <CardDescription>
            Paste the message exactly as it appeared, error code and all. Nothing else needs
            to be filled in first — this works on your first visit.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <form
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              setAnswers({})
              run(text)
            }}
          >
            <label className="visually-hidden" htmlFor="decoder-input">
              The error message
            </label>
            <textarea
              id="decoder-input"
              className={`${INPUT_CLASS} w-full font-mono text-body`}
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="e.g. ERR_PREREQ: Requisites not met for this class"
              disabled={busy}
            />
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={busy || text.trim().length < 2}>
                {busy ? "Reading it…" : "Decode"}
              </Button>
              {result ? (
                <Button type="button" variant="outline" onClick={reset}>
                  Clear
                </Button>
              ) : null}
            </div>
          </form>

          {!result ? (
            <div className="flex flex-col items-start gap-2">
              <Muted>Or try one of these:</Muted>
              {SAMPLES.map((sample) => (
                <Button
                  key={sample}
                  size="sm"
                  variant="outline"
                  className="h-auto rounded-full py-1.5 text-left font-mono text-meta whitespace-normal"
                  onClick={() => {
                    setText(sample)
                    setAnswers({})
                    run(sample)
                  }}
                >
                  {sample}
                </Button>
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {error ? (
        <div className="flex flex-col items-start gap-2">
          <ErrorNote>{error}</ErrorNote>
          <Button variant="outline" size="sm" onClick={() => run(text, answers)}>
            Try again
          </Button>
        </div>
      ) : null}

      {result ? (
        <Result
          result={result}
          answers={answers}
          onAnswer={(key, value) => setAnswers((a) => ({ ...a, [key]: value }))}
          onResubmit={() => run(text, answers)}
          busy={busy}
          onOpenPlanner={onOpenPlanner}
        />
      ) : null}
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

function Result({ result, answers, onAnswer, onResubmit, busy, onOpenPlanner }) {
  const meta = OUTCOME_META[result.outcome] ?? OUTCOME_META.unrecognized
  // Ambiguity means the leading candidates are all in play, so all of their evidence is
  // worth showing. Identified results highlight only the winner's.
  const shown =
    result.outcome === "identified" ? result.candidates.slice(0, 1) : result.candidates.slice(0, 2)
  const evidence = shown.flatMap((c) => c.evidence)

  return (
    <>
      <Card className="border-primary/30">
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2.5">
            <Tone tone={meta.tone}>{meta.label}</Tone>
            {result.reason_label ? <CardTitle>{result.reason_label}</CardTitle> : null}
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="rounded-md border border-border bg-muted/40 p-3 font-mono text-body leading-relaxed whitespace-pre-wrap">
            {segment(result.text_used, evidence).map((run, i) =>
              run.kind ? (
                <mark key={i} className={`ev ev--${run.kind}`} title={EVIDENCE_TITLE[run.kind]}>
                  {run.text}
                </mark>
              ) : (
                <span key={i}>{run.text}</span>
              ),
            )}
          </div>
          <p className="text-meta text-muted-foreground">
            Highlighted: what the reading is based on.{" "}
            <span className="ev ev--code">error code</span>{" "}
            <span className="ev ev--phrase">phrase</span>{" "}
            <span className="ev ev--keyword">weak hint</span>
          </p>

          {result.reading ? (
            <p className="text-lead leading-relaxed">{result.reading}</p>
          ) : null}

          {result.outcome === "ambiguous" ? (
            <div className="flex flex-col gap-2">
              <WarnNote>
                This message is consistent with more than one cause, and they are fixed by
                different people. It is not saying which — so neither is this.
              </WarnNote>
              {/* Side by side where the width exists; neither styled as the answer. */}
              <div className="grid gap-2 sm:grid-cols-2">
                {shown.map((candidate) => (
                  <div
                    key={candidate.reason}
                    className="flex flex-col gap-1 rounded-md border border-border bg-card p-3"
                  >
                    <p className="text-body leading-snug font-medium">{candidate.label}</p>
                    <p className="text-meta leading-relaxed text-muted-foreground">
                      Matched: {candidate.evidence.map((e) => `“${e.matched}”`).join(", ")}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {result.outcome === "unrecognized" ? (
            <Muted>
              None of the patterns this tool knows appear in that text. That is a gap in the
              tool, not a verdict about your registration — the questions below are what
              would let it try again.
            </Muted>
          ) : null}

          {result.responsible_office ? (
            <p className="text-body">
              Who can act on it:{" "}
              <strong className="font-medium">
                {OFFICE_LABEL[result.responsible_office] ?? result.responsible_office}
              </strong>
            </p>
          ) : null}

          {result.what_to_do.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              <Eyebrow>What to do</Eyebrow>
              <ol className="flex list-decimal flex-col gap-1 pl-5 text-body leading-relaxed">
                {result.what_to_do.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
            </div>
          ) : null}

          {result.degraded.length > 0 ? (
            <WarnNote>
              Reduced service: {result.degraded.join(", ")}. The policy passages below may be
              less relevant than usual.
            </WarnNote>
          ) : null}

          <p className="text-meta leading-relaxed text-subtle">{result.disclaimer}</p>
        </CardContent>
      </Card>

      {result.follow_ups.length > 0 ? (
        <Card>
          <CardHeader>
            <Eyebrow>
              {result.outcome === "identified"
                ? "One thing would sharpen this"
                : "Answer to narrow it down"}
            </Eyebrow>
            <CardTitle>
              {result.follow_ups.length === 1
                ? "One question"
                : `${result.follow_ups.length} questions`}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {result.follow_ups.map((followUp, i) => (
              <div key={i} className="flex flex-col gap-1.5">
                <p className="text-body leading-relaxed font-medium">
                  {followUp.question}
                </p>
                <Muted>{followUp.why}</Muted>
                <input
                  type="text"
                  className={INPUT_CLASS}
                  value={answers[i] ?? ""}
                  onChange={(e) => onAnswer(i, e.target.value)}
                  placeholder="Your answer"
                  aria-label={followUp.question}
                  disabled={busy}
                />
              </div>
            ))}
            <div>
              <Button
                onClick={onResubmit}
                disabled={busy || !Object.values(answers).some((a) => a && a.trim())}
              >
                {busy ? "Reading it again…" : "Decode again with this"}
              </Button>
            </div>
            <Muted>
              Your answer is added to the message and the whole thing is read again from
              scratch, so the second reading can only differ because of what you told it.
            </Muted>
          </CardContent>
        </Card>
      ) : null}

      {result.record_check ? (
        <Card>
          <CardHeader>
            <Eyebrow>Checked against your own entries</Eyebrow>
            <CardTitle>
              {result.record_check.performed
                ? "What your record says"
                : "Not enough entered to check"}
            </CardTitle>
            <CardDescription>{result.record_check.basis}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {result.record_check.findings.length > 0 ? (
              <ul className="findings">
                {result.record_check.findings.map((finding, i) => (
                  <Finding key={i} finding={finding} />
                ))}
              </ul>
            ) : null}

            {result.record_check.note ? <Muted>{result.record_check.note}</Muted> : null}

            {!result.record_check.performed && onOpenPlanner ? (
              <div>
                <Button variant="outline" onClick={onOpenPlanner}>
                  Enter your courses on the planner →
                </Button>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {result.passages.length > 0 ? (
        <Card>
          <CardHeader>
            <Eyebrow>Published policy</Eyebrow>
            <CardTitle>What the bulletin says</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="findings">
              {result.passages.map((passage) => (
                <Passage
                  key={passage.source_id}
                  title={passage.section ?? passage.document}
                  text={passage.text}
                  source={passage.document}
                  office={passage.office}
                  fetchedOn={passage.verified_at?.slice(0, 10)}
                  url={passage.url}
                />
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {result.no_policy_note ? (
        <Card>
          <CardHeader>
            <Eyebrow>No policy source</Eyebrow>
          </CardHeader>
          <CardContent>
            <WarnNote>{result.no_policy_note}</WarnNote>
          </CardContent>
        </Card>
      ) : null}

      {result.albert ? (
        <Card>
          <CardHeader>
            <Eyebrow>Only Albert knows this part</Eyebrow>
            {result.albert.topic ? <CardTitle>{result.albert.topic}</CardTitle> : null}
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {result.albert.where_to_look ? (
              <p className="text-body leading-relaxed">
                <strong className="font-medium">Where to look:</strong>{" "}
                {result.albert.where_to_look}
              </p>
            ) : null}
            {result.albert.what_to_know ? <Muted>{result.albert.what_to_know}</Muted> : null}
            {result.albert.hold_code_note ? <Muted>{result.albert.hold_code_note}</Muted> : null}
          </CardContent>
        </Card>
      ) : null}
    </>
  )
}
