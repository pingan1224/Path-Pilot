"""Declarative base and shared column mixins."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """All models inherit from this."""


class TimestampMixin:
    """Row lifecycle timestamps, maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SourcedMixin:
    """For rows mirrored from an upstream system of record.

    Rule 4 in ARCHITECTURE.md says staleness is disclosed rather than hidden, which is only
    possible if every mirrored fact remembers where it came from and when it was last
    confirmed. `source_key` joins to `source_freshness_policy`, which owns the maximum
    tolerable age for that source. Anything past that threshold is still served, but the
    answer must say it may be out of date.
    """

    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
