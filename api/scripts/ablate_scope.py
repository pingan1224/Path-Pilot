"""Tune and measure the home-school scope boost.

    .venv/Scripts/python -m scripts.ablate_scope

Sweeps the boost from 0 (no scoping, the recorded baseline) upward and reports recall and
MRR overall and per family. The value that ships is whichever this sweep supports, which
is the only defensible way to pick a magic number.

Watch two things, not one: `home_scope` should rise, and nothing else should fall. A boost
large enough to promote an irrelevant home-school chunk over a relevant peer-school one
would trade one failure mode for another, and only the per-family view shows that.
"""

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from app.db.session import get_sessionmaker
from app.services.retrieval import RetrievalScope, search_policy
from eval.retrieval_cases import RETRIEVAL_CASES

RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval" / "results"

# Every labelled query is asked from the perspective of a graduate student at the School
# of Professional Studies — the demo population — so this is the scope the running system
# would supply, not an advantage the eval invents.
SCOPE = RetrievalScope(school="professional-studies", level="graduate")

SWEEP = [0.0, 0.02, 0.04, 0.06, 0.08, 0.12, 0.20]


def score(session, school_boost: float, level_boost: float) -> dict:
    rows = []
    for case in RETRIEVAL_CASES:
        expected = set(case.expected)
        result = search_policy(
            session, case.query, case.role, k=5,
            scope=SCOPE if school_boost or level_boost else RetrievalScope(),
            school_boost=school_boost, level_boost=level_boost,
        )
        covered = [set(c.section_keys) & expected for c in result.chunks]
        ranks = [i + 1 for i, hit in enumerate(covered) if hit]
        found = set().union(*covered) if covered else set()
        rows.append(
            {
                "family": case.family,
                "recall": len(found) / len(expected),
                "rr": (1 / ranks[0]) if ranks else 0.0,
            }
        )

    by_family: dict[str, list[dict]] = {}
    for r in rows:
        by_family.setdefault(r["family"], []).append(r)

    return {
        "school_boost": school_boost,
        "recall": round(statistics.mean(r["recall"] for r in rows), 4),
        "mrr": round(statistics.mean(r["rr"] for r in rows), 4),
        "families": {
            name: round(statistics.mean(r["recall"] for r in group), 4)
            for name, group in sorted(by_family.items())
        },
    }


def main() -> None:
    results = []
    with get_sessionmaker()() as session:
        for boost in SWEEP:
            print(f"boost={boost} ...", flush=True)
            results.append(score(session, boost, boost / 3 if boost else 0.0))

    families = sorted(results[0]["families"])
    print(f"\n{'boost':>7}{'recall@5':>11}{'MRR':>8}   " + "".join(f"{f[:10]:>11}" for f in families))
    print("-" * (26 + 11 * len(families) + 3))
    for r in results:
        row = "".join(f"{r['families'][f]:>11}" for f in families)
        print(f"{r['school_boost']:>7}{r['recall']:>11}{r['mrr']:>8}   {row}")

    base, *rest = results
    best = max(rest, key=lambda r: (r["recall"], r["mrr"]))
    print(
        f"\nbaseline (no scoping): recall {base['recall']}  MRR {base['mrr']}"
        f"\nbest boost {best['school_boost']}: recall {best['recall']}  MRR {best['mrr']}"
        f"  ({best['recall'] - base['recall']:+.4f} recall, {best['mrr'] - base['mrr']:+.4f} MRR)"
    )
    regressions = [
        f for f in families if best["families"][f] < base["families"][f] - 1e-9
    ]
    print("families that regressed at the best boost:", regressions or "none")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"ablation-scope-{stamp}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
