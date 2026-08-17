"""Database glue for missions: load the facts, compute the state, record what happened.

Every function here takes `user_id` and scopes by it. There is no `get_mission(mission_id)`
that trusts the id it was handed — a mission is always fetched as "this user's mission with
this id", so an id from anywhere else resolves to nothing rather than to somebody else's
plan. Same reasoning as the profile router having no user id in any path.

The other rule this module enforces: **confirming is a separate call from proposing, and
the assistant can only reach the first one.** `propose_candidates` writes rows with
`confirmed_at IS NULL`; `decide_candidate` is what sets it, and it is only called from a
student-authenticated endpoint. Nothing in the agent tool layer can reach it, because the
function it would have to call is not exposed to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.missions.handoff import build_handoff
from app.missions.steps import compute_state
from app.missions.albert import AlbertCheck, CheckKind
from app.missions.types import (
    AcceptedRisk,
    Candidate,
    CandidateState,
    MissionFacts,
    MissionState,
)
from app.models import Mission, MissionCandidate, MissionDecision
from app.planning.types import CourseState, StatedCourse
from app.planning.loader import ProgramNotEncodedError
from app.services.profile import list_profile, plan_for_user, program_for_user

ACKNOWLEDGED_GAPS = "acknowledged_gaps"
ACCEPTED_RISK = "accepted_risk"
RECORDED_HANDOFF = "recorded_handoff"
# Step six. Two kinds rather than one with a note, because the handoff has to print them
# differently — "checked in Albert on the 17th" and "skipped" are not the same statement to
# an advisor, and a nullable note is not a discriminator anyone can rely on.
ALBERT_CHECKED = "albert_checked"
ALBERT_SKIPPED = "albert_skipped"
ALBERT_KINDS = (ALBERT_CHECKED, ALBERT_SKIPPED)


class MissionNotFoundError(LookupError):
    """No such mission for this user. Deliberately indistinguishable from 'not yours'."""


def _now() -> datetime:
    return datetime.now(UTC)


def _candidate_state(row: MissionCandidate) -> CandidateState:
    if row.confirmed_at is not None:
        return CandidateState.confirmed
    if row.declined_at is not None:
        return CandidateState.declined
    return CandidateState.proposed


def get_mission(session: Session, user_id: int, mission_id: int) -> Mission:
    """The single read path. Always returns rows as the database has them.

    `populate_existing` is load-bearing, not tidiness. The sessionmaker sets
    `expire_on_commit=False`, so an instance already in the identity map keeps the
    collections it loaded earlier in the request — and by default a fresh `selectinload`
    will not overwrite an attribute that is already populated. Every route here writes and
    then re-reads to build its response, so without this the response reported the state
    from *before* the write while the database held the state after it.

    Found by the probe: withdrawing an accepted risk deleted the row and then returned a
    mission that still listed it. The failure mode is the worst one available to a task
    tracker — the student clicks, the click works, and the screen says it did not.
    """
    mission = session.scalars(
        select(Mission)
        .where(Mission.id == mission_id, Mission.user_id == user_id)
        .options(
            selectinload(Mission.candidates),
            selectinload(Mission.decisions),
        )
        .execution_options(populate_existing=True)
    ).first()
    if mission is None:
        raise MissionNotFoundError(f"No mission {mission_id} for this account.")
    return mission


def open_missions(session: Session, user_id: int) -> list[Mission]:
    return list(
        session.scalars(
            select(Mission)
            .where(Mission.user_id == user_id, Mission.closed_at.is_(None))
            .options(selectinload(Mission.candidates), selectinload(Mission.decisions))
            .order_by(Mission.created_at.desc())
        ).all()
    )


def create_mission(
    session: Session,
    user_id: int,
    *,
    term: str,
    program_code: str | None = None,
    created_by: str = "student",
) -> Mission:
    """Open (or reopen) a mission for a term.

    `created_by='ai'` is reachable from the agent tool. Opening a container is the only
    write the assistant may do beyond proposing, and it is safe for a structural reason:
    an empty mission asserts nothing about the student's plan. Note that reopening an
    existing mission never rewrites `created_by` — the fact of who first opened it is not
    the assistant's to overwrite.
    """
    term = " ".join(term.strip().split())

    # Programme before lookup, because it is half of what identifies a mission. This
    # resolution used to sit *after* the search, so "one mission per term" matched on term
    # alone and a student who had changed programme was handed back the mission they
    # opened under the old one — evaluated against its rules, and labelled on screen with
    # nothing but the term.
    if program_code is None:
        program = program_for_user(session, user_id)
        if not program.is_encoded:
            # Refuse before writing. Every step of a mission is computed from the program's
            # requirements, so a mission for a program with none is a container that can
            # never be read — `mission_state` raises on load — and the row would sit there
            # being reopened by each retry. A mission is not the place to discover that.
            raise ProgramNotEncodedError(
                f"Path Pilot has not encoded the degree requirements for {program.name}, "
                "so it cannot track a registration mission for it. Policy answers and "
                "error decoding are still available."
            )
        program_code = program.code

    existing = session.scalars(
        select(Mission).where(
            Mission.user_id == user_id,
            Mission.term == term,
            Mission.program_code == program_code,
        )
    ).first()
    if existing is not None:
        # Reopen rather than duplicate. A student coming back to a term they abandoned
        # wants their candidate list, not a clean slate that silently discards it. Scoping
        # the search by programme is what keeps the row's own `program_code` authoritative
        # — the mission is still evaluated against the programme it was opened for, which
        # is now guaranteed to be the one being asked about.
        if existing.closed_at is not None:
            existing.closed_at = None
            existing.close_reason = None
            session.commit()
        return get_mission(session, user_id, existing.id)

    mission = Mission(
        user_id=user_id, term=term, program_code=program_code, created_by=created_by
    )
    session.add(mission)
    session.commit()
    return get_mission(session, user_id, mission.id)


@dataclass(frozen=True)
class ConfirmedCandidate:
    """A course the student chose on a mission, with the mission that carries it.

    The provenance is not decoration: this course appears in the planner's totals while
    being uneditable there, and a row you cannot edit and cannot place is worse than one
    that is simply absent.
    """

    course_code: str
    term: str
    mission_id: int
    confirmed_at: datetime


def confirmed_candidates(session: Session, user_id: int) -> list[ConfirmedCandidate]:
    """Every course confirmed on an open mission, newest mission first.

    Closed missions are excluded: closing one is the student saying it is no longer what
    they are doing, and its courses should stop counting the moment they say so.
    """
    rows = session.scalars(
        select(Mission)
        .where(Mission.user_id == user_id, Mission.closed_at.is_(None))
        .options(selectinload(Mission.candidates))
        .order_by(Mission.created_at.desc())
    ).all()
    seen: set[str] = set()
    out: list[ConfirmedCandidate] = []
    for mission in rows:
        for candidate in sorted(mission.candidates, key=lambda c: c.course_code):
            if candidate.confirmed_at is None or candidate.course_code in seen:
                continue
            seen.add(candidate.course_code)
            out.append(
                ConfirmedCandidate(
                    course_code=candidate.course_code,
                    term=mission.term,
                    mission_id=mission.id,
                    confirmed_at=candidate.confirmed_at,
                )
            )
    return out


def confirmed_candidate_courses(session: Session, user_id: int) -> list[StatedCourse]:
    """Courses the student has confirmed on any open mission, as planned coursework.

    The read half of "Add to my plan". A confirmed candidate is a decision the student
    made — the same kind of fact as a course they typed into their record — so the planner
    and the sequence read it alongside the profile rather than each keeping their own idea
    of what is planned. See `services.profile.stated_record` for why this is merged on
    read instead of copied into `profile_courses`.

    Closed missions are excluded: closing one is the student saying it is no longer what
    they are doing, and its courses should stop counting the moment they say so.
    """
    return [
        StatedCourse(code=c.course_code, state=CourseState.planned, term=c.term)
        for c in confirmed_candidates(session, user_id)
    ]


def mission_id_for_term(
    session: Session, user_id: int, term: str, program_code: str
) -> int | None:
    """The id of this user's mission for a term *under a programme*, closed ones included.

    Exists so a caller can tell whether `create_mission` is about to create or to reopen.
    That distinction is invisible in its return value and matters to anything that may
    need to undo the call: reopening returns work the student already did. It takes the
    programme for the same reason `create_mission` does — matching on term alone would
    call a new mission "existing" whenever the student had one for that term under a
    programme they have left, and the deferral rollback would then decline to undo a
    container it had just created.
    """
    term = " ".join(term.strip().split())
    return session.scalar(
        select(Mission.id).where(
            Mission.user_id == user_id,
            Mission.term == term,
            Mission.program_code == program_code,
        )
    )


def discard_missions(session: Session, mission_ids: list[int]) -> int:
    """Delete missions that a single turn created and then had to take back.

    The agent loop calls this when a turn ends in a deferral: a question the assistant had
    to refuse must not leave a container behind on the student's record. Deleting rather
    than closing is deliberate — a closed mission is a thing the student did and can see
    in their history, and a refusal is not that. Nothing here was ever theirs.

    The caller is responsible for passing only ids it created this turn. `create_mission`
    is idempotent, so a mission the student already had comes back through the same call,
    and deleting one of those would destroy real work over a question they asked badly.
    Cascade takes any candidates the same turn proposed into the container.
    """
    if not mission_ids:
        return 0
    rows = session.scalars(select(Mission).where(Mission.id.in_(mission_ids))).all()
    for row in rows:
        session.delete(row)
    session.commit()
    return len(rows)


def close_mission(
    session: Session, user_id: int, mission_id: int, *, reason: str | None = None
) -> Mission:
    mission = get_mission(session, user_id, mission_id)
    mission.closed_at = _now()
    mission.close_reason = (reason or "").strip()[:200] or None
    session.commit()
    return mission


# --------------------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------------------


def add_candidate(
    session: Session,
    user_id: int,
    mission_id: int,
    *,
    course_code: str,
    proposed_by: str = "student",
    rationale: str | None = None,
    confirmed: bool = False,
) -> MissionCandidate:
    """Put a course on the mission.

    `confirmed` is only ever True from a student route: a student adding a course to their
    own plan has by definition chosen it, so making them confirm their own click would be
    ceremony. The assistant calls this with `confirmed=False` and cannot pass otherwise —
    see `app.services.agent_tools.tool_propose_mission_candidates`, whose schema has no
    such parameter.
    """
    mission = get_mission(session, user_id, mission_id)
    code = " ".join(course_code.strip().upper().split())

    row = next((c for c in mission.candidates if c.course_code == code), None)
    if row is None:
        row = MissionCandidate(
            mission_id=mission.id,
            course_code=code,
            proposed_by=proposed_by,
            rationale=rationale,
        )
        session.add(row)
    elif proposed_by == "ai":
        # Never overwrite a student's own decision with a suggestion. If they already
        # declined this course, the assistant proposing it again does not undo that.
        session.commit()
        return row
    else:
        row.declined_at = None
        row.rationale = rationale or row.rationale

    if confirmed:
        row.confirmed_at = _now()
        row.declined_at = None
    session.commit()
    return row


def decide_candidate(
    session: Session,
    user_id: int,
    mission_id: int,
    candidate_id: int,
    *,
    confirm: bool,
) -> MissionCandidate:
    """The student's yes or no. The only path to `confirmed_at`."""
    mission = get_mission(session, user_id, mission_id)
    row = next((c for c in mission.candidates if c.id == candidate_id), None)
    if row is None:
        raise MissionNotFoundError(f"No candidate {candidate_id} on this mission.")

    now = _now()
    if confirm:
        row.confirmed_at = now
        row.declined_at = None
    else:
        row.declined_at = now
        row.confirmed_at = None
    session.commit()
    return row


