"""Student-facing reads: readiness and blockers."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import Student, User, UserRole
from app.schemas import BlockerOut, ReadinessResponse
from app.services.auth import (
    Identity,
    current_user,
    require_roles,
    require_student_access,
)
from app.services.blockers import get_blockers
from app.services.readiness import StudentNotFoundError, compute_readiness

router = APIRouter(prefix="/students", tags=["student"])


@router.get("")
def list_students(
    identity: Identity = Depends(require_roles(UserRole.advisor, UserRole.registrar)),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Roster, for staff who legitimately need one.

    An advisor sees their own caseload rather than all 48 students: reading the roster is
    not the same permission as reading everyone's record, and the narrower scope is the
    one their job actually needs.
    """
    query = (
        select(Student.id, Student.student_number, User.full_name)
        .join(User, User.id == Student.user_id)
        .order_by(User.full_name)
    )
    if identity.role == UserRole.advisor:
        query = query.where(Student.advisor_id == identity.user.id)

    rows = session.execute(query).all()
    return [
        {"id": row[0], "student_number": row[1], "full_name": row[2]} for row in rows
    ]


@router.get("/{student_id}/readiness", response_model=ReadinessResponse)
def readiness(
    student_id: int,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> ReadinessResponse:
    require_student_access(identity, student_id, session)
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
    require_student_access(identity, student_id, session)
    if session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail=f"No student with id {student_id}")
    return get_blockers(session, student_id)
