import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, Meter, ProvenanceTag, StatusPill } from "../components";

const STATUS_TONE = { on_track: "good", watchlist: "warn", at_risk: "danger" };

export default function StudentView({ studentId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await api.readiness(studentId));
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

  return (
    <div className="stack">
      {/* Zone 1 used to be a critical-blocker banner fed by the holds table. Both are gone
          (2026-08-13): this product cannot see a hold, and a banner is the loudest possible
          place to assert one. What replaces it claims nothing about this student. */}
      <div className="alert" role="note">
        <div className="alert__head">
          <strong>Before you register</strong>
        </div>
        <p className="alert__body">
          Path Pilot cannot see holds, your enrollment appointment, or seat availability —
          those live in Albert and only Albert. Check there before your window opens. What
          is below is your degree progress, from the courses you entered.
        </p>
      </div>

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

    </div>
  );
}
