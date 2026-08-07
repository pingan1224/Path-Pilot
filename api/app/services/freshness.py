"""Turn a source key and a verification timestamp into a provenance record."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import faults
from app.models import SourceFreshnessPolicy
from app.schemas import Provenance

# Used when a row references a source with no policy row. Deliberately strict: an unknown
# source is treated as immediately stale rather than assumed fresh, so a missing policy
# shows up as a visible disclosure instead of a silent claim of currency.
UNKNOWN_POLICY_MAX_AGE = 0

UNKNOWN_DISCLOSURE = (
    "This value comes from a source with no freshness policy on file, so its age cannot be "
    "assessed. Confirm with the responsible office before relying on it."
)


class FreshnessPolicies:
    """Cheap in-request cache of the policy table.

    The table has single-digit rows and is read for nearly every field of every response,
    so it is loaded once per request rather than joined into each query.
    """

    def __init__(self, policies: dict[str, SourceFreshnessPolicy]) -> None:
        self._policies = policies

    @classmethod
    def load(cls, session: Session) -> "FreshnessPolicies":
        rows = session.scalars(select(SourceFreshnessPolicy)).all()
        return cls({row.source_key: row for row in rows})

    def build(self, source_key: str, verified_at: datetime) -> Provenance:
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=UTC)
        age = int((datetime.now(UTC) - verified_at).total_seconds())

        policy = self._policies.get(source_key)
        if policy is None:
            return Provenance(
                source_key=source_key,
                label=source_key.replace("_", " ").title(),
                office="unknown",
                verified_at=verified_at,
                age_seconds=age,
                max_age_seconds=UNKNOWN_POLICY_MAX_AGE,
                is_stale=True,
                disclosure=UNKNOWN_DISCLOSURE,
            )

        # Forces the rule-2 disclosure path for every field at once. The mirror going
        # stale is the most likely real degradation of the four and the least visible:
        # nothing errors, the numbers are simply older than they claim to be.
        is_stale = age > policy.max_age_seconds or faults.is_armed("freshness.all_stale")
        return Provenance(
            source_key=source_key,
            label=policy.label,
            office=policy.owning_office,
            verified_at=verified_at,
            age_seconds=max(age, 0),
            max_age_seconds=policy.max_age_seconds,
            is_stale=is_stale,
            disclosure=policy.stale_disclosure if is_stale else None,
        )


def humanize_age(seconds: int) -> str:
    """Plain-language age, for clients that want a phrase rather than a number."""
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} minutes ago"
    if seconds < 86_400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86_400
    return f"{days} day{'s' if days != 1 else ''} ago"
