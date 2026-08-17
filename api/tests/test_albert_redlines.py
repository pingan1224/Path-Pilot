"""The two things the Albert checklist must never be able to say.

Written before the feature, and the point of writing them first is that they are meant to
constrain its *shape*, not audit its output afterwards. Both red lines come from the same
place: this product has no Albert access, so a checklist about Albert is a record of what
the student says they did, and every word of it has to stay on that side of the line.

  1. **Never a check without a date.** "verified ✓" with no date reads as the system having
     confirmed something. `AlbertCheck.decided_at` is therefore a required field with no
     default — the dateless check is not a state the type can express, so no branch, no
     template and no future edit can produce one.

  2. **Never a claim about the student's record.** "You have no holds" is a false statement
     about a system this product cannot see, and it is the exact sentence a student would
     act on. Every status line is generated from the *decision* ("you checked this on
     …", "you skipped this on …", "not checked yet") and there is no branch that reads or
     asserts a result, because no result is ever stored.

The forbidden list is shared in spirit with `scripts/live_mode_probe.FORBIDDEN`, which
guards the same claims on the model's side. This file guards the deterministic side, where
the guarantee can be total rather than measured.
"""

import dataclasses
import re
from datetime import UTC, datetime

import pytest

from app.missions.albert import (
    AlbertCheck,
    CheckKind,
    checklist,
)

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
TERM = "Fall 2026"
COURSES = ("MASY1-GC 2100", "MASY1-GC 3010")

# Each of these, said by this product about a student's Albert record, would be a false
# statement it has no way to make true.
FORBIDDEN = [
    r"\bno holds?\b",
    r"\byou have no\b",
    r"\bnone found\b",
    r"your record is clear",
    r"nothing is blocking",
    r"\bwe (?:checked|verified|confirmed)\b",
    r"\bsystem (?:checked|verified|confirmed)\b",
    r"\bhas been verified\b",
    r"\bseats? (?:are|is) available\b",
    r"\bno conflicts?\b",
]


def _every_item_in_every_state():
    """Every (item, decision-state) pair the product can render. The probes below are only
    worth anything if they see all of them, so this is deliberately exhaustive rather than
    a sample."""
    variants = []
    for checks in (
        (),
        tuple(
            AlbertCheck(key=k, kind=CheckKind.checked, decided_at=NOW)
            for k in ("holds", f"appointment:{TERM}", *(f"seats:{c}" for c in COURSES))
        ),
        tuple(
            AlbertCheck(key=k, kind=CheckKind.skipped, decided_at=NOW)
            for k in ("holds", f"appointment:{TERM}", *(f"seats:{c}" for c in COURSES))
        ),
    ):
        variants.extend(checklist(term=TERM, confirmed_codes=COURSES, checks=checks))
    return variants


# --------------------------------------------------------------------------------------
# Red line 1 — a check cannot exist without a date
# --------------------------------------------------------------------------------------


def test_a_check_cannot_be_constructed_without_a_date():
    with pytest.raises(TypeError):
        AlbertCheck(key="holds", kind=CheckKind.checked)  # noqa: PLE1120 — that is the test


def test_the_date_field_is_required_and_not_optional():
    """Belt and braces against a future edit adding `= None`, which would reopen the hole
    quietly — the constructor test above would still pass."""
    field = next(f for f in dataclasses.fields(AlbertCheck) if f.name == "decided_at")
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING
    assert "None" not in str(field.type)


def test_every_settled_item_renders_its_date():
    for item in _every_item_in_every_state():
        if item.check is None:
            continue
        line = item.status_line()
        assert "2026" in line, f"{item.key}: settled item with no date in {line!r}"


def test_no_item_ever_renders_a_tick_or_the_word_verified():
    for item in _every_item_in_every_state():
        text = " ".join(
            [item.label, item.where, item.what, item.own_words, item.status_line()]
        )
        assert "✓" not in text, f"{item.key}: {text!r}"
        assert not re.search(r"\bverified\b", text, re.I), f"{item.key}: {text!r}"


# --------------------------------------------------------------------------------------
# Red line 2 — nothing asserts what the record says
# --------------------------------------------------------------------------------------


