"""Advisor-facing reads: the triage queue."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import User, UserRole
from app.schemas import AdvisorQueueResponse
from app.services.auth import Identity, require_roles
from app.services.dashboards import advisor_queue

router = APIRouter(prefix="/advisors", tags=["advisor"])


@router.get("")
def list_advisors(
    _: Identity = Depends(require_roles(UserRole.advisor, UserRole.registrar)),
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = session.execute(
        select(User.id, User.full_name)
        .where(User.role == UserRole.advisor)
        .order_by(User.full_name)
    ).all()
    return [{"id": row[0], "full_name": row[1]} for row in rows]


@router.get("/queue", response_model=AdvisorQueueResponse)
def my_queue(
    identity: Identity = Depends(require_roles(UserRole.advisor)),
    session: Session = Depends(get_session),
) -> AdvisorQueueResponse:
    """An advisor's own caseload.

    The advisor id is no longer a path parameter. It was one when the client chose which
    advisor to view; keeping it would mean any signed-in advisor could read a colleague's
    entire caseload by changing a number in the URL.
    """
    try:
        return advisor_queue(session, identity.user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
