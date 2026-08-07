"""Turning an uploaded file into a reviewable reading, and a confirmed review into a record.

**There is no OCR path, and that is a measured decision rather than a gap.** The extraction
experiment over four synthetic layouts found that text-layer PDFs parse well and a scan is
cleanly detectable — zero extractable characters, unambiguously. Adding OCR would mean a
system binary (tesseract) with Windows install friction, plus a whole class of
character-confusion error modes that would need their own accuracy eval to be trustworthy.
Against that, a scanned upload can be answered honestly today: say the file has no text
layer, say why, and point the student at the text export their student information system
already produces. That answer costs nothing and is true. OCR can come later on evidence that
students actually upload scans, which is the point at which its eval would be worth writing.

The file itself is never stored. It is read from memory, parsed, and dropped — a transcript
is the most sensitive document this product handles, and the reading (course codes and
grades the student is about to confirm anyway) is all that has any downstream use.
"""

from __future__ import annotations

import io

from sqlalchemy.orm import Session

from app.intake.parse import parse_rows
from app.intake.types import ExtractedRow, RowStatus, TranscriptReading
from app.planning.loader import load_catalog_courses

# Generous enough for a multi-page record, small enough that a mis-picked file fails fast.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
# Beyond this the file is not a transcript, and parsing it would be a denial-of-service
# vector dressed as a feature.
MAX_PAGES = 40


class UnreadableUploadError(ValueError):
    """The bytes are not a PDF this reader can open at all."""


def read_transcript(session: Session, data: bytes) -> TranscriptReading:
    """Extract, parse, and classify. Never writes anything."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = reader.pages[:MAX_PAGES]
        text = "\n".join((page.extract_text() or "") for page in pages)
    except (PdfReadError, OSError, ValueError) as exc:
        raise UnreadableUploadError(
            "That file could not be opened as a PDF. If it came from a phone camera or a "
            "scanner, export or print the record to PDF from Albert instead."
        ) from exc

    reading = TranscriptReading(pages=len(pages), extracted_chars=len(text.strip()))

    if not text.strip():
        # The scanned-document case. A distinct, honest answer rather than an empty result
        # that reads as "you have no courses".
        reading.no_text_layer = True
        reading.notes.append(
            "This file has no text layer — it is almost certainly a scan or a photo, and "
            "there is nothing in it to read. Albert can export your record as a text PDF; "
            "that version will work here. You can also enter courses by hand."
        )
        return reading

    catalog = set(load_catalog_courses(session))
    reading.rows = parse_rows(text, catalog=catalog)

    if not reading.rows:
        reading.notes.append(
            "The file was readable but no course codes were found in it. If this is a "
            "transcript, the courses may be in an image; otherwise check you uploaded the "
            "right file."
        )
    if len(reader.pages) > MAX_PAGES:
        reading.notes.append(
            f"Only the first {MAX_PAGES} pages were read."
        )

    counts = reading.counts()
    if counts[RowStatus.needs_review.value]:
        reading.notes.append(
            f"{counts[RowStatus.needs_review.value]} row(s) need your attention before they "
            "can be added — each says why."
        )
    return reading


def confirm_rows(
    session: Session, user_id: int, rows: list[ExtractedRow]
) -> tuple[int, list[str]]:
    """Write accepted rows into the student's self-reported record.

    Goes through the same `upsert_course` the manual form uses, so a transcript-sourced
    course is stored exactly as a hand-entered one: as a claim by the student, with no
    special authority. There is no "imported from transcript" flag, on purpose — the file
    was not verified, so a marker implying it was would be the one thing this whole feature
    must not do.
    """
    from app.services.profile import upsert_course

    written = 0
    skipped: list[str] = []
    for row in rows:
        if not row.confirmable:
            skipped.append(row.raw[:80] or "(unreadable row)")
            continue
        upsert_course(
            session,
            user_id,
            course_code=row.course_code,
            state=row.state,
            term=row.term,
            grade=row.grade,
        )
        written += 1
    return written, skipped


__all__ = [
    "MAX_PAGES",
    "MAX_UPLOAD_BYTES",
    "UnreadableUploadError",
    "confirm_rows",
    "read_transcript",
]
