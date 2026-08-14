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

from app import faults
from app.models import (
    Course,
    CoursePrerequisite,
    Section,
    Student,
    Term,
    User,
    UserRole,
)
from app.services.freshness import FreshnessPolicies, humanize_age
from app.services.profile import program_page_slug
from app.services.retrieval import (
    SCHOOL_TO_CORPUS_SLUG,
    RetrievalScope,
    search_policy,
)

MAX_SECTIONS = 6

# Every prefix a tool in this module puts in front of a source id.
#
# Declared rather than inferred so `tests/test_case_labels.py` can check the golden set's
# `must_cite_prefix` labels against something. On 2026-08-13 two of those labels named
# prefixes nothing emits — `plan:` (the real one is `selfreport:plan:`) and
# `record:progress`, left behind when its tool was deleted — and the only thing that could
# catch either was a fourteen-minute paid eval run. One of them had been passing by falling
# through to its second prefix, which is the worse kind: a label that looks satisfied.
#
# Hand-maintained, with the same limitation as WRITE_TOOLS and the same answer: the test
# checks both directions, so a prefix declared here that no longer appears in this file
# fails too. What it cannot catch is a *new* prefix nobody added — that check is this
# comment.
SOURCE_ID_PREFIXES: frozenset[str] = frozenset({
    "policy:chunk:",
    "record:course:",
    "selfreport:plan:",
    "checklist:",
    "decode:",
    "mission:",
})


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
    # Policy queries issued this turn, in order. The budget counts these; see
    # MAX_POLICY_SEARCHES.
    policy_queries: list[str] = field(default_factory=list)

    # Which world this conversation lives in. **This no longer changes what the model can
    # see** — since 2026-08-13 there is one tool surface, and it is the one that never
    # claims to read Albert (see TOOL_IMPLS). `demo` is a seeded fixture student, `live` a
    # real signed-in user, and in both cases coursework is self-reported and hold status is
    # unreachable.
    #
    # What it still decides is whether an escalation opens a `Case` with a quotable number.
    # A demo scenario has a seeded advisor and a case queue to point at; a real user has
    # neither, and handing them a case number would promise a staff workflow that does not
    # exist behind this product.
    mode: str = "demo"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


# --------------------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------------------


def _scope_for(ctx: ToolContext) -> RetrievalScope:
    """The asker's own school and level, so their policies outrank a peer school's.

    Both kinds of caller resolve, which they did not until 2026-08-11. This used to return
    an empty scope whenever `subject_student_id` was None — and that is *always* true in
    live mode, so every real user searched the corpus unscoped, without the boost measured
    to take recall@5 from 0.7367 to 0.91. The demo students had the scoping; the actual
    people did not.

    Level is read from the program rather than inferred from its degree abbreviation. The
    old inference treated anything outside (MS, MA, PhD) as undergraduate, which was
    harmless while one graduate program existed and becomes a wrong-level answer the moment
    the corpus carries both.
    """
    program = None
    if ctx.subject_student_id is not None:
        student = ctx.session.get(Student, ctx.subject_student_id)
        program = student.program if student is not None else None
    elif ctx.user_id is not None:
        user = ctx.session.get(User, ctx.user_id)
        program = user.program if user is not None else None

    if program is None:
        return RetrievalScope()
    return RetrievalScope(
        school=SCHOOL_TO_CORPUS_SLUG.get(program.school),
        level=program.level,
        # The degree's own page, so a passage written for a sibling degree can be told
        # apart. Built here rather than by calling program_for_user because this function
        # already holds the Program row; `services.profile.program_page_slug` owns the
        # derivation so both paths slug a URL the same way.
        program_slug=program_page_slug(program.catalog_url),
    )


