"""The bounded agent loop.

The model decides which tools to call and when it has enough evidence; everything else is
constrained by the server:

- **Iteration cap.** At most MAX_ITERATIONS model turns. On the final turn the model is
  forced (tool_choice) to call submit_answer — the loop cannot run away or end without a
  structured outcome.
- **Forced citation.** The only way to finish is submit_answer, whose schema requires a
  citation list. An answer without the citations field is not schema-valid, so an uncited
  answer cannot be produced.
- **Citations must be real.** The server keeps the set of source ids actually returned by
  tools this turn and rejects any citation outside it. A fabricated source id gets one
  correction round; a second failure forces escalation. Schema forces the *shape*,
  validation forces the *truth* of citations.
- **Escalation is a first-class outcome.** When the model cannot verify an answer, it
  escalates: a real Case row with a case number the student can quote, never a shrug.

Every turn is written to ai_interactions with the retrieval trace, tool calls, prompt
snapshot, citations, decision, and degradations — the replayable audit rule.
"""

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app import faults
from app.config import settings
from app.models import (
    ActorKind,
    AiInteraction,
    Case,
    CaseCategory,
    CaseEvent,
    CasePriority,
    CaseStatus,
    Intent,
    InteractionDecision,
    Student,
    UserRole,
)
from app.services.agent_tools import ToolContext, schemas_for, tools_for
from app.services.llm import chat

MAX_ITERATIONS = 6

SUBMIT_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": (
            "Deliver the final answer. Every factual claim must cite a source_id that a "
            "tool returned in this conversation. Call this exactly once, when you either "
            "have verified evidence or have concluded the question must go to a human."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "Plain-language answer for the user. State data age when a source was stale.",
                },
                "intent": {
                    "type": "string",
                    "enum": [i.value for i in Intent],
                    "description": "Which intent category this question was.",
                },
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim": {"type": "string", "description": "The specific claim being supported"},
                            "source_id": {"type": "string", "description": "A source_id returned by a tool this turn"},
                        },
                        "required": ["claim", "source_id"],
                    },
                    "description": "One entry per factual claim. Empty only when escalating without asserting facts.",
                },
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "escalate": {
                    "type": "boolean",
                    "description": "True when a human must review this instead of the answer standing alone.",
                },
                "escalation": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": [c.value for c in CaseCategory]},
                        "title": {"type": "string"},
                        "summary": {
                            "type": "string",
                            "description": "Context for the human: what was verified, what could not be, why it matters.",
                        },
                    },
                    "required": ["category", "title", "summary"],
                },
            },
            "required": ["answer", "intent", "citations", "confidence", "escalate"],
        },
    },
}

