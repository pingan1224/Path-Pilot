"""Shapes the planning engine speaks in.

The central decision here is that a finding is one of three things, never two. A tool
whose vocabulary is only pass/fail is forced to call everything it cannot check a failure
or a success, and both are lies. The third value is what makes honesty expressible:

    satisfied     — verified true from encoded rules and the student's stated record
    conditional   — true given something outside this tool (approval, a seat, a GPA it
                    cannot see); the condition is stated in the bulletin's own words
    unverifiable  — the rules do not cover it, or the data needed is only in Albert

`unverifiable` is not a bug to be driven to zero. Cross-school electives, departmental
permission, and seat availability are permanently unverifiable here, and saying so is the
product. What must be zero is a `satisfied` that should have been one of the other two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    satisfied = "satisfied"
    conditional = "conditional"
    unverifiable = "unverifiable"
    not_satisfied = "not_satisfied"


class CourseState(str, Enum):
    """What the student says about a course. Everything is self-reported."""

    completed = "completed"
    in_progress = "in_progress"
    planned = "planned"


@dataclass(frozen=True)
class Citation:
    """Where a finding came from, in a form a student can go and check."""

    label: str
    url: str | None = None
    # ISO date the source was last fetched or the rule last confirmed.
    verified_on: str | None = None
    # The source's own sentence, when quoting it is better than paraphrasing.
    quote: str | None = None


@dataclass(frozen=True)
class Finding:
    """One checkable statement about a plan."""

    verdict: Verdict
    # Short enough for a list item; the reason carries the detail.
    summary: str
    detail: str
    citations: tuple[Citation, ...] = ()
    # What the student should do about it, when there is something to do.
    next_step: str | None = None
    # Set when the verdict depends on something this tool cannot see.
    check_in_albert: bool = False
    # Stable identity for the *subject* of the finding, deliberately independent of the
    # verdict and of any number in the summary: `requirement:Electives`,
    # `prereq:MASY1-GC 2100:MASY1-GC 2000`, `catalog:MKTG-GB 2350`.
    #
    # This exists so a student can say "I know about this one, I am handling it" and have
    # that still refer to the same thing next week. Keying on the summary would break the
    # moment "3 credit(s) short" became "6 credit(s) short" — silently dropping an
    # acknowledgement is how a task tracker starts lying about what has been dealt with.
    # Keying on the verdict would be worse: the acknowledgement would vanish exactly when
    # the situation changed and the student most needed to see their earlier decision.
    key: str = ""
    # The course this finding is about, when it is about a course at all. Requirement-level
    # findings have none. Used to separate "blockers for the courses you actually chose"
    # from "where you stand on the degree", which are different questions with different
    # answers and must not be pooled.
    subject: str | None = None

    @property
    def blocking(self) -> bool:
        return self.verdict is Verdict.not_satisfied


@dataclass(frozen=True)
class StatedCourse:
    """A course the student says they have taken, are taking, or intend to take."""

    code: str
    state: CourseState
    term: str | None = None
    # Self-reported grades matter for prerequisites with a minimum grade. Absent means the
    # student did not say, which is different from a failing grade and must not be treated
    # as one.
    grade: str | None = None


@dataclass
class PlanResult:
    """Everything the engine concluded, ready for the model to narrate."""

    findings: list[Finding] = field(default_factory=list)
    # Float, because half credits are real and they are not decoration: three encoded
    # degrees (MSEM, TCTM, TCHS) are built out of 1.5-credit courses, and MSEM's internship
    # — a single 1.5-credit *required* course — means the first thing such a student enters
    # produces a fractional total. These were annotated `int` while `CourseRule.credits` was
    # already float, so the lie was invisible here and surfaced two layers away as a 500
    # from `/plan` when pydantic refused to coerce 1.5. `credits_required` stays float for
    # symmetry with the other three even though its column is Integer today.
    credits_completed: float = 0.0
    credits_in_progress: float = 0.0
    credits_planned: float = 0.0
    credits_required: float = 0.0

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    @property
    def needs_human(self) -> list[Finding]:
        return [
            f
            for f in self.findings
            if f.verdict in (Verdict.conditional, Verdict.unverifiable)
        ]

    def summary_counts(self) -> dict[str, int]:
        counts = {v.value: 0 for v in Verdict}
        for finding in self.findings:
            counts[finding.verdict.value] += 1
        return counts
