"""Support cases, scoped by the caller's role.

Read scope:  student -> own cases · advisor -> own caseload · registrar -> all ·
             finance -> financial categories only (FERPA minimum-necessary).
Write scope: students open cases about themselves; only staff move a case's status, and
             only within their read scope. The actor on every event is the session holder.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import Case, CaseCategory, CaseStatus, Student, UserRole
from app.schemas import CaseCreate, CaseOut, CaseUpdate
from app.services.auth import Identity, current_user
from app.services.cases import (
    CaseNotFoundError,
    create_case,
    get_case,
    list_cases,
    update_case,
)

router = APIRouter(prefix="/cases", tags=["cases"])

FINANCE_CATEGORIES = {CaseCategory.financial_hold, CaseCategory.aid_dispute}


def _require_case_access(identity: Identity, case: Case, session: Session) -> None:
    if identity.role == UserRole.registrar:
        return
    if identity.role == UserRole.student:
        if case.student_id != identity.subject_student_id:
            raise HTTPException(status_code=403, detail="You may only view your own cases.")
        return
    if identity.role == UserRole.advisor:
        student = session.get(Student, case.student_id)
        if student is None or student.advisor_id != identity.user.id:
            raise HTTPException(
                status_code=403, detail="That case is not in your advising caseload."
            )
        return
    if identity.role == UserRole.finance:
        if case.category not in FINANCE_CATEGORIES:
            raise HTTPException(
                status_code=403, detail="Finance staff see financial cases only."
            )
        return
    raise HTTPException(status_code=403, detail="No case access for this role.")


@router.get("", response_model=list[CaseOut])
def index(
    status: CaseStatus | None = None,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[CaseOut]:
    if identity.role == UserRole.student:
        return list_cases(session, student_id=identity.subject_student_id, status=status)
    if identity.role == UserRole.advisor:
        return list_cases(session, advisor_id=identity.user.id, status=status)
    cases = list_cases(session, status=status)
    if identity.role == UserRole.finance:
        cases = [c for c in cases if c.category in FINANCE_CATEGORIES]
    return cases


@router.post("", response_model=CaseOut, status_code=201)
def create(
    payload: CaseCreate,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> CaseOut:
    if identity.role != UserRole.student or identity.subject_student_id is None:
        raise HTTPException(
            status_code=403, detail="Cases are opened by students about their own record."
        )
    try:
        return create_case(session, payload, student_id=identity.subject_student_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{case_id}", response_model=CaseOut)
def detail(
    case_id: int,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> CaseOut:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    _require_case_access(identity, case, session)
    try:
        return get_case(session, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{case_id}", response_model=CaseOut)
def patch(
    case_id: int,
    payload: CaseUpdate,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> CaseOut:
    if identity.role == UserRole.student:
        raise HTTPException(
            status_code=403,
            detail="Case status is changed by staff; reply to your advisor instead.",
        )
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    _require_case_access(identity, case, session)
    try:
        return update_case(session, case_id, payload, actor_user_id=identity.user.id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
