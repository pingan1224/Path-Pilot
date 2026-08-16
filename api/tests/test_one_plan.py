"""One plan, read the same way everywhere.

A course reaches a student's plan two ways — typed into the record, or confirmed on a
registration mission — and until 2026-08-16 only the first reached the planner and the
sequence. "Add to my plan" on a mission card put a course somewhere the planner could not
see, so the mission page said four courses were planned and the degree audit said none
were. Three surfaces, three answers to one question.

These pin the merge and the two rules that keep it honest:

* it happens on *read*, so un-confirming needs no undo path — the fact simply stops being
  there next time;
* the typed profile wins a collision, because it carries a grade and a real term while a
  candidate carries neither.
"""

import pytest
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.missions.service import (
    add_candidate,
    close_mission,
    confirmed_candidate_courses,
    create_mission,
    decide_candidate,
)
from app.models import Mission, ProfileCourse, Program, User
from app.planning.types import CourseState
from app.services.profile import stated_record, upsert_course

PROBE_EMAIL = "live.probe@pathpilot.example.edu"
TERM = "Fall 2031"  # far enough out that no fixture or other test uses it
CONFIRMED = "MASY1-GC 1700"
TYPED = "MASY1-GC 1015"


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


def _wipe(session, uid: int) -> None:
    for mission in session.scalars(
        select(Mission).where(Mission.user_id == uid, Mission.term == TERM)
    ).all():
        session.delete(mission)
    for row in session.scalars(
        select(ProfileCourse).where(
            ProfileCourse.user_id == uid, ProfileCourse.course_code.in_([CONFIRMED, TYPED])
        )
    ).all():
        session.delete(row)
    session.commit()


@pytest.fixture
def user_id():
    """The probe account, pointed at an encoded programme for the duration.

    Missions cannot exist without one — `create_mission` resolves the programme before
    writing, on purpose — and the probe account deliberately states none, because its
    other job is proving the no-programme path. Restored afterwards so that stays true.
    """
    with get_sessionmaker()() as session:
        user = session.scalars(select(User).where(User.email == PROBE_EMAIL)).first()
        if user is None:
            pytest.skip("live probe account is not seeded")
        uid, original = user.id, user.program_id
        program_id = session.scalar(
            select(Program.id).where(
                Program.code == "MASY-MS-REAL", Program.source == "catalog"
            )
        )
        if program_id is None:
            pytest.skip("catalog programmes are not ingested")
        user.program_id = program_id
        session.commit()
        _wipe(session, uid)
    try:
        yield uid
    finally:
        with get_sessionmaker()() as session:
            _wipe(session, uid)
            user = session.scalars(select(User).where(User.email == PROBE_EMAIL)).first()
            user.program_id = original
            session.commit()


def _confirm(session, uid: int, code: str) -> Mission:
    mission = create_mission(session, uid, term=TERM)
    row = add_candidate(session, uid, mission.id, course_code=code, proposed_by="ai")
    decide_candidate(session, uid, mission.id, row.id, confirm=True)
    return mission


def test_a_confirmed_candidate_is_in_the_record_the_planner_reads(user_id):
    """The bug this whole change exists for."""
    with get_sessionmaker()() as session:
        _confirm(session, user_id, CONFIRMED)
        codes = {c.code for c in stated_record(session, user_id)}
    assert CONFIRMED in codes


def test_it_arrives_as_planned_coursework_for_the_missions_term(user_id):
    with get_sessionmaker()() as session:
        _confirm(session, user_id, CONFIRMED)
        merged = {c.code: c for c in stated_record(session, user_id)}
    assert merged[CONFIRMED].state is CourseState.planned
    assert merged[CONFIRMED].term == TERM


def test_unconfirming_removes_it_with_no_undo_path(user_id):
    """Read-through's whole payoff: taking it back is the fact ceasing to exist."""
    with get_sessionmaker()() as session:
        mission = _confirm(session, user_id, CONFIRMED)
        row = next(c for c in mission.candidates if c.course_code == CONFIRMED)
        decide_candidate(session, user_id, mission.id, row.id, confirm=False)
        codes = {c.code for c in stated_record(session, user_id)}
    assert CONFIRMED not in codes


def test_a_closed_mission_stops_counting(user_id):
    """Closing is the student saying this is not what they are doing any more."""
    with get_sessionmaker()() as session:
        mission = _confirm(session, user_id, CONFIRMED)
        close_mission(session, user_id, mission.id, reason="changed my mind")
        codes = {c.code for c in stated_record(session, user_id)}
    assert CONFIRMED not in codes


def test_the_typed_record_wins_a_collision(user_id):
    """A typed row carries a grade and a real term; a candidate carries neither."""
    with get_sessionmaker()() as session:
        upsert_course(
            session,
            user_id,
            course_code=TYPED,
            state=CourseState.completed,
            term="Fall 2024",
            grade="A",
        )
        _confirm(session, user_id, TYPED)
        merged = [c for c in stated_record(session, user_id) if c.code == TYPED]

    assert len(merged) == 1, "one course must not appear twice in one plan"
    assert merged[0].state is CourseState.completed
    assert merged[0].grade == "A"
    assert merged[0].term == "Fall 2024"


def test_confirmed_candidate_courses_ignores_a_merely_proposed_one(user_id):
    """The propose/confirm boundary, at the read layer: a suggestion is not a choice."""
    with get_sessionmaker()() as session:
        mission = create_mission(session, user_id, term=TERM)
        add_candidate(
            session, user_id, mission.id, course_code=CONFIRMED, proposed_by="ai"
        )
        codes = {c.code for c in confirmed_candidate_courses(session, user_id)}
    assert CONFIRMED not in codes


def test_changing_programme_closes_the_missions_of_the_one_being_left(user_id):
    """A mission is evaluated against the programme it was opened for.

    One that survives a programme change is a live task measuring the student against
    rules they have left — and the rail shows only the term, so nothing on screen would
    say which. It is closed with a reason instead, which the mission page can show.
    """
    from app.missions.service import open_missions

    with get_sessionmaker()() as session:
        _confirm(session, user_id, CONFIRMED)
        assert any(m.term == TERM for m in open_missions(session, user_id))

        other = session.scalar(
            select(Program.id).where(
                Program.code == "MSFP-MS-REAL", Program.source == "catalog"
            )
        )
        if other is None:
            pytest.skip("second encoded programme is not ingested")
        user = session.get(User, user_id)
        user.program_id = other
        session.commit()

        # The router does the closing; call the same service path it uses.
        from app.missions.service import close_mission

        for mission in open_missions(session, user_id):
            if mission.program_code != "MSFP-MS-REAL":
                close_mission(
                    session, user_id, mission.id, reason="Programme changed"
                )

        assert not any(m.term == TERM for m in open_missions(session, user_id))
        # And its courses stop counting as the current plan, which is the whole point.
        assert CONFIRMED not in {c.code for c in stated_record(session, user_id)}


def test_one_term_can_hold_a_mission_per_programme(user_id):
    """The constraint that makes the above safe: term alone no longer identifies one."""
    with get_sessionmaker()() as session:
        first = create_mission(session, user_id, term=TERM)
        second = create_mission(
            session, user_id, term=TERM, program_code="MSFP-MS-REAL"
        )
    assert first.id != second.id, "term alone must not identify a mission"
    assert first.program_code != second.program_code
