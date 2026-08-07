import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading } from "../components";

/**
 * The sequence planner: what order the remaining requirements can be taken in.
 *
 * The layout is arranged around one risk. A term-by-term schedule is the most
 * authoritative-looking thing this product produces — it is a grid, it has dates, and a
 * student will screenshot it and plan a year around it. But a third of the catalog does not
 * say when its courses run, the per-term credit cap is the student's own number rather than a
 * published rule for this program, and an open-ended elective is a placeholder with no
 * prerequisites checked.
 *
 * So each placement carries its own basis inline — "offered Fall, Spring" against "the
 * bulletin does not say when this runs" — rather than one disclaimer under the grid. A
 * caveat averaged across the whole plan tells the student nothing about which two courses
 * are the shaky ones, and those are exactly the two they need to go and check.
 *
 * When nothing fits, the binding constraint takes the position the grid would have had.
 * "No sequence works" is nearly useless; "the finish date is the only thing in the way, and
 * one more term fixes it" is the answer.
 */

const BASIS_META = {
  published: { tone: "good", label: "Published" },
  irregular: { tone: "warn", label: "Runs irregularly" },
  unstated: { tone: "neutral", label: "Term is a guess" },
};

const CREDIT_CHOICES = [3, 6, 9, 12];

export default function SequenceView({ onOpenPlanner }) {
  const [startTerm, setStartTerm] = useState("");
  const [deadline, setDeadline] = useState("");
  const [maxCredits, setMaxCredits] = useState("");
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function load(overrides = {}) {
    setBusy(true);
    setError(null);
    try {
      setPlan(
        await api.sequence({
          startTerm: overrides.startTerm ?? startTerm,
          deadline: overrides.deadline ?? deadline,
          maxCredits: overrides.maxCredits ?? maxCredits,
        }),
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error && !plan) return <ErrorState message={error} onRetry={() => load()} />;
  if (!plan) return <Loading what="your sequence" />;

  return (
    <div className="stack">
      {error ? <ErrorState message={error} /> : null}

      <section className="card">
        <p className="eyebrow">Remaining requirements</p>
        <h2>What order can I take these in?</h2>
        <p className="muted">
          Prerequisite order, when the bulletin says each course runs, how many credits you
          will carry, one concentration finished in full, and a term to finish by — solved
          together, because that is the part you cannot do on paper.
        </p>

        <form
          className="seq__controls"
          onSubmit={(e) => {
            e.preventDefault();
            load();
          }}
        >
          <label className="seq__field">
            <span>Starting term</span>
            <input
              value={startTerm}
              onChange={(e) => setStartTerm(e.target.value)}
              placeholder={plan.start_term}
              disabled={busy}
            />
          </label>
          <label className="seq__field">
            <span>Finish by (optional)</span>
            <input
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
              placeholder="e.g. Spring 2028"
              disabled={busy}
            />
          </label>
          <label className="seq__field">
            <span>Credits per term</span>
            <select
              value={maxCredits}
              onChange={(e) => {
                setMaxCredits(e.target.value);
                load({ maxCredits: e.target.value });
              }}
              disabled={busy}
            >
              <option value="">{plan.max_credits_per_term} (assumed)</option>
              {CREDIT_CHOICES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {busy ? "Solving…" : "Recalculate"}
          </button>
        </form>

        <p className="planner__disclaimer">{plan.disclaimer}</p>
      </section>

      {plan.feasible ? (
        <Schedule plan={plan} />
      ) : (
        <Blocked plan={plan} onOpenPlanner={onOpenPlanner} />
      )}

      {plan.rejected_tracks.length > 0 ? (
        <section className="card">
          <p className="eyebrow">Concentrations that do not fit</p>
          <h2>Other tracks</h2>
          <p className="muted">
            You are free to change concentration, so each one was tried. These could not be
            sequenced under the same constraints.
          </p>
          <ul className="findings">
            {plan.rejected_tracks.map((t) => (
              <li key={t.track} className="finding finding--warn">
                <div className="finding__head">
                  <span className="finding__summary">{t.track}</span>
                </div>
                <p className="finding__detail">{t.why}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <Assumptions plan={plan} onOpenPlanner={onOpenPlanner} />
    </div>
  );
}

/* ---------------------------------------------------------------------------------- */

function Schedule({ plan }) {
  const guesses = plan.terms
    .flatMap((t) => t.courses)
    .filter((c) => c.offering_basis !== "published").length;

  return (
    <section className="card card--hero">
      <div className="hero__top">
        <div>
          <p className="eyebrow">
            {plan.chosen_track ? `Concentration: ${plan.chosen_track}` : "Sequence"}
          </p>
          <h2>
            {plan.terms_needed} more term{plan.terms_needed === 1 ? "" : "s"}, finishing{" "}
            {plan.finish_term}
          </h2>
          <p className="hero__reason">
            {guesses === 0
              ? "Every placement matches a term the bulletin publishes for that course."
              : `${guesses} placement${guesses === 1 ? "" : "s"} sit in a term the bulletin does not confirm — marked below.`}
          </p>
        </div>
      </div>

      <ol className="seq__terms">
        {plan.terms.map((term) => (
          <li key={term.term} className="seq__term">
            <div className="seq__term-head">
              <span className="seq__term-name">{term.term}</span>
              <span className="muted">{term.credits} credits</span>
            </div>
            <ul className="seq__courses">
              {term.courses.map((course) => {
                const meta = BASIS_META[course.offering_basis] ?? BASIS_META.unstated;
                return (
                  <li key={course.course_code} className="seq__course">
                    <div className="seq__course-head">
                      <span className="mono">{course.course_code}</span>
                      <span className={`tag tag--${meta.tone}`}>{meta.label}</span>
                    </div>
                    <p className="seq__course-title">{course.title}</p>
                    <p className="muted">
                      {course.requirement ? `${course.requirement} · ` : ""}
                      {course.credits} cr · {course.offering_note}
                      {course.offering_source ? ` (“${course.offering_source}”)` : ""}
                    </p>
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Blocked({ plan, onOpenPlanner }) {
  const why = plan.infeasibility;
  return (
    <section className="card card--focus">
      <p className="eyebrow">No order fits</p>
      <h2>What is standing in the way</h2>
      <p className="seq__blocked">{why?.explanation}</p>

      {why?.binding_labels?.length ? (
        <>
          <p className="eyebrow">Any one of these would unblock it</p>
          <ul className="findings">
            {why.binding_labels.map((label, i) => (
              <li key={label} className="finding finding--warn">
                <div className="finding__head">
                  <span className="finding__summary">{label}</span>
                </div>
                {why.remedies[i] ? (
                  <p className="finding__detail">{why.remedies[i]}</p>
                ) : null}
              </li>
            ))}
          </ul>
          <p className="muted">
            Each of these was established by removing it and re-solving — not inferred.
          </p>
        </>
      ) : null}

      {onOpenPlanner ? (
        <button type="button" className="btn" onClick={onOpenPlanner}>
          Check my record →
        </button>
      ) : null}
    </section>
  );
}

function Assumptions({ plan, onOpenPlanner }) {
  if (plan.assumptions.length === 0 && plan.unplaceable.length === 0) return null;

  return (
    <section className="card">
      <p className="eyebrow">What this rests on</p>
      <h2>Assumptions</h2>
      <p className="muted">
        The sequence above is only as good as these. None of them is a rule UAX could verify.
      </p>
      <ul className="findings">
        {plan.assumptions.map((a) => (
          <li key={a.subject} className="finding finding--neutral">
            <div className="finding__head">
              <span className="finding__mark">?</span>
              <span className="finding__summary">{a.subject}</span>
            </div>
            <p className="finding__detail">{a.statement}</p>
            {a.check ? <p className="finding__next">{a.check}</p> : null}
          </li>
        ))}
      </ul>
      {plan.unplaceable.length > 0 ? (
        <p className="note note--warn">
          Left out of the sequence entirely, because they are not in the catalog UAX has
          loaded: {plan.unplaceable.join(", ")}.
        </p>
      ) : null}
      {onOpenPlanner ? (
        <button type="button" className="btn" onClick={onOpenPlanner}>
          Edit my record →
        </button>
      ) : null}
    </section>
  );
}
