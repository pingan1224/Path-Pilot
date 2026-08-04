"""Chunking ablation: the same 50 labelled queries against every strategy.

    .venv/Scripts/python -m scripts.ablate_chunking

Cheap because every strategy is already embedded and stored side by side — this is
retrieval only, no model calls. Prints the headline table and the per-family breakdown,
because an aggregate can hide a strategy that wins on one kind of question and loses on
another.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.db.session import get_sessionmaker
from eval.retrieval_cases import family_counts
from scripts.run_eval import eval_retrieval

RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval" / "results"
STRATEGIES = ["fixed", "section", "heading"]


def main() -> None:
    results: dict[str, dict] = {}
    with get_sessionmaker()() as session:
        for strategy in STRATEGIES:
            print(f"running {strategy} ...", flush=True)
            results[strategy] = eval_retrieval(session, strategy=strategy)

    print(f"\n{'=' * 74}")
    print(f"Chunking ablation — 50 labelled queries, {family_counts()}")
    print("=" * 74)
    print(f"\n{'strategy':<10}{'recall@5':>10}{'MRR':>8}{'misses':>9}{'sec/chunk':>11}")
    print("-" * 48)
    for strategy in STRATEGIES:
        r = results[strategy]
        misses = sum(1 for c in r["cases"] if c["first_hit_rank"] is None)
        print(
            f"{strategy:<10}{r['recall_at_5']:>10}{r['mrr']:>8}{misses:>9}"
            f"{r['sections_per_chunk']:>11}"
        )

    print(
        "\nsec/chunk is the confound to read this table against: coverage-based labels"
        "\nscore a hit when a retrieved chunk *contains* the target section, so a wider"
        "\nchunk gets more chances per slot. Recall@5 therefore rewards chunk size as much"
        "\nas chunk quality. MRR is less exposed — it asks where the first hit landed, not"
        "\nhow many the window swept up."
    )

    families = sorted(results[STRATEGIES[0]]["families"])
    print(f"\nrecall@5 by family\n{'family':<13}" + "".join(f"{s:>10}" for s in STRATEGIES))
    print("-" * (13 + 10 * len(STRATEGIES)))
    for family in families:
        row = "".join(f"{results[s]['families'][family]['recall_at_5']:>10}" for s in STRATEGIES)
        print(f"{family:<13}{row}")

    print(f"\nMRR by family\n{'family':<13}" + "".join(f"{s:>10}" for s in STRATEGIES))
    print("-" * (13 + 10 * len(STRATEGIES)))
    for family in families:
        row = "".join(f"{results[s]['families'][family]['mrr']:>10}" for s in STRATEGIES)
        print(f"{family:<13}{row}")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"ablation-chunking-{stamp}.json"
    out.write_text(
        json.dumps(
            {s: {kk: vv for kk, vv in r.items() if kk != "cases"} for s, r in results.items()},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
