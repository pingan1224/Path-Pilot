"""Mission step engine tests.

The engine's whole claim is that a mission's progress is *derived*, so these tests are
written as: here are the facts, here is the state that must follow. No database, no
fixtures to reset, every branch reachable from a literal.

Weighted towards the two ways a task tracker lies. It can say a step is done when the facts
do not support it — which here would tell a student they are ready to register when they are
not. Or it can keep an acknowledgement alive across a change that invalidated it, so a
review of last week's plan silently vouches for this week's.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.missions.steps import compute_state, unverifiable_for_handoff
from app.missions.types import (
    STEP_ORDER,
    AcceptedRisk,
    Candidate,
    CandidateState,
    MissionFacts,
    StepId,
    StepState,
)
from app.planning.types import CourseState, Finding, StatedCourse, Verdict

T0 = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
LATER = T0 + timedelta(days=1)


def course(code, state=CourseState.completed, grade=None):
    return StatedCourse(code=code, state=state, grade=grade)


def candidate(code, state=CandidateState.confirmed, by="student", at=T0):
    return Candidate(
        course_code=code,
        state=state,
        proposed_by=by,
        created_at=at,
        decided_at=at if state is not CandidateState.proposed else None,
    )


def blocker(key, subject, summary="Prerequisite missing: X"):
    return Finding(
        verdict=Verdict.not_satisfied,
        key=key,
        subject=subject,
        summary=summary,
        detail="detail",
    )


def degree_gap(key="requirement:Electives", summary="Electives: 3 credit(s) short"):
    return Finding(
        verdict=Verdict.not_satisfied, key=key, summary=summary, detail="detail"
    )


def facts(**overrides) -> MissionFacts:
    base = {
        "term": "Fall 2026",
        "stated_courses": (),
        "candidates": (),
        "findings": (),
    }
    return MissionFacts(**{**base, **overrides})


# --------------------------------------------------------------------------------------
# The step sequence
# --------------------------------------------------------------------------------------


def test_an_empty_mission_starts_at_the_profile_step():
    state = compute_state(facts())
    assert state.current is StepId.profile
    assert state.step(StepId.profile).state is StepState.active
    assert not state.complete


def test_everything_after_the_active_step_is_blocked_not_pending():
    state = compute_state(facts())
    later = [s for s in state.steps if s.id is not StepId.profile]
    assert all(s.state is StepState.blocked for s in later)


def test_entering_a_course_completes_the_profile_step_and_moves_on():
    state = compute_state(facts(stated_courses=(course("A"),)))
    assert state.step(StepId.profile).state is StepState.done
    assert state.current is StepId.gaps


def test_acknowledging_gaps_moves_to_choosing_courses():
    state = compute_state(
        facts(stated_courses=(course("A"),), acknowledged_gaps_at=T0)
    )
    assert state.current is StepId.candidates


def test_a_confirmed_candidate_with_no_blockers_moves_to_the_handoff():
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B"),),
        )
    )
    assert state.step(StepId.candidates).state is StepState.done
    assert state.step(StepId.open_items).state is StepState.done
    assert state.current is StepId.handoff


def test_the_mission_completes_when_the_handoff_is_produced():
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B"),),
            handoff_recorded_at=LATER,
            last_material_change_at=T0,
        )
    )
    assert state.complete
    assert state.current is None
    assert state.done_count == len(STEP_ORDER)


# --------------------------------------------------------------------------------------
# Proposals are not decisions — the boundary the agent cannot cross
# --------------------------------------------------------------------------------------


def test_an_ai_proposal_does_not_complete_the_candidates_step():
    """The assistant suggesting three courses is not the student having chosen any."""
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(
                candidate("B", CandidateState.proposed, by="ai"),
                candidate("C", CandidateState.proposed, by="ai"),
                candidate("D", CandidateState.proposed, by="ai"),
            ),
        )
    )
    assert state.current is StepId.candidates
    assert state.step(StepId.candidates).state is StepState.active


def test_proposals_are_named_in_the_step_note_so_they_do_not_read_as_progress():
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B", CandidateState.proposed, by="ai"),),
        )
    )
    note = state.step(StepId.candidates).note
    assert note and "not counted until you confirm" in note


def test_a_declined_candidate_does_not_count_either():
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B", CandidateState.declined),),
        )
    )
    assert state.current is StepId.candidates


# --------------------------------------------------------------------------------------
# The termination condition
# --------------------------------------------------------------------------------------


def test_a_blocker_on_a_chosen_course_holds_the_mission_open():
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B"),),
            findings=(blocker("prereq:B:A2", "B"),),
        )
    )
    assert state.current is StepId.open_items
    assert [f.key for f in state.open_blockers] == ["prereq:B:A2"]


def test_accepting_the_blocker_by_name_releases_the_step():
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B"),),
            findings=(blocker("prereq:B:A2", "B"),),
            accepted_risks=(
                AcceptedRisk(
                    finding_key="prereq:B:A2",
                    accepted_summary="Prerequisite missing: X",
                    accepted_at=T0,
                ),
            ),
        )
    )
    assert state.open_blockers == ()
    assert state.step(StepId.open_items).state is StepState.done


def test_accepting_a_different_finding_does_not_release_the_blocker():
    """Acceptance is by key. A blanket "I accept the risks" is not expressible here, which
    is the point — it would be a signature on something unread."""
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B"),),
            findings=(blocker("prereq:B:A2", "B"),),
            accepted_risks=(
                AcceptedRisk(
                    finding_key="prereq:C:C1", accepted_summary="other", accepted_at=T0
                ),
            ),
        )
    )
    assert len(state.open_blockers) == 1


def test_a_blocker_on_a_course_they_did_not_choose_is_not_a_blocker():
    """A prerequisite problem on a course sitting in the profile as 'planned' someday is
    not a reason they cannot register for the courses they actually picked."""
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B"),),
            findings=(blocker("prereq:Z:A2", "Z"),),
        )
    )
    assert state.open_blockers == ()
    assert state.current is StepId.handoff


def test_a_degree_gap_never_blocks_a_registration_mission():
    """Otherwise the mission is unfinishable for anyone who has not already graduated."""
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B"),),
            findings=(degree_gap(),),
        )
    )
    assert state.open_blockers == ()
    assert [f.key for f in state.degree_findings] == ["requirement:Electives"]
    assert state.current is StepId.handoff


def test_open_items_cannot_be_done_before_a_course_is_chosen():
    """Vacuously-satisfied steps are how a progress bar reaches the end without anything
    having happened."""
    state = compute_state(
        facts(stated_courses=(course("A"),), acknowledged_gaps_at=T0)
    )
    assert state.step(StepId.open_items).state is not StepState.done


# --------------------------------------------------------------------------------------
# Staleness — an acknowledgement must not vouch for facts it never saw
# --------------------------------------------------------------------------------------


def test_a_gap_review_that_predates_a_later_edit_is_flagged_not_revoked():
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            last_material_change_at=LATER,
        )
    )
    step = state.step(StepId.gaps)
    # They did review it, so re-opening would be wrong; they reviewed something older, so
    # saying nothing would be worse.
    assert step.state is StepState.done
    assert step.note and "out of date" in step.note


def test_a_handoff_that_predates_a_later_change_reopens_the_step():
    """Stronger than a note, because this document gets sent to a human who acts on it."""
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B"),),
            handoff_recorded_at=T0,
            last_material_change_at=LATER,
        )
    )
    assert state.step(StepId.handoff).state is StepState.active
    assert not state.complete
    assert state.step(StepId.handoff).note


def test_an_accepted_risk_that_now_reads_worse_is_surfaced():
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B"),),
            findings=(blocker("prereq:B:A2", "B", summary="Prerequisite missing: A2, A3"),),
            accepted_risks=(
                AcceptedRisk(
                    finding_key="prereq:B:A2",
                    accepted_summary="Prerequisite missing: A2",
                    accepted_at=T0,
                ),
            ),
        )
    )
    # Still accepted — it is the same requirement — but the change is not swallowed.
    assert state.open_blockers == ()
    assert [r.finding_key for r in state.stale_acceptances] == ["prereq:B:A2"]


def test_an_acceptance_matching_the_current_wording_is_not_stale():
    state = compute_state(
        facts(
            stated_courses=(course("A"),),
            acknowledged_gaps_at=T0,
            candidates=(candidate("B"),),
            findings=(blocker("prereq:B:A2", "B", summary="Prerequisite missing: A2"),),
            accepted_risks=(
                AcceptedRisk(
                    finding_key="prereq:B:A2",
                    accepted_summary="Prerequisite missing: A2",
                    accepted_at=T0,
                ),
            ),
        )
    )
    assert state.stale_acceptances == ()


# --------------------------------------------------------------------------------------
# Determinism and the handoff contents
# --------------------------------------------------------------------------------------


def test_the_same_facts_always_give_the_same_state():
    """A derived state that varies between reads is a stored state with extra steps."""
    given = facts(
        stated_courses=(course("A"), course("B", CourseState.in_progress)),
        acknowledged_gaps_at=T0,
        candidates=(candidate("C"), candidate("D", CandidateState.proposed, by="ai")),
        findings=(blocker("prereq:C:A2", "C"), degree_gap()),
    )
    first, second = compute_state(given), compute_state(given)
    assert first == second


def test_every_step_states_a_criterion_and_an_unfinished_one_states_the_next_action():
    state = compute_state(facts())
    for step in state.steps:
        assert step.criterion
        if step.state is not StepState.done:
            assert step.what_now, f"{step.id} gives the student nothing to do"


def test_the_handoff_collects_conditional_and_unverifiable_findings_including_degree_level():
    conditional = Finding(
        verdict=Verdict.conditional, key="prereq:B:A2", subject="B",
        summary="Holds if you pass A2", detail="d",
    )
    unverifiable_degree = Finding(
        verdict=Verdict.unverifiable, key="requirement:Electives",
        summary="Elective choice cannot be confirmed", detail="d",
    )
    given = facts(
        stated_courses=(course("A"),),
        candidates=(candidate("B"),),
        findings=(conditional, unverifiable_degree, blocker("prereq:C:C1", "C")),
    )
    keys = {f.key for f in unverifiable_for_handoff(given)}
    # The degree-level one is included even though it is not about the chosen course: it is
    # exactly what the advisor conversation is for.
    assert keys == {"prereq:B:A2", "requirement:Electives"}


@pytest.mark.parametrize("step_id", list(StepId))
def test_no_step_is_ever_done_on_empty_facts(step_id):
    """The floor under everything: nothing is complete before anything has happened."""
    state = compute_state(facts())
    assert state.step(step_id).state is not StepState.done
