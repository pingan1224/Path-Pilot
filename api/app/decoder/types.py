"""Shapes the decoder speaks in.

The load-bearing decision here is that a classification has three outcomes, not two.
A classifier whose vocabulary is only "here is the cause" / "no idea" has to resolve
every genuinely ambiguous message into one of those, and both resolutions are wrong:
naming a cause it cannot distinguish sends the student to the wrong office, and giving
up throws away the two candidates it *did* narrow to.

    identified    — one cause, and the evidence separates it from its siblings
    ambiguous     — the message is consistent with several causes; the discriminating
                    question is returned instead of a guess
    unrecognized  — nothing in the rule table matched

`ambiguous` is the outcome the product is built around. "You have a hold on your record"
genuinely does not say which office placed it, and no amount of pattern matching can
recover what the message never contained. Answering "that is a financial hold" would be
a fabrication with a plausible tone, which is the most dangerous kind — the student pays
a balance they may not owe and misses the advising appointment that was actually
blocking them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models import FailureReason


class DecodeOutcome(str, Enum):
    identified = "identified"
    ambiguous = "ambiguous"
    unrecognized = "unrecognized"


class EvidenceKind(str, Enum):
    """How strong a match is, which is the whole basis of the score.

    `code` is an error token the system emitted (`ERR_PREREQ`); it is close to
    conclusive because a machine wrote it. `phrase` is a sentence fragment students
    quote or paraphrase. `keyword` is a single suggestive word and is deliberately too
    weak on its own to name a cause — a hunch that reaches a verdict is how a decoder
    starts confidently misrouting people.
    """

    code = "code"
    phrase = "phrase"
    keyword = "keyword"


WEIGHTS = {EvidenceKind.code: 10, EvidenceKind.phrase: 4, EvidenceKind.keyword: 1}


@dataclass(frozen=True)
class Evidence:
    """Why a candidate scored: the literal substring out of the student's own text.

    This is the classifier's equivalent of a citation. The student can see that
    "requisites not met" is what triggered the prerequisite reading, so a wrong
    classification is visibly wrong rather than mysteriously wrong — and a right one is
    checkable without trusting us.
    """

    kind: EvidenceKind
    # The pattern from the rule table.
    pattern: str
    # What it matched in the input, as the student typed it, case preserved.
    matched: str
    # Character offsets into the original text, so the UI can highlight in place.
    start: int
    end: int

    @property
    def weight(self) -> int:
        return WEIGHTS[self.kind]


@dataclass(frozen=True)
class Candidate:
    reason: FailureReason
    score: int
    evidence: tuple[Evidence, ...]

    @property
    def strongest_kind(self) -> EvidenceKind:
        return min((e.kind for e in self.evidence), key=lambda k: -WEIGHTS[k])


@dataclass(frozen=True)
class Extracted:
    """Identifiers lifted out of the message, for the parts of the answer that need them.

    A prerequisite error naming no course is a different (and much less useful) object
    than one naming MASY1-GC 2100: only the second can be checked against the student's
    stated record. What is missing here is what the follow-up questions ask for.
    """

    course_codes: tuple[str, ...] = ()
    # PeopleSoft-style five-digit class numbers, e.g. "class 12043".
    class_numbers: tuple[str, ...] = ()
    # Whatever the message called a hold code. Deliberately NOT interpreted — see
    # patterns.HOLD_CODE_NOTE.
    hold_codes: tuple[str, ...] = ()
    term: str | None = None


@dataclass(frozen=True)
class FollowUp:
    """One question whose answer would change the decoding.

    Not conversational filler: each of these either separates two candidate causes or
    fills a slot the specific answer needs. A question that would not change the output
    does not belong here, because every question spends the student's patience and the
    ones that matter have to survive that budget.
    """

    question: str
    why: str
    # Populated when answering would separate candidates.
    discriminates: tuple[FailureReason, ...] = ()
    # Populated when answering would fill a missing identifier ("course_code", "term").
    fills: str | None = None


@dataclass(frozen=True)
class Classification:
    outcome: DecodeOutcome
    # Set only when outcome is `identified`. Ambiguous results carry candidates instead,
    # so a caller cannot accidentally read a guess out of this field.
    reason: FailureReason | None
    candidates: tuple[Candidate, ...]
    extracted: Extracted
    follow_ups: tuple[FollowUp, ...]
    confidence: str  # high | medium | low
    # What the scorer actually saw, kept for the audit trail and for debugging patterns.
    normalized_text: str

    @property
    def top(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


@dataclass
class RecordCheck:
    """What the student's self-reported record says about the decoded cause.

    Never a claim about Albert. This runs the same prerequisite engine the planner uses,
    over the courses the student typed in themselves, and says so in `basis`. When the
    engine confirms the error ("you have not reported MASY1-GC 2000"), that is the single
    most useful sentence the decoder produces — and when it contradicts the error, saying
    so plainly is what sends the student to a human with something concrete.
    """

    performed: bool
    basis: str
    findings: list[dict] = field(default_factory=list)
    note: str | None = None


@dataclass
class DecodeResult:
    classification: Classification
    # Restates what the message says, in plain language. Deliberately carries no policy
    # content — the policy comes from `passages`, which are cited.
    reading: str | None
    what_to_do: tuple[str, ...]
    responsible_office: str | None
    passages: list[dict] = field(default_factory=list)
    record_check: RecordCheck | None = None
    # Where to look for the part only the student information system knows.
    albert: dict | None = None
    # The message plus any follow-up answers, exactly as classified. Evidence offsets
    # index into this string, so the UI has to render this text — not the original box
    # contents — for the highlights to land on the right words.
    text_used: str = ""
    # Set when retrieval found nothing that actually mentions the decoded cause. Saying so
    # is the point: an unsourced explanation labelled as unsourced is usable, and the same
    # explanation propped up by three unrelated policy links is not.
    no_policy_note: str | None = None
    # Every source id handed out, so the assistant can cite this decoding by id.
    source_ids: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    disclaimer: str = (
        "This reads the message you pasted and the published rules. Path Pilot has no access to "
        "Albert and cannot see your record, your holds, or the seat counts. Confirm "
        "anything that affects registration in Albert."
    )
