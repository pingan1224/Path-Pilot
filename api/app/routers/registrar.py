"""Registrar operations: capacity pressure and failure breakdown."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import UserRole
from app.schemas import RegistrarPressureResponse
from app.services.auth import Identity, require_roles
from app.services.dashboards import registrar_pressure

router = APIRouter(prefix="/registrar", tags=["registrar"])


@router.get("/pressure", response_model=RegistrarPressureResponse)
def pressure(
    term: str | None = None,
    _: Identity = Depends(require_roles(UserRole.registrar)),
    session: Session = Depends(get_session),
) -> RegistrarPressureResponse:
    try:
        return registrar_pressure(session, term)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
