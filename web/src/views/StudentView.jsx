import { useEffect, useState } from "react";
import { api, formatDate, formatMoney } from "../api";
import { Empty, ErrorState, Loading, Meter, ProvenanceTag, StatusPill } from "../components";

const STATUS_TONE = { on_track: "good", watchlist: "warn", at_risk: "danger" };
const URGENCY_TONE = { critical: "danger", high: "danger", normal: "warn", low: "neutral" };

export default function StudentView({ studentId }) {
  const [data, setData] = useState(null);
  const [blockers, setBlockers] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [readiness, holds] = await Promise.all([
        api.readiness(studentId),
        api.blockers(studentId),
      ]);
      setData(readiness);
      setBlockers(holds);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studentId]);

  if (loading) return <Loading what="your dashboard" />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) return null;

  const critical = blockers.filter((b) => b.urgency === "critical");

  return (
    <div className="stack">
      {/* Zone 1: critical alerts, above everything else. A student cannot act on degree
          planning while registration is blocked, so blockers outrank the hero card. */}
      {critical.map((blocker) => (
        <div key={blocker.id} className="alert" role="alert">
          <div className="alert__head">
            <strong>Registration blocker</strong>
            <span className="alert__flag">{blocker.urgency_label}</span>
          </div>
          <p className="alert__title">{blocker.title}</p>
          <p className="alert__body">{blocker.required_action}</p>
          <p className="alert__meta">
            {blocker.deadline_at ? (
              <>
                Due {formatDate(blocker.deadline_at)}
                {blocker.days_until_deadline != null
                  ? ` · ${blocker.days_until_deadline} days left`
                  : ""}
                {data.student.days_until_registration != null
                  ? ` · your registration opens in ${data.student.days_until_registration} days`
                  : ""}
              </>
            ) : (
              "No deadline on file"
            )}
          </p>
          {blocker.resolution_url ? (
            <a className="btn btn--primary" href={blocker.resolution_url} target="_blank" rel="noreferrer">
              Resolve with {blocker.office.replace(/_/g, " ")}
            </a>
          ) : null}
        </div>
      ))}

      {/* Zone 2: the headline question — will I graduate on time? */}
      <section className="card card--hero" aria-labelledby="readiness-heading">
        <div className="hero__top">
          <div>
            <p className="eyebrow">Graduation status</p>
            <h2 id="readiness-heading">{data.student.full_name}</h2>
            <p className="muted">
              {data.student.program_name} · expected {data.student.expected_graduation_term ?? "—"}
            </p>
          </div>
          <StatusPill
            tone={STATUS_TONE[data.status]}
            label={data.status_label}
            action={data.status_action}
          />
        </div>

        <p className="hero__reason">{data.status_reason}</p>

        <div className="hero__progress">
          <div className="hero__numbers">
            <span className="hero__pct">{data.percent_complete}%</span>
            <span className="muted">
              {data.credits_applied} of {data.credits_required} credits applied
            </span>
          </div>
          <Meter
            value={data.credits_applied}
            max={data.credits_required}
            tone={STATUS_TONE[data.status]}
            label={`${data.credits_applied} of ${data.credits_required} credits applied`}
          />
          {data.credits_unapplied > 0 ? (
            <p className="note note--warn">
              You have earned {data.credits_earned_raw} credits, but {data.credits_unapplied} of
              them exceed a requirement limit and do not count toward your degree. Your
              applicable total is {data.credits_applied}.
            </p>
          ) : null}
        </div>

        <ProvenanceTag provenance={data.provenance} />
      </section>

      {/* Zone 3: requirement breakdown — where the gap actually is. */}
      <section className="card" aria-labelledby="req-heading">
        <h3 id="req-heading">Requirements</h3>
        <ul className="reqs">
          {data.requirements.map((req) => (
            <li key={req.name} className="req">
              <div className="req__head">
                <span className="req__name">{req.name}</span>
                <span className="req__count">
                  {req.applied_credits}/{req.required_credits} credits
                  {req.satisfied ? " · complete" : ` · ${req.remaining_credits} to go`}
                </span>
              </div>
              <Meter
                value={req.applied_credits}
                max={req.required_credits}
                tone={req.satisfied ? "good" : "accent"}
                label={`${req.name}: ${req.applied_credits} of ${req.required_credits} credits`}
              />
              {req.unapplied_credits > 0 ? (
                <p className="note note--warn">
                  {req.unapplied_credits} earned credits above the {req.required_credits}-credit
                  limit are not counted.
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      {/* Remaining blockers, including anything not critical enough for the banner. */}
      <section className="card" aria-labelledby="blockers-heading">
        <h3 id="blockers-heading">Blockers and holds</h3>
        {blockers.length === 0 ? (
          <Empty>Nothing is currently blocking your registration.</Empty>
        ) : (
          <ul className="blockers">
            {blockers.map((blocker) => (
              <li key={blocker.id} className={`blocker blocker--${URGENCY_TONE[blocker.urgency]}`}>
                <div className="blocker__head">
                  <span className="blocker__title">{blocker.title}</span>
                  <StatusPill tone={URGENCY_TONE[blocker.urgency]} label={blocker.urgency_label} />
                </div>
                <p>{blocker.explanation}</p>
                <p className="blocker__action">
                  <strong>Next step:</strong> {blocker.required_action}
                </p>
                <p className="blocker__meta">
                  {blocker.office.replace(/_/g, " ")}
                  {blocker.amount_cents != null ? ` · ${formatMoney(blocker.amount_cents)}` : ""}
                  {blocker.deadline_at ? ` · due ${formatDate(blocker.deadline_at)}` : ""}
                </p>
                <ProvenanceTag provenance={blocker.provenance} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
