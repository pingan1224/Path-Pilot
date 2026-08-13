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


class CaseCategory(str, enum.Enum):
    financial_hold = "financial_hold"
    prerequisite_conflict = "prerequisite_conflict"
    degree_planning = "degree_planning"
    overload_risk = "overload_risk"
    registration_issue = "registration_issue"
    aid_dispute = "aid_dispute"
    general_support = "general_support"


class CaseStatus(str, enum.Enum):
    new = "new"
    in_review = "in_review"
    waiting_on_student = "waiting_on_student"
    resolved = "resolved"


class CasePriority(str, enum.Enum):
    routine = "routine"
    elevated = "elevated"
    urgent = "urgent"


class ActorKind(str, enum.Enum):
    """Who performed an action. `ai` is distinct from `staff` on purpose — the audit log
    has to make it unambiguous whether a human or the model moved a case."""

    student = "student"
    staff = "staff"
    ai = "ai"
    system = "system"


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

    `refused` means it declined without escalating (out of scope, e.g. legal advice).
    `escalated` means it opened a path to a human. The distinction matters for the P4
    escalation metrics — refusals must not be counted as successful escalations.
    """

    answered = "answered"
    answered_with_caveat = "answered_with_caveat"
    escalated = "escalated"
    refused = "refused"
