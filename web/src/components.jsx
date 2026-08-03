import { humanizeAge } from "./api";

/**
 * Where a value came from and how old it is.
 *
 * Rendered next to every mirrored fact. When the value is past its source's tolerance the
 * badge changes text as well as colour and shows the office's own disclosure, so a stale
 * balance never looks like a current one.
 */
export function ProvenanceTag({ provenance }) {
  if (!provenance) return null;
  const { label, office, age_seconds, is_stale, disclosure } = provenance;

  return (
    <div className={`prov ${is_stale ? "prov--stale" : ""}`}>
      <span className="prov__line">
        <span className="prov__source">{label}</span>
        <span className="prov__sep" aria-hidden="true">·</span>
        <span>{office.replace(/_/g, " ")}</span>
        <span className="prov__sep" aria-hidden="true">·</span>
        <span>
          {is_stale ? "May be out of date — last verified " : "Verified "}
          {humanizeAge(age_seconds)}
        </span>
      </span>
      {is_stale && disclosure ? <p className="prov__disclosure">{disclosure}</p> : null}
    </div>
  );
}

/**
 * Status as text first, colour second. The label is never the only carrier of meaning —
 * `action` spells out what the colour is trying to say.
 */
export function StatusPill({ tone, label, action }) {
  return (
    <span className={`pill pill--${tone}`}>
      <span className="pill__label">{label}</span>
      {action ? <span className="pill__action">{action}</span> : null}
    </span>
  );
}

export function Meter({ value, max, tone = "accent", label }) {
  const percent = max > 0 ? Math.min(100, Math.round((100 * value) / max)) : 0;
  return (
    <div className="meter">
      <div
        className="meter__track"
        role="meter"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-label={label}
      >
        <div className={`meter__fill meter__fill--${tone}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export function Stat({ label, value, hint, tone }) {
  return (
    <div className={`stat ${tone ? `stat--${tone}` : ""}`}>
      <span className="stat__label">{label}</span>
      <span className="stat__value">{value}</span>
      {hint ? <span className="stat__hint">{hint}</span> : null}
    </div>
  );
}

export function Loading({ what }) {
  return <p className="state state--loading">Loading {what}…</p>;
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="state state--error" role="alert">
      <p>{message}</p>
      {onRetry ? (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Empty({ children }) {
  return <p className="state state--empty">{children}</p>;
}
