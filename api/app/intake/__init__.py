"""Transcript intake: read an uploaded record, propose it, let the student confirm it.

The friction this removes is the largest in the product — entering a dozen courses by hand
before any other view can say anything — and it removes it without changing what the data
*is*. A course read from a transcript enters `profile_courses` as a self-reported claim,
identical to one typed in, because the file was never verified either.

- `types.py`   — three-outcome rows: matched / needs_review / unreadable
- `parse.py`   — course-code-anchored parsing, pure functions over extracted text
- `service.py` — PDF bytes in, reading out; and confirmed rows into the profile
"""

from app.intake.parse import parse_rows
from app.intake.service import (
    MAX_PAGES,
    MAX_UPLOAD_BYTES,
    UnreadableUploadError,
    confirm_rows,
    read_transcript,
)
from app.intake.types import ExtractedRow, RowStatus, TranscriptReading

__all__ = [
    "MAX_PAGES",
    "MAX_UPLOAD_BYTES",
    "ExtractedRow",
    "RowStatus",
    "TranscriptReading",
    "UnreadableUploadError",
    "confirm_rows",
    "parse_rows",
    "read_transcript",
]
