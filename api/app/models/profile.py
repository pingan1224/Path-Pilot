"""A real user's self-reported academic record.

The distinction that governs this whole module: rows in `students`, `enrollments`, and
`holds` are mirrors of a system of record, carrying `source_key` and `verified_at` so the
freshness machinery can say how old they are. Rows here are **claims made by the person
using the tool**. Nobody verified them, and no amount of elapsed time will.

So `updated_at` here answers a different question than `verified_at` does elsewhere. There
it means "the registrar confirmed this N hours ago". Here it means "you told us this N
days ago" — useful for prompting a student to update a stale plan, useless as evidence.
Conflating the two would let self-reported data inherit institutional authority it does
not have, which is the single most damaging thing this product could do.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.planning.types import CourseState


class ProfileCourse(Base):
    """One course a student says they have taken, are taking, or plan to take."""

    __tablename__ = "profile_courses"
    __table_args__ = (UniqueConstraint("user_id", "course_code", name="profile_courses_user_id_course_code_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Free text, not a foreign key. A student's elective may be a Stern course this
    # catalog has never heard of; rejecting it would make the tool pretend that a real,
    # permitted choice is impossible. The planner reports such a course as unverifiable
    # instead — which is true, and useful.
    course_code: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    term: Mapped[str | None] = mapped_column(String(16))
    # Only meaningful for completed courses, and only when the student chose to give it.
    # Absent means "not stated", never "failed".
    grade: Mapped[str | None] = mapped_column(String(4))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship()

    @property
    def course_state(self) -> CourseState:
        return CourseState(self.state)


from app.models.identity import User  # noqa: E402
