"""Hybrid retrieval ablation: dense vs dense+lexical, and the RRF-space scope boost.

    .venv/Scripts/python -m scripts.ablate_hybrid

Two questions, in order. Does fusing lexical retrieval help at all, and where does the
scope boost sit once RRF has changed the score scale out from under the value tuned for
cosine space? Reporting per family matters more than usual here: hybrid is expected to win
on `course` and `lexical` and could plausibly lose on `paraphrase`, and an aggregate would
average that story away.
"""

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from app.db.session import get_sessionmaker
from app.services.retrieval import RetrievalScope, search_policy
from eval.retrieval_cases import RETRIEVAL_CASES

RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval" / "results"
SCOPE = RetrievalScope(school="professional-studies", level="graduate")

# (label, mode, school_boost, level_boost)
ARMS = [
    ("vector", "vector", 0.12, 0.04),
    ("hybrid b=0", "hybrid", 0.0, 0.0),
    ("hybrid b=.005", "hybrid", 0.005, 0.0015),
    ("hybrid b=.010", "hybrid", 0.010, 0.003),
    ("hybrid b=.020", "hybrid", 0.020, 0.006),
    ("hybrid b=.040", "hybrid", 0.040, 0.012),
]


def score(session, mode: str, school_boost: float, level_boost: float) -> dict:
    rows = []
    for case in RETRIEVAL_CASES:
        expected = set(case.expected)
        result = search_policy(
            session, case.query, case.role, k=5, scope=SCOPE, mode=mode,
            school_boost=school_boost, level_boost=level_boost,
        )
        covered = [set(c.section_keys) & expected for c in result.chunks]
        ranks = [i + 1 for i, hit in enumerate(covered) if hit]
        found = set().union(*covered) if covered else set()
        rows.append({"family": case.family, "id": case.id,
                     "recall": len(found) / len(expected),
                     "rr": (1 / ranks[0]) if ranks else 0.0})

    by_family: dict[str, list[dict]] = {}
    for r in rows:
        by_family.setdefault(r["family"], []).append(r)

    return {
        "recall": round(statistics.mean(r["recall"] for r in rows), 4),
        "mrr": round(statistics.mean(r["rr"] for r in rows), 4),
        "misses": [r["id"] for r in rows if r["rr"] == 0.0],
        "families": {
            name: round(statistics.mean(r["recall"] for r in group), 4)
            for name, group in sorted(by_family.items())
        },
    }


def main() -> None:
    results: dict[str, dict] = {}
    with get_sessionmaker()() as session:
        for label, mode, sb, lb in ARMS:
            print(f"{label} ...", flush=True)
            results[label] = score(session, mode, sb, lb)

    families = sorted(next(iter(results.values()))["families"])
    header = f"{'arm':<15}{'recall@5':>10}{'MRR':>8}{'miss':>6}   " + "".join(
        f"{f[:10]:>11}" for f in families
    )
    print(f"\n{header}\n" + "-" * len(header))
    for label, r in results.items():
        row = "".join(f"{r['families'][f]:>11}" for f in families)
        print(f"{label:<15}{r['recall']:>10}{r['mrr']:>8}{len(r['misses']):>6}   {row}")

    base = results["vector"]
    best_label = max(
        (k for k in results if k != "vector"), key=lambda k: (results[k]["mrr"], results[k]["recall"])
    )
    best = results[best_label]
    print(
        f"\nvector baseline : recall {base['recall']}  MRR {base['mrr']}  misses {base['misses']}"
        f"\nbest hybrid arm : {best_label} — recall {best['recall']}  MRR {best['mrr']}"
        f"  ({best['recall'] - base['recall']:+.4f} / {best['mrr'] - base['mrr']:+.4f})"
        f"\n  misses {best['misses']}"
    )
    regressed = [f for f in families if best["families"][f] < base["families"][f] - 1e-9]
    print("  families regressed vs vector:", regressed or "none")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"ablation-hybrid-{stamp}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(f"\nwritten: eval/results/ablation-hybrid-{stamp}.json")


if __name__ == "__main__":
    main()
