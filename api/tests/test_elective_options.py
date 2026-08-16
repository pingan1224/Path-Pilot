"""Candidates for a credits requirement, and the line between listing and asserting.

The planner reports "3 of 6 credits so far" and stops, honestly: a credits requirement is
a pool, not a checklist. But *what should I take* is the product's own question, and a
shortfall with no candidates is where it goes unanswered — the student is sent to find the
courses themselves in a bulletin this tool has already read.

The whole risk here is inventing eligibility. The obvious implementation — every catalogue
course sharing the subject prefix — is a guess dressed as a list, and it is wrong in both
directions at once: it sweeps in core courses the student must take elsewhere, and it
misses the cross-programme options the bulletin explicitly allows. So these pin the
opposite property: **every candidate comes from something already encoded**, either named
by the requirement or belonging to a concentration sitting next to it.

What is deliberately *not* asserted: that any of these counts. That is the bulletin's
judgement and the advisor's. What is computed is narrower and checkable — this course
exists, you have not taken it, and its prerequisites are or are not met by your record.
"""

import pytest
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import User
from app.planning.electives import elective_options
from app.planning.loader import load_program_rules
from app.planning.types import CourseState, StatedCourse

PROGRAM = "MASY-MS-REAL"


def _rules():
    with get_sessionmaker()() as session:
        return load_program_rules(session, PROGRAM)


def _db_available() -> bool:
    try:
        with get_sessionmaker()() as session:
            session.scalar(select(User.id).limit(1))
        _rules()
        return True
    except Exception:  # noqa: BLE001 — the suite must skip, not fail, without a database
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="needs the seeded dev database with catalog programmes"
)


@pytest.fixture
def program():
    return _rules()


@pytest.fixture
def spec(program):
    return next(s for s in program.requirements if s.rule == "credits")


def _held(*codes, state=CourseState.completed):
    return [StatedCourse(code=c, state=state, term=None, grade="A") for c in codes]


def test_every_candidate_traces_to_something_encoded(program, spec):
    """No candidate is inferred from a course code.

    Each one is either named by the requirement or belongs to a concentration encoded in
    the sibling one_track requirement. A prefix match would produce a longer list and a
    less honest one.
    """
    listed = set(spec.course_codes)
    track_courses = {
        code
        for other in program.requirements
        if other.rule == "one_track" and other.tracks
        for track in other.tracks
        for code in track.course_codes
    }

    for option in elective_options(program, spec, []):
        assert option.code in listed | track_courses
        assert option.source == "listed" or option.code in track_courses


def test_courses_already_held_are_not_offered(program, spec):
    """Whatever the record says they have, in any state — planned counts as taken here,
    because suggesting a course they have already planned is noise, not help."""
    first = elective_options(program, spec, [])[0]
    after = elective_options(program, spec, _held(first.code))
    assert first.code not in {o.code for o in after}

    planned = elective_options(
        program, spec, _held(first.code, state=CourseState.planned)
    )
    assert first.code not in {o.code for o in planned}


def test_the_concentration_they_have_started_is_not_offered_as_electives(program, spec):
    """The one suggestion here that could cost a term.

    Those courses are required by the one_track requirement. Offering them as electives
    invites a student to spend an elective slot on something they must take anyway.
    """
    tracks = next(s for s in program.requirements if s.rule == "one_track").tracks
    started = tracks[0]

    options = elective_options(program, spec, _held(started.course_codes[0]))
    assert not ({o.code for o in options} & set(started.course_codes))
    # The other concentrations are still open to them, so their courses remain.
    assert any(o.source == tracks[1].name for o in options)


