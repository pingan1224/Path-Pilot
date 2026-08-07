"""Turning an uploaded file into a reviewable reading, and a confirmed review into a record.

**Two channels, and the difference between them is trust, not plumbing.**

A text-layer PDF *states* its characters, so a row read from one can be `matched` and
confirmed in a batch. A photo or a scan only *suggests* them, and it suggests them worst for
exactly the characters a transcript is made of — `B`/`8`, `0`/`O`, `A-`/`A`. So every row
that arrived through OCR is forced to `needs_review` here, structurally, whatever the parser
concluded (`_as_reviewed`). There is deliberately no confidence threshold that promotes one:
a score from a model that cannot see the original is a statement about its own certainty,
not about the transcript. A student clicking through four rows is a small cost; a misread
grade entering a degree audit is silent and permanent, and `silently_wrong` is gated at zero
for a reason.

The OCR path was built after the product decision that students will photograph their
transcripts whatever the upload form says — which is true, and the previous behaviour was
worse than "no OCR": a `.jpg` could not even be opened, so the most likely real upload got
the least useful answer in the product. See `app/intake/ocr.py`, including why the image is
sent to a vision endpoint rather than read by a local tesseract, and what that costs.

The file itself is never stored. It is read from memory, parsed, and dropped — a transcript
is the most sensitive document this product handles, and the reading (course codes and
grades the student is about to confirm anyway) is all that has any downstream use. The one
exception to "nothing leaves" is the OCR call itself, which is disclosed to the student
before they choose to upload an image.
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
# OCR is a paid call per page, so a scanned upload reads fewer pages than a text one. A
# transcript that needs more than four scanned pages is better served by the text export.
OCR_MAX_PAGES = 4


class UnreadableUploadError(ValueError):
    """The bytes are not a PDF this reader can open at all."""


# JPEG, PNG, WebP, GIF, and the HEIC/HEIF container a modern iPhone produces. Sniffed from
# the bytes rather than taken from the filename or the browser's content-type, both of which
# are the caller's opinion.
_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def sniff_image(data: bytes) -> str | None:
    """The image MIME type these bytes actually are, or None if they are not an image."""
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # HEIC/HEIF: an ISO-BMFF box whose brand says heic/heif/mif1.
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"heif", b"mif1", b"msf1"):
        return "image/heic"
    return None


def _as_reviewed(rows: list[ExtractedRow], why: str) -> list[ExtractedRow]:
    """Force every row to needs_review. The OCR trust boundary, applied structurally.

    A function rather than a flag threaded through the parser, so there is exactly one place
    where an OCR row could ever become `matched` and it is this one refusing to let it. An
    `unreadable` row stays unreadable — it is already saying something weaker.
    """
    import dataclasses

    out = []
    for row in rows:
        if row.status is RowStatus.unreadable:
            out.append(row)
            continue
        out.append(
            dataclasses.replace(
                row,
                status=RowStatus.needs_review,
                reasons=tuple(dict.fromkeys((*row.reasons, why))),
            )
        )
    return out


OCR_ROW_REASON = (
    "Read from an image, so the characters are a best guess — check the code and grade "
    "against your transcript before adding it."
)


def read_transcript(session: Session, data: bytes) -> TranscriptReading:
    """Extract, parse, and classify. Never writes anything."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    mime = sniff_image(data)
    if mime is not None:
        return _read_photo(session, data, mime=mime)

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = reader.pages[:MAX_PAGES]
        text = "\n".join((page.extract_text() or "") for page in pages)
    except (PdfReadError, OSError, ValueError) as exc:
        raise UnreadableUploadError(
            "That file could not be opened. Upload a PDF, or a photo of your transcript "
            "as a JPEG, PNG, or HEIC image."
        ) from exc

    reading = TranscriptReading(pages=len(pages), extracted_chars=len(text.strip()))

    if not text.strip():
        # No text layer: a scan, saved as a PDF. The page images are what the student
        # actually has, so read those rather than refusing outright.
        reading.no_text_layer = True
        return _read_scanned_pdf(session, pages, reading)

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


NO_TEXT_LAYER_FALLBACK = (
    "This file is a scan or a photo, and reading images is unavailable right now, so there "
    "is nothing here that can be read. Albert can export your record as a text PDF, which "
    "always works — or you can enter courses by hand."
)


def _finish_ocr(
    session: Session, text: str, reading: TranscriptReading
) -> TranscriptReading:
    """Parse OCR text into rows that can never be `matched`."""
    catalog = set(load_catalog_courses(session))
    reading.rows = _as_reviewed(parse_rows(text, catalog=catalog), OCR_ROW_REASON)
    reading.read_by_ocr = True
    reading.extracted_chars = len(text.strip())

    if not reading.rows:
        reading.notes.append(
            "The image was read but no course codes were found in it. If the photo is "
            "blurry or cropped, retake it with the whole page in frame — or upload the "
            "text PDF Albert exports."
        )
    else:
        reading.notes.append(
            f"Read from an image, so all {len(reading.rows)} row(s) need checking before "
            "they can be added. Character-level mistakes are the risk here: confirm each "
            "course code and grade against the original."
        )
    return reading


def _read_photo(session: Session, data: bytes, *, mime: str) -> TranscriptReading:
    from app.intake.ocr import OcrUnavailableError, read_image

    reading = TranscriptReading(pages=1, extracted_chars=0)
    try:
        text = read_image(data, mime=mime)
    except OcrUnavailableError as exc:
        # Rule 6: degrade to the answer that existed before OCR, never to an empty reading
        # — "no courses found" would read as a fact about the student's record.
        reading.no_text_layer = True
        reading.ocr_degraded = True
        reading.notes.append(NO_TEXT_LAYER_FALLBACK)
        reading.notes.append(f"(Image reading failed: {exc})")
        return reading
    return _finish_ocr(session, text, reading)


def _read_scanned_pdf(session: Session, pages, reading: TranscriptReading) -> TranscriptReading:
    """A PDF with no text layer: read the page images it embeds.

    A scanner writes one image per page, so `page.images` is the scan itself. A PDF whose
    pages are drawn as vectors has no images to find, and that genuinely cannot be read —
    the pre-OCR refusal is the right answer there and is what this returns.
    """
    from app.intake.ocr import OcrUnavailableError, read_image

    chunks: list[str] = []
    for page in pages[:OCR_MAX_PAGES]:
        try:
            images = list(page.images)
        except Exception:  # noqa: BLE001 — a malformed embedded image is not a crash
            images = []
        if not images:
            continue
        largest = max(images, key=lambda item: len(item.data))
        try:
            chunks.append(read_image(largest.data, mime="image/jpeg"))
        except OcrUnavailableError as exc:
            reading.ocr_degraded = True
            reading.notes.append(NO_TEXT_LAYER_FALLBACK)
            reading.notes.append(f"(Image reading failed: {exc})")
            return reading

    if not chunks:
        reading.notes.append(
            "This file has no text layer and no page images to read — it is almost "
            "certainly a vector scan. Albert can export your record as a text PDF; that "
            "version will work here. You can also enter courses by hand."
        )
        return reading

    return _finish_ocr(session, "\n".join(chunks), reading)


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
