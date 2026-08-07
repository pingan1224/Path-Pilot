"""The OCR trust boundary, and the file-type sniffing that leads to it.

No vision calls here — these are the invariants that must hold without spending anything,
and the one that matters is negative: **there is no input for which an OCR-derived row
becomes `matched`**. The accuracy of the reading itself is measured in `eval/intake_cases.py`
(T07-T09), where it costs money and is allowed to be imperfect.

The measured reason this boundary exists: on a downscaled JPEG the reader returns `A-` for a
course the page grades `A`, reproducibly, three runs out of three. Nothing in the reading
looks different when it does.
"""

import pytest

from app.intake.service import OCR_ROW_REASON, _as_reviewed, sniff_image
from app.intake.types import ExtractedRow, RowStatus
from app.planning.types import CourseState


def row(code="MASY1-GC 1015", status=RowStatus.matched, **kw):
    return ExtractedRow(course_code=code, status=status, **kw)


# --------------------------------------------------------------------------------------
# Sniffing — the bytes decide, not the filename
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"\xff\xd8\xff\xe0" + b"\x00" * 20, "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, "image/png"),
        (b"GIF89a" + b"\x00" * 20, "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 8, "image/heic"),
        (b"\x00\x00\x00\x18ftypmif1" + b"\x00" * 8, "image/heic"),
    ],
)
def test_image_formats_are_recognised_from_their_magic_bytes(data, expected):
    assert sniff_image(data) == expected


def test_a_pdf_is_not_an_image():
    assert sniff_image(b"%PDF-1.7\n" + b"\x00" * 20) is None


def test_an_empty_upload_is_not_an_image():
    assert sniff_image(b"") is None


def test_a_jpeg_named_pdf_is_still_a_jpeg():
    """The filename and the browser's content-type are the caller's opinion; bytes are not."""
    assert sniff_image(b"\xff\xd8\xff\xe0fake.pdf") == "image/jpeg"


# --------------------------------------------------------------------------------------
# The trust boundary
# --------------------------------------------------------------------------------------


def test_a_matched_row_from_an_image_is_downgraded():
    out = _as_reviewed([row(status=RowStatus.matched)], OCR_ROW_REASON)
    assert out[0].status is RowStatus.needs_review


def test_the_downgrade_says_why_in_the_students_words():
    out = _as_reviewed([row(status=RowStatus.matched)], OCR_ROW_REASON)
    assert OCR_ROW_REASON in out[0].reasons


def test_no_status_survives_as_matched():
    """The negative invariant, over every status the parser can produce."""
    rows = [row(code=f"MASY1-GC 10{i}", status=s) for i, s in enumerate(RowStatus)]
    assert all(r.status is not RowStatus.matched for r in _as_reviewed(rows, OCR_ROW_REASON))


def test_an_unreadable_row_stays_unreadable():
    """It is already making a weaker claim; promoting it to needs_review would overstate it."""
    out = _as_reviewed([row(code=None, status=RowStatus.unreadable)], OCR_ROW_REASON)
    assert out[0].status is RowStatus.unreadable


def test_existing_reasons_are_kept_and_not_duplicated():
    original = row(status=RowStatus.needs_review, reasons=("no grade on this row",))
    out = _as_reviewed([original, original], OCR_ROW_REASON)
    assert out[0].reasons == ("no grade on this row", OCR_ROW_REASON)
    assert out[0].reasons.count(OCR_ROW_REASON) == 1


def test_the_row_fields_themselves_are_untouched():
    """The downgrade is about trust, not about hiding what was read — the student needs to
    see the values in order to check them."""
    original = row(term="Fall 2024", grade="A", credits=3, state=CourseState.completed)
    out = _as_reviewed([original], OCR_ROW_REASON)[0]
    assert (out.course_code, out.term, out.grade, out.credits) == (
        original.course_code, "Fall 2024", "A", 3,
    )


def test_downgraded_rows_are_still_confirmable_one_at_a_time():
    """Needs_review is 'check this', not 'discard this' — the student can still accept it."""
    assert _as_reviewed([row(status=RowStatus.matched)], OCR_ROW_REASON)[0].confirmable


def test_nothing_is_dropped():
    rows = [row(code=f"MASY1-GC 1{i:03d}") for i in range(5)]
    assert len(_as_reviewed(rows, OCR_ROW_REASON)) == 5


# --------------------------------------------------------------------------------------
# Degradation — the reader being down must not become a claim about the student
# --------------------------------------------------------------------------------------


def test_an_unreadable_image_degrades_to_the_honest_refusal(monkeypatch):
    """Rule 6, at the point where getting it wrong is worst.

    If the vision endpoint is down and this returned an empty reading, the review screen
    would say "0 courses found" about a transcript full of them — a statement about the
    student's record, made because a third-party service was unavailable. It has to come
    back as "this is a photo and it cannot be read right now" instead.

    Free to test: the fault raises before any network call, and the session is never touched
    because parsing is not reached.
    """
    from app import faults
    from app.config import settings
    from app.intake.service import read_transcript

    monkeypatch.setattr(settings, "fault_injection", True)
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64

    with faults.injected("ocr.unavailable"):
        reading = read_transcript(None, jpeg)

    assert reading.rows == []
    assert reading.ocr_degraded is True
    # The distinction that matters: no_text_layer says "there is nothing to read here",
    # which is true of a photo, and the notes say the reader is down rather than blaming
    # the file permanently.
    assert reading.no_text_layer is True
    assert any("unavailable right now" in note for note in reading.notes)


def test_a_degraded_reading_never_claims_the_transcript_was_empty(monkeypatch):
    from app import faults
    from app.config import settings
    from app.intake.service import read_transcript

    monkeypatch.setattr(settings, "fault_injection", True)
    with faults.injected("ocr.unavailable"):
        reading = read_transcript(None, b"\xff\xd8\xff\xe0" + b"\x00" * 64)

    blob = " ".join(reading.notes).lower()
    assert "no course" not in blob
    assert "0 course" not in blob
