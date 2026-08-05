"""Importing this package registers every mapper.

Order matters only in that all modules must be imported before SQLAlchemy configures
relationships; the cross-module imports at the bottom of each module handle the rest.
"""

from app.models.academic import (
    Course,
    CoursePrerequisite,
    Enrollment,
    Program,
    Requirement,
    RequirementRule,
    RequirementTrack,
    Section,
    Term,
    requirement_courses,
    requirement_track_courses,
)
from app.models.blockers import Hold, RegistrationAttempt
from app.models.cases import Case, CaseEvent
from app.models.enums import (
    ActorKind,
    CaseCategory,
    CasePriority,
    CaseStatus,
    EnrollmentStatus,
    FailureReason,
    HoldType,
    Intent,
    InteractionDecision,
    Office,
    ReadinessStatus,
    RegistrationOutcome,
    RequirementKind,
    UserRole,
)
from app.models.governance import AiInteraction, SourceFreshnessPolicy
from app.models.identity import Student, User
from app.models.knowledge import EMBEDDING_DIM, Document, DocumentChunk

__all__ = [
    "EMBEDDING_DIM",
    "ActorKind",
    "AiInteraction",
    "Case",
    "CaseCategory",
    "CaseEvent",
    "CasePriority",
    "CaseStatus",
    "Course",
    "CoursePrerequisite",
    "Document",
    "DocumentChunk",
    "Enrollment",
    "EnrollmentStatus",
    "FailureReason",
    "Hold",
    "HoldType",
    "Intent",
    "InteractionDecision",
    "Office",
    "Program",
    "ReadinessStatus",
    "RegistrationAttempt",
    "RegistrationOutcome",
    "Requirement",
    "RequirementKind",
    "RequirementRule",
    "RequirementTrack",
    "Section",
    "SourceFreshnessPolicy",
    "Student",
    "Term",
    "User",
    "requirement_courses",
    "requirement_track_courses",
]
