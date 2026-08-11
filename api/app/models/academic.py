"""Degree structure, course catalog, offerings, and enrollments."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SourcedMixin, TimestampMixin
from app.models.enums import EnrollmentStatus, RequirementKind

# Which courses can satisfy which requirement. A course may count toward several
# requirements, which is precisely why "enough credits but the wrong credits" happens —
# the pain point the readiness calculation exists to catch.
requirement_courses = Table(
    "requirement_courses",
    Base.metadata,
    Column("requirement_id", ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
    Column("course_id", ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
)

requirement_track_courses = Table(
    "requirement_track_courses",
    Base.metadata,
    Column("track_id", ForeignKey("requirement_tracks.id", ondelete="CASCADE"), primary_key=True),
    Column("course_id", ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
)


class RequirementRule(str, enum.Enum):
    """How a requirement is satisfied.

    `credits` — accumulate the minimum from any listed course.
    `all_of`  — every listed course is required.
    `one_track` — choose exactly one track and complete it. Credit counting answers this
        one wrong: a student holding one course from each of two concentrations has the
        credits and has completed neither.
    """

    credits = "credits"
    all_of = "all_of"
    one_track = "one_track"


class RequirementTrack(Base):
    """One mutually exclusive option inside a `one_track` requirement."""

    __tablename__ = "requirement_tracks"
    __table_args__ = (UniqueConstraint("requirement_id", "name", name="uq_track_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_id: Mapped[int] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    requirement: Mapped["Requirement"] = relationship(back_populates="tracks")
    courses: Mapped[list["Course"]] = relationship(secondary=requirement_track_courses)


class Term(Base, TimestampMixin):
    __tablename__ = "terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)  # e.g. 2026FA
    name: Mapped[str] = mapped_column(String(48), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    add_drop_ends_on: Mapped[date | None] = mapped_column(Date)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class Program(Base, TimestampMixin):
    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    degree: Mapped[str] = mapped_column(String(24), nullable=False)
    school: Mapped[str] = mapped_column(String(120), nullable=False)
    # Stated, not inferred. Level used to be derived as `degree in ("MS", "MA", "PhD")`,
    # which reads every undergraduate degree as graduate — and level is half of the
    # retrieval scope, so getting it wrong hands an undergraduate the graduate credit-load
    # rules with a real citation and an accurate quote.
    level: Mapped[str] = mapped_column(String(16), default="graduate", nullable=False)
    # Null for a program whose requirements have not been encoded — the total is simply not
    # known for it, and storing 0 would assert that the degree requires no credits. Encoding
    # a program (ingest/requirements.py) sets this and validates that the requirements sum
    # to it.
    total_credits_required: Mapped[int | None] = mapped_column(Integer)

    source: Mapped[str] = mapped_column(String(16), default="demo", nullable=False)
    catalog_url: Mapped[str | None] = mapped_column(String(1024))
    catalog_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requirements: Mapped[list[Requirement]] = relationship(
        back_populates="program", cascade="all, delete-orphan", order_by="Requirement.sort_order"
    )
    students: Mapped[list[Student]] = relationship(back_populates="program")


class Requirement(Base, TimestampMixin):
    """A requirement group within a program, e.g. "Core" or "Capstone"."""

    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[RequirementKind] = mapped_column(
        SAEnum(RequirementKind, name="requirement_kind"), nullable=False
    )
    min_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    min_courses: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    rule: Mapped[RequirementRule] = mapped_column(
        String(24), default=RequirementRule.credits, nullable=False
    )
    # Conditions the bulletin states that the engine cannot evaluate — approval gates,
    # eligibility thresholds, the scope of an open choice. Surfaced verbatim rather than
    # dropped, because a rule the tool cannot check is exactly what a student needs told.
    caveat: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    program: Mapped[Program] = relationship(back_populates="requirements")
    courses: Mapped[list[Course]] = relationship(
        secondary=requirement_courses, back_populates="requirements"
    )
    tracks: Mapped[list[RequirementTrack]] = relationship(
        back_populates="requirement",
        cascade="all, delete-orphan",
        order_by="RequirementTrack.sort_order",
    )


class Course(Base, TimestampMixin):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # "demo" for the invented courses the seeded scenarios run on, "catalog" for records
    # parsed from the published bulletin. Planning for a real student must only ever
    # traverse catalog rows; mixing the two would let it cite a course that does not exist.
    source: Mapped[str] = mapped_column(String(16), default="demo", nullable=False, index=True)
    catalog_url: Mapped[str | None] = mapped_column(String(1024))
    typically_offered: Mapped[str | None] = mapped_column(String(120))
    catalog_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requirements: Mapped[list[Requirement]] = relationship(
        secondary=requirement_courses, back_populates="courses"
    )
    sections: Mapped[list[Section]] = relationship(back_populates="course")
    prerequisites: Mapped[list[CoursePrerequisite]] = relationship(
        back_populates="course",
        foreign_keys="CoursePrerequisite.course_id",
        cascade="all, delete-orphan",
    )


class CoursePrerequisite(Base):
    """A directed edge: `course` requires `prerequisite`.

    Modelled as its own table rather than a self-referential many-to-many so each edge can
    carry `min_grade` and `can_be_concurrent` — the two details that decide whether a
    prerequisite failure is a hard block or a negotiable one.
    """

    __tablename__ = "course_prerequisites"
    __table_args__ = (UniqueConstraint("course_id", "prerequisite_id", name="uq_course_prereq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prerequisite_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    min_grade: Mapped[str | None] = mapped_column(String(4))
    can_be_concurrent: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Rows sharing a group_index are alternatives (satisfy any one); distinct groups must
    # all be satisfied. Flat AND is the degenerate case of one row per group.
    group_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # The bulletin's own sentence, carried so a planner verdict can quote the source
    # instead of asking the student to trust a parse they cannot see.
    raw_text: Mapped[str | None] = mapped_column(String(512))

    course: Mapped[Course] = relationship(back_populates="prerequisites", foreign_keys=[course_id])
    prerequisite: Mapped[Course] = relationship(foreign_keys=[prerequisite_id])


class Section(Base, TimestampMixin, SourcedMixin):
    """A course offering in a term. Capacity numbers are what "is it full?" resolves to."""

    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("course_id", "term_id", "section_code", name="uq_section_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False, index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id"), nullable=False, index=True)
    section_code: Mapped[str] = mapped_column(String(12), nullable=False)

    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    enrolled_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    waitlist_capacity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    waitlist_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    instructor: Mapped[str | None] = mapped_column(String(160))
    meeting_pattern: Mapped[str | None] = mapped_column(String(64))  # "Mon 18:00-20:30"
    modality: Mapped[str | None] = mapped_column(String(32))
    # Seats held for a subset of students, e.g. "MSMS majors only until Mar 20". A frequent
    # cause of the "the site says there are seats but I cannot enroll" confusion.
    reserved_seat_rule: Mapped[str | None] = mapped_column(Text)
    requires_permission: Mapped[bool] = mapped_column(default=False, nullable=False)

    course: Mapped[Course] = relationship(back_populates="sections")
    term: Mapped[Term] = relationship()
    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="section")

    @property
    def seats_remaining(self) -> int:
        return max(self.capacity - self.enrolled_count, 0)

    @property
    def fill_rate(self) -> float:
        return self.enrolled_count / self.capacity if self.capacity else 0.0


class Enrollment(Base, TimestampMixin, SourcedMixin):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "section_id", name="uq_student_section"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False, index=True)
    status: Mapped[EnrollmentStatus] = mapped_column(
        SAEnum(EnrollmentStatus, name="enrollment_status"), nullable=False, index=True
    )
    grade: Mapped[str | None] = mapped_column(String(4))
    grade_points: Mapped[float | None] = mapped_column(Numeric(3, 2))
    waitlist_position: Mapped[int | None] = mapped_column(Integer)
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    student: Mapped[Student] = relationship(back_populates="enrollments")
    section: Mapped[Section] = relationship(back_populates="enrollments")


from app.models.identity import Student  # noqa: E402
