"""Scoring an error message against the rule table.

Pure functions over a string. No database, no model, no I/O — the same property that
makes `planning/rules.py` testable, for the same reason: a classification that can be
wrong needs to be wrong reproducibly.

The scoring is deliberately boring. Each pattern that matches contributes its weight
once, the highest total wins, and it only *wins* if it clears an absolute floor and beats
the runner-up by a margin. Both conditions matter and they fail differently:

* Without the floor, a single suggestive word ("hold", "units") would be enough to name
  a cause, and the decoder would confidently route people on a hunch.
* Without the margin, two causes tied at the top would silently resolve to whichever the
  iteration order happened to reach first — the worst kind of bug, because it looks
  decisive and is arbitrary.

An input that clears neither is not a failure of the classifier. It is a message that
does not contain the answer, and the follow-up question is the output.
"""

from __future__ import annotations

import re

from app.decoder.patterns import (
    SLOT_QUESTIONS,
    SPECS,
    discriminating_question,
)
from app.decoder.types import (
    Candidate,
    Classification,
    DecodeOutcome,
    Evidence,
    EvidenceKind,
    Extracted,
    FollowUp,
    WEIGHTS,
)
from app.models import FailureReason

# A cause must be backed by at least one phrase or code match. Equal to the phrase weight
# on purpose: keyword hits accumulate but can never reach it alone, so "hold" appearing
# three times still does not name a cause.
MIN_SCORE_TO_NAME = WEIGHTS[EvidenceKind.phrase]

# How far ahead the leader has to be. Three is one keyword short of a phrase: a cause
# wins on evidence the runner-up lacks, not on a shared signal plus a stray word.
DECISIVE_MARGIN = 3

# More than three questions at once reads as an interrogation and gets abandoned.
MAX_FOLLOW_UPS = 3

# NYU subject codes carry an optional trailing digit (MASY1-GC) and a two-letter school
# suffix; the number is three or four digits. Written to accept the spacing students
# actually type, including none at all.
COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,5}\d?)\s*-\s*([A-Z]{2})\s*(\d{3,4})\b", re.I)

# Only with an anchoring word. A bare five-digit number in a pasted message is as likely
# to be a course number, a term code, or a student id, and quietly reading it as a class
# number would put a wrong identifier into an otherwise correct answer.
CLASS_NUMBER_RE = re.compile(r"\b(?:class|section|nbr|number)\s*(?:nbr|number|#|:)?\s*(\d{4,6})\b", re.I)

# Echoed, never interpreted — see patterns.HOLD_CODE_NOTE.
HOLD_CODE_RE = re.compile(
    r"\bhold\s*(?:code|id|type)?\s*[:#(]?\s*([A-Z]{1,4}\s?\d{1,3})\b", re.I
)

TERM_RE = re.compile(
    r"\b(spring|summer|fall|autumn|winter|january|j-?term)\s*(?:of\s*)?(\d{4})\b", re.I
)
TERM_RE_REVERSED = re.compile(
    r"\b(\d{4})\s*(spring|summer|fall|autumn|winter)\b", re.I
)


def _normalize(text: str) -> tuple[str, list[int]]:
    """Lowercase and collapse whitespace, keeping a map back to the original offsets.

    The map is what lets the UI highlight the matched words in the student's own text.
    Matching on a normalized copy and reporting offsets into it would misplace every
    highlight the moment the pasted message contained a line break, which pasted messages
    invariably do.
    """
    out: list[str] = []
    index_map: list[int] = []
    previous_was_space = True  # leading whitespace is dropped
    for i, char in enumerate(text):
        if char.isspace():
            if previous_was_space:
                continue
            out.append(" ")
            index_map.append(i)
            previous_was_space = True
            continue
        out.append(char.lower())
        index_map.append(i)
        previous_was_space = False
    while out and out[-1] == " ":
        out.pop()
        index_map.pop()
    return "".join(out), index_map


def _span(index_map: list[int], start: int, length: int) -> tuple[int, int]:
    return (index_map[start], index_map[start + length - 1] + 1)


