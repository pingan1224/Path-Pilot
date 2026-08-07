"""Classifier tests.

Weighted the same way the planning tests are: towards the cases where being wrong costs
the student something. A misread error message sends them to an office that cannot help,
on a day when their registration window is open and seats are moving.

Three invariants carry most of the weight here:

* **A keyword never names a cause.** Everything the classifier is confident about must be
  backed by an error code or a phrase.
* **Generic hold text stays ambiguous.** The message does not say which office placed the
  hold, so neither does the decoder.
* **Confidence tracks the evidence kind, not the score.** A phrase-only match is
  `medium` however many phrases piled up, because none of them was written by a machine.
"""

import pytest

from app.decoder.classify import (
    DECISIVE_MARGIN,
    MIN_SCORE_TO_NAME,
    classify,
)
from app.decoder.patterns import BY_REASON, SPECS
from app.decoder.types import DecodeOutcome, EvidenceKind
from app.models import FailureReason


# --------------------------------------------------------------------------------------
# The seeded error strings — the exact text scripts/seed.py writes into raw_error
# --------------------------------------------------------------------------------------

SEEDED = [
    ("ERR_PREREQ: Requisites not met for this class", FailureReason.prerequisite_not_met),
    ("ERR_CLOSED: Class 12043 is full", FailureReason.section_full),
    ("ERR_CONFLICT: Time conflict with class 11987", FailureReason.time_conflict),
    (
        "ERR_RESERVE: Reserved capacity requirement not met",
        FailureReason.reserved_seat_restriction,
    ),
    ("ERR_APPT: Enrollment appointment has not begun", FailureReason.appointment_not_open),
    ("ERR_PERM: Department consent required", FailureReason.permission_required),
    ("ERR_MAXUNT: Maximum term unit load exceeded", FailureReason.max_credits_exceeded),
    ("ERR_DUPL: Duplicate enrollment for this course", FailureReason.duplicate_enrollment),
]


@pytest.mark.parametrize(("text", "expected"), SEEDED)
def test_seeded_error_strings_are_identified(text, expected):
    result = classify(text)
    assert result.outcome is DecodeOutcome.identified
    assert result.reason is expected
    assert result.confidence == "high"


def test_seeded_hold_error_is_the_one_that_stays_ambiguous():
    """`ERR_HOLD_ACTIVE: Registration blocked (hold code SF2)` is in the fixtures as a
    financial hold, and the decoder still must not say so.

    The seed knows it is financial because the seed invented it. The message does not say
    it, and the decoder only sees the message. Encoding `SF2 -> bursar` would make this
    case look sharper and would be a fabricated mapping — the demo passing is not worth a
    student paying a balance to clear an advising hold.
    """
    result = classify("ERR_HOLD_ACTIVE: Registration blocked (hold code SF2)")

    assert result.outcome is DecodeOutcome.ambiguous
    assert result.reason is None
    reasons = {c.reason for c in result.candidates}
    assert FailureReason.financial_hold in reasons
    assert FailureReason.other in reasons
    # The code is carried, uninterpreted, so the student can take it to Albert.
    assert result.extracted.hold_codes == ("SF2",)
    # And the question asked is the one that resolves it.
    assert any("which office" in f.question.lower() for f in result.follow_ups)


# --------------------------------------------------------------------------------------
# Natural phrasing — students paraphrase, and the paraphrase is what arrives
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("It says requisites not met", FailureReason.prerequisite_not_met),
        ("the class is full", FailureReason.section_full),
        ("there is a time conflict with another class", FailureReason.time_conflict),
        ("it wants department consent", FailureReason.permission_required),
        ("my enrollment appointment has not begun yet", FailureReason.appointment_not_open),
        ("seats are reserved for another group", FailureReason.reserved_seat_restriction),
        ("it says I am already enrolled", FailureReason.duplicate_enrollment),
        ("this would put me over the maximum units", FailureReason.max_credits_exceeded),
        ("I have a financial hold from the bursar", FailureReason.financial_hold),
    ],
)
def test_paraphrases_are_identified_with_medium_confidence(text, expected):
    result = classify(text)
    assert result.reason is expected
    # No machine wrote these words, so the ceiling is medium however strong the score.
    assert result.confidence == "medium"


