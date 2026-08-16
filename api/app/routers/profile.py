"""The self-reported record, and planning against it.

Every endpoint here operates on the signed-in user's own profile. There is no user id in
any path or body: a student plans their own degree, and an endpoint that accepted an id
would be a way to read someone else's academic record.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import Program, UserRole
from app.planning.types import CourseState, Verdict
from app.services.auth import Identity, require_roles
from app.missions import service
from app.services.profile import (
    UNSET,
    elective_options_for,
    get_preferences,
    list_profile,
    list_record,
    plan_for_user,
    program_for_user,
    remove_course,
    set_preferences,
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
    credits: float | None
    # False for courses this program's catalog does not contain — a real possibility for
    # electives, and something the UI must show rather than hide.
    in_catalog: bool
    updated_at: datetime
    # The mission term this course was confirmed on; null when the student typed it. The
    # UI renders a set value read-only — the mission page owns it.
    from_mission: str | None = None


class CitationOut(BaseModel):
    label: str
    url: str | None
    verified_on: str | None
    quote: str | None


class FindingOut(BaseModel):
    verdict: Verdict
    # Stable across re-evaluations, so a client can carry a reference to one finding
    # (a mission's accepted risk) without holding on to its wording.
    key: str
    subject: str | None
    summary: str
    detail: str
    next_step: str | None
    check_in_albert: bool
    citations: list[CitationOut]
    # Courses that could fill this gap, on a `credits` requirement that is short. Empty
    # everywhere else. Not a recommendation and not an eligibility ruling — see
    # planning/electives.py — which is why the caveat travels in `detail` beside them.
    options: list[dict] = []


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
        "Based only on what you have entered. Path Pilot has no access to Albert and cannot see "
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
        from_mission=entry.from_mission,
    )


def _plan_response(result, meta, options_by_key: dict | None = None) -> PlanOut:
    options_by_key = options_by_key or {}
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
                options=[
                    {
                        "code": o.code,
                        "title": o.title,
                        "credits": o.credits,
                        "typically_offered": o.typically_offered,
                        "source": o.source,
                        "counts_automatically": o.counts_automatically,
                        "prerequisites_met": o.prerequisites_met,
                        "prerequisite_text": o.prerequisite_text,
                    }
                    for o in options_by_key.get(f.key, ())
                ],
                verdict=f.verdict,
                key=f.key,
                subject=f.subject,
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


class ProgramIn(BaseModel):
    program_code: str = Field(min_length=1, max_length=24)


class ProgramOut(BaseModel):
    program_code: str
    program_name: str
    level: str
    is_encoded: bool
    # What the student can expect, stated rather than left for them to discover by finding
    # a page that refuses. An unencoded program is a smaller promise honestly kept.
    capabilities: list[str]


def _program_out(program) -> ProgramOut:
    capabilities = ["policy_answers", "error_decoding", "albert_checklist"]
    if program.is_encoded:
        capabilities += ["degree_audit", "course_sequence", "registration_mission"]
    return ProgramOut(
        program_code=program.code,
        program_name=program.name,
        level=program.level,
        is_encoded=program.is_encoded,
        capabilities=capabilities,
    )


@router.get("/program", response_model=ProgramOut)
def get_program(
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> ProgramOut:
    # ProgramNotStatedError is handled globally (main.py) as a 409 with its own code, so
    # the UI can route to the picker instead of showing a generic failure.
    return _program_out(program_for_user(session, identity.user.id))


@router.put("/program", response_model=ProgramOut)
def put_program(
    payload: ProgramIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> ProgramOut:
    """Set the signed-in user's program.

    Only `source='catalog'` programs are settable. The demo program is a fixture built from
    invented courses; letting a real account select it would produce a degree audit against
    a degree that does not exist.

    No user id in the body — a student sets their own program and nobody else's, the same
    rule every other endpoint in this router follows.
    """
    program = session.scalars(
        select(Program).where(
            Program.code == payload.program_code, Program.source == "catalog"
        )
    ).first()
    if program is None:
        raise HTTPException(
            status_code=404,
            detail=f"No program with code {payload.program_code!r}.",
        )

    # Missions opened under the programme being left are closed, not carried across. A
    # mission is evaluated against the programme it was opened for, so one that survives a
    # programme change is a live task measuring the student against rules they have left —
    # and the rail shows only its term, so nothing on screen would say which. Closing is
    # recorded with a reason the mission page can show; the candidates and decisions stay
    # readable in it, they simply stop counting as the current plan.
    previous_id = identity.user.program_id
    identity.user.program_id = program.id
    session.commit()

    if previous_id is not None and previous_id != program.id:
        previous = session.get(Program, previous_id)
        if previous is not None:
            for mission in service.open_missions(session, identity.user.id):
                if mission.program_code != program.code:
                    service.close_mission(
                        session,
                        identity.user.id,
                        mission.id,
                        reason=f"Programme changed from {previous.name}",
                    )

    return _program_out(program_for_user(session, identity.user.id))


class PreferencesIn(BaseModel):
    """Every field optional twice over: absent means unchanged, null means clear.

    `model_fields_set` is what tells those apart — see put_preferences. Without it,
    saving a credit cap would silently forget the finish term, because a partial update
    would arrive indistinguishable from an explicit "I no longer have one".
    """

    target_finish_term: str | None = Field(default=None, max_length=16)
    max_credits_per_term: int | None = Field(default=None, ge=1, le=24)
    summers_ok: bool | None = None

    @field_validator("target_finish_term")
    @classmethod
    def parseable(cls, value: str | None) -> str | None:
        """A term this product can actually solve against, normalised to its own spelling.

        Rejected at the door rather than stored and discovered later. This value does not
        show up on screen the moment it is typed the way a mission's term does — it sits
        in preferences and only bites at the next solve — so a form the parser cannot read
        would fail silently, weeks after the student set it.
        """
        if value is None or not value.strip():
            return None
        from app.sequence.terms import TermParseError, Term

        try:
            return str(Term.parse(value))
        except TermParseError as exc:
            raise ValueError(str(exc)) from exc


class PreferencesOut(BaseModel):
    target_finish_term: str | None
    max_credits_per_term: int | None
    summers_ok: bool | None
    # When the student last said any of this. Intent goes stale like anything else: a
    # finish date chosen a year ago may not be the one they want now, so the UI shows the
    # date beside the value instead of presenting it as timeless.
    updated_at: datetime | None
    # Terms offerable as a target, in this product's own spelling. Supplied by the server
    # so the picker cannot produce a value the solver would reject.
    selectable_terms: list[str]


def _preferences_out(prefs, terms: list[str]) -> PreferencesOut:
    return PreferencesOut(
        target_finish_term=prefs.target_finish_term,
        max_credits_per_term=prefs.max_credits_per_term,
        summers_ok=prefs.summers_ok,
        updated_at=prefs.updated_at,
        selectable_terms=terms,
    )


def _selectable_terms(saved: str | None) -> list[str]:
    """The next twelve terms from the one a student could next register for.

    Three years is past the finish date of anyone this product can usefully plan for, and
    a longer list is a scroll rather than a choice. A saved target further out than that
    is kept in the list rather than dropped — a picker that silently cannot represent the
    stored value is how a preference gets cleared by being looked at.
    """
    from app.sequence.service import next_registerable_term
    from app.sequence.terms import parse_or_none

    terms = [str(t) for t in next_registerable_term().forward(12)]
    if saved and saved not in terms:
        terms = sorted(
            terms + [saved],
            key=lambda text: (parse_or_none(text) or next_registerable_term()),
        )
    return terms


@router.get("/preferences", response_model=PreferencesOut)
def get_prefs(
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> PreferencesOut:
    prefs = get_preferences(session, identity.user.id)
    return _preferences_out(prefs, _selectable_terms(prefs.target_finish_term))


@router.put("/preferences", response_model=PreferencesOut)
def put_preferences(
    payload: PreferencesIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> PreferencesOut:
    """Update the preferences the caller mentioned, and only those.

    Three unrelated intentions share this row, so a partial update must not be a way to
    forget the other two. The client saves one control at a time.
    """
    sent = payload.model_fields_set
    prefs = set_preferences(
        session,
        identity.user.id,
        target_finish_term=(
            payload.target_finish_term if "target_finish_term" in sent else UNSET
        ),
        max_credits_per_term=(
            payload.max_credits_per_term if "max_credits_per_term" in sent else UNSET
        ),
        summers_ok=payload.summers_ok if "summers_ok" in sent else UNSET,
    )
    return _preferences_out(prefs, _selectable_terms(prefs.target_finish_term))


@router.get("/courses", response_model=list[CourseOut])
def get_courses(
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> list[CourseOut]:
    return [_to_out(e) for e in list_record(session, identity.user.id)]


@router.put("/courses", response_model=CourseOut)
def put_course(
    payload: CourseIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> CourseOut:
    # `model_fields_set` is what separates "term: null" from no term at all. Passing
    # `payload.term` unconditionally made every partial update clear the fields it did not
    # mention, so editing a grade dropped the semester the transcript importer had filled
    # in. A client that means to clear one still can — by sending it as null.
    sent = payload.model_fields_set
    entry = upsert_course(
        session,
        identity.user.id,
        course_code=payload.course_code,
        state=payload.state,
        term=payload.term if "term" in sent else UNSET,
        grade=payload.grade if "grade" in sent else UNSET,
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
    # ProgramNotEncodedError propagates to main.py's handler, which distinguishes it from
    # ProgramNotStatedError by error code — one sends the student to the picker, the other
    # tells them their (correct) answer is not one this tool can audit.
    result, meta = plan_for_user(
        session, identity.user.id, include_planned=include_planned
    )
    return _plan_response(
        result, meta, elective_options_for(session, identity.user.id, result)
    )


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
    result, meta = plan_for_user(
        session,
        identity.user.id,
        include_planned=True,
        extra_courses=extra,
    )
    return _plan_response(result, meta)
