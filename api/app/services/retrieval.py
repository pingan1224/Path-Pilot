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

from app import faults
from app.config import settings
from app.services.embeddings import EmbeddingsUnavailableError, embed_one

# Hybrid: dense retrieval fused with lexical retrieval by Reciprocal Rank Fusion.
#
# RRF over score normalisation on purpose. Cosine similarity sits around 0.5-0.7 while
# ts_rank_cd is unbounded and corpus-dependent; any weighted sum of the two requires
# inventing a normalisation that quietly becomes a tuning parameter nobody can defend.
# RRF only reads positions, so the two systems never have to be made comparable.
#
# The lexical arm tries AND first and falls back to OR only when AND finds nothing.
#
# Measured, after getting it wrong the other way round. An all-OR arm looked safer — AND
# seemed too strict for natural questions — but the numbers said the opposite: for
# "MASY1-GC 2100 prerequisites" the AND query matches exactly one chunk, the right one,
# while OR matches 67 whose top five tie at an identical rank because every MASY course
# shares the terms `masy1-gc` and `prerequisit` and the discriminating `2100` carries no
# extra weight. All-OR destroyed the very case hybrid retrieval was added to fix. It is
# also indiscriminate on vague questions: a colloquial query matched 355 of 1,012 chunks,
# a third of the corpus fed into the fusion with the same standing as dense results.
#
# Precision when it is available, recall only as a fallback.
HYBRID_SQL = text(
    """
    WITH raw AS (
        SELECT plainto_tsquery('english', :query) AS strict,
               CAST(
                 replace(plainto_tsquery('english', :query)::text, '&', '|') AS tsquery
               ) AS loose
    ),
    q AS (
        SELECT CASE
                 WHEN EXISTS (
                   SELECT 1 FROM document_chunks dc2
                   WHERE dc2.strategy = :strategy AND dc2.tsv @@ raw.strict
                 ) THEN raw.strict
                 ELSE raw.loose
               END AS lex
        FROM raw
    ),
    vec AS (
        SELECT dc.id, ROW_NUMBER() OVER (
                   ORDER BY dc.embedding <=> CAST(:query_vec AS vector)
               ) AS rank
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE d.is_active
          AND dc.strategy = :strategy
          AND dc.embedding IS NOT NULL
          AND dc.visible_to_roles @> ARRAY[:role]::varchar(16)[]
        ORDER BY dc.embedding <=> CAST(:query_vec AS vector)
        LIMIT :candidate_k
    ),
    lex AS (
        SELECT dc.id, ROW_NUMBER() OVER (
                   ORDER BY ts_rank_cd(dc.tsv, q.lex) DESC
               ) AS rank
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        CROSS JOIN q
        WHERE d.is_active
          AND dc.strategy = :strategy
          AND dc.visible_to_roles @> ARRAY[:role]::varchar(16)[]
          AND dc.tsv @@ q.lex
        ORDER BY ts_rank_cd(dc.tsv, q.lex) DESC
        LIMIT :candidate_k
    ),
    fused AS (
        SELECT COALESCE(vec.id, lex.id) AS id,
               COALESCE(1.0 / (:rrf_k + vec.rank), 0) AS vec_rrf,
               COALESCE(1.0 / (:rrf_k + lex.rank), 0) AS lex_rrf
        FROM vec FULL OUTER JOIN lex ON vec.id = lex.id
    )
    SELECT dc.id, dc.text, dc.heading_path, dc.section_keys,
           d.title, d.url, d.office, d.fetched_at, d.school, d.level,
           (f.vec_rrf + f.lex_rrf) AS raw_score,
           f.vec_rrf + f.lex_rrf
             + CASE WHEN d.school IS NULL
                      OR d.school = CAST(:school AS varchar)
                      OR d.school = 'synthetic'
                    THEN CAST(:school_boost AS float) ELSE 0 END
             + CASE WHEN d.level IS NULL OR d.level = CAST(:level AS varchar)
                    THEN CAST(:level_boost AS float) ELSE 0 END
             AS score
    FROM fused f
    JOIN document_chunks dc ON dc.id = f.id
    JOIN documents d ON d.id = dc.document_id
    ORDER BY score DESC
    LIMIT :k
    """
)

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
#
# The boost also applies to unaffiliated documents, not only the home school. Only a *peer
# school's* answer is the wrong answer; a university-wide policy is the right one for
# everybody. Restricting the boost to the home school silently demoted every unaffiliated
# document — invisible in cosine space where the boost is small beside the score, and
# glaring once RRF shrank the scale: restricted-document recall fell 1.00 -> 0.00 because
# those fixtures carry no school and were crowded out by boosted SPS chunks.
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
             + CASE WHEN school IS NULL
                      OR school = CAST(:school AS varchar)
                      OR school = 'synthetic'
                    THEN CAST(:school_boost AS float) ELSE 0 END
             + CASE WHEN level IS NULL OR level = CAST(:level AS varchar)
                    THEN CAST(:level_boost AS float) ELSE 0 END
             AS score
    FROM candidates
    ORDER BY score DESC
    LIMIT :k
    """
)

# Fallback: crude term matching, same role boundary. Scores are counts, not similarities;
# they are surfaced as-is so a degraded turn never masquerades as a normal one.
#
# `CAST(:terms AS varchar[])` is load-bearing, and its absence is the first thing fault
# injection found. A bare `unnest(:terms)` sends the array as an untyped parameter, and
# Postgres cannot choose between the unnest overloads: "function unnest(unknown) is not
# unique". This entire fallback therefore raised on its first statement from the day it was
# written — the documented degraded path for an embeddings outage would itself have failed,
# in the one situation it exists for. Nothing caught it because nothing ever ran it.
KEYWORD_SQL = text(
    """
    WITH matched AS (
        SELECT dc.id, dc.text, dc.heading_path, dc.section_keys,
               d.title, d.url, d.office, d.fetched_at,
               d.school, d.level,
               (
                 SELECT count(*) FROM unnest(CAST(:terms AS varchar[])) AS term
                 WHERE dc.text ILIKE '%' || term || '%'
                    OR dc.heading_path ILIKE '%' || term || '%'
               )::float AS match_count
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE d.is_active
          AND dc.strategy = :strategy
          AND dc.visible_to_roles @> ARRAY[:role]::varchar(16)[]
    )
    SELECT id, text, heading_path, section_keys, title, url, office, fetched_at,
           school, level, match_count,
           match_count
             + CASE WHEN school IS NULL
                      OR school = CAST(:school AS varchar)
                      OR school = 'synthetic'
                    THEN CAST(:school_boost AS float) ELSE 0 END
             + CASE WHEN level IS NULL OR level = CAST(:level AS varchar)
                    THEN CAST(:level_boost AS float) ELSE 0 END
             AS score
    FROM matched
    -- Matching no term at all is not a weak result, it is not a result. Filtering here
    -- rather than on the final score is the difference between "drop the rows that
    -- matched nothing" and "drop every row whose score is under the boost", which at a
    -- large boost quietly deletes the whole peer-school half of the corpus and turns the
    -- boost into a hard filter without saying so.
    WHERE match_count > 0
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

