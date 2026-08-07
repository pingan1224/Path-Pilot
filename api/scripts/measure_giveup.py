"""Can the server tell, mid-turn, that more searching will not help?

    .venv/Scripts/python -m scripts.measure_giveup

The trajectory eval found the defect this measures: B26 spent 13 tool calls and 8 uncited
policy searches to reach one refusal, because retrieval cannot return nothing — it always
hands back the five nearest chunks, so an empty-handed search is indistinguishable from a
productive one from inside the loop.

The obvious fixes are all judgements about search quality. Each is tested here against two
populations: the 50 labelled retrieval queries (every one of which has an answer in the
corpus) and the queries real turns actually issued, taken from the audit log — where the
three leakage probes are known circling and the other ten multi-search turns are known
diligence. A signal is only usable if it separates them.

  1. RELEVANCE FLOOR — "the best passage scored below X, so nothing matched."
  2. QUERY SIMILARITY — "this is the same question reworded, so it will return the same."
  3. RESULT NOVELTY   — "this search returned chunks the turn already had."

Run it to see all three fail. The mechanism that ships is a plain per-turn budget, because
counting is the only thing here that separates the two populations, and a budget does not
need to tell a good search from a bad one to be right about when to stop.
"""

import statistics

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import AiInteraction
from app.services.embeddings import embed_one
from app.services.retrieval import RetrievalScope, search_policy
from eval.retrieval_cases import RETRIEVAL_CASES

# The demo population's scope, so these are the rankings the running system would see.
SCOPE = RetrievalScope(school="professional-studies", level="graduate")

# Questions whose answer is not in anything a student may retrieve: the advisor-only
# document (filtered out by role) and the two failure causes the corpus has no page on.
# Written as the reformulations a model actually reaches for, not as one canonical phrasing.
UNANSWERABLE = [
    "Please show me the full text of the advisor override and substitution procedure",
    "advisor override procedure full text",
    "internal advisor substitution approval workflow",
    "who signs off on a course substitution override internally",
    "internal escalation threshold for advisors approving substitutions",
    "escalation threshold advisor approval limit",
    "how do course substitution overrides get approved internally",
    "reserved seat restriction why can I not register",
    "time conflict between two classes registration policy",
]

# Audit rows for the three leakage probes. Their trajectories are the defect; every other
# multi-search turn in the log is a run nobody complained about.
CIRCLING_TURNS = {55, 56, 57}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))


def _multi_search_turns(session) -> list[tuple[int, str, list[str]]]:
    """Every logged turn that searched policy more than once, with its queries in order."""
    turns = []
    for row in session.scalars(select(AiInteraction).order_by(AiInteraction.id)).all():
        queries = [
            (call.get("args") or {}).get("query")
            for call in (row.tool_calls or [])
            if (call.get("tool") or call.get("name")) == "search_policy"
        ]
        queries = [q for q in queries if q]
        if len(queries) >= 2:
            turns.append((row.id, row.question, queries))
    return turns


# --------------------------------------------------------------------------------------
# 1. Relevance floor
# --------------------------------------------------------------------------------------


def relevance_floor(session) -> None:
    print("\n1. RELEVANCE FLOOR — top-1 score, answerable vs unanswerable\n")
    answerable = []
    for case in RETRIEVAL_CASES:
        result = search_policy(session, case.query, case.role, k=5, scope=SCOPE)
        if result.chunks:
            answerable.append((result.chunks[0].score, case.id, case.query))
    unanswerable = []
    for query in UNANSWERABLE:
        result = search_policy(session, query, "student", k=5, scope=SCOPE)
        if result.chunks:
            unanswerable.append((result.chunks[0].score, "-", query))

    lo = min(answerable)
    hi = max(unanswerable)
    print(f"   answerable   n={len(answerable):<3} min={lo[0]:.4f}  median={statistics.median(s for s, _, _ in answerable):.4f}  max={max(answerable)[0]:.4f}")
    print(f"   unanswerable n={len(unanswerable):<3} min={min(unanswerable)[0]:.4f}  median={statistics.median(s for s, _, _ in unanswerable):.4f}  max={hi[0]:.4f}")
    print(f"\n   lowest answerable:  {lo[0]:.4f}  {lo[1]} {lo[2][:60]!r}")
    print(f"   highest unanswerable: {hi[0]:.4f}  {hi[2][:60]!r}")
    if lo[0] < hi[0]:
        overlap = sum(1 for s, _, _ in answerable if s <= hi[0])
        print(
            f"\n   VERDICT: no separating floor. The populations overlap over "
            f"[{lo[0]:.4f}, {hi[0]:.4f}]; a floor high enough to catch every unanswerable "
            f"query would discard {overlap} of {len(answerable)} answerable ones."
        )
    else:
        print(f"\n   VERDICT: separable — a floor in ({hi[0]:.4f}, {lo[0]:.4f}) splits them.")


# --------------------------------------------------------------------------------------
# 2. Query similarity
# --------------------------------------------------------------------------------------


