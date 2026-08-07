"""The sequencing search: backtracking over (course -> term) assignments.

Pure functions over frozen dataclasses. No database, no model — the same boundary as
`planning.rules` and for the same reason: a schedule a student plans a year around has to be
reproducible, and every branch here has to be reachable from a literal in a test.

**Why backtracking and not a solver library.** The problem is 3-8 courses over 3-8 terms with
four constraint families. A hand-written search over that is a hundred lines, terminates in
microseconds, and — the part that matters — can explain itself. The explanation is most of
the product here: an off-the-shelf solver returns UNSAT, and UNSAT is not something you can
tell a student. Relaxation testing (see `explain_infeasibility`) is only cheap because the
search is cheap.

**Why courses are assigned in topological order.** Prerequisites are checked against terms
already assigned, which is only sound if a course's prerequisites are placed before it.
Assigning in dependency order makes the check local and makes the first solution found the
earliest-finishing one, since each course takes the earliest term that still works.
"""

from __future__ import annotations

from app.sequence.types import (
    CONSTRAINT_LABEL,
    Constraint,
    CourseNeed,
    Infeasibility,
    Placement,
)
from app.sequence.terms import Term

ALL_CONSTRAINTS = frozenset(Constraint)


class DependencyCycleError(ValueError):
    """The needed courses require each other. A data defect, not an infeasible plan."""


def topological_order(needs: tuple[CourseNeed, ...]) -> list[CourseNeed]:
    """Needs sorted so every course follows the needed courses it depends on.

    Only edges *within the need set* matter. A prerequisite the student already holds is
    not a scheduling constraint at all, and one outside the catalog cannot be scheduled —
    both are handled by the caller before we get here.
    """
    by_code = {need.code: need for need in needs}
    # Deterministic input order, so two runs on the same data give the same schedule.
    remaining = sorted(needs, key=lambda n: n.code)
    placed: list[CourseNeed] = []
    placed_codes: set[str] = set()

    while remaining:
        ready = [
            need
            for need in remaining
            if all(
                code in placed_codes or code not in by_code
                for group in need.prerequisite_groups
                for code in group
            )
        ]
        if not ready:
            raise DependencyCycleError(
                "These courses list each other as prerequisites: "
                + ", ".join(sorted(n.code for n in remaining))
            )
        for need in ready:
            placed.append(need)
            placed_codes.add(need.code)
        remaining = [n for n in remaining if n.code not in placed_codes]

    return placed


def _group_satisfied(
    need: CourseNeed,
    group: tuple[str, ...],
    term: Term,
    assigned: dict[str, Term],
    already_held: frozenset[str],
    in_catalog: frozenset[str],
) -> bool:
    for code in group:
        if code in already_held:
            return True
        when = assigned.get(code)
        if when is not None:
            if when < term:
                return True
            if when == term and code in need.concurrent_ok:
                return True
            continue
        if code not in in_catalog:
            # A prerequisite this catalog has never heard of cannot be scheduled or
            # checked. Treating it as blocking would make the course permanently
            # unschedulable on the strength of missing data; the caller records it as an
            # assumption instead, so the gap is disclosed rather than decided.
            return True
    return False


def _prerequisites_ok(
    need: CourseNeed,
    term: Term,
    assigned: dict[str, Term],
    already_held: frozenset[str],
    in_catalog: frozenset[str],
) -> bool:
    return all(
        _group_satisfied(need, group, term, assigned, already_held, in_catalog)
        for group in need.prerequisite_groups
    )


