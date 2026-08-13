"""Users and student records."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SourcedMixin, TimestampMixin
from app.models.enums import UserRole


class User(Base, TimestampMixin):
    """An authenticated identity: a student, or the advisor a student's record points at.

    Role lives here rather than on a join table because a person holds exactly one role in
    this system. That is a simplification of reality — a real advisor might also be a
    part-time student — but modelling it as one-to-many would make every permission
    pre-filter ambiguous, which is exactly the thing rule 3 forbids.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"), nullable=False, index=True
    )
    office: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # scrypt, with parameters and salt encoded in the value. Null means the account
    # cannot sign in at all, which is the right default for a record created by import.
    password_hash: Mapped[str | None] = mapped_column(String(256))

    # The program a real signed-in user is studying. Demo accounts carry theirs on the
    # `Student` fixture instead; `services.profile.program_for_user` reads whichever exists.
    #
    # Nullable because a user reaches this app before stating anything about themselves,
    # and one-to-one because a person here is studying one program. A minor or second major
    # would need a join table — deliberately not built until a real SPS degree needs it,
    # for the same reason `User.role` is a column rather than a relationship.
    program_id: Mapped[int | None] = mapped_column(
        ForeignKey("programs.id", ondelete="SET NULL"), index=True
    )

    program: Mapped[Program | None] = relationship(foreign_keys=[program_id])

    student_profile: Mapped[Student | None] = relationship(
        back_populates="user", foreign_keys="Student.user_id", uselist=False
    )
    advisees: Mapped[list[Student]] = relationship(
        back_populates="advisor", foreign_keys="Student.advisor_id"
    )


class Student(Base, TimestampMixin, SourcedMixin):
    """A student record, mirrored from the registrar system of record."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_number: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    advisor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), nullable=False, index=True)

    admitted_term_id: Mapped[int | None] = mapped_column(ForeignKey("terms.id"))
    expected_graduation_term_id: Mapped[int | None] = mapped_column(ForeignKey("terms.id"))

    # When this student's registration window opens. Drives the urgency of every blocker:
    # a hold two days before your window is a different problem than one two months out.
    registration_opens_at: Mapped[date | None] = mapped_column(Date)

    # Credits transferred in. Everything else is derived from enrollments rather than
    # stored, so the dashboard can never disagree with the underlying record.
    transfer_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped[User | None] = relationship(
        back_populates="student_profile", foreign_keys=[user_id]
    )
    advisor: Mapped[User | None] = relationship(
        back_populates="advisees", foreign_keys=[advisor_id]
    )
    program: Mapped[Program] = relationship(back_populates="students")
    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    cases: Mapped[list[Case]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )

    @property
    def display_name(self) -> str:
        return self.user.full_name if self.user else self.student_number


from app.models.academic import Enrollment, Program  # noqa: E402
from app.models.cases import Case  # noqa: E402
