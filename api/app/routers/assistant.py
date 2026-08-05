"""The Ask Albert AI endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.services.agent import run_agent
from app.services.auth import Identity, current_user
from app.services.llm import LlmNotConfiguredError

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AskRequest(BaseModel):
    """The question, and nothing else.

    `student_id` and `role` used to be fields here. They are gone on purpose: while the
    caller supplied their own role, every permission check downstream — the retrieval
    pre-filter, the tool layer's subject scoping — was validating a claim the caller made
    about themselves. Identity now comes from the signed session and only from there.
    """

    question: str = Field(min_length=2, max_length=2000)


class CitationOut(BaseModel):
    claim: str
    source_id: str


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    decision: str
    intent: str | None
    confidence: str | None
    case_number: str | None
    degraded_modes: list[str]
    iterations: int
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
        )
    except LlmNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return AskResponse(
        answer=result.answer,
        citations=[CitationOut(**c) for c in result.citations],
        decision=result.decision.value,
        intent=result.intent,
        confidence=result.confidence,
        case_number=result.case_number,
        degraded_modes=result.degraded_modes,
        iterations=result.iterations,
        tool_trace=result.tool_trace,
        latency_ms=result.latency_ms,
        interaction_id=result.interaction_id,
    )
