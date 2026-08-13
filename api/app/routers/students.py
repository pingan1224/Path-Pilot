"""Student-facing reads: registration readiness.

There used to be a second endpoint here, `GET /students/{id}/blockers`, and a service
behind it whose only data source was the `holds` table. Both were removed on 2026-08-13
with hold-reading itself: a blocker list this product could compute was, in practice, a
list of invented rows. What replaces it is not another endpoint — it is `albert_checklist`
telling the student where to look, and readiness confining itself to what a self-reported
record can actually support.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas import ReadinessResponse
from app.services.auth import Identity, current_user, require_student_access
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
