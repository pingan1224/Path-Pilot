import { useState } from "react";
import { api } from "../api";
import { ErrorState } from "../components";

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
  identified: { tag: "good", label: "Cause identified" },
  ambiguous: { tag: "warn", label: "Needs one more detail" },
  unrecognized: { tag: "neutral", label: "Could not decode this" },
};

const EVIDENCE_TITLE = {
  code: "Error code — written by the system, near-conclusive",
  phrase: "Phrase match",
  keyword: "Single suggestive word — not enough on its own",
};

const OFFICE_LABEL = {
  registrar: "Registrar",
  bursar: "Bursar",
  financial_aid: "Financial Aid",
  advising: "Academic advising",
  department: "The department or program",
  international: "Office of Global Services",
};

const VERDICT_META = {
  satisfied: { mark: "✓", tone: "good" },
  conditional: { mark: "◐", tone: "warn" },
  unverifiable: { mark: "?", tone: "neutral" },
  not_satisfied: { mark: "✕", tone: "danger" },
};

const SAMPLES = [
  "ERR_PREREQ: Requisites not met for this class",
  "ERR_HOLD_ACTIVE: Registration blocked (hold code SF2)",
  "ERR_RESERVE: Reserved capacity requirement not met",
];

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
    .sort((a, b) => a.start - b.start || b.end - a.end);

  const merged = [];
  for (const span of spans) {
    const last = merged[merged.length - 1];
    if (last && span.start < last.end) {
      // Overlapping matches keep the stronger label: a keyword inside a phrase should
      // read as part of the phrase, not as independent evidence.
      last.end = Math.max(last.end, span.end);
      if (last.kind !== "code" && span.kind === "code") last.kind = "code";
      else if (last.kind === "keyword" && span.kind === "phrase") last.kind = "phrase";
      continue;
    }
    merged.push({ ...span });
  }

  const out = [];
  let at = 0;
  for (const span of merged) {
    if (span.start > at) out.push({ text: text.slice(at, span.start), kind: null });
    out.push({ text: text.slice(span.start, span.end), kind: span.kind });
    at = span.end;
  }
  if (at < text.length) out.push({ text: text.slice(at), kind: null });
  return out;
}

