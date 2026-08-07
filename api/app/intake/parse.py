"""Reading course rows out of extracted transcript text. Pure functions, no I/O.

**The parsing strategy came out of measurement, not from a guess about layouts.** Running
`pypdf` over four synthetic layouts showed that the obvious approach — regex each line —
fails on the most common transcript shape. Extraction from a ruled table emits one cell per
line, so a row arrives as five separate lines:

    Fall 2024
    MASY1-GC 1015
    Quantitative Methods for Business Analysis
    3.0
    A

Worse, **empty cells vanish from the stream entirely.** An in-progress row with no grade
emits four tokens where its neighbours emit five, so any parser that assumes a fixed field
count silently reads the *next* row's term as this row's grade.

So the parser anchors on the one thing every layout preserves intact: the course code. Codes
are found first, then each one's neighbourhood is searched for a grade, a term, and credits.
Field order, cell alignment, and missing cells all stop mattering.

The multi-column finding is the reason `term` is treated as expendable. In a two-term
side-by-side layout the stream is row-major across both columns, so term headers appear
before the courses of *both* terms and nothing in the linear order says which course belongs
to which. Guessing "the nearest preceding header" is wrong half the time, and the term is
optional in `profile_courses` — so when the layout makes it ambiguous the term is dropped
and the row says why. A missing optional field costs the student nothing; a confidently
wrong one puts a course in the wrong semester of their plan.
"""

from __future__ import annotations

import re

from app.intake.types import ExtractedRow, RowStatus
from app.planning.rules import GRADE_ORDER
from app.planning.types import CourseState

# Same shape as the decoder's extractor: NYU subject codes carry an optional trailing digit
# and a two-letter school suffix. Kept separate rather than imported because the decoder
# matches inside prose while this matches inside table debris, and the two will drift.
#
# Case-insensitive, matching the decoder. Transcripts are machine-generated and almost always
# uppercase, so this mostly costs a small false-positive risk on hyphenated prose ("re-do
# 100" is code-shaped). That trade is worth taking because the failure modes are wildly
# asymmetric: a lowercase export under a case-sensitive pattern does not merely miss the
# courses, it routes every one of them into `unreadable` — actively misleading rather than
# incomplete. A false positive, by contrast, arrives as one `needs_review` row saying it is
# not in the catalog, which the student ignores.
COURSE_CODE_RE = re.compile(r"\b([A-Za-z]{2,5}\d?)\s*-\s*([A-Za-z]{2})\s*(\d{3,4})\b")

TERM_RE = re.compile(r"\b(Spring|Summer|Fall|Autumn|Winter)\s*(\d{4})\b", re.I)
# A term carrying its own label belongs to the course it follows — no inference needed.
# Unlabelled terms are headers, and headers sit *above* their courses, so the two cases have
# to be told apart: measured on the fixtures, preferring whichever term came first after the
# code mis-assigned every row of a ruled table by one, because the next row's header falls
# inside the window.
LABELLED_TERM_RE = re.compile(
    r"Term\s*[:.]?\s*(Spring|Summer|Fall|Autumn|Winter)\s*(\d{4})", re.I
)
CREDITS_RE = re.compile(r"\b([0-6](?:\.\d)?)\b")

# Grades the scale understands, longest first so "A-" is not read as "A".
_KNOWN_GRADES = sorted(GRADE_ORDER, key=len, reverse=True)
GRADE_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(re.escape(g) for g in _KNOWN_GRADES) + r")(?![A-Za-z0-9+-])"
)

# Grade-shaped tokens that are real and outside the numeric scale. Recognised so they become
# `needs_review` with an explanation, rather than falling through as "no grade" and being
# quietly reported as coursework in progress.
NON_SCALE_GRADES = {
    "S": "a satisfactory/unsatisfactory grade, which this tool cannot convert to the 4.0 scale",
    "U": "an unsatisfactory grade outside the 4.0 scale",
    "P": "a pass/fail grade, which this tool cannot convert to the 4.0 scale",
    "TR": "transfer credit, which only your advisor can confirm counts here",
    "T": "transfer credit, which only your advisor can confirm counts here",
    "W": "a withdrawal, which earns no credit",
    "I": "an incomplete, which has no final grade yet",
    "IP": "an in-progress marker",
    "AUD": "an audit, which earns no credit",
    "NA": "no grade recorded",
}
NON_SCALE_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(sorted(NON_SCALE_GRADES, key=len, reverse=True)) + r")(?![A-Za-z0-9])"
)