SYSTEM_PROMPT = """You are the Path Pilot academic assistant inside a university student information system.
You help with registration blockers, holds, degree progress, courses, and university policy.

Subject: {subject_line}
Requester role: {role}
Today: {today}

Hard rules, none of which you may relax:
1. Only assert facts returned by your tools in THIS conversation, citing their source_id.
   No training-data answers about this university's policies or this student's record.
2. If a tool marks data stale (is_stale/stale_note), say how old it is and quote the note.
3. Escalation decision rule. Escalate when AT LEAST ONE of these is true:
   (a) The user asks you to PERFORM, approve, change, or confirm completion of an action
       — clear/remove a hold, waive a prerequisite, approve a substitution, update a
       record, move money, "confirm you received X".
   (b) The user asserts something your tools cannot see, AND the answer depends on it
       (example: "I already uploaded the document" when document receipt is not in your
       tools — you cannot confirm OR deny, so say what you can see and escalate).
   (c) Evidence is conflicting, or stale enough that acting on it could hurt the user.
   (d) The decision itself is reserved to staff: graduation-date commitments, exceptions,
       appeals, aid amounts.
   Otherwise ANSWER. Explaining verified facts, required steps, deadlines, and processes
   is answering — the topic being a hold or money does not make it an escalation.
   Example: "What do I need to do to clear my hold, and by when?" → answer from the hold
   record. Example: "Do I have any holds?" with tools showing none active → answer
   plainly: "No active holds as of <time>." Never promise an outcome either way.
4. You cannot modify any record. You explain and escalate; offices act. On a registration
   mission you may open an empty container (start_mission) and propose courses, never
   decide: confirming a course, accepting a risk, and finishing the mission are the
   student's actions, and a suggestion you made is not a choice they made. Never describe a
   mission as further along than get_mission_state says it is.

8. When a student asks for help preparing to register, do the whole job in this turn rather
   than one step per reply: read their plan, open a mission if there is none, propose the
   courses that fit, sequence the remaining terms, and tell them what is left for them to
   decide. Request independent lookups together. End with what needs their decision, not
   with a question about whether to begin.
5. When 3(b) applies, never confirm or deny the user's unverified claim — state what your
   tools do show, what they cannot show, and open the escalation.
6. No legal, medical, immigration, or mental-health advice; those go to a human.
7. Answer in the user's language; keep source quotes in their original language.

9. Policy search always returns its five nearest passages, so results coming back is not
   evidence that the corpus covers the question. Searching is budgeted and each result
   says how many searches are left. Reformulate once or twice when the first results miss
   part of the question; after that, stop. "The material available to me does not cover
   that" is a complete answer, and it is the right one far more often than a sixth
   wording. This applies with full force when the user asks for a specific document you
   cannot find: report that you cannot retrieve it, and do not keep trying phrasings.
10. Every policy passage names the school it came from. Before relying on one, check it
    against the student's own school. A passage from a DIFFERENT, named school is not this
    student's applicable procedure — it is at most an example of how the topic works
    elsewhere, and generalizing it to "here is what you should do" is wrong even when the
    citation is real and the quote is accurate. Say explicitly which school a passage is
    for whenever it is not the student's own; if search_policy flags cross_school_warning,
    treat that as the finding, not a suggestion.

Work in small steps: gather evidence with tools (reformulate and search again when a
result misses part of the question, within the budget in rule 9), then finish with
submit_answer. Cite every claim.
When lookups are independent — e.g. holds, attempts, and a policy search — request them
as multiple tool calls in the SAME turn rather than one per turn; latency matters."""


LIVE_MODE_RULES = """

LIVE MODE — this is a real student, and the constraints are different.

Path Pilot has no connection to Albert. You cannot see holds, registration errors, enrollment
appointment dates, seat counts, official grades, balances, or aid status. Not "the query
returned nothing" — you have no access at all.

9. Everything you know about this student's coursework is what they typed into Path Pilot
   themselves. Call it what it is: "based on what you have entered". Never present it as
   an official record or a degree audit.
10. For anything only Albert knows, call albert_checklist and relay where to look. Never
   say a record is clear, never say there are no holds, never infer from silence. An
   absent record here means no access, not no problem — and a student who believes
   otherwise skips the one check that mattered.
11. When the planner marks a finding unverifiable or conditional, keep it that way. Those
   are the parts a human has to settle, and smoothing them into a confident answer is the
   most damaging thing you can do here.
12. Escalation does not open a case in live mode — there is no staff queue behind this
   product. Instead, tell the student to take it to their advisor, and point them at the
   handoff summary on the planner page, which they can copy into an email."""


@dataclass
class AgentResult:
    answer: str
    citations: list[dict[str, Any]]
    decision: InteractionDecision
    intent: str | None
    confidence: str | None
    case_number: str | None
    degraded_modes: list[str]
    iterations: int
    tool_trace: list[dict[str, Any]]
    latency_ms: int
    interaction_id: int


def _next_case_number(session: Session) -> str:
    highest = session.scalar(
        select(func.max(func.split_part(Case.case_number, "-", 2).cast(Integer)))
    )
    return f"PP-{(highest or 1000) + 1}"


def _validate_citations(payload: dict[str, Any], seen: set[str]) -> list[str]:
    return [
        c["source_id"]
        for c in payload.get("citations", [])
        if c.get("source_id") not in seen
    ]


# How many prior turns of conversation to carry. Six is three exchanges — enough for "take
# that elective out" to resolve, short enough that the context stays small and a stale early
# turn cannot outweigh the tools' current answers.
#
# Deliberately not a full thread: the durable state a student cares about (their profile,
# their mission, accepted risks) is already persistent and recomputed on every read, so the
# agent does not need conversation memory to know where things stand. What it needs history
# for is narrower — resolving what "that one" refers to.
MAX_HISTORY_TURNS = 6


