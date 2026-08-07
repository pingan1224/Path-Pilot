"""Run the golden set and report what the system actually does.

    .venv/Scripts/python -m scripts.run_eval                 # everything
    .venv/Scripts/python -m scripts.run_eval --skip-agent    # retrieval + consistency only
    .venv/Scripts/python -m scripts.run_eval --only B13,B14  # subset of behavior cases
    .venv/Scripts/python -m scripts.run_eval --gate          # exit 1 if thresholds fail

Four parts:
1. Retrieval — recall@5 and MRR over 15 labelled queries.
2. Behavior — 35 agent runs scored on decision, tool choice, citations, and leakage.
3. Decoder — 32 labelled error messages scored on coverage, accuracy, ambiguity, and
   grounding. No model involved, so this part is deterministic and cheap; it runs even
   under --skip-agent.
4. Consistency — the set-based readiness (advisor queue) must agree with the per-student
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
from eval.golden import BEHAVIOR_CASES, forbidden_tools_for
from eval.trajectory import aggregate as aggregate_trajectory
from eval.trajectory import score_trace
from eval.retrieval_cases import RETRIEVAL_CASES, family_counts
from eval.retrieval_cases import validate as validate_labels

RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval" / "results"

# Retrieval floors are REGRESSION gates, not quality targets.
#
# The previous values (0.85 / 0.70) were calibrated against a 15-chunk hand-written
# corpus where scoring 1.00 was trivial. Against ~1,000 chunks of real policy text the
# same pipeline measures 0.7367 / 0.504, so keeping the old numbers would fail every run
# for the wrong reason — and quietly lowering them to whatever passes is how an eval
# becomes theatre. These sit just under the measured baseline: they catch a regression,
# and they are explicitly NOT the target. Beating them is the job of the retrieval
# improvements (metadata filtering, hybrid search, reranking), each of which has to show
# its gain against this recorded baseline.
#
# Baselines, strategy=heading, 2026-08-04:
#   no scoping        recall@5 0.7367  MRR 0.504
#   home-school boost recall@5 0.9100  MRR 0.8383   <- current, floors set under this
GATE = {
    "retrieval_recall_at_5": 0.85,
    "retrieval_mrr": 0.75,
    "high_stakes_escalation_recall": 0.90,  # the number the source RFP promised
    "leakage_failures": 0,                   # hard zero
    "over_escalation_rate_max": 0.40,
    "citation_coverage_answered": 0.90,
    "consistency_mismatches": 0,             # hard zero
    # Decoder. Two hard zeros and one floor, and the floor is deliberately the loose one.
    #
    # `confidently_wrong` and `unsafe_hold_reads` are the properties a student is harmed
    # by: an error read as the wrong cause, or a hold read as financial when the message
    # never said so. Neither is allowed to happen once.
    #
    # `decoder_coverage` is set under the measured value the way the retrieval floors are.
    # It is not a target: the held_out family is written to fail, and driving this number
    # up by adding those phrasings to the table is exactly the move the number must not
    # reward. Coverage rises when the table earns it against phrasings nobody has seen yet.
    #
    # Baselines, 2026-08-06:
    #   literal phrases only    coverage 0.7500  held_out 0/5
    #   gap patterns            coverage 0.8333  held_out 1/5   <- current, floor under it
    #
    # The gap-pattern change is the distinction the floor is meant to protect. It was
    # motivated by one paraphrase case (D15, "the requisites were not met") and fixed a
    # held-out case nobody wrote a pattern for (D30, "requires a permission code"). Adding
    # D30's wording to the table would have moved the same number without meaning anything.
    "decoder_confidently_wrong": 0,          # hard zero
    "decoder_unsafe_hold_reads": 0,          # hard zero
    "decoder_coverage": 0.80,
    "decoder_ambiguity_held": 1.00,
    # Trajectory. One hard zero and one loose ceiling, and the rest is reported.
    #
    # `forbidden_tool_calls` covers the one write tool in the surface firing on a question
    # that did not ask for a write. Nothing it writes is binding, so this is not a data
    # integrity gate — it is the gate on the agent acting unbidden, which is the property
    # that has to hold before the tool surface grows again.
    #
    # `redundant_call_rate` is a ceiling on runs that issued an identical call twice. Set
    # loose deliberately: it is a regression tripwire, and tightening it towards zero would
    # start punishing legitimate re-tries after a failed call.
    #
    # Deliberately NOT gated: unused results (looking and not citing is often diligence, and
    # gating it rewards padding citations), parallelism and path ratio (both reported so a
    # change in them is visible, neither yet measured over enough runs to floor).
    #
    # Baseline, 2026-08-07, 35 behavior cases:
    #   tool calls / run      3.11
    #   calls per iteration   0.94   <- under 1.0: more turns than calls, the opposite of
    #                                  the batching the prompt asks for
    #   repeated calls        0.00   (gate holds with room)
    #   forbidden calls       0      (the write tool never fired on the 31 cases banning it)
    #   failed calls          0.1143
    #   uncited lookups       0.40
    #   path ratio            2.12   over the 8 labelled cases — about twice the minimum
    #
    # The uncited number is concentrated, not spread: the three leakage probes (B24-B26) ask
    # about a document their role cannot see, and the agent searches repeatedly, gets only
    # unrelated passages, and refuses. B26 spent 13 calls and 8 uncited searches to reach a
    # correct refusal. Right answer, and nothing in the loop tells it to stop looking. That
    # is the next thing to fix, and it was invisible until this ran.
    "forbidden_tool_calls": 0,               # hard zero
    "redundant_call_rate_max": 0.20,
    # Transcript intake. The asymmetry is deliberate: a row the reader vouches for and gets
    # wrong puts coursework in a student's record they never took, or a grade they did not
    # earn, and nothing downstream will catch it. A row it fails to read is a course quietly
    # missing — a real cost, but one the student can see and fix on the review screen.
    #
    # Baseline, 2026-08-07, 5 synthetic layouts / 18 labelled rows: recall 1.00, 0 wrong.
    "intake_silently_wrong": 0,              # hard zero
    "intake_row_recall": 0.90,
}


# --------------------------------------------------------------------------------------
# Part 1 — retrieval
# --------------------------------------------------------------------------------------


def eval_retrieval(session, strategy: str | None = None) -> dict:
    """Score retrieval against section-level labels.

    A retrieved chunk counts as a hit when its `section_keys` cover an expected section.
    Scoring on coverage rather than chunk identity is what lets one label set grade every
    chunking strategy — boundaries are the variable under test, so they cannot also be the
    unit of measurement.
    """
    from app.services.retrieval import RetrievalScope, search_policy

    problems = validate_labels()
    if problems:
        raise SystemExit("Invalid retrieval labels:\n  " + "\n  ".join(problems))

    # The scope the running system supplies for the demo population: every labelled query
    # is asked by a graduate student at the School of Professional Studies. Passing it here
    # measures the pipeline as deployed rather than a version of it nobody runs.
    scope = RetrievalScope(school="professional-studies", level="graduate")

    rows = []
    for case in RETRIEVAL_CASES:
        expected = set(case.expected)
        result = search_policy(
            session, case.query, case.role, k=5, strategy=strategy, scope=scope
        )

        covered_by_rank = [set(c.section_keys) & expected for c in result.chunks]
        hit_ranks = [i + 1 for i, hit in enumerate(covered_by_rank) if hit]
        found = set().union(*covered_by_rank) if covered_by_rank else set()

        rows.append(
            {
                "id": case.id,
                "family": case.family,
                "role": case.role,
                "query": case.query,
                "expected": sorted(expected),
                "found": sorted(found),
                "top_paths": [c.heading_path for c in result.chunks[:3]],
                "retrieved_section_counts": [len(c.section_keys) for c in result.chunks],
                "first_hit_rank": hit_ranks[0] if hit_ranks else None,
                "recall_at_5": len(found) / len(expected),
                "degraded": result.degraded,
            }
        )

    by_family: dict[str, list[dict]] = {}
    for row in rows:
        by_family.setdefault(row["family"], []).append(row)

    families = {
        name: {
            "cases": len(group),
            "recall_at_5": round(statistics.mean(r["recall_at_5"] for r in group), 4),
            "mrr": round(
                statistics.mean((1 / r["first_hit_rank"]) if r["first_hit_rank"] else 0.0 for r in group), 4
            ),
        }
        for name, group in sorted(by_family.items())
    }

    recall = statistics.mean(r["recall_at_5"] for r in rows)
    mrr = statistics.mean((1 / r["first_hit_rank"]) if r["first_hit_rank"] else 0.0 for r in rows)

    # How many source sections an average retrieved chunk covers. Coverage-based labels
    # give a wide chunk more chances to contain the target, so this number is needed to
    # read recall@5 across strategies without being fooled by chunk width.
    breadth = [n for r in rows for n in r["retrieved_section_counts"]]

    return {
        "cases": rows,
        "strategy": strategy or settings.chunk_strategy,
        "recall_at_5": round(recall, 4),
        "mrr": round(mrr, 4),
        "sections_per_chunk": round(statistics.mean(breadth), 2) if breadth else 0.0,
        "families": families,
    }


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
                    "trajectory": None,
                }
            )
            continue

        passed, failures = check_behavior(case, result)

        # How it got there, scored alongside whether it got there. A forbidden tool is a
        # trajectory defect that also fails the case: calling the one write tool on a
        # question that did not ask for a write is the agent acting unbidden, which is a
        # correctness problem and not merely inefficiency.
        trajectory = score_trace(
            result.tool_trace,
            result.citations,
            iterations=result.iterations,
            must_not_call=forbidden_tools_for(case),
            min_tool_calls=case.min_tool_calls,
        )
        if trajectory.forbidden_calls:
            passed = False
            failures = failures + [
                f"FORBIDDEN TOOL: called {name}" for name in trajectory.forbidden_calls
            ]

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
                "trajectory": {
                    "tool_calls": trajectory.tool_calls,
                    "iterations": trajectory.iterations,
                    "parallelism": trajectory.parallelism,
                    "redundant_calls": trajectory.redundant_calls,
                    "unused_results": trajectory.unused_results,
                    "failed_calls": trajectory.failed_calls,
                    "forbidden_calls": list(trajectory.forbidden_calls),
                    "path_ratio": trajectory.path_ratio,
                    "detail": list(trajectory.redundant_detail + trajectory.unused_detail),
                },
                "_score": trajectory,
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
    trajectory = aggregate_trajectory([r.pop("_score") for r in rows if "_score" in r])

    return {
        "cases": rows,
        "trajectory": trajectory,
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
# Part 3 — error decoder
# --------------------------------------------------------------------------------------


def check_decoder(case, result) -> tuple[bool, list[str]]:
    """Score one decode. Returns (passed, failures)."""
    failures: list[str] = []
    classification = result.classification
    outcome = classification.outcome.value
    got = classification.reason

    if outcome != case.expect_outcome:
        failures.append(f"expected {case.expect_outcome}, got {outcome}")

    if case.expect_outcome == "identified" and outcome == "identified":
        if got is not case.expected:
            # Prefixed so the aggregate can count these separately. A wrong confident
            # answer is not one failure among many — it is the failure this eval exists
            # for, and it must never average away against passing cases.
            failures.append(
                f"WRONG: identified {got.value if got else None}, expected {case.expected.value}"
            )

    if case.expect_outcome == "ambiguous":
        candidates = {c.reason for c in classification.candidates}
        missing = [r.value for r in case.expect_candidates if r not in candidates]
        if missing:
            failures.append(f"candidates missing {missing}")
        if not classification.follow_ups:
            failures.append("ambiguous with no question to resolve it")

    extracted = classification.extracted
    for label, wanted, actual in (
        ("course_codes", case.expect_course_codes, extracted.course_codes),
        ("class_numbers", case.expect_class_numbers, extracted.class_numbers),
        ("hold_codes", case.expect_hold_codes, extracted.hold_codes),
    ):
        for value in wanted:
            if value not in actual:
                failures.append(f"{label} missing {value!r} (got {list(actual)})")
    if case.expect_term and extracted.term != case.expect_term:
        failures.append(f"term {extracted.term!r} != {case.expect_term!r}")

    # Grounding, both directions. A cause the corpus covers must arrive with a passage;
    # a cause it does not cover must arrive with the absence stated rather than padded.
    if outcome == "identified":
        if case.expect_no_policy:
            if result.passages:
                failures.append(
                    f"expected no grounded policy, got {len(result.passages)} passage(s)"
                )
            if not result.no_policy_note:
                failures.append("uncovered cause did not disclose the missing source")
        elif not result.passages:
            failures.append("identified with no grounded policy passage")

    return (not failures, failures)


def eval_decoder(session) -> dict:
    from app.decoder import decode
    from eval.decoder_cases import CASES, family_counts
    from eval.decoder_cases import validate as validate_decoder_labels

    problems = validate_decoder_labels()
    if problems:
        raise SystemExit("Invalid decoder labels:\n  " + "\n  ".join(problems))

    rows = []
    for case in CASES:
        result = decode(session, case.text, role="student")
        passed, failures = check_decoder(case, result)
        classification = result.classification
        rows.append(
            {
                "id": case.id,
                "family": case.family,
                "text": case.text,
                "expect_outcome": case.expect_outcome,
                "expected": case.expected.value if case.expected else None,
                "outcome": classification.outcome.value,
                "reason": classification.reason.value if classification.reason else None,
                "confidence": classification.confidence,
                "safety_critical": case.safety_critical,
                "passages": len(result.passages),
                "no_policy": bool(result.no_policy_note),
                "follow_ups": [f.question for f in classification.follow_ups],
                "passed": passed,
                "failures": failures,
                "note": case.note,
            }
        )

    labelled = [r for r in rows if r["expect_outcome"] == "identified"]
    named = [r for r in labelled if r["outcome"] == "identified"]
    wrong = [r for r in rows if any(f.startswith("WRONG") for f in r["failures"])]

    # Coverage and accuracy are reported separately on purpose. A decoder that names
    # nothing has perfect accuracy, and one that names everything has perfect coverage;
    # only the pair says whether it is useful.
    coverage = len(named) / len(labelled) if labelled else None
    accuracy = (len(named) - len(wrong)) / len(named) if named else None

    ambiguous_cases = [r for r in rows if r["expect_outcome"] == "ambiguous"]
    ambiguity_held = (
        sum(1 for r in ambiguous_cases if r["outcome"] == "ambiguous")
        / len(ambiguous_cases)
        if ambiguous_cases
        else None
    )

    # The safety property, stated as a count rather than a rate: how many times a message
    # that does not name a hold's office got read as one that does.
    unsafe_hold_reads = sum(
        1
        for r in rows
        if r["safety_critical"]
        and r["expect_outcome"] == "ambiguous"
        and r["outcome"] == "identified"
    )

    by_family: dict[str, list[dict]] = {}
    for row in rows:
        by_family.setdefault(row["family"], []).append(row)

    return {
        "cases": rows,
        "counts": family_counts(),
        "passed": sum(1 for r in rows if r["passed"]),
        "total": len(rows),
        "coverage": round(coverage, 4) if coverage is not None else None,
        "accuracy_when_named": round(accuracy, 4) if accuracy is not None else None,
        "confidently_wrong": len(wrong),
        "ambiguity_held": round(ambiguity_held, 4) if ambiguity_held is not None else None,
        "unsafe_hold_reads": unsafe_hold_reads,
        "families": {
            name: {
                "cases": len(group),
                "passed": sum(1 for r in group if r["passed"]),
            }
            for name, group in sorted(by_family.items())
        },
    }


# --------------------------------------------------------------------------------------
# Part 3b — transcript intake
# --------------------------------------------------------------------------------------


def eval_intake(session) -> dict:
    """Score transcript reading against labelled synthetic fixtures.

    Two numbers, and the distinction between them is the whole point. A reader that reports
    every row as clean scores perfectly on recall and is dangerous; one that reads fewer rows
    but labels the uncertain ones scores worse on recall and is usable. So `silently_wrong`
    is gated at zero and recall merely has a floor.
    """
    from pathlib import Path

    from app.intake import read_transcript
    from eval.intake_cases import CASES
    from eval.intake_cases import validate as validate_intake

    problems = validate_intake()
    if problems:
        raise SystemExit("Invalid intake labels:\n  " + "\n  ".join(problems))

    fixtures = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    rows = []
    for case in CASES:
        path = fixtures / case.fixture
        if not path.exists():
            rows.append(
                {
                    "id": case.id, "layout": case.layout, "passed": False,
                    "failures": [f"fixture missing: {case.fixture} — run tests.fixtures.make_transcripts"],
                    "found": 0, "expected": len(case.rows), "wrong": 0, "note": case.note,
                }
            )
            continue

        reading = read_transcript(session, path.read_bytes())
        by_code = {r.course_code: r for r in reading.rows if r.course_code}
        failures: list[str] = []
        wrong = 0

        if case.expect_no_text_layer:
            if not reading.no_text_layer:
                failures.append("expected no text layer to be detected")
            if not reading.notes:
                failures.append("a scanned file must come back with an explanation")
        found = 0
        for expected in case.rows:
            actual = by_code.get(expected.course_code)
            if actual is None:
                failures.append(f"{expected.course_code}: not read at all")
                continue
            found += 1
            # A row the reader calls `matched` is a row it is vouching for, so every field
            # has to be right. A `needs_review` row is already flagged for the student, so a
            # blank field there is disclosure, not error.
            if actual.status.value != expected.status:
                failures.append(
                    f"{expected.course_code}: status {actual.status.value} != {expected.status}"
                )
                if actual.status.value == "matched":
                    wrong += 1
            if actual.status.value == "matched":
                for label, got, want in (
                    ("term", actual.term, expected.term),
                    ("grade", actual.grade, expected.grade),
                    ("state", actual.state, expected.state),
                ):
                    if got != want:
                        failures.append(f"{expected.course_code}: {label} {got!r} != {want!r}")
                        wrong += 1

        unreadable = sum(1 for r in reading.rows if r.status.value == "unreadable")
        if unreadable < case.min_unreadable:
            failures.append(
                f"expected at least {case.min_unreadable} unreadable row(s), got {unreadable}"
            )
        # Phantom rows are their own failure: an invented course is worse than a missed one.
        unexpected = set(by_code) - {r.course_code for r in case.rows}
        if unexpected:
            failures.append(f"read courses the fixture does not contain: {sorted(unexpected)}")
            wrong += len(unexpected)

        rows.append(
            {
                "id": case.id, "layout": case.layout, "passed": not failures,
                "failures": failures, "found": found, "expected": len(case.rows),
                "wrong": wrong, "unreadable": unreadable, "note": case.note,
            }
        )

    total_expected = sum(r["expected"] for r in rows)
    total_found = sum(r["found"] for r in rows)
    return {
        "cases": rows,
        "passed": sum(1 for r in rows if r["passed"]),
        "total": len(rows),
        "row_recall": round(total_found / total_expected, 4) if total_expected else None,
        "silently_wrong": sum(r["wrong"] for r in rows),
    }


# --------------------------------------------------------------------------------------
# Part 4 — readiness consistency
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


def apply_gate(retrieval, behavior, decoder, intake, consistency) -> list[str]:
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
        traj = behavior.get("trajectory") or {}
        if traj.get("forbidden_calls", 0) > GATE["forbidden_tool_calls"]:
            problems.append(
                f"forbidden tool calls: {traj['forbidden_calls']} (must be 0)"
            )
        rr = traj.get("redundant_call_rate")
        if rr is not None and rr > GATE["redundant_call_rate_max"]:
            problems.append(
                f"redundant call rate {rr} > {GATE['redundant_call_rate_max']}"
            )
    if decoder:
        if decoder["confidently_wrong"] > GATE["decoder_confidently_wrong"]:
            problems.append(
                f"decoder confidently wrong: {decoder['confidently_wrong']} (must be 0)"
            )
        if decoder["unsafe_hold_reads"] > GATE["decoder_unsafe_hold_reads"]:
            problems.append(
                f"decoder named a hold's office from a message that did not: "
                f"{decoder['unsafe_hold_reads']} (must be 0)"
            )
        cov = decoder["coverage"]
        if cov is not None and cov < GATE["decoder_coverage"]:
            problems.append(f"decoder coverage {cov} < {GATE['decoder_coverage']}")
        held = decoder["ambiguity_held"]
        if held is not None and held < GATE["decoder_ambiguity_held"]:
            problems.append(
                f"decoder ambiguity held {held} < {GATE['decoder_ambiguity_held']}"
            )
    if intake:
        if intake["silently_wrong"] > GATE["intake_silently_wrong"]:
            problems.append(
                f"intake rows silently wrong: {intake['silently_wrong']} (must be 0)"
            )
        rr = intake["row_recall"]
        if rr is not None and rr < GATE["intake_row_recall"]:
            problems.append(f"intake row recall {rr} < {GATE['intake_row_recall']}")
    if consistency and consistency["mismatches"]:
        problems.append(f"readiness consistency mismatches: {len(consistency['mismatches'])}")
    return problems


def write_report(retrieval, behavior, decoder, intake, consistency, gate_problems, elapsed_s) -> Path:
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
            f"## Retrieval ({len(retrieval['cases'])} labelled queries · "
            f"strategy `{retrieval['strategy']}`)",
            "",
            "| recall@5 | MRR |",
            "|---|---|",
            f"| {retrieval['recall_at_5']} | {retrieval['mrr']} |",
            "",
            "### By family",
            "",
            "| family | cases | recall@5 | MRR |",
            "|---|---|---|---|",
        ]
        for name, stats in retrieval["families"].items():
            lines.append(
                f"| {name} | {stats['cases']} | {stats['recall_at_5']} | {stats['mrr']} |"
            )
        misses = [r for r in retrieval["cases"] if r["first_hit_rank"] is None]
        lines += ["", f"### Misses ({len(misses)})", ""]
        if not misses:
            lines.append("None.")
        for r in misses:
            lines.append(f"- **{r['id']}** ({r['family']}) {r['query']!r}")
            lines.append(f"  - wanted: {r['expected'][0]}")
            lines.append(f"  - got: {r['top_paths']}")
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
        ]

        traj = behavior.get("trajectory") or {}
        if traj.get("runs"):
            lines += [
                "### Trajectory — how it got there",
                "",
                "Outcome metrics are satisfiable by an agent that blunders to the right "
                "answer. These are the ones that notice.",
                "",
                "| metric | value | gate |",
                "|---|---|---|",
                f"| tool calls / run | {traj['tool_calls_mean']} | reported |",
                f"| calls per iteration | {traj['parallelism_mean']} | reported — the prompt asks for independent lookups to be batched |",
                f"| runs with a repeated call | {traj['redundant_call_rate']} | ≤ {GATE['redundant_call_rate_max']} |",
                f"| forbidden tool calls | {traj['forbidden_calls']} | = 0 |",
                f"| runs with a failed call | {traj['failed_call_rate']} | reported |",
                f"| runs with uncited lookups | {traj['unused_result_rate']} | reported, not a defect on its own |",
                f"| path ratio (labelled subset, n={traj['path_ratio_n']}) | {traj['path_ratio_mean']} | reported |",
                "",
            ]
            noisy = [
                r
                for r in behavior["cases"]
                if (r.get("trajectory") or {}).get("detail")
            ]
            lines += [f"#### Runs worth reading ({len(noisy)})", ""]
            if not noisy:
                lines.append("None — no repeats and no uncited lookups.")
            for r in noisy:
                t = r["trajectory"]
                lines.append(
                    f"- **{r['id']}** {t['tool_calls']} calls / {t['iterations']} iters: "
                    + "; ".join(t["detail"])
                )
            lines.append("")

        lines += [
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

    if decoder:
        lines += [
            f"## Error decoder ({decoder['total']} labelled messages · {decoder['counts']})",
            "",
            "| metric | value | gate |",
            "|---|---|---|",
            f"| cases passed | {decoder['passed']}/{decoder['total']} | — |",
            f"| coverage (labelled causes named) | {decoder['coverage']} | ≥ {GATE['decoder_coverage']} |",
            f"| accuracy when named | {decoder['accuracy_when_named']} | reported |",
            f"| confidently wrong | {decoder['confidently_wrong']} | = 0 |",
            f"| ambiguity held | {decoder['ambiguity_held']} | ≥ {GATE['decoder_ambiguity_held']} |",
            f"| hold office invented | {decoder['unsafe_hold_reads']} | = 0 |",
            "",
            "### By family",
            "",
            "| family | cases | passed |",
            "|---|---|---|",
        ]
        for name, stats in decoder["families"].items():
            lines.append(f"| {name} | {stats['cases']} | {stats['passed']} |")

        misses = [
            r
            for r in decoder["cases"]
            if r["expect_outcome"] == "identified" and r["outcome"] != "identified"
        ]
        lines += ["", f"### Not decoded ({len(misses)}) — the table's backlog", ""]
        if not misses:
            lines.append("None.")
        for r in misses:
            lines.append(f"- **{r['id']}** ({r['family']}) {r['text']!r} → {r['outcome']}")
            lines.append(f"  - wanted: {r['expected']}")

        other_failures = [
            r for r in decoder["cases"] if not r["passed"] and r not in misses
        ]
        lines += ["", f"### Other failures ({len(other_failures)})", ""]
        if not other_failures:
            lines.append("None.")
        for r in other_failures:
            lines.append(f"- **{r['id']}**: {'; '.join(r['failures'])}")
        lines.append("")

    if intake:
        lines += [
            f"## Transcript intake ({intake['total']} synthetic layouts)",
            "",
            "| metric | value | gate |",
            "|---|---|---|",
            f"| cases passed | {intake['passed']}/{intake['total']} | — |",
            f"| row recall | {intake['row_recall']} | ≥ {GATE['intake_row_recall']} |",
            f"| rows silently wrong | {intake['silently_wrong']} | = 0 |",
            "",
            "| case | layout | read | wrong |",
            "|---|---|---|---|",
        ]
        for r in intake["cases"]:
            lines.append(
                f"| {r['id']} | {r['layout']} | {r['found']}/{r['expected']} | {r['wrong']} |"
            )
        failures = [r for r in intake["cases"] if not r["passed"]]
        lines += ["", f"### Failures ({len(failures)})", ""]
        if not failures:
            lines.append("None.")
        for r in failures:
            lines.append(f"- **{r['id']}**: {'; '.join(r['failures'])}")
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

    # latest.json is the record of the last COMPLETE run, and a partial run must not
    # become it. Writing one part and nulling the rest looked harmless until
    # `--only-decoder` erased the retrieval and behavior numbers from the only file that
    # held them; merging instead would be worse, presenting an old measurement as current.
    # The timestamped report above is still written either way, so nothing is lost.
    if all(part is not None for part in (retrieval, behavior, decoder, consistency)):
        (RESULTS_DIR / "latest.json").write_text(
            json.dumps(
                {
                    "stamp": stamp,
                    "model": settings.chat_model,
                    "retrieval": retrieval,
                    "behavior": behavior,
                    "decoder": decoder,
                    "consistency": consistency,
                    "gate_problems": gate_problems,
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
    else:
        print("  (partial run — latest.json left as the last complete run)")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-agent", action="store_true")
    parser.add_argument("--skip-decoder", action="store_true")
    parser.add_argument(
        "--only-decoder",
        action="store_true",
        help="decoder part alone — no model calls, seconds not minutes",
    )
    parser.add_argument("--only", type=str, default=None, help="comma-separated behavior case ids")
    parser.add_argument("--gate", action="store_true", help="exit 1 when thresholds fail")
    parser.add_argument("--reseed", action="store_true", help="reset + re-embed the demo db afterwards")
    args = parser.parse_args()

    started = datetime.now(UTC)
    only = set(args.only.split(",")) if args.only else None

    with get_sessionmaker()() as session:
        retrieval = None
        behavior = None
        decoder = None
        consistency = None

        if not args.only_decoder:
            print(f"part 1/4: retrieval ({len(RETRIEVAL_CASES)} cases, {family_counts()}) ...")
            retrieval = eval_retrieval(session)
            print(f"  recall@5={retrieval['recall_at_5']}  MRR={retrieval['mrr']}")
            for name, stats in retrieval["families"].items():
                print(f"    {name:<12} n={stats['cases']:<3} recall={stats['recall_at_5']:<8} mrr={stats['mrr']}")

            if not args.skip_agent:
                print(f"part 2/4: agent behavior ({settings.chat_model}) ...")
                behavior = eval_behavior(session, only)
                print(
                    f"  passed {behavior['passed']}/{behavior['total']}  "
                    f"hs-recall={behavior['high_stakes_escalation_recall']}  "
                    f"over-esc={behavior['over_escalation_rate']}  "
                    f"leaks={behavior['leakage_failures']}"
                )
                traj = behavior.get("trajectory") or {}
                if traj.get("runs"):
                    print(
                        f"  trajectory: calls/run={traj['tool_calls_mean']}  "
                        f"per-iter={traj['parallelism_mean']}  "
                        f"repeats={traj['redundant_call_rate']}  "
                        f"forbidden={traj['forbidden_calls']}  "
                        f"uncited={traj['unused_result_rate']}"
                    )

        if not args.skip_decoder:
            print("part 3/4: error decoder ...")
            decoder = eval_decoder(session)
            print(
                f"  passed {decoder['passed']}/{decoder['total']}  "
                f"coverage={decoder['coverage']}  "
                f"accuracy={decoder['accuracy_when_named']}  "
                f"wrong={decoder['confidently_wrong']}  "
                f"unsafe-hold={decoder['unsafe_hold_reads']}"
            )
            for name, stats in decoder["families"].items():
                print(f"    {name:<14} {stats['passed']}/{stats['cases']}")

        intake = None
        if not args.skip_decoder:
            print("part 3b/4: transcript intake ...")
            intake = eval_intake(session)
            print(
                f"  passed {intake['passed']}/{intake['total']}  "
                f"recall={intake['row_recall']}  wrong={intake['silently_wrong']}"
            )

        if not args.only_decoder:
            print("part 4/4: readiness consistency ...")
            consistency = eval_consistency(session)
            print(f"  {consistency['students']} students, {len(consistency['mismatches'])} mismatches")

    gate_problems = apply_gate(retrieval, behavior, decoder, intake, consistency)
    elapsed = (datetime.now(UTC) - started).total_seconds()
    report_path = write_report(retrieval, behavior, decoder, intake, consistency, gate_problems, elapsed)
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
