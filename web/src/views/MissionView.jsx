import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading } from "../components";
import { Finding } from "@/components/Finding";

/**
 * The registration mission: a resumable task, shown as the five steps it actually is.
 *
 * The progress here is never computed in this file. Every mutation returns the whole
 * mission with its step states recomputed server-side, and this component renders what it
 * is given. That is deliberate — a client that derived "you are on step 4" from its own
 * copy of the data would eventually disagree with the server about whether a student is
 * ready to register, and the student would believe whichever one they were looking at.
 *
 * All five step panels stay visible rather than being revealed one at a time. A student who
 * comes back after two weeks needs to see the shape of the whole task and where they
 * stopped, and a wizard that hides the remaining work also hides how much is left.
 *
 * The assistant's suggestions render in the candidate list marked as suggestions, with
 * their reason, and they do not move the progress counter. That gap between "the assistant
 * put three courses in front of me" and "I have chosen three courses" is the product.
 */

const STEP_MARK = {
  done: { mark: "✓", tone: "good", label: "Done" },
  active: { mark: "→", tone: "accent", label: "Now" },
  blocked: { mark: "·", tone: "neutral", label: "Waiting" },
};

const TERM_SUGGESTIONS =["Fall 2026", "Spring 2027", "Summer 2027"];

export default function MissionView({ onOpenPlanner }) {
  const [missions, setMissions] = useState(null);
  const [activeId, setActiveId] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .missions()
      .then((list) => {
        setMissions(list);
        setActiveId(list.length > 0 ? list[0].id : null);
      })
      .catch((err) => setError(err.message));
  }, []);

  /** Every mutation hands back the full mission; replace it wholesale. */
  function replace(mission) {
    setMissions((list) => (list ?? []).map((m) => (m.id === mission.id ? mission : m)));
  }

  async function act(fn) {
    setBusy(true);
    setError(null);
    try {
      replace(await fn());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function start(term) {
    setBusy(true);
    setError(null);
    try {
      const mission = await api.createMission(term);
      setMissions((list) => [mission, ...(list ?? []).filter((m) => m.id !== mission.id)]);
      setActiveId(mission.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !missions) return <ErrorState message={error} />;
  if (!missions) return <Loading what="your mission" />;

  const mission = missions.find((m) => m.id === activeId) ?? null;

  return (
    <div className="stack">
      {error ? <ErrorState message={error} /> : null}

      {missions.length === 0 ? (
        <StartCard onStart={start} busy={busy} />
      ) : (
        <>
          {missions.length > 1 ? (
            <nav className="roles" aria-label="Your missions">
              {missions.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className={`role ${m.id === activeId ? "role--active" : ""}`}
                  onClick={() => setActiveId(m.id)}
                >
                  {m.term}
                </button>
              ))}
            </nav>
          ) : null}

          {mission ? (
            <Mission
              mission={mission}
              busy={busy}
              act={act}
              onMission={replace}
              onOpenPlanner={onOpenPlanner}
            />
          ) : null}

          <StartCard onStart={start} busy={busy} compact />
        </>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------------------- */

function StartCard({ onStart, busy, compact = false }) {
  const [term, setTerm] = useState("");

  return (
    <section className="card">
      <p className="eyebrow">{compact ? "Another term" : "Get started"}</p>
      <h2>{compact ? "Start a mission for another term" : "Which term are you preparing for?"}</h2>
      {!compact ? (
        <p className="muted">
          A mission walks you through getting ready to register: your record, where you
          stand, the courses you want, what is in the way, and a summary for your advisor.
          You can leave it half-finished and come back — nothing is lost.
        </p>
      ) : null}
      <form
        className="whatif__form"
        onSubmit={(e) => {
          e.preventDefault();
          if (term.trim()) onStart(term.trim());
        }}
      >
        <input
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="e.g. Spring 2027"
          aria-label="Term"
          disabled={busy}
        />
        <button type="submit" className="btn btn--primary" disabled={busy || !term.trim()}>
          Start
        </button>
      </form>
      <div className="decoder__samples">
        {TERM_SUGGESTIONS.map((t) => (
          <button
            key={t}
            type="button"
            className="chat__suggestion"
            onClick={() => onStart(t)}
            disabled={busy}
          >
            {t}
          </button>
        ))}
      </div>
    </section>
  );
}

function Mission({ mission, busy, act, onMission, onOpenPlanner }) {
  const done = mission.steps.filter((s) => s.state === "done").length;
  const stepState = (id) => mission.steps.find((s) => s.id === id)?.state;

  return (
    <>
      <section className={`card card--hero ${mission.complete ? "mission--complete" : ""}`}>
        <div className="hero__top">
          <div>
            <p className="eyebrow">Registration mission</p>
            <h2>{mission.term}</h2>
            <p className="hero__reason">
              {mission.complete
                ? "Every step is done. Take the handoff to your advisor, then register in Albert."
                : mission.steps.find((s) => s.state === "active")?.what_now}
            </p>
          </div>
          <div className="hero__progress">
            <span className="hero__pct">
              {done}/{mission.steps.length}
            </span>
            <div className="meter__track">
              <div
                className={`meter__fill meter__fill--${mission.complete ? "good" : "accent"}`}
                style={{ width: `${(done / mission.steps.length) * 100}%` }}
              />
            </div>
          </div>
        </div>
        <p className="planner__disclaimer">{mission.disclaimer}</p>
      </section>

      <section className="card">
        <p className="eyebrow">The steps</p>
        <h2>What finishing means</h2>
        <ol className="mission__steps">
          {mission.steps.map((step) => {
            const meta = STEP_MARK[step.state] ?? STEP_MARK.blocked;
            return (
              <li key={step.id} className={`mstep mstep--${step.state}`}>
                <div className="mstep__head">
                  <span className={`mstep__mark mstep__mark--${meta.tone}`} aria-hidden="true">
                    {meta.mark}
                  </span>
                  <span className="mstep__title">{step.title}</span>
                  <span className={`tag tag--${meta.tone}`}>{meta.label}</span>
                </div>
                <p className="mstep__criterion">{step.criterion}</p>
                {step.evidence.map((line, i) => (
                  <p key={i} className="muted">
                    {line}
                  </p>
                ))}
                {step.what_now ? <p className="finding__next">{step.what_now}</p> : null}
                {step.note ? <p className="note note--warn">{step.note}</p> : null}
              </li>
            );
          })}
        </ol>
      </section>

      <GapsCard
        mission={mission}
        state={stepState("gaps")}
        busy={busy}
        act={act}
        onOpenPlanner={onOpenPlanner}
      />
      <CandidatesCard mission={mission} state={stepState("candidates")} busy={busy} act={act} />
      <OpenItemsCard mission={mission} state={stepState("open_items")} busy={busy} act={act} />
      <HandoffCard
        mission={mission}
        state={stepState("handoff")}
        busy={busy}
        onMission={onMission}
      />
    </>
  );
}

function Panel({ state, eyebrow, title, children }) {
  return (
    <section className={`card ${state === "active" ? "card--focus" : ""}`}>
      <p className="eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function GapsCard({ mission, state, busy, act, onOpenPlanner }) {
  return (
    <Panel state={state} eyebrow="Step 2" title="Where you stand on the degree">
      <p className="muted">
        These are about your degree overall, not about next term. None of them stops you
        registering — you just need to have seen them.
      </p>
      {mission.degree_findings.length === 0 ? (
        <p className="muted">Nothing outstanding at the degree level.</p>
      ) : (
        <ul className="findings">
          {mission.degree_findings.map((f) => (
            <Finding key={f.key} finding={f} />
          ))}
        </ul>
      )}
      <div className="decoder__actions">
        {state === "done" ? (
          <span className="tag tag--good">Reviewed</span>
        ) : (
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy}
            onClick={() => act(() => api.missionAcknowledgeGaps(mission.id))}
          >
            I have read these
          </button>
        )}
        {onOpenPlanner ? (
          <button type="button" className="btn" onClick={onOpenPlanner}>
            Edit my record →
          </button>
        ) : null}
      </div>
    </Panel>
  );
}

function CandidatesCard({ mission, state, busy, act }) {
  const [code, setCode] = useState("");
  const chosen = mission.candidates.filter((c) => c.state === "confirmed");
  const proposed = mission.candidates.filter((c) => c.state === "proposed");
  const declined = mission.candidates.filter((c) => c.state === "declined");

  return (
    <Panel state={state} eyebrow="Step 3" title={`Courses for ${mission.term}`}>
      <form
        className="whatif__form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!code.trim()) return;
          act(() => api.missionAddCandidate(mission.id, code.trim()));
          setCode("");
        }}
      >
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Add a course by code, e.g. MASY1-GC 2100"
          aria-label="Course code"
          disabled={busy}
        />
        <button type="submit" className="btn btn--primary" disabled={busy || !code.trim()}>
          Add
        </button>
      </form>

      {proposed.length > 0 ? (
        <>
          <p className="eyebrow">Suggested by the assistant — your call</p>
          <ul className="course-list">
            {proposed.map((c) => (
              <li key={c.id} className="course-row">
                <div className="course-row__id">
                  <span className="mono">{c.course_code}</span>
                  <span className="tag tag--accent">Suggestion</span>
                </div>
                {c.rationale ? <p className="course-row__title">{c.rationale}</p> : null}
                <div className="course-row__controls">
                  <button
                    type="button"
                    className="btn btn--small btn--primary"
                    disabled={busy}
                    onClick={() => act(() => api.missionDecideCandidate(mission.id, c.id, true))}
                  >
                    Add to my plan
                  </button>
                  <button
                    type="button"
                    className="btn btn--small"
                    disabled={busy}
                    onClick={() => act(() => api.missionDecideCandidate(mission.id, c.id, false))}
                  >
                    No thanks
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <p className="muted">
            Suggestions do not count toward this step until you add one.
          </p>
        </>
      ) : null}

      <p className="eyebrow">Chosen ({chosen.length})</p>
      {chosen.length === 0 ? (
        <p className="muted">Nothing chosen yet.</p>
      ) : (
        <ul className="course-list">
          {chosen.map((c) => (
            <li key={c.id} className="course-row">
              <div className="course-row__id">
                <span className="mono">{c.course_code}</span>
                {c.proposed_by === "ai" ? (
                  <span className="tag tag--neutral">You accepted a suggestion</span>
                ) : null}
              </div>
              <div className="course-row__controls">
                <button
                  type="button"
                  className="btn btn--small"
                  disabled={busy}
                  onClick={() => act(() => api.missionRemoveCandidate(mission.id, c.id))}
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {declined.length > 0 ? (
        <p className="muted">
          Declined: {declined.map((c) => c.course_code).join(", ")}. The assistant cannot
          re-add these.
        </p>
      ) : null}
    </Panel>
  );
}

function OpenItemsCard({ mission, state, busy, act }) {
  const [notes, setNotes] = useState({});

  return (
    <Panel state={state} eyebrow="Step 4" title="Open items on your chosen courses">
      {mission.open_blockers.length === 0 && mission.accepted_risks.length === 0 ? (
        <p className="muted">
          Nothing in the way of the courses you chose — as far as the published rules and
          what you entered can tell.
        </p>
      ) : null}

      {mission.open_blockers.length > 0 ? (
        <ul className="findings">
          {mission.open_blockers.map((f) => (
            /* A blocker is a `not_satisfied` verdict — it was written as a hardcoded red
               border and a ✕, which is the same statement with the label left off. */
            <Finding key={f.key} finding={f} verdict="not_satisfied">
              <label className="visually-hidden" htmlFor={`note-${f.key}`}>
                Why you are accepting this
              </label>
              <input
                id={`note-${f.key}`}
                value={notes[f.key] ?? ""}
                onChange={(e) => setNotes((n) => ({ ...n, [f.key]: e.target.value }))}
                placeholder="Why you are going ahead anyway (goes in the advisor summary)"
                disabled={busy}
              />
              <button
                type="button"
                className="btn btn--small"
                disabled={busy}
                onClick={() =>
                  act(() =>
                    api.missionAcceptRisk(mission.id, {
                      finding_key: f.key,
                      finding_summary: f.summary,
                      note: notes[f.key] || null,
                    }),
                  )
                }
              >
                Accept as a known risk
              </button>
            </Finding>
          ))}
        </ul>
      ) : null}

      {mission.accepted_risks.length > 0 ? (
        <>
          <p className="eyebrow">Accepted knowingly</p>
          <ul className="findings">
            {mission.accepted_risks.map((r) => (
              /* Label overridden because the section heading above already says "Accepted
                 knowingly" — the default "Holds if…" would describe the blocker rather than
                 the student's decision about it. */
              <Finding
                key={r.finding_key}
                verdict="conditional"
                label="Accepted"
                summary={r.accepted_summary ?? r.finding_key}
                detail={r.note ? `Your note: ${r.note}` : null}
              >
                {r.reads_differently_now ? (
                  <p className="note note--warn">
                    This now reads differently than when you accepted it. Worth a second
                    look — your acceptance still stands, but it was for the earlier version.
                  </p>
                ) : null}
                <button
                  type="button"
                  className="btn btn--small"
                  disabled={busy}
                  onClick={() => act(() => api.missionWithdrawRisk(mission.id, r.finding_key))}
                >
                  Undo
                </button>
              </Finding>
            ))}
          </ul>
        </>
      ) : null}
    </Panel>
  );
}

function HandoffCard({ mission, state, busy, onMission }) {
  const [question, setQuestion] = useState("");
  const [text, setText] = useState("");
  const [copied, setCopied] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  async function generate() {
    setWorking(true);
    setError(null);
    try {
      const result = await api.missionHandoff(mission.id, question);
      setText(result.text);
      // Generating the handoff is what completes the last step, so the response carries
      // the recomputed mission. Dropping it left the page showing step 5 as outstanding
      // after it had been satisfied — the same "your click worked and the screen says it
      // did not" failure the service layer had.
      if (result.mission) onMission(result.mission);
    } catch (err) {
      setError(err.message);
    } finally {
      setWorking(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      /* the textarea stays selectable by hand */
    }
  }

  return (
    <Panel state={state} eyebrow="Step 5" title="Summary for your advisor">
      <p className="muted">
        Everything you reported, what the rules say about it, what could not be confirmed,
        and the risks you decided to carry. Copy it into an email — UAX does not send
        anything for you.
      </p>
      <input
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Your main question, in one sentence (optional)"
        aria-label="Your question for the advisor"
        disabled={busy || working}
      />
      <div className="decoder__actions">
        <button
          type="button"
          className="btn btn--primary"
          onClick={generate}
          disabled={busy || working}
        >
          {working ? "Building…" : text ? "Rebuild" : "Generate the summary"}
        </button>
        {text ? (
          <button type="button" className="btn" onClick={copy}>
            {copied ? "Copied ✓" : "Copy to clipboard"}
          </button>
        ) : null}
      </div>
      {error ? <p className="msg--error">{error}</p> : null}
      {text ? (
        <textarea
          className="handoff__text"
          readOnly
          value={text}
          rows={16}
          aria-label="Generated advisor email"
        />
      ) : null}
    </Panel>
  );
}