# RRF puts scores on a completely different scale: with k=60 a first-place hit contributes
# 1/61 ≈ 0.016, so the 0.12 boost tuned for cosine space would swamp the fusion entirely.
# Hybrid therefore carries its own pair, swept separately in scripts/ablate_hybrid.py.
RRF_K = 60
HYBRID_SCHOOL_BOOST = 0.010
HYBRID_LEVEL_BOOST = 0.003

# The keyword fallback needs its own pair for the third time, because its scores are term
# *counts* — small integers, at most 8 — not similarities. The 0.12 tuned for cosine space
# is a rounding error here, and the 1.0 that was hardcoded before is worth exactly one
# matched term.
#
# Swept by scripts/measure_degraded_retrieval.py, the first measurement this path has ever
# had:
#
#   school  level   recall@5     MRR   home_scope  restricted
#     0.00   0.00     0.3100  0.2517       0.17        0.75   (no scoping)
#     1.00   0.00     0.5767  0.3930       0.42        1.00   (what was hardcoded)
#     2.00   0.50     0.6967  0.4890       0.67        1.00
#     5.00   1.00     0.7367  0.5363       0.67        1.00   <- shipped
#     8.00   1.50     0.7367  0.5647       0.67        1.00
#    12.00   2.00     0.7367  0.5547       0.67        1.00
#
# **Not the argmax, deliberately.** MRR nominally peaks at 8.0, but recall has been flat
# since 5.0 and everything above it is a hard partition already: a chunk must match a term
# to be returned at all, so the lowest possible home-school score is 1 + 5 + 1 = 7 while the
# highest possible peer-school score is 8 terms — past this point the school dimension no
# longer trades off against anything, and the remaining MRR wiggle is the level boost
# breaking ties. Taking the maximum of that wiggle across 50 points would be reading noise
# as signal. 5.0 is the smallest setting that reaches the plateau.
#
# A partition rather than a soft boost is the right call *for this path specifically*. The
# dense path keeps its boost soft because a peer school's page is sometimes the only answer
# and cosine ranking is good enough to find it. Ranking by term count is not good enough for
# that judgement, and the failure it produces is the one fault injection caught: an SPS
# student being handed the School of Social Work's waitlist procedure, confidently.
KEYWORD_SCHOOL_BOOST = 5.0
KEYWORD_LEVEL_BOOST = 1.0


