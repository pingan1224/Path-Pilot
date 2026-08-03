"""The tools the agent may call, with permission enforcement inside each tool.

The security design in one sentence: **no tool accepts a student_id from the model.**
The subject student comes from the server-side ToolContext, so asking about another
student is not something the model can be tricked into — the parameter does not exist.
Prompt injection cannot widen a boundary that is not expressed in the schema.

Every tool result that carries facts also carries source ids and verified_at timestamps.
The agent must cite these ids in its final answer, and the server rejects citations that
reference ids no tool returned this turn (see agent.py). Provenance, freshness, and the
role filter all hold in every mode — they are properties of the tool layer, not of the
prompt.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Course,
    CoursePrerequisite,
    Hold,
    RegistrationAttempt,
    Section,
    Student,
    Term,
    UserRole,
)
from app.services.freshness import FreshnessPolicies, humanize_age
from app.services.readiness import compute_readiness
from app.services.retrieval import search_policy

MAX_SECTIONS = 6
MAX_ATTEMPTS = 5


@dataclass
class ToolContext:
    """Server-injected scope for one assistant turn. The model never sees or sets this."""

    session: Session
    acting_role: UserRole
    subject_student_id: int | None
    # Every source id handed to the model this turn; citations are validated against it.
    seen_source_ids: set[str] = field(default_factory=set)
    # Degradations that occurred while serving tools (e.g. keyword_fallback).
    degraded_modes: set[str] = field(default_factory=set)
    # Raw retrieval hits for the audit log.
    retrieval_trace: list[dict[str, Any]] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------------------


def tool_search_policy(ctx: ToolContext, query: str) -> dict[str, Any]:
    result = search_policy(ctx.session, query, ctx.acting_role.value, k=5)
    if result.degraded:
        ctx.degraded_modes.add("keyword_fallback")

    passages = []
    for chunk in result.chunks:
        source_id = f"policy:chunk:{chunk.chunk_id}"
        ctx.seen_source_ids.add(source_id)
        ctx.retrieval_trace.append(
            {"chunk_id": chunk.chunk_id, "score": chunk.score, "rank": chunk.rank}
        )
        passages.append(
            {
                "source_id": source_id,
                "document": chunk.document_title,
                "section": chunk.heading_path,
                "text": chunk.text,
                "url": chunk.url,
                "office": chunk.office,
                "verified_at": chunk.fetched_at,
                "relevance": chunk.score,
            }
        )
    return {
        "passages": passages,
        "search_degraded": result.degraded,
        "note": (
            "Ranking is keyword-based right now because semantic search is unavailable; "
            "results may be less relevant."
            if result.degraded
            else None
        ),
    }


def _require_subject(ctx: ToolContext) -> int:
    if ctx.subject_student_id is None:
        raise PermissionError(
            "No student is in scope for this conversation, so record lookups are unavailable. "
            "Policy questions can still be answered."
        )
    return ctx.subject_student_id


def tool_get_holds(ctx: ToolContext) -> dict[str, Any]:
    student_id = _require_subject(ctx)
    policies = FreshnessPolicies.load(ctx.session)

    holds = ctx.session.scalars(
        select(Hold).where(Hold.student_id == student_id, Hold.cleared_at.is_(None))
    ).all()

    # The query result itself is a citable fact, independent of the rows in it. Without
    # this, "you have no active holds" is an assertion with no source_id — and a model
    # correctly following the cite-everything rule can only escalate it. Found via eval
    # case B07: absence needs provenance too.
    student = ctx.session.get(Student, student_id)
    collection_id = f"record:holds:{student_id}"
    ctx.seen_source_ids.add(collection_id)
    collection_provenance = policies.build(student.source_key, student.verified_at)

    out = []
    for hold in holds:
        source_id = f"record:hold:{hold.id}"
        ctx.seen_source_ids.add(source_id)
        provenance = policies.build(hold.source_key, hold.verified_at)
        out.append(
            {
                "source_id": source_id,
                "type": hold.hold_type.value,
                "office": hold.office.value,
                "title": hold.title,
                "explanation": hold.explanation,
                "required_action": hold.required_action,
                "blocks_registration": hold.blocks_registration,
                "deadline": hold.deadline_at.isoformat() if hold.deadline_at else None,
                "verified_at": provenance.verified_at.isoformat(),
                "data_age": humanize_age(provenance.age_seconds),
                "is_stale": provenance.is_stale,
                "stale_note": provenance.disclosure,
            }
        )
    return {
        "source_id": collection_id,
        "active_holds": out,
        "count": len(out),
        "verified_at": collection_provenance.verified_at.isoformat(),
        "data_age": humanize_age(collection_provenance.age_seconds),
        "note": (
            "A count of 0 is a verified empty result from the registrar mirror as of the "
            "timestamp above — cite this source_id for it. It is not missing data."
            if not out
            else None
        ),
    }


def tool_get_degree_progress(ctx: ToolContext) -> dict[str, Any]:
    student_id = _require_subject(ctx)
    readiness = compute_readiness(ctx.session, student_id)

    source_id = f"record:progress:{student_id}"
    ctx.seen_source_ids.add(source_id)
    return {
        "source_id": source_id,
        "status": readiness.status.value,
        "status_reason": readiness.status_reason,
        "credits_applied": readiness.credits_applied,
        "credits_earned_raw": readiness.credits_earned_raw,
        "credits_unapplied": readiness.credits_unapplied,
        "credits_required": readiness.credits_required,
        "terms_required_for_remaining_work": readiness.terms_required,
        "terms_until_expected_graduation": readiness.terms_remaining,
        "can_finish_on_time": readiness.can_finish_on_time,
        "requirements": [
            {
                "name": r.name,
                "applied": r.applied_credits,
                "required": r.required_credits,
                "remaining": r.remaining_credits,
                "over_cap_not_counted": r.unapplied_credits,
            }
            for r in readiness.requirements
        ],
        "verified_at": readiness.provenance.verified_at.isoformat(),
        "is_stale": readiness.provenance.is_stale,
        "stale_note": readiness.provenance.disclosure,
    }


def tool_get_registration_attempts(ctx: ToolContext) -> dict[str, Any]:
    student_id = _require_subject(ctx)
    attempts = ctx.session.scalars(
        select(RegistrationAttempt)
        .where(RegistrationAttempt.student_id == student_id)
        .options(
            selectinload(RegistrationAttempt.section).selectinload(Section.course),
            selectinload(RegistrationAttempt.blocking_hold),
        )
        .order_by(RegistrationAttempt.attempted_at.desc())
        .limit(MAX_ATTEMPTS)
    ).all()

    out = []
    for attempt in attempts:
        source_id = f"record:attempt:{attempt.id}"
        ctx.seen_source_ids.add(source_id)
        out.append(
            {
                "source_id": source_id,
                "course": attempt.section.course.code,
                "attempted_at": attempt.attempted_at.isoformat(),
                "outcome": attempt.outcome.value,
                "failure_reason": attempt.failure_reason.value if attempt.failure_reason else None,
                "system_error_verbatim": attempt.raw_error,
                "linked_hold_source_id": (
                    f"record:hold:{attempt.blocking_hold_id}" if attempt.blocking_hold_id else None
                ),
            }
        )
    return {"recent_attempts": out}


def tool_get_course_info(ctx: ToolContext, course_code: str) -> dict[str, Any]:
    """Catalog facts: prerequisites and current-term sections. Public, no subject needed."""
    course = ctx.session.scalars(
        select(Course).where(Course.code == course_code.strip().upper())
    ).first()
    if course is None:
        return {"error": f"No course found with code {course_code!r}."}

    policies = FreshnessPolicies.load(ctx.session)
    source_id = f"record:course:{course.code}"
    ctx.seen_source_ids.add(source_id)

    prereqs = ctx.session.scalars(
        select(CoursePrerequisite)
        .where(CoursePrerequisite.course_id == course.id)
        .options(selectinload(CoursePrerequisite.prerequisite))
    ).all()

    today = datetime.now(UTC).date()
    active_term = ctx.session.scalars(
        select(Term).where(Term.starts_on > today).order_by(Term.sort_order).limit(1)
    ).first()

    sections_out = []
    if active_term is not None:
        sections = ctx.session.scalars(
            select(Section)
            .where(Section.course_id == course.id, Section.term_id == active_term.id)
            .limit(MAX_SECTIONS)
        ).all()
        for section in sections:
            provenance = policies.build(section.source_key, section.verified_at)
            sections_out.append(
                {
                    "section": section.section_code,
                    "seats": f"{section.enrolled_count}/{section.capacity}",
                    "seats_remaining": section.seats_remaining,
                    "waitlist": section.waitlist_count,
                    "meeting": section.meeting_pattern,
                    "requires_permission": section.requires_permission,
                    "reserved_seat_rule": section.reserved_seat_rule,
                    "seat_data_age": humanize_age(provenance.age_seconds),
                    "seat_data_stale": provenance.is_stale,
                }
            )

    return {
        "source_id": source_id,
        "code": course.code,
        "title": course.title,
        "credits": course.credits,
        "prerequisites": [
            {
                "course": p.prerequisite.code,
                "title": p.prerequisite.title,
                "min_grade": p.min_grade,
                "may_take_concurrently": p.can_be_concurrent,
            }
            for p in prereqs
        ],
        "term": active_term.name if active_term else None,
        "sections": sections_out,
    }


# --------------------------------------------------------------------------------------
# Registry and OpenAI-format schemas
# --------------------------------------------------------------------------------------

TOOL_IMPLS = {
    "search_policy": tool_search_policy,
    "get_holds": tool_get_holds,
    "get_degree_progress": tool_get_degree_progress,
    "get_registration_attempts": tool_get_registration_attempts,
    "get_course_info": tool_get_course_info,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": (
                "Search official university policy documents. Use for questions about how "
                "processes work: holds, prerequisites, waitlists, payment plans, appointments. "
                "Reformulate and search again if the first results miss part of the question."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_holds",
            "description": "Active holds on the current student's record, with deadlines and required actions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_degree_progress",
            "description": (
                "The current student's degree progress: credits applied vs required per "
                "requirement, whether the expected graduation term is achievable."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_registration_attempts",
            "description": "The current student's recent registration attempts with exact failure reasons.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_course_info",
            "description": "Catalog facts for one course: prerequisites, sections this term, seat availability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "course_code": {"type": "string", "description": "e.g. MASY-GC 2200"}
                },
                "required": ["course_code"],
            },
        },
    },
]
