"""Advisor triage queue and registrar operations aggregates.

Both views need a readiness status for many students at once. Calling the per-student
readiness service in a loop would issue several queries per advisee and take seconds
against a hosted database, so the status is recomputed here from two set-based queries and
classified in Python.
"""

import math
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from app.models import (
    Case,
    CaseStatus,
    Course,
    Enrollment,
    EnrollmentStatus,
    Hold,
    Program,
    ReadinessStatus,
    RegistrationAttempt,
    RegistrationOutcome,
    Requirement,
    RequirementKind,
    Section,
    Student,
    Term,
    User,
    requirement_courses,
)
from app.schemas import (
    AdvisorQueueResponse,
    FailureBucket,
    QueueEntry,
    RegistrarPressureResponse,
    SectionPressure,
)
from app.services.freshness import FreshnessPolicies
from app.services.readiness import (
    CAPSTONE_CREDITS_PER_TERM,
    MAX_CREDITS_PER_TERM,
    STATUS_LABELS,
)

# Triage groups in the order an advisor works them. Rank drives sort position; the label is
# what the UI groups under.
GROUPS = {
    "ai_escalation": (1, "Open AI escalations"),
    "graduation_risk": (2, "Graduation risk"),
    "blocker_before_window": (3, "Blockers before registration opens"),
    "open_case": (4, "Pending case review"),
    "routine": (5, "Routine check-in"),
}

FAILURE_LABELS = {
    "prerequisite_not_met": "Prerequisite not met",
    "financial_hold": "Financial hold",
    "time_conflict": "Time conflict",
    "section_full": "Section full",
    "reserved_seat_restriction": "Reserved seat restriction",
    "permission_required": "Permission required",
    "appointment_not_open": "Registration window not open",
    "max_credits_exceeded": "Credit limit exceeded",
    "duplicate_enrollment": "Duplicate enrollment",
    "other": "Other",
}


def _active_term(session: Session, today: date) -> Term | None:
    return session.scalars(
        select(Term).where(Term.starts_on > today).order_by(Term.sort_order).limit(1)
    ).first()


def batch_readiness(session: Session, student_ids: list[int]) -> dict[int, ReadinessStatus]:
    """Readiness status for many students, in two queries.

    Mirrors the logic in services.readiness but set-based. Keeping the two in step is a real
    risk; P4's eval harness should assert they agree on the whole population.
    """
    if not student_ids:
        return {}

    today = datetime.now(UTC).date()
    active = _active_term(session, today)

    # Applied credits per student per requirement, capped at the requirement minimum.
    rows = session.execute(
        select(
            Enrollment.student_id,
            Requirement.kind,
            Requirement.min_credits,
            func.sum(Course.credits).label("earned"),
        )
        .join(Section, Section.id == Enrollment.section_id)
        .join(Course, Course.id == Section.course_id)
        .join(requirement_courses, requirement_courses.c.course_id == Course.id)
        .join(Requirement, Requirement.id == requirement_courses.c.requirement_id)
        .join(Student, Student.id == Enrollment.student_id)
        .where(
            Enrollment.student_id.in_(student_ids),
            Enrollment.status == EnrollmentStatus.completed,
            Requirement.program_id == Student.program_id,
        )
        .group_by(Enrollment.student_id, Requirement.id, Requirement.kind, Requirement.min_credits)
    ).all()

    applied: dict[int, int] = {}
    capstone_remaining: dict[int, int] = {}
    for student_id, kind, min_credits, earned in rows:
        counted = min(int(earned), min_credits)
        applied[student_id] = applied.get(student_id, 0) + counted
        if kind == RequirementKind.capstone:
            capstone_remaining[student_id] = min_credits - counted

    # Program totals, graduation terms, and blocking-hold counts in one pass.
    meta = session.execute(
        select(
            Student.id,
            Student.program_id,
            Term.sort_order,
            func.count(Hold.id).filter(
                Hold.cleared_at.is_(None), Hold.blocks_registration.is_(True)
            ),
        )
        .outerjoin(Term, Term.id == Student.expected_graduation_term_id)
        .outerjoin(Hold, Hold.student_id == Student.id)
        .where(Student.id.in_(student_ids))
        .group_by(Student.id, Student.program_id, Term.sort_order)
    ).all()

    credits_by_program = dict(
        session.execute(select(Program.id, Program.total_credits_required)).all()
    )

    statuses: dict[int, ReadinessStatus] = {}
    for student_id, program_id, grad_sort, blocking in meta:
        required = credits_by_program.get(program_id, 36)
        earned_applied = applied.get(student_id, 0)
        remaining = max(required - earned_applied, 0)
        # A student with no capstone rows has not started it, so the full block remains.
        capstone_left = capstone_remaining.get(student_id, CAPSTONE_CREDITS_PER_TERM * 2)

        terms_required = max(
            math.ceil(remaining / MAX_CREDITS_PER_TERM),
            math.ceil(capstone_left / CAPSTONE_CREDITS_PER_TERM),
            0,
        )
        terms_remaining = (
            grad_sort - active.sort_order + 1 if active is not None and grad_sort else None
        )

        if terms_remaining is not None and terms_required > terms_remaining:
            statuses[student_id] = ReadinessStatus.at_risk
        elif blocking:
            statuses[student_id] = ReadinessStatus.watchlist
        elif terms_remaining is not None and terms_required == terms_remaining:
            statuses[student_id] = ReadinessStatus.watchlist
        else:
            statuses[student_id] = ReadinessStatus.on_track

    return statuses


