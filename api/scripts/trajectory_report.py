"""Trajectory metrics over the audit log, retroactively and for free.

    .venv/Scripts/python -m scripts.trajectory_report
    .venv/Scripts/python -m scripts.trajectory_report --since 20 --by-tool

Rule 7 says every AI interaction is logged replayably and the audit log doubles as the eval
dataset. This is that promise being cashed in: the same scoring the eval applies to fresh
runs, applied to runs that already happened, at no token cost. It gives a baseline before a
single new model call, and it is the only way to see whether the agent's behaviour drifted
over the weeks the tool surface was growing.

One honesty note it prints for itself: rows written before per-call source attribution
existed cannot be scored for unused results, and rows written before the `iterations` column
existed have their loop length inferred from the trace, which undercounts by one because the
answer-producing turn calls no tool. Both are stated rather than smoothed over.
"""

import argparse
from collections import Counter

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import AiInteraction
from eval.trajectory import aggregate, score_trace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=int, default=0, help="only the newest N rows")
    parser.add_argument("--by-tool", action="store_true", help="per-tool call counts")
    args = parser.parse_args()

    with get_sessionmaker()() as session:
        query = select(AiInteraction).order_by(AiInteraction.id.desc())
        if args.since:
            query = query.limit(args.since)
        rows = list(session.scalars(query).all())

    if not rows:
        print("No ai_interactions rows to score. Run the agent or the eval first.")
        return

    rows.reverse()
    scores = []
    attributable = 0
    stored_iterations = 0

    for row in rows:
        trace = row.tool_calls or []
        if any(call.get("source_ids") is not None for call in trace):
            attributable += 1
        if row.iterations is not None:
            stored_iterations += 1
        scores.append(
            score_trace(
                trace,
                row.citations or [],
                iterations=row.iterations,
            )
        )

    stats = aggregate(scores)

    print(f"Trajectory over {stats['runs']} logged interactions\n")
    print(f"  tool calls / run      {stats['tool_calls_mean']}")
    print(f"  iterations / run      {stats['iterations_mean']}")
    print(f"  calls per iteration   {stats['parallelism_mean']}   (the prompt asks for independent lookups to be batched)")
    print(f"  runs with a repeat    {stats['redundant_call_rate']}")
    print(f"  runs with a failure   {stats['failed_call_rate']}")
    print(f"  runs w/ uncited work  {stats['unused_result_rate']}   (reported, not a defect on its own)")

    print("\nCoverage of the measurement itself:")
    print(f"  {attributable}/{len(rows)} rows carry per-call source attribution")
    print(f"  {stored_iterations}/{len(rows)} rows carry a stored iteration count")
    if attributable < len(rows):
        print("  older rows predate per-call attribution and are not scored for uncited work")
    if stored_iterations < len(rows):
        print("  older rows infer loop length from the trace, which undercounts by one turn")

    worst = sorted(
        zip(rows, scores, strict=True),
        key=lambda pair: (
            pair[1].redundant_calls,
            pair[1].unused_results,
            pair[1].tool_calls,
        ),
        reverse=True,
    )[:5]
    print("\nRuns worth reading:")
    for row, score in worst:
        print(
            f"  #{row.id}  calls={score.tool_calls} iters={score.iterations} "
            f"par={score.parallelism} repeats={score.redundant_calls} "
            f"uncited={score.unused_results}"
        )
        print(f"        {(row.question or '')[:88]}")
        for detail in (*score.redundant_detail, *score.unused_detail):
            print(f"        - {detail}")

    if args.by_tool:
        counter = Counter(
            call.get("tool") or call.get("name") or "?"
            for row in rows
            for call in (row.tool_calls or [])
        )
        print("\nCalls by tool:")
        width = max((len(str(name)) for name in counter), default=4)
        for name, count in counter.most_common():
            print(f"  {str(name):<{width}}  {count}")


if __name__ == "__main__":
    main()
