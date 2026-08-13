"""Registration readiness and degree progress.

The whole point of this module is that a credit total is a misleading progress bar. A
student can hold 27 of 36 credits and be further from graduating than someone with 21,
because credits earned past a requirement's cap do not count toward the degree. Everything
here works in *applied* credits and reports the discarded remainder explicitly rather than
quietly folding it into a percentage.
"""

import math
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Course,
    Enrollment,
    EnrollmentStatus,
    ReadinessStatus,
    Requirement,
    RequirementKind,
    Section,
    Student,
    Term,
)
from app.schemas import ReadinessResponse, RequirementProgress, StudentSummary
from app.services.freshness import FreshnessPolicies

# How many terms the remaining work needs, at the same assumed per-term load the sequence
# planner uses.
#
# **These were two different numbers until 2026-08-13** — 12 here, 9 in `sequence.plan` —
# so the same student could be told two different finish dates depending on which surface
# they asked. That was survivable while readiness was a status badge; it is not now that
# the graduation date is the constraint the whole plan is justified against.
#
# The sequence planner's number wins because it is the one carrying its reasoning: the
# ingested corpus publishes a per-term cap for Stern's MBA programmes and nothing for SPS,
# so 9 is a conservative assumption, is the student's to change, and is disclosed as
# assumed every time it is used. 12 was "a full-time graduate load" with nothing behind it.
from app.sequence.plan import ASSUMED_CREDIT_CAP as MAX_CREDITS_PER_TERM

# Capstone courses are 3 credits each and must be taken in consecutive terms, so remaining
# capstone work sets a floor on the number of terms no amount of overloading can beat.
CAPSTONE_CREDITS_PER_TERM = 3

STATUS_LABELS = {
    ReadinessStatus.on_track: ("On track", "No immediate action"),
    ReadinessStatus.watchlist: ("Watchlist", "Review recommended"),
    ReadinessStatus.at_risk: ("At risk", "Action required"),
}


class StudentNotFoundError(LookupError):
    pass


def _active_term(session: Session, today: date) -> Term | None:
    """The term currently open for registration: the next one that has not started."""
    return session.scalars(
        select(Term).where(Term.starts_on > today).order_by(Term.sort_order).limit(1)
    ).first()


