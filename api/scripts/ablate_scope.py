"""Tune and measure the scope boosts.

    .venv/Scripts/python -m scripts.ablate_scope              # school (level rides along)
    .venv/Scripts/python -m scripts.ablate_scope --program    # the programme facet

Sweeps a boost from 0 (no scoping, the recorded baseline) upward and reports recall and
MRR overall and per family. The value that ships is whichever this sweep supports, which
is the only defensible way to pick a magic number.

Watch two things, not one: the family the boost targets should rise, and nothing else
should fall. A boost large enough to promote an irrelevant home chunk over a relevant peer
one trades one failure mode for another, and only the per-family view shows that.

**Every constant this sweeps is a fit to one corpus, and the corpus moved.** The shipped
0.12/0.04 was swept over 35 pages and 1,252 chunks; ingesting a page per SPS degree took
that to 57 and 1,461, and 22 of the new pages share the home school and level. A tuned
number carried across that change is a number with no evidence behind it, which is why this
gets re-run rather than trusted.

`--program` sweeps the facet added with those pages. School and level cannot separate 23
programmes that share both, and each programme page carries a "Policies" section competing
with the school-wide one — measured on R11, where Publishing (MS)'s programme policies
outranked the school's own attendance policy for a Management & Analytics student.
"""

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from app.db.session import get_sessionmaker
from app.services.retrieval import RetrievalScope, search_policy
from eval.retrieval_cases import RETRIEVAL_CASES

RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval" / "results"

# The demo population: every labelled query is asked by a graduate student at the School of
# Professional Studies, studying the one programme whose requirements are encoded. That is
# the scope the running system supplies, not an advantage the eval invents.
SCOPE = RetrievalScope(
    school="professional-studies",
    level="graduate",
    program_slug="management-analytics-ms",
)

# Extended past 0.20 on purpose. The first re-sweep after the corpus grew put the best
# value at 0.20 — the top of the old range — and an optimum sitting on the edge of the
# window is a statement about the window, not about the data.
SWEEP = [0.0, 0.04, 0.08, 0.12, 0.14, 0.15, 0.16, 0.20, 0.30]


def score(
    session,
    school_boost: float,
    level_boost: float,
    program_boost: float = 0.0,
    *,
    hold_school: bool = False,
) -> dict:
    """One row of the sweep.

    `hold_school` keeps the shipped school/level pair fixed while the programme boost
    varies — the programme facet has to be judged on top of the scoping that already
    exists, not against an unscoped baseline it would trivially beat.
    """
    rows = []
    scoped = hold_school or school_boost or level_boost or program_boost
    for case in RETRIEVAL_CASES:
        expected = set(case.expected)
        result = search_policy(
            session, case.query, case.role, k=5,
            scope=SCOPE if scoped else RetrievalScope(),
            school_boost=school_boost, level_boost=level_boost,
            program_boost=program_boost,
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
        "program_boost": program_boost,
        "recall": round(statistics.mean(r["recall"] for r in rows), 4),
        "mrr": round(statistics.mean(r["rr"] for r in rows), 4),
        "families": {
            name: round(statistics.mean(r["recall"] for r in group), 4)
            for name, group in sorted(by_family.items())
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--program",
        action="store_true",
        help=(
            "sweep the programme boost with the shipped school/level pair held fixed, "
            "rather than sweeping school"
        ),
    )
    args = parser.parse_args()

    from app.services.retrieval import DEFAULT_LEVEL_BOOST, DEFAULT_SCHOOL_BOOST

    results = []
    with get_sessionmaker()() as session:
        for boost in SWEEP:
            print(f"boost={boost} ...", flush=True)
            if args.program:
                # School and level stay at what ships. A programme boost measured against
                # an unscoped baseline would take credit for the school boost's work.
                results.append(
                    score(
                        session,
                        DEFAULT_SCHOOL_BOOST,
                        DEFAULT_LEVEL_BOOST,
                        boost,
                        hold_school=True,
                    )
                )
            else:
                results.append(score(session, boost, boost / 3 if boost else 0.0))

    key = "program_boost" if args.program else "school_boost"
    families = sorted(results[0]["families"])
    label = "prog" if args.program else "boost"
    print(f"\n{label:>7}{'recall@5':>11}{'MRR':>8}   " + "".join(f"{f[:10]:>11}" for f in families))
    print("-" * (26 + 11 * len(families) + 3))
    for r in results:
        row = "".join(f"{r['families'][f]:>11}" for f in families)
        print(f"{r[key]:>7}{r['recall']:>11}{r['mrr']:>8}   {row}")

    base, *rest = results
    best = max(rest, key=lambda r: (r["recall"], r["mrr"]))
    baseline_label = (
        f"school {DEFAULT_SCHOOL_BOOST}/{DEFAULT_LEVEL_BOOST}, no programme boost"
        if args.program
        else "no scoping"
    )
    print(
        f"\nbaseline ({baseline_label}): recall {base['recall']}  MRR {base['mrr']}"
        f"\nbest {key} {best[key]}: recall {best['recall']}  MRR {best['mrr']}"
        f"  ({best['recall'] - base['recall']:+.4f} recall, {best['mrr'] - base['mrr']:+.4f} MRR)"
    )
    regressions = [
        f for f in families if best["families"][f] < base["families"][f] - 1e-9
    ]
    print("families that regressed at the best value:", regressions or "none")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"ablation-{'program' if args.program else 'scope'}-{stamp}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
