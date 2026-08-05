"""The self-reported record, and planning against it.

Every endpoint here operates on the signed-in user's own profile. There is no user id in
any path or body: a student plans their own degree, and an endpoint that accepted an id
would be a way to read someone else's academic record.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import UserRole
from app.planning.loader import ProgramNotEncodedError
from app.planning.types import CourseState, Verdict
from app.services.auth import Identity, require_roles
from app.services.profile import (
    list_profile,
    plan_for_user,
    remove_course,
    upsert_course,
)
from app.planning.types import StatedCourse

router = APIRouter(prefix="/profile", tags=["profile"])

# Planning is a student-facing feature. Staff have their own scoped views and no business
# editing anyone's self-reported record.
student_only = require_roles(UserRole.student)


class CourseIn(BaseModel):
    course_code: str = Field(min_length=3, max_length=24)
    state: CourseState
    term: str | None = Field(default=None, max_length=16)
    grade: str | None = Field(default=None, max_length=4)

    @field_validator("course_code")
    @classmethod
    def normalise(cls, value: str) -> str:
        return " ".join(value.strip().upper().split())


class CourseOut(BaseModel):
    course_code: str
    state: CourseState
    term: str | None
    grade: str | None
    title: str | None
    credits: int | None
    # False for courses this program's catalog does not contain — a real possibility for
    # electives, and something the UI must show rather than hide.
    in_catalog: bool
    updated_at: datetime


class CitationOut(BaseModel):
    label: str
    url: str | None
    verified_on: str | None
    quote: str | None


class FindingOut(BaseModel):
    verdict: Verdict
    summary: str
    detail: str
    next_step: str | None
    check_in_albert: bool
    citations: list[CitationOut]


class PlanOut(BaseModel):
    program_name: str
    program_source_url: str | None
    rules_verified_on: str | None
    credits_completed: int
    credits_in_progress: int
    credits_planned: int
    credits_required: int
    courses_stated: int
    profile_last_updated: str | None
    profile_age_days: int | None
    profile_is_stale: bool
    counts: dict[str, int]
    findings: list[FindingOut]
    # Restated on every response, because this is the surface a student acts on.
    disclaimer: str = (
        "Based only on what you have entered. UAX has no access to Albert and cannot see "
        "your official record. Confirm anything that affects registration in Albert."
    )


def _to_out(entry) -> CourseOut:
    return CourseOut(
        course_code=entry.course_code,
        state=entry.state,
        term=entry.term,
        grade=entry.grade,
        title=entry.title,
        credits=entry.credits,
        in_catalog=entry.in_catalog,
        updated_at=entry.updated_at,
    )


def _plan_response(result, meta) -> PlanOut:
    return PlanOut(
        program_name=meta["program_name"],
        program_source_url=meta["program_source_url"],
        rules_verified_on=meta["rules_verified_on"],
        credits_completed=result.credits_completed,
        credits_in_progress=result.credits_in_progress,
        credits_planned=result.credits_planned,
        credits_required=result.credits_required,
        courses_stated=meta["courses_stated"],
        profile_last_updated=meta["profile_last_updated"],
        profile_age_days=meta["profile_age_days"],
        profile_is_stale=meta["profile_is_stale"],
        counts=result.summary_counts(),
        findings=[
            FindingOut(
                verdict=f.verdict,
                summary=f.summary,
                detail=f.detail,
                next_step=f.next_step,
                check_in_albert=f.check_in_albert,
                citations=[
                    CitationOut(
                        label=c.label, url=c.url, verified_on=c.verified_on, quote=c.quote
                    )
                    for c in f.citations
                ],
            )
            for f in result.findings
        ],
    )


@router.get("/courses", response_model=list[CourseOut])
def get_courses(
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> list[CourseOut]:
    return [_to_out(e) for e in list_profile(session, identity.user.id)]


@router.put("/courses", response_model=CourseOut)
def put_course(
    payload: CourseIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> CourseOut:
    entry = upsert_course(
        session,
        identity.user.id,
        course_code=payload.course_code,
        state=payload.state,
        term=payload.term,
        grade=payload.grade,
    )
    return _to_out(entry)


@router.delete("/courses/{course_code:path}", status_code=204)
def delete_course(
    course_code: str,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> None:
    if not remove_course(session, identity.user.id, course_code):
        raise HTTPException(status_code=404, detail=f"{course_code} is not in your record.")


@router.get("/plan", response_model=PlanOut)
def get_plan(
    include_planned: bool = False,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> PlanOut:
    try:
        result, meta = plan_for_user(
            session, identity.user.id, include_planned=include_planned
        )
    except ProgramNotEncodedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _plan_response(result, meta)


class WhatIfIn(BaseModel):
    """Hypothetical courses, evaluated without being saved."""

    courses: list[CourseIn] = Field(min_length=1, max_length=10)


@router.post("/plan/what-if", response_model=PlanOut)
def post_what_if(
    payload: WhatIfIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> PlanOut:
    extra = [
        StatedCourse(
            code=c.course_code,
            state=c.state,
            term=c.term,
            grade=c.grade if c.state is CourseState.completed else None,
        )
        for c in payload.courses
    ]
    try:
        result, meta = plan_for_user(
            session,
            identity.user.id,
            include_planned=True,
            extra_courses=extra,
        )
    except ProgramNotEncodedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _plan_response(result, meta)