# How far around a course code to look for its fields. Wide enough to cross the line breaks
# a table layout inserts between cells of one row, narrow enough not to reach the next row's
# course — measured against the fixtures, where one row spans about 60 characters.
WINDOW_BEFORE = 90
WINDOW_AFTER = 160


def _row_window(text: str, code_end: int, next_code_start: int | None) -> str:
    """The text belonging to one course row, bounded so it cannot swallow the next one.

    Three bounds, and the third is the one that matters. A missing cell disappears from the
    extracted stream entirely, so an in-progress row with no grade runs straight into its
    neighbour — measured, this made a blank-grade row absorb the following row's "TR" and
    report transfer credit the student never claimed. Each row carries exactly one credits
    value, so a *second* credits token is the reliable signal that the next row has started.
    """
    hard_end = min(len(text), code_end + WINDOW_AFTER)
    if next_code_start is not None:
        hard_end = min(hard_end, next_code_start)

    window = text[code_end:hard_end]
    credit_hits = list(CREDITS_RE.finditer(window))
    if len(credit_hits) >= 2:
        window = window[: credit_hits[1].start()]
    return window


def normalise_code(subject: str, school: str, number: str) -> str:
    return f"{subject.upper()}-{school.upper()} {number}"


def _terms_in(text: str) -> list[tuple[int, str]]:
    out = []
    for match in TERM_RE.finditer(text):
        season = match.group(1).title()
        if season == "Autumn":
            season = "Fall"
        out.append((match.start(), f"{season} {match.group(2)}"))
    return out


def _looks_multi_column(text: str, code_positions: list[int]) -> bool:
    """True when term headers cluster ahead of the courses instead of interleaving.

    The signature of a side-by-side layout: two or more term headers appear before the
    first course code. In a single-column record each term header sits immediately above
    its own courses, so headers and codes alternate. When they do not, the linear order
    carries no information about which course belongs to which term.
    """
    if not code_positions:
        return False
    first_code = min(code_positions)
    headers_before = sum(1 for pos, _ in _terms_in(text) if pos < first_code)
    return headers_before >= 2