def remove_candidate(
    session: Session, user_id: int, mission_id: int, candidate_id: int
) -> bool:
    mission = get_mission(session, user_id, mission_id)
    row = next((c for c in mission.candidates if c.id == candidate_id), None)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


# --------------------------------------------------------------------------------------
# Decisions
# --------------------------------------------------------------------------------------


def record_decision(
    session: Session,
    user_id: int,
    mission_id: int,
    *,
    kind: str,
    finding_key: str | None = None,
    finding_summary: str | None = None,
    note: str | None = None,
) -> MissionDecision:
    mission = get_mission(session, user_id, mission_id)

    if kind in (ACKNOWLEDGED_GAPS, RECORDED_HANDOFF):
        # These are "most recently at" facts, not a log: keeping every acknowledgement
        # would make "did you review this after your last edit" a scan instead of a read.
        for existing in list(mission.decisions):
            if existing.kind == kind:
                session.delete(existing)

    row = MissionDecision(
        mission_id=mission.id,
        kind=kind,
        finding_key=finding_key,
        finding_summary=(finding_summary or None) and finding_summary[:400],
        note=(note or "").strip() or None,
    )
    session.add(row)
    session.commit()
    return row


def withdraw_albert_check(
    session: Session, user_id: int, mission_id: int, key: str
) -> bool:
    """Remove every declaration for one checklist key, checked or skipped.

    Both kinds, because a student correcting a mis-click does not know or care which one
    they recorded — and leaving the other behind would settle the item with the opposite
    meaning from the one they just withdrew.
    """
    mission = get_mission(session, user_id, mission_id)
    matches = [
        d for d in mission.decisions if d.kind in ALBERT_KINDS and d.finding_key == key
    ]
    if not matches:
        return False
    for row in matches:
        session.delete(row)
    session.commit()
    return True


