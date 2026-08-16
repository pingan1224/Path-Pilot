"""Read and write a user's self-reported record, and plan against it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, ProfileCourse, Program, Student, User
from app.planning.loader import ProgramNotEncodedError, load_program_rules
from app.planning.rules import evaluate_plan
from app.planning.types import CourseState, PlanResult, StatedCourse
from app.services.retrieval import SCHOOL_TO_CORPUS_SLUG, RetrievalScope


class _Unset:
    """"The caller said nothing", which is not the same as "the caller said None"."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"


UNSET = _Unset()
Omissible = str | None | _Unset

# Planning is only offered for programs whose requirements have been hand-encoded and
# validated. Everyone else gets policy answers, which is a smaller promise honestly kept.
#
# A set rather than the single constant this used to be. Encoding a program is hand work
# (see ingest/requirements.py on why a parser is not acceptable here), so this list grows
# one validated program at a time and membership is the gate for degree-audit features.
ENCODED_PROGRAMS: frozenset[str] = frozenset({
    "MASY-MS-REAL", "MSFP-MS-REAL", "GSCC-MS-REAL",
    "ENTR-MS-REAL", "MSEM-MS-REAL", "ECOC-MS-REAL", "EMSC-MS-REAL",
    "GLOB-MS-REAL", "GLSP-MS-REAL", "MSPM-MS-REAL", "HCAT-MS-REAL",
    "PWRT-MS-REAL", "HRCM-MS-REAL", "TRAN-MS-REAL", "TCSB-MS-REAL",
    "TCTM-MS-REAL", "TCHS-MS-REAL", "INTG-MS-REAL", "PUBB-MS-REAL",
    "PRCC-MS-REAL", "REAL-MS-REAL", "DEVE-MS-REAL",
})

# How old a self-reported record gets before the UI nudges. Not a staleness claim about
# authority — the data was never authoritative — just a prompt that plans drift.
PROFILE_STALE_AFTER_DAYS = 120


# Bulletin degree pages live at .../programs/<slug>/, and `Document.program_slug` is
# derived from the same shape (see ingest/load.py). Matching on it is how a page written
# for this student's own degree is told from one written for a sibling degree.
_PROGRAM_PATH = re.compile(r"/programs/([^/]+)/?$")


def program_page_slug(catalog_url: str | None) -> str | None:
    if not catalog_url:
        return None
    match = _PROGRAM_PATH.search(catalog_url.split("?")[0])
    return match.group(1) if match else None


class ProgramNotStatedError(LookupError):
    """Raised when a user has told us nothing about which program they are studying.

    Distinct from ProgramNotEncodedError, and the distinction is what the student gets
    told: "we do not support your program yet" is a statement about this product, while
    "you have not said what you are studying" is a thing they can fix in one step.
    """


@dataclass
class UserProgram:
    """Which program a user is in, and what this product can do about it."""

    code: str
    name: str
    school: str
    level: str
    is_encoded: bool
    # The school as the ingested corpus names it, resolved once here so no caller has to
    # know the mapping. None when this school has no ingested policies — which must read
    # as "no scope signal", never as a match.
    corpus_slug: str | None

    # How the ingested corpus slugs this program's own bulletin page, taken from the URL
    # the row already carries. None for a program with no ingested page.
    page_slug: str | None

    @property
    def scope(self) -> RetrievalScope:
        return RetrievalScope(
            school=self.corpus_slug, level=self.level, program_slug=self.page_slug
        )


def program_for_user(session: Session, user_id: int) -> UserProgram:
    """Resolve a user's program from whichever record carries it.

    Two paths, because there are two kinds of account. A demo account is a seeded fixture
    whose program hangs off its `Student` row; a real account has no Student at all — that
    is the entire reason live mode exists — and states its program on `users` directly.

    Everything that used to default to one hardcoded program code goes through here, so a
    student is planned against their own requirements or told plainly that this product
    cannot plan for them. There is deliberately no fallback to a default program: quietly
    auditing someone against a degree they are not enrolled in produces a confident,
    correctly-cited answer to a question nobody asked.
    """
    user = session.get(User, user_id)
    if user is None:
        raise ProgramNotStatedError(f"No user with id {user_id!r}.")

    program: Program | None = user.program
    if program is None:
        student = session.scalars(
            select(Student).where(Student.user_id == user_id)
        ).first()
        program = student.program if student is not None else None

    if program is None:
        raise ProgramNotStatedError(
            "This account has not said which program it is studying, so requirements "
            "cannot be applied. Policy questions can still be answered."
        )

    return UserProgram(
        code=program.code,
        name=program.name,
        school=program.school,
        level=program.level,
        is_encoded=program.code in ENCODED_PROGRAMS,
        corpus_slug=SCHOOL_TO_CORPUS_SLUG.get(program.school),
        page_slug=program_page_slug(program.catalog_url),
    )


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
    term: Omissible = UNSET,
    grade: Omissible = UNSET,
) -> ProfileEntry:
    """Create or update one self-reported course.

    An omitted `term` or `grade` means "leave it alone"; passing None means "clear it".
    They used to be assigned unconditionally, which made every partial update a silent
    delete: the planner's state and grade controls post only the code, the state and the
    grade, so changing either one wiped the term a transcript import had filled in. The
    student saw a course quietly lose the semester they never edited.
    """
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
    if term is not UNSET:
        row.term = term or None
    # A grade only means anything for something finished. Keeping one on an in-progress or
    # planned course would let a stale value silently satisfy a minimum-grade prerequisite
    # later — so leaving `completed` clears it even when the caller sent no grade at all.
    if state is not CourseState.completed:
        row.grade = None
    elif grade is not UNSET:
        row.grade = grade or None
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
    program_code: str | None = None,
    include_planned: bool = False,
    extra_courses: list[StatedCourse] | None = None,
) -> tuple[PlanResult, dict]:
    """Evaluate a user's stated record, optionally with hypothetical additions.

    `extra_courses` powers the what-if flow without persisting anything: a student can ask
    "what if I took this next term" and get an answer without committing to it.

    `program_code` defaulted to one hardcoded program until 2026-08-11, which meant every
    real user was audited against Management & Analytics MS whether or not they were in it.
    It now resolves from the user, and an explicit code is only for callers that already
    know one (a mission stores the program it was opened for).
    """
    if program_code is None:
        program_code = program_for_user(session, user_id).code
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
    "ENCODED_PROGRAMS",
    "ProfileEntry",
    "ProgramNotEncodedError",
    "ProgramNotStatedError",
    "UserProgram",
    "list_profile",
    "plan_for_user",
    "program_for_user",
    "remove_course",
    "upsert_course",
]
