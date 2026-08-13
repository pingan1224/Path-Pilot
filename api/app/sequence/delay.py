"""What it costs to not take a course next term.

This is the piece that turns a list of courses into a plan. A planner that answers "take
these three" has told the student what, and nothing about why — and *why* is the only part
they can check. Priced in terms, the answer becomes arguable: *drop this one and you finish
in Fall 2027 instead of Spring 2027, because the capstone it unlocks only runs in spring.*

**Every number here comes from re-running the real search, never from reasoning about it.**
The counterfactual is asked the same way infeasibility is attributed one module over: change
one thing, solve again, compare. A cheaper implementation would inspect the baseline plan
and reason about prerequisite chains — and would be wrong exactly when the schedule is
complicated enough for the student to need help, which is the failure mode this codebase has
already rejected once for the same reason.

Two properties worth stating because they are easy to get wrong:

**Deferring is not deleting.** The course still has to be taken; it is held out of the next
term only. A student asking "can I skip this?" usually means "can this wait?", and the two
have different answers whenever a later term is tighter than the next one.

**The re-plan includes the choice of concentration.** Deferring a course can make a
different track finish sooner, and a version that only shifted rows in the existing answer
would report a delay the student could have avoided by switching — a cost that is not real.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.planning.rules import ProgramRules
from app.planning.types import StatedCourse
from app.sequence.plan import ASSUMED_CREDIT_CAP, DEFAULT_HORIZON, build_sequence
from app.sequence.terms import Term


@dataclass(frozen=True)
class DelayCost:
    """One course's next-term price, in terms."""

    code: str
    title: str
    requirement: str | None
    # The finish term when this course is taken next term, i.e. the baseline plan's.
    baseline_finish: Term
    # The finish term when it is held out of the next term. None when holding it out makes
    # the whole plan infeasible — which is a stronger statement than any number of terms.
    deferred_finish: Term | None
    # Whether holding it out breaks the plan against the student's deadline entirely.
    breaks_plan: bool

    @property
    def terms_lost(self) -> int | None:
        """How many terms later the deferred plan finishes. Zero when it does not.

        `Term.distance_to` counts both ends — it returns 1 for a term and itself — so the
        subtraction is the difference this needs, not an off-by-one waiting to happen. A
        student told a course costs "one term" when it costs none would stop believing the
        number, and that number is the whole reason this module exists.
        """
        if self.deferred_finish is None:
            return None
        return self.baseline_finish.distance_to(self.deferred_finish) - 1

    @property
    def delays(self) -> bool:
        return self.breaks_plan or bool(self.terms_lost)

    def describe(self) -> str:
        """The sentence a student reads. Written here rather than in the view so the same
        words appear in the card, the chat answer and the advisor handoff."""
        if self.breaks_plan:
            return (
                f"{self.code} has to be next term. Holding it back leaves no sequence that "
                "still meets your deadline."
            )
        lost = self.terms_lost or 0
        if lost == 0:
            return (
                f"{self.code} can wait. Taking it later does not move your finish term, so "
                "this one is yours to schedule."
            )
        return (
            f"{self.code} costs {lost} term{'s' if lost != 1 else ''} if it waits: you would "
            f"finish {self.deferred_finish} instead of {self.baseline_finish}."
        )


def delay_costs(
    program: ProgramRules,
    stated: list[StatedCourse],
    *,
    start_term: Term,
    deadline: Term | None = None,
    max_credits_per_term: int = ASSUMED_CREDIT_CAP,
    horizon: int = DEFAULT_HORIZON,
) -> tuple[DelayCost, ...]:
    """Price every course the baseline plan puts in `start_term`.

    Only that term is priced, and only because that is the decision in front of the student.
    Pricing the whole plan would be N re-solves for a question nobody asked yet, and the
    answer for a course three terms out changes every time anything before it moves.

    Returns empty when there is no feasible baseline: a delay cost is a comparison against a
    plan, and there is nothing to compare against. The infeasibility itself is already
    reported by `build_sequence`, and saying "this course costs nothing" because no plan
    exists would be the worst available answer.
    """
    baseline = build_sequence(
        program,
        stated,
        start_term=start_term,
        deadline=deadline,
        max_credits_per_term=max_credits_per_term,
        horizon=horizon,
    )
    if not baseline.feasible or baseline.finish_term is None:
        return ()

    next_term = [p for p in baseline.placements if p.term == start_term]
    costs: list[DelayCost] = []
    for placement in next_term:
        # A credit placeholder has no identity — no code to defer, no prerequisites checked
        # for it, and nothing the student could go and register for. Pricing it would put a
        # number against a course nobody has chosen yet.
        if placement.course.code.endswith("(credits, course not chosen)"):
            continue

        deferred = build_sequence(
            program,
            stated,
            start_term=start_term,
            deadline=deadline,
            max_credits_per_term=max_credits_per_term,
            horizon=horizon,
            defer=placement.course.code,
        )
        costs.append(
            DelayCost(
                code=placement.course.code,
                title=placement.course.title,
                requirement=placement.course.requirement,
                baseline_finish=baseline.finish_term,
                deferred_finish=deferred.finish_term if deferred.feasible else None,
                breaks_plan=not deferred.feasible,
            )
        )

    # Most expensive first: the student is deciding what to drop, so the courses that cannot
    # be dropped belong at the top. Ties break on code so two runs on one record agree.
    return tuple(
        sorted(
            costs,
            key=lambda c: (
                0 if c.breaks_plan else 1,
                -(c.terms_lost or 0),
                c.code,
            ),
        )
    )