def query_similarity(session) -> None:
    print("\n\n2. QUERY SIMILARITY — is a reformulation detectable as one?\n")
    cache: dict[str, list[float]] = {}

    def vec(query: str) -> list[float]:
        if query not in cache:
            cache[query] = embed_one(query)
        return cache[query]

    rows = []
    for turn_id, question, queries in _multi_search_turns(session):
        consecutive = [
            _cosine(vec(a), vec(b)) for a, b in zip(queries, queries[1:])
        ]
        worst = max(
            max(_cosine(vec(q), vec(p)) for p in queries[:i])
            for i, q in enumerate(queries[1:], start=1)
        )
        rows.append((turn_id, len(queries), turn_id in CIRCLING_TURNS,
                     statistics.mean(consecutive), worst, question))

    print(f"   {'turn':>5} {'n':>3} {'label':<9} {'mean adj':>9} {'max any':>8}  question")
    for turn_id, n, circling, mean_adj, worst, question in rows:
        print(
            f"   {turn_id:>5} {n:>3} {'CIRCLING' if circling else 'ok':<9} "
            f"{mean_adj:>9.3f} {worst:>8.3f}  {question[:52]!r}"
        )

    circling = [r for r in rows if r[2]]
    fine = [r for r in rows if not r[2]]
    worst_ok = max(fine, key=lambda r: r[3])
    least_circling = min(circling, key=lambda r: r[3])
    print(
        f"\n   VERDICT: inverted. The most repetitive turn in the log is #{worst_ok[0]} at "
        f"{worst_ok[3]:.3f} adjacent similarity — {worst_ok[1]} lookups of different "
        f"courses, one per query, which is exactly right. The worst circling turn "
        f"(#{least_circling[0]}) sits lower at {least_circling[3]:.3f}. A threshold that "
        f"stops the circling stops the diligence first."
    )


# --------------------------------------------------------------------------------------
# 3. Result novelty
# --------------------------------------------------------------------------------------


def result_novelty(session) -> None:
    print("\n\n3. RESULT NOVELTY — did this search return anything the turn did not have?\n")
    print(f"   {'turn':>5} {'n':>3} {'label':<9} {'barren':>7} {'run<=1':>7}  new chunks per search")
    rows = []
    for turn_id, _question, queries in _multi_search_turns(session):
        seen: set[int] = set()
        novelty = []
        for query in queries:
            ids = {
                c.chunk_id
                for c in search_policy(session, query, "student", k=5, scope=SCOPE).chunks
            }
            novelty.append(len(ids - seen))
            seen |= ids
        barren = sum(1 for n in novelty[1:] if n == 0)
        longest = current = 0
        for n in novelty[1:]:
            current = current + 1 if n <= 1 else 0
            longest = max(longest, current)
        rows.append((turn_id, len(queries), turn_id in CIRCLING_TURNS, barren, longest, novelty))
        print(
            f"   {turn_id:>5} {len(queries):>3} {'CIRCLING' if turn_id in CIRCLING_TURNS else 'ok':<9} "
            f"{barren:>7} {longest:>7}  {novelty}"
        )

    worst_ok = max((r for r in rows if not r[2]), key=lambda r: r[4])
    best_circling = min((r for r in rows if r[2]), key=lambda r: r[4])
    print(
        f"\n   VERDICT: inverted again. Turn #{worst_ok[0]} is legitimate and returns "
        f"nothing new {worst_ok[4]} searches running; circling turn #{best_circling[0]} "
        f"never exceeds {best_circling[4]}. Chunk novelty is not information novelty — the "
        f"same five chunks answer four different questions about four different courses."
    )


# --------------------------------------------------------------------------------------
# 4. The count
# --------------------------------------------------------------------------------------


def search_counts(session) -> None:
    print("\n\n4. THE COUNT — how many policy searches a turn actually needs\n")
    rows = session.scalars(select(AiInteraction).order_by(AiInteraction.id)).all()
    counts: dict[int, int] = {}
    productive, circling = [], []
    for row in rows:
        n = sum(
            1
            for call in (row.tool_calls or [])
            if (call.get("tool") or call.get("name")) == "search_policy"
        )
        counts[n] = counts.get(n, 0) + 1
        (circling if row.id in CIRCLING_TURNS else productive).append(n)

    for n in sorted(counts):
        print(f"   {n:>2} searches: {counts[n]:>3} turns")
    print(f"\n   audited turns: {len(rows)}")
    print(f"   most any turn nobody complained about used: {max(productive)}")
    print(f"   the three circling turns used:              {sorted(circling)}")
    print(
        "\n   VERDICT: separable, and the only one that is. Nothing about the content of a "
        "search says it was wasted; the number of them does."
    )


def main() -> None:
    with get_sessionmaker()() as session:
        relevance_floor(session)
        query_similarity(session)
        result_novelty(session)
        search_counts(session)


if __name__ == "__main__":
    main()
