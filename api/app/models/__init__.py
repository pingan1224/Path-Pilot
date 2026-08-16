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
from app.models.enums import (
    EnrollmentStatus,
    FailureReason,
    Intent,
    InteractionDecision,
    Office,
    ReadinessStatus,
    RequirementKind,
    UserRole,
)
from app.models.governance import AiInteraction, SourceFreshnessPolicy
from app.models.identity import Student, User
from app.models.knowledge import EMBEDDING_DIM, Document, DocumentChunk
from app.models.missions import Mission, MissionCandidate, MissionDecision
from app.models.profile import ProfileCourse

__all__ = [
    "EMBEDDING_DIM",
    "AiInteraction",
    "Course",
    "CoursePrerequisite",
    "Document",
    "DocumentChunk",
    "Enrollment",
    "EnrollmentStatus",
    "FailureReason",
    "Intent",
    "InteractionDecision",
    "Mission",
    "MissionCandidate",
    "MissionDecision",
    "Office",
    "ProfileCourse",
    "Program",
    "ReadinessStatus",
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
