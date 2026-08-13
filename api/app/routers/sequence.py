"""Sequence planning: what order to take the remaining requirements in.

A GET with query parameters rather than a POST, because it computes and stores nothing —
asking twice with the same inputs gives the same answer, and there is no state to get out of
step. Student-only, and it reads the caller's own record; there is no user id in the path.

Every response carries `assumptions`. That field is not decoration: a third of the catalog
does not say when its courses run, the per-term credit cap is the student's number rather
than a published rule for this program, and an open-ended elective is a placeholder with no
prerequisites checked. A term-by-term schedule looks authoritative, so what it rests on
travels with it.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import UserRole
from app.sequence.service import sequence_for_user
from app.sequence.terms import Term, TermParseError
from app.sequence.types import CONSTRAINT_LABEL
from app.services.auth import Identity, require_roles

router = APIRouter(prefix="/sequence", tags=["sequence"])

student_only = require_roles(UserRole.student)


class PlacementOut(BaseModel):
    course_code: str
    title: str
    credits: float
    requirement: str | None
    term: str
    # "published" | "irregular" | "unstated" — what the term choice was based on.
    offering_basis: str
    offering_note: str
    # The bulletin's own words about when it runs, when there are any.
    offering_source: str | None


class TermOut(BaseModel):
    term: str
    credits: float
    courses: list[PlacementOut]


class AssumptionOut(BaseModel):
    subject: str
    statement: str
    check: str | None


class InfeasibilityOut(BaseModel):
    binding: list[str]
    binding_labels: list[str]
    explanation: str
    remedies: list[str]


class SequenceOut(BaseModel):
    feasible: bool
    program_name: str
    rules_verified_on: str | None
    start_term: str
    deadline: str | None
    max_credits_per_term: int
    credit_cap_was_assumed: bool
    chosen_track: str | None
    rejected_tracks: list[dict]
    terms: list[TermOut]
    finish_term: str | None
    terms_needed: int
    assumptions: list[AssumptionOut]
    infeasibility: InfeasibilityOut | None
    unplaceable: list[str]
    disclaimer: str = (
        "An order that satisfies the published rules, computed from what you have entered. "
        "It is not a guarantee that a section will run or that a seat will exist — Path Pilot "
        "cannot see either. Confirm every term in Albert before you rely on it."
    )


def _term_or_400(value: str | None, field: str) -> Term | None:
    if not value:
        return None
    try:
        return Term.parse(value)
    except TermParseError as exc:
        raise HTTPException(status_code=422, detail=f"{field}: {exc}") from exc


@router.get("", response_model=SequenceOut)
def get_sequence(
    start_term: str | None = Query(default=None, description='e.g. "Fall 2026"'),
    deadline: str | None = Query(default=None, description="Term you want to finish by"),
    max_credits_per_term: int | None = Query(default=None, ge=1, le=24),
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> SequenceOut:
    start = _term_or_400(start_term, "start_term")
    finish_by = _term_or_400(deadline, "deadline")
    if start and finish_by and finish_by < start:
        raise HTTPException(
            status_code=422, detail="deadline: cannot be before the starting term."
        )

    # ProgramNotEncodedError propagates to the handler in main.py, which returns 409 with
    # a `program_not_encoded` code the UI can act on. Caught here it collapsed into a
    # generic conflict, indistinguishable from "you have not said what you study".
    plan, meta = sequence_for_user(
        session,
        identity.user.id,
        start_term=start,
        deadline=finish_by,
        max_credits_per_term=max_credits_per_term,
    )

    terms_out: list[TermOut] = []
    for term, placements in plan.by_term().items():
        terms_out.append(
            TermOut(
                term=str(term),
                credits=sum(p.course.credits for p in placements),
                courses=[
                    PlacementOut(
                        course_code=p.course.code,
                        title=p.course.title,
                        credits=p.course.credits,
                        requirement=p.course.requirement,
                        term=str(p.term),
                        offering_basis=p.course.offering.basis.value,
                        offering_note=p.course.offering.describe(),
                        offering_source=p.course.offering.source_text,
                    )
                    for p in placements
                ],
            )
        )

    return SequenceOut(
        feasible=plan.feasible,
        program_name=meta["program_name"],
        rules_verified_on=meta["rules_verified_on"],
        start_term=meta["start_term"],
        deadline=meta["deadline"],
        max_credits_per_term=meta["max_credits_per_term"],
        credit_cap_was_assumed=meta["credit_cap_was_assumed"],
        chosen_track=plan.chosen_track,
        rejected_tracks=[
            {"track": name, "why": why} for name, why in plan.rejected_tracks
        ],
        terms=terms_out,
        finish_term=str(plan.finish_term) if plan.finish_term else None,
        terms_needed=len(plan.terms_used),
        assumptions=[
            AssumptionOut(subject=a.subject, statement=a.statement, check=a.check)
            for a in plan.assumptions
        ],
        infeasibility=(
            InfeasibilityOut(
                binding=[c.value for c in plan.infeasibility.binding],
                binding_labels=[
                    CONSTRAINT_LABEL[c] for c in plan.infeasibility.binding
                ],
                explanation=plan.infeasibility.explanation,
                remedies=list(plan.infeasibility.remedies),
            )
            if plan.infeasibility
            else None
        ),
        unplaceable=list(plan.unplaceable),
    )
