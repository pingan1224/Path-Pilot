import { useEffect, useRef, useState } from "react";
import { api } from "../api";

/**
 * The Ask Albert AI panel. Non-modal by design — the RFP is explicit that the dashboard
 * stays visible and usable while the assistant is open, so this is a docked panel, not an
 * overlay that takes the page hostage.
 *
 * Answers render with their citations, the tools the agent consulted, and — when the
 * agent escalated — the case number the student can quote to a human.
 */

const DECISION_META = {
  answered: { label: "Answered from verified sources", tone: "good" },
  answered_with_caveat: { label: "Answered — see caveats", tone: "warn" },
  escalated: { label: "Routed to a human", tone: "accent" },
  refused: { label: "Outside what I can help with", tone: "neutral" },
};

const SUGGESTIONS = [
  "Why is my registration blocked?",
  "Am I on track to graduate on time?",
  "What happens if I join a waitlist?",
];

function sourceLabel(sourceId) {
  if (sourceId.startsWith("policy:")) return "University policy";
  if (sourceId.startsWith("record:hold:")) return "Your holds record";
  if (sourceId.startsWith("record:progress:")) return "Your degree audit";
  if (sourceId.startsWith("record:attempt:")) return "Your registration history";
  if (sourceId.startsWith("record:course:")) return "Course catalog";
  return sourceId;
}

function Thinking() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="chat__thinking" role="status">
      <span className="chat__dots" aria-hidden="true">
        <i /><i /><i />
      </span>
      Checking your record and university policy… {seconds}s
      {seconds > 20 ? <span className="muted"> (thorough answers take a moment)</span> : null}
    </div>
  );
}

export default function AskAlbert() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [thread, setThread] = useState([]);
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [thread, busy]);

  async function ask(text) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setQuestion("");
    setThread((t) => [...t, { kind: "user", text: trimmed }]);
    setBusy(true);
    try {
      // Who is asking — and whose record the tools may read — comes from the session.
      const result = await api.ask(trimmed);
      setThread((t) => [...t, { kind: "assistant", result }]);
    } catch (err) {
      setThread((t) => [...t, { kind: "error", text: err.message }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="fab"
        aria-expanded={open}
        aria-controls="ask-albert-panel"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Close assistant" : "Ask Albert AI"}
      </button>

      {open ? (
        <section id="ask-albert-panel" className="chat" aria-label="Ask Albert AI assistant">
          <header className="chat__head">
            <div>
              <strong>Albert AI</strong>
              <p className="chat__sub">
                Answers come from your record and official policy, with sources. High-stakes
                questions go to a human.
              </p>
            </div>
          </header>

          <div className="chat__scroll" ref={scrollRef}>
            {thread.length === 0 ? (
              <div className="chat__empty">
                <p className="muted">Try one of these:</p>
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" className="chat__suggestion" onClick={() => ask(s)}>
                    {s}
                  </button>
                ))}
              </div>
            ) : null}

            {thread.map((entry, i) => {
              if (entry.kind === "user") {
                return (
                  <div key={i} className="msg msg--user">
                    {entry.text}
                  </div>
                );
              }
              if (entry.kind === "error") {
                return (
                  <div key={i} className="msg msg--error" role="alert">
                    {entry.text}
                  </div>
                );
              }
              const r = entry.result;
              const meta = DECISION_META[r.decision] ?? DECISION_META.answered;
              return (
                <div key={i} className="msg msg--assistant">
                  <span className={`tag tag--${meta.tone}`}>{meta.label}</span>
                  <div className="msg__body">{r.answer}</div>

                  {r.case_number ? (
                    <p className="msg__case">
                      Case <strong>{r.case_number}</strong> has been opened — quote this number
                      when you contact the office.
                    </p>
                  ) : null}

                  {r.degraded_modes.length > 0 ? (
                    <p className="msg__degraded">
                      Reduced service: {r.degraded_modes.join(", ")}. Parts of this answer may
                      be less precise than usual.
                    </p>
                  ) : null}

                  {r.citations.length > 0 ? (
                    <details className="msg__sources">
                      <summary>Sources ({r.citations.length})</summary>
                      <ul>
                        {r.citations.map((c, j) => (
                          <li key={j}>
                            <span className="msg__source-label">{sourceLabel(c.source_id)}</span>
                            <span className="muted"> — {c.claim}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}

                  <details className="msg__trace">
                    <summary>What I checked ({r.tool_trace.length} lookups)</summary>
                    <ol>
                      {r.tool_trace.map((t, j) => (
                        <li key={j}>
                          <code>{t.tool}</code>
                          {t.args?.query ? <span className="muted"> “{t.args.query}”</span> : null}
                          {t.args?.course_code ? (
                            <span className="muted"> {t.args.course_code}</span>
                          ) : null}
                        </li>
                      ))}
                    </ol>
                  </details>
                </div>
              );
            })}

            {busy ? <Thinking /> : null}
          </div>

          <form
            className="chat__form"
            onSubmit={(e) => {
              e.preventDefault();
              ask(question);
            }}
          >
            <label className="visually-hidden" htmlFor="ask-input">
              Ask a question
            </label>
            <input
              id="ask-input"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about holds, courses, degree progress…"
              disabled={busy}
            />
            <button type="submit" className="btn btn--primary" disabled={busy || !question.trim()}>
              Ask
            </button>
          </form>
        </section>
      ) : null}
    </>
  );
}
