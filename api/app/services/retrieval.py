"""Policy retrieval: vector search with the role filter inside the query.

Rule 3 lives here. The WHERE clause on visible_to_roles runs in the same statement as the
vector ranking, so a chunk the caller's role may not see is never a candidate — there is
no post-filtering step that could be forgotten. The GIN index on visible_to_roles keeps
the pre-filter cheap.

Degradation (rule 6): if the embedding provider is down, retrieval falls back to keyword
search over the same role-filtered set and says so via `degraded`. Weaker ranking, same
permission boundary — the filter must hold in every mode, not just the happy path.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.services.embeddings import EmbeddingsUnavailableError, embed_one

# Over-fetch on pure vector distance, then re-rank with a home-school boost.
#
# Boosting inside ORDER BY would make the expression non-indexable; fetching a wider
# candidate set first keeps the vector index doing the work it is good at and confines the
# scoring policy to a cheap second pass. At this corpus size either would be fast — the
# shape matters because it is the one that still works when the corpus is large.
#
# A *soft* boost rather than a hard filter, deliberately. Some questions genuinely have no
# home-school answer (the SPS registration page is a pointer to the university-wide rules),
# and a hard filter would answer "nothing found" while the correct answer sat one row down.
VECTOR_SQL = text(
    """
    WITH candidates AS (
        SELECT dc.id, dc.text, dc.heading_path, dc.section_keys,
               d.title, d.url, d.office, d.fetched_at,
               d.school, d.level, d.scope,
               1 - (dc.embedding <=> CAST(:query_vec AS vector)) AS raw_score
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE d.is_active
          AND dc.strategy = :strategy
          AND dc.embedding IS NOT NULL
          AND dc.visible_to_roles @> ARRAY[:role]::varchar(16)[]
        ORDER BY dc.embedding <=> CAST(:query_vec AS vector)
        LIMIT :candidate_k
    )
    SELECT id, text, heading_path, section_keys, title, url, office, fetched_at,
           school, level, raw_score,
           raw_score
             + CASE WHEN school = CAST(:school AS varchar)
                    THEN CAST(:school_boost AS float) ELSE 0 END
             + CASE WHEN level = CAST(:level AS varchar)
                    THEN CAST(:level_boost AS float) ELSE 0 END
             AS score
    FROM candidates
    ORDER BY score DESC
    LIMIT :k
    """
)

# Fallback: crude term matching, same role boundary. Scores are counts, not similarities;
# they are surfaced as-is so a degraded turn never masquerades as a normal one.
KEYWORD_SQL = text(
    """
    SELECT dc.id, dc.text, dc.heading_path, dc.section_keys,
           d.title, d.url, d.office, d.fetched_at,
           d.school, d.level,
           (
             SELECT count(*) FROM unnest(:terms) AS term
             WHERE dc.text ILIKE '%' || term || '%'
                OR dc.heading_path ILIKE '%' || term || '%'
           )::float
           + CASE WHEN d.school = CAST(:school AS varchar) THEN 1 ELSE 0 END
           AS score
    FROM document_chunks dc
    JOIN documents d ON d.id = dc.document_id
    WHERE d.is_active
      AND dc.strategy = :strategy
      AND dc.visible_to_roles @> ARRAY[:role]::varchar(16)[]
    ORDER BY score DESC
    LIMIT :k
    """
)


# How many candidates the vector index returns before the boost re-ranks them. Six times
# the final k: wide enough that a home-school chunk sitting outside the naive top-5 can
# still be promoted, narrow enough to stay cheap.
CANDIDATE_MULTIPLIER = 6

# Tuned by sweep in scripts/ablate_scope.py, not guessed.
#
#   boost  recall@5     MRR   home_scope
#    0.00    0.7367   0.504       0.5833   (no scoping — the recorded baseline)
#    0.08    0.9000   0.8267      0.9583
#    0.12    0.9100   0.8383      0.9583   <- shipped
#    0.20    0.9167   0.8250      0.9583
#
# 0.12 is where MRR peaks. Recall keeps creeping up to 0.20 but MRR turns over, which is
# the signal that the boost has started promoting home-school chunks past better peer-school
# matches — buying recall by degrading ranking. No family regressed at 0.12.
DEFAULT_SCHOOL_BOOST = 0.12
DEFAULT_LEVEL_BOOST = 0.04


@dataclass
class RetrievalScope:
    """Whose policies apply to the person asking.

    Thirty-one NYU schools publish policies on the same topics with different substance,
    so "how many credits is full-time" has a different correct answer per school. Without
    this the retriever has no way to prefer the asker's own — measured at 9 of 12 misses.
    """

    school: str | None = None
    level: str | None = None


@dataclass
class RetrievedChunk:
    chunk_id: int
    text: str
    heading_path: str | None
    # Source sections covered, so retrieval eval can score a hit without knowing how the
    # active strategy drew its boundaries.
    section_keys: list[str]
    document_title: str
    url: str
    office: str
    fetched_at: str
    score: float
    rank: int
    school: str | None = None
    # Similarity before the scope boost, kept so a ranking change is attributable.
    raw_score: float | None = None


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    degraded: bool  # True when keyword fallback served this query


def search_policy(
    session: Session,
    query: str,
    role: str,
    k: int = 5,
    strategy: str | None = None,
    scope: RetrievalScope | None = None,
    school_boost: float = DEFAULT_SCHOOL_BOOST,
    level_boost: float = DEFAULT_LEVEL_BOOST,
) -> RetrievalResult:
    active = strategy or settings.chunk_strategy
    scope = scope or RetrievalScope()

    try:
        vector = embed_one(query)
        rows = session.execute(
            VECTOR_SQL,
            {
                "query_vec": str(vector),
                "role": role,
                "k": k,
                "candidate_k": k * CANDIDATE_MULTIPLIER,
                "strategy": active,
                "school": scope.school,
                "level": scope.level,
                "school_boost": school_boost,
                "level_boost": level_boost,
            },
        ).all()
        degraded = False
    except EmbeddingsUnavailableError:
        terms = [t for t in query.lower().split() if len(t) > 2][:8]
        rows = session.execute(
            KEYWORD_SQL,
            {
                "terms": terms, "role": role, "k": k,
                "strategy": active, "school": scope.school,
            },
        ).all()
        rows = [r for r in rows if r.score > 0]
        degraded = True

    chunks = [
        RetrievedChunk(
            chunk_id=row.id,
            text=row.text,
            heading_path=row.heading_path,
            section_keys=list(row.section_keys or []),
            document_title=row.title,
            url=row.url,
            office=row.office,
            fetched_at=row.fetched_at.isoformat(),
            score=round(float(row.score), 4),
            rank=i + 1,
            school=getattr(row, "school", None),
            raw_score=round(float(row.raw_score), 4) if hasattr(row, "raw_score") else None,
        )
        for i, row in enumerate(rows)
    ]
    return RetrievalResult(chunks=chunks, degraded=degraded)