# What a `*` in a phrase pattern stands for: a short run of anything except a sentence
# boundary. Introduced because rigid phrases lose to ordinary English — the table had
# "requisites not met" and a student wrote "the requisites were not met", which is the same
# sentence with an auxiliary verb in it. Two words of slack recovers that whole class of
# near-miss without inventing a synonym list.
#
# The excluded punctuation is what stops it becoming a wildcard: without it, "hold" and
# "prevent" could bridge two unrelated sentences and score a phrase nobody wrote.
PHRASE_GAP = r"[^.;!?]{0,16}?"


def _find_phrase(
    normalized: str, index_map: list[int], original: str, pattern: str
) -> Evidence | None:
    if "*" in pattern:
        expression = PHRASE_GAP.join(
            re.escape(part.strip()) for part in pattern.lower().split("*")
        )
        match = re.search(expression, normalized)
        if match is None:
            return None
        at, length = match.start(), match.end() - match.start()
    else:
        at = normalized.find(pattern.lower())
        if at < 0:
            return None
        length = len(pattern)

    start, end = _span(index_map, at, length)
    return Evidence(
        kind=EvidenceKind.phrase,
        pattern=pattern,
        matched=original[start:end],
        start=start,
        end=end,
    )


def _find_token(
    normalized: str,
    index_map: list[int],
    original: str,
    pattern: str,
    kind: EvidenceKind,
) -> Evidence | None:
    """Word-boundary match, for error codes and single keywords.

    Boundaries are not cosmetic here: `ERR_HOLD` is a prefix of `ERR_HOLD_ACTIVE`, and a
    substring search would score the shorter pattern inside the longer one and inflate
    the total. `_` counts as a word character, so `\\berr_hold\\b` correctly declines to
    match inside `err_hold_active`.
    """
    match = re.search(rf"\b{re.escape(pattern.lower())}\b", normalized)
    if match is None:
        return None
    start, end = _span(index_map, match.start(), match.end() - match.start())
    return Evidence(
        kind=kind,
        pattern=pattern,
        matched=original[start:end],
        start=start,
        end=end,
    )


def _extract(text: str) -> Extracted:
    codes: list[str] = []
    for match in COURSE_CODE_RE.finditer(text):
        subject, school, number = match.groups()
        code = f"{subject.upper()}-{school.upper()} {number}"
        if code not in codes:
            codes.append(code)

    class_numbers: list[str] = []
    for match in CLASS_NUMBER_RE.finditer(text):
        if match.group(1) not in class_numbers:
            class_numbers.append(match.group(1))

    hold_codes: list[str] = []
    for match in HOLD_CODE_RE.finditer(text):
        code = " ".join(match.group(1).upper().split())
        if code not in hold_codes:
            hold_codes.append(code)

    term = None
    if (match := TERM_RE.search(text)) is not None:
        term = f"{match.group(1).title()} {match.group(2)}"
    elif (match := TERM_RE_REVERSED.search(text)) is not None:
        term = f"{match.group(2).title()} {match.group(1)}"

    return Extracted(
        course_codes=tuple(codes),
        class_numbers=tuple(class_numbers),
        hold_codes=tuple(hold_codes),
        term=term,
    )


