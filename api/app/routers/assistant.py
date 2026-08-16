"""The Ask Albert AI endpoint."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import UserRole
from app.services.agent import run_agent
from app.services.artifacts import ArtifactOut, build_artifacts, specs_from_trace
from app.services.auth import Identity, current_user
from app.services.llm import LlmNotConfiguredError

router = APIRouter(prefix="/assistant", tags=["assistant"])


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    """The question, plus prior conversation text.

    `student_id` and `role` used to be fields here. They are gone on purpose: while the
    caller supplied their own role, every permission check downstream — the retrieval
    pre-filter, the tool layer's subject scoping — was validating a claim the caller made
    about themselves. Identity now comes from the signed session and only from there.

    `history` is client-supplied and therefore untrusted, which is fine for what it is: it
    reaches the model as conversation text and nothing else. It grants no data access —
    every fact still has to come from a tool call scoped by the session — so the worst a
    forged history can do is mislead the model about what was said earlier, which a user
    can already do by typing it. Tool calls and their results are never replayed from it.
    """

    question: str = Field(min_length=2, max_length=2000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=20)


class CitationOut(BaseModel):
    claim: str
    source_id: str


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    decision: str
    intent: str | None
    confidence: str | None
    # Present when the turn deferred: {office, question, bring}. Replaces `case_number`,
    # which named a ticket nobody ever received.
    referral: dict | None
    degraded_modes: list[str]
    iterations: int
    # What the UI should render, said outright — see services/artifacts.py. `tool_trace`
    # below is the audit record and nothing else; clients must not infer cards from it.
    artifacts: list[ArtifactOut]
    tool_trace: list[dict]
    latency_ms: int
    interaction_id: int


@router.post("/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> AskResponse:
    # A seeded fixture student has invented-but-consistent holds and registration history,
    # so the record tools answer meaningfully. A real account has none of that, and the
    # same tools would answer emptily — which reads as "your record is clear".
    mode = "demo" if identity.subject_student_id is not None else "live"

    try:
        result = run_agent(
            session,
            question=payload.question,
            acting_role=identity.role,
            subject_student_id=identity.subject_student_id,
            user_id=identity.user.id,
            mode=mode,
            history=[t.model_dump() for t in payload.history],
        )
    except LlmNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    artifacts = build_artifacts(
        session,
        identity,
        specs_from_trace(
            result.tool_trace, student_caller=identity.role == UserRole.student
        ),
    )

    return AskResponse(
        answer=result.answer,
        citations=[CitationOut(**c) for c in result.citations],
        decision=result.decision.value,
        intent=result.intent,
        confidence=result.confidence,
        referral=result.referral,
        degraded_modes=result.degraded_modes,
        iterations=result.iterations,
        artifacts=artifacts,
        tool_trace=result.tool_trace,
        latency_ms=result.latency_ms,
        interaction_id=result.interaction_id,
    )
