"""Transcript parser tests.

Pure functions over extracted text, so no PDF and no database is needed — the layout
behaviours are pinned by the eval against real fixtures; these pin the *rules*.

Weighted at the three bugs the fixtures actually caught, because each was silent and each
would have put wrong coursework in a student's record:

1. The row window ran into the next row, so a blank-grade course absorbed its neighbour's
   transfer marker and reported a grade the student never earned.
2. Term association preferred one direction, which mis-assigned every row of the layout that
   puts the term on the other side.
3. The unreadable heuristic keyed on the word "grade", so every continuation line of a
   labelled record became a phantom course.
"""

import pytest

from app.intake.parse import normalise_code, parse_rows
from app.intake.types import RowStatus
from app.planning.types import CourseState

CATALOG = {"MASY1-GC 1015", "MASY1-GC 1500", "MASY1-GC 2100", "MASY1-GC 2500"}


def only(rows, code):
    return next(r for r in rows if r.course_code == code)


# --------------------------------------------------------------------------------------
# Code recognition
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MASY1-GC 1015", "MASY1-GC 1015"),
        ("MASY1-GC1015", "MASY1-GC 1015"),
        ("MASY1 - GC 1015", "MASY1-GC 1015"),
        ("masy1-gc 1015", "MASY1-GC 1015"),
    ],
)
def test_codes_are_normalised_to_catalog_form(raw, expected):
    rows = parse_rows(f"{raw} 3.0 A", catalog=CATALOG)
    assert rows[0].course_code == expected


def test_normalise_code_is_case_and_shape_stable():
    assert normalise_code("masy1", "gc", "1015") == "MASY1-GC 1015"


def test_a_repeated_course_yields_one_row():
    """A transcript may list a retake. Two conflicting rows for one code would be worse
    than one, since the profile is keyed by code anyway."""
    text = "MASY1-GC 1015 3.0 C\nMASY1-GC 1015 3.0 A"
    rows = [r for r in parse_rows(text, catalog=CATALOG) if r.course_code]
    assert len(rows) == 1


def test_a_retake_keeps_the_latest_attempt_not_the_first():
    """Which of the two survives is not arbitrary.

    Transcripts run in date order, so keeping the first meant an autumn failure silently
    outranked the spring pass that replaced it — a worse grade written into a degree audit
    with nothing on screen saying a merge had happened.
    """
    text = "MASY1-GC 1015 3.0 F\nMASY1-GC 1015 3.0 B+"
    row = only(parse_rows(text, catalog=CATALOG), "MASY1-GC 1015")
    assert row.grade == "B+"


def test_a_retake_is_never_vouched_for():
    """One row cannot represent two attempts, so the reader says so instead of implying
    the record is complete. `matched` means every field is trusted; a collapsed history
    is exactly what a student should be asked to look at."""
    text = "MASY1-GC 1015 3.0 F\nMASY1-GC 1015 3.0 B+"
    row = only(parse_rows(text, catalog=CATALOG), "MASY1-GC 1015")
    assert row.status is RowStatus.needs_review
    assert any("more than once" in r for r in row.reasons)


def test_empty_text_yields_nothing_rather_than_erroring():
    assert parse_rows("", catalog=CATALOG) == []
    assert parse_rows("   \n\n ", catalog=CATALOG) == []


def test_prose_without_codes_yields_no_courses():
    rows = parse_rows("Cumulative GPA: 3.72  Credits earned: 15.0", catalog=CATALOG)
    assert [r for r in rows if r.course_code] == []


# --------------------------------------------------------------------------------------
# The row window — bug 1, the one that invented a grade
# --------------------------------------------------------------------------------------


def test_a_blank_grade_row_does_not_absorb_the_next_rows_grade():
    """Measured on a real fixture: an in-progress row ran into the following transfer row
    and reported "TR". Each row has exactly one credits value, so a second one means the
    next row has begun."""
    text = "Fall 2026\nMASY1-GC 2500\n3.0\nTransfer\n3.0\nTR"
    row = only(parse_rows(text, catalog=CATALOG), "MASY1-GC 2500")
    assert row.grade is None
    assert row.state is CourseState.in_progress