def test_prerequisites_are_reported_as_a_fact_not_a_filter(program, spec):
    """A course whose prerequisites are unmet stays on the list, marked.

    Dropping it would hide a course they could take next year, and dropping it silently is
    the failure this product treats as worse than an unhelpful answer. None means the
    course has no prerequisites to check — distinct from False, which is a finding.
    """
    options = elective_options(program, spec, [])
    assert any(o.prerequisites_met is False for o in options), "nothing to check here"
    assert all(o.prerequisites_met in (True, False, None) for o in options)

    blocked = next(o for o in options if o.prerequisites_met is False)
    # Meeting them flips it, which is what makes the flag worth showing at all. One course
    # from each group: the groups are ANDed, the alternatives inside one are ORed.
    needed = [group[0] for group in program.courses[blocked.code].prerequisite_groups]
    after = elective_options(program, spec, _held(*needed))
    assert next(o for o in after if o.code == blocked.code).prerequisites_met is True


def test_the_order_is_by_code_and_not_a_ranking(program, spec):
    """Any other order would read as a recommendation.

    Soonest-offered or fewest-prerequisites would both look like the product had a view on
    which elective is better, and it has none: that is a question about what the student
    wants to study.
    """
    codes = [o.code for o in elective_options(program, spec, [])]
    assert codes == sorted(codes)


def test_a_satisfied_requirement_gets_no_candidates():
    """Suggestions under a finished requirement read as "there is still something to do"."""
    from app.services.profile import elective_options_for, plan_for_user

    with get_sessionmaker()() as session:
        uid = session.scalar(select(User.id).where(User.email.like("diego%")))
        if uid is None:
            pytest.skip("demo students are not seeded")
        result, _ = plan_for_user(session, uid)
        options = elective_options_for(session, uid, result)

        satisfied = {
            f.key for f in result.findings if f.verdict.value == "satisfied"
        }
        assert not (set(options) & satisfied)


def test_no_demo_fixture_course_can_reach_a_real_students_options(program, spec):
    """Real planning must never traverse an invented course.

    The demo programme's courses are fixtures with codes of their own shape (MASY-GC), and
    a catalogue candidate carrying one would mean the two sources had been mixed.
    """
    for option in elective_options(program, spec, []):
        assert option.code in program.courses
        assert "1-GC" in option.code, f"{option.code} is not a catalogue code"


def test_a_row_says_whether_the_audit_will_count_it(program, spec):
    """The trap this list could have walked a student into.

    The rule engine counts a credits requirement from the courses the requirement lists
    and nothing else; the caveat's other allowances are prose it cannot execute. So a
    concentration course is permitted by the bulletin and will not move the total — both
    true, and a row that carried only the first would have a student add what this list
    suggested and watch the gap stay where it was.
    """
    options = elective_options(program, spec, [])
    listed = [o for o in options if o.source == "listed"]
    borrowed = [o for o in options if o.source != "listed"]

    assert listed and borrowed, "both kinds must be present or this proves nothing"
    assert all(o.counts_automatically is True for o in listed)
    assert all(o.counts_automatically is False for o in borrowed)


def test_what_the_audit_counts_matches_what_the_flag_promises(program, spec):
    """Ties the flag to the engine rather than to a comment about the engine."""
    from app.planning.rules import evaluate_plan

    options = elective_options(program, spec, [])
    baseline = evaluate_plan(program, [], include_planned=True).credits_planned

    for option in (
        next(o for o in options if o.counts_automatically),
        next(o for o in options if not o.counts_automatically),
    ):
        result = evaluate_plan(
            program, _held(option.code, state=CourseState.planned), include_planned=True
        )
        finding = next(f for f in result.findings if f.key == f"requirement:{spec.name}")
        # The requirement's own arithmetic, not the sentence describing it: "N of M
        # credits" is display text and would tie this test to wording rather than to the
        # engine it is supposed to be checking.
        counted = "0 of" not in finding.detail or finding.verdict.value == "satisfied"
        assert counted is option.counts_automatically, (
            f"{option.code} claims counts_automatically={option.counts_automatically} "
            f"but the audit says: {finding.detail[:70]}"
        )
        assert result.credits_planned > baseline, "the course reached the plan at all"
