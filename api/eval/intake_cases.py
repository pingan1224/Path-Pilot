"""Labelled expectations for transcript reading.

Every fixture is synthetic — see `tests/fixtures/make_transcripts.py`. Nothing here is
derived from a real transcript, which matters more for this feature than any other in the
project: the test corpus for a document this sensitive must not contain a real one.

The metric that matters is **not** how many rows were read. It is how many were read *and
labelled correctly*, where "correctly" includes being labelled `needs_review`. A reader that
confidently reports 100% of rows as clean is worse than one that reads 80% and flags the rest,
because the student trusts the first one and their degree audit is then wrong in ways nobody
will notice until registration.

So there are two separate numbers, gated differently:

- `silently_wrong` — a row reported `matched` whose code, grade, term, or state is not what
  the fixture says. Gated at zero. This is the one that damages a student.
- `row_recall` — labelled courses that were found at all. Reported with a floor, because a
  missed row is a real cost (a course quietly absent from their record) but a much smaller
  one than an invented or mis-stated row.
"""

from dataclasses import dataclass, field

from app.planning.types import CourseState


@dataclass(frozen=True)
class ExpectedRow:
    course_code: str
    status: str  # "matched" | "needs_review"
    term: str | None = None
    grade: str | None = None
    state: CourseState = CourseState.completed
    note: str = ""


@dataclass(frozen=True)
class IntakeCase:
    id: str
    fixture: str
    layout: str
    rows: tuple[ExpectedRow, ...] = ()
    # Set for a file with no text layer at all — the scanned-document path.
    expect_no_text_layer: bool = False
    # Lines the reader must hand back rather than drop.
    min_unreadable: int = 0
    note: str = ""


M = "matched"
R = "needs_review"

