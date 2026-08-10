"""Support cases — the student's own, and nobody else's.

A case is the escape hatch: the record that a question stopped being answerable by this
product and went to a human. The student opens it and reads it; the human who works it
does so in the institution's own systems, which this product has never had access to.

That is why there is no PATCH here any more. There used to be one, scoped so that only
staff could move a status, back when UAX rendered an advisor queue and a registrar board.
With those gone, the only caller that endpoint could have had is a student changing the
status of their own escalation, which is precisely what it was written to prevent.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import Case, CaseStatus, UserRole
from app.schemas import CaseCreate, CaseOut
from app.services.auth import Identity, current_user
from app.services.cases import CaseNotFoundError, create_case, get_case, list_cases

router = APIRouter(prefix="/cases", tags=["cases"])


def _own_student_id(identity: Identity) -> int:
    """The caller's own student id, or 403.

    Every route in this module is about one record, and it is always the session holder's.
    Reading the id from the session rather than the path is the whole access control story
    — there is no parameter here for a caller to change.
    """
    if identity.role != UserRole.student or identity.subject_student_id is None:
        raise HTTPException(
            status_code=403, detail="Cases belong to a student record. Sign in as a student."
        )
    return identity.subject_student_id


@router.get("", response_model=list[CaseOut])
def index(
    status: CaseStatus | None = None,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[CaseOut]:
    return list_cases(session, student_id=_own_student_id(identity), status=status)


@router.post("", response_model=CaseOut, status_code=201)
def create(
    payload: CaseCreate,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> CaseOut:
    try:
        return create_case(session, payload, student_id=_own_student_id(identity))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{case_id}", response_model=CaseOut)
def detail(
    case_id: int,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> CaseOut:
    student_id = _own_student_id(identity)
    case = session.get(Case, case_id)
    # 404 before the ownership check would answer "does case 812 exist?" for any caller.
    # A case that is not yours is indistinguishable from one that does not exist.
    if case is None or case.student_id != student_id:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    try:
        return get_case(session, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
