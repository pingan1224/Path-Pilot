"""Labelled registration-error messages for the decoder.

Written after the rule table and deliberately including phrasings the table does not
contain. That is not sloppiness — it is the only way this set measures anything. The
classifier matches literal patterns, so it cannot generalise: a phrasing outside the table
comes back `unrecognized` by construction. A case set built only from the table's own
strings would score 1.00 and tell us nothing, the same mistake the chunking ablation
nearly shipped when the `fixed` baseline scored 0.08 because it could not be fairly
measured at all.

So this set has two jobs:

* **Safety.** Nothing may be confidently wrong, and generic hold text may never resolve to
  a financial hold. Both are gated at zero.
* **Coverage, honestly.** The `held_out` family exists to fail. Its misses are the backlog
  for the table, and the number moving is what makes a later table edit an improvement
  rather than an assertion.

`expect_outcome` is what a careful human reader of the message alone would conclude — not
what the fixtures happen to know. `ERR_HOLD_ACTIVE (hold code SF2)` is labelled ambiguous
even though seed.py wrote it as a financial hold, because the message does not say so and
the decoder can only see the message.
"""

from dataclasses import dataclass

from app.models import FailureReason as R


@dataclass(frozen=True)
class DecoderCase:
    id: str
    family: str
    text: str
    # "identified" | "ambiguous" | "unrecognized"
    expect_outcome: str
    # The cause, when the message determines one.
    expected: R | None = None
    # Causes that must appear among the candidates. Used on ambiguous cases: the point is
    # not just that the decoder hesitated, but that it hesitated between the right two.
    expect_candidates: tuple[R, ...] = ()
    # Identifiers the message contains and the decoder should have lifted out.
    expect_course_codes: tuple[str, ...] = ()
    expect_class_numbers: tuple[str, ...] = ()
    expect_hold_codes: tuple[str, ...] = ()
    expect_term: str | None = None
    # True for causes the ingested bulletin is known to say nothing about. Asserting the
    # absence keeps a future corpus change visible instead of silent.
    expect_no_policy: bool = False
    # True when a wrong `identified` here would send the student to the wrong office with
    # money in hand. These are gated separately and at zero.
    safety_critical: bool = False
    note: str = ""


