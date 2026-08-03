"""Student-facing reads: readiness and blockers."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import Student, User
from app.schemas import BlockerOut, ReadinessResponse
from app.services.blockers import get_blockers
from app.services.readiness import StudentNotFoundError, compute_readiness

router = APIRouter(prefix="/students", tags=["student"])


@router.get("")
def list_students(session: Session = Depends(get_session)) -> list[dict]:
    """Roster for the demo role picker. Replaced by the authenticated identity in P5."""
    rows = session.execute(
        select(Student.id, Student.student_number, User.full_name)
        .join(User, User.id == Student.user_id)
        .order_by(User.full_name)
    ).all()
    return [
        {"id": row[0], "student_number": row[1], "full_name": row[2]} for row in rows
    ]


@router.get("/{student_id}/readiness", response_model=ReadinessResponse)
def readiness(student_id: int, session: Session = Depends(get_session)) -> ReadinessResponse:
    try:
        return compute_readiness(session, student_id)
    except StudentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{student_id}/blockers", response_model=list[BlockerOut])
def blockers(student_id: int, session: Session = Depends(get_session)) -> list[BlockerOut]:
    if session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail=f"No student with id {student_id}")
    return get_blockers(session, student_id)