def advisor_queue(session: Session, advisor_id: int) -> AdvisorQueueResponse:
    advisor = session.get(User, advisor_id)
    if advisor is None:
        raise LookupError(f"No user with id {advisor_id}")

    today = datetime.now(UTC).date()
    week_ago = datetime.now(UTC) - timedelta(days=7)

    students = session.execute(
        select(Student, User.full_name)
        .join(User, User.id == Student.user_id)
        .where(Student.advisor_id == advisor_id)
    ).all()
    student_ids = [s.id for s, _ in students]
    statuses = batch_readiness(session, student_ids)

    hold_counts = dict(
        session.execute(
            select(Hold.student_id, func.count(Hold.id))
            .where(Hold.student_id.in_(student_ids), Hold.cleared_at.is_(None))
            .group_by(Hold.student_id)
        ).all()
    )
    open_case_counts = dict(
        session.execute(
            select(Case.student_id, func.count(Case.id))
            .where(Case.student_id.in_(student_ids), Case.status != CaseStatus.resolved)
            .group_by(Case.student_id)
        ).all()
    )
    ai_escalations = {
        row[0]
        for row in session.execute(
            select(Case.student_id).where(
                Case.student_id.in_(student_ids),
                Case.status != CaseStatus.resolved,
                Case.opened_by == "ai",
            )
        ).all()
    }
    failure_counts = dict(
        session.execute(
            select(RegistrationAttempt.student_id, func.count(RegistrationAttempt.id))
            .where(
                RegistrationAttempt.student_id.in_(student_ids),
                RegistrationAttempt.outcome == RegistrationOutcome.failed,
            )
            .group_by(RegistrationAttempt.student_id)
        ).all()
    )
    latest_failures = dict(
        session.execute(
            select(
                RegistrationAttempt.student_id,
                func.max(RegistrationAttempt.attempted_at),
            )
            .where(
                RegistrationAttempt.student_id.in_(student_ids),
                RegistrationAttempt.outcome == RegistrationOutcome.failed,
            )
            .group_by(RegistrationAttempt.student_id)
        ).all()
    )
    reason_by_student: dict[int, str] = {}
    if latest_failures:
        for student_id, attempted_at in latest_failures.items():
            reason = session.scalar(
                select(RegistrationAttempt.failure_reason).where(
                    RegistrationAttempt.student_id == student_id,
                    RegistrationAttempt.attempted_at == attempted_at,
                ).limit(1)
            )
            if reason is not None:
                reason_by_student[student_id] = reason

    resolved_this_week = session.scalar(
        select(func.count(Case.id))
        .join(Student, Student.id == Case.student_id)
        .where(
            Student.advisor_id == advisor_id,
            Case.status == CaseStatus.resolved,
            Case.resolved_at >= week_ago,
        )
    ) or 0

    entries: list[QueueEntry] = []
    for student, full_name in students:
        status = statuses.get(student.id, ReadinessStatus.on_track)
        holds = hold_counts.get(student.id, 0)
        open_cases = open_case_counts.get(student.id, 0)
        days_until = (
            (student.registration_opens_at - today).days
            if student.registration_opens_at
            else None
        )

        if student.id in ai_escalations:
            group_key = "ai_escalation"
        elif status == ReadinessStatus.at_risk:
            group_key = "graduation_risk"
        elif holds and days_until is not None and days_until <= 10:
            group_key = "blocker_before_window"
        elif open_cases:
            group_key = "open_case"
        else:
            group_key = "routine"

        rank, label = GROUPS[group_key]
        entries.append(
            QueueEntry(
                student_id=student.id,
                student_number=student.student_number,
                full_name=full_name,
                readiness_status=status,
                readiness_label=STATUS_LABELS[status][0],
                active_holds=holds,
                open_cases=open_cases,
                failed_attempts=failure_counts.get(student.id, 0),
                latest_failure_reason=reason_by_student.get(student.id),
                days_until_registration=days_until,
                group=label,
                group_rank=rank,
            )
        )

    entries.sort(
        key=lambda e: (
            e.group_rank,
            e.days_until_registration if e.days_until_registration is not None else 999,
            -e.failed_attempts,
        )
    )

    return AdvisorQueueResponse(
        advisor_id=advisor.id,
        advisor_name=advisor.full_name,
        caseload=len(entries),
        at_risk_count=sum(1 for e in entries if e.readiness_status == ReadinessStatus.at_risk),
        open_escalations=len(ai_escalations),
        resolved_this_week=resolved_this_week,
        entries=entries,
    )


