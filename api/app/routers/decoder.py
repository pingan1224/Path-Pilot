"""Decode a registration error the student pastes in.

This is the one feature in UAX that is useful on first contact. Everything else on the
planner asks for a dozen courses first, and a student who is stuck at the registration
screen right now will not enter a dozen courses to find out what `ERR_PREREQ` means.

Open to any signed-in role rather than students only, and that is safe by construction:
the record cross-check reads `identity.user.id`'s own self-reported courses, so an
advisor decoding a message a student forwarded gets the policy reading with an empty
record check — never somebody else's coursework. The retrieval role filter is the
caller's own role, so the corpus boundary holds per role as everywhere else.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.decoder import decode
from app.decoder.patterns import BY_REASON
from app.services.auth import Identity, current_user

router = APIRouter(prefix="/decoder", tags=["decoder"])


class DecodeRequest(BaseModel):
    text: str = Field(min_length=2, max_length=4000)
    # Replies to follow-up questions from a previous decode. Appended to the message and
    # classified together — see decoder.service.decode on why this is not session state.
    answers: list[str] = Field(default_factory=list, max_length=6)


class EvidenceOut(BaseModel):
    kind: str
    pattern: str
    matched: str
    start: int
    end: int


class CandidateOut(BaseModel):
    reason: str
    label: str
    score: int
    evidence: list[EvidenceOut]


class ExtractedOut(BaseModel):
    course_codes: list[str]
    class_numbers: list[str]
    hold_codes: list[str]
    term: str | None


class FollowUpOut(BaseModel):
    question: str
    why: str
    discriminates: list[str]
    fills: str | None


class PassageOut(BaseModel):
    source_id: str
    explains: str
    document: str
    section: str | None
    text: str
    url: str
    office: str
    verified_at: str


class RecordCheckOut(BaseModel):
    performed: bool
    basis: str
    findings: list[dict]
    note: str | None


class DecodeResponse(BaseModel):
    outcome: str
    reason: str | None
    reason_label: str | None
    confidence: str
    reading: str | None
    what_to_do: list[str]
    responsible_office: str | None
    candidates: list[CandidateOut]
    extracted: ExtractedOut
    follow_ups: list[FollowUpOut]
    passages: list[PassageOut]
    record_check: RecordCheckOut | None
    albert: dict | None
    no_policy_note: str | None
    degraded: list[str]
    text_used: str
    disclaimer: str


@router.post("/decode", response_model=DecodeResponse)
def post_decode(
    payload: DecodeRequest,
    identity: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> DecodeResponse:
    result = decode(
        session,
        payload.text,
        role=identity.role.value,
        user_id=identity.user.id,
        answers=payload.answers,
    )
    classification = result.classification

    return DecodeResponse(
        outcome=classification.outcome.value,
        reason=classification.reason.value if classification.reason else None,
        reason_label=(
            BY_REASON[classification.reason].label if classification.reason else None
        ),
        confidence=classification.confidence,
        reading=result.reading,
        what_to_do=list(result.what_to_do),
        responsible_office=result.responsible_office,
        candidates=[
            CandidateOut(
                reason=c.reason.value,
                label=BY_REASON[c.reason].label,
                score=c.score,
                evidence=[
                    EvidenceOut(
                        kind=e.kind.value,
                        pattern=e.pattern,
                        matched=e.matched,
                        start=e.start,
                        end=e.end,
                    )
                    for e in c.evidence
                ],
            )
            for c in classification.candidates
        ],
        extracted=ExtractedOut(
            course_codes=list(classification.extracted.course_codes),
            class_numbers=list(classification.extracted.class_numbers),
            hold_codes=list(classification.extracted.hold_codes),
            term=classification.extracted.term,
        ),
        follow_ups=[
            FollowUpOut(
                question=f.question,
                why=f.why,
                discriminates=[r.value for r in f.discriminates],
                fills=f.fills,
            )
            for f in classification.follow_ups
        ],
        passages=[PassageOut(**p) for p in result.passages],
        record_check=(
            RecordCheckOut(
                performed=result.record_check.performed,
                basis=result.record_check.basis,
                findings=result.record_check.findings,
                note=result.record_check.note,
            )
            if result.record_check
            else None
        ),
        albert=result.albert,
        no_policy_note=result.no_policy_note,
        degraded=result.degraded,
        text_used=result.text_used,
        disclaimer=result.disclaimer,
    )
