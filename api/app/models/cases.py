"""Support cases and their append-only event history."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import ActorKind, CaseCategory, CasePriority, CaseStatus


class Case(Base, TimestampMixin):
    """A handoff to a human.

    Rule 8: the assistant may create these but may never resolve one. Every escalation the
    assistant makes lands here with a case number the student can quote, which is the
    concrete form of "escalates with full context" from the source RFP.
    """

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_number: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)

    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    category: Mapped[CaseCategory] = mapped_column(
        SAEnum(CaseCategory, name="case_category"), nullable=False, index=True
    )
    status: Mapped[CaseStatus] = mapped_column(
        SAEnum(CaseStatus, name="case_status"), nullable=False, index=True
    )
    priority: Mapped[CasePriority] = mapped_column(
        SAEnum(CasePriority, name="case_priority"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    student_message: Mapped[str | None] = mapped_column(Text)
    # Context the assistant assembled at escalation time, so the human does not restart
    # the diagnosis from scratch.
    ai_summary: Mapped[str | None] = mapped_column(Text)

    opened_by: Mapped[ActorKind] = mapped_column(
        SAEnum(ActorKind, name="actor_kind"), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Links back to the exact assistant turn that produced this case, making any escalation
    # decision reviewable after the fact.
    # `cases` and `ai_interactions` reference each other, so this constraint is added by a
    # separate ALTER after both tables exist. Without use_alter, create_all cannot order them.
    origin_interaction_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "ai_interactions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_cases_origin_interaction",
        )
    )

    student: Mapped[Student] = relationship(back_populates="cases")
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_user_id])
    events: Mapped[list[CaseEvent]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="CaseEvent.occurred_at.desc()",
    )


class CaseEvent(Base):
    """One entry in a case's history. Append-only — rows are never updated or deleted."""

    __tablename__ = "case_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_kind: Mapped[ActorKind] = mapped_column(
        SAEnum(ActorKind, name="actor_kind"), nullable=False
    )
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    from_status: Mapped[CaseStatus | None] = mapped_column(SAEnum(CaseStatus, name="case_status"))
    to_status: Mapped[CaseStatus | None] = mapped_column(SAEnum(CaseStatus, name="case_status"))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    case: Mapped[Case] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])


from app.models.identity import Student, User  # noqa: E402