def _score(normalized: str, index_map: list[int], original: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for spec in SPECS:
        evidence: list[Evidence] = []
        for code in spec.codes:
            found = _find_token(normalized, index_map, original, code, EvidenceKind.code)
            if found:
                evidence.append(found)
        for phrase in spec.phrases:
            found = _find_phrase(normalized, index_map, original, phrase)
            if found:
                evidence.append(found)
        for keyword in spec.keywords:
            found = _find_token(
                normalized, index_map, original, keyword, EvidenceKind.keyword
            )
            if found:
                evidence.append(found)
        if not evidence:
            continue
        candidates.append(
            Candidate(
                reason=spec.reason,
                score=sum(e.weight for e in evidence),
                evidence=tuple(evidence),
            )
        )

    # Ties are broken by the enum's declaration order, which is stable across runs. It is
    # not meaningful — a tie is reported as ambiguous precisely so that nothing downstream
    # has to rely on this ordering being right.
    order = {r: i for i, r in enumerate(FailureReason)}
    candidates.sort(key=lambda c: (-c.score, order[c.reason]))
    return candidates


def _satisfied(slot: str, extracted: Extracted) -> bool:
    return {
        "course_code": bool(extracted.course_codes),
        "class_number": bool(extracted.class_numbers),
        "term": extracted.term is not None,
    }.get(slot, True)


def _follow_ups(
    outcome: DecodeOutcome,
    candidates: list[Candidate],
    extracted: Extracted,
) -> tuple[FollowUp, ...]:
    from app.decoder.patterns import BY_REASON

    out: list[FollowUp] = []

    if outcome is DecodeOutcome.unrecognized:
        out.append(
            FollowUp(
                question=(
                    "Can you paste the message exactly as Albert showed it, including any "
                    "code like ERR_PREREQ?"
                ),
                why=(
                    "The code is the part that names the cause. A summary of the message "
                    "usually leaves it out, and it is the difference between an answer and "
                    "a guess."
                ),
            )
        )
        return tuple(out)

    if outcome is DecodeOutcome.ambiguous:
        # Everything within a margin of the leader is genuinely in play. Asking about the
        # leader alone would presuppose the answer.
        leader = candidates[0].score
        tied = [c for c in candidates if leader - c.score < DECISIVE_MARGIN][:3]
        scripted = False
        for i, first in enumerate(tied):
            for second in tied[i + 1 :]:
                pair = discriminating_question(first.reason, second.reason)
                if pair is None:
                    continue
                question, why = pair
                out.append(
                    FollowUp(
                        question=question,
                        why=why,
                        discriminates=(first.reason, second.reason),
                    )
                )
                scripted = True
        if not scripted and len(tied) > 1:
            labels = [BY_REASON[c.reason].label.lower() for c in tied]
            out.append(
                FollowUp(
                    question=(
                        "Which of these matches what Albert showed you: "
                        + "; or ".join(labels)
                        + "?"
                    ),
                    why=(
                        "The message is consistent with more than one of these, and they "
                        "are resolved by different people."
                    ),
                    discriminates=tuple(c.reason for c in tied),
                )
            )
        if not out:
            # A lone weak candidate: something in the text was suggestive, nothing was
            # decisive. There is no pair to discriminate between, so the useful question
            # is for the part of the message that got lost on the way here.
            out.append(
                FollowUp(
                    question=(
                        "Can you paste the whole message, including any code like "
                        "ERR_PREREQ or the class number?"
                    ),
                    why=(
                        "One word in what you sent points at "
                        f"{BY_REASON[candidates[0].reason].label.lower()}, but that is a "
                        "hunch rather than a reading, and it is not worth acting on."
                    ),
                )
            )

    if outcome is DecodeOutcome.identified:
        spec = BY_REASON[candidates[0].reason]
        for slot in spec.needs:
            if _satisfied(slot, extracted):
                continue
            question, why = SLOT_QUESTIONS[slot]
            out.append(FollowUp(question=question, why=why, fills=slot))

    return tuple(out[:MAX_FOLLOW_UPS])


def classify(text: str) -> Classification:
    """Decide what a pasted registration error says, or report why it cannot be decided."""
    original = text or ""
    normalized, index_map = _normalize(original)

    if not normalized:
        return Classification(
            outcome=DecodeOutcome.unrecognized,
            reason=None,
            candidates=(),
            extracted=Extracted(),
            follow_ups=_follow_ups(DecodeOutcome.unrecognized, [], Extracted()),
            confidence="low",
            normalized_text="",
        )

    extracted = _extract(original)
    candidates = _score(normalized, index_map, original)

    if not candidates:
        outcome = DecodeOutcome.unrecognized
    else:
        leader = candidates[0].score
        runner_up = candidates[1].score if len(candidates) > 1 else 0
        decisive = (
            leader >= MIN_SCORE_TO_NAME and (leader - runner_up) >= DECISIVE_MARGIN
        )
        outcome = DecodeOutcome.identified if decisive else DecodeOutcome.ambiguous

    reason = candidates[0].reason if outcome is DecodeOutcome.identified else None

    if outcome is DecodeOutcome.identified:
        has_code = any(
            e.kind is EvidenceKind.code for e in candidates[0].evidence
        )
        confidence = "high" if has_code else "medium"
    else:
        confidence = "low"

    return Classification(
        outcome=outcome,
        reason=reason,
        candidates=tuple(candidates),
        extracted=extracted,
        follow_ups=_follow_ups(outcome, candidates, extracted),
        confidence=confidence,
        normalized_text=normalized,
    )
