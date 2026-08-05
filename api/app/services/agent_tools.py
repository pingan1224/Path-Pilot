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
from app.services.retrieval import RetrievalScope, search_policy

# Maps a program's school to the corpus slug its policies were ingested under.
#
# A column on `programs` would be the right home for this in a system with more than one
# program; as a single-program demo, a stated mapping beats a schema migration plus a
# full re-embed of 2,836 chunks. Unmapped programs simply get no scope boost, which
# degrades to the previous behaviour rather than to a wrong answer.
SCHOOL_TO_CORPUS_SLUG = {
    "School of Professional Studies": "professional-studies",
}

MAX_SECTIONS = 6
MAX_ATTEMPTS = 5


@dataclass
class ToolContext:
    """Server-injected scope for one assistant turn. The model never sees or sets this."""

    session: Session
    acting_role: UserRole
    subject_student_id: int | None
    # The signed-in account. Live mode plans against this user's self-reported record;
    # there is no student fixture to read from.
    user_id: int | None = None
    # Every source id handed to the model this turn; citations are validated against it.
    seen_source_ids: set[str] = field(default_factory=set)
    # Degradations that occurred while serving tools (e.g. keyword_fallback).
    degraded_modes: set[str] = field(default_factory=set)
    # Raw retrieval hits for the audit log.
    retrieval_trace: list[dict[str, Any]] = field(default_factory=list)

    # Which world this conversation lives in.
    #
    # `demo` — a seeded fixture student. Holds, registration attempts, and enrollments are
    #   invented but internally consistent, so the record tools answer meaningfully.
    # `live` — a real signed-in user. UAX has no Albert access, so there is no hold data,
    #   no registration history, and no official transcript. The record tools do not
    #   degrade gracefully here; they answer *emptily*, which is worse. "You have no
    #   holds" is a claim about the registrar's system that this product is in no position
    #   to make, and a student who believes it may skip the one check that mattered.
    #   In live mode those tools are withdrawn and replaced by ones that say where to look.
    mode: str = "demo"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


# --------------------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------------------


def _scope_for(ctx: ToolContext) -> RetrievalScope:
    """The asker's own school and level, so their policies outrank a peer school's."""
    if ctx.subject_student_id is None:
        return RetrievalScope()
    student = ctx.session.get(Student, ctx.subject_student_id)
    if student is None or student.program is None:
        return RetrievalScope()
    return RetrievalScope(
        school=SCHOOL_TO_CORPUS_SLUG.get(student.program.school),
        level="graduate" if student.program.degree in ("MS", "MA", "PhD") else "undergraduate",
    )


def tool_search_policy(ctx: ToolContext, query: str) -> dict[str, Any]:
    result = search_policy(
        ctx.session, query, ctx.acting_role.value, k=5, scope=_scope_for(ctx)
    )
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

def tool_get_my_plan(ctx: ToolContext) -> dict[str, Any]:
    """The live-mode replacement for get_degree_progress.

    Runs the deterministic planner over what the student entered, and labels the result as
    self-reported at every level so the model cannot narrate it as an official audit.
    """
    from app.services.profile import plan_for_user

    result, meta = plan_for_user(ctx.session, ctx.user_id)
    source_id = f"selfreport:plan:{ctx.user_id}"
    ctx.seen_source_ids.add(source_id)

    return {
        "source_id": source_id,
        "basis": (
            "Computed from courses the student entered themselves, checked against the "
            "published program requirements. Not an official degree audit."
        ),
        "program": meta["program_name"],
        "rules_source": meta["program_source_url"],
        "rules_verified_on": meta["rules_verified_on"],
        "courses_the_student_reported": meta["courses_stated"],
        "record_last_updated_by_student": meta["profile_last_updated"],
        "record_age_days": meta["profile_age_days"],
        "credits": {
            "completed": result.credits_completed,
            "in_progress": result.credits_in_progress,
            "planned": result.credits_planned,
            "required": result.credits_required,
        },
        "findings": [
            {
                "verdict": f.verdict.value,
                "summary": f.summary,
                "detail": f.detail,
                "next_step": f.next_step,
                "must_check_in_albert": f.check_in_albert,
            }
            for f in result.findings
        ],
        "note": (
            "Findings marked unverifiable or conditional are the ones this tool cannot "
            "settle. Say so plainly rather than resolving them."
            if result.needs_human
            else None
        ),
    }


