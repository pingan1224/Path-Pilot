"""Computing a mission's state from its facts. Pure functions, no I/O.

Read the criteria first; they are the specification:

1. **profile** — at least one course entered. Nothing downstream means anything without it.
2. **gaps** — the student has acknowledged the degree review. Acknowledging is not
   resolving: a missing capstone is not something you fix before next term's registration,
   it is something you must have *seen*.
3. **candidates** — at least one course confirmed for the term. Assistant proposals do not
   count, however many there are.
4. **open_items** — every blocker on the confirmed candidates is either gone or accepted by
   name. This is the termination condition, and it is the reason the whole mission is
   decidable: "resolved or knowingly accepted" is checkable, where "the student is ready"
   is not.
5. **handoff** — a handoff has been produced *since the last material change*. A summary
   generated before the student added two courses no longer describes their plan, and it is
   a document they send to a human who will act on it.

Two things this file refuses to do.

It never marks a step done on the strength of someone saying so — every criterion reads
facts. And it never silently keeps an acknowledgement alive across a change that
invalidated it: where re-opening the step would be too aggressive (the student did review
their gaps, just before an edit), the step stays done and carries a note. Where the
document would be actively misleading if sent (the handoff), the step re-opens.
"""

from __future__ import annotations

from datetime import datetime

from app.missions.types import (
    STEP_ORDER,
    AcceptedRisk,
    MissionFacts,
    MissionState,
    Step,
    StepId,
    StepState,
)
from app.planning.types import Finding, Verdict


def _candidate_blockers(facts: MissionFacts) -> tuple[Finding, ...]:
    """Blocking findings attributable to a course the student actually chose.

    The `subject` filter is what keeps this list about registration. A degree-level finding
    ("Electives: 3 credits short") is blocking in the planner's sense and is not a reason
    the student cannot register for the courses in front of them; treating it as one would
    make the mission unfinishable for anybody who has not already graduated.
    """
    chosen = {c.course_code for c in facts.confirmed}
    return tuple(
        f
        for f in facts.findings
        if f.blocking and f.subject is not None and f.subject in chosen
    )


def _degree_findings(facts: MissionFacts) -> tuple[Finding, ...]:
    return tuple(f for f in facts.findings if f.subject is None)


def _open_blockers(facts: MissionFacts) -> tuple[Finding, ...]:
    accepted = facts.accepted_keys
    return tuple(f for f in _candidate_blockers(facts) if f.key not in accepted)


def _stale_acceptances(facts: MissionFacts) -> tuple[AcceptedRisk, ...]:
    """Accepted risks whose finding no longer reads the way it did when accepted.

    Not an error and not a re-opening: the acceptance still counts, because the student
    accepted that requirement and it is still that requirement. But "Electives: 3 credits
    short" becoming "Electives: 6 credits short" is a different size of problem, and
    letting the older, smaller acceptance cover it without comment would be the tool
    deciding on their behalf that the change did not matter.
    """
    current = {f.key: f for f in _candidate_blockers(facts)}
    out = []
    for risk in facts.accepted_risks:
        finding = current.get(risk.finding_key)
        if finding is None or risk.accepted_summary is None:
            continue
        if finding.summary != risk.accepted_summary:
            out.append(risk)
    return tuple(out)


def _reviewed_before_a_later_change(
    facts: MissionFacts, reviewed_at: datetime | None
) -> bool:
    return (
        reviewed_at is not None
        and facts.last_material_change_at is not None
        and facts.last_material_change_at > reviewed_at
    )


