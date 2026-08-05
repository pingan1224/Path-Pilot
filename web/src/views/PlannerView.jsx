import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Empty, ErrorState, Loading } from "../components";

/**
 * The degree planner: self-reported record in, verdicts with citations out.
 *
 * Layout follows the trust model. The record editor sits first because everything below
 * is derived from it; the plan is labelled as computed from published rules; and the
 * verdicts a human must resolve are visually separated from the ones the engine settled.
 * The handoff generator is a pure template over the plan data — deterministic, instant,
 * and faithful, which matters more than prose polish in a document a student sends to
 * their advisor.
 */

const VERDICT_META = {
  satisfied: { mark: "✓", label: "Verified", tone: "good" },
  conditional: { mark: "◐", label: "Holds if…", tone: "warn" },
  unverifiable: { mark: "?", label: "Ask a human", tone: "neutral" },
  not_satisfied: { mark: "✕", label: "Not met", tone: "danger" },
};

const STATE_LABEL = {
  completed: "Completed",
  in_progress: "Taking now",
  planned: "Planned",
};

export default function PlannerView() {
  const [courses, setCourses] = useState(null);
  const [plan, setPlan] = useState(null);
  const [includePlanned, setIncludePlanned] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const [profile, planned] = await Promise.all([
        api.profileCourses(),
        api.plan(includePlanned),
      ]);
      setCourses(profile);
      setPlan(planned);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includePlanned]);

  async function saveCourse(payload) {
    setBusy(true);
    try {
      await api.profilePut(payload);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeCourse(code) {
    setBusy(true);
    try {
      await api.profileDelete(code);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !plan) return <ErrorState message={error} onRetry={refresh} />;
  if (!courses || !plan) return <Loading what="your plan" />;

  return (
    <div className="stack">
      {error ? <ErrorState message={error} onRetry={refresh} /> : null}

      <CourseEditor courses={courses} onSave={saveCourse} onRemove={removeCourse} busy={busy} />

      <PlanCard
        plan={plan}
        includePlanned={includePlanned}
        onTogglePlanned={() => setIncludePlanned((v) => !v)}
      />

      <WhatIfCard />

      <HandoffCard courses={courses} plan={plan} />
    </div>
  );
}

/* ---------------------------------------------------------------------------------- */

function CourseEditor({ courses, onSave, onRemove, busy }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [manualCode, setManualCode] = useState("");

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const found = await api.catalogSearch(query);
        if (!cancelled) setResults(found.slice(0, 8));
      } catch {
        /* search failures are non-fatal; the manual field still works */
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  const held = new Set(courses.map((c) => c.course_code));

  return (
    <section className="card" aria-labelledby="record-heading">
      <div className="planner__head">
        <div>
          <p className="eyebrow">Your record — self-reported</p>
          <h2 id="record-heading">My courses</h2>
        </div>
        <p className="muted planner__note">
          UAX cannot see Albert. Everything below is what you tell it, and the plan is only
          as accurate as this list.
        </p>
      </div>

      <div className="course-add">
        <input
          type="search"
          placeholder="Search the MASY catalog — code or title…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search the course catalog"
        />
        {results.length > 0 ? (
          <ul className="course-add__results">
            {results.map((r) => (
              <li key={r.code}>
                <div className="course-add__info">
                  <span className="mono">{r.code}</span> {r.title}
                  <span className="muted"> · {r.credits}cr</span>
                  {r.prerequisites_text ? (
                    <span className="course-add__prereq">Prereq: {r.prerequisites_text}</span>
                  ) : null}
                </div>
                {held.has(r.code) ? (
                  <span className="muted">added</span>
                ) : (
                  <span className="course-add__actions">
                    {["completed", "in_progress", "planned"].map((state) => (
                      <button
                        key={state}
                        type="button"
                        className="btn btn--small"
                        disabled={busy}
                        onClick={() => {
                          onSave({ course_code: r.code, state });
                          setQuery("");
                        }}
                      >
                        {STATE_LABEL[state]}
                      </button>
                    ))}
                  </span>
                )}
              </li>
            ))}
          </ul>
        ) : null}

        <details className="course-add__manual">
          <summary>Course not in this catalog? Add it by code</summary>
          <p className="muted">
            Cross-school and outside-program courses are allowed by your elective rules, but
            this tool cannot verify them — they will show as “ask a human”.
          </p>
          <form
            className="course-add__manual-form"
            onSubmit={(e) => {
              e.preventDefault();
              const code = manualCode.trim();
              if (code) {
                onSave({ course_code: code, state: "planned" });
                setManualCode("");
              }
            }}
          >
            <input
              value={manualCode}
              onChange={(e) => setManualCode(e.target.value)}
              placeholder="e.g. MKTG-GB 2350"
              aria-label="Course code"
            />
            <button type="submit" className="btn" disabled={busy}>
              Add as planned
            </button>
          </form>
        </details>
      </div>

      {courses.length === 0 ? (
        <Empty>No courses yet — search above to start building your record.</Empty>
      ) : (
        <ul className="course-list">
          {courses.map((c) => (
            <li key={c.course_code} className="course-row">
              <div className="course-row__id">
                <span className="mono">{c.course_code}</span>
                <span className="course-row__title">
                  {c.title ?? "Not in this catalog"}
                  {!c.in_catalog ? <span className="tag tag--warn">unverified</span> : null}
                </span>
              </div>
              <div className="course-row__controls">
                <select
                  value={c.state}
                  disabled={busy}
                  aria-label={`Status of ${c.course_code}`}
                  onChange={(e) =>
                    onSave({ course_code: c.course_code, state: e.target.value, grade: c.grade })
                  }
                >
                  {Object.entries(STATE_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                {c.state === "completed" ? (
                  <input
                    className="course-row__grade"
                    value={c.grade ?? ""}
                    placeholder="grade"
                    maxLength={2}
                    disabled={busy}
                    aria-label={`Grade for ${c.course_code}`}
                    onChange={(e) =>
                      onSave({
                        course_code: c.course_code,
                        state: c.state,
                        grade: e.target.value || null,
                      })
                    }
                  />
                ) : null}
                <button
                  type="button"
                  className="btn btn--small"
                  disabled={busy}
                  onClick={() => onRemove(c.course_code)}
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/* ---------------------------------------------------------------------------------- */

function Finding({ finding }) {
  const meta = VERDICT_META[finding.verdict];
  return (
    <li className={`finding finding--${meta.tone}`}>
      <div className="finding__head">
        <span className="finding__mark" aria-hidden="true">
          {meta.mark}
        </span>
        <span className="finding__summary">{finding.summary}</span>
        <span className={`tag tag--${meta.tone}`}>{meta.label}</span>
      </div>
      <p className="finding__detail">{finding.detail}</p>
      {finding.next_step ? (
        <p className="finding__next">→ {finding.next_step}</p>
      ) : null}
      {finding.citations.length > 0 ? (
        <details className="finding__sources">
          <summary>Source</summary>
          {finding.citations.map((c, i) => (
            <p key={i} className="finding__cite">
              {c.url ? (
                <a href={c.url} target="_blank" rel="noreferrer">
                  {c.label}
                </a>
              ) : (
                c.label
              )}
              {c.verified_on ? ` · checked ${c.verified_on}` : ""}
              {c.quote ? <span className="finding__quote">“{c.quote}”</span> : null}
            </p>
          ))}
        </details>
      ) : null}
    </li>
  );
}

function PlanCard({ plan, includePlanned, onTogglePlanned }) {
  const settled = plan.findings.filter(
    (f) => f.verdict === "satisfied" || f.verdict === "not_satisfied",
  );
  const forHumans = plan.findings.filter(
    (f) => f.verdict === "conditional" || f.verdict === "unverifiable",
  );

  return (
    <section className="card" aria-labelledby="plan-heading">
      <div className="planner__head">
        <div>
          <p className="eyebrow">
            Computed from published rules · checked {plan.rules_verified_on}
          </p>
          <h2 id="plan-heading">{plan.program_name} — degree check</h2>
        </div>
        <label className="planner__toggle">
          <input type="checkbox" checked={includePlanned} onChange={onTogglePlanned} />
          Count planned & in-progress courses
        </label>
      </div>

      <div className="plan-credits">
        <span>
          <strong>{plan.credits_completed}</strong> completed
        </span>
        <span>
          <strong>{plan.credits_in_progress}</strong> in progress
        </span>
        <span>
          <strong>{plan.credits_planned}</strong> planned
        </span>
        <span className="muted">of {plan.credits_required} required</span>
      </div>

      <ul className="findings">
        {settled.map((f, i) => (
          <Finding key={i} finding={f} />
        ))}
      </ul>

      {forHumans.length > 0 ? (
        <>
          <h3 className="planner__subhead">Needs a human</h3>
          <p className="muted">
            These are the parts this tool cannot settle — which is exactly what to bring to
            your advisor.
          </p>
          <ul className="findings">
            {forHumans.map((f, i) => (
              <Finding key={i} finding={f} />
            ))}
          </ul>
        </>
      ) : null}

      <p className="planner__disclaimer">{plan.disclaimer}</p>
    </section>
  );
}

/* ---------------------------------------------------------------------------------- */

function WhatIfCard() {
  const [code, setCode] = useState("");
  // The course the displayed result is about, which is not the same as whatever is
  // currently in the box once the student starts typing the next question.
  const [asked, setAsked] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function run(e) {
    e.preventDefault();
    const trimmed = code.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.whatIf([{ course_code: trimmed, state: "planned" }]));
      setAsked(trimmed.toUpperCase());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // Only findings that actually mention the course asked about. An earlier version also
  // swept in every unmet requirement, which answered "what if I took 2100" with a note
  // about the capstone — true, unasked, and enough noise to bury the real answer.
  const relevant = useMemo(() => {
    if (!result) return [];
    const needle = (asked || "").toUpperCase();
    if (!needle) return [];
    return result.findings.filter(
      (f) =>
        f.summary.toUpperCase().includes(needle) ||
        f.detail.toUpperCase().includes(needle),
    );
  }, [result, asked]);

  return (
    <section className="card" aria-labelledby="whatif-heading">
      <p className="eyebrow">Hypothetical — nothing is saved</p>
      <h2 id="whatif-heading">What if I took…</h2>
      <form className="whatif__form" onSubmit={run}>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Course code, e.g. MASY1-GC 2100"
          aria-label="Course code to test"
        />
        <button type="submit" className="btn btn--primary" disabled={busy || !code.trim()}>
          {busy ? "Checking…" : "Check"}
        </button>
      </form>
      {error ? <p className="login__error">{error}</p> : null}
      {result ? (
        relevant.length > 0 ? (
          <>
            <p className="muted">Adding {asked} to your plan:</p>
            <ul className="findings">
              {relevant.map((f, i) => (
                <Finding key={i} finding={f} />
              ))}
            </ul>
          </>
        ) : (
          <Empty>
            Nothing in the encoded rules blocks {asked}. Seat availability and any
            departmental approval still have to be checked in Albert.
          </Empty>
        )
      ) : null}
    </section>
  );
}

/* ---------------------------------------------------------------------------------- */

function buildHandoff(courses, plan, question) {
  const byState = (state) =>
    courses
      .filter((c) => c.state === state)
      .map((c) => `  - ${c.course_code}${c.title ? ` (${c.title})` : ""}${c.grade ? ` — ${c.grade}` : ""}`)
      .join("\n") || "  (none)";

  const confirmed = plan.findings
    .filter((f) => f.verdict === "satisfied" || f.verdict === "not_satisfied")
    .map((f) => `  - ${f.verdict === "satisfied" ? "[met]" : "[not met]"} ${f.summary}`)
    .join("\n");

  const open = plan.findings
    .filter((f) => f.verdict === "conditional" || f.verdict === "unverifiable")
    .map((f) => `  - ${f.summary}: ${f.detail}`)
    .join("\n");

  const questions = plan.findings
    .filter((f) => f.next_step && f.verdict !== "satisfied")
    .map((f) => `  ${f.next_step}`)
    .filter((v, i, a) => a.indexOf(v) === i)
    .join("\n");

  return `Subject: Advising question — degree plan check

Hi,

${question.trim() || "I would like to review my degree plan and registration for next term."}

MY RECORD AS I UNDERSTAND IT (self-reported, please correct me if Albert says otherwise):

Completed:
${byState("completed")}

Taking now:
${byState("in_progress")}

Planning to take:
${byState("planned")}

WHAT THE PUBLISHED RULES SAY (checked against the ${plan.program_name} bulletin, ${plan.rules_verified_on}):
${confirmed}

WHAT I COULD NOT CONFIRM MYSELF:
${open || "  (nothing outstanding)"}

MY QUESTIONS:
${questions || "  Does this plan look right to you?"}

Generated with UAX, an independent planning tool (not an NYU system). Everything above
should be verified against Albert.

Thanks!`;
}

function HandoffCard({ courses, plan }) {
  const [question, setQuestion] = useState("");
  const [copied, setCopied] = useState(false);

  const text = useMemo(
    () => buildHandoff(courses, plan, question),
    [courses, plan, question],
  );

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      /* the textarea below remains selectable by hand */
    }
  }

  return (
    <section className="card" aria-labelledby="handoff-heading">
      <p className="eyebrow">For your advisor</p>
      <h2 id="handoff-heading">Advisor handoff</h2>
      <p className="muted">
        A ready-to-send summary of your record, what the rules say, and what only your
        advisor can answer. Copy it into an email — UAX does not send anything for you.
      </p>
      <input
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Your main question, in one sentence (optional)"
        aria-label="Your question for the advisor"
      />
      <textarea
        className="handoff__text"
        readOnly
        value={text}
        rows={14}
        aria-label="Generated advisor email"
      />
      <button type="button" className="btn btn--primary" onClick={copy}>
        {copied ? "Copied ✓" : "Copy to clipboard"}
      </button>
    </section>
  );
}
