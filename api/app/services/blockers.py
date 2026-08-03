"""Active blockers for a student, ordered by how much trouble they are."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Hold, Student
from app.schemas import BlockerOut
from app.services.freshness import FreshnessPolicies

# Never colour alone: each urgency carries the sentence a screen reader would announce.
URGENCY_LABELS = {
    "critical": "Action required",
    "high": "Action required",
    "normal": "Review recommended",
    "low": "No immediate action",
}


def get_blockers(session: Session, student_id: int) -> list[BlockerOut]:
    student = session.get(Student, student_id)
    if student is None:
        return []

    policies = FreshnessPolicies.load(session)
    now = datetime.now(UTC)
    today = now.date()

    holds = session.scalars(
        select(Hold)
        .where(Hold.student_id == student_id, Hold.cleared_at.is_(None))
        .order_by(Hold.deadline_at.nulls_last(), Hold.placed_at)
    ).all()

    out: list[BlockerOut] = []
    for hold in holds:
        deadline = hold.deadline_at
        if deadline is not None and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        days_left = (deadline.date() - today).days if deadline else None

        urgency = _urgency(
            blocks_registration=hold.blocks_registration,
            days_left=days_left,
            registration_in_days=(
                (student.registration_opens_at - today).days
                if student.registration_opens_at
                else None
            ),
        )

        placed = hold.placed_at
        if placed.tzinfo is None:
            placed = placed.replace(tzinfo=UTC)

        out.append(
            BlockerOut(
                id=hold.id,
                hold_type=hold.hold_type,
                office=hold.office,
                title=hold.title,
                explanation=hold.explanation,
                required_action=hold.required_action,
                amount_cents=hold.amount_cents,
                blocks_registration=hold.blocks_registration,
                placed_at=placed,
                deadline_at=deadline,
                days_until_deadline=days_left,
                urgency=urgency,
                urgency_label=URGENCY_LABELS[urgency],
                resolution_url=hold.resolution_url,
                provenance=policies.build(hold.source_key, hold.verified_at),
            )
        )

    order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    out.sort(key=lambda b: (order[b.urgency], b.days_until_deadline is None, b.days_until_deadline or 0))
    return out


def _urgency(
    *, blocks_registration: bool, days_left: int | None, registration_in_days: int | None
) -> str:
    """Rank a blocker by consequence, not just by how soon it expires.

    The case worth catching is a deadline that lands close to the registration window:
    processing takes days, so a student who clears the hold exactly on time can still find
    their window gone. That reads as "plenty of time" on a plain countdown and is the
    reason urgency considers both dates together rather than the deadline alone.
    """
    if not blocks_registration:
        return "low"

    if days_left is not None and days_left < 0:
        return "critical"

    if (
        days_left is not None
        and registration_in_days is not None
        and days_left >= registration_in_days - 2
    ):
        return "critical"

    if days_left is not None and days_left <= 3:
        return "critical"

    if days_left is not None and days_left <= 10:
        return "high"

    return "normal"