def withdraw_accepted_risk(
    session: Session, user_id: int, mission_id: int, finding_key: str
) -> bool:
    mission = get_mission(session, user_id, mission_id)
    matches = [
        d
        for d in mission.decisions
        if d.kind == ACCEPTED_RISK and d.finding_key == finding_key
    ]
    if not matches:
        return False
    for row in matches:
        session.delete(row)
    session.commit()
    return True


# --------------------------------------------------------------------------------------
# Facts and state
# --------------------------------------------------------------------------------------


def build_facts(session: Session, user_id: int, mission: Mission) -> tuple[MissionFacts, dict]:
    """Assemble everything the pure engine needs, and the plan metadata for display.

    Confirmed candidates reach the planner as `planned` coursework, which is what makes
    "are these courses actually takeable" answerable by the existing rule engine rather
    than by a second implementation. They arrive through `plan_for_user`'s own read of the
    record, not from here — this function used to inject them as hypotheticals, and one
    surface merging privately is exactly how the mission page, the planner and the
    sequence ended up disagreeing about what was planned.

    `stated_courses` below stays the typed profile alone. It is the mission's report of
    what the student entered, and folding confirmed candidates into it would make the
    mission page claim they had typed courses they had only chosen.
    """
    profile = list_profile(session, user_id)
    stated_from_profile = {
        e.course_code: StatedCourse(
            code=e.course_code, state=e.state, term=e.term, grade=e.grade
        )
        for e in profile
    }

    candidates = tuple(
        Candidate(
            course_code=row.course_code,
            state=_candidate_state(row),
            proposed_by=row.proposed_by,
            rationale=row.rationale,
            created_at=row.created_at,
            decided_at=row.confirmed_at or row.declined_at,
        )
        for row in sorted(mission.candidates, key=lambda c: c.course_code)
    )

    # No `extra_courses` here any more. This function used to inject its own mission's
    # confirmed candidates as hypotheticals, which is how the mission page came to see a
    # plan the planner and the sequence did not: the merge lived here instead of in the
    # read every surface shares. `plan_for_user` now reads confirmed candidates from every
    # open mission, so this one is already included — and so are the others, which is
    # right: a course confirmed for spring is planned coursework when you are looking at
    # the autumn mission too.
    result, meta = plan_for_user(
        session,
        user_id,
        program_code=mission.program_code,
        include_planned=True,
    )

    accepted = tuple(
        AcceptedRisk(
            finding_key=d.finding_key or "",
            accepted_summary=d.finding_summary,
            accepted_at=d.decided_at,
            note=d.note,
        )
        for d in mission.decisions
        if d.kind == ACCEPTED_RISK and d.finding_key
    )
    # Declarations about Albert, keyed the same way an accepted risk is. Only the most
    # recent per key survives — re-checking seats is the student saying "as of now", and a
    # list of every time they looked would make "how old is this check" a scan.
    albert_by_key: dict[str, AlbertCheck] = {}
    for d in sorted(
        (d for d in mission.decisions if d.kind in ALBERT_KINDS and d.finding_key),
        key=lambda d: d.decided_at,
    ):
        albert_by_key[d.finding_key] = AlbertCheck(
            key=d.finding_key,
            kind=CheckKind.checked if d.kind == ALBERT_CHECKED else CheckKind.skipped,
            decided_at=d.decided_at,
        )

    acknowledged = next(
        (d.decided_at for d in mission.decisions if d.kind == ACKNOWLEDGED_GAPS), None
    )
    handoff_at = next(
        (d.decided_at for d in mission.decisions if d.kind == RECORDED_HANDOFF), None
    )

    # What counts as a material change: a thing the *student* did that could alter a
    # verdict or the plan. Two exclusions, both load-bearing.
    #
    # A pending assistant suggestion is not a change. Counting its `created_at` meant the
    # assistant could un-finish a completed mission just by suggesting a course — the
    # boundary this whole design exists to hold, breached from the one direction nobody was
    # watching. Caught by running the agent against a finished mission: three proposals and
    # it went from complete back to step 5.
    #
    # The handoff timestamp is excluded because producing a document cannot invalidate
    # itself; including it would make the last step permanently unreachable.
    stamps: list[datetime | None] = [e.updated_at for e in profile]
    for row in mission.candidates:
        if row.proposed_by == "student":
            stamps.append(row.created_at)
        # Confirming or declining is a student action whichever way it went, including
        # declining a suggestion — that is a decision about the plan.
        stamps.append(row.confirmed_at)
        stamps.append(row.declined_at)
    stamps += [d.decided_at for d in mission.decisions if d.kind == ACCEPTED_RISK]
    # Deliberately *not* included: an Albert declaration must not count as a material
    # change. It is the student reporting on the outside world, not altering their plan,
    # and counting it would make each check invalidate the ones recorded before it — the
    # last item ticked would leave every earlier one flagged as out of date.
    last_change = max((s for s in stamps if s is not None), default=None)

    facts = MissionFacts(
        term=mission.term,
        stated_courses=tuple(stated_from_profile.values()),
        candidates=candidates,
        findings=tuple(result.findings),
        accepted_risks=accepted,
        albert_checks=tuple(albert_by_key.values()),
        acknowledged_gaps_at=acknowledged,
        handoff_recorded_at=handoff_at,
        last_material_change_at=last_change,
    )
    return facts, meta