def test_a_grade_is_not_taken_from_beyond_the_next_course():
    text = "MASY1-GC 1015\n3.0\nMASY1-GC 1500\n3.0\nA"
    assert only(parse_rows(text, catalog=CATALOG), "MASY1-GC 1015").grade is None


def test_a_grade_separated_by_a_long_title_is_still_found():
    """The table layout puts the whole course title between the code and the grade."""
    text = "Fall 2024\nMASY1-GC 1015\nQuantitative Methods for Business Analysis\n3.0\nA"
    assert only(parse_rows(text, catalog=CATALOG), "MASY1-GC 1015").grade == "A"


# --------------------------------------------------------------------------------------
# Terms — bug 2, off by one row
# --------------------------------------------------------------------------------------


def test_an_unlabelled_term_header_applies_to_the_courses_below_it():
    text = "Fall 2024\nMASY1-GC 1015\n3.0\nA\nSpring 2025\nMASY1-GC 1500\n3.0\nB+"
    rows = parse_rows(text, catalog=CATALOG)
    assert only(rows, "MASY1-GC 1015").term == "Fall 2024"
    assert only(rows, "MASY1-GC 1500").term == "Spring 2025"


def test_a_labelled_term_after_the_course_wins_over_a_preceding_header():
    """The labelled layout puts the term after its course. Preferring the preceding header
    here assigned every row the previous row's term."""
    text = (
        "Course: MASY1-GC 1015\nTerm: Fall 2024 Credits: 3.0 Grade: A\n"
        "Course: MASY1-GC 1500\nTerm: Spring 2025 Credits: 3.0 Grade: B+"
    )
    rows = parse_rows(text, catalog=CATALOG)
    assert only(rows, "MASY1-GC 1015").term == "Fall 2024"
    assert only(rows, "MASY1-GC 1500").term == "Spring 2025"


def test_autumn_is_normalised_to_fall():
    rows = parse_rows("Autumn 2024\nMASY1-GC 1015\n3.0\nA", catalog=CATALOG)
    assert rows[0].term == "Fall 2024"


def test_side_by_side_terms_drop_the_term_instead_of_guessing():
    """Two headers before any course means the stream carries no term association. The term
    is optional in the profile, so blank costs nothing; wrong puts a course in the wrong
    semester of the student's plan."""
    text = "Fall 2024\nSpring 2025\nMASY1-GC 1015\nA\nMASY1-GC 1500\nB+"
    rows = parse_rows(text, catalog=CATALOG)
    for row in rows:
        assert row.term is None
        assert row.status is RowStatus.needs_review
        assert any("side-by-side" in r for r in row.reasons)


# --------------------------------------------------------------------------------------
# Grades and state — absence must never become a failing grade
# --------------------------------------------------------------------------------------


def test_a_missing_grade_reads_as_in_progress_and_says_so():
    row = only(parse_rows("MASY1-GC 1015\n3.0", catalog=CATALOG), "MASY1-GC 1015")
    assert row.state is CourseState.in_progress
    assert row.grade is None
    assert row.status is RowStatus.needs_review
    assert any("no grade" in r.lower() for r in row.reasons)


@pytest.mark.parametrize("grade", ["A", "A-", "B+", "C", "D+", "F"])
def test_scale_grades_are_read_and_the_row_matches(grade):
    row = only(parse_rows(f"MASY1-GC 1015\n3.0\n{grade}", catalog=CATALOG), "MASY1-GC 1015")
    assert row.grade == grade
    assert row.status is RowStatus.matched
    assert row.state is CourseState.completed


@pytest.mark.parametrize("token", ["S", "U", "P", "TR", "W", "I", "AUD"])
def test_off_scale_grades_are_flagged_not_dropped(token):
    """These are real grades. Treating them as "no grade" would silently report finished
    coursework as in progress."""
    row = only(parse_rows(f"MASY1-GC 1015\n3.0\n{token}", catalog=CATALOG), "MASY1-GC 1015")
    assert row.status is RowStatus.needs_review
    assert row.grade is None
    assert any(token in r for r in row.reasons)