# How many policy searches one turn may spend, and the reason it is a count rather than a
# judgement about search quality.
#
# Retrieval cannot return nothing: it always hands back the five nearest chunks, so from
# inside the loop an empty-handed search looks exactly like a productive one. The
# trajectory eval caught what that costs — B26 spent 13 tool calls and 8 uncited policy
# searches reformulating its way towards a document its role cannot see, and arrived at the
# refusal it could have given after two.
#
# Three ways to detect that from the content of a search were measured against the 50
# labelled queries and every multi-search turn in the audit log
# (`scripts/measure_giveup.py`). All three failed:
#
#   relevance floor    answerable top-1 bottoms out at 0.5894, unanswerable tops out at
#                      0.6480 — overlapping, and a floor strict enough to catch the
#                      unanswerable ones discards 4 of 50 real queries.
#   query similarity   inverted. The most repetitive turn in the log (0.952 adjacent
#                      cosine) is four prerequisite lookups for four different courses;
#                      the worst circling turn sits at 0.598.
#   result novelty     inverted too. That same legitimate turn returns nothing new three
#                      searches running, while a circling turn never does. Chunk novelty is
#                      not information novelty.
#
# What separates cleanly is the count. Across 77 audited turns, no turn anyone called
# productive used more than 4 policy searches; the three circling ones used 8, 9 and 13.
# The cap is set one above the observed productive maximum, so the first turn that
# genuinely needs a fifth search is not the one that pays for this. The model is told the
# budget and its remaining balance, so running out is a stop signal it saw coming rather
# than a failure it has to work around.
#
# Only explicit search_policy calls count. The decoder runs its own retrieval, but it
# verifies that a passage mentions the cause before returning it and says so when none
# does — it cannot circle, so it is not budgeted.
MAX_POLICY_SEARCHES = 5


