"""Catalogue parsing tests, for the failures that do not announce themselves.

`ingest/catalog.py` reports everything it half-understands: a prerequisite clause with no
course code in it, a course with no credit value, a heading that is not a course. Those are
loud, and `--strict` turns them into a failed build.

The failure that has actually happened is the quiet one. The course-code pattern required
four digits, because MASY1-GC — the only catalogue read for months — uses four throughout.
Executive Masters in Marketing numbers its courses `EMSC1-GC 10` to `EMSC1-GC 300`, so the
pattern matched none of its seventeen headings, the page yielded no courses, and nothing
complained: every check in the module fires on a course it partly parsed, and there was no
course. Twenty-three catalogues were added at once, so a page silently reading as empty is
the defect most likely to recur and least likely to be noticed.

Both halves are pinned here — the pattern that reads short numbers, and the check that
fails a page yielding nothing at all.
"""

import pytest

from ingest.catalog import COURSE_CODE, HEADING_CODE, parse_all, parse_prerequisites


@pytest.mark.parametrize(
    "heading",
    [
        "EMSC1-GC 10 Developing and Driving Actionable Customer Insights",
        "EMSC1-GC 100 Taking Calculated Risks, Negotiating and Leading Dispute Resolutions",
        "MASY1-GC 2100 Advanced Business Analytics",
    ],
)
def test_course_codes_are_read_at_every_number_length(heading):
    """Two, three and four digits are all real codes in the SPS catalogues."""
    assert HEADING_CODE.match(heading), heading
    assert COURSE_CODE.search(heading), heading


def test_a_number_longer_than_four_digits_is_not_a_course_code():
    """The pattern widened downwards only. Five digits is a page artefact, not a course."""
    assert not HEADING_CODE.match("MASY1-GC 21000 Not A Course")


@pytest.fixture(scope="module")
def parsed():
    return parse_all()


def test_every_catalogue_page_yields_at_least_one_course(parsed):
    """The regression that motivated this file: a page reading as empty and passing.

    Asserted over the real snapshot rather than a fixture, because the thing being guarded
    against is a *new* catalogue whose numbering nobody checked.
    """
    _, problems = parsed
    empty = [p for p in problems if "parsed to zero courses" in p]
    assert not empty, "catalogue page(s) parsed to nothing:\n  " + "\n  ".join(empty)


def test_the_marketing_catalogue_is_read_in_full(parsed):
    """EMSC is the page the old pattern read as empty; pin its count, not just non-zero."""
    courses, _ = parsed
    emsc = [c for c, _ in courses if c.code.startswith("EMSC1-GC")]
    assert len(emsc) == 17, f"expected 17 EMSC courses, parsed {len(emsc)}"


@pytest.mark.parametrize("stated", ["None", "none", "N/A", "No prerequisites"])
def test_a_stated_absence_of_prerequisites_is_an_answer(stated):
    """"None" means the bulletin checked and there are none — not that parsing failed.

    Both end with an empty edge list, and the difference decides whether the planner offers
    the course or warns it cannot verify it. Fourteen courses say this longhand.
    """
    groups, problem = parse_prerequisites(stated)
    assert groups == []
    assert problem is None, f"{stated!r} was read as unparseable"


def test_a_title_only_prerequisite_is_kept_as_unverifiable():
    """The opposite case: a real requirement the graph cannot model must stay loud.

    Resolving these to codes is deliberately not attempted — a title can match courses under
    four prefixes, the AND separator also occurs inside titles ("Quantitative Methods and
    Metrics"), and the published text carries truncations.
    """
    groups, problem = parse_prerequisites(
        "Workforce Planning AND Quantitative Methods and Metrics"
    )
    assert groups == []
    assert problem, "a title-only prerequisite must be reported, not silently dropped"


def test_prerequisite_edges_survive_the_wider_pattern(parsed):
    """A looser code pattern must not start matching inside prerequisite prose.

    MASY1-GC's graph was correct before this change and is the only one with a known-good
    shape, so it is the control: if widening the pattern broke clause parsing, this moves.
    """
    courses, _ = parsed
    masy = [c for c, _ in courses if c.code.startswith("MASY1-GC")]
    assert len(masy) == 57
    with_prereqs = [c for c in masy if c.prerequisite_groups]
    assert with_prereqs, "MASY1-GC lost every prerequisite edge"