export default function DecoderView({ onOpenPlanner }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [answers, setAnswers] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function run(message, replies = {}) {
    const trimmed = (message ?? "").trim();
    if (trimmed.length < 2 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const answerList = Object.values(replies).filter((a) => a && a.trim());
      setResult(await api.decode(trimmed, answerList));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setResult(null);
    setAnswers({});
    setError(null);
  }

  return (
    <div className="stack">
      <section className="card">
        <p className="eyebrow">Registration error</p>
        <h2>What did Albert tell you?</h2>
        <p className="muted">
          Paste the message exactly as it appeared, error code and all. Nothing else needs
          to be filled in first — this works on your first visit.
        </p>

        <form
          className="decoder__form"
          onSubmit={(e) => {
            e.preventDefault();
            setAnswers({});
            run(text);
          }}
        >
          <label className="visually-hidden" htmlFor="decoder-input">
            The error message
          </label>
          <textarea
            id="decoder-input"
            className="decoder__input"
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. ERR_PREREQ: Requisites not met for this class"
            disabled={busy}
          />
          <div className="decoder__actions">
            <button
              type="submit"
              className="btn btn--primary"
              disabled={busy || text.trim().length < 2}
            >
              {busy ? "Reading it…" : "Decode"}
            </button>
            {result ? (
              <button type="button" className="btn" onClick={reset}>
                Clear
              </button>
            ) : null}
          </div>
        </form>

        {!result ? (
          <div className="decoder__samples">
            <p className="muted">Or try one of these:</p>
            {SAMPLES.map((sample) => (
              <button
                key={sample}
                type="button"
                className="chat__suggestion"
                onClick={() => {
                  setText(sample);
                  setAnswers({});
                  run(sample);
                }}
              >
                {sample}
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {error ? <ErrorState message={error} onRetry={() => run(text, answers)} /> : null}

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
  );
}

/* ---------------------------------------------------------------------------------- */

function Result({ result, answers, onAnswer, onResubmit, busy, onOpenPlanner }) {
  const meta = OUTCOME_META[result.outcome] ?? OUTCOME_META.unrecognized;
  // Ambiguity means the leading candidates are all in play, so all of their evidence is
  // worth showing. Identified results highlight only the winner's.
  const shown =
    result.outcome === "identified" ? result.candidates.slice(0, 1) : result.candidates.slice(0, 2);
  const evidence = shown.flatMap((c) => c.evidence);

  return (
    <>
      <section className="card">
        <div className="decoder__head">
          <span className={`tag tag--${meta.tag}`}>{meta.label}</span>
          {result.reason_label ? <h2>{result.reason_label}</h2> : null}
        </div>

        <div className="decoder__echo">
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
        <p className="decoder__legend muted">
          Highlighted: what the reading is based on.{" "}
          <span className="ev ev--code">error code</span>{" "}
          <span className="ev ev--phrase">phrase</span>{" "}
          <span className="ev ev--keyword">weak hint</span>
        </p>

        {result.reading ? <p className="decoder__reading">{result.reading}</p> : null}

        {result.outcome === "ambiguous" ? (
          <div className="decoder__split">
            <p className="note note--warn">
              This message is consistent with more than one cause, and they are fixed by
              different people. It is not saying which — so neither is this.
            </p>
            {shown.map((candidate) => (
              <div key={candidate.reason} className="decoder__option">
                <p className="decoder__option-label">{candidate.label}</p>
                <p className="muted">
                  Matched:{" "}
                  {candidate.evidence.map((e) => `“${e.matched}”`).join(", ")}
                </p>
              </div>
            ))}
          </div>
        ) : null}

        {result.outcome === "unrecognized" ? (
          <p className="note">
            None of the patterns this tool knows appear in that text. That is a gap in the
            tool, not a verdict about your registration — the questions below are what
            would let it try again.
          </p>
        ) : null}

        {result.responsible_office ? (
          <p className="decoder__office">
            Who can act on it:{" "}
            <strong>{OFFICE_LABEL[result.responsible_office] ?? result.responsible_office}</strong>
          </p>
        ) : null}

        {result.what_to_do.length > 0 ? (
          <>
            <p className="eyebrow">What to do</p>
            <ol className="decoder__steps">
              {result.what_to_do.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </>
        ) : null}

        {result.degraded.length > 0 ? (
          <p className="msg__degraded">
            Reduced service: {result.degraded.join(", ")}. The policy passages below may be
            less relevant than usual.
          </p>
        ) : null}

        <p className="chat__disclaimer">{result.disclaimer}</p>
      </section>

      {result.follow_ups.length > 0 ? (
        <section className="card">
          <p className="eyebrow">
            {result.outcome === "identified" ? "One thing would sharpen this" : "Answer to narrow it down"}
          </p>
          <h2>{result.follow_ups.length === 1 ? "One question" : `${result.follow_ups.length} questions`}</h2>
          {result.follow_ups.map((followUp, i) => (
            <div key={i} className="decoder__q">
              <p className="decoder__q-text">{followUp.question}</p>
              <p className="muted">{followUp.why}</p>
              <input
                type="text"
                value={answers[i] ?? ""}
                onChange={(e) => onAnswer(i, e.target.value)}
                placeholder="Your answer"
                disabled={busy}
              />
            </div>
          ))}
          <button
            type="button"
            className="btn btn--primary"
            onClick={onResubmit}
            disabled={busy || !Object.values(answers).some((a) => a && a.trim())}
          >
            {busy ? "Reading it again…" : "Decode again with this"}
          </button>
          <p className="muted">
            Your answer is added to the message and the whole thing is read again from
            scratch, so the second reading can only differ because of what you told it.
          </p>
        </section>
      ) : null}

      {result.record_check ? (
        <section className="card">
          <p className="eyebrow">Checked against your own entries</p>
          <h2>{result.record_check.performed ? "What your record says" : "Not enough entered to check"}</h2>
          <p className="planner__disclaimer">{result.record_check.basis}</p>

          {result.record_check.findings.length > 0 ? (
            <ul className="findings">
              {result.record_check.findings.map((finding, i) => {
                const verdict = VERDICT_META[finding.verdict] ?? VERDICT_META.unverifiable;
                return (
                  <li key={i} className={`finding finding--${verdict.tone}`}>
                    <div className="finding__head">
                      <span className="finding__mark">{verdict.mark}</span>
                      <span className="finding__summary">{finding.summary}</span>
                    </div>
                    <p className="finding__detail">{finding.detail}</p>
                    {finding.next_step ? (
                      <p className="finding__next">{finding.next_step}</p>
                    ) : null}
                    {finding.citations.length > 0 ? (
                      <details className="finding__sources">
                        <summary>Source</summary>
                        {finding.citations.map((cite, j) => (
                          <p key={j} className="finding__cite">
                            {cite.url ? (
                              <a href={cite.url} target="_blank" rel="noreferrer">
                                {cite.label}
                              </a>
                            ) : (
                              cite.label
                            )}
                            {cite.verified_on ? ` · checked ${cite.verified_on}` : ""}
                            {cite.quote ? (
                              <span className="finding__quote">“{cite.quote}”</span>
                            ) : null}
                          </p>
                        ))}
                      </details>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : null}

          {result.record_check.note ? <p className="note">{result.record_check.note}</p> : null}

          {!result.record_check.performed && onOpenPlanner ? (
            <button type="button" className="btn" onClick={onOpenPlanner}>
              Enter your courses on the planner →
            </button>
          ) : null}
        </section>
      ) : null}

      {result.passages.length > 0 ? (
        <section className="card">
          <p className="eyebrow">Published policy</p>
          <h2>What the bulletin says</h2>
          <ul className="findings">
            {result.passages.map((passage) => (
              <li key={passage.source_id} className="finding">
                <div className="finding__head">
                  <span className="finding__summary">
                    {passage.section ?? passage.document}
                  </span>
                </div>
                <p className="finding__detail">{passage.text}</p>
                <p className="finding__cite">
                  <a href={passage.url} target="_blank" rel="noreferrer">
                    {passage.document}
                  </a>
                  {" · "}
                  {passage.office.replace(/_/g, " ")}
                  {" · fetched "}
                  {passage.verified_at?.slice(0, 10)}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {result.no_policy_note ? (
        <section className="card">
          <p className="eyebrow">No policy source</p>
          <p className="note note--warn">{result.no_policy_note}</p>
        </section>
      ) : null}

      {result.albert ? (
        <section className="card">
          <p className="eyebrow">Only Albert knows this part</p>
          {result.albert.topic ? <h2>{result.albert.topic}</h2> : null}
          {result.albert.where_to_look ? (
            <p>
              <strong>Where to look:</strong> {result.albert.where_to_look}
            </p>
          ) : null}
          {result.albert.what_to_know ? (
            <p className="muted">{result.albert.what_to_know}</p>
          ) : null}
          {result.albert.hold_code_note ? (
            <p className="note">{result.albert.hold_code_note}</p>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
