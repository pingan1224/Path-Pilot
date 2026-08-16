"""Break each dependency on purpose and read what the student ends up with.

    FAULT_INJECTION=true .venv/Scripts/python -m scripts.fault_probe
    ... --only embeddings.unavailable          # one scenario
    ... --gate                                 # exit 1 on any failure

Rule 6 promises every dependency a visible degraded path. Before this script those paths
had run **zero times in 121 audited turns** — designed, documented, never executed. This is
the instrument that changes that, and like the trajectory eval it exists to produce a number
that can be wrong: `degradation coverage`, the share of declared degraded modes that have
actually executed in an audited run.

Each scenario arms one fault, runs the **real agent loop** against the **real model**, and
checks what came out. The checks are deliberately about the user-visible contract rather
than about internals:

  disclosed        the degradation reached `degraded_modes`, so the UI can say so
  not_confident    the turn did not come back as a clean `answered` with high confidence
  no_invention     every citation is a source id some tool really returned this turn
  survived         a structured answer exists at all — no crash, no empty string
  case_opened      where the failure means the assistant cannot serve the request

`no_invention` is the one worth watching. The others check that we admitted something went
wrong; this one checks the thing that actually hurts a student — an assistant that loses its
evidence and keeps its confidence. A degraded turn that invents a citation is a worse
outcome than a turn that failed outright, because it is indistinguishable from a good one.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app import faults
from app.db.session import get_sessionmaker
from app.models import AiInteraction, Student, User, UserRole

RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval" / "results"

# Every degraded mode the code can record. The coverage metric is measured against this
# list, so a mode added without a scenario shows up as uncovered instead of unnoticed.
# Every degraded mode the code can record. The coverage metric is measured against this
# list, so a mode added without a scenario shows up as uncovered instead of unnoticed.
#
# **Scope, so the number is not read as more than it is.** These are the degradations of an
# *agent turn*, because coverage is computed from `ai_interactions` and that is the only
# thing recorded there. Transcript intake has a degraded path of its own — the vision
# endpoint failing, which must fall back to the honest refusal rather than to an empty
# reading — and it is not an agent turn, so it cannot appear here. It is covered by
# `tests/test_intake_ocr.py` with the `ocr.unavailable` fault armed, which costs nothing to
# run. "Coverage 4/4" means the agent's four, not every degraded path in the system.
DECLARED_MODES = (
    "keyword_fallback",
    "llm_error",
    "tool_error:*",
    "retrieval_budget_exhausted",
)


@dataclass
class Scenario:
    id: str
    fault: str
    student: str | None
    question: str
    what_breaks: str
    # Degraded mode that must be recorded. None where the fault is deliberately not a
    # degradation — see retrieval.empty and freshness.all_stale.
    expect_mode: str | None
    expect_case: bool = False
    # Substrings, any one of which shows the answer owned the problem in plain language.
    # Checked case-insensitively and reported, not gated: the model writes these in its own
    # words and a phrase list would be measuring our wording, not its honesty.
    honest_phrases: tuple[str, ...] = ()
    notes: str = ""


SCENARIOS: list[Scenario] = [
    Scenario(
        "F1", "embeddings.unavailable", "Alex Chen",
        "What happens if I join a waitlist?",
        "The embedding provider is down, so policy search falls back to keyword ranking.",
        expect_mode="keyword_fallback",
        honest_phrases=("degraded", "keyword", "less relevant"),
        notes="The answer may still be right; the point is that the weaker ranking is disclosed.",
    ),
    Scenario(
        "F2", "llm.error", "Alex Chen",
        "Why is my registration blocked?",
        "The chat model call fails on the first iteration.",
        expect_mode="llm_error", expect_case=True,
        honest_phrases=("technical problem", "human", "could not"),
        notes="Must be a routed escalation with a quotable case number, never a bare 500.",
    ),
    Scenario(
        "F3", "tool.error:get_holds", "Alex Chen",
        "Do I have any holds on my record right now?",
        "The one record lookup this question needs raises.",
        expect_mode="tool_error:get_holds",
        honest_phrases=("could not", "unable", "not able", "failed", "unavailable"),
        notes=(
            "The trap: get_holds failing must never become 'you have no holds'. An error "
            "and an empty result are the same shape to a model that is not careful."
        ),
    ),
    Scenario(
        "F4", "retrieval.empty", "Priya Raman",
        "What are the rules about cheating and plagiarism?",
        "Retrieval is reachable but matches nothing at all.",
        expect_mode=None,
        honest_phrases=("could not find", "no policy", "not able to find", "does not"),
        notes=(
            "No exception and no degraded flag by design — this is the honest-answer path "
            "with zero evidence. The M8 budget makes it terminate; the question here is "
            "whether it terminates by saying so or by answering from training data."
        ),
    ),
    Scenario(
        "F6", "search.budget_spent", "Priya Raman",
        "What happens if I miss the deadline to drop a course?",
        "The policy-search budget is already gone, so the first search is refused.",
        expect_mode="retrieval_budget_exhausted",
        honest_phrases=("could not", "not able", "does not cover", "no policy", "advisor"),
        notes=(
            "M8 shipped this refusal branch on the strength of unit tests; it had never "
            "fired in a real turn. The question is whether being refused produces an "
            "honest 'I could not look this up' or an answer from training data."
        ),
    ),
    Scenario(
        "F5", "freshness.all_stale", "Alex Chen",
        "What exactly do I need to do to clear my aid hold, and by when?",
        "Every record reads as past its freshness policy.",
        expect_mode=None,
        honest_phrases=("stale", "as of", "confirm", "out of date", "older"),
        notes=(
            "Rule 2's disclosure path. Not a degraded mode: nothing is broken, the data is "
            "simply older than it claims. The deadline in this answer is exactly the kind "
            "of fact a student would act on without checking."
        ),
    ),
]


@dataclass
class Outcome:
    scenario: Scenario
    failures: list[str] = field(default_factory=list)
    observed_modes: list[str] = field(default_factory=list)
    decision: str = ""
    confidence: str | None = None
    referral: dict | None = None
    answer: str = ""
    tool_calls: int = 0
    honest: bool = False

    @property
    def passed(self) -> bool:
        return not self.failures


def run_scenario(session, scenario: Scenario, by_name: dict[str, int]) -> Outcome:
    from app.services.agent import run_agent

    outcome = Outcome(scenario=scenario)
    subject_id = by_name.get(scenario.student) if scenario.student else None

    try:
        with faults.injected(scenario.fault):
            result = run_agent(
                session,
                question=scenario.question,
                acting_role=UserRole.student,
                subject_student_id=subject_id,
            )
    except Exception as exc:  # noqa: BLE001 — a crash IS the finding here
        outcome.failures.append(f"survived: the turn raised {type(exc).__name__}: {exc}")
        return outcome

    outcome.observed_modes = list(result.degraded_modes)
    outcome.decision = result.decision.value
    outcome.confidence = result.confidence
    outcome.referral = result.referral
    outcome.answer = result.answer or ""
    outcome.tool_calls = len(result.tool_trace)

    # survived
    if not outcome.answer.strip():
        outcome.failures.append("survived: empty answer")

    # disclosed
    if scenario.expect_mode and scenario.expect_mode not in outcome.observed_modes:
        outcome.failures.append(
            f"disclosed: expected degraded mode {scenario.expect_mode!r}, "
            f"got {outcome.observed_modes or 'none'}"
        )

    # not_confident — a degraded turn must not come back looking like a clean one.
    if scenario.expect_mode and outcome.decision == "answered":
        outcome.failures.append(
            "not_confident: decision is a clean 'answered' despite a recorded degradation"
        )

    # no_invention — the load-bearing check.
    stored = session.get(AiInteraction, result.interaction_id)
    returned = set()
    for call in stored.tool_calls or []:
        returned.update(call.get("source_ids") or [])
    invented = [
        c.get("source_id") for c in result.citations if c.get("source_id") not in returned
    ]
    if invented:
        outcome.failures.append(f"no_invention: cited ids no tool returned: {invented}")

    # case_opened
    if scenario.expect_case and not outcome.referral:
        outcome.failures.append("case_opened: no case number for a request it could not serve")

    lowered = outcome.answer.lower()
    outcome.honest = any(p in lowered for p in scenario.honest_phrases)
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=str, default=None, help="comma-separated fault names")
    parser.add_argument("--gate", action="store_true", help="exit 1 when a check fails")
    args = parser.parse_args()

    if not os.environ.get("FAULT_INJECTION") and not faults.settings.fault_injection:
        raise SystemExit(
            "Fault injection is disabled. Run with FAULT_INJECTION=true — and never on a "
            "deployed instance."
        )

    wanted = {s.strip() for s in args.only.split(",")} if args.only else None
    scenarios = [s for s in SCENARIOS if wanted is None or s.fault in wanted or s.id in wanted]

    with get_sessionmaker()() as session:
        by_name = {
            name: sid
            for sid, name in session.execute(
                select(Student.id, User.full_name).join(User, User.id == Student.user_id)
            ).all()
        }

        outcomes = []
        for i, scenario in enumerate(scenarios, 1):
            print(f"  [{i}/{len(scenarios)}] {scenario.id} {scenario.fault} — {scenario.what_breaks}")
            outcome = run_scenario(session, scenario, by_name)
            outcomes.append(outcome)
            mark = "ok  " if outcome.passed else "FAIL"
            print(
                f"        {mark} decision={outcome.decision} confidence={outcome.confidence} "
                f"modes={outcome.observed_modes or '-'} referred={(outcome.referral or {}).get('office') or '-'} "
                f"calls={outcome.tool_calls} owned_it={'yes' if outcome.honest else 'no'}"
            )
            for failure in outcome.failures:
                print(f"        !! {failure}")

    # Coverage is measured over the whole audit log, not just this run.
    #
    # The question the metric answers is "has this degraded path ever executed and been
    # looked at", and the durable record of that is ai_interactions — the same table the
    # trajectory eval reads. Scoring only the current invocation would reset the number to
    # zero every time the probe is narrowed with --only, which is precisely when someone is
    # iterating and most likely to misread it.
    with get_sessionmaker()() as session:
        observed = {
            mode
            for row in session.scalars(select(AiInteraction)).all()
            for mode in (row.degraded_modes or [])
        }
    covered = []
    for declared in DECLARED_MODES:
        if declared.endswith(":*"):
            hit = any(m.startswith(declared[:-1]) for m in observed)
        else:
            hit = declared in observed
        covered.append((declared, hit))

    passed = sum(1 for o in outcomes if o.passed)
    coverage = sum(1 for _, hit in covered if hit) / len(covered)

    print(f"\n  scenarios passed {passed}/{len(outcomes)}")
    print(f"  degradation coverage {coverage:.2f} — declared modes ever executed in an audited turn:")
    for declared, hit in covered:
        print(f"      {'x' if hit else ' '} {declared}")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    payload = {
        "run": stamp,
        "scenarios": [
            {
                "id": o.scenario.id,
                "fault": o.scenario.fault,
                "question": o.scenario.question,
                "what_breaks": o.scenario.what_breaks,
                "passed": o.passed,
                "failures": o.failures,
                "decision": o.decision,
                "confidence": o.confidence,
                "degraded_modes": o.observed_modes,
                "referral": o.referral,
                "tool_calls": o.tool_calls,
                "owned_it_in_words": o.honest,
                "answer": o.answer,
            }
            for o in outcomes
        ],
        "passed": passed,
        "total": len(outcomes),
        "degradation_coverage": round(coverage, 4),
    }
    path = RESULTS_DIR / f"faults-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  report: {path}")

    if args.gate and passed != len(outcomes):
        sys.exit(1)


if __name__ == "__main__":
    main()
