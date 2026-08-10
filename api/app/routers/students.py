"""Student-facing reads: readiness and blockers."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import Student
from app.schemas import BlockerOut, ReadinessResponse
from app.services.auth import Identity, current_user, require_student_access
from app.services.blockers import get_blockers
from app.services.readiness import StudentNotFoundError, compute_readiness

router = APIRouter(prefix="/students", tags=["student"])

# There is no `GET /students`. There was, when an advisor needed a roster and a registrar
# needed all of them; with the staff views gone, a list of every student in the institution
# is an endpoint with no caller and a standing invitation to enumerate the database.


@router.get("/{student_id}/readiness", response_model=ReadinessResponse)
def readiness(
    student_id: int,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> ReadinessResponse:
    require_student_access(identity, student_id)
    try:
        return compute_readiness(session, student_id)
    except StudentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{student_id}/blockers", response_model=list[BlockerOut])
def blockers(
    student_id: int,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[BlockerOut]:
    require_student_access(identity, student_id)
    if session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail=f"No student with id {student_id}")
    return get_blockers(session, student_id)
