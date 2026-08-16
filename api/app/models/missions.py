"""A registration mission: the task of getting ready to register for one term.

**There is no status column here, and that is the design.** A mission's progress is
recomputed from these rows every time it is read (`app/missions/steps.py`). Storing a
status would create a second source of truth that has to be kept in step with the profile,
the candidate list, and the decisions — and the moment it drifts, the tool is telling a
student that a step is done when the facts say otherwise. That failure is invisible
precisely because a status column looks authoritative. Derivation cannot drift.

What *is* stored is facts, each of which someone did at a time:

- `missions` — a mission was opened for a term, by the student or (since 2026-08-07, with
  the user's explicit approval) by the assistant. `created_by` records which. Opening an
  empty container is the one write the agent may perform beyond proposing: it involves no
  course decision, its only parameter is the term — visible on the card the moment it
  exists — and every decision inside the container remains student-only.
- `mission_candidates` — a course was put forward, by the student or by the assistant, and
  separately confirmed or declined **by the student**.
- `mission_decisions` — the student acknowledged the gap review, accepted a specific risk
  knowingly, or produced a handoff.

The split between proposing and confirming is the load-bearing one. The assistant writes
rows with `proposed_by='ai'` and `confirmed_at IS NULL`; only a student-authenticated
endpoint sets `confirmed_at`. An unconfirmed candidate is not in the plan and does not
advance a step, so the assistant can suggest all day without ever having decided anything.
That is rule 8 ("the AI never mutates official records") applied to a record the student
owns rather than one the registrar owns.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Mission(Base):
    """One student's registration preparation for one term."""

    __tablename__ = "missions"
    # One open mission per term per student. Two would give the same question two answers.
    __table_args__ = (
        # Programme is part of the identity, not decoration. Without it "one mission per
        # term" meant a student who changed programme got the old programme's mission back
        # for the same term — still evaluated against rules they had left, with only the
        # term shown on screen to tell them apart.
        UniqueConstraint(
            "user_id", "term", "program_code", name="missions_user_id_term_program_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Free text like "Fall 2026". Not a foreign key to `terms`: that table holds demo
    # fixtures, and a real student registering for a term this tool has never heard of is
    # the normal case, not an error.
    term: Mapped[str] = mapped_column(String(32), nullable=False)
    program_code: Mapped[str] = mapped_column(String(24), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 'student' or 'ai'. The UI badges an assistant-opened mission so nobody is surprised
    # to find a container they did not create, and the trajectory eval can tell whether
    # the agent opened one when it should have.
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="student")
    # Closing is the student's choice and is not the same as finishing. A mission
    # abandoned in March is a fact worth keeping; overwriting it with a fresh one would
    # erase the reason they gave up.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(String(200))

    user: Mapped["User"] = relationship()
    candidates: Mapped[list["MissionCandidate"]] = relationship(
        back_populates="mission", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["MissionDecision"]] = relationship(
        back_populates="mission", cascade="all, delete-orphan"
    )


class MissionCandidate(Base):
    """A course under consideration for the mission's term."""

    __tablename__ = "mission_candidates"
    __table_args__ = (
        UniqueConstraint(
            "mission_id", "course_code", name="mission_candidates_mission_id_course_code_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_code: Mapped[str] = mapped_column(String(24), nullable=False)

    # 'student' or 'ai'. Kept because the two mean different things downstream and because
    # an audit of what the assistant put in front of someone is worth having.
    proposed_by: Mapped[str] = mapped_column(String(16), nullable=False, default="student")
    # Why the assistant suggested it, in its own words. Null for student-added courses —
    # they do not owe anyone a reason for their own plan.
    rationale: Mapped[str | None] = mapped_column(Text)

    # Set only by a student action. The agent tool that writes this table has no parameter
    # that reaches either column, so "the assistant confirmed a course" is not a state the
    # system can be talked into.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    mission: Mapped["Mission"] = relationship(back_populates="candidates")

    @property
    def pending(self) -> bool:
        return self.confirmed_at is None and self.declined_at is None


class MissionDecision(Base):
    """Something the student decided, recorded with what it was about and when.

    `finding_key` points at a planning finding's stable key (see `planning.types.Finding`).
    `finding_summary` stores how that finding *read at the time of the decision*, which is
    not redundant: when the situation worsens, the student should be shown that they
    accepted a smaller version of the problem rather than have the old acceptance quietly
    cover the new one.
    """

    __tablename__ = "mission_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 'acknowledged_gaps' | 'accepted_risk' | 'recorded_handoff'
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    finding_key: Mapped[str | None] = mapped_column(String(200))
    finding_summary: Mapped[str | None] = mapped_column(String(400))
    note: Mapped[str | None] = mapped_column(Text)

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    mission: Mapped["Mission"] = relationship(back_populates="decisions")


from app.models.identity import User  # noqa: E402
