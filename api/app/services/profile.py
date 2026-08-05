"""Read and write a user's self-reported record, and plan against it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, ProfileCourse
from app.planning.loader import ProgramNotEncodedError, load_program_rules
from app.planning.rules import evaluate_plan
from app.planning.types import CourseState, PlanResult, StatedCourse

# Planning is only offered for programs whose requirements have been hand-encoded and
# validated. Everyone else gets policy answers, which is a smaller promise honestly kept.
SUPPORTED_PROGRAM = "MASY-MS-REAL"

# How old a self-reported record gets before the UI nudges. Not a staleness claim about
# authority — the data was never authoritative — just a prompt that plans drift.
PROFILE_STALE_AFTER_DAYS = 120


@dataclass
class ProfileEntry:
    course_code: str
    state: CourseState
    term: str | None
    grade: str | None
    updated_at: datetime
    # Resolved against the loaded catalog, so the UI can show a title and flag the
    # courses this tool cannot reason about.
    title: str | None = None
    credits: int | None = None
    in_catalog: bool = False


def list_profile(session: Session, user_id: int) -> list[ProfileEntry]:
    rows = session.scalars(
        select(ProfileCourse)
        .where(ProfileCourse.user_id == user_id)
        .order_by(ProfileCourse.course_code)
    ).all()
    if not rows:
        return []

    codes = {r.course_code for r in rows}
    catalog = {
        c.code: c
        for c in session.scalars(
            select(Course).where(Course.source == "catalog", Course.code.in_(codes))
        )
    }

    return [
        ProfileEntry(
            course_code=row.course_code,
            state=row.course_state,
            term=row.term,
            grade=row.grade,
            updated_at=row.updated_at,
            title=catalog[row.course_code].title if row.course_code in catalog else None,
            credits=catalog[row.course_code].credits if row.course_code in catalog else None,
            in_catalog=row.course_code in catalog,
        )
        for row in rows
    ]


def upsert_course(
    session: Session,
    user_id: int,
    *,
    course_code: str,
    state: CourseState,
    term: str | None = None,
    grade: str | None = None,
) -> ProfileEntry:
    code = " ".join(course_code.strip().upper().split())
    row = session.scalars(
        select(ProfileCourse).where(
            ProfileCourse.user_id == user_id, ProfileCourse.course_code == code
        )
    ).first()
    if row is None:
        row = ProfileCourse(user_id=user_id, course_code=code)
        session.add(row)

    row.state = state.value
    row.term = term or None
    # A grade only means anything for something finished. Keeping one on an in-progress or
    # planned course would let a stale value silently satisfy a minimum-grade prerequisite
    # later.
    row.grade = (grade or None) if state is CourseState.completed else None
    session.commit()

    entries = [e for e in list_profile(session, user_id) if e.course_code == code]
    return entries[0]


def remove_course(session: Session, user_id: int, course_code: str) -> bool:
    code = " ".join(course_code.strip().upper().split())
    row = session.scalars(
        select(ProfileCourse).where(
            ProfileCourse.user_id == user_id, ProfileCourse.course_code == code
        )
    ).first()
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def plan_for_user(
    session: Session,
    user_id: int,
    *,
    program_code: str = SUPPORTED_PROGRAM,
    include_planned: bool = False,
    extra_courses: list[StatedCourse] | None = None,
) -> tuple[PlanResult, dict]:
    """Evaluate a user's stated record, optionally with hypothetical additions.

    `extra_courses` powers the what-if flow without persisting anything: a student can ask
    "what if I took this next term" and get an answer without committing to it.
    """
    program = load_program_rules(session, program_code)

    stated = [
        StatedCourse(
            code=entry.course_code, state=entry.state, term=entry.term, grade=entry.grade
        )
        for entry in list_profile(session, user_id)
    ]
    if extra_courses:
        # Hypotheticals win: asking "what if I took X next term" while X sits in the
        # profile as planned should evaluate the question asked.
        overridden = {c.code for c in extra_courses}
        stated = [s for s in stated if s.code not in overridden] + list(extra_courses)

    result = evaluate_plan(program, stated, include_planned=include_planned)

    oldest = min((s.term for s in stated if s.term), default=None)
    last_updated = max(
        (e.updated_at for e in list_profile(session, user_id)), default=None
    )
    age_days = (
        (datetime.now(UTC) - last_updated).days if last_updated else None
    )

    meta = {
        "program_name": program.name,
        "program_source_url": program.source_url,
        "rules_verified_on": program.verified_on,
        "courses_stated": len(stated),
        "profile_last_updated": last_updated.isoformat() if last_updated else None,
        "profile_age_days": age_days,
        "profile_is_stale": age_days is not None and age_days > PROFILE_STALE_AFTER_DAYS,
        "earliest_term": oldest,
    }
    return result, meta


__all__ = [
    "ProfileEntry",
    "ProgramNotEncodedError",
    "SUPPORTED_PROGRAM",
    "list_profile",
    "plan_for_user",
    "remove_course",
    "upsert_course",
]
