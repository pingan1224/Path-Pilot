"""Response and request shapes for the HTTP layer."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    ReadinessStatus,
    RequirementKind,
)

# --------------------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------------------


class Provenance(BaseModel):
    """Where a fact came from and how much to trust its age.

    Attached to every mirrored fact the API returns. This is rule 4 expressed as a contract
    rather than a convention: a client cannot render a value from this API without also
    having been handed its age and staleness, so "forgot to show the timestamp" stops being
    a thing that can happen by omission.
    """

    source_key: str
    label: str
    office: str
    verified_at: datetime
    age_seconds: int
    max_age_seconds: int
    is_stale: bool
    # Populated only when is_stale — the office's own words about what may be out of date.
    disclosure: str | None = None


# --------------------------------------------------------------------------------------
# Student
# --------------------------------------------------------------------------------------


class StudentSummary(BaseModel):
    id: int
    student_number: str
    full_name: str
    program_name: str
    program_credits_required: int
    advisor_name: str | None
    expected_graduation_term: str | None
    registration_opens_at: date | None
    days_until_registration: int | None


class RequirementProgress(BaseModel):
    name: str
    kind: RequirementKind
    required_credits: int
    earned_credits: int = Field(description="Credits completed in courses tied to this requirement")
    applied_credits: int = Field(description="Credits that count, capped at required_credits")
    remaining_credits: int
    unapplied_credits: int = Field(
        description="Earned but over the cap, so they do not count toward the degree"
    )
    satisfied: bool


class ReadinessResponse(BaseModel):
    student: StudentSummary
    status: ReadinessStatus
    # Rule: status is never conveyed by colour alone. Clients render this text next to any
    # colour treatment, so the meaning survives greyscale, colour blindness, and screen
    # readers without the client having to know the mapping.
    status_label: str
    status_action: str
    status_reason: str

    credits_required: int
    credits_applied: int
    credits_earned_raw: int
    credits_unapplied: int
    percent_complete: int

    terms_remaining: int | None
    terms_required: int
    can_finish_on_time: bool

    requirements: list[RequirementProgress]
    provenance: Provenance


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