# Maps a program's school to the corpus slug its policies were ingested under.
#
# Lives here rather than beside the agent tools because both the assistant and the decoder
# need it, and the decoder is downstream of the tools — importing it the other way would
# close a cycle. It is also the single place that grows when the corpus covers more of the
# university, so a school missing from this table is one grep away.
#
# An unmapped school simply gets no scope boost, which degrades to unscoped retrieval
# rather than to a wrong answer.
SCHOOL_TO_CORPUS_SLUG = {
    "School of Professional Studies": "professional-studies",
}


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
    school_boost: float | None = None,
    level_boost: float | None = None,
    mode: str | None = None,
    keyword_school_boost: float | None = None,
    keyword_level_boost: float | None = None,
) -> RetrievalResult:
    active = strategy or settings.chunk_strategy
    retrieval_mode = mode or settings.retrieval_mode
    scope = scope or RetrievalScope()

    hybrid = retrieval_mode == "hybrid"
    if school_boost is None:
        school_boost = HYBRID_SCHOOL_BOOST if hybrid else DEFAULT_SCHOOL_BOOST
    if level_boost is None:
        level_boost = HYBRID_LEVEL_BOOST if hybrid else DEFAULT_LEVEL_BOOST

    try:
        vector = embed_one(query)
        params = {
            "query_vec": str(vector),
            "role": role,
            "k": k,
            "candidate_k": k * CANDIDATE_MULTIPLIER,
            "strategy": active,
            "school": scope.school,
            "level": scope.level,
            "school_boost": school_boost,
            "level_boost": level_boost,
        }
        if hybrid:
            params |= {"query": query, "rrf_k": RRF_K}
        rows = session.execute(HYBRID_SQL if hybrid else VECTOR_SQL, params).all()
        degraded = False
    except EmbeddingsUnavailableError:
        terms = [t for t in query.lower().split() if len(t) > 2][:8]
        rows = session.execute(
            KEYWORD_SQL,
            {
                "terms": terms, "role": role, "k": k,
                "strategy": active, "school": scope.school,
                "level": scope.level,
                "school_boost": (
                    KEYWORD_SCHOOL_BOOST if keyword_school_boost is None else keyword_school_boost
                ),
                "level_boost": (
                    KEYWORD_LEVEL_BOOST if keyword_level_boost is None else keyword_level_boost
                ),
            },
        ).all()
        degraded = True

    # A corpus that is reachable but matches nothing. Deliberately NOT a degraded mode:
    # there is no outage to disclose, and the question this fault asks is whether the
    # assistant says "I found nothing" or fills the silence.
    if faults.is_armed("retrieval.empty"):
        rows = []

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
