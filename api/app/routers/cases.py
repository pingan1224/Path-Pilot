"""Support cases."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import CaseStatus
from app.schemas import CaseCreate, CaseOut, CaseUpdate
from app.services.cases import (
    CaseNotFoundError,
    create_case,
    get_case,
    list_cases,
    update_case,
)

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseOut])
def index(
    student_id: int | None = None,
    advisor_id: int | None = None,
    status: CaseStatus | None = None,
    session: Session = Depends(get_session),
) -> list[CaseOut]:
    return list_cases(
        session, student_id=student_id, advisor_id=advisor_id, status=status
    )


@router.post("", response_model=CaseOut, status_code=201)
def create(payload: CaseCreate, session: Session = Depends(get_session)) -> CaseOut:
    try:
        return create_case(session, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{case_id}", response_model=CaseOut)
def detail(case_id: int, session: Session = Depends(get_session)) -> CaseOut:
    try:
        return get_case(session, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{case_id}", response_model=CaseOut)
def patch(
    case_id: int, payload: CaseUpdate, session: Session = Depends(get_session)
) -> CaseOut:
    try:
        return update_case(session, case_id, payload)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
