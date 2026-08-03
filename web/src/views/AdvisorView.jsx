import { useEffect, useState } from "react";
import { api } from "../api";
import { Empty, ErrorState, Loading, Stat, StatusPill } from "../components";

const STATUS_TONE = { on_track: "good", watchlist: "warn", at_risk: "danger" };

export default function AdvisorView({ advisorId, onOpenStudent }) {
  const [queue, setQueue] = useState(null);
  const [cases, setCases] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyCase, setBusyCase] = useState(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [q, c] = await Promise.all([
        api.advisorQueue(advisorId),
        api.cases({ advisor_id: advisorId }),
      ]);
      setQueue(q);
      setCases(c);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [advisorId]);

  async function advance(caseId, status) {
    setBusyCase(caseId);
    try {
      await api.updateCase(caseId, { status, actor_user_id: advisorId });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyCase(null);
    }
  }

  if (loading) return <Loading what="your caseload" />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!queue) return null;

  // Entries arrive pre-sorted by triage rank; grouping preserves that order.
  const groups = [];
  for (const entry of queue.entries) {
    const last = groups[groups.length - 1];
    if (last && last.name === entry.group) last.items.push(entry);
    else groups.push({ name: entry.group, items: [entry] });
  }

  const openCases = cases.filter((c) => c.status !== "resolved");

  return (
    <div className="stack">
      <section className="card">
        <p className="eyebrow">Advisor hub</p>
        <h2>{queue.advisor_name}</h2>
        <div className="stats">
          <Stat label="Advisees" value={queue.caseload} />
          <Stat label="At risk" value={queue.at_risk_count} tone={queue.at_risk_count ? "danger" : undefined} />
          <Stat label="Open escalations" value={queue.open_escalations} tone={queue.open_escalations ? "warn" : undefined} />
          <Stat label="Resolved this week" value={queue.resolved_this_week} />
        </div>
      </section>

      <section className="card" aria-labelledby="cases-heading">
        <h3 id="cases-heading">Open cases</h3>
        {openCases.length === 0 ? (
          <Empty>No open cases in your caseload.</Empty>
        ) : (
          <ul className="cases">
            {openCases.map((item) => (
              <li key={item.id} className="case">
                <div className="case__head">
                  <span className="case__number">{item.case_number}</span>
                  <StatusPill tone={item.status === "new" ? "danger" : "warn"} label={item.status_label} />
                </div>
                <p className="case__title">{item.title}</p>
                <p className="muted">
                  {item.student_name} · opened by {item.opened_by}
                </p>
                {item.ai_summary ? (
                  <div className="case__summary">
                    <span className="case__summary-label">Assistant summary</span>
                    <p>{item.ai_summary}</p>
                  </div>
                ) : null}
                <div className="case__actions">
                  {item.status !== "in_review" ? (
                    <button
                      type="button"
                      className="btn"
                      disabled={busyCase === item.id}
                      onClick={() => advance(item.id, "in_review")}
                    >
                      Take for review
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="btn btn--primary"
                    disabled={busyCase === item.id}
                    onClick={() => advance(item.id, "resolved")}
                  >
                    Resolve
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card" aria-labelledby="queue-heading">
        <h3 id="queue-heading">Triage queue</h3>
        {groups.map((group) => (
          <div key={group.name} className="group">
            <p className="group__label">
              {group.name} <span className="group__count">{group.items.length}</span>
            </p>
            <ul className="queue">
              {group.items.map((entry) => (
                <li key={entry.student_id} className="queue__row">
                  <button
                    type="button"
                    className="queue__name"
                    onClick={() => onOpenStudent(entry.student_id)}
                  >
                    {entry.full_name}
                  </button>
                  <span className="queue__meta">
                    <StatusPill tone={STATUS_TONE[entry.readiness_status]} label={entry.readiness_label} />
                  </span>
                  <span className="queue__facts">
                    {entry.active_holds > 0 ? `${entry.active_holds} hold(s)` : "no holds"}
                    {entry.failed_attempts > 0 ? ` · ${entry.failed_attempts} failed attempts` : ""}
                    {entry.days_until_registration != null
                      ? ` · registers in ${entry.days_until_registration}d`
                      : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
