"""Liveness and dependency checks.

`/health` answers "is the process up". `/health/ready` answers "can it actually serve
requests" — which means the database is reachable, not merely configured. Keeping these
separate matters for the degradation rules in ARCHITECTURE.md: the API reports partial capability
rather than failing outright, and a caller can tell which dependency is missing.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import DatabaseNotConfiguredError, get_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "path-pilot-api", "version": "0.2.0"}


@router.get("/health/ready")
def ready() -> dict[str, object]:
    checks: dict[str, str] = {}

    if settings.database_url is None:
        checks["database"] = "not_configured"
    else:
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except (SQLAlchemyError, DatabaseNotConfiguredError) as exc:
            checks["database"] = f"unreachable: {type(exc).__name__}"

    degraded = [name for name, state in checks.items() if state != "ok"]

    return {
        "status": "degraded" if degraded else "ready",
        "checks": checks,
        "degraded": degraded,
    }