def test_no_rendered_text_claims_anything_about_the_students_record():
    for item in _every_item_in_every_state():
        text = " ".join(
            [item.label, item.where, item.what, item.own_words, item.status_line()]
        )
        for pattern in FORBIDDEN:
            assert not re.search(pattern, text, re.I), (
                f"{item.key} can say {pattern!r}: {text!r}"
            )


def test_a_checked_item_reports_the_declaration_not_a_result():
    item = next(
        i
        for i in checklist(
            term=TERM,
            confirmed_codes=COURSES,
            checks=(AlbertCheck(key="holds", kind=CheckKind.checked, decided_at=NOW),),
        )
        if i.key == "holds"
    )
    line = item.status_line()
    # The subject of the sentence is the student, and what it reports is the act of
    # looking — never what they saw, which is not stored and must not be inferred.
    assert line.lower().startswith("you checked")
    assert "hold" not in line.lower().replace("holds on your record", "")


def test_the_checklist_stores_no_outcome_field_at_all():
    """The strongest form of red line 2: there is nowhere to put a result.

    A boolean "clear/not clear" on the record would be filled in eventually, and the moment
    it is, every sentence above becomes derivable from it.
    """
    names = {f.name for f in dataclasses.fields(AlbertCheck)}
    for forbidden in ("outcome", "result", "clear", "passed", "ok", "status", "value"):
        assert forbidden not in names, f"AlbertCheck.{forbidden} is a place to store a claim"


# --------------------------------------------------------------------------------------
# The handoff — the same red lines, on the text a human actually acts on
# --------------------------------------------------------------------------------------


def keys_for(*codes):
    return ("holds", f"appointment:{TERM}", *(f"seats:{c}" for c in codes))


def all_checks(*keys, kind=CheckKind.checked, at=NOW):
    return tuple(AlbertCheck(key=k, kind=kind, decided_at=at) for k in keys)


def _handoff(checks):
    from app.missions.handoff import build_handoff
    from app.missions.types import Candidate, CandidateState, MissionFacts
    from app.planning.types import CourseState, StatedCourse

    facts = MissionFacts(
        term=TERM,
        stated_courses=(StatedCourse(code="MASY1-GC 1000", state=CourseState.completed),),
        candidates=tuple(
            Candidate(course_code=c, state=CandidateState.confirmed, proposed_by="student")
            for c in COURSES
        ),
        findings=(),
        albert_checks=checks,
    )
    return build_handoff(facts, program_name="Management and Analytics", rules_verified_on=None)


def test_the_handoff_never_claims_the_system_checked_anything():
    """This is the document that reaches an advisor, so it is the worst place for the
    claim and the only one where a reader can act on it before anyone notices."""
    for checks in (
        (),
        all_checks(*keys_for(*COURSES)),
        all_checks(*keys_for(*COURSES), kind=CheckKind.skipped),
    ):
        text = _handoff(checks)
        for pattern in FORBIDDEN:
            assert not re.search(pattern, text, re.I), f"handoff can say {pattern!r}"


def test_every_albert_line_is_in_the_students_own_voice():
    """An advisor must read these as the student's report, not the tool's finding. The
    labels elsewhere address the student ("Holds on your record"), which inside a
    first-person email would put a second speaker in the middle of the sentence."""
    text = _handoff(all_checks(*keys_for(*COURSES)))
    section = text.split("WHAT ONLY ALBERT KNOWS")[1].split("RISKS I AM")[0]
    lines = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("- ")]
    assert lines
    for line in lines:
        assert line.startswith("- I "), f"not in the student's voice: {line!r}"
        assert "your" not in line.lower(), f"addresses the reader: {line!r}"


def test_a_checked_line_carries_its_date_and_a_skipped_line_claims_nothing():
    text = _handoff(
        (
            AlbertCheck(key="holds", kind=CheckKind.checked, decided_at=NOW),
            AlbertCheck(
                key=f"seats:{COURSES[0]}", kind=CheckKind.skipped, decided_at=NOW
            ),
        )
    )
    assert "I checked my holds in Albert on 2026-08-17" in text
    assert f"I did not get to seats in {COURSES[0]}" in text
    # The unchecked ones say so rather than being omitted: an advisor who cannot tell the
    # difference between "checked" and "not mentioned" has been given a worse document.
    assert "I have not checked when my registration window opens" in text
