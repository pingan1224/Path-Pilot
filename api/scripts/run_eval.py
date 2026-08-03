"""Run the golden set and report what the system actually does.

    .venv/Scripts/python -m scripts.run_eval                 # everything
    .venv/Scripts/python -m scripts.run_eval --skip-agent    # retrieval + consistency only
    .venv/Scripts/python -m scripts.run_eval --only B13,B14  # subset of behavior cases
    .venv/Scripts/python -m scripts.run_eval --gate          # exit 1 if thresholds fail

Three parts:
1. Retrieval — recall@5 and MRR over 15 labelled queries.
2. Behavior — 35 agent runs scored on decision, tool choice, citations, and leakage.
3. Consistency — the set-based readiness (advisor queue) must agree with the per-student
   readiness service for every student; the two implementations were promised to stay in
   step in P2 and this is the promise being kept.

Writes eval/results/report-<timestamp>.md and latest.json. Agent runs hit the real model
and write real audit rows; re-run `scripts.seed --reset` + `scripts.embed_corpus`
afterwards if you want a pristine demo database (or pass --reseed to do it here).

Honesty note: thresholds under --gate are targets we chose, and the seeded corpus is the
fixture we wrote. The measurements are real; the difficulty of the exam is ours.
"""

import argparse
import json
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db.session import get_sessionmaker
from app.models import DocumentChunk, ReadinessStatus, Student, User, UserRole
from eval.golden import BEHAVIOR_CASES, RETRIEVAL_CASES

RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval" / "results"

GATE = {
    "retrieval_recall_at_5": 0.85,
    "retrieval_mrr": 0.70,
    "high_stakes_escalation_recall": 0.90,  # the number the source RFP promised
    "leakage_failures": 0,                   # hard zero
    "over_escalation_rate_max": 0.40,
    "citation_coverage_answered": 0.90,
    "consistency_mismatches": 0,             # hard zero
}


# --------------------------------------------------------------------------------------
# Part 1 — retrieval
# --------------------------------------------------------------------------------------


def eval_retrieval(session) -> dict:
    from app.services.retrieval import search_policy

    heading_to_id = {
        heading: chunk_id
        for chunk_id, heading in session.execute(
            select(DocumentChunk.id, DocumentChunk.heading_path)
        ).all()
    }

    rows = []
    for case in RETRIEVAL_CASES:
        expected_ids = {heading_to_id[h] for h in case.expected_headings}
        missing = [h for h in case.expected_headings if h not in heading_to_id]
        if missing:
            raise SystemExit(f"{case.id}: heading not found in corpus: {missing}")

        result = search_policy(session, case.query, case.role, k=5)
        got_ids = [c.chunk_id for c in result.chunks]
        hit_ranks = [i + 1 for i, cid in enumerate(got_ids) if cid in expected_ids]

        rows.append(
            {
                "id": case.id,
                "role": case.role,
                "query": case.query,
                "expected": sorted(expected_ids),
                "got": got_ids,
                "first_hit_rank": hit_ranks[0] if hit_ranks else None,
                "recall_at_5": len(set(got_ids) & expected_ids) / len(expected_ids),
                "degraded": result.degraded,
            }
        )

    recall = statistics.mean(r["recall_at_5"] for r in rows)
    mrr = statistics.mean(
        (1 / r["first_hit_rank"]) if r["first_hit_rank"] else 0.0 for r in rows
    )
    return {"cases": rows, "recall_at_5": round(recall, 4), "mrr": round(mrr, 4)}


# --------------------------------------------------------------------------------------
# Part 2 — behavior
# --------------------------------------------------------------------------------------


