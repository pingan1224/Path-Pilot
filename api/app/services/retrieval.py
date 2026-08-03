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

from app.services.embeddings import EmbeddingsUnavailableError, embed_one

VECTOR_SQL = text(
    """
    SELECT dc.id, dc.text, dc.heading_path,
           d.title, d.url, d.office, d.fetched_at,
           1 - (dc.embedding <=> CAST(:query_vec AS vector)) AS score
    FROM document_chunks dc
    JOIN documents d ON d.id = dc.document_id
    WHERE d.is_active
      AND dc.embedding IS NOT NULL
      AND dc.visible_to_roles @> ARRAY[:role]::varchar(16)[]
    ORDER BY dc.embedding <=> CAST(:query_vec AS vector)
    LIMIT :k
    """
)

# Fallback: crude term matching, same role boundary. Scores are counts, not similarities;
# they are surfaced as-is so a degraded turn never masquerades as a normal one.
KEYWORD_SQL = text(
    """
    SELECT dc.id, dc.text, dc.heading_path,
           d.title, d.url, d.office, d.fetched_at,
           (
             SELECT count(*) FROM unnest(:terms) AS term
             WHERE dc.text ILIKE '%' || term || '%'
                OR dc.heading_path ILIKE '%' || term || '%'
           )::float AS score
    FROM document_chunks dc
    JOIN documents d ON d.id = dc.document_id
    WHERE d.is_active
      AND dc.visible_to_roles @> ARRAY[:role]::varchar(16)[]
    ORDER BY score DESC
    LIMIT :k
    """
)


@dataclass
class RetrievedChunk:
    chunk_id: int
    text: str
    heading_path: str | None
    document_title: str
    url: str
    office: str
    fetched_at: str
    score: float
    rank: int


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    degraded: bool  # True when keyword fallback served this query


def search_policy(
    session: Session, query: str, role: str, k: int = 5
) -> RetrievalResult:
    try:
        vector = embed_one(query)
        rows = session.execute(
            VECTOR_SQL, {"query_vec": str(vector), "role": role, "k": k}
        ).all()
        degraded = False
    except EmbeddingsUnavailableError:
        terms = [t for t in query.lower().split() if len(t) > 2][:8]
        rows = session.execute(
            KEYWORD_SQL, {"terms": terms, "role": role, "k": k}
        ).all()
        rows = [r for r in rows if r.score > 0]
        degraded = True

    chunks = [
        RetrievedChunk(
            chunk_id=row.id,
            text=row.text,
            heading_path=row.heading_path,
            document_title=row.title,
            url=row.url,
            office=row.office,
            fetched_at=row.fetched_at.isoformat(),
            score=round(float(row.score), 4),
            rank=i + 1,
        )
        for i, row in enumerate(rows)
    ]
    return RetrievalResult(chunks=chunks, degraded=degraded)
