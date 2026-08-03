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
from app.services.agent_tools import TOOL_IMPLS, TOOL_SCHEMAS, ToolContext
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

SYSTEM_PROMPT = """You are the UAX academic assistant inside a university student information system.
You help with registration blockers, holds, degree progress, courses, and university policy.

Subject: {subject_line}
Requester role: {role}
Today: {today}

Hard rules, none of which you may relax:
1. Only assert facts returned by your tools in THIS conversation, citing their source_id.
   No training-data answers about this university's policies or this student's record.
2. If a tool marks data stale (is_stale/stale_note), say how old it is and quote the note.
3. High-stakes matters — graduation timing changes, substitutions, appeals, waiving
   prerequisites, clearing holds, payments, academic standing — are decided by humans.
   Explain what you verified, then escalate. Never promise an outcome.
4. You cannot modify any record. You explain and escalate; offices act.
5. If tools cannot verify what the user claims (e.g. "I already submitted it"), do not
   confirm or deny it. Say what you can and cannot see, and escalate if it matters.
6. No legal, medical, immigration, or mental-health advice; those go to a human.
7. Answer in the user's language; keep source quotes in their original language.

Work in small steps: gather evidence with tools (reformulate and search again when a
result misses part of the question), then finish with submit_answer. Cite every claim.
When lookups are independent — e.g. holds, attempts, and a policy search — request them
as multiple tool calls in the SAME turn rather than one per turn; latency matters."""


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
    return f"UAX-{(highest or 1000) + 1}"


def _validate_citations(payload: dict[str, Any], seen: set[str]) -> list[str]:
    return [
        c["source_id"]
        for c in payload.get("citations", [])
        if c.get("source_id") not in seen
    ]


def run_agent(
    session: Session,
    *,
    question: str,
    acting_role: UserRole,
    subject_student_id: int | None,
    user_id: int | None = None,
) -> AgentResult:
    started = time.monotonic()
    ctx = ToolContext(
        session=session, acting_role=acting_role, subject_student_id=subject_student_id
    )

    subject_line = "no specific student (policy questions only)"
    if subject_student_id is not None:
        student = session.get(Student, subject_student_id)
        if student is not None:
            subject_line = f"student {student.display_name} ({student.student_number})"

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                subject_line=subject_line,
                role=acting_role.value,
                today=datetime.now(UTC).strftime("%Y-%m-%d"),
            ),
        },
        {"role": "user", "content": question},
    ]

    tools = TOOL_SCHEMAS + [SUBMIT_ANSWER_SCHEMA]
    tool_trace: list[dict[str, Any]] = []
    payload: dict[str, Any] | None = None
    citation_retry_used = False
    iterations = 0
    tokens = {"input_tokens": 0, "output_tokens": 0}

    while iterations < MAX_ITERATIONS:
        iterations += 1
        force_finish = iterations == MAX_ITERATIONS
        message, usage = chat(
            messages,
            tools=tools,
            tool_choice=(
                {"type": "function", "function": {"name": "submit_answer"}}
                if force_finish
                else "auto"
            ),
        )
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

            impl = TOOL_IMPLS.get(name)
            if impl is None:
                result: dict[str, Any] = {"error": f"unknown tool {name!r}"}
            else:
                try:
                    result = impl(ctx, **args)
                except PermissionError as exc:
                    result = {"error": str(exc)}
                except Exception as exc:  # noqa: BLE001 — the model gets a named failure, not a crash
                    result = {"error": f"{name} failed: {type(exc).__name__}. Try another approach or escalate."}
                    ctx.degraded_modes.add(f"tool_error:{name}")

            tool_trace.append({"tool": name, "args": args, "iteration": iterations})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

        if finished:
            break

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
    if payload.get("escalate") and subject_student_id is not None:
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
