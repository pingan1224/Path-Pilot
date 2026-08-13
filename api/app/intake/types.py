"""Shapes the transcript reader speaks in.

Same three-outcome discipline as the decoder and the planner, for the same reason: a reader
whose vocabulary is only "here is the course" / "failed to read" has to resolve everything
uncertain into one of those, and both resolutions damage the student. Inventing a course
puts coursework in their record they never took; dropping a row silently makes their degree
audit wrong in the direction that says they need *more* than they do.

    matched       — a course code the loaded catalog contains, with a grade the scale
                    understands or an unambiguous in-progress row
    needs_review  — read, but something about it cannot be settled here: a code outside
                    this catalog, a grade the scale has no place for, a term that the page
                    layout makes ambiguous
    unreadable    — something course-shaped was found and could not be resolved into a
                    course; the raw text is carried so the student can retype it

`needs_review` is the load-bearing one. A cross-school elective, a transfer credit, and a
"S/U" grade are all legitimate and all permanently unresolvable by this tool, and saying so
is the product — the same stance `planning.types.Verdict.unverifiable` takes.

Nothing here is written to the student's record. The reading is a proposal; a separate
student action confirms it, exactly like a mission candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.planning.types import CourseState


class RowStatus(str, Enum):
    matched = "matched"
    needs_review = "needs_review"
    unreadable = "unreadable"


@dataclass(frozen=True)
class ExtractedRow:
    """One candidate course lifted from a transcript."""

    # Normalised to catalog form ("MASY1-GC 1015") when a code was recognisable at all.
    course_code: str | None
    status: RowStatus
    # Everything below is best-effort; each may be absent without invalidating the row.
    title: str | None = None
    term: str | None = None
    credits: float | None = None
    grade: str | None = None
    # What the reader believes the student's relationship to this course is. Never derived
    # from a missing grade alone without saying so in `reasons`.
    state: CourseState = CourseState.completed
    # Why this row is not `matched`, in the student's words. Empty for matched rows.
    reasons: tuple[str, ...] = ()
    # The surrounding text this row was read from, so a wrong reading is checkable and an
    # unreadable one can be retyped.
    raw: str = ""

    @property
    def confirmable(self) -> bool:
        """Whether this row could be written into the profile if the student accepts it."""
        return self.course_code is not None and self.status is not RowStatus.unreadable


@dataclass
class TranscriptReading:
    """Everything read from one uploaded file."""

    rows: list[ExtractedRow] = field(default_factory=list)
    pages: int = 0
    # Characters of extractable text. Zero is the scanned-document signal, and it is a
    # reliable one — see intake/service.py on why no OCR path exists yet.
    extracted_chars: int = 0
    # Set when the file has no text layer at all. Distinguished from "read it and found no
    # courses", which is a different problem with a different answer.
    no_text_layer: bool = False
    # The rows came from an image, so none of them is `matched` and the student is told the
    # characters are a guess. Surfaced to the client because the review screen should look
    # different when nothing on it can be batch-confirmed.
    read_by_ocr: bool = False
    # Image reading was attempted and failed. Separate from `no_text_layer`: the file was a
    # photo *and* the reader was down, which is a temporary condition worth retrying rather
    # than a permanent property of the file.
    ocr_degraded: bool = False
    # Reader-level caveats, as opposed to per-row ones.
    notes: list[str] = field(default_factory=list)
    disclaimer: str = (
        "Read from the file you uploaded, not from Albert. Nothing is added to your record "
        "until you confirm it, and anything this tool could not settle is marked for you to "
        "check."
    )

    def counts(self) -> dict[str, int]:
        out = {status.value: 0 for status in RowStatus}
        for row in self.rows:
            out[row.status.value] += 1
        return out