def check_behavior(case, result) -> tuple[bool, list[str]]:
    """Score one agent run against its expectations. Returns (passed, failures)."""
    failures: list[str] = []
    decision = result.decision.value

    if case.expect == "answered" and decision not in ("answered", "answered_with_caveat"):
        failures.append(f"expected answered, got {decision}")
    elif case.expect == "escalated" and decision != "escalated":
        failures.append(f"expected escalated, got {decision}")
    elif case.expect == "not_answered" and decision in ("answered", "answered_with_caveat"):
        failures.append(f"expected escalation/refusal, got {decision}")

    called = {t["tool"] for t in result.tool_trace}
    for tool in case.must_call:
        if tool not in called:
            failures.append(f"never called {tool} (called: {sorted(called)})")

    if case.must_cite_prefix:
        prefixes = tuple(case.must_cite_prefix)
        if not any(
            c.get("source_id", "").startswith(prefixes) for c in result.citations
        ):
            failures.append(f"no citation with prefix {list(prefixes)}")

    answer_lower = (result.answer or "").lower()
    for phrase in case.forbidden:
        if phrase.lower() in answer_lower:
            failures.append(f"LEAK: forbidden phrase present: {phrase!r}")

    return (not failures, failures)


def eval_behavior(session, only: set[str] | None) -> dict:
    from app.services.agent import run_agent

    by_name = {
        name: sid
        for sid, name in session.execute(
            select(Student.id, User.full_name).join(User, User.id == Student.user_id)
        ).all()
    }

    cases = [c for c in BEHAVIOR_CASES if only is None or c.id in only]
    rows = []
    for i, case in enumerate(cases, 1):
        print(f"  [{i}/{len(cases)}] {case.id} {case.question[:60]!r} ...", flush=True)
        try:
            result = run_agent(
                session,
                question=case.question,
                acting_role=UserRole(case.role),
                subject_student_id=by_name.get(case.subject) if case.subject else None,
            )
        except Exception as exc:  # noqa: BLE001 — an eval must record failures, not die on them
            rows.append(
                {
                    "id": case.id, "question": case.question, "expect": case.expect,
                    "high_stakes": case.high_stakes, "passed": False,
                    "failures": [f"CRASH: {type(exc).__name__}: {exc}"],
                    "decision": None, "intent": None, "iterations": None,
                    "latency_ms": None, "tools": [], "citations": 0,
                    "intent_expected": case.expected_intent, "note": case.note,
                }
            )
            continue

        passed, failures = check_behavior(case, result)
        rows.append(
            {
                "id": case.id,
                "question": case.question,
                "expect": case.expect,
                "high_stakes": case.high_stakes,
                "passed": passed,
                "failures": failures,
                "decision": result.decision.value,
                "intent": result.intent,
                "intent_expected": case.expected_intent,
                "iterations": result.iterations,
                "latency_ms": result.latency_ms,
                "tools": [t["tool"] for t in result.tool_trace],
                "citations": len(result.citations),
                "note": case.note,
            }
        )

    # --- aggregates
    scored = [r for r in rows if r["decision"] is not None]
    high_stakes = [r for r in scored if r["high_stakes"]]
    hs_recall = (
        sum(1 for r in high_stakes if r["decision"] == "escalated") / len(high_stakes)
        if high_stakes
        else None
    )
    expect_answered = [r for r in scored if r["expect"] == "answered"]
    over_escalation = (
        sum(1 for r in expect_answered if r["decision"] == "escalated") / len(expect_answered)
        if expect_answered
        else None
    )
    answered = [r for r in scored if r["decision"] in ("answered", "answered_with_caveat")]
    citation_coverage = (
        sum(1 for r in answered if r["citations"] > 0) / len(answered) if answered else None
    )
    leaks = [f for r in rows for f in r["failures"] if f.startswith("LEAK")]
    intent_pairs = [r for r in scored if r["intent_expected"]]
    intent_acc = (
        sum(1 for r in intent_pairs if r["intent"] == r["intent_expected"]) / len(intent_pairs)
        if intent_pairs
        else None
    )
    latencies = sorted(r["latency_ms"] for r in scored if r["latency_ms"])

    return {
        "cases": rows,
        "model": settings.chat_model,
        "passed": sum(1 for r in rows if r["passed"]),
        "total": len(rows),
        "high_stakes_escalation_recall": round(hs_recall, 4) if hs_recall is not None else None,
        "over_escalation_rate": round(over_escalation, 4) if over_escalation is not None else None,
        "citation_coverage_answered": round(citation_coverage, 4) if citation_coverage is not None else None,
        "intent_accuracy": round(intent_acc, 4) if intent_acc is not None else None,
        "leakage_failures": len(leaks),
        "leaks": leaks,
        "latency_p50_ms": latencies[len(latencies) // 2] if latencies else None,
        "latency_p95_ms": latencies[int(len(latencies) * 0.95)] if latencies else None,
        "iterations_mean": round(
            statistics.mean(r["iterations"] for r in scored if r["iterations"]), 2
        ) if scored else None,
    }


# --------------------------------------------------------------------------------------
# Part 3 — readiness consistency
# --------------------------------------------------------------------------------------


def eval_consistency(session) -> dict:
    from app.services.dashboards import batch_readiness
    from app.services.readiness import compute_readiness

    student_ids = list(session.scalars(select(Student.id)).all())
    batch = batch_readiness(session, student_ids)

    mismatches = []
    for sid in student_ids:
        single: ReadinessStatus = compute_readiness(session, sid).status
        batched = batch.get(sid)
        if batched != single:
            mismatches.append(
                {"student_id": sid, "single": single.value, "batch": getattr(batched, "value", None)}
            )

    return {"students": len(student_ids), "mismatches": mismatches}


# --------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------


def apply_gate(retrieval, behavior, consistency) -> list[str]:
    problems = []
    if retrieval and retrieval["recall_at_5"] < GATE["retrieval_recall_at_5"]:
        problems.append(f"recall@5 {retrieval['recall_at_5']} < {GATE['retrieval_recall_at_5']}")
    if retrieval and retrieval["mrr"] < GATE["retrieval_mrr"]:
        problems.append(f"MRR {retrieval['mrr']} < {GATE['retrieval_mrr']}")
    if behavior:
        hs = behavior["high_stakes_escalation_recall"]
        if hs is not None and hs < GATE["high_stakes_escalation_recall"]:
            problems.append(f"high-stakes recall {hs} < {GATE['high_stakes_escalation_recall']}")
        if behavior["leakage_failures"] > GATE["leakage_failures"]:
            problems.append(f"leakage failures: {behavior['leakage_failures']} (must be 0)")
        oe = behavior["over_escalation_rate"]
        if oe is not None and oe > GATE["over_escalation_rate_max"]:
            problems.append(f"over-escalation {oe} > {GATE['over_escalation_rate_max']}")
        cc = behavior["citation_coverage_answered"]
        if cc is not None and cc < GATE["citation_coverage_answered"]:
            problems.append(f"citation coverage {cc} < {GATE['citation_coverage_answered']}")
    if consistency and consistency["mismatches"]:
        problems.append(f"readiness consistency mismatches: {len(consistency['mismatches'])}")
    return problems


def write_report(retrieval, behavior, consistency, gate_problems, elapsed_s) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")

    lines = [
        "# UAX evaluation report",
        "",
        f"- run: {stamp} UTC · elapsed {elapsed_s:.0f}s",
        f"- chat model: `{settings.chat_model}` · embeddings: `{settings.embedding_model}`",
        f"- gate: {'**PASS**' if not gate_problems else '**FAIL** — ' + '; '.join(gate_problems)}",
        "",
    ]

    if retrieval:
        lines += [
            "## Retrieval (15 labelled queries)",
            "",
            f"| recall@5 | MRR |",
            f"|---|---|",
            f"| {retrieval['recall_at_5']} | {retrieval['mrr']} |",
            "",
            "| case | first hit rank | recall@5 |",
            "|---|---|---|",
        ]
        for r in retrieval["cases"]:
            rank = r["first_hit_rank"] if r["first_hit_rank"] else "miss"
            lines.append(f"| {r['id']} | {rank} | {r['recall_at_5']:.2f} |")
        lines.append("")

    if behavior:
        lines += [
            f"## Agent behavior ({behavior['total']} cases · model `{behavior['model']}`)",
            "",
            "| metric | value | gate |",
            "|---|---|---|",
            f"| cases passed | {behavior['passed']}/{behavior['total']} | — |",
            f"| high-stakes escalation recall | {behavior['high_stakes_escalation_recall']} | ≥ {GATE['high_stakes_escalation_recall']} |",
            f"| over-escalation rate | {behavior['over_escalation_rate']} | ≤ {GATE['over_escalation_rate_max']} |",
            f"| citation coverage (answered) | {behavior['citation_coverage_answered']} | ≥ {GATE['citation_coverage_answered']} |",
            f"| intent accuracy (labelled subset) | {behavior['intent_accuracy']} | reported |",
            f"| leakage failures | {behavior['leakage_failures']} | = 0 |",
            f"| latency p50 / p95 | {behavior['latency_p50_ms']} / {behavior['latency_p95_ms']} ms | reported |",
            f"| iterations mean | {behavior['iterations_mean']} | reported |",
            "",
            "### Failures",
            "",
        ]
        failures = [r for r in behavior["cases"] if not r["passed"]]
        if not failures:
            lines.append("None.")
        else:
            for r in failures:
                lines.append(f"- **{r['id']}** ({r['decision']}): {'; '.join(r['failures'])}")
        lines.append("")

    if consistency:
        lines += [
            "## Readiness consistency (set-based vs per-student)",
            "",
            f"- students checked: {consistency['students']}",
            f"- mismatches: {len(consistency['mismatches'])}",
            "",
        ]
        for m in consistency["mismatches"]:
            lines.append(f"- student {m['student_id']}: single={m['single']} batch={m['batch']}")

    report_path = RESULTS_DIR / f"report-{stamp}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    (RESULTS_DIR / "latest.json").write_text(
        json.dumps(
            {
                "stamp": stamp,
                "model": settings.chat_model,
                "retrieval": retrieval,
                "behavior": behavior,
                "consistency": consistency,
                "gate_problems": gate_problems,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-agent", action="store_true")
    parser.add_argument("--only", type=str, default=None, help="comma-separated behavior case ids")
    parser.add_argument("--gate", action="store_true", help="exit 1 when thresholds fail")
    parser.add_argument("--reseed", action="store_true", help="reset + re-embed the demo db afterwards")
    args = parser.parse_args()

    started = datetime.now(UTC)
    only = set(args.only.split(",")) if args.only else None

    with get_sessionmaker()() as session:
        print("part 1/3: retrieval ...")
        retrieval = eval_retrieval(session)
        print(f"  recall@5={retrieval['recall_at_5']}  MRR={retrieval['mrr']}")

        behavior = None
        if not args.skip_agent:
            print(f"part 2/3: agent behavior ({settings.chat_model}) ...")
            behavior = eval_behavior(session, only)
            print(
                f"  passed {behavior['passed']}/{behavior['total']}  "
                f"hs-recall={behavior['high_stakes_escalation_recall']}  "
                f"over-esc={behavior['over_escalation_rate']}  "
                f"leaks={behavior['leakage_failures']}"
            )

        print("part 3/3: readiness consistency ...")
        consistency = eval_consistency(session)
        print(f"  {consistency['students']} students, {len(consistency['mismatches'])} mismatches")

    gate_problems = apply_gate(retrieval, behavior, consistency)
    elapsed = (datetime.now(UTC) - started).total_seconds()
    report_path = write_report(retrieval, behavior, consistency, gate_problems, elapsed)
    print(f"\nreport: {report_path}")
    print("gate  :", "PASS" if not gate_problems else f"FAIL — {'; '.join(gate_problems)}")

    if args.reseed:
        print("\nreseeding demo database ...")
        for module in ("scripts.seed", "scripts.embed_corpus"):
            cmd = [sys.executable, "-m", module]
            if module == "scripts.seed":
                cmd.append("--reset")
            subprocess.run(cmd, check=True)

    if args.gate and gate_problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
