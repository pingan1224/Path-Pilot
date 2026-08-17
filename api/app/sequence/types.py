"""Shapes the sequence planner speaks in.

The planner answers "in what order can I take what is left, and by when". Its output has to
carry two things a bare schedule does not:

**What each placement rests on.** A course placed in Spring 2028 because the bulletin says
it runs in spring is a different claim from the same course placed there because the
bulletin says nothing and the solver had a slot. Both are useful; presenting them
identically is not, because the student plans around the second one as if it were the first.

**Which constraint is binding, when there is no answer.** "No sequence fits" is almost
useless on its own. "No sequence fits because the capstone only runs in the fall and needs a
course that only runs in the spring, so you need one more term" is the thing a student can
act on. See `solver.explain_infeasibility`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.sequence.offerings import Offering
from app.sequence.terms import Term


class Constraint(str, Enum):
    """The constraints the search enforces, named so infeasibility can point at one."""

    prerequisites = "prerequisites"
    offering = "offering"
    credit_cap = "credit_cap"
    deadline = "deadline"


CONSTRAINT_LABEL = {
    Constraint.prerequisites: "prerequisite order",
    Constraint.offering: "when courses are offered",
    Constraint.credit_cap: "the credits you are willing to take per term",
    Constraint.deadline: "the term you want to finish by",
}


@dataclass(frozen=True)
class CourseNeed:
    """One course still to be taken, with everything the search needs about it."""

    code: str
    title: str
    # Float: fed from `CourseRule.credits`, and from a `credits`-requirement shortfall,
    # both of which can be fractional. The per-term cap sums these, so an int annotation
    # here quietly claims a 1.5-credit course cannot exist.
    credits: float
    offering: Offering
    # Each inner tuple is an OR-group; every group must be satisfied by an earlier term or
    # by coursework already held.
    prerequisite_groups: tuple[tuple[str, ...], ...] = ()
    # Prerequisites the catalog allows to be taken alongside rather than before.
    concurrent_ok: frozenset[str] = frozenset()
    # Which requirement this course is being taken for, for grouping in the answer.
    requirement: str | None = None


@dataclass(frozen=True)
class Placement:
    course: CourseNeed
    term: Term

    @property
    def rests_on_assumption(self) -> bool:
        return self.course.offering.is_assumption


@dataclass(frozen=True)
class Assumption:
    """Something the answer depends on that the tool could not verify.

    Collected rather than footnoted. The sequence is only as good as these, and a student
    reading a clean-looking three-term plan has no way to know which parts of it are load
    bearing unless the tool says so in the same breath.
    """

    subject: str
    statement: str
    # What to do about it, when there is something.
    check: str | None = None


@dataclass(frozen=True)
class Infeasibility:
    """Why there is no sequence, established by relaxation rather than by guessing."""

    # Constraints whose removal, on its own, produces a workable sequence.
    binding: tuple[Constraint, ...]
    explanation: str
    # What relaxing each one would take, in the student's terms.
    remedies: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrackOption:
    """A concentration that fits, summarised against the one being recommended.

    A `one_track` requirement is a choice, not a constraint: the solver sequences each
    concentration separately and picks by finish date, but "soonest" is the product's
    tiebreak, not necessarily the student's reason. Business Analytics a term later may
    still be the one they want. Reporting only the winner makes that decision for them.

    A summary rather than the whole schedule, because the question a student asks first is
    "does it still fit", not "show me every term". `terms_later_than_chosen` answers it in
    the unit they think in, and `GET /sequence?track=` returns the full board for the one
    they want to look at properly.
    """

    track: str
    finish_term: Term
    # Placements resting on a term the bulletin does not state. Two plans finishing
    # together are not equally solid, and this is the difference.
    guesses: int
    terms_later_than_chosen: int
    # None when the student has stated no target. False means this track finishes after a
    # deadline the chosen one meets — the sharpest thing the comparison can say.
    meets_deadline: bool | None = None


@dataclass(frozen=True)
class SequencePlan:
    feasible: bool
    # In term order. Empty when infeasible.
    placements: tuple[Placement, ...] = ()
    # The track chosen when the program requires picking one concentration.
    chosen_track: str | None = None
    # Tracks that were considered and could not be sequenced, with the reason.
    rejected_tracks: tuple[tuple[str, str], ...] = ()
    # Tracks that *can* be sequenced but lost the tiebreak. Kept because losing on finish
    # date is not the same as not fitting, and the student is the one who gets to weigh a
    # term against a subject they would rather study.
    alternatives: tuple[TrackOption, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    infeasibility: Infeasibility | None = None
    # Terms actually used, so the caller can say "three more terms" without recomputing.
    terms_used: tuple[Term, ...] = ()
    # Courses the planner could not reason about at all — not in the loaded catalog.
    unplaceable: tuple[str, ...] = field(default_factory=tuple)

    @property
    def finish_term(self) -> Term | None:
        return self.terms_used[-1] if self.terms_used else None

    def by_term(self) -> dict[Term, list[Placement]]:
        out: dict[Term, list[Placement]] = {}
        for placement in self.placements:
            out.setdefault(placement.term, []).append(placement)
        return out
