"""Check the assistant's live-mode behaviour against a real account.

    .venv/Scripts/python -m scripts.live_mode_probe

The claim under test is narrow and important: with no Albert access, the assistant must
never report a clear record. Silence from a system it cannot query is not evidence of
absence, and a student who reads it that way skips the check that mattered.

Uses a real account with no seeded student fixture, so the live tool surface is what the
agent actually gets. Costs a few model calls.
"""

import re

from sqlalchemy import select

from app.config import settings
from app.db.session import get_sessionmaker
from app.models import Student, User, UserRole
from app.planning.types import CourseState
from app.services.agent import run_agent
from app.services.auth import hash_password
from app.services.profile import upsert_course

LIVE_EMAIL = "live.probe@pathpilot.example.edu"

# Phrases that would each be a false statement about a system Path Pilot cannot see.
FORBIDDEN = [
    r"\bno holds?\b",
    r"\bno active holds?\b",
    r"your record is clear",
    r"nothing is blocking",
    r"you (?:are|'re) clear to register",
    r"there are no (?:holds|blockers)",
]

CASES = [
    ("Do I have any holds on my account?", {"albert_checklist"}),
    ("Why did my registration fail last week?", {"albert_checklist"}),
    ("Am I on track to graduate?", {"get_my_plan"}),
    ("What are the prerequisites for MASY1-GC 2100?", {"get_course_info", "search_policy"}),
    ("When does my registration window open?", {"albert_checklist"}),
]

results: list[tuple[bool, str, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((passed, name, detail))


def ensure_live_user(session) -> int:
    user = session.scalars(select(User).where(User.email == LIVE_EMAIL)).first()
    if user is None:
        user = User(
            email=LIVE_EMAIL,
            full_name="Live Probe",
            role=UserRole.student,
            password_hash=hash_password(settings.demo_password),
        )
        session.add(user)
        session.commit()
    # No Student row on purpose: that absence is what puts the turn in live mode.
    linked = session.scalars(select(Student).where(Student.user_id == user.id)).first()
    assert linked is None, "live probe user must have no seeded student fixture"
    return user.id


def main() -> None:
    with get_sessionmaker()() as session:
        user_id = ensure_live_user(session)
        for code, state in [
            ("MASY1-GC 1015", CourseState.completed),
            ("MASY1-GC 1115", CourseState.completed),
            ("MASY1-GC 1500", CourseState.completed),
            ("MASY1-GC 2100", CourseState.planned),
        ]:
            upsert_course(session, user_id, course_code=code, state=state)

        for question, expected_tools in CASES:
            result = run_agent(
                session,
                question=question,
                acting_role=UserRole.student,
                subject_student_id=None,
                user_id=user_id,
                mode="live",
            )
            called = {t["tool"] for t in result.tool_trace}
            answer = (result.answer or "").lower()

            print(f"\nQ: {question}")
            print(f"   tools: {sorted(called)}   decision: {result.decision.value}")
            print(f"   {result.answer[:260]}")

            check(
                f"{question[:34]!r} used an expected tool",
                bool(called & expected_tools),
                f"called {sorted(called)}, wanted one of {sorted(expected_tools)}",
            )

            hits = [p for p in FORBIDDEN if re.search(p, answer)]
            check(
                f"{question[:34]!r} claims no clear record",
                not hits,
                "clean" if not hits else f"FALSE CLAIM: {hits}",
            )

            withdrawn = called & {"get_holds", "get_registration_attempts", "get_degree_progress"}
            check(
                f"{question[:34]!r} never reached a demo-only tool",
                not withdrawn,
                "ok" if not withdrawn else f"called {sorted(withdrawn)}",
            )

            if result.case_number:
                check(
                    f"{question[:34]!r} opened no case",
                    False,
                    f"created {result.case_number} with no staff queue behind it",
                )

    width = max(len(n) for _, n, _ in results)
    print("\n" + "=" * (width + 20))
    for passed, name, detail in results:
        print(f"  [{'ok  ' if passed else 'FAIL'}] {name:<{width}}  {detail}")
    failed = [n for p, n, _ in results if not p]
    print(f"\n{len(results) - len(failed)}/{len(results)} held")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
