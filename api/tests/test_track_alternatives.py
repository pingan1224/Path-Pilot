"""Concentrations that fit but finish later.

`plan.py` has promised this comparison since it was written — "Risk Analytics fits your
deadline and Business Analytics does not is a decision the student can make and one they
cannot make from a single recommended answer" — and the code did the opposite. Tracks that
could not be sequenced were reported with their reason; tracks that *could* be sequenced
and merely lost the finish-date tiebreak were dropped on the floor along with their
schedules.

"Soonest" is this product's tiebreak, not necessarily the student's reason. A
concentration one term later may be the subject they actually want, and reporting only the
winner makes that decision for them — which is precisely what a `one_track` requirement
exists not to do.

Run against the real encoded MASY programme rather than a hand-built fixture: its four
concentrations are what the comparison is for, and a fixture with two invented tracks
would prove the code works on a shape the product never sees.
"""

import pytest
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import User
from app.planning.loader import load_program_rules
from app.sequence.plan import build_sequence
from app.sequence.terms import Term

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


def _plan(deadline=None, track=None, cap=9):
    """A student with nothing on record, so every concentration is still open to them."""
    return build_sequence(
        _rules(),
        [],
        start_term=Term.parse("Fall 2026"),
        deadline=deadline,
        max_credits_per_term=cap,
        track=track,
    )


def test_tracks_that_fit_are_reported_rather_than_dropped():
    """The bug: losing the tiebreak is not the same as not fitting."""
    plan = _plan()
    assert plan.feasible
    assert plan.chosen_track
    assert plan.alternatives, "every other concentration was discarded silently"
    assert plan.chosen_track not in {a.track for a in plan.alternatives}


def test_alternatives_come_back_in_the_order_they_were_ranked():
    """Soonest first, so the closest runner-up is the one a student reads first."""
    finishes = [a.finish_term for a in _plan().alternatives]
    assert finishes == sorted(finishes)


def test_the_summary_says_how_much_later_in_terms():
    """Terms are the unit a student thinks in; a finish date alone makes them subtract."""
    plan = _plan()
    for alternative in plan.alternatives:
        assert alternative.terms_later_than_chosen >= 0
        assert alternative.finish_term >= plan.finish_term
        # Same-length concentrations are a real outcome and read as "no cost at all".
        if alternative.finish_term == plan.finish_term:
            assert alternative.terms_later_than_chosen == 0


def test_without_a_stated_target_it_says_nothing_about_deadlines():
    """None, not True.

    Unset is a real answer, and inventing a verdict against a deadline nobody named is the
    same fabrication as inventing the deadline.
    """
    assert all(a.meets_deadline is None for a in _plan().alternatives)


def test_a_stated_target_turns_the_comparison_into_a_yes_or_no():
    """The sharpest thing this can say, and only sayable once they have said when."""
    plan = _plan()
    generous = plan.finish_term
    for _ in range(6):
        generous = generous.next()

    loose = _plan(deadline=generous)
    assert loose.feasible
    assert loose.alternatives
    assert all(a.meets_deadline is True for a in loose.alternatives)


def test_asking_for_a_track_returns_that_track_solved():
    """A summary answers "does it still fit"; this is the deep look at one of them."""
    baseline = _plan()
    wanted = baseline.alternatives[0].track

    plan = _plan(track=wanted)
    assert plan.feasible
    assert plan.chosen_track == wanted
    # The narrowed search considered one concentration, so nothing is listed against it.
    # A track is never an alternative to itself.
    assert [a.track for a in plan.alternatives] == []


def test_an_unknown_track_falls_back_to_the_full_search():
    """A stale bookmark should show the plan, not an empty screen."""
    plan = _plan(track="A Concentration That Does Not Exist")
    assert plan.feasible
    assert plan.chosen_track == _plan().chosen_track


def test_rejected_and_alternative_are_different_lists():
    """One cannot be sequenced; the other can and simply finishes later.

    Collapsing them would tell a student their second choice is impossible when it is
    merely slower — the opposite of the decision this is supposed to hand them.
    """
    # A cap tight enough that some concentrations stop fitting, so both lists have
    # something in them and the separation is actually under test.
    plan = _plan(deadline=Term.parse("Fall 2027"), cap=3)
    rejected_names = {name for name, _ in plan.rejected_tracks}
    alternative_names = {a.track for a in plan.alternatives}
    assert not (rejected_names & alternative_names)
