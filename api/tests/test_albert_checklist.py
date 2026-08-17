"""Step six: the Albert checklist, and the three ways it has to behave.

The step exists to close the distance between what "Mission complete" computes ("you saw
the steps and settled the risks") and what a student reads it as ("I can go and register").
It closes it the only honest way available to a product with no Albert access: by recording
that they went and looked.

Two properties carry the design, and both are here:

- **It must be completable.** A gate with no escape is not a gate, it is a wall — a student
  with no time to open Albert would be stuck on the last step forever. Skipping is a
  recorded decision, and the handoff prints it.
- **It must re-open when it stops being true.** Confirming another course means another
  seat to check. That falls out of deriving the list rather than storing it, which is why
  there is no staleness rule here to drift out of sync.

Red lines for the same feature live in `test_albert_redlines.py` and were written first.
"""

from datetime import UTC, datetime, timedelta

from app.missions.albert import (
    AlbertCheck,
    CheckKind,
    checklist,
    outstanding,
)
from app.missions.steps import compute_state
from app.missions.types import Candidate, CandidateState, MissionFacts, StepId, StepState
from app.planning.types import CourseState, StatedCourse

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
TERM = "Fall 2026"
A, B = "MASY1-GC 2100", "MASY1-GC 3010"


def confirmed(*codes):
    return tuple(
        Candidate(course_code=c, state=CandidateState.confirmed, proposed_by="student")
        for c in codes
    )


def facts(*, codes=(A,), checks=(), changed_at=None):
    """A mission whose first four steps are done, so step six is the one under test."""
    return MissionFacts(
        term=TERM,
        stated_courses=(StatedCourse(code="MASY1-GC 1000", state=CourseState.completed),),
        candidates=confirmed(*codes),
        findings=(),
        albert_checks=checks,
        acknowledged_gaps_at=NOW,
        handoff_recorded_at=NOW,
        last_material_change_at=changed_at,
    )


def all_checks(*keys, kind=CheckKind.checked, at=NOW):
    return tuple(AlbertCheck(key=k, kind=kind, decided_at=at) for k in keys)


def keys_for(*codes):
    return ("holds", f"appointment:{TERM}", *(f"seats:{c}" for c in codes))


# --------------------------------------------------------------------------------------
# The list itself
# --------------------------------------------------------------------------------------


def test_the_list_is_holds_appointment_and_one_seat_check_per_confirmed_course():
    items = checklist(term=TERM, confirmed_codes=(B, A), checks=())
    assert [i.key for i in items] == [
        "holds",
        f"appointment:{TERM}",
        f"seats:{A}",
        f"seats:{B}",  # sorted by code, so two reads of one record agree
    ]


def test_a_proposal_does_not_put_a_seat_check_on_the_list():
    """The proposal/confirmation boundary again: an assistant suggestion is not a course
    the student has chosen, so it is not something they need to go and check."""
    f = MissionFacts(
        term=TERM,
        stated_courses=(StatedCourse(code="X", state=CourseState.completed),),
        candidates=(
            Candidate(course_code=A, state=CandidateState.confirmed, proposed_by="student"),
            Candidate(course_code=B, state=CandidateState.proposed, proposed_by="ai"),
        ),
        findings=(),
    )
    state = compute_state(f)
    assert [i.key for i in state.albert_items if i.key.startswith("seats:")] == [
        f"seats:{A}"
    ]


def test_the_appointment_key_carries_the_term():
    """A mission for a later term must not inherit the earlier term's appointment check —
    the registration window is a different fact for a different term."""
    spring = checklist(term="Spring 2027", confirmed_codes=(A,), checks=())
    carried = all_checks(*keys_for(A))  # checks recorded against Fall
    still_open = outstanding(
        checklist(term="Spring 2027", confirmed_codes=(A,), checks=carried)
    )
    assert f"appointment:Spring 2027" in {i.key for i in spring}
    assert {i.key for i in still_open} == {"appointment:Spring 2027"}


# --------------------------------------------------------------------------------------
# The step
# --------------------------------------------------------------------------------------


def test_the_step_gates_completion_until_every_item_is_settled():
    state = compute_state(facts())
    assert state.step(StepId.albert_check).state is StepState.active
    assert state.complete is False
    assert state.current is StepId.albert_check


def test_checking_everything_completes_the_mission():
    state = compute_state(facts(checks=all_checks(*keys_for(A))))
    assert state.step(StepId.albert_check).state is StepState.done
    assert state.complete is True


def test_skipping_also_settles_an_item_so_the_step_can_always_be_finished():
    """The escape that keeps a gate from being a wall."""
    mixed = (
        *all_checks("holds", f"appointment:{TERM}"),
        *all_checks(f"seats:{A}", kind=CheckKind.skipped),
    )
    state = compute_state(facts(checks=mixed))
    assert state.step(StepId.albert_check).state is StepState.done
    assert state.complete is True
    evidence = state.step(StepId.albert_check).evidence[0]
    assert "2 checked" in evidence and "1 skipped" in evidence


def test_confirming_another_course_reopens_the_step():
    """The re-open the roadmap asked for, obtained by deriving the list rather than by a
    staleness rule that would have to be kept in step with it."""
    settled = all_checks(*keys_for(A))
    assert compute_state(facts(codes=(A,), checks=settled)).complete is True

    after = compute_state(facts(codes=(A, B), checks=settled))
    assert after.step(StepId.albert_check).state is StepState.active
    assert after.complete is False
    assert [i.key for i in outstanding(after.albert_items)] == [f"seats:{B}"]


def test_swapping_a_course_does_not_revoke_the_holds_check():
    """The reason this is derivation and not blanket invalidation: nothing about changing
    a course makes it untrue that the student looked at their holds."""
    settled = all_checks(*keys_for(A))
    after = compute_state(facts(codes=(B,), checks=settled))
    holds = next(i for i in after.albert_items if i.key == "holds")
    assert holds.settled
    assert [i.key for i in outstanding(after.albert_items)] == [f"seats:{B}"]


def test_the_step_waits_for_courses_before_asking_for_seat_checks():
    """With nothing confirmed there are no seat items, so without this the student could
    settle two items and be told the checking is finished before choosing anything."""
    f = MissionFacts(
        term=TERM,
        stated_courses=(StatedCourse(code="X", state=CourseState.completed),),
        candidates=(),
        findings=(),
        albert_checks=all_checks("holds", f"appointment:{TERM}"),
        acknowledged_gaps_at=NOW,
    )
    state = compute_state(f)
    assert state.step(StepId.albert_check).state is StepState.blocked
    assert state.complete is False


def test_a_check_older_than_the_last_change_is_noted_but_not_revoked():
    state = compute_state(
        facts(checks=all_checks(*keys_for(A), at=NOW), changed_at=NOW + timedelta(days=1))
    )
    step = state.step(StepId.albert_check)
    assert step.state is StepState.done, "a note must not un-complete the step"
    assert "before your most recent change" in (step.note or "")


def test_the_step_sits_before_the_handoff():
    """Order matters: the handoff lists what was checked and skipped, so producing it
    first would send an advisor a document missing the answer to their next question."""
    ids = [s.id for s in compute_state(facts()).steps]
    assert ids.index(StepId.albert_check) < ids.index(StepId.handoff)