def mission_state(
    session: Session, user_id: int, mission_id: int
) -> tuple[Mission, MissionFacts, MissionState, dict]:
    mission = get_mission(session, user_id, mission_id)
    facts, meta = build_facts(session, user_id, mission)
    return mission, facts, compute_state(facts), meta


def generate_handoff(
    session: Session,
    user_id: int,
    mission_id: int,
    *,
    question: str | None = None,
    record: bool = True,
) -> tuple[str, MissionState]:
    """Produce the handoff text, and record that it was produced.

    Recording is what closes the last step, so it happens here rather than in a separate
    call the UI might forget to make. `record=False` exists for the agent tool: the
    assistant showing a student a preview has not produced the document they will send.
    """
    mission, facts, _, meta = mission_state(session, user_id, mission_id)
    text = build_handoff(
        facts,
        program_name=meta["program_name"],
        rules_verified_on=meta["rules_verified_on"],
        question=question,
    )
    if record:
        record_decision(session, user_id, mission_id, kind=RECORDED_HANDOFF)
        mission, facts, state, meta = mission_state(session, user_id, mission_id)
    else:
        state = compute_state(facts)
    return text, state


__all__ = [
    "ACCEPTED_RISK",
    "ACKNOWLEDGED_GAPS",
    "RECORDED_HANDOFF",
    "MissionNotFoundError",
    "add_candidate",
    "build_facts",
    "close_mission",
    "ConfirmedCandidate",
    "confirmed_candidate_courses",
    "confirmed_candidates",
    "create_mission",
    "decide_candidate",
    "discard_missions",
    "generate_handoff",
    "get_mission",
    "mission_id_for_term",
    "mission_state",
    "open_missions",
    "record_decision",
    "remove_candidate",
    "withdraw_accepted_risk",
]
