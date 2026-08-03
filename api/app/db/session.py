"""Database engine and request-scoped sessions."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a database operation is attempted with no DATABASE_URL set.

    Kept explicit rather than letting SQLAlchemy fail on an empty URL, so the readiness
    endpoint and the degradation paths can distinguish "not configured" from "configured
    but unreachable" — those call for different user-facing messages.
    """


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    if not settings.database_url:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL is not set. Copy api/.env.example to api/.env and fill it in."
        )
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,  # Neon closes idle connections; verify before handing one out.
        future=True,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session that always closes."""
    with get_sessionmaker()() as session:
        yield session
