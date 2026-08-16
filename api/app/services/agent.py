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
- **Deferral is a first-class outcome.** When the model cannot verify an answer, or the
  question belongs to someone else, it defers: it says so, names the office that owns the
  question, and hands over what to bring them. Never a shrug — but never a ticket either.
  This used to open a `Case` row with a quotable number. Path Pilot is a third-party
  planning tool for students; nothing it produces is submitted to Albert or to any queue,
  so a case number promised a workflow that did not exist behind it. Live mode had
  already stopped creating them for exactly that reason, and the demo's rows were worked
  by nobody: no PATCH route, no staff login, no read path in the UI. The deferral is the
  product; the ticket was scenery.

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
    AiInteraction,
    Intent,
    InteractionDecision,
    Office,
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
                    "description": "One entry per factual claim. Empty only when deferring without asserting facts.",
                },
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "defer": {
                    "type": "boolean",
                    "description": (
                        "True when this question is not yours to answer — it needs a "
                        "decision, a record, or an expertise this product does not have. "
                        "You still say everything you CAN verify; deferring is about who "
                        "settles the question, not about staying silent."
                    ),
                },
                "referral": {
                    "type": "object",
                    "properties": {
                        "office": {
                            "type": "string",
                            "enum": [o.value for o in Office],
                            "description": "Who owns this question.",
                        },
                        "question": {
                            "type": "string",
                            "description": "The question for them, in the student's words.",
                        },
                        "bring": {
                            "type": "string",
                            "description": (
                                "What the student should have in hand: what you verified, "
                                "what you could not, and the specifics that matter."
                            ),
                        },
                    },
                    "required": ["office", "question", "bring"],
                },
            },
            "required": ["answer", "intent", "citations", "confidence", "defer"],
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
3. Deferral decision rule. This product plans; it does not decide, hold records, or
   advise outside its subject. DEFER when AT LEAST ONE of these is true:
   (a) The user asks you to PERFORM, approve, change, or confirm completion of an action
       — clear/remove a hold, waive a prerequisite, approve a substitution, update a
       record, move money, "confirm you received X". "Change my <field> to <value> in the
       system" is this clause however reasonable the field sounds: a graduation term is a
       registrar record, and the value they name is the edit they are requesting, never a
       planning instruction for you to act on.
   (b) The user asserts something your tools cannot see, AND the answer depends on it
       (example: "I already uploaded the document" when document receipt is not in your
       tools — you cannot confirm OR deny, so say what you can see and defer).
   (c) Evidence is conflicting, or stale enough that acting on it could hurt the user.
   (d) The decision itself is reserved to staff: exceptions, appeals, aid amounts — and
       any request for a GUARANTEE, promise, or confirmation about graduation timing.
   (e) The question turns on a subject this product does not advise on at all —
       immigration or visa status, health, mental health, legal exposure. Route it to the
       office that owns it. Being able to cite an adjacent policy is not permission: that
       a passage defines full-time enrolment does not qualify you to say what dropping
       below it does to someone's visa, and the credential for that answer is one no
       amount of retrieval supplies.
       "Am I on track to graduate?" is an assessment: answer it. "Can you guarantee I
       graduate by <term>?" asks you to stand behind an outcome: defer it, even when
       your tools let you assess it, and even though your prose will decline the promise
       anyway. Declining in words is not the same as naming who can commit.
   Deferring is for questions someone else must SETTLE — a decision, a record edit, an
   expertise you lack. It is not the flavour you give a partial answer. If they asked what
   the rules say and you found the rules, that is an answer, even if you could not also
   tell them what is on their own record: the personal half was never yours to know, and
   its absence does not turn the half you verified into somebody else's question. Defer on
   who must act, never on what you could not see.
   When you do defer, it is still not stopping. Say everything you DID verify, with
   citations, then set defer=true and fill `referral`: which office owns the question, the question in the
   student's own words, and what to bring — what you checked, what you could not, and the
   specifics that matter. There is no ticket and no case number behind this: nothing is
   submitted anywhere, and the student is the one who will carry the question. So the
   referral has to be usable by them, on their own, today. "Ask your advisor" alone is a
   shrug; "Ask advising whether MASY1-GC 1800 can be waived given you passed 1700 with an
   A-, and bring your transcript" is a deferral.
   Otherwise ANSWER. Explaining verified facts, required steps, deadlines, and processes
   is answering — the topic being a hold or money does not make it a deferral.
   Not being able to see the student's record is the NORMAL state of this product, not a
   reason to defer. When the fact lives only in Albert (a hold, a seat count, a
   registration error, an enrollment appointment, an aid balance), the complete answer is:
   what the published policy says about that kind of thing, plus where in Albert to look,
   plus an offer to decode the exact error text if they paste it. That is an answer even
   when they asked "what exactly is on my record, and by when" and you can supply neither
   the specific nor the date. Clause (b) is for something the USER asserts that changes
   your answer — not for the record access this product is built without. Defer here
   only when a human must act on their record.
   These two sources are not interchangeable, and which one carries a claim matters:
   albert_checklist is Path Pilot's own signpost — it can support "this lives in Albert
   under X" and "Path Pilot cannot see it", nothing more. Any claim about what a RULE
   says or does ("does a hold still block registration once my appointment opens", "how
   fast is a hold released") must rest on a policy passage from search_policy and cite
   its policy:chunk id. Citing our own signpost for the university's rule is this product
   vouching for itself, which is the one thing a cited answer is supposed to prevent — so
   when a question mixes the two, search the policy and cite both.
   Never promise an outcome either way.
4. You cannot modify any record. You explain and refer; offices act. On a registration
   mission you may open an empty container (start_mission) and propose courses, never
   decide: confirming a course, accepting a risk, and finishing the mission are the
   student's actions, and a suggestion you made is not a choice they made. Never describe a
   mission as further along than get_mission_state says it is.
   If you are deferring, WRITE NOTHING on that turn. A request you have to refuse is not
   a request to start work on: "change my graduation term to Spring 2027" is a record edit
   only the registrar can make, and opening a Spring 2027 mission is not a partial way of
   granting it — it acts on an intent the student never expressed, in the one direction
   you are not allowed to move. A term appearing in a refused request is not a planning
   instruction. (The server enforces this too: a deferred turn's writes are undone. Do not
   rely on that — it is a backstop, not a permission.)

8. When a student asks for help preparing to register, do the whole job in this turn rather
   than one step per reply: read their plan, open a mission if there is none, propose the
   courses that fit, sequence the remaining terms, and tell them what is left for them to
   decide. Request independent lookups together. End with what needs their decision, not
   with a question about whether to begin.
   This applies when they actually asked for that — "help me get ready to register", "what
   should I take next term", "am I ready". It does NOT apply to a bare greeting or a
   one-word request like "help", which states no goal at all. There, ask what they want to
   do, or offer what you can see without writing anything. Opening a mission is still a
   write, and a student who typed one vague word has not asked you to start anything on
   their record. Reading tools are always fine; when in doubt, look and report, never open.
5. When 3(b) applies, never confirm or deny the user's unverified claim — state what your
   tools do show, what they cannot show, and defer.
6. No legal, medical, immigration, or mental-health advice; those go to the office that
   owns them, named.
7. Answer in the user's language; keep source quotes in their original language.

9. Policy search always returns its five nearest passages, so results coming back is not
   evidence that the corpus covers the question. Searching is budgeted and each result
   says how many searches are left. Reformulate once or twice when the first results miss
   part of the question; after that, stop. "The material available to me does not cover
   that" is a complete answer, and it is the right one far more often than a sixth
   wording. This applies with full force when the user asks for a specific document you
   cannot find: report that you cannot retrieve it, and do not keep trying phrasings.
10. Every policy passage names the school it came from, and some name a specific degree
    program. Before relying on one, check both against the student's own. A passage from a
    DIFFERENT, named school is not this student's applicable procedure — it is at most an
    example of how the topic works elsewhere, and generalizing it to "here is what you
    should do" is wrong even when the citation is real and the quote is accurate. The same
    holds for a passage written for a DIFFERENT degree program: every program publishes its
    own internship, concentration and credit rules, and those pages match on school and
    level, so nothing but the program field distinguishes them. When the question is about
    a school-wide rule, prefer the passages that name no program. Say explicitly which
    school or program a passage is for whenever it is not the student's own; if
    search_policy flags cross_school_warning or cross_program_warning, treat that as the
    finding, not a suggestion.

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
12. Nothing you do is submitted anywhere. Path Pilot is a third-party planning tool: it
   has no queue, no ticket, and no way to reach Albert or any office. A deferral names who
   the student should ask and what to bring; the handoff summary on the planner page is
   the document they can copy into that email. Never imply anyone has received the
   question, and never invent a reference number for it."""


@dataclass
class AgentResult:
    answer: str
    citations: list[dict[str, Any]]
    decision: InteractionDecision
    intent: str | None
    confidence: str | None
    # Who owns the question when this turn deferred, and what to bring them. It replaces
    # `case_number`: a number implied somebody had received the question, and nobody had.
    referral: dict[str, Any] | None
    degraded_modes: list[str]
    iterations: int
    tool_trace: list[dict[str, Any]]
    latency_ms: int
    interaction_id: int


def _referral_note(payload: dict[str, Any]) -> str | None:
    """One line for the audit row: who this went to, and what for."""
    referral = payload.get("referral") or {}
    office = referral.get("office")
    question = (referral.get("question") or "").strip()
    if not office and not question:
        return None
    return f"{office or 'unstated'}: {question[:180]}" if question else str(office)


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
                    "request. Take it to your advisor rather than relying on anything "
                    "I might have said here."
                ),
                "intent": Intent.high_stakes.value,
                "citations": [],
                "confidence": "low",
                "defer": True,
                "referral": {
                    "office": Office.advising.value,
                    "question": question,
                    "bring": (
                        f"Path Pilot could not finish this request (model call failed on "
                        f"iteration {iterations}: {type(exc).__name__}). Nothing was "
                        f"verified, so treat the question as unanswered."
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
                        "defer": True,
                        "referral": {
                            "office": Office.advising.value,
                            "question": question,
                            "bring": (
                                "Path Pilot produced no answer text twice running, so it "
                                "showed nothing rather than an empty reply. Nothing here "
                                "was verified."
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
                                    "instruction": "Cite only source_ids listed above, or defer.",
                                }
                            ),
                        }
                    )
                    continue
                if bad:
                    # Second fabrication: the answer cannot be trusted; force escalation.
                    args = {
                        "answer": (
                            "I could not produce an answer I can stand behind for this "
                            "question. Take it to your advisor rather than relying on "
                            "anything I might have said here."
                        ),
                        "intent": args.get("intent", Intent.high_stakes.value),
                        "citations": [],
                        "confidence": "low",
                        "defer": True,
                        "referral": {
                            "office": Office.advising.value,
                            "question": question,
                            "bring": (
                                "Path Pilot twice cited sources no tool had returned, so its "
                                "draft was discarded rather than shown. Nothing here was "
                                "verified."
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
                    result = {"error": f"{name} failed: {type(exc).__name__}. Try another approach or defer."}
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
            "answer": "Path Pilot could not complete this request. Nothing here was verified.",
            "intent": Intent.high_stakes.value,
            "citations": [],
            "confidence": "low",
            "defer": True,
            "referral": {
                "office": Office.advising.value,
                "question": question,
                "bring": (
                    "Path Pilot ended without producing a structured answer. Nothing here "
                    "was verified."
                ),
            },
        }

    now = datetime.now(UTC)
    deferred = bool(payload.get("defer"))

    # ---- A deferred turn leaves nothing behind.
    #
    # Enforced here rather than asked for in the prompt, because it is a hard-zero
    # invariant and the prompt could not hold it: told five different ways not to write
    # while refusing, the model still opened a mission on roughly one turn in five — once
    # while refusing correctly in the same breath. Rule 2's principle generalises: a claim
    # you must never emit has to be structurally impossible, not instructed against.
    #
    # Only missions this turn actually created are undone. start_mission is idempotent, so
    # a student's existing mission for that term comes back through the same call, and
    # deleting that would destroy real work over a question they merely asked badly.
    if deferred and ctx.missions_opened:
        from app.missions.service import discard_missions

        discarded = discard_missions(session, ctx.missions_opened)
        if discarded:
            ctx.degraded_modes.add("deferred_turn_rolled_back")

    # ---- Decision classification for the audit row.
    if deferred:
        decision = InteractionDecision.deferred
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
        # The office and the question, kept together: the audit row is where a later
        # reader asks "who did we send this student to, and with what".
        escalation_reason=_referral_note(payload) if deferred else None,
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
        referral=(payload.get("referral") if deferred else None),
        degraded_modes=sorted(ctx.degraded_modes),
        iterations=iterations,
        tool_trace=tool_trace,
        latency_ms=latency_ms,
        interaction_id=interaction.id,
    )