def solve(
    needs: tuple[CourseNeed, ...],
    terms: tuple[Term, ...],
    *,
    already_held: frozenset[str] = frozenset(),
    max_credits_per_term: int = 9,
    deadline: Term | None = None,
    enforce: frozenset[Constraint] = ALL_CONSTRAINTS,
) -> tuple[Placement, ...] | None:
    """The earliest-finishing assignment of needs to terms, or None if there is none.

    `enforce` exists for relaxation testing: dropping one constraint and re-solving is how
    infeasibility gets attributed to a cause rather than reported as a dead end.
    """
    if not needs:
        return ()

    ordered = topological_order(needs)
    in_catalog = frozenset(need.code for need in needs) | already_held
    allowed_terms = [
        term
        for term in terms
        if Constraint.deadline not in enforce or deadline is None or term <= deadline
    ]
    if not allowed_terms:
        return None

    assigned: dict[str, Term] = {}
    load: dict[Term, int] = {term: 0 for term in allowed_terms}
    result: list[Placement] = []

    def place(index: int) -> bool:
        if index == len(ordered):
            return True
        need = ordered[index]
        for term in allowed_terms:
            if Constraint.offering in enforce and not need.offering.allows(term.season):
                continue
            if (
                Constraint.credit_cap in enforce
                and load[term] + need.credits > max_credits_per_term
            ):
                continue
            if Constraint.prerequisites in enforce and not _prerequisites_ok(
                need, term, assigned, already_held, in_catalog
            ):
                continue

            assigned[need.code] = term
            load[term] += need.credits
            result.append(Placement(course=need, term=term))
            if place(index + 1):
                return True
            result.pop()
            load[term] -= need.credits
            del assigned[need.code]
        return False

    if not place(0):
        return None
    return tuple(sorted(result, key=lambda p: (p.term, p.course.code)))


# Ordered by how reasonable it is to ask the student to give this one up. Taking an extra
# term is a real cost but a normal one; being told to ignore prerequisite order is not
# advice, so that possibility is reported last and never as a suggestion.
_RELAXATION_ORDER = (
    Constraint.deadline,
    Constraint.credit_cap,
    Constraint.offering,
    Constraint.prerequisites,
)

_REMEDY = {
    Constraint.deadline: (
        "Allow one or more extra terms. This is the usual answer, and the cheapest."
    ),
    Constraint.credit_cap: (
        "Raise the credits you are willing to carry in a term — check with your advisor "
        "what the limit is for your program and whether an overload needs approval."
    ),
    Constraint.offering: (
        "Something has to run in a term the bulletin does not list it in. Ask the "
        "department whether the schedule has changed; UAX only knows the published text."
    ),
    Constraint.prerequisites: (
        "A prerequisite would have to be waived or taken alongside. Only the program can "
        "decide that, and it is a conversation, not a setting."
    ),
}


def explain_infeasibility(
    needs: tuple[CourseNeed, ...],
    terms: tuple[Term, ...],
    *,
    already_held: frozenset[str] = frozenset(),
    max_credits_per_term: int = 9,
    deadline: Term | None = None,
) -> Infeasibility:
    """Find which constraints are binding by removing them one at a time.

    Relaxation rather than inference. A hand-written diagnosis ("it is probably the
    capstone") is a guess dressed as an explanation, and it will be wrong in exactly the
    cases where the schedule is complicated enough for the student to need help. Removing a
    constraint and re-solving *proves* whether it was the obstacle.

    Cheap because the search is: at this size, four extra solves cost nothing.
    """
    binding: list[Constraint] = []
    for constraint in _RELAXATION_ORDER:
        relaxed = ALL_CONSTRAINTS - {constraint}
        if (
            solve(
                needs,
                terms,
                already_held=already_held,
                max_credits_per_term=max_credits_per_term,
                deadline=deadline,
                enforce=relaxed,
            )
            is not None
        ):
            binding.append(constraint)

    if not binding:
        return Infeasibility(
            binding=(),
            explanation=(
                "No sequence fits, and relaxing any single one of the four constraints on "
                "its own does not produce one either — at least two are working against "
                "each other. This is the point to take the whole plan to an advisor rather "
                "than adjust one dial."
            ),
            remedies=(),
        )

    labels = [CONSTRAINT_LABEL[c] for c in binding]
    if len(labels) == 1:
        explanation = (
            f"No sequence fits. The single thing standing in the way is {labels[0]} — "
            "relaxing it, and nothing else, produces a workable order."
        )
    else:
        explanation = (
            "No sequence fits. Any one of these would be enough to unblock it on its own: "
            + "; ".join(labels)
            + "."
        )

    return Infeasibility(
        binding=tuple(binding),
        explanation=explanation,
        remedies=tuple(_REMEDY[c] for c in binding),
    )
