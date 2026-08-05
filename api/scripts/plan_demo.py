"""Run the planning engine against the real encoded MASY rules.

    .venv/Scripts/python -m scripts.plan_demo

Three scenarios chosen because each is a case a credit total gets wrong. Prints what a
student would be told, so the output can be read for tone as well as correctness — a
verdict that is right and unusable is not finished.
"""

from app.db.session import get_sessionmaker
from app.planning.loader import load_program_rules
from app.planning.rules import evaluate_plan
from app.planning.types import CourseState, StatedCourse, Verdict

PROGRAM = "MASY-MS-REAL"

MARK = {
    Verdict.satisfied: "OK ",
    Verdict.conditional: "IF ",
    Verdict.unverifiable: "?  ",
    Verdict.not_satisfied: "NO ",
}

SCENARIOS = [
    (
        "Spread across two concentrations — 6 credits, neither complete",
        [
            ("MASY1-GC 1015", "completed"), ("MASY1-GC 1115", "completed"),
            ("MASY1-GC 1215", "completed"), ("MASY1-GC 1315", "completed"),
            ("MASY1-GC 2000", "completed"),  # Business Analytics
            ("MASY1-GC 2200", "completed"),  # Risk Analytics
        ],
        False,
    ),
    (
        "Planning a course whose prerequisite is still in progress",
        [
            ("MASY1-GC 1015", "completed"), ("MASY1-GC 1500", "completed"),
            ("MASY1-GC 2000", "in_progress"),
            ("MASY1-GC 2100", "planned"),  # requires 2000
        ],
        False,
    ),
    (
        "Cross-school elective the catalog cannot place",
        [
            ("MASY1-GC 1015", "completed"), ("MASY1-GC 1115", "completed"),
            ("MASY1-GC 1215", "completed"), ("MASY1-GC 1315", "completed"),
            ("MASY1-GC 1500", "completed"), ("MASY1-GC 1600", "completed"),
            ("MASY1-GC 1700", "completed"), ("MASY1-GC 1800", "completed"),
            ("MASY1-GC 2400", "completed"), ("MASY1-GC 2500", "completed"),
            ("MKTG-GB 2350", "planned"),  # a Stern course
        ],
        True,
    ),
]


def main() -> None:
    with get_sessionmaker()() as session:
        program = load_program_rules(session, PROGRAM)

    print(f"{program.name} — {program.total_credits} credits")
    print(f"rules verified {program.verified_on} · {program.source_url}\n")

    for title, courses, what_if in SCENARIOS:
        stated = [
            StatedCourse(code=code, state=CourseState(state)) for code, state in courses
        ]
        result = evaluate_plan(program, stated, include_planned=what_if)

        print("=" * 92)
        print(f"{title}{'   [what-if: counting planned]' if what_if else ''}")
        print("=" * 92)
        print(
            f"  credits — completed {result.credits_completed}, "
            f"in progress {result.credits_in_progress}, "
            f"planned {result.credits_planned}, required {result.credits_required}"
        )
        print(f"  verdicts — {result.summary_counts()}\n")
        for finding in result.findings:
            print(f"  {MARK[finding.verdict]} {finding.summary}")
            print(f"      {finding.detail}")
            if finding.next_step:
                print(f"      -> {finding.next_step}")
            if finding.check_in_albert:
                print("      -> confirm in Albert")
        print()


if __name__ == "__main__":
    main()