def compute_readiness(session: Session, student_id: int) -> ReadinessResponse:
    student = session.scalars(
        select(Student)
        .where(Student.id == student_id)
        .options(
            selectinload(Student.user),
            selectinload(Student.advisor),
            selectinload(Student.program),
        )
    ).first()
    if student is None:
        raise StudentNotFoundError(f"No student with id {student_id}")

    policies = FreshnessPolicies.load(session)
    today = datetime.now(UTC).date()

    # --- Completed coursework, as {course_id: credits}.
    completed = session.execute(
        select(Course.id, Course.credits)
        .join(Section, Section.course_id == Course.id)
        .join(Enrollment, Enrollment.section_id == Section.id)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.status == EnrollmentStatus.completed,
        )
    ).all()
    completed_credits: dict[int, int] = {row[0]: row[1] for row in completed}

    # --- Requirements with the courses that satisfy them.
    requirements = session.scalars(
        select(Requirement)
        .where(Requirement.program_id == student.program_id)
        .options(selectinload(Requirement.courses))
        .order_by(Requirement.sort_order)
    ).all()

    progress: list[RequirementProgress] = []
    total_applied = 0
    total_raw = 0
    remaining_by_kind: dict[RequirementKind, int] = {}

    for requirement in requirements:
        earned = sum(
            completed_credits.get(course.id, 0) for course in requirement.courses
        )
        applied = min(earned, requirement.min_credits)
        remaining = requirement.min_credits - applied
        unapplied = earned - applied

        total_applied += applied
        total_raw += earned
        remaining_by_kind[requirement.kind] = (
            remaining_by_kind.get(requirement.kind, 0) + remaining
        )

        progress.append(
            RequirementProgress(
                name=requirement.name,
                kind=requirement.kind,
                required_credits=requirement.min_credits,
                earned_credits=earned,
                applied_credits=applied,
                remaining_credits=remaining,
                unapplied_credits=unapplied,
                satisfied=remaining == 0,
            )
        )

    credits_required = student.program.total_credits_required
    credits_remaining = max(credits_required - total_applied, 0)
    percent = round(100 * total_applied / credits_required) if credits_required else 0

    # --- How many terms the remaining work actually needs.
    capstone_remaining = remaining_by_kind.get(RequirementKind.capstone, 0)
    terms_for_credits = math.ceil(credits_remaining / MAX_CREDITS_PER_TERM)
    terms_for_capstone = math.ceil(capstone_remaining / CAPSTONE_CREDITS_PER_TERM)
    terms_required = max(terms_for_credits, terms_for_capstone, 0)

    active = _active_term(session, today)
    grad_term = (
        session.get(Term, student.expected_graduation_term_id)
        if student.expected_graduation_term_id
        else None
    )
    terms_remaining: int | None = None
    if active is not None and grad_term is not None:
        terms_remaining = grad_term.sort_order - active.sort_order + 1

    can_finish = terms_remaining is None or terms_required <= terms_remaining

    # Readiness used to count active holds here and fold them into the status. It cannot
    # any more, and must not pretend to: hold status lives in Albert, which this product
    # does not read. What is computed below is a claim about *degree progress only*, and
    # every sentence it produces is worded to stay inside that.
    status, reason = _classify(
        can_finish=can_finish,
        terms_required=terms_required,
        terms_remaining=terms_remaining,
        capstone_remaining=capstone_remaining,
        credits_remaining=credits_remaining,
    )
    label, action = STATUS_LABELS[status]

    days_until_registration = (
        (student.registration_opens_at - today).days
        if student.registration_opens_at
        else None
    )

    return ReadinessResponse(
        student=StudentSummary(
            id=student.id,
            student_number=student.student_number,
            full_name=student.display_name,
            program_name=student.program.name,
            program_credits_required=credits_required,
            advisor_name=student.advisor.full_name if student.advisor else None,
            expected_graduation_term=grad_term.name if grad_term else None,
            registration_opens_at=student.registration_opens_at,
            days_until_registration=days_until_registration,
        ),
        status=status,
        status_label=label,
        status_action=action,
        status_reason=reason,
        credits_required=credits_required,
        credits_applied=total_applied,
        credits_earned_raw=total_raw,
        credits_unapplied=total_raw - total_applied,
        percent_complete=percent,
        terms_remaining=terms_remaining,
        terms_required=terms_required,
        can_finish_on_time=can_finish,
        requirements=progress,
        provenance=policies.build(student.source_key, student.verified_at),
    )


def _classify(
    *,
    can_finish: bool,
    terms_required: int,
    terms_remaining: int | None,
    capstone_remaining: int,
    credits_remaining: int,
) -> tuple[ReadinessStatus, str]:
    """Pick a status and say why in one sentence.

    **Every sentence here is about degree progress and nothing else.** Until 2026-08-13
    this function also read hold status, and its healthiest verdict ended "and nothing is
    currently blocking registration" — a claim about the registrar's system, made by a
    product with no access to it, on the strength of a fixture. Removing the hold data
    without removing that sentence would have been the worse half of the change: the
    reassurance is what a student acts on, and acting on it means skipping the one check
    that mattered.
    """
    if not can_finish and terms_remaining is not None:
        detail = f"{credits_remaining} applicable credits remain"
        if capstone_remaining:
            detail += (
                f", including {capstone_remaining} capstone credits that must be taken in "
                "consecutive terms"
            )
        return (
            ReadinessStatus.at_risk,
            f"{detail}. That needs {terms_required} term"
            f"{'s' if terms_required != 1 else ''}, but only {terms_remaining} remain before "
            "your expected graduation term.",
        )

    if terms_remaining is not None and terms_required == terms_remaining:
        return (
            ReadinessStatus.watchlist,
            "Remaining work fits your timeline exactly, with no spare term. A dropped or "
            "failed course would move your graduation term.",
        )

    return (
        ReadinessStatus.on_track,
        "Degree progress is on pace, based on the courses you have entered. Whether "
        "anything else blocks registration — a hold, your enrollment appointment — is only "
        "visible in Albert.",
    )