# Questions whose answer lives only in Albert. Each maps to where the student should look
# instead — because "I cannot see that" is only half an answer.
ALBERT_ONLY_TOPICS = {
    "holds": (
        "Holds on your record",
        "Albert home page, under Tasks / Holds",
        "A hold names the office that placed it, and only that office can remove it.",
    ),
    "registration_errors": (
        "Why a registration attempt failed",
        "The error message Albert showed when you clicked Enroll",
        "The error code identifies the cause: prerequisites, a hold, a time conflict, a "
        "reserved seat, or your enrollment appointment not having opened.",
    ),
    "enrollment_appointment": (
        "When your registration window opens",
        "Albert, under Enrollment Dates",
        "Appointments are assigned by earned credits; a hold does not move the date and "
        "seats are not reserved while you resolve one.",
    ),
    "seats": (
        "Whether a section has seats",
        "Albert course search for the term",
        "Seat counts move quickly during registration, and reserved-seat rules can make a "
        "section unavailable to you even when it shows open seats.",
    ),
    "official_transcript": (
        "Your official grades and credits",
        "Albert, under Academic Records",
        "UAX only knows the courses you typed in yourself.",
    ),
    "financial": (
        "Balances, aid status, and payment holds",
        "Albert and the Bursar / Financial Aid portals",
        "Financial status is not visible to this tool at all.",
    ),
}


def tool_albert_checklist(ctx: ToolContext, topic: str) -> dict[str, Any]:
    """Live-mode answer for anything only the student information system knows.

    Returns where to look and what to look for. The alternative — a record tool that
    queries nothing and returns nothing — would let the assistant answer "you have no
    holds", which is a claim about the registrar's system that this product cannot make.
    """
    key = topic.strip().lower()
    entry = ALBERT_ONLY_TOPICS.get(key)
    if entry is None:
        return {
            "error": f"unknown topic {topic!r}",
            "available_topics": sorted(ALBERT_ONLY_TOPICS),
        }

    title, where, why = entry
    source_id = f"checklist:{key}"
    ctx.seen_source_ids.add(source_id)
    return {
        "source_id": source_id,
        "topic": title,
        "uax_can_see_this": False,
        "where_to_look": where,
        "what_to_know": why,
        "instruction": (
            "State that UAX cannot see this and point the student to where it lives. Do "
            "not guess, and do not say the record is clear — an empty result here means "
            "no access, not no problem."
        ),
    }


DEMO_TOOL_IMPLS = {
    "search_policy": tool_search_policy,
    "get_holds": tool_get_holds,
    "get_degree_progress": tool_get_degree_progress,
    "get_registration_attempts": tool_get_registration_attempts,
    "get_course_info": tool_get_course_info,
}

LIVE_TOOL_IMPLS = {
    "search_policy": tool_search_policy,
    "get_course_info": tool_get_course_info,
    "get_my_plan": tool_get_my_plan,
    "albert_checklist": tool_albert_checklist,
}

# Kept for callers that predate the split; demo remains the default world.
TOOL_IMPLS = DEMO_TOOL_IMPLS


def tools_for(ctx: ToolContext) -> dict[str, Any]:
    return LIVE_TOOL_IMPLS if ctx.is_live else DEMO_TOOL_IMPLS

LIVE_ONLY_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_my_plan",
            "description": (
                "The student's degree progress, computed from the courses they entered "
                "themselves and checked against published program requirements. This is "
                "self-reported, not an official audit — say so when you use it."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "albert_checklist",
            "description": (
                "Use for anything only the university's student information system knows: "
                "holds, why a registration attempt failed, enrollment appointment dates, "
                "seat availability, official grades, balances and aid. Returns where the "
                "student should look. You have no access to any of this — never state or "
                "imply that a record is clear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": sorted(ALBERT_ONLY_TOPICS),
                    }
                },
                "required": ["topic"],
            },
        },
    },
]

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

# Live mode withdraws the record tools entirely rather than letting them return empty.
# A tool the model cannot call is a claim the model cannot make.
_DEMO_ONLY = {"get_holds", "get_degree_progress", "get_registration_attempts"}

LIVE_TOOL_SCHEMAS: list[dict[str, Any]] = [
    schema for schema in TOOL_SCHEMAS if schema["function"]["name"] not in _DEMO_ONLY
] + LIVE_ONLY_SCHEMAS


def schemas_for(ctx: ToolContext) -> list[dict[str, Any]]:
    return LIVE_TOOL_SCHEMAS if ctx.is_live else TOOL_SCHEMAS
