"""Support case reads and writes."""

from datetime import UTC, datetime

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ActorKind,
    Case,
    CaseEvent,
    CaseStatus,
    Student,
    User,
)
from app.schemas import CaseCreate, CaseEventOut, CaseOut, CaseUpdate

STATUS_LABELS = {
    CaseStatus.new: "New",
    CaseStatus.in_review: "In review",
    CaseStatus.waiting_on_student: "Waiting on student",
    CaseStatus.resolved: "Resolved",
}

ACTION_FOR_STATUS = {
    CaseStatus.new: "Reopened case",
    CaseStatus.in_review: "Moved case to in review",
    CaseStatus.waiting_on_student: "Requested student follow-up",
    CaseStatus.resolved: "Resolved case",
}


class CaseNotFoundError(LookupError):
    pass


def _next_case_number(session: Session) -> str:
    """Sequential, human-quotable identifiers.

    Students read case numbers aloud to staff, so they are short and sequential rather than
    a UUID. Derived from the current maximum instead of a counter table because cases are
    created rarely enough that the race is not worth a table.
    """
    highest = session.scalar(
        select(func.max(func.split_part(Case.case_number, "-", 2).cast(Integer)))
    )
    return f"UAX-{(highest or 1000) + 1}"


def _to_out(case: Case, include_events: bool = True) -> CaseOut:
    return CaseOut(
        id=case.id,
        case_number=case.case_number,
        student_id=case.student_id,
        student_name=case.student.display_name if case.student else "Unknown",
        owner_name=case.owner.full_name if case.owner else None,
        category=case.category,
        status=case.status,
        status_label=STATUS_LABELS[case.status],
        priority=case.priority,
        title=case.title,
        student_message=case.student_message,
        ai_summary=case.ai_summary,
        opened_by=case.opened_by.value,
        opened_at=case.opened_at,
        resolved_at=case.resolved_at,
        events=[
            CaseEventOut(
                id=event.id,
                actor_kind=event.actor_kind.value,
                actor_name=event.actor.full_name if event.actor else None,
                action=event.action,
                note=event.note,
                from_status=event.from_status,
                to_status=event.to_status,
                occurred_at=event.occurred_at,
            )
            for event in (case.events if include_events else [])
        ],
    )


def _base_query():
    return select(Case).options(
        selectinload(Case.student).selectinload(Student.user),
        selectinload(Case.owner),
        selectinload(Case.events).selectinload(CaseEvent.actor),
    )


def list_cases(
    session: Session,
    *,
    student_id: int | None = None,
    advisor_id: int | None = None,
    status: CaseStatus | None = None,
) -> list[CaseOut]:
    query = _base_query()
    if student_id is not None:
        query = query.where(Case.student_id == student_id)
    if advisor_id is not None:
        query = query.join(Student, Student.id == Case.student_id).where(
            Student.advisor_id == advisor_id
        )
    if status is not None:
        query = query.where(Case.status == status)

    cases = session.scalars(query.order_by(Case.opened_at.desc())).unique().all()
    return [_to_out(case) for case in cases]


def get_case(session: Session, case_id: int) -> CaseOut:
    case = session.scalars(_base_query().where(Case.id == case_id)).unique().first()
    if case is None:
        raise CaseNotFoundError(f"No case with id {case_id}")
    return _to_out(case)


def create_case(session: Session, payload: CaseCreate) -> CaseOut:
    student = session.get(Student, payload.student_id)
    if student is None:
        raise LookupError(f"No student with id {payload.student_id}")

    now = datetime.now(UTC)
    case = Case(
        case_number=_next_case_number(session),
        student_id=payload.student_id,
        owner_user_id=student.advisor_id,
        category=payload.category,
        status=CaseStatus.new,
        priority=payload.priority,
        title=payload.title,
        student_message=payload.message,
        opened_by=ActorKind.student,
        opened_at=now,
    )
    session.add(case)
    session.flush()

    session.add(
        CaseEvent(
            case_id=case.id,
            actor_kind=ActorKind.student,
            action="Submitted case",
            note=payload.message,
            to_status=CaseStatus.new,
            occurred_at=now,
        )
    )
    session.commit()
    return get_case(session, case.id)


def update_case(session: Session, case_id: int, payload: CaseUpdate) -> CaseOut:
    case = session.get(Case, case_id)
    if case is None:
        raise CaseNotFoundError(f"No case with id {case_id}")

    now = datetime.now(UTC)
    previous = case.status

    case.status = payload.status
    if payload.owner_user_id is not None:
        case.owner_user_id = payload.owner_user_id
    if payload.status == CaseStatus.resolved and case.resolved_at is None:
        case.resolved_at = now
    if payload.status != CaseStatus.resolved:
        case.resolved_at = None

    actor = session.get(User, payload.actor_user_id) if payload.actor_user_id else None
    session.add(
        CaseEvent(
            case_id=case.id,
            # Rule 8: only a human closes a case. Anything arriving through this endpoint is
            # a staff action, recorded as such, so the audit trail never shows the assistant
            # resolving its own escalation.
            actor_kind=ActorKind.staff,
            actor_user_id=actor.id if actor else None,
            action=ACTION_FOR_STATUS[payload.status],
            note=payload.note,
            from_status=previous,
            to_status=payload.status,
            occurred_at=now,
        )
    )
    session.commit()
    return get_case(session, case_id)
