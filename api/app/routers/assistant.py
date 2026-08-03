"""The Ask Albert AI endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import Student, UserRole
from app.services.agent import run_agent
from app.services.llm import LlmNotConfiguredError

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    # Demo-mode identity: replaced by the authenticated session in P5. The subject student
    # is still resolved and scoped server-side — the model never receives an id parameter.
    student_id: int | None = None
    role: UserRole = UserRole.student


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
def ask(payload: AskRequest, session: Session = Depends(get_session)) -> AskResponse:
    if payload.student_id is not None and session.get(Student, payload.student_id) is None:
        raise HTTPException(status_code=404, detail=f"No student with id {payload.student_id}")

    try:
        result = run_agent(
            session,
            question=payload.question,
            acting_role=payload.role,
            subject_student_id=payload.student_id,
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