def test_case_and_whitespace_do_not_matter():
    messy = "  ERR_PREREQ:\n\n   REQUISITES   NOT MET\tfor this class  "
    assert classify(messy).reason is FailureReason.prerequisite_not_met


# --------------------------------------------------------------------------------------
# The no-false-confidence invariants
# --------------------------------------------------------------------------------------


def test_a_lone_keyword_never_names_a_cause():
    """"units" alone is a hunch, and a hunch that reaches a verdict misroutes people."""
    result = classify("something about units")
    assert result.outcome is not DecodeOutcome.identified
    assert result.reason is None
    # It is still worth showing the hunch and asking for the rest of the message.
    assert result.follow_ups


@pytest.mark.parametrize(
    "text",
    [
        "I have a hold on my record",
        "there is a hold preventing registration",
        "registration is blocked",
        "negative service indicator on my account",
    ],
)
def test_generic_hold_text_never_resolves_to_financial(text):
    result = classify(text)
    assert result.reason is not FailureReason.financial_hold
    assert result.outcome is DecodeOutcome.ambiguous


def test_a_financial_cue_breaks_the_hold_tie():
    """The tie is not permanent — evidence the message actually contains resolves it."""
    generic = classify("I have a hold on my record")
    specific = classify("I have a hold on my record because of my past due balance")

    assert generic.reason is None
    assert specific.reason is FailureReason.financial_hold


def test_every_identified_result_is_backed_by_a_code_or_phrase():
    for text, _ in SEEDED:
        result = classify(text)
        kinds = {e.kind for e in result.candidates[0].evidence}
        assert kinds & {EvidenceKind.code, EvidenceKind.phrase}


def test_unrecognized_input_asks_for_the_message_verbatim():
    result = classify("it didn't work, I don't know why")
    assert result.outcome is DecodeOutcome.unrecognized
    assert result.reason is None
    assert result.candidates == ()
    assert len(result.follow_ups) == 1
    assert "ERR_" in result.follow_ups[0].question


def test_empty_input_does_not_crash():
    for text in ("", "   ", "\n\t"):
        result = classify(text)
        assert result.outcome is DecodeOutcome.unrecognized
        assert result.normalized_text == ""


# --------------------------------------------------------------------------------------
# Evidence provenance — the classifier's answer to "why did you say that"
# --------------------------------------------------------------------------------------


def test_evidence_offsets_point_at_the_original_text():
    text = "Albert said:\n   ERR_PREREQ — requisites not met\n"
    result = classify(text)

    for evidence in result.candidates[0].evidence:
        # The slice must reproduce the matched string exactly, or a UI highlight built
        # from these offsets would land on the wrong words.
        assert text[evidence.start : evidence.end] == evidence.matched
        assert evidence.matched.lower().replace("\n", " ") or True


def test_evidence_survives_line_breaks_inside_a_phrase():
    """Pasted messages wrap. The normalizer collapses the break; the offsets must not."""
    text = "requisites\nnot met"
    result = classify(text)

    assert result.reason is FailureReason.prerequisite_not_met
    phrase = next(
        e for e in result.candidates[0].evidence if e.kind is EvidenceKind.phrase
    )
    assert text[phrase.start : phrase.end] == "requisites\nnot met"


def test_code_patterns_do_not_match_inside_longer_codes():
    """`ERR_HOLD` is a prefix of `ERR_HOLD_ACTIVE`; a substring search would count both."""
    result = classify("ERR_HOLD_ACTIVE")
    for candidate in result.candidates:
        codes = [e.pattern for e in candidate.evidence if e.kind is EvidenceKind.code]
        assert codes == ["ERR_HOLD_ACTIVE"]


# --------------------------------------------------------------------------------------
# Extraction — the identifiers that make an answer specific
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("prereq missing for MASY1-GC 2100", ("MASY1-GC 2100",)),
        ("cannot add MASY-GC 2400", ("MASY-GC 2400",)),
        ("blocked from MKTG-GB 2350 at Stern", ("MKTG-GB 2350",)),
        ("masy1-gc 2100 rejected me", ("MASY1-GC 2100",)),
        ("MASY1-GC2100 with no space", ("MASY1-GC 2100",)),
    ],
)
def test_course_codes_are_extracted_and_normalized(text, expected):
    assert classify(text).extracted.course_codes == expected


