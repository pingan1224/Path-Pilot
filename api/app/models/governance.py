"""Freshness policy and the replayable AI audit log."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import InteractionDecision, Intent, UserRole


class SourceFreshnessPolicy(Base, TimestampMixin):
    """How old data from a given source may be before it must be flagged as stale.

    Rule 4 made concrete. A financial balance and a policy document age at completely
    different rates, so a single global TTL would be wrong in both directions — too strict
    for policy text, far too lax for money. Each source declares its own tolerance here,
    and anything mirrored from it carries `source_key` + `verified_at` for comparison.
    """

    __tablename__ = "source_freshness_policy"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    owning_office: Mapped[str] = mapped_column(String(64), nullable=False)
    max_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    # Shown verbatim when data exceeds max_age, e.g. "Balances update overnight; a payment
    # made today may not appear yet."
    stale_disclosure: Mapped[str] = mapped_column(Text, nullable=False)


class AiInteraction(Base):
    """One assistant turn, recorded completely enough to replay.

    This table does double duty, which is the design's nicest economy: it is the compliance
    audit trail that makes any answer contestable, and it is the raw material for the P4
    evaluation set. Retrieval hits are stored with their similarity scores, so a regression
    in ranking is visible without re-running the pipeline.

    Rows are immutable once written.
    """

    __tablename__ = "ai_interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Who asked, and in what capacity. `subject_student_id` is who the question was *about*
    # — an advisor asking about an advisee makes these differ, and any mismatch outside an
    # advising relationship is exactly what an auditor would look for.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    acting_role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"), nullable=False, index=True
    )
    subject_student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="SET NULL"), index=True
    )

    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[Intent | None] = mapped_column(SAEnum(Intent, name="intent"), index=True)
    intent_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))

    # [{"chunk_id": 12, "score": 0.83, "rank": 1}, ...] — ordered as ranked.
    retrieved_chunks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # Permission-checked tool layer calls: name, arguments, and what came back.
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    prompt_snapshot: Mapped[str | None] = mapped_column(Text)

    response_text: Mapped[str | None] = mapped_column(Text)
    # [{"claim": "...", "source_id": "...", "verified_at": "..."}, ...]
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    decision: Mapped[InteractionDecision] = mapped_column(
        SAEnum(InteractionDecision, name="interaction_decision"), nullable=False, index=True
    )
    escalation_reason: Mapped[str | None] = mapped_column(String(200))
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))

    # Which degradation paths were active, e.g. ["keyword_fallback"]. Empty means the full
    # pipeline ran; evaluation must be able to exclude degraded turns from headline metrics.
    degraded_modes: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)))

    model: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    # How many model turns the loop took. Derivable from `tool_calls` only approximately —
    # the last turn produces the answer and calls no tool, so it leaves no mark in the trace
    # — and loop length is the headline number for whether a change made the agent wander.
    # An audit row that promises to be replayable should not make it a subtraction.
    iterations: Mapped[int | None] = mapped_column(Integer)

    case: Mapped[Case | None] = relationship(foreign_keys=[case_id])


from app.models.cases import Case  # noqa: E402
