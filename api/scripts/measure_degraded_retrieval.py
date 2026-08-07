"""How much worse is retrieval when the embedding provider is down?

    FAULT_INJECTION=true .venv/Scripts/python -m scripts.measure_degraded_retrieval

Until fault injection existed, "reduced service" was a phrase the UI printed without anyone
knowing what it meant. This scores the keyword fallback against the same 50 labelled
queries as the healthy path, so the degradation has a size: not "less relevant", but
recall@5 x against 0.91.

It also sweeps the fallback's home-school boost, for the same reason the dense path's boost
was swept — a magic number that nobody measured is a magic number. The scales are unrelated:
dense scores are cosine similarities in [0,1] and these are counts of matched terms, so the
0.12 that ships for vectors is invisible here.

Reading the sweep, watch `home_scope` and `restricted` together. `home_scope` is the family
that punishes serving another school's answer, and `restricted` is the family of documents
that carry no school at all — a boost written as "home school only" lifts the first and
buries the second. That exact bug was found and fixed in the dense path months ago; the
fallback still had it today, because a path that never runs never gets patched.
"""

import statistics

from app import faults
from app.db.session import get_sessionmaker
from app.services.retrieval import RetrievalScope, search_policy
from eval.retrieval_cases import RETRIEVAL_CASES

SCOPE = RetrievalScope(school="professional-studies", level="graduate")

# (school_boost, level_boost). 0/0 is the no-scoping baseline; 1/0 is what was hardcoded
# before this was measured, in its original home-school-only form.
SWEEP = [
    (0.0, 0.0), (1.0, 0.0), (1.0, 0.25), (2.0, 0.5), (3.0, 0.5),
    (5.0, 1.0), (8.0, 1.5), (12.0, 2.0), (20.0, 3.0),
]


def score(session, school_boost: float, level_boost: float, degraded: bool) -> dict:
    rows = []
    for case in RETRIEVAL_CASES:
        result = search_policy(
            session, case.query, case.role, k=5, scope=SCOPE,
            keyword_school_boost=school_boost, keyword_level_boost=level_boost,
        )
        expected = set(case.expected)
        covered = [set(c.section_keys) & expected for c in result.chunks]
        ranks = [i + 1 for i, hit in enumerate(covered) if hit]
        found = set().union(*covered) if covered else set()
        rows.append(
            {
                "family": case.family,
                "recall": len(found) / len(expected),
                "rr": 1 / ranks[0] if ranks else 0.0,
                "empty": not result.chunks,
                "degraded": result.degraded,
            }
        )
    assert all(r["degraded"] == degraded for r in rows), "wrong retrieval path measured"

    by_family: dict[str, list[dict]] = {}
    for row in rows:
        by_family.setdefault(row["family"], []).append(row)
    return {
        "recall": statistics.mean(r["recall"] for r in rows),
        "mrr": statistics.mean(r["rr"] for r in rows),
        "empty": sum(1 for r in rows if r["empty"]),
        "families": {
            name: statistics.mean(r["recall"] for r in group)
            for name, group in sorted(by_family.items())
        },
    }


def main() -> None:
    with get_sessionmaker()() as session:
        healthy = score(session, 0, 0, degraded=False)
        print("healthy (dense + scope boost, the shipped path)")
        print(f"  recall@5={healthy['recall']:.4f}  MRR={healthy['mrr']:.4f}\n")

        print("degraded (keyword fallback), sweeping its own boost")
        print(f"  {'school':>7} {'level':>6} {'recall@5':>9} {'MRR':>8} {'empty':>6}  per-family recall")
        best = None
        for school_boost, level_boost in SWEEP:
            with faults.injected("embeddings.unavailable"):
                result = score(session, school_boost, level_boost, degraded=True)
            families = "  ".join(f"{k}={v:.2f}" for k, v in result["families"].items())
            print(
                f"  {school_boost:>7.1f} {level_boost:>6.2f} {result['recall']:>9.4f} "
                f"{result['mrr']:>8.4f} {result['empty']:>6}  {families}"
            )
            if best is None or result["mrr"] > best[1]["mrr"]:
                best = ((school_boost, level_boost), result)

        (school_boost, level_boost), result = best
        print(f"\n  peak MRR at school={school_boost} level={level_boost}")
        print(
            f"  degradation, stated as a size: recall@5 {healthy['recall']:.4f} -> "
            f"{result['recall']:.4f}, MRR {healthy['mrr']:.4f} -> {result['mrr']:.4f}"
        )


if __name__ == "__main__":
    main()