def test_class_numbers_need_an_anchoring_word():
    """A bare five-digit number is as likely to be a term code or a student id."""
    assert classify("time conflict with class 11987").extracted.class_numbers == ("11987",)
    assert classify("time conflict, reference 11987 whatever").extracted.class_numbers == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("registering for Fall 2026", "Fall 2026"),
        ("this was spring 2027", "Spring 2027"),
        ("2026 Fall registration", "Fall 2026"),
    ],
)
def test_terms_are_extracted(text, expected):
    assert classify(text).extracted.term == expected


def test_identified_result_asks_only_for_slots_it_is_missing():
    with_code = classify("ERR_PREREQ requisites not met for MASY1-GC 2100")
    without = classify("ERR_PREREQ requisites not met")

    assert not [f for f in with_code.follow_ups if f.fills == "course_code"]
    assert [f for f in without.follow_ups if f.fills == "course_code"]


def test_follow_up_answers_narrow_a_previously_missing_slot():
    """The second pass is a re-decode of the whole text, not a patch of the first."""
    first = classify("ERR_PREREQ: requisites not met")
    second = classify("ERR_PREREQ: requisites not met\nMASY1-GC 2100")

    assert first.extracted.course_codes == ()
    assert second.extracted.course_codes == ("MASY1-GC 2100",)
    assert second.reason is first.reason


# --------------------------------------------------------------------------------------
# Table integrity — cheap checks that catch an edit nobody meant to make
# --------------------------------------------------------------------------------------


def test_every_failure_reason_has_a_spec():
    assert {spec.reason for spec in SPECS} == set(FailureReason)


def test_every_spec_can_actually_be_named():
    """A spec with only keywords could never clear the floor, so it would be dead code."""
    for spec in SPECS:
        assert spec.codes or spec.phrases, f"{spec.reason} has no nameable evidence"


def test_every_spec_has_a_policy_query_and_next_steps():
    for spec in SPECS:
        assert spec.policy_query, f"{spec.reason} would be explained with no sources"
        assert spec.what_to_do, f"{spec.reason} would leave the student with no next step"


def test_every_spec_can_verify_its_own_retrieval():
    """Without `must_mention`, retrieval's top k gets cited whether or not it is on topic.

    Retrieval cannot return nothing. A cause with no verification stems would therefore
    always look sourced, including for the two causes the ingested corpus genuinely says
    nothing about.
    """
    for spec in SPECS:
        assert spec.must_mention, f"{spec.reason} would cite whatever came back"


def test_confusable_pairs_are_declared_symmetrically_or_have_a_question():
    """A pair the classifier can tie on needs someone to own the discriminating question."""
    for spec in SPECS:
        for other in spec.confusable_with:
            partner = BY_REASON[other]
            assert (
                spec.discriminator
                or partner.discriminator
                or spec.reason in partner.confusable_with
            ), f"{spec.reason} vs {other} has no question and no reciprocal declaration"


def test_only_the_hold_causes_share_patterns():
    """Shared patterns are how ambiguity is produced; anywhere else they are a mistake."""
    seen: dict[str, set[FailureReason]] = {}
    for spec in SPECS:
        for pattern in spec.codes + spec.phrases:
            seen.setdefault(pattern.lower(), set()).add(spec.reason)

    shared = {p: r for p, r in seen.items() if len(r) > 1}
    assert all(
        reasons == {FailureReason.financial_hold, FailureReason.other}
        for reasons in shared.values()
    ), f"unexpected shared patterns: {shared}"


def test_scoring_constants_stay_coherent():
    """The floor has to be unreachable by keywords, or the floor is not a floor."""
    from app.decoder.types import WEIGHTS

    assert MIN_SCORE_TO_NAME > WEIGHTS[EvidenceKind.keyword]
    assert DECISIVE_MARGIN > 0
    # A code alone must clear both bars against a phrase-scoring rival.
    assert WEIGHTS[EvidenceKind.code] - WEIGHTS[EvidenceKind.phrase] >= DECISIVE_MARGIN