CASES: list[IntakeCase] = [
    IntakeCase(
        "T01",
        "transcript_table.pdf",
        "ruled table",
        rows=(
            ExpectedRow("MASY1-GC 1015", M, "Fall 2024", "A"),
            ExpectedRow("MASY1-GC 1115", M, "Fall 2024", "A-"),
            ExpectedRow("MASY1-GC 1500", M, "Spring 2025", "B+"),
            ExpectedRow("MASY1-GC 1600", M, "Spring 2025", "A"),
            ExpectedRow("MASY1-GC 2400", M, "Fall 2025", "A-"),
        ),
        note=(
            "The shape a student information system exports. Extraction emits one cell per "
            "line, so a row arrives as five separate lines — this is the case that killed "
            "the obvious line-regex approach."
        ),
    ),
    IntakeCase(
        "T02",
        "transcript_labelled.pdf",
        "labelled prose",
        rows=(
            ExpectedRow("MASY1-GC 1015", M, "Fall 2024", "A"),
            ExpectedRow("MASY1-GC 1115", M, "Fall 2024", "A-"),
            ExpectedRow("MASY1-GC 1500", M, "Spring 2025", "B+"),
            ExpectedRow("MASY1-GC 1600", M, "Spring 2025", "A"),
            ExpectedRow("MASY1-GC 2400", M, "Fall 2025", "A-"),
        ),
        note=(
            "Here the term follows its course and is labelled, the opposite of T01 where the "
            "term is an unlabelled header above. Preferring either direction alone "
            "mis-assigned every row of the other layout."
        ),
    ),
    IntakeCase(
        "T03",
        "transcript_twocolumn.pdf",
        "two terms side by side",
        rows=(
            # Codes and grades are adjacent in the stream and read fine; the *term* is what
            # the layout destroys, so every row must land in needs_review with no term rather
            # than carrying a confidently wrong one.
            ExpectedRow("MASY1-GC 1015", R, None, "A"),
            ExpectedRow("MASY1-GC 1115", R, None, "A-"),
            ExpectedRow("MASY1-GC 1500", R, None, "B+"),
            ExpectedRow("MASY1-GC 1600", R, None, "A"),
        ),
        note=(
            "The extracted stream is row-major across both columns, so nothing in the linear "
            "order says which term a course belongs to. Term is optional in the profile, so "
            "dropping it costs the student nothing; guessing it would put courses in the "
            "wrong semester of their plan."
        ),
    ),
    IntakeCase(
        "T04",
        "transcript_messy.pdf",
        "mixed real-world cases",
        rows=(
            ExpectedRow("MASY1-GC 1015", M, "Fall 2024", "A"),
            # Legitimate cross-school elective. Allowed, uncheckable here.
            ExpectedRow("MKTG-GB 2350", R, "Fall 2024", "B"),
            # S/U grade: real, and outside the 4.0 scale this tool compares against.
            ExpectedRow("MASY1-GC 1500", R, "Spring 2025", None),
            # No grade at all. Must read as in progress, never as a failing grade — and must
            # NOT absorb the following row's "TR", which is what happened before the row
            # window was bounded on a second credits token.
            ExpectedRow("MASY1-GC 2500", R, "Fall 2026", None, CourseState.in_progress),
        ),
        min_unreadable=1,
        note="The rows that decide whether the reader is honest rather than confident.",
    ),
    IntakeCase(
        "T06",
        "transcript_sis_export.pdf",
        "SIS export, whole row on one line",
        rows=(
            ExpectedRow("MASY1-GC 1015", M, "Fall 2024", "A-"),
            # Title long enough to wrap, so the code lands on its own line with its title
            # stranded above it — the case T01 cannot produce, because there every field is
            # already on its own line.
            ExpectedRow("MASY1-GC 1115", M, "Fall 2024", "A-"),
            ExpectedRow("MASY1-GC 1500", M, "Spring 2025", "A"),
            ExpectedRow("MASY1-GC 1600", M, "Spring 2025", "A-"),
            # Enrolled, ungraded. The term's summary line directly below it reads
            # `Current 12.0 0.0 0.0 0.000 0.000` — six numbers where a grade would be.
            ExpectedRow("MASY1-GC 2400", R, "Fall 2025", None, CourseState.in_progress),
        ),
        note=(
            "Modelled on the first real transcript this reader ever saw (2026-08-07), which "
            "was not copied into the repo — a genuine NYU SPS export carries a name, a "
            "birthdate and a student number. Its *shape* is what is reproduced here, and it "
            "differs from all four reasoned-about layouts: the whole row arrives on one line "
            "with the title first, the code carries a section suffix (`-400`), long titles "
            "wrap away from their code, and every term ends with a GPA block whose six "
            "numbers sit exactly where a credits-and-grade parser is looking. The reader "
            "handled the real document 12/12 on the first attempt; this case is what keeps "
            "that true."
        ),
    ),
    IntakeCase(
        "T05",
        "transcript_scanned.pdf",
        "no text layer",
        expect_no_text_layer=True,
        note=(
            "A scan or a photo. Cleanly detectable at zero extractable characters, which is "
            "why there is no OCR dependency yet: this case can be answered honestly today."
        ),
    ),
]


def validate() -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for case in CASES:
        if case.id in seen:
            problems.append(f"{case.id}: duplicate id")
        seen.add(case.id)
        if case.expect_no_text_layer and case.rows:
            problems.append(f"{case.id}: a file with no text layer cannot have expected rows")
        if not case.expect_no_text_layer and not case.rows:
            problems.append(f"{case.id}: no expected rows and not a no-text-layer case")
        for row in case.rows:
            if row.status not in (M, R):
                problems.append(f"{case.id}: {row.course_code} has status {row.status!r}")
            if row.status == M and row.grade is None and row.state is CourseState.completed:
                problems.append(
                    f"{case.id}: {row.course_code} is matched+completed with no grade, "
                    "which the reader would flag"
                )
    return problems


__all__ = ["CASES", "ExpectedRow", "IntakeCase", "validate"]
