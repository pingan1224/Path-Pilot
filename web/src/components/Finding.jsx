import { verdictMeta } from "@/lib/verdicts";

/**
 * The finding card — this product's signature surface.
 *
 * Everything UAX does ends in one of these: a verdict, why, what to do next, and the source
 * it rests on. It was hand-rolled eight times across four views, and the copies disagreed
 * about the one thing that matters — DecoderView, MissionView and SequenceView shipped the
 * verdict as colour and a glyph with no text label at all.
 *
 * The API is deliberately narrow. There is **no `tone` prop**: tone comes from the verdict,
 * because the two callers that hardcoded `finding--danger` and `✕` were writing a verdict
 * without saying so, and the next person to add a card would have picked a colour by eye.
 * `label` overrides only the wording, never the colour, for the cases where the surrounding
 * section already names the verdict ("Accepted knowingly") and repeating it reads as a stutter.
 *
 * Pass `finding` when the server handed back its standard shape; pass the fields explicitly
 * for the cards built from something else (a track that does not fit, a sequencing
 * assumption). Explicit fields win, so a caller can take the object and correct one part of it.
 */
export function Finding({
  finding,
  verdict,
  summary,
  detail,
  nextStep,
  citations,
  label,
  children,
}) {
  const f = finding ?? {};
  const meta = verdictMeta(verdict ?? f.verdict);
  summary = summary ?? f.summary;
  detail = detail ?? f.detail;
  nextStep = nextStep ?? f.next_step;
  citations = citations ?? f.citations;

  return (
    <li className={`finding finding--${meta.tone}`}>
      <div className="finding__head">
        <span className="finding__mark" aria-hidden="true">
          {meta.mark}
        </span>
        <span className="finding__summary">{summary}</span>
        <span className={`tag tag--${meta.tone}`}>
          {label ?? meta.label}
          <span className="visually-hidden"> — {meta.action}</span>
        </span>
      </div>
      {detail ? <p className="finding__detail">{detail}</p> : null}
      {nextStep ? <p className="finding__next">→ {nextStep}</p> : null}
      {citations?.length ? <Sources citations={citations} /> : null}
      {children ? <div className="finding__actions">{children}</div> : null}
    </li>
  );
}

/**
 * Collapsed by default because a finding is read for its verdict; the citation is there for
 * the reader who doubts it. The count is in the summary so "is this claim actually sourced"
 * is answerable without opening it — an uncited finding shows no toggle at all.
 */
function Sources({ citations }) {
  return (
    <details className="finding__sources">
      <summary>{citations.length === 1 ? "Source" : `${citations.length} sources`}</summary>
      {citations.map((c, i) => (
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
  );
}

/**
 * A retrieved bulletin passage. Not a finding, though it was rendered with the finding
 * classes: a finding is this system's judgement about the student, a passage is somebody
 * else's published text quoted verbatim. Giving them one look invited the reader to trust
 * both the same amount, and only one of them is a claim UAX is making.
 */
export function Passage({ title, text, source, office, fetchedOn, url }) {
  return (
    <li className="passage">
      <p className="passage__title">{title}</p>
      <blockquote className="passage__text">{text}</blockquote>
      <p className="passage__cite">
        {url ? (
          <a href={url} target="_blank" rel="noreferrer">
            {source}
          </a>
        ) : (
          source
        )}
        {office ? ` · ${office.replace(/_/g, " ")}` : ""}
        {fetchedOn ? ` · fetched ${fetchedOn}` : ""}
      </p>
    </li>
  );
}