def test_a_minus_grade_is_not_truncated_to_its_letter():
    row = only(parse_rows("MASY1-GC 1015\n3.0\nA-", catalog=CATALOG), "MASY1-GC 1015")
    assert row.grade == "A-"


def test_a_letter_inside_a_word_is_not_read_as_a_grade():
    text = "MASY1-GC 1015\nAdvanced Systems\n3.0"
    assert only(parse_rows(text, catalog=CATALOG), "MASY1-GC 1015").grade is None


# --------------------------------------------------------------------------------------
# Catalog matching
# --------------------------------------------------------------------------------------


def test_a_course_outside_the_catalog_is_reviewable_not_rejected():
    """A cross-school elective is legitimate and permanently uncheckable here."""
    row = only(parse_rows("MKTG-GB 2350\n3.0\nB", catalog=CATALOG), "MKTG-GB 2350")
    assert row.status is RowStatus.needs_review
    assert row.confirmable
    assert any("not in the catalog" in r for r in row.reasons)


def test_without_a_catalog_nothing_is_claimed_as_matched():
    rows = parse_rows("MASY1-GC 1015\n3.0\nA", catalog=None)
    assert rows[0].status is RowStatus.needs_review


def test_credits_are_read_but_a_course_number_is_not_mistaken_for_them():
    row = only(parse_rows("MASY1-GC 1015\n3.0\nA", catalog=CATALOG), "MASY1-GC 1015")
    assert row.credits == 3


# --------------------------------------------------------------------------------------
# Unreadable rows — bug 3, phantom courses
# --------------------------------------------------------------------------------------


def test_an_illegible_line_is_handed_back_for_retyping():
    rows = parse_rows("~~~ c0urse c0de illegible ~~~", catalog=CATALOG)
    assert len(rows) == 1
    assert rows[0].status is RowStatus.unreadable
    assert rows[0].course_code is None
    assert not rows[0].confirmable
    assert rows[0].raw


def test_continuation_lines_are_not_phantom_courses():
    """Keying on the word "grade" made every labelled row emit a second, fake course."""
    text = "Course: MASY1-GC 1015\nTerm: Fall 2024 Credits: 3.0 Grade: A"
    rows = parse_rows(text, catalog=CATALOG)
    assert [r.status for r in rows] == [RowStatus.matched]


def test_a_header_row_is_not_an_unreadable_course():
    rows = parse_rows("Term Course Title Cr Grade", catalog=CATALOG)
    assert rows == []


def test_a_summary_line_is_not_an_unreadable_course():
    rows = parse_rows("Cumulative GPA: 3.72   Credits earned: 15.0", catalog=CATALOG)
    assert [r for r in rows if r.status is RowStatus.unreadable] == []


# --------------------------------------------------------------------------------------
# The invariant that protects the student
# --------------------------------------------------------------------------------------


def test_a_matched_row_is_always_fully_resolved():
    """`matched` is the reader vouching for a row. It may never carry an unresolved field —
    anything missing has to demote the row to needs_review instead."""
    text = (
        "Fall 2024\nMASY1-GC 1015\n3.0\nA\n"
        "Spring 2025\nMASY1-GC 1500\n3.0\nB+\n"
        "MKTG-GB 2350\n3.0\nB\n"
        "MASY1-GC 2500\n3.0"
    )
    for row in parse_rows(text, catalog=CATALOG):
        if row.status is RowStatus.matched:
            assert row.course_code and row.grade and row.term
            assert row.state is CourseState.completed
            assert row.reasons == ()


def test_every_non_matched_row_explains_itself():
    text = "Fall 2024\nSpring 2025\nMASY1-GC 1015\nA\nMKTG-GB 2350\nS\nMASY1-GC 2500\n3.0"
    for row in parse_rows(text, catalog=CATALOG):
        if row.status is not RowStatus.matched:
            assert row.reasons, f"{row.course_code or row.raw} is flagged with no reason"
