"""Advisor-facing reads: the triage queue."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import User, UserRole
from app.schemas import AdvisorQueueResponse
from app.services.dashboards import advisor_queue

router = APIRouter(prefix="/advisors", tags=["advisor"])


@router.get("")
def list_advisors(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.execute(
        select(User.id, User.full_name)
        .where(User.role == UserRole.advisor)
        .order_by(User.full_name)
    ).all()
    return [{"id": row[0], "full_name": row[1]} for row in rows]


@router.get("/{advisor_id}/queue", response_model=AdvisorQueueResponse)
def queue(advisor_id: int, session: Session = Depends(get_session)) -> AdvisorQueueResponse:
    try:
        return advisor_queue(session, advisor_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