def parse_rows(text: str, *, catalog: set[str] | None = None) -> list[ExtractedRow]:
    """Read every course-shaped row out of extracted transcript text.

    `catalog` is the set of known course codes. Absent, every code is reported as
    `needs_review` rather than `matched` — the reader will not claim a code is real when it
    has nothing to check against.
    """
    if not text or not text.strip():
        return []

    matches = list(COURSE_CODE_RE.finditer(text))
    ambiguous_terms = _looks_multi_column(text, [m.start() for m in matches])
    terms = _terms_in(text)

    rows: list[ExtractedRow] = []
    seen: set[str] = set()

    for index, match in enumerate(matches):
        code = normalise_code(*match.groups())
        # A transcript can legitimately list a repeated course twice; the review list is
        # keyed by code downstream, so collapse duplicates here and say nothing false about
        # repeats rather than inventing two conflicting rows for one code.
        if code in seen:
            continue
        seen.add(code)

        start, end = match.start(), match.end()
        next_start = matches[index + 1].start() if index + 1 < len(matches) else None
        after = _row_window(text, end, next_start)
        window = text[max(0, start - WINDOW_BEFORE) : end] + after

        reasons: list[str] = []

        # --- grade. Searched after the code first: every layout measured puts the grade
        # after its course, and looking behind would find the previous row's grade.
        grade: str | None = None
        state = CourseState.completed
        scale_hit = GRADE_RE.search(after)
        non_scale_hit = NON_SCALE_RE.search(after)
        # Whichever comes first wins — "S" before "A" means this row's grade is S and the A
        # belongs to a later row.
        if scale_hit and (not non_scale_hit or scale_hit.start() <= non_scale_hit.start()):
            grade = scale_hit.group(1)
        elif non_scale_hit:
            token = non_scale_hit.group(1)
            reasons.append(
                f"The grade reads {token!r} — {NON_SCALE_GRADES[token]}. Set the right "
                "state yourself before confirming."
            )
        else:
            # No grade at all. Most likely in progress, and that is a guess worth stating
            # rather than a fact: absence of a grade must never become a failing one.
            state = CourseState.in_progress
            reasons.append(
                "No grade was found for this course, so it is treated as in progress. "
                "Correct it if you have finished it."
            )

        # --- term. A labelled term inside this row's own window is definitive; an
        # unlabelled one is a header, and headers sit above the courses they cover.
        term: str | None = None
        labelled = LABELLED_TERM_RE.search(after)
        if labelled:
            season = labelled.group(1).title()
            term = f"{'Fall' if season == 'Autumn' else season} {labelled.group(2)}"
        elif ambiguous_terms:
            reasons.append(
                "This file lists terms in side-by-side columns, so which term this course "
                "belongs to cannot be read reliably. The term is left blank rather than "
                "guessed."
            )
        else:
            preceding = [value for pos, value in terms if pos < start]
            if preceding:
                term = preceding[-1]

        # --- credits. Excludes anything already claimed by the code or the grade, and
        # rejects the 4-digit course number that CREDITS_RE would otherwise match.
        credits: int | None = None
        for candidate in CREDITS_RE.finditer(after):
            raw = candidate.group(1)
            value = float(raw)
            if 0 < value <= 6:
                credits = int(value)
                break

        # --- classification
        if catalog is None:
            status = RowStatus.needs_review
            reasons.append(
                "No course catalog was available to check this code against."
            )
        elif code not in catalog:
            status = RowStatus.needs_review
            reasons.append(
                f"{code} is not in the catalog this tool has loaded — it may be a course "
                "from another school, which is allowed but cannot be checked here."
            )
        elif reasons:
            status = RowStatus.needs_review
        else:
            status = RowStatus.matched

        rows.append(
            ExtractedRow(
                course_code=code,
                status=status,
                term=term,
                credits=credits,
                grade=grade,
                state=state,
                reasons=tuple(reasons),
                raw=" ".join(window.split()),
            )
        )

    rows.extend(_unreadable_rows(text, matches))
    return rows


# Lines that were meant to carry a course code and did not. Reported rather than dropped: a
# row the reader cannot see is a course missing from the student's audit, and they would have
# no way to know to look for it.
#
# The trigger is deliberately narrow. An earlier version keyed on any line mentioning
# "course", "credit", or "grade", which flagged every continuation line of a labelled layout
# ("Term: Fall 2024  Credits: 3.0  Grade: A") as a phantom unreadable course — five false
# rows on a five-course file. Only two things now qualify: an explicit illegibility marker,
# or a code-shaped token that failed to parse (digit-for-letter substitution being the
# classic OCR-ish corruption).
_ILLEGIBLE_MARKER = re.compile(r"(illegible|unreadable|not\s+legible|cannot\s+read)", re.I)
# Code-like but broken: letters and digits joined by a hyphen that COURSE_CODE_RE rejected.
_NEAR_MISS_CODE = re.compile(r"\b[A-Za-z0-9]{2,6}\s*-\s*[A-Za-z0-9]{1,3}\s*\d{2,4}\b")


def _unreadable_rows(text: str, matches: list[re.Match]) -> list[ExtractedRow]:
    claimed = [(m.start(), m.end()) for m in matches]
    out: list[ExtractedRow] = []
    offset = 0
    for line in text.splitlines():
        line_start, line_end = offset, offset + len(line)
        offset = line_end + 1
        stripped = line.strip()
        if len(stripped) < 8:
            continue
        if any(s < line_end and e > line_start for s, e in claimed):
            continue  # a real code lives on this line; already handled
        if not (_ILLEGIBLE_MARKER.search(stripped) or _NEAR_MISS_CODE.search(stripped)):
            continue
        out.append(
            ExtractedRow(
                course_code=None,
                status=RowStatus.unreadable,
                reasons=(
                    "This line looks like it was meant to be a course but no course code "
                    "could be read from it. Add it by hand if it belongs in your record.",
                ),
                raw=stripped[:200],
            )
        )
    return out
