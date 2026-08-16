"""What a partial update to a self-reported course is allowed to change.

The record is the student's own claim and nothing re-derives it, so a field this layer
drops is simply gone — there is no transcript to read it back from. That made the write
path's "assign everything, every time" shape a silent delete: the planner's state and
grade controls post only the code, the state and the grade, so touching either one wiped
the term a transcript import had filled in, on a screen that never showed the term.

So the contract these pin is: an omitted field is unchanged, an explicit null clears, and
the one field allowed to change without being mentioned is a grade whose course stopped
being finished — because a stale grade left behind on an in-progress course can satisfy a
minimum-grade prerequisite later.
"""

import pytest
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import ProfileCourse, User
from app.planning.types import CourseState
from app.services.profile import UNSET, upsert_course

PROBE_EMAIL = "live.probe@pathpilot.example.edu"
CODE = "MASY1-GC 9993"


def _db_available() -> bool:
    try:
        with get_sessionmaker()() as session:
            session.scalar(select(User.id).limit(1))
        return True
    except Exception:  # noqa: BLE001 — the suite must skip, not fail, without a database
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="needs the seeded dev database"
)


@pytest.fixture
def user_id():
    """A probe user, with the test's scratch course removed either side.

    A code no catalogue uses, so nothing else in the suite reads it and a leaked row
    cannot change another test's plan.
    """
    with get_sessionmaker()() as session:
        uid = session.scalar(select(User.id).where(User.email == PROBE_EMAIL))
        if uid is None:
            pytest.skip("live probe account is not seeded")
        _delete(session, uid)
    try:
        yield uid
    finally:
        with get_sessionmaker()() as session:
            _delete(session, uid)


def _delete(session, uid: int) -> None:
    row = session.scalars(
        select(ProfileCourse).where(
            ProfileCourse.user_id == uid, ProfileCourse.course_code == CODE
        )
    ).first()
    if row is not None:
        session.delete(row)
        session.commit()


def _read(uid: int) -> ProfileCourse:
    with get_sessionmaker()() as session:
        return session.scalars(
            select(ProfileCourse).where(
                ProfileCourse.user_id == uid, ProfileCourse.course_code == CODE
            )
        ).one()


def test_an_omitted_term_survives_a_state_change(user_id):
    """The planner's own payload, replayed. This is the bug that shipped."""
    with get_sessionmaker()() as session:
        upsert_course(
            session,
            user_id,
            course_code=CODE,
            state=CourseState.completed,
            term="Fall 2024",
            grade="A",
        )
        # Exactly what the state <select> sends: no term key at all.
        upsert_course(
            session,
            user_id,
            course_code=CODE,
            state=CourseState.completed,
            grade="A-",
        )

    row = _read(user_id)
    assert row.term == "Fall 2024"
    assert row.grade == "A-"


def test_an_explicit_none_still_clears_the_term(user_id):
    """"Unchanged" must not cost the caller the ability to clear a field."""
    with get_sessionmaker()() as session:
        upsert_course(
            session,
            user_id,
            course_code=CODE,
            state=CourseState.completed,
            term="Fall 2024",
        )
        upsert_course(
            session,
            user_id,
            course_code=CODE,
            state=CourseState.completed,
            term=None,
        )

    assert _read(user_id).term is None


def test_leaving_completed_clears_the_grade_even_when_none_is_sent(user_id):
    """The one field that changes without being mentioned, and why.

    A grade kept on a course the student has moved back to in-progress would go on
    satisfying a minimum-grade prerequisite for a course they have not finished.
    """
    with get_sessionmaker()() as session:
        upsert_course(
            session,
            user_id,
            course_code=CODE,
            state=CourseState.completed,
            term="Fall 2024",
            grade="A",
        )
        upsert_course(
            session,
            user_id,
            course_code=CODE,
            state=CourseState.in_progress,
            term="Spring 2025",
        )

    row = _read(user_id)
    assert row.grade is None
    assert row.term == "Spring 2025"


def test_a_new_row_omitting_everything_stores_nothing_invented(user_id):
    with get_sessionmaker()() as session:
        upsert_course(
            session, user_id, course_code=CODE, state=CourseState.planned
        )

    row = _read(user_id)
    assert row.term is None
    assert row.grade is None


def test_unset_is_not_none(user_id):
    """The sentinel has to be distinguishable, or the whole contract collapses back."""
    assert UNSET is not None
    assert bool(UNSET) is True