def registrar_pressure(session: Session, term_code: str | None = None) -> RegistrarPressureResponse:
    today = datetime.now(UTC).date()
    term = (
        session.scalars(select(Term).where(Term.code == term_code)).first()
        if term_code
        else _active_term(session, today)
    )
    if term is None:
        raise LookupError("No active term")

    policies = FreshnessPolicies.load(session)

    total_attempts = session.scalar(
        select(func.count(RegistrationAttempt.id)).where(RegistrationAttempt.term_id == term.id)
    ) or 0
    failed = session.scalar(
        select(func.count(RegistrationAttempt.id)).where(
            RegistrationAttempt.term_id == term.id,
            RegistrationAttempt.outcome == RegistrationOutcome.failed,
        )
    ) or 0

    breakdown_rows = session.execute(
        select(RegistrationAttempt.failure_reason, func.count(RegistrationAttempt.id))
        .where(
            RegistrationAttempt.term_id == term.id,
            RegistrationAttempt.outcome == RegistrationOutcome.failed,
            RegistrationAttempt.failure_reason.is_not(None),
        )
        .group_by(RegistrationAttempt.failure_reason)
        .order_by(func.count(RegistrationAttempt.id).desc())
    ).all()

    breakdown = [
        FailureBucket(
            reason=reason,
            label=FAILURE_LABELS.get(reason.value, reason.value),
            attempts=count,
            percent=round(100 * count / failed, 1) if failed else 0.0,
        )
        for reason, count in breakdown_rows
    ]

    section_rows = session.execute(
        select(Section, Course.code, Course.title)
        .join(Course, Course.id == Section.course_id)
        .where(Section.term_id == term.id)
        .order_by(
            (cast(Section.enrolled_count, Integer) * 100 / Section.capacity).desc(),
            Section.waitlist_count.desc(),
        )
    ).all()

    sections: list[SectionPressure] = []
    at_capacity = 0
    for section, code, title in section_rows:
        fill = round(100 * section.enrolled_count / section.capacity) if section.capacity else 0
        if section.enrolled_count >= section.capacity:
            at_capacity += 1

        if fill >= 100:
            pressure = "at capacity"
        elif fill >= 90:
            pressure = "filling"
        elif fill >= 70:
            pressure = "steady"
        else:
            pressure = "open"

        restriction = None
        if section.reserved_seat_rule:
            restriction = "Reserved seats"
        elif section.requires_permission:
            restriction = "Permission required"

        sections.append(
            SectionPressure(
                section_id=section.id,
                course_code=code,
                course_title=title,
                section_code=section.section_code,
                capacity=section.capacity,
                enrolled=section.enrolled_count,
                fill_percent=fill,
                seats_remaining=max(section.capacity - section.enrolled_count, 0),
                waitlisted=section.waitlist_count,
                restriction=restriction,
                pressure=pressure,
                provenance=policies.build(section.source_key, section.verified_at),
            )
        )

    students_with_holds = session.scalar(
        select(func.count(func.distinct(Hold.student_id))).where(
            Hold.cleared_at.is_(None), Hold.blocks_registration.is_(True)
        )
    ) or 0

    return RegistrarPressureResponse(
        term_code=term.code,
        term_name=term.name,
        total_attempts=total_attempts,
        failed_attempts=failed,
        failure_rate_percent=round(100 * failed / total_attempts, 1) if total_attempts else 0.0,
        sections_at_capacity=at_capacity,
        students_with_blocking_holds=students_with_holds,
        failure_breakdown=breakdown,
        sections=sections,
    )
