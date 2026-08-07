"""Scoring *how* the agent got to its answer, not whether the answer was right.

The behavior eval already asks the outcome questions: was the decision correct, were the
required tools consulted, did anything leak. All of them are satisfiable by an agent that
blunders to the right place — one that looks up four courses to cite one, or spends five
turns doing what fits in two. That agent costs more, takes longer, and gets worse as the
tool surface grows, and none of it shows up in a passing eval.

Which is the actual problem: this codebase went from five tools to nine over M4-M6 with no
instrument on tool choice at all. Adding multi-turn next would change trajectories, so the
instrument has to exist before the thing that moves it, or "it feels better" becomes the
measurement.

Everything here is a pure function over a recorded trace, so it runs over the audit log
retroactively for free — `ai_interactions` was always meant to double as eval data.

## What is measured, and what is deliberately not gated

`redundant_calls` and `forbidden_calls` are defects: an identical repeated call bought
nothing, and a tool the case forbids should not have been reachable.

`unused_results` is **reported, not gated**. A lookup whose result goes uncited is often
correct — checking three courses and citing the one that mattered is diligence, and the
alternative behaviour, citing everything it touched, is exactly the padding this project
refuses elsewhere. It becomes interesting as a trend, not as a per-run failure.

`parallelism` scores adherence to an instruction the system prompt actually gives ("request
independent lookups in the SAME turn"). Latency is the reason that instruction exists, so
measuring it closes the loop on a prompt rule rather than inventing a new standard.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field


def _arg_key(args: object) -> str:
    """A stable key for a call's arguments, so repeats can be spotted.

    Sorted keys because the model may emit the same arguments in a different order, and two
    calls that differ only in JSON key order are the same call.
    """
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        return repr(args)


@dataclass
class TrajectoryScore:
    tool_calls: int = 0
    distinct_tools: int = 0
    iterations: int = 0
    # Calls per model turn. The system prompt asks for independent lookups to be batched, so
    # a value near 1.0 across a run with many lookups means the instruction is not landing.
    parallelism: float = 0.0
    # Identical (tool, args) issued more than once. Every repeat is spend with no new
    # information.
    redundant_calls: int = 0
    # Calls whose source ids never appear in the citations. Reported, not gated — see the
    # module docstring.
    unused_results: int = 0
    # Calls that returned an error, degraded or otherwise.
    failed_calls: int = 0
    # Tools the case said must not be called.
    forbidden_calls: tuple[str, ...] = ()
    # calls / labelled minimum. None when the case has no labelled minimum, which is most of
    # them — a made-up minimum would make the ratio meaningless and the aggregate worse.
    path_ratio: float | None = None
    # Names, for the report's failure list.
    redundant_detail: tuple[str, ...] = field(default_factory=tuple)
    unused_detail: tuple[str, ...] = field(default_factory=tuple)


def score_trace(
    tool_trace: list[dict],
    citations: list[dict] | None = None,
    *,
    iterations: int | None = None,
    must_not_call: tuple[str, ...] = (),
    min_tool_calls: int | None = None,
) -> TrajectoryScore:
    """Score one run.

    `iterations` is the stored loop length when available. Falling back to the trace
    undercounts by one, because the turn that produces the answer calls no tool and so
    leaves no entry — worth knowing when reading numbers from rows written before the
    column existed.
    """
    trace = tool_trace or []
    cited_ids = {
        c.get("source_id") for c in (citations or []) if isinstance(c, dict)
    }

    seen: dict[tuple[str, str], int] = {}
    redundant = 0
    redundant_detail: list[str] = []
    unused = 0
    unused_detail: list[str] = []
    failed = 0
    forbidden: list[str] = []

    for call in trace:
        # `name` is the pre-M1 trace key. The audit log is the eval dataset, so it spans
        # every schema this project has had — the two oldest rows still carry tool names
        # that no longer exist and a `student_id` argument from before that parameter was
        # removed. Reading only the current key silently scored those as an unnamed tool.
        name = str(call.get("tool") or call.get("name") or "?")
        key = (name, _arg_key(call.get("args")))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            redundant += 1
            redundant_detail.append(f"{name} repeated with identical arguments")

        if call.get("failed"):
            failed += 1

        if name in must_not_call:
            forbidden.append(name)

        # Only judge a call as unused when we know what it produced. Traces written before
        # per-call attribution existed have no `source_ids`, and counting those as unused
        # would manufacture a regression out of a schema change.
        produced = call.get("source_ids")
        if produced is not None:
            if produced and not (set(produced) & cited_ids):
                unused += 1
                unused_detail.append(f"{name} returned sources that were never cited")

    turns = iterations
    if turns is None:
        recorded = [c.get("iteration") for c in trace if isinstance(c.get("iteration"), int)]
        turns = max(recorded) if recorded else 0

    calls = len(trace)
    return TrajectoryScore(
        tool_calls=calls,
        distinct_tools=len({name for name, _ in seen}),
        iterations=turns or 0,
        parallelism=round(calls / turns, 2) if turns else 0.0,
        redundant_calls=redundant,
        unused_results=unused,
        failed_calls=failed,
        forbidden_calls=tuple(forbidden),
        path_ratio=(
            round(calls / min_tool_calls, 2)
            if min_tool_calls and min_tool_calls > 0
            else None
        ),
        redundant_detail=tuple(redundant_detail),
        unused_detail=tuple(unused_detail),
    )


def aggregate(scores: list[TrajectoryScore]) -> dict:
    """Roll individual scores into the numbers a gate can read.

    Rates are over runs rather than over calls. A run either wandered or it did not; making
    it a share of total calls would let one clean twelve-call run absorb a two-call run that
    repeated itself, which is the run worth looking at.
    """
    if not scores:
        return {
            "runs": 0,
            "tool_calls_mean": None,
            "iterations_mean": None,
            "parallelism_mean": None,
            "redundant_call_rate": None,
            "unused_result_rate": None,
            "failed_call_rate": None,
            "forbidden_calls": 0,
            "path_ratio_mean": None,
            "path_ratio_n": 0,
        }

    n = len(scores)
    ratios = [s.path_ratio for s in scores if s.path_ratio is not None]
    return {
        "runs": n,
        "tool_calls_mean": round(statistics.mean(s.tool_calls for s in scores), 2),
        "iterations_mean": round(statistics.mean(s.iterations for s in scores), 2),
        "parallelism_mean": round(statistics.mean(s.parallelism for s in scores), 2),
        "redundant_call_rate": round(
            sum(1 for s in scores if s.redundant_calls) / n, 4
        ),
        "unused_result_rate": round(sum(1 for s in scores if s.unused_results) / n, 4),
        "failed_call_rate": round(sum(1 for s in scores if s.failed_calls) / n, 4),
        "forbidden_calls": sum(len(s.forbidden_calls) for s in scores),
        "path_ratio_mean": round(statistics.mean(ratios), 2) if ratios else None,
        # Stated so the mean is read as covering a subset, not all runs.
        "path_ratio_n": len(ratios),
    }


__all__ = ["TrajectoryScore", "aggregate", "score_trace"]
