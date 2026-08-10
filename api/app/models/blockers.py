"""Holds and failed registration attempts — the things that stop a student enrolling."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SourcedMixin, TimestampMixin
from app.models.enums import FailureReason, HoldType, Office, RegistrationOutcome


class Hold(Base, TimestampMixin, SourcedMixin):
    """A condition on a student's record, possibly blocking registration.

    `explanation` and `required_action` are stored as plain-language text rather than
    generated at read time. The assistant quotes them verbatim and cites this row, so the
    student sees the same words the responsible office would use — which is what makes the
    citation meaningful instead of decorative.
    """

    __tablename__ = "holds"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )

    hold_type: Mapped[HoldType] = mapped_column(SAEnum(HoldType, name="hold_type"), nullable=False)
    office: Mapped[Office] = mapped_column(SAEnum(Office, name="office"), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    required_action: Mapped[str] = mapped_column(Text, nullable=False)

    # Stored in cents to keep money out of floating point.
    amount_cents: Mapped[int | None] = mapped_column(Integer)

    blocks_registration: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_url: Mapped[str | None] = mapped_column(String(512))

    student: Mapped[Student] = relationship(back_populates="holds")

    @property
    def is_active(self) -> bool:
        return self.cleared_at is None


class RegistrationAttempt(Base, TimestampMixin):
    """One enrollment attempt and its outcome.

    The rank-1 pain point in the source RFP was students receiving non-actionable
    registration errors. Recording every attempt with a typed `failure_reason` is what lets
    the student view say *why* in plain language instead of echoing the error code back.
    """

    __tablename__ = "registration_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False, index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id"), nullable=False, index=True)

    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    outcome: Mapped[RegistrationOutcome] = mapped_column(
        SAEnum(RegistrationOutcome, name="registration_outcome"), nullable=False, index=True
    )
    failure_reason: Mapped[FailureReason | None] = mapped_column(
        SAEnum(FailureReason, name="failure_reason"), index=True
    )
    # What the legacy system actually returned. Kept verbatim so the plain-language
    # rewrite can be checked against the original rather than trusted blindly.
    raw_error: Mapped[str | None] = mapped_column(Text)
    blocking_hold_id: Mapped[int | None] = mapped_column(ForeignKey("holds.id", ondelete="SET NULL"))

    student: Mapped[Student] = relationship()
    section: Mapped[Section] = relationship()
    blocking_hold: Mapped[Hold | None] = relationship()


from app.models.academic import Section  # noqa: E402
from app.models.identity import Student  # noqa: E402
