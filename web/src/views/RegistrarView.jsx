import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, Meter, ProvenanceTag, Stat } from "../components";

const PRESSURE_TONE = {
  "at capacity": "danger",
  filling: "warn",
  steady: "accent",
  open: "good",
};

export default function RegistrarView() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await api.registrarPressure());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  if (loading) return <Loading what="enrollment operations" />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) return null;

  const topReason = data.failure_breakdown[0];
  const maxAttempts = topReason?.attempts ?? 1;

  return (
    <div className="stack">
      <section className="card">
        <p className="eyebrow">Registrar operations</p>
        <h2>{data.term_name}</h2>
        <div className="stats">
          <Stat label="Registration attempts" value={data.total_attempts} />
          <Stat
            label="Failed"
            value={data.failed_attempts}
            hint={`${data.failure_rate_percent}% of attempts`}
            tone={data.failure_rate_percent > 30 ? "danger" : "warn"}
          />
          <Stat
            label="Sections at capacity"
            value={data.sections_at_capacity}
            tone={data.sections_at_capacity ? "warn" : undefined}
          />
          <Stat
            label="Students with blocking holds"
            value={data.students_with_blocking_holds}
            tone={data.students_with_blocking_holds ? "danger" : undefined}
          />
        </div>
      </section>

      {/* The same rows that tell a student "here is why you were rejected" tell the
          registrar "here is where the errors cluster". */}
      <section className="card" aria-labelledby="reasons-heading">
        <h3 id="reasons-heading">Why registrations are failing</h3>
        <ul className="reasons">
          {data.failure_breakdown.map((bucket) => (
            <li key={bucket.reason} className="reason">
              <div className="reason__head">
                <span>{bucket.label}</span>
                <span className="reason__count">
                  {bucket.attempts} <span className="muted">({bucket.percent}%)</span>
                </span>
              </div>
              <Meter
                value={bucket.attempts}
                max={maxAttempts}
                tone="accent"
                label={`${bucket.label}: ${bucket.attempts} failed attempts`}
              />
            </li>
          ))}
        </ul>
      </section>

      <section className="card" aria-labelledby="sections-heading">
        <h3 id="sections-heading">Section pressure</h3>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Course</th>
                <th scope="col">Seats</th>
                <th scope="col">Fill</th>
                <th scope="col">Waitlist</th>
                <th scope="col">Restriction</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.sections.map((section) => (
                <tr key={section.section_id}>
                  <th scope="row">
                    <span className="mono">{section.course_code}</span>
                    <span className="muted"> {section.course_title}</span>
                  </th>
                  <td className="num">
                    {section.enrolled}/{section.capacity}
                  </td>
                  <td className="num">{section.fill_percent}%</td>
                  <td className="num">{section.waitlisted || "—"}</td>
                  <td>{section.restriction ?? "—"}</td>
                  <td>
                    <span className={`tag tag--${PRESSURE_TONE[section.pressure]}`}>
                      {section.pressure}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.sections[0] ? <ProvenanceTag provenance={data.sections[0].provenance} /> : null}
      </section>
    </div>
  );
}
