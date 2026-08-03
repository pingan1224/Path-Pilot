"""Liveness and dependency checks.

`/health` answers "is the process up". `/health/ready` answers "can it actually serve
requests" — which, once a database is configured, means the database answers too. Keeping
these separate matters for the degradation rules in CLAUDE.md: the API should be able to
report partial capability rather than simply failing.
"""

from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "uax-api", "version": "0.1.0"}


@router.get("/health/ready")
def ready() -> dict[str, object]:
    checks: dict[str, str] = {}

    if settings.database_url is None:
        checks["database"] = "not_configured"
    else:
        checks["database"] = "configured"

    degraded = [name for name, state in checks.items() if state != "configured"]

    return {
        "status": "degraded" if degraded else "ready",
        "checks": checks,
        "degraded": degraded,
    }