def tool_search_policy(ctx: ToolContext, query: str) -> dict[str, Any]:
    if len(ctx.policy_queries) >= MAX_POLICY_SEARCHES or faults.is_armed("search.budget_spent"):
        # Refused before retrieval: no embedding call, no query, no fresh passages to
        # tempt another reformulation.
        ctx.degraded_modes.add("retrieval_budget_exhausted")
        return {
            "error": "search_budget_exhausted",
            "searches_used": len(ctx.policy_queries),
            "queries_already_tried": list(ctx.policy_queries),
            "instruction": (
                "This turn has spent its policy searches. Another wording will not surface "
                "a document that is not there, and nothing further will be retrieved. "
                "Answer from the passages you already have and say plainly which part of "
                "the question they do not cover — 'the material available to me does not "
                "address that' is a complete and honest answer. Escalate only if the "
                "escalation rules apply for their own reasons."
            ),
        }

    ctx.policy_queries.append(query)
    scope = _scope_for(ctx)
    result = search_policy(
        ctx.session, query, ctx.acting_role.value, k=5, scope=scope
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
        # The scope boost is soft by design (see retrieval.py) — it nudges ranking, it does
        # not filter, because some questions genuinely have no home-school answer. That
        # means a passage from a *different, named* school can still outrank the asker's
        # own, and it did: asked whether an SPS student could take a Stern elective, the
        # top-ranked passage on the healthy dense path was School of Social Work's
        # cross-registration procedure, and the model narrated it as this student's own
        # process — real citation, accurate quote, wrong program. The heading_path said
        # "(MSW)" and the model read past it.
        #
        # So the mismatch is computed here, once, as a fact rather than left for the model
        # to notice in prose. `None` means "no signal either way" — school is unknown for
        # one or both sides — which must not be read as a match.
        cross_school = (
            bool(scope.school)
            and bool(chunk.school)
            and chunk.school != scope.school
            and chunk.school != "synthetic"
        )
        # The same mistake one level down, and the one school and level cannot catch.
        #
        # Since the corpus carries a page per degree, all 23 SPS graduate programmes match
        # on both facets while each page carries its own "Policies" section. Measured when
        # those pages landed: "what is the attendance policy" returned Publishing (MS)'s
        # programme policies above the school-wide page. A student reading an internship
        # GPA rule written for another degree has no way to know it is not theirs.
        #
        # `None` on either side means no signal — a school-wide policy page belongs to
        # every programme — and must not be read as a mismatch.
        cross_program = (
            bool(scope.program_slug)
            and bool(chunk.program_slug)
            and chunk.program_slug != scope.program_slug
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
                "school": chunk.school,
                "school_differs_from_students_own": cross_school,
                "written_for_program": chunk.program_slug,
                "program_differs_from_students_own": cross_program,
            }
        )
    any_cross_school = any(p["school_differs_from_students_own"] for p in passages)
    any_cross_program = any(p["program_differs_from_students_own"] for p in passages)
    remaining = MAX_POLICY_SEARCHES - len(ctx.policy_queries)
    return {
        "passages": passages,
        "search_degraded": result.degraded,
        "searches_remaining_this_turn": remaining,
        # Server-computed, not left for the model to infer from a heading path. Found live
        # (2026-08-07): asked whether an SPS student could take a Stern elective, a School
        # of Social Work cross-registration passage outranked the student's own thin
        # program page — real citation, accurate quote, and the model narrated the MSW
        # procedure as this student's own, never noticing the "(MSW)" in the section it was
        # quoting. A soft ranking boost can still lose to a genuinely on-topic passage from
        # the wrong school, so the mismatch is stated as a fact here rather than hoped for.
        "cross_school_warning": (
            "One or more passages above are from a DIFFERENT school than this student's "
            "own (see each passage's \"school\" and \"school_differs_from_students_own\" "
            "fields). A passage written for another school's students — its own program "
            "name, its own credit rules — is not this student's applicable procedure just "
            "because the topic matches. You may report what it shows as an example of how "
            "cross-registration works in general, but say explicitly which school it is "
            "actually for, and do not tell this student they can do something on the "
            "strength of a rule written for a different program. If nothing you retrieved "
            "is actually about this student's own school, say that plainly instead of "
            "generalizing from what is."
            if any_cross_school
            else None
        ),
        # Server-computed for the same reason as the school warning: the model cannot be
        # relied on to notice "(MS)" in a heading, and here the two pages agree on school
        # and level, so nothing else in the result distinguishes them.
        "cross_program_warning": (
            "One or more passages above come from a DIFFERENT degree program's page (see "
            'each passage\'s "written_for_program" and '
            '"program_differs_from_students_own" fields). Every program at this school '
            "publishes its own policies — internship eligibility, concentration rules, "
            "credit structure — and they differ. A rule written for another program is not "
            "this student's rule, even though the school and the degree level match and "
            "the passage looks like general policy. Say which program a passage is for "
            "whenever it is not the student's own, and prefer the school-wide policy page "
            "(the passages with no program named) when the question is about a "
            "school-wide rule."
            if any_cross_program
            else None
        ),
        # The corpus does not tell you it lacks a page; the nearest five chunks come back
        # either way. Saying so once, near the end of the budget, is what turns "keep
        # rewording" into "say it is not there".
        "budget_note": (
            "These are the nearest passages, not necessarily relevant ones — retrieval "
            f"always returns five. {remaining} search(es) left this turn. If what you have "
            "does not answer the question, the corpus most likely has no page on it: say "
            "so rather than trying another wording."
            if remaining <= 2
            else None
        ),
        # Measured, not adjectival. "Less relevant" is what this said before the fallback
        # had ever run; the first run of it answered an SPS student with the School of
        # Social Work's waitlist procedure, in confident prose, with nothing in the text
        # marking it as degraded. The numbers come from scripts/measure_degraded_retrieval.
        "note": (
            "DEGRADED SEARCH: semantic search is unavailable, so these passages were "
            "ranked by keyword overlap alone. Measured on this corpus, that finds the "
            "right section about 66% of the time against 91% normally, and ranks it worse. "
            "Two things follow. Say in your answer that policy search is degraded right "
            "now and the passage may not be the best one. And check that each passage is "
            "actually about this student's school and level before relying on it — the "
            "wrong school's answer to the right question is the characteristic failure "
            "here, and it reads as perfectly authoritative."
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
    from app.services.profile import (
        ProgramNotStatedError,
        plan_for_user,
        program_for_user,
    )

    # A program this project has not encoded gets a refusal, never the nearest encoded
    # program's rules. Auditing someone against a degree they are not in produces a
    # confident, correctly-cited answer to a question nobody asked — the same failure the
    # cross-school warning exists to prevent, one level up.
    try:
        program = program_for_user(ctx.session, ctx.user_id)
    except ProgramNotStatedError as exc:
        return {
            "error": "program_not_stated",
            "detail": str(exc),
            "instruction": (
                "Ask the student which program they are studying, then answer. Do not "
                "assume a program and do not apply any requirement rules until they say."
            ),
        }

    if not program.is_encoded:
        ctx.degraded_modes.add("program_not_encoded")
        return {
            "error": "program_not_encoded",
            "program": program.name,
            "instruction": (
                f"Path Pilot has not encoded the degree requirements for {program.name}, "
                "so there is no degree audit for this student and you must not produce "
                "one. Say plainly that their program is not supported for requirement "
                "checking yet. You may still answer policy questions with search_policy "
                "and point them at what only Albert knows. Never apply another program's "
                "requirements to them, however similar it looks."
            ),
        }

    result, meta = plan_for_user(ctx.session, ctx.user_id, program_code=program.code)
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
        "Path Pilot only knows the courses you typed in yourself.",
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
        "path_pilot_can_see_this": False,
        "where_to_look": where,
        "what_to_know": why,
        "instruction": (
            "State that Path Pilot cannot see this and point the student to where it lives. Do "
            "not guess, and do not say the record is clear — an empty result here means "
            "no access, not no problem."
        ),
    }


def tool_decode_registration_error(ctx: ToolContext, error_text: str) -> dict[str, Any]:
    """Decode a registration error message the student quotes in conversation.

    The model does not classify the error — `app.decoder` does, from a rule table — and
    this tool hands back the result plus the evidence for it. That split is the same one
    the planner uses: the verdict is computed so it is repeatable and testable, and the
    model's job is to narrate it and cite the passages.

    Available in both modes on purpose. Nothing here reads a student record, so it is not
    one of the tools live mode has to withdraw: the input is text the student pasted, and
    the only record consulted is their own self-reported coursework, clearly labelled.
    """
    from app.decoder import decode

    result = decode(
        ctx.session,
        error_text,
        role=ctx.acting_role.value,
        user_id=ctx.user_id,
    )
    classification = result.classification
    ctx.seen_source_ids.update(result.source_ids)
    for passage in result.passages:
        ctx.retrieval_trace.append(
            {"chunk_id": int(passage["source_id"].rsplit(":", 1)[1]), "via": "decoder"}
        )
    if result.degraded:
        ctx.degraded_modes.update(result.degraded)

    from app.decoder.patterns import BY_REASON

    payload: dict[str, Any] = {
        "outcome": classification.outcome.value,
        "confidence": classification.confidence,
        "identified_cause": (
            {
                "source_id": f"decode:{classification.reason.value}",
                "reason": classification.reason.value,
                "label": BY_REASON[classification.reason].label,
                "what_the_message_says": result.reading,
                "what_to_do": list(result.what_to_do),
                "office_that_can_act": result.responsible_office,
                "matched_in_your_text": [
                    e.matched for e in classification.candidates[0].evidence
                ],
            }
            if classification.reason is not None
            else None
        ),
        "possible_causes": [
            {
                "reason": c.reason.value,
                "label": BY_REASON[c.reason].label,
                "what_the_message_says": BY_REASON[c.reason].reading,
                "matched_in_your_text": [e.matched for e in c.evidence],
            }
            for c in classification.candidates[:3]
        ],
        "identifiers_found": {
            "course_codes": list(classification.extracted.course_codes),
            "class_numbers": list(classification.extracted.class_numbers),
            "hold_codes": list(classification.extracted.hold_codes),
            "term": classification.extracted.term,
        },
        "questions_to_ask_the_student": [
            {"question": f.question, "why": f.why} for f in classification.follow_ups
        ],
        "policy_passages": result.passages,
        "no_policy_source": result.no_policy_note,
        "albert": result.albert,
    }

    if result.record_check is not None:
        payload["self_reported_record_check"] = {
            "performed": result.record_check.performed,
            "basis": result.record_check.basis,
            "findings": result.record_check.findings,
            "note": result.record_check.note,
        }

    payload["instruction"] = (
        "Report the decoded cause and cite it. When outcome is 'ambiguous', do NOT pick "
        "one of the possible causes — name them, explain what separates them, and ask the "
        "questions above; the message genuinely does not determine which it is, and "
        "guessing sends the student to the wrong office. When outcome is 'unrecognized', "
        "say the message could not be decoded and ask for it verbatim. When "
        "no_policy_source is set, the corpus has no page on this cause: relay the steps "
        "as general guidance and say plainly that no policy source backs them."
    )
    return payload


MAX_PROPOSALS = 4


def _mission_for_tools(ctx: ToolContext):
    """The user's single open mission, or None. Never an id from the model.

    The model cannot name a mission any more than it can name a student: it gets the open
    mission belonging to the signed-in account, and if there are several it gets the most
    recent. A `mission_id` parameter would be a way to ask about somebody else's plan, so
    it does not exist.
    """
    from app.missions.service import open_missions

    if ctx.user_id is None:
        return None
    missions = open_missions(ctx.session, ctx.user_id)
    return missions[0] if missions else None


def tool_get_mission_state(ctx: ToolContext) -> dict[str, Any]:
    """Where the student is in preparing to register, and what is left.

    This is the tool that gives the assistant a notion of a task being *finished*. Every
    other tool answers a question; this one reports progress against a termination
    condition the server computed.
    """
    from app.missions.service import build_facts, mission_state

    mission = _mission_for_tools(ctx)
    if mission is None:
        return {
            "has_mission": False,
            "instruction": (
                "The student has no open registration mission. If they want help preparing "
                "for a term, tell them to start one on the Registration mission page — you "
                "cannot create it for them."
            ),
        }

    _, facts, state, meta = mission_state(ctx.session, ctx.user_id, mission.id)
    source_id = f"mission:{mission.id}"
    ctx.seen_source_ids.add(source_id)

    return {
        "source_id": source_id,
        "has_mission": True,
        "term": mission.term,
        "program": meta["program_name"],
        "basis": (
            "Computed from the courses the student entered themselves and the published "
            "program rules. Not an official record, and not a registration."
        ),
        "complete": state.complete,
        "current_step": state.current.value if state.current else None,
        "steps": [
            {
                "id": step.id.value,
                "title": step.title,
                "state": step.state.value,
                "criterion": step.criterion,
                "what_now": step.what_now,
                "note": step.note,
            }
            for step in state.steps
        ],
        "chosen_courses": [c.course_code for c in facts.confirmed],
        "awaiting_the_student_decision": [
            {"course": c.course_code, "proposed_by": c.proposed_by, "why": c.rationale}
            for c in facts.proposed
        ],
        "unresolved_blockers": [
            {
                "key": f.key,
                "course": f.subject,
                "summary": f.summary,
                "detail": f.detail,
                "next_step": f.next_step,
            }
            for f in state.open_blockers
        ],
        "risks_the_student_accepted_knowingly": [
            {"key": r.finding_key, "as_it_read_then": r.accepted_summary, "note": r.note}
            for r in facts.accepted_risks
        ],
        "instruction": (
            "Report the current step and what it needs. You cannot advance a step, confirm "
            "a course, accept a risk, or finish the mission — each of those is the student's "
            "decision and only their own action counts. Say what is left, not that it is "
            "handled."
        ),
    }


def tool_start_mission(ctx: ToolContext, term: str | None = None) -> dict[str, Any]:
    """Open an empty registration mission for a term.

    The one write the assistant may do beyond proposing, approved 2026-08-07 after being
    flagged as a boundary question rather than assumed. The reasoning is structural, not a
    relaxation: an empty container asserts nothing about the student's plan, its single
    parameter is a term the student sees on the card the moment it exists, and every
    decision inside it — which courses, which risks accepted, when it is finished — stays
    student-only and still cannot be reached from any tool.

    What this buys is the difference between "I can help once you go and open a mission"
    and actually starting the work in the turn the student asked for it.

    Idempotent by way of the service: an existing mission for that term is returned rather
    than duplicated, and a reopened one keeps its original `created_by`.
    """
    from app.missions.service import create_mission, mission_state
    from app.sequence.service import next_registerable_term
    from app.sequence.terms import parse_or_none

    if ctx.user_id is None:
        return {
            "error": "no_signed_in_record",
            "instruction": "A mission belongs to a signed-in student.",
        }

    parsed = parse_or_none(term)
    if term and parsed is None:
        return {
            "error": "unparsed_term",
            "given": term,
            "instruction": 'Ask the student which term, in a form like "Spring 2027".',
        }
    # No term given is the common case for "help me plan next semester" — default to the
    # next term a student could plausibly register for and say so, rather than making the
    # model guess a date or forcing a clarifying round trip.
    target = parsed or next_registerable_term()
    assumed = parsed is None

    existing = _mission_for_tools(ctx)
    mission = create_mission(ctx.session, ctx.user_id, term=str(target), created_by="ai")
    _, _, state, _ = mission_state(ctx.session, ctx.user_id, mission.id)

    source_id = f"mission:{mission.id}"
    ctx.seen_source_ids.add(source_id)
    return {
        "source_id": source_id,
        "term": mission.term,
        "term_was_assumed": assumed,
        "already_existed": existing is not None and existing.id == mission.id,
        "opened_by": "assistant",
        "current_step": state.current.value if state.current else None,
        "next_action_for_the_student": next(
            (s.what_now for s in state.steps if s.state.value == "active"), None
        ),
        "instruction": (
            "The container exists now; nothing in it is decided. Tell the student which "
            "term it is for — especially if term_was_assumed is true, so they can correct "
            "it — and carry on with the actual work. You still cannot confirm a course, "
            "accept a risk, or finish the mission."
        ),
    }


def tool_propose_mission_candidates(
    ctx: ToolContext, courses: list[dict[str, Any]]
) -> dict[str, Any]:
    """Suggest courses for the mission's term. Suggestions only.

    Every row this writes has `confirmed_at IS NULL`, and there is no parameter here that
    could change that — the same design as no tool accepting a `student_id`. An unconfirmed
    candidate is not in the plan and does not advance the mission, so the model can suggest
    freely without ever having decided anything on the student's behalf.
    """
    from app.missions.service import add_candidate, mission_state

    mission = _mission_for_tools(ctx)
    if mission is None:
        return {
            "error": "no_open_mission",
            "instruction": (
                "There is no open mission to propose into. Tell the student to start one; "
                "you cannot."
            ),
        }

    proposed, skipped = [], []
    for entry in (courses or [])[:MAX_PROPOSALS]:
        code = str(entry.get("course_code", "")).strip()
        if not code:
            continue
        row = add_candidate(
            ctx.session,
            ctx.user_id,
            mission.id,
            course_code=code,
            proposed_by="ai",
            rationale=str(entry.get("why", "")).strip() or None,
            # Not a parameter of this tool, and pinned here so a future edit to the schema
            # cannot quietly turn suggestions into decisions.
            confirmed=False,
        )
        if row.confirmed_at is not None or row.declined_at is not None:
            # The student already ruled on this course. A suggestion does not reopen it.
            skipped.append({"course": row.course_code, "why": "the student already decided this one"})
        else:
            proposed.append(row.course_code)

    _, _, state, _ = mission_state(ctx.session, ctx.user_id, mission.id)
    source_id = f"mission:{mission.id}"
    ctx.seen_source_ids.add(source_id)

    return {
        "source_id": source_id,
        "proposed": proposed,
        "not_proposed": skipped,
        "status": "awaiting the student's confirmation",
        "mission_still_needs": state.current.value if state.current else None,
        "instruction": (
            "These are suggestions sitting on the student's mission page for them to accept "
            "or reject. Tell them what you suggested and why, and that nothing is chosen "
            "until they confirm it. Do not describe the mission as further along than the "
            "current step says it is."
        ),
    }


def tool_get_course_sequence(
    ctx: ToolContext,
    finish_by: str | None = None,
    max_credits_per_term: int | None = None,
) -> dict[str, Any]:
    """An order for the student's remaining requirements across future terms.

    The solver decides; the model narrates. Same split as the planner and the decoder, and
    it matters most here: a schedule is the output a student plans a year of their life
    around, so it has to be reproducible and it has to carry what it rests on.

    When there is no workable order, the tool returns which constraint is binding — proven
    by relaxing it, not guessed. The model must relay that rather than inventing a reason.
    """
    from app.sequence.service import sequence_for_user
    from app.sequence.terms import TermParseError, parse_or_none

    if ctx.user_id is None:
        return {
            "error": "no_signed_in_record",
            "instruction": "Sequencing needs the student's own entered coursework.",
        }

    deadline = parse_or_none(finish_by)
    if finish_by and deadline is None:
        return {
            "error": "unparsed_term",
            "given": finish_by,
            "instruction": 'Ask the student for a term like "Spring 2028".',
        }

    try:
        plan, meta = sequence_for_user(
            ctx.session,
            ctx.user_id,
            deadline=deadline,
            max_credits_per_term=max_credits_per_term,
        )
    except (TermParseError, LookupError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    # The parameters are part of the identity. A sequence computed with a Spring 2027
    # deadline at 3 credits is a different document from the unconstrained one, and the
    # assistant legitimately asks for both in a single turn ("can I finish by X, and if not
    # what is the fastest path"). With one shared id, a citation could not say which of the
    # two schedules a claim came from — the whole point of citing it.
    cap_part = meta["max_credits_per_term"]
    deadline_part = meta["deadline"] or "open"
    source_id = (
        f"selfreport:sequence:{ctx.user_id}:{meta['start_term']}:{deadline_part}:{cap_part}"
    ).replace(" ", "")
    ctx.seen_source_ids.add(source_id)

    payload: dict[str, Any] = {
        "source_id": source_id,
        "basis": (
            "Computed from the courses the student entered themselves and the published "
            "program rules. Not a registration, and no evidence that a section will run."
        ),
        "program": meta["program_name"],
        "start_term": meta["start_term"],
        "finish_by_requested": meta["deadline"],
        "credits_per_term_used": meta["max_credits_per_term"],
        "credits_per_term_was_assumed": meta["credit_cap_was_assumed"],
        "feasible": plan.feasible,
        "concentration_used": plan.chosen_track,
        "concentrations_that_do_not_fit": [
            {"track": name, "why": why} for name, why in plan.rejected_tracks
        ],
        "terms": [
            {
                "term": str(term),
                "credits": sum(p.course.credits for p in placements),
                "courses": [
                    {
                        "code": p.course.code,
                        "credits": p.course.credits,
                        "for_requirement": p.course.requirement,
                        "why_this_term": p.course.offering.describe(),
                        "this_term_is_a_guess": p.rests_on_assumption,
                    }
                    for p in placements
                ],
            }
            for term, placements in plan.by_term().items()
        ],
        "finish_term": str(plan.finish_term) if plan.finish_term else None,
        "terms_needed": len(plan.terms_used),
        "assumptions_this_rests_on": [
            {"about": a.subject, "assumption": a.statement, "check": a.check}
            for a in plan.assumptions
        ],
    }

    if plan.infeasibility is not None:
        payload["no_workable_order"] = {
            "binding_constraints": [c.value for c in plan.infeasibility.binding],
            "explanation": plan.infeasibility.explanation,
            "what_would_unblock_it": list(plan.infeasibility.remedies),
        }

    payload["instruction"] = (
        "Give the term-by-term order and say what it assumes. Any course marked "
        "this_term_is_a_guess was placed in a term the bulletin does not confirm — say so "
        "for those specifically, do not average the caveat across the whole plan. If "
        "no_workable_order is present, relay the binding constraint and the remedies; do "
        "not invent a different reason and do not present a partial order as workable. "
        "Never say a course will be available: this tool cannot see sections or seats."
    )
    return payload


# One tool surface, demo and live alike (2026-08-13).
#
# There used to be two. The demo world could read `get_holds`, `get_degree_progress` and
# `get_registration_attempts` — three tools backed by seeded fixtures — while live mode
# withdrew them and offered `get_my_plan` and `albert_checklist` instead, on the principle
# stated here at the time: *a tool the model cannot call is a claim the model cannot make.*
#
# The split was the bug. It meant the demo — the thing anyone judging this project actually
# opens — was a **more capable product than the real one**, and the extra capability was
# entirely invented data presented with the confidence of a computed result. The honest
# surface already existed and was already tested; this deletes the other one.
#
# What survives the deletion is not nothing: coursework comes from what the student entered
# (`get_my_plan`), and everything only Albert knows is answered by `albert_checklist`, which
# returns *where to look* and is forbidden from implying any record is clear.
TOOL_IMPLS = {
    "search_policy": tool_search_policy,
    "decode_registration_error": tool_decode_registration_error,
    "get_mission_state": tool_get_mission_state,
    "start_mission": tool_start_mission,
    "propose_mission_candidates": tool_propose_mission_candidates,
    "get_course_sequence": tool_get_course_sequence,
    "get_course_info": tool_get_course_info,
    "get_my_plan": tool_get_my_plan,
    "albert_checklist": tool_albert_checklist,
}


def tools_for(ctx: ToolContext) -> dict[str, Any]:
    return TOOL_IMPLS

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
                "Reformulate and search again if the first results miss part of the question. "
                f"Budgeted: {MAX_POLICY_SEARCHES} searches per turn, and the result says how "
                "many are left. Always returns the five nearest passages, so getting results "
                "back is not evidence the corpus has your answer. Every passage names the "
                "school it is from; check that against the student's own before treating it "
                "as their applicable procedure."
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
            "name": "decode_registration_error",
            "description": (
                "Use whenever the student quotes or describes an error the registration "
                "system gave them — an error code, a refusal message, or their paraphrase "
                "of one. Classifies the cause from a rule table, returns the evidence it "
                "matched in their text, the policy passages that explain it, and — when "
                "the message is consistent with several causes — the question that "
                "separates them. Pass the error text as the student gave it, unedited."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "error_text": {
                        "type": "string",
                        "description": "The error message as the student wrote it.",
                    }
                },
                "required": ["error_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mission_state",
            "description": (
                "The student's registration-preparation progress for a term: which of the "
                "five steps is current, what it needs, which courses they have chosen, and "
                "which blockers are unresolved. Use whenever they ask what is left to do, "
                "whether they are ready, or what to do next. You cannot advance it."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_mission",
            "description": (
                "Open an empty registration mission for a term, when the student wants help "
                "preparing and get_mission_state reports none. This creates only the "
                "container — no course is chosen, nothing is decided, and the student can "
                "change the term. Use it to start the work in this turn instead of telling "
                "them to go and create one. Omit `term` if they did not name one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": 'e.g. "Spring 2027". Omit to use the next registerable term.',
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_mission_candidates",
            "description": (
                "Suggest up to four courses for the student's registration mission. These "
                "are SUGGESTIONS: they appear on their mission page awaiting confirmation, "
                "they are not added to their plan, and they do not advance the mission. "
                "Only the student can confirm one. Give a reason for each."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "courses": {
                        "type": "array",
                        "maxItems": MAX_PROPOSALS,
                        "items": {
                            "type": "object",
                            "properties": {
                                "course_code": {"type": "string", "description": "e.g. MASY1-GC 2100"},
                                "why": {
                                    "type": "string",
                                    "description": "One sentence: what this course does for their plan.",
                                },
                            },
                            "required": ["course_code", "why"],
                        },
                    }
                },
                "required": ["courses"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_course_sequence",
            "description": (
                "What order the student can take their remaining requirements in, term by "
                "term. Use for 'what is the fastest path', 'can I finish by X', 'what "
                "should I take when', or any question about ordering across terms. "
                "Enforces prerequisite order, the bulletin's offering pattern, a per-term "
                "credit cap, one concentration in full, and a finish-by term. When no "
                "order fits it returns which constraint is binding — relay that, do not "
                "guess a reason."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "finish_by": {
                        "type": "string",
                        "description": 'Term to finish by, e.g. "Spring 2028". Omit if the student did not say.',
                    },
                    "max_credits_per_term": {
                        "type": "integer",
                        "description": (
                            "Credits the student is willing to carry per term, if they "
                            "said. Omit to use the conservative assumed default — there is "
                            "no published cap for this program in the corpus."
                        ),
                    },
                },
            },
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

TOOL_SCHEMAS += LIVE_ONLY_SCHEMAS


def schemas_for(ctx: ToolContext) -> list[dict[str, Any]]:
    """One surface. `ctx` is kept in the signature because every caller passes it and the
    next thing that varies by context will want it back."""
    return TOOL_SCHEMAS
