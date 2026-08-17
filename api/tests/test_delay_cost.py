"""What it costs to not take a course next term.

A planner that says "take these three" has told the student what and nothing about why, and
why is the only part they can check. These tests hold the properties that make the answer
arguable rather than decorative.

The one that matters most is the last: a course whose deferral costs nothing must be
reported as costing nothing. A delay cost that fires on every course is a delay cost the
student learns to ignore, and it would be trivially satisfiable by an implementation that
never re-solved at all.
"""

import pytest
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import User
from app.planning.loader import load_program_rules
from app.planning.rules import CourseRule, ProgramRules, RequirementRuleSpec
from app.planning.types import CourseState, StatedCourse
from app.sequence.delay import delay_costs
from app.sequence.service import sequence_for_user
from app.sequence.terms import Term

FALL26 = Term.parse("Fall 2026")
PROBE_EMAIL = "live.probe@pathpilot.example.edu"


def course(code, *, prereqs=(), offered=None, credits=3):
    return CourseRule(
        code=code,
        title=f"{code} title",
        credits=credits,
        prerequisite_groups=prereqs,
        typically_offered=offered,
    )


def chain_program():
    """A→B→C in a straight line, plus a free-standing D.

    The chain is the whole point: C cannot start until B is done, so deferring B pushes C
    and the finish term with it. D is attached to nothing and exists to prove the cost is
    computed rather than assumed — it is in the same first term as B and must price at zero.
    """
    return ProgramRules(
        name="Chain",
        total_credits=12,
        requirements=(RequirementRuleSpec("Core", "all_of", 12, course_codes=("A", "B", "C", "D")),),
        courses={
            "A": course("A"),
            "B": course("B", prereqs=(("A",),)),
            "C": course("C", prereqs=(("B",),)),
            "D": course("D"),
        },
    )


def held(*codes):
    return [StatedCourse(code=c, state=CourseState.completed) for c in codes]


def test_deferring_a_course_its_successor_waits_on_costs_a_term():
    """A is done, so B and D are next term and C follows. Push B and C goes with it."""
    costs = {c.code: c for c in delay_costs(chain_program(), held("A"), start_term=FALL26)}

    assert costs["B"].terms_lost == 1, costs["B"].describe()
    assert costs["B"].delays is True
    assert "Spring 2027" in costs["B"].describe()


def test_a_course_nothing_waits_on_costs_nothing():
    """The property that keeps the number meaningful. D blocks no one, so deferring it must
    price at zero — an implementation that flagged everything would pass every test above
    this one and be useless in the product."""
    costs = {c.code: c for c in delay_costs(chain_program(), held("A"), start_term=FALL26)}

    assert costs["D"].terms_lost == 0
    assert costs["D"].delays is False
    assert "can wait" in costs["D"].describe()


def test_only_next_terms_courses_are_priced():
    """C sits two terms out; pricing it would answer a question the student has not reached,
    and its answer changes every time anything before it moves."""
    codes = {c.code for c in delay_costs(chain_program(), held("A"), start_term=FALL26)}

    assert codes == {"B", "D"}


def test_a_course_that_cannot_wait_is_reported_as_breaking_the_plan():
    """With the deadline one term after the baseline finish, deferring B leaves no sequence
    at all. That is a stronger statement than any number of terms and must not be flattened
    into one."""
    program = chain_program()
    baseline = delay_costs(program, held("A"), start_term=FALL26)
    finish = baseline[0].baseline_finish

    tight = delay_costs(program, held("A"), start_term=FALL26, deadline=finish)
    by_code = {c.code: c for c in tight}

    assert by_code["B"].breaks_plan is True
    assert by_code["B"].terms_lost is None
    assert by_code["B"].delays is True
    assert "has to be next term" in by_code["B"].describe()
    # And the free-standing course still is not blamed for it.
    assert by_code["D"].breaks_plan is False


def test_the_costly_course_is_reported_first():
    """The student is choosing what to drop, so what cannot be dropped goes at the top."""
    ordered = delay_costs(chain_program(), held("A"), start_term=FALL26)
    assert [c.code for c in ordered] == ["B", "D"]


def test_no_baseline_means_no_costs_rather_than_free_courses():
    """A deadline in the past leaves no feasible plan. Reporting every course as costing
    nothing would be the worst available answer — it reads as "drop anything you like"."""
    program = chain_program()
    costs = delay_costs(program, held(), start_term=FALL26, deadline=FALL26)
    assert costs == ()


def test_a_credit_placeholder_is_not_priced():
    """An open elective has no code to register for and no prerequisites checked. Putting a
    number against it prices a course nobody has chosen."""
    program = ProgramRules(
        name="Open",
        total_credits=6,
        requirements=(
            RequirementRuleSpec("Core", "all_of", 3, course_codes=("A",)),
            RequirementRuleSpec("Electives", "credits", 3),
        ),
        courses={"A": course("A")},
    )
    codes = [c.code for c in delay_costs(program, held(), start_term=FALL26)]
    assert codes == ["A"]


# --------------------------------------------------------------------------------------
# The service boundary: which baseline the prices belong to
# --------------------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        with get_sessionmaker()() as session:
            session.scalar(select(User.id).limit(1))
            load_program_rules(session, "MASY-MS-REAL")
        return True
    except Exception:  # noqa: BLE001 — the suite must skip, not fail, without a database
        return False


needs_db = pytest.mark.skipif(
    not _db_available(), reason="needs the seeded dev database with catalog programmes"
)


@needs_db
def test_a_deferral_returns_no_prices_rather_than_the_baselines():
    """The prices belong to a board the caller has just replaced.

    Under `defer=X` every remaining course kept a price solved from the plan where X was
    still in the starting term, and the UI rendered those chips beside the deferred board.
    Same failure the no-feasible-baseline case guards against, one step along: a delay cost
    is a comparison, and the thing it compared against is not what is on screen.
    """
    with get_sessionmaker()() as session:
        uid = session.scalar(select(User.id).where(User.email == PROBE_EMAIL))
        if uid is None:
            pytest.skip("live probe account is not seeded")

        start = Term.parse("Fall 2026")
        _, baseline = sequence_for_user(
            session, uid, start_term=start, program_code="MASY-MS-REAL"
        )
        priced = [c.code for c in baseline["delay_costs"]]
        assert priced, "no baseline prices to begin with, so this proves nothing"

        _, whatif = sequence_for_user(
            session,
            uid,
            start_term=start,
            program_code="MASY-MS-REAL",
            defer=priced[0],
        )
        assert whatif["deferred"] == priced[0]
        assert whatif["delay_costs"] == ()