def run_agent(
    session: Session,
    *,
    question: str,
    acting_role: UserRole,
    subject_student_id: int | None,
    user_id: int | None = None,
    mode: str = "demo",
    history: list[dict[str, str]] | None = None,
) -> AgentResult:
    started = time.monotonic()
    ctx = ToolContext(
        session=session,
        acting_role=acting_role,
        subject_student_id=subject_student_id,
        user_id=user_id,
        mode=mode,
    )

    subject_line = "no specific student (policy questions only)"
    if subject_student_id is not None:
        student = session.get(Student, subject_student_id)
        if student is not None:
            subject_line = f"student {student.display_name} ({student.student_number})"
    elif ctx.is_live:
        subject_line = (
            "the signed-in student. You can see only the courses they entered themselves; "
            "you have no access to their official record"
        )

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                subject_line=subject_line,
                role=acting_role.value,
                today=datetime.now(UTC).strftime("%Y-%m-%d"),
            )
            + (LIVE_MODE_RULES if ctx.is_live else ""),
        }
    ]

    # Prior turns, plain text only. Earlier tool calls and their results are deliberately
    # NOT replayed: a stale seat count or hold status from two turns ago would sit in
    # context looking exactly as authoritative as this turn's lookup, and the rule that
    # every claim cites a source returned *this* turn would quietly stop holding. History
    # carries what was said; the tools re-establish what is true.
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        text = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and text:
            messages.append({"role": role, "content": text[:4000]})

    messages.append({"role": "user", "content": question})

    tools = schemas_for(ctx) + [SUBMIT_ANSWER_SCHEMA]
    tool_trace: list[dict[str, Any]] = []
    payload: dict[str, Any] | None = None
    citation_retry_used = False
    empty_answer_retry_used = False
    iterations = 0
    tokens = {"input_tokens": 0, "output_tokens": 0}

    while iterations < MAX_ITERATIONS:
        iterations += 1
        force_finish = iterations == MAX_ITERATIONS
        if force_finish:
            # Force completion by narrowing the tool list to submit_answer alone rather
            # than via tool_choice naming a function — Moonshot rejects a named
            # tool_choice when thinking is enabled ("tool_choice 'specified' is
            # incompatible with thinking enabled"), found the hard way by eval case B24.
            call_tools = [SUBMIT_ANSWER_SCHEMA]
            messages.append(
                {
                    "role": "user",
                    "content": "Iteration limit reached. Call submit_answer now with what "
                    "you have — escalate if the evidence is insufficient.",
                }
            )
        else:
            call_tools = tools

        try:
            message, usage = chat(messages, tools=call_tools, tool_choice="auto")
        except Exception as exc:  # noqa: BLE001 — an upstream 4xx/5xx must degrade, not crash
            # Rule 6: the assistant failing is an outcome the user hears about, with a
            # case number — never a bare 500.
            ctx.degraded_modes.add("llm_error")
            payload = {
                "answer": (
                    "The assistant hit a technical problem and could not finish this "
                    "request. It has been routed to a human instead."
                ),
                "intent": Intent.high_stakes.value,
                "citations": [],
                "confidence": "low",
                "escalate": True,
                "escalation": {
                    "category": CaseCategory.general_support.value,
                    "title": "Assistant failed mid-conversation",
                    "summary": (
                        f"Question: {question!r}. The model call failed on iteration "
                        f"{iterations}: {type(exc).__name__}: {str(exc)[:300]}"
                    ),
                },
            }
            break
        tokens["input_tokens"] += usage["input_tokens"] or 0
        tokens["output_tokens"] += usage["output_tokens"] or 0

        if not message.tool_calls:
            # Content without submit_answer is not a legal way to finish; remind and retry.
            messages.append({"role": "assistant", "content": message.content or ""})
            messages.append(
                {
                    "role": "user",
                    "content": "Finish by calling submit_answer with citations, or call another tool first.",
                }
            )
            continue

        messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in message.tool_calls
                ],
            }
        )

        finished = False
        for call in message.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "submit_answer":
                # An empty answer is not a completion, whatever the schema said.
                #
                # `answer` is a required property, and a model can still omit it or send it
                # blank — observed live 2026-08-07, one run in four: submit_answer arrived
                # with no `answer` at all, the loop accepted it, and the turn was written to
                # the audit log as `answered` with `response_text = NULL`. The student got
                # an empty bubble from a system whose own record said it had answered them,
                # which is the silent failure rule 6 exists to prevent.
                #
                # Same shape as the citation check below: one correction round, then treat
                # it as the assistant failing rather than shipping the emptiness onward.
                if not str(args.get("answer") or "").strip():
                    if not empty_answer_retry_used:
                        empty_answer_retry_used = True
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": json.dumps(
                                    {
                                        "error": "empty_answer",
                                        "instruction": (
                                            "submit_answer was called with no answer text. "
                                            "Call it again with the full plain-language "
                                            "answer in the `answer` field."
                                        ),
                                    }
                                ),
                            }
                        )
                        continue
                    ctx.degraded_modes.add("empty_answer")
                    args = {
                        "answer": (
                            "The assistant could not produce an answer to this question, so "
                            "it has been routed to a human instead."
                        ),
                        "intent": args.get("intent", Intent.high_stakes.value),
                        "citations": [],
                        "confidence": "low",
                        "escalate": True,
                        "escalation": {
                            "category": CaseCategory.general_support.value,
                            "title": "Assistant returned an empty answer",
                            "summary": (
                                f"Question: {question!r}. The assistant twice called "
                                "submit_answer with no answer text, so the turn was routed "
                                "to a human rather than shown as an empty reply."
                            ),
                        },
                    }
                    payload = args
                    finished = True
                    break

                bad = _validate_citations(args, ctx.seen_source_ids)
                if bad and not citation_retry_used:
                    # One correction round: name the fabricated ids, demand real ones.
                    citation_retry_used = True
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(
                                {
                                    "error": "invalid_citations",
                                    "unknown_source_ids": bad,
                                    "valid_source_ids": sorted(ctx.seen_source_ids),
                                    "instruction": "Cite only source_ids listed above, or escalate.",
                                }
                            ),
                        }
                    )
                    continue
                if bad:
                    # Second fabrication: the answer cannot be trusted; force escalation.
                    args = {
                        "answer": (
                            "I could not produce a verifiable answer to this question, so I am "
                            "routing it to a human who can review your record directly."
                        ),
                        "intent": args.get("intent", Intent.high_stakes.value),
                        "citations": [],
                        "confidence": "low",
                        "escalate": True,
                        "escalation": {
                            "category": CaseCategory.general_support.value,
                            "title": "Assistant answer failed citation validation",
                            "summary": (
                                f"Question: {question!r}. The assistant twice cited sources that "
                                "were not returned by any tool, so its draft answer was discarded "
                                "rather than shown."
                            ),
                        },
                    }
                payload = args
                finished = True
                break

            impl = tools_for(ctx).get(name)
            # Which source ids this one call put on the table. Captured as a delta because
            # the tools write into a shared set, and without per-call attribution "this
            # lookup was never used" is not a computable statement — the trajectory eval
            # needs to know which call earned which citation, not just that some call did.
            before_sources = set(ctx.seen_source_ids)
            if impl is None:
                result: dict[str, Any] = {"error": f"unknown tool {name!r}"}
            else:
                try:
                    # Inside the real try, so an injected tool failure takes the same path
                    # as a genuine one: a named error handed back to the model, a degraded
                    # mode recorded, and the loop continuing rather than aborting.
                    if faults.armed_for_tool(name):
                        raise faults.InjectedFault(f"injected fault: tool.error:{name}")
                    result = impl(ctx, **args)
                except PermissionError as exc:
                    result = {"error": str(exc)}
                except Exception as exc:  # noqa: BLE001 — the model gets a named failure, not a crash
                    result = {"error": f"{name} failed: {type(exc).__name__}. Try another approach or escalate."}
                    ctx.degraded_modes.add(f"tool_error:{name}")
                    # A tool that failed on a database error leaves the transaction
                    # aborted, and every statement after it fails too — including the
                    # escalation that is supposed to be the safety net. So the net fails
                    # in exactly the case it exists for, and the student gets a 500
                    # instead of a case number. Found by fault injection, not by review.
                    #
                    # Safe to roll back here because the write tools commit as they go:
                    # a mission opened earlier in this turn is already durable, and what
                    # is discarded is the failed statement's own work.
                    session.rollback()

            tool_trace.append(
                {
                    "tool": name,
                    "args": args,
                    "iteration": iterations,
                    "source_ids": sorted(ctx.seen_source_ids - before_sources),
                    "failed": isinstance(result, dict) and "error" in result,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

        if finished:
            break

    # Belt to the braces above: whatever route produced `payload`, an answer with no text
    # in it is not something to show anybody. The check inside the loop is the one that
    # gets a retry and a case; this one exists so that no future edit can open a path to a
    # blank reply without tripping over it.
    if payload is not None and not str(payload.get("answer") or "").strip():
        ctx.degraded_modes.add("empty_answer")
        payload = None

    if payload is None:
        # Loop exhausted without a submit_answer call even under forcing — treat as an
        # outage of the assistant, not a silent nothing.
        payload = {
            "answer": "The assistant could not complete this request. It has been routed to a human.",
            "intent": Intent.high_stakes.value,
            "citations": [],
            "confidence": "low",
            "escalate": True,
            "escalation": {
                "category": CaseCategory.general_support.value,
                "title": "Assistant failed to produce an answer",
                "summary": f"Question: {question!r}. The agent loop ended without a structured answer.",
            },
        }

    # ---- Escalation → a real case with a quotable number.
    case_number: str | None = None
    case_id: int | None = None
    now = datetime.now(UTC)
    # Live mode escalates to the student's own advisor, not into a queue. Opening a case
    # here would promise a staff workflow that does not exist behind this product — the
    # student would wait for a reply that is never coming.
    if payload.get("escalate") and subject_student_id is not None and not ctx.is_live:
        escalation = payload.get("escalation") or {
            "category": CaseCategory.general_support.value,
            "title": "Assistant escalation",
            "summary": f"Question: {question!r}",
        }
        student = session.get(Student, subject_student_id)
        case = Case(
            case_number=_next_case_number(session),
            student_id=subject_student_id,
            owner_user_id=student.advisor_id if student else None,
            category=CaseCategory(escalation["category"]),
            status=CaseStatus.new,
            priority=CasePriority.elevated,
            title=escalation["title"][:200],
            student_message=question,
            ai_summary=escalation["summary"],
            opened_by=ActorKind.ai,
            opened_at=now,
        )
        session.add(case)
        session.flush()
        session.add(
            CaseEvent(
                case_id=case.id,
                actor_kind=ActorKind.ai,
                action="Opened case from assistant escalation",
                note=escalation["summary"],
                to_status=CaseStatus.new,
                occurred_at=now,
            )
        )
        case_number = case.case_number
        case_id = case.id

    # ---- Decision classification for the audit row.
    if payload.get("escalate"):
        decision = InteractionDecision.escalated
    elif ctx.degraded_modes or payload.get("confidence") == "low":
        decision = InteractionDecision.answered_with_caveat
    else:
        decision = InteractionDecision.answered

    latency_ms = int((time.monotonic() - started) * 1000)

    try:
        intent = Intent(payload.get("intent"))
    except ValueError:
        intent = None

    interaction = AiInteraction(
        occurred_at=now,
        user_id=user_id,
        acting_role=acting_role,
        subject_student_id=subject_student_id,
        question=question,
        intent=intent,
        retrieved_chunks=ctx.retrieval_trace or None,
        tool_calls=tool_trace or None,
        prompt_snapshot=json.dumps(messages, ensure_ascii=False, default=str),
        response_text=payload.get("answer"),
        citations=payload.get("citations") or None,
        decision=decision,
        escalation_reason=(payload.get("escalation") or {}).get("title") if payload.get("escalate") else None,
        case_id=case_id,
        degraded_modes=sorted(ctx.degraded_modes) or None,
        model=settings.chat_model,
        input_tokens=tokens["input_tokens"] or None,
        output_tokens=tokens["output_tokens"] or None,
        latency_ms=latency_ms,
        iterations=iterations,
    )
    session.add(interaction)
    session.commit()

    return AgentResult(
        answer=payload.get("answer", ""),
        citations=payload.get("citations", []),
        decision=decision,
        intent=intent.value if intent else None,
        confidence=payload.get("confidence"),
        case_number=case_number,
        degraded_modes=sorted(ctx.degraded_modes),
        iterations=iterations,
        tool_trace=tool_trace,
        latency_ms=latency_ms,
        interaction_id=interaction.id,
    )