def compute_state(facts: MissionFacts) -> MissionState:
    """The mission's whole state, derived. Call this on every read."""
    open_blockers = _open_blockers(facts)
    degree = _degree_findings(facts)
    stale = _stale_acceptances(facts)

    blocker_keys = {f.key for f in _candidate_blockers(facts)}
    accepted_count = len(facts.accepted_keys & blocker_keys)

    # Each entry: (done?, criterion, what_now when not done, evidence, note)
    profile_done = len(facts.stated_courses) > 0
    gaps_done = facts.acknowledged_gaps_at is not None
    candidates_done = len(facts.confirmed) > 0
    open_items_done = candidates_done and not open_blockers
    handoff_done = facts.handoff_recorded_at is not None and not _reviewed_before_a_later_change(
        facts, facts.handoff_recorded_at
    )

    specs: dict[StepId, tuple[bool, str, str | None, tuple[str, ...], str | None]] = {
        StepId.profile: (
            profile_done,
            "At least one course entered in your record.",
            "Add the courses you have completed, are taking, and plan to take.",
            (f"{len(facts.stated_courses)} course(s) entered.",),
            None,
        ),
        StepId.gaps: (
            gaps_done,
            "You have reviewed where you stand against the published degree rules.",
            "Read the degree review below and confirm you have seen it.",
            (
                f"{len(degree)} degree-level finding(s) to review."
                if degree
                else "No degree-level findings.",
            ),
            (
                "You reviewed this before your most recent change, so it may be out of date."
                if gaps_done and _reviewed_before_a_later_change(facts, facts.acknowledged_gaps_at)
                else None
            ),
        ),
        StepId.candidates: (
            candidates_done,
            f"At least one course confirmed for {facts.term}.",
            "Choose the courses you intend to register for and confirm them.",
            (
                f"{len(facts.confirmed)} confirmed, {len(facts.proposed)} awaiting your decision.",
            ),
            (
                # Named explicitly, because an assistant suggestion sitting on screen looks
                # like progress and is not.
                f"{len(facts.proposed)} suggestion(s) from the assistant are not counted "
                "until you confirm them."
                if facts.proposed
                else None
            ),
        ),
        StepId.open_items: (
            open_items_done,
            "Every blocker on your chosen courses is either resolved or accepted by name.",
            (
                "Resolve each blocker below, or accept it explicitly as a risk you are "
                "carrying."
                if candidates_done
                else "Confirm your courses first — there is nothing to check yet."
            ),
            (
                f"{len(open_blockers)} unresolved, {accepted_count} accepted.",
            ),
            (
                f"{len(stale)} accepted risk(s) now read differently than when you accepted them."
                if stale
                else None
            ),
        ),
        StepId.handoff: (
            handoff_done,
            "A handoff summary has been produced since your last change.",
            "Generate the summary to take to your advisor.",
            (
                f"Last produced {facts.handoff_recorded_at.isoformat()}."
                if facts.handoff_recorded_at
                else "Not produced yet.",
            ),
            (
                "Your last handoff predates your most recent change, so it no longer "
                "describes your plan."
                if facts.handoff_recorded_at is not None and not handoff_done
                else None
            ),
        ),
    }

    titles = {
        StepId.profile: "Enter your record",
        StepId.gaps: "Review your degree gaps",
        StepId.candidates: f"Choose courses for {facts.term}",
        StepId.open_items: "Settle the open items",
        StepId.handoff: "Produce the advisor handoff",
    }

    # The active step is the first not-done one; everything after it is blocked. Computing
    # it by position rather than storing it is what makes a mission resumable weeks later
    # without a migration or a repair script.
    first_undone: StepId | None = next(
        (step_id for step_id in STEP_ORDER if not specs[step_id][0]), None
    )

    steps: list[Step] = []
    for step_id in STEP_ORDER:
        done, criterion, what_now, evidence, note = specs[step_id]
        if done:
            state = StepState.done
        elif step_id == first_undone:
            state = StepState.active
        else:
            state = StepState.blocked
        steps.append(
            Step(
                id=step_id,
                title=titles[step_id],
                criterion=criterion,
                state=state,
                what_now=None if done else what_now,
                evidence=evidence,
                note=note,
            )
        )

    return MissionState(
        term=facts.term,
        steps=tuple(steps),
        complete=first_undone is None,
        current=first_undone,
        open_blockers=open_blockers,
        stale_acceptances=stale,
        degree_findings=degree,
    )


def unverifiable_for_handoff(facts: MissionFacts) -> tuple[Finding, ...]:
    """What the student must take to a human: everything the engine could not settle.

    Both `conditional` and `unverifiable`, and deliberately not filtered to the chosen
    courses. A degree-level item the tool cannot check is exactly the sort of thing an
    advisor conversation exists for, and dropping it because it is not about next term is
    how it goes unasked for another semester.
    """
    return tuple(
        f
        for f in facts.findings
        if f.verdict in (Verdict.conditional, Verdict.unverifiable)
    )
