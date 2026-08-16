"""Domain enumerations.

These are `str` enums so they serialize to readable values in JSON and in the audit log,
which has to stay human-inspectable years later.
"""

import enum


class UserRole(str, enum.Enum):
    """Who an account belongs to.

    There were four: student, advisor, registrar, finance, each with its own dashboard.
    Path Pilot is a student product now, and the registrar and finance personas went with their
    views. `advisor` stays because the advisor did not exist only as a login — a student's
    record names theirs, the handoff email is addressed to them, and retrieval still scopes
    documents by audience (rule 3), which needs an audience other than `student` to be a
    scope rather than a constant.
    """

    student = "student"
    advisor = "advisor"


class ReadinessStatus(str, enum.Enum):
    """The headline KPI on the student dashboard."""

    on_track = "on_track"
    watchlist = "watchlist"
    at_risk = "at_risk"


class RequirementKind(str, enum.Enum):
    core = "core"
    elective = "elective"
    capstone = "capstone"


class EnrollmentStatus(str, enum.Enum):
    enrolled = "enrolled"
    waitlisted = "waitlisted"
    dropped = "dropped"
    completed = "completed"


class Office(str, enum.Enum):
    """Responsible office. Every blocker names one, so the UI can route the student."""

    registrar = "registrar"
    bursar = "bursar"
    financial_aid = "financial_aid"
    advising = "advising"
    department = "department"
    international = "international"


class FailureReason(str, enum.Enum):
    """Why an enrollment attempt failed.

    This is the taxonomy behind the error decoder's plain-language explanation. The
    original RFP identified unclear failure reasons as the rank-1 pain point, so this enum
    is the single most load-bearing piece of the schema. It also used to drive the
    registrar dashboard's "failed attempts by reason" panel; that the panel is gone and
    this is unchanged is the point — the taxonomy was always for the student.
    """

    prerequisite_not_met = "prerequisite_not_met"
    financial_hold = "financial_hold"
    time_conflict = "time_conflict"
    section_full = "section_full"
    reserved_seat_restriction = "reserved_seat_restriction"
    permission_required = "permission_required"
    appointment_not_open = "appointment_not_open"
    max_credits_exceeded = "max_credits_exceeded"
    duplicate_enrollment = "duplicate_enrollment"
    other = "other"


class Intent(str, enum.Enum):
    """The five intent categories the assistant routes on.

    `explain_blocker` and `check_status` need the student's own record and therefore the
    permission-checked tool layer. `find_policy` and `navigate` are answerable from policy
    documents alone. `high_stakes` never gets an autonomous answer — see rule 5.
    """

    explain_blocker = "explain_blocker"
    check_status = "check_status"
    find_policy = "find_policy"
    navigate = "navigate"
    high_stakes = "high_stakes"


class InteractionDecision(str, enum.Enum):
    """What the assistant did with a question.

    `deferred` means it named who owns the question and what to bring them. It was called
    `escalated` while the assistant opened a Case row with a quotable number; Path Pilot
    is a third-party planning tool that submits nothing to anyone, so the word promised a
    queue that never existed. The behaviour it names is unchanged and still gated — what
    went is the ticket, not the refusal.

    `refused` is the narrower thing: declined with nowhere to send them. Kept distinct
    because a deferral that cannot name an office is worse than one that can, and the
    metrics have to be able to see the difference.

    Rows written before 2026-08-16 carry the literal `escalated`; readers of historical
    audit data have to accept both, the same way the trajectory scorer accepts the old
    tool-call key.
    """

    answered = "answered"
    answered_with_caveat = "answered_with_caveat"
    deferred = "deferred"
    refused = "refused"
