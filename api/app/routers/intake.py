"""Transcript upload: read a file, propose what it contains, let the student confirm.

Two endpoints and a deliberate gap between them. `POST /intake/transcript` reads and returns;
it writes nothing and keeps nothing. `POST /intake/confirm` takes rows the student has
reviewed and writes them into their own self-reported record. Nothing crosses that gap
automatically — the same propose/confirm shape as a mission candidate, for the same reason.

The uploaded bytes are never persisted. A transcript is the most sensitive document this
product will ever be handed, and there is no feature that needs it after parsing.

Confirmation re-validates every field rather than trusting the client's echo of what the
reader said. The rows come back through the browser, so treating them as authoritative would
let a caller write an arbitrary course, term, and grade into their record by editing the
payload — which is, in fairness, exactly what the manual form already permits, but the
validation belongs here regardless: the profile's own rules (a grade only means something on
a completed course) must hold whichever door the data came through.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.intake import (
    MAX_UPLOAD_BYTES,
    UnreadableUploadError,
    confirm_rows,
    read_transcript,
)
from app.intake.types import ExtractedRow, RowStatus
from app.models import UserRole
from app.planning.types import CourseState
from app.services.auth import Identity, require_roles

router = APIRouter(prefix="/intake", tags=["intake"])

student_only = require_roles(UserRole.student)


class RowOut(BaseModel):
    course_code: str | None
    status: str
    term: str | None
    credits: int | None
    grade: str | None
    state: str
    reasons: list[str]
    raw: str
    confirmable: bool


class ReadingOut(BaseModel):
    pages: int
    extracted_chars: int
    no_text_layer: bool
    # The rows came from an image. The review screen must look different: nothing here can
    # be batch-confirmed, and the student is being asked to check characters, not just
    # course choices.
    read_by_ocr: bool
    # Image reading was attempted and failed — a temporary condition, worth a retry, as
    # opposed to a file that can never be read.
    ocr_degraded: bool
    counts: dict[str, int]
    rows: list[RowOut]
    notes: list[str]
    disclaimer: str


def _row_out(row: ExtractedRow) -> RowOut:
    return RowOut(
        course_code=row.course_code,
        status=row.status.value,
        term=row.term,
        credits=row.credits,
        grade=row.grade,
        state=row.state.value,
        reasons=list(row.reasons),
        raw=row.raw,
        confirmable=row.confirmable,
    )


@router.post("/transcript", response_model=ReadingOut)
async def post_transcript(
    file: UploadFile = File(...),
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> ReadingOut:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="file: the upload was empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"file: that file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. "
                "A transcript export is normally well under that."
            ),
        )

    try:
        reading = read_transcript(session, data)
    except UnreadableUploadError as exc:
        raise HTTPException(status_code=422, detail=f"file: {exc}") from exc
    # ProgramNotEncodedError deliberately propagates — see main.py.

    return ReadingOut(
        pages=reading.pages,
        extracted_chars=reading.extracted_chars,
        no_text_layer=reading.no_text_layer,
        read_by_ocr=reading.read_by_ocr,
        ocr_degraded=reading.ocr_degraded,
        counts=reading.counts(),
        rows=[_row_out(r) for r in reading.rows],
        notes=reading.notes,
        disclaimer=reading.disclaimer,
    )


class ConfirmRow(BaseModel):
    course_code: str = Field(min_length=3, max_length=24)
    state: CourseState
    term: str | None = Field(default=None, max_length=16)
    grade: str | None = Field(default=None, max_length=4)

    @field_validator("course_code")
    @classmethod
    def normalise(cls, value: str) -> str:
        return " ".join(value.strip().upper().split())


class ConfirmIn(BaseModel):
    rows: list[ConfirmRow] = Field(min_length=1, max_length=100)


class ConfirmOut(BaseModel):
    written: int
    skipped: list[str]


@router.post("/confirm", response_model=ConfirmOut)
def post_confirm(
    payload: ConfirmIn,
    identity: Identity = Depends(student_only),
    session: Session = Depends(get_session),
) -> ConfirmOut:
    rows = [
        ExtractedRow(
            course_code=row.course_code,
            # Everything arriving here has been through the student's review, so the status
            # is no longer a claim about readability — it is simply confirmable.
            status=RowStatus.matched,
            term=row.term,
            # A grade only means something on a finished course. `upsert_course` enforces
            # this too; doing it here as well means the rule holds even if that path changes.
            grade=row.grade if row.state is CourseState.completed else None,
            state=row.state,
        )
        for row in payload.rows
    ]
    written, skipped = confirm_rows(session, identity.user.id, rows)
    return ConfirmOut(written=written, skipped=skipped)
