"""Registration missions.

Student-only, and every route resolves the mission as *this user's* mission with that id.
An id belonging to somebody else does not 403 — it 404s, because distinguishing "not yours"
from "does not exist" tells an attacker which ids are real.

The route list is where the proposal/confirmation boundary becomes visible: candidates
arrive either through `POST /candidates` (the student adding their own, confirmed by the
act of adding) or through the assistant's tool (unconfirmed), and the only thing that
confirms an unconfirmed one is `POST /candidates/{id}/decision` — a student route.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.missions import service
from app.missions.service import MissionNotFoundError
from app.missions.types import MissionFacts, MissionState
from app.models import UserRole
from app.planning.loader import ProgramNotEncodedError
from app.services.auth import Identity, require_roles

router = APIRouter(prefix="/missions", tags=["missions"])

student_only = require_roles(UserRole.student)


class MissionIn(BaseModel):
    term: str = Field(min_length=3, max_length=32)

    @field_validator("term")
    @classmethod
    def tidy(cls, value: str) -> str:
        return " ".join(value.strip().split())


class CandidateIn(BaseModel):
    course_code: str = Field(min_length=3, max_length=24)


class DecisionIn(BaseModel):
    confirm: bool


class AcceptRiskIn(BaseModel):
    finding_key: str = Field(min_length=1, max_length=200)
    # Sent back by the client so the record keeps how the finding read at the time. The
    # server could look it up, but then a stale client and the server would disagree about
    # what was on screen when the student clicked, and the screen is what they accepted.
    finding_summary: str | None = Field(default=None, max_length=400)
    note: str | None = Field(default=None, max_length=2000)


class HandoffIn(BaseModel):
    question: str | None = Field(default=None, max_length=500)


class CandidateOut(BaseModel):
    id: int
    course_code: str
    state: str
    proposed_by: str
    rationale: str | None
    created_at: datetime
    decided_at: datetime | None


class StepOut(BaseModel):
    id: str
    title: str
    criterion: str
    state: str
    what_now: str | None
    evidence: list[str]
    note: str | None


class FindingOut(BaseModel):
    key: str
    subject: str | None
    verdict: str
    summary: str
    detail: str
    next_step: str | None
    check_in_albert: bool


class AcceptedRiskOut(BaseModel):
    finding_key: str
    accepted_summary: str | None
    accepted_at: datetime
    note: str | None
    # True when the finding now reads differently than it did at acceptance.
    reads_differently_now: bool


class MissionOut(BaseModel):
    id: int
    term: str
    program_name: str
    rules_verified_on: str | None
    created_at: datetime
    closed_at: datetime | None
    complete: bool
    current_step: str | None
    steps: list[StepOut]
    candidates: list[CandidateOut]
    open_blockers: list[FindingOut]
    degree_findings: list[FindingOut]
    accepted_risks: list[AcceptedRiskOut]
    disclaimer: str = (
        "This mission tracks what you have told UAX and what the published rules say about "
        "it. UAX cannot see Albert, cannot register you, and cannot confirm a course is "
        "available. Nothing here is done until you have done it in Albert."
    )


def _finding_out(finding) -> FindingOut:
    return FindingOut(
        key=finding.key,
        subject=finding.subject,
        verdict=finding.verdict.value,
        summary=finding.summary,
        detail=finding.detail,
        next_step=finding.next_step,
        check_in_albert=finding.check_in_albert,
    )


def _mission_out(mission, facts: MissionFacts, state: MissionState, meta: dict) -> MissionOut:
    stale_keys = {r.finding_key for r in state.stale_acceptances}
    row_by_code = {c.course_code: c for c in mission.candidates}

    return MissionOut(
        id=mission.id,
        term=mission.term,
        program_name=meta["program_name"],
        rules_verified_on=meta["rules_verified_on"],
        created_at=mission.created_at,
        closed_at=mission.closed_at,
        complete=state.complete,
        current_step=state.current.value if state.current else None,
        steps=[
            StepOut(
                id=step.id.value,
                title=step.title,
                criterion=step.criterion,
                state=step.state.value,
                what_now=step.what_now,
                evidence=list(step.evidence),
                note=step.note,
            )
            for step in state.steps
        ],
        candidates=[
            CandidateOut(
                id=row_by_code[c.course_code].id,
                course_code=c.course_code,
                state=c.state.value,
                proposed_by=c.proposed_by,
                rationale=c.rationale,
                created_at=c.created_at,
                decided_at=c.decided_at,
            )
            for c in facts.candidates
            if c.course_code in row_by_code
        ],
        open_blockers=[_finding_out(f) for f in state.open_blockers],
        degree_findings=[_finding_out(f) for f in state.degree_findings],
        accepted_risks=[
            AcceptedRiskOut(
                finding_key=r.finding_key,
                accepted_summary=r.accepted_summary,
                accepted_at=r.accepted_at,
                note=r.note,
                reads_differently_now=r.finding_key in stale_keys,
            )
            for r in facts.accepted_risks
        ],
    )


def _load(session: Session, user_id: int, mission_id: int) -> MissionOut:
    try:
        mission, facts, state, meta = service.mission_state(session, user_id, mission_id)
    except MissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProgramNotEncodedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _mission_out(mission, facts, state, meta)


@router.get("", response_model=list[MissionOut])
def list_missions(
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> list[MissionOut]:
    return [
        _load(session, identity.user.id, m.id)
        for m in service.open_missions(session, identity.user.id)
    ]


@router.post("", response_model=MissionOut, status_code=201)
def post_mission(
    payload: MissionIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> MissionOut:
    mission = service.create_mission(session, identity.user.id, term=payload.term)
    return _load(session, identity.user.id, mission.id)


@router.get("/{mission_id}", response_model=MissionOut)
def get_one(
    mission_id: int,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> MissionOut:
    return _load(session, identity.user.id, mission_id)


@router.post("/{mission_id}/candidates", response_model=MissionOut)
def post_candidate(
    mission_id: int,
    payload: CandidateIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> MissionOut:
    # Confirmed on arrival: a student adding a course to their own plan has chosen it, and
    # asking them to confirm their own click would be ceremony rather than consent.
    try:
        service.add_candidate(
            session,
            identity.user.id,
            mission_id,
            course_code=payload.course_code,
            proposed_by="student",
            confirmed=True,
        )
    except MissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _load(session, identity.user.id, mission_id)


@router.post("/{mission_id}/candidates/{candidate_id}/decision", response_model=MissionOut)
def post_candidate_decision(
    mission_id: int,
    candidate_id: int,
    payload: DecisionIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> MissionOut:
    try:
        service.decide_candidate(
            session, identity.user.id, mission_id, candidate_id, confirm=payload.confirm
        )
    except MissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _load(session, identity.user.id, mission_id)


@router.delete("/{mission_id}/candidates/{candidate_id}", response_model=MissionOut)
def delete_candidate(
    mission_id: int,
    candidate_id: int,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> MissionOut:
    try:
        removed = service.remove_candidate(
            session, identity.user.id, mission_id, candidate_id
        )
    except MissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="No such candidate on this mission.")
    return _load(session, identity.user.id, mission_id)


@router.post("/{mission_id}/acknowledge-gaps", response_model=MissionOut)
def post_acknowledge(
    mission_id: int,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> MissionOut:
    try:
        service.record_decision(
            session, identity.user.id, mission_id, kind=service.ACKNOWLEDGED_GAPS
        )
    except MissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _load(session, identity.user.id, mission_id)


@router.post("/{mission_id}/accepted-risks", response_model=MissionOut)
def post_accept_risk(
    mission_id: int,
    payload: AcceptRiskIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> MissionOut:
    try:
        service.record_decision(
            session,
            identity.user.id,
            mission_id,
            kind=service.ACCEPTED_RISK,
            finding_key=payload.finding_key,
            finding_summary=payload.finding_summary,
            note=payload.note,
        )
    except MissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _load(session, identity.user.id, mission_id)


@router.delete("/{mission_id}/accepted-risks/{finding_key:path}", response_model=MissionOut)
def delete_accept_risk(
    mission_id: int,
    finding_key: str,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> MissionOut:
    try:
        withdrawn = service.withdraw_accepted_risk(
            session, identity.user.id, mission_id, finding_key
        )
    except MissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not withdrawn:
        raise HTTPException(status_code=404, detail="That risk was not accepted.")
    return _load(session, identity.user.id, mission_id)


class HandoffOut(BaseModel):
    text: str
    mission: MissionOut


@router.post("/{mission_id}/handoff", response_model=HandoffOut)
def post_handoff(
    mission_id: int,
    payload: HandoffIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> HandoffOut:
    try:
        text, _ = service.generate_handoff(
            session, identity.user.id, mission_id, question=payload.question
        )
    except MissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HandoffOut(text=text, mission=_load(session, identity.user.id, mission_id))


class CloseIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


@router.post("/{mission_id}/close", response_model=MissionOut)
def post_close(
    mission_id: int,
    payload: CloseIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> MissionOut:
    try:
        service.close_mission(
            session, identity.user.id, mission_id, reason=payload.reason
        )
    except MissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _load(session, identity.user.id, mission_id)