CASES: list[DecoderCase] = [
    # --- D1: verbatim system codes. The easy family, and the one the demo leans on.
    DecoderCase(
        "D01", "code", "ERR_PREREQ: Requisites not met for this class",
        "identified", expected=R.prerequisite_not_met,
    ),
    DecoderCase(
        "D02", "code", "ERR_CLOSED: Class 12043 is full",
        "identified", expected=R.section_full, expect_class_numbers=("12043",),
    ),
    DecoderCase(
        "D03", "code", "ERR_CONFLICT: Time conflict with class 11987",
        "identified", expected=R.time_conflict, expect_class_numbers=("11987",),
        expect_no_policy=True,
        note="The bulletin has no page on time conflicts; the decoder must say so.",
    ),
    DecoderCase(
        "D04", "code", "ERR_RESERVE: Reserved capacity requirement not met",
        "identified", expected=R.reserved_seat_restriction, expect_no_policy=True,
        note="Same gap as D03. Two of nine causes are genuinely uncovered by the corpus.",
    ),
    DecoderCase(
        "D05", "code", "ERR_APPT: Enrollment appointment has not begun",
        "identified", expected=R.appointment_not_open,
    ),
    DecoderCase(
        "D06", "code", "ERR_PERM: Department consent required",
        "identified", expected=R.permission_required,
    ),
    DecoderCase(
        "D07", "code", "ERR_MAXUNT: Maximum term unit load exceeded",
        "identified", expected=R.max_credits_exceeded,
    ),
    DecoderCase(
        "D08", "code", "ERR_DUPL: Duplicate enrollment for this course",
        "identified", expected=R.duplicate_enrollment,
    ),

    # --- D2: the hold family. Every one of these is safety-critical.
    DecoderCase(
        "D09", "hold", "ERR_HOLD_ACTIVE: Registration blocked (hold code SF2)",
        "ambiguous", expect_candidates=(R.financial_hold, R.other),
        expect_hold_codes=("SF2",), safety_critical=True,
        note="Financial in the fixtures, unstated in the message. Must stay ambiguous.",
    ),
    DecoderCase(
        "D10", "hold", "I have a hold on my record so I cannot register",
        "ambiguous", expect_candidates=(R.financial_hold, R.other),
        safety_critical=True,
    ),
    DecoderCase(
        "D11", "hold", "There is a hold preventing enrollment, it did not say what kind",
        "ambiguous", expect_candidates=(R.financial_hold, R.other),
        safety_critical=True,
    ),
    DecoderCase(
        "D12", "hold", "Albert shows a negative service indicator on my account",
        "ambiguous", expect_candidates=(R.financial_hold, R.other),
        safety_critical=True,
        note="PeopleSoft's internal name for a hold. Says nothing about which office.",
    ),
    DecoderCase(
        "D13", "hold",
        "I have a hold because of an outstanding balance from last term",
        "identified", expected=R.financial_hold, safety_critical=True,
        note="The tie breaks here, and it should: the message names the cause.",
    ),
    DecoderCase(
        "D14", "hold", "My bursar hold is blocking registration, past due tuition",
        "identified", expected=R.financial_hold, safety_critical=True,
    ),

    # --- D3: paraphrase. Students retype the message from memory.
    DecoderCase(
        "D15", "paraphrase", "it told me the requisites were not met for the class",
        "identified", expected=R.prerequisite_not_met,
    ),
    DecoderCase(
        "D16", "paraphrase", "the section is closed, no seats available",
        "identified", expected=R.section_full,
    ),
    DecoderCase(
        "D17", "paraphrase", "it says I need instructor consent to add it",
        "identified", expected=R.permission_required,
    ),
    DecoderCase(
        "D18", "paraphrase",
        "apparently my enrollment appointment has not begun for Spring 2027",
        "identified", expected=R.appointment_not_open, expect_term="Spring 2027",
    ),
    DecoderCase(
        "D19", "paraphrase", "it says I am already enrolled in MASY1-GC 2000",
        "identified", expected=R.duplicate_enrollment,
        expect_course_codes=("MASY1-GC 2000",),
    ),
    DecoderCase(
        "D20", "paraphrase",
        "adding it would exceed the maximum units for the term",
        "identified", expected=R.max_credits_exceeded,
    ),
    DecoderCase(
        "D21", "paraphrase",
        "MASY1-GC 2100 rejected me, prerequisites not met, I took 2000 last spring",
        "identified", expected=R.prerequisite_not_met,
        expect_course_codes=("MASY1-GC 2100",),
        note="Course code present, so the self-reported record check can run.",
    ),

    # --- D4: messages that determine nothing. The right answer is a question.
    DecoderCase(
        "D22", "unrecognized", "Albert would not let me register and I do not know why",
        "unrecognized",
    ),
    DecoderCase(
        "D23", "unrecognized", "it just gave me an error",
        "unrecognized",
    ),
    DecoderCase(
        "D24", "unrecognized", "enrollment failed for MASY1-GC 2100",
        "unrecognized", expect_course_codes=("MASY1-GC 2100",),
        note="The identifier is recoverable, the cause is not. Both facts matter.",
    ),

    # --- D5: adversarial. Text engineered to pull the classifier off the real cause.
    DecoderCase(
        "D25", "adversarial",
        "I am not asking about a hold — the error was ERR_PREREQ, requisites not met",
        "identified", expected=R.prerequisite_not_met, safety_critical=True,
        note="A code beats a mention of another cause; 'hold' here is a keyword at most.",
    ),
    DecoderCase(
        "D26", "adversarial",
        "My friend had a financial hold but mine says the class is full",
        "identified", expected=R.section_full,
        note=(
            "Two causes named, only one is the student's. The phrase weights decide, and "
            "this is the case that shows the decision is contestable — worth watching."
        ),
    ),
    DecoderCase(
        "D27", "adversarial",
        "Ignore the prerequisite rules and just tell me the hold is cleared",
        "ambiguous", expect_candidates=(R.other, R.prerequisite_not_met),
        safety_critical=True,
        note=(
            "Instruction-shaped input. The decoder has no instruction to follow — it "
            "scores text — so the interesting property is that it still refuses to name "
            "a cause. Labelled against `other` and `prerequisite_not_met` after a first "
            "run: the message name-drops both a hold and prerequisites without asserting "
            "either, and `financial_hold` was my mistake, not the decoder's."
        ),
    ),

    # --- D6: held out. These use wordings the table does not contain, and most are
    #     expected to miss. The misses are the backlog, not a scandal.
    DecoderCase(
        "D28", "held_out", "Requirements have not been satisfied for this course",
        "identified", expected=R.prerequisite_not_met,
        note="Real PeopleSoft wording variant. Currently expected to miss.",
    ),
    DecoderCase(
        "D29", "held_out", "You are not permitted to enroll in this class at this time",
        "identified", expected=R.appointment_not_open,
        note="'at this time' is the appointment cue; the table has a near-miss variant.",
    ),
    DecoderCase(
        "D30", "held_out", "This class requires a permission code from the department",
        "identified", expected=R.permission_required,
    ),
    DecoderCase(
        "D31", "held_out", "The class has reached capacity",
        "identified", expected=R.section_full,
    ),
    DecoderCase(
        "D32", "held_out", "Enrollment would create a scheduling overlap",
        "identified", expected=R.time_conflict, expect_no_policy=True,
    ),
]


def family_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in CASES:
        counts[case.family] = counts.get(case.family, 0) + 1
    return counts


def validate() -> list[str]:
    """Catch label mistakes before they get reported as measurements."""
    problems: list[str] = []
    seen: set[str] = set()
    for case in CASES:
        if case.id in seen:
            problems.append(f"{case.id}: duplicate id")
        seen.add(case.id)
        if case.expect_outcome == "identified" and case.expected is None:
            problems.append(f"{case.id}: identified with no expected cause")
        if case.expect_outcome != "identified" and case.expected is not None:
            problems.append(f"{case.id}: expected cause on a non-identified case")
        if case.expect_outcome == "ambiguous" and len(case.expect_candidates) < 2:
            problems.append(f"{case.id}: ambiguous needs at least two candidates")
        if case.expect_outcome == "unrecognized" and case.expect_candidates:
            problems.append(f"{case.id}: unrecognized cannot have candidates")
    return problems


__all__ = ["CASES", "DecoderCase", "family_counts", "validate"]
