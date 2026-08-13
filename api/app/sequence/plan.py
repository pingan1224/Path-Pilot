"""Turning "what is left" into a sequence, including the parts that cannot be sequenced.

This is where the three requirement kinds stop being interchangeable.

`all_of` is easy: the missing courses are named, and they go into the search.

`one_track` is a choice, not a constraint. The program says pick one concentration and
finish it, so the honest procedure is to sequence each candidate track separately and
compare — and to say which ones could not be sequenced at all, because "Business Analytics
does not fit before your deadline but Risk Analytics does" is a decision the student can
make and one they cannot make from a single recommended answer.

`credits` cannot be turned into courses at all. The MASY elective scope is "any course in
this list, or a foundational course from another concentration, or a graduate course
elsewhere in the division" — an open set this tool cannot enumerate, let alone check
prerequisites for. Dropping it would make the finish term optimistic by a whole course, so
it enters the search as a credit placeholder with no identity, and the answer says that is
what it is.
"""

from __future__ import annotations

from app.planning.rules import ProgramRules, RequirementRuleSpec, courses_applied
from app.planning.types import CourseState, StatedCourse
from app.sequence.offerings import OfferingBasis, parse_offering
from app.sequence.solver import (
    DependencyCycleError,
    explain_infeasibility,
    solve,
)
from app.sequence.terms import Term
from app.sequence.types import (
    Assumption,
    CourseNeed,
    Infeasibility,
    SequencePlan,
)

# How far ahead to look when no deadline is given. Eight terms is a little under three
# years; a plan longer than that is not a scheduling answer, it is a conversation.
DEFAULT_HORIZON = 8

# The per-term credit ceiling used when the student does not set one.
#
# **Not a published rule for this program.** The ingested corpus contains credit caps for
# Stern's Full-time MBA (15) and Langone (9) programs and nothing for SPS. Citing either at
# an SPS student would be quoting another school's policy — the same mistake the home-school
# retrieval boost exists to prevent, and worse here, because it would be buried inside a
# solver constraint instead of visible as a citation. So this is the student's number, it
# defaults to something conservative, and every plan states that it was assumed.
ASSUMED_CREDIT_CAP = 9


def _placeholder_code(requirement: str) -> str:
    return f"{requirement} (credits, course not chosen)"


def _needs_for_requirement(
    spec: RequirementRuleSpec,
    program: ProgramRules,
    held: frozenset[str],
    *,
    track_name: str | None = None,
    spent: frozenset[str] = frozenset(),
) -> tuple[list[CourseNeed], list[str], list[Assumption]]:
    """The courses this requirement still needs, plus anything unplaceable or assumed."""
    needs: list[CourseNeed] = []
    unplaceable: list[str] = []
    assumptions: list[Assumption] = []

    if spec.rule == "one_track":
        track = next((t for t in spec.tracks if t.name == track_name), None)
        codes = list(track.required_codes) + list(track.course_codes) if track else []
        if track and track.is_pool:
            # A pool track offers more courses than it needs, so scheduling all of them
            # would invent coursework the student does not owe and push the finish date out
            # by the difference. Which ones they pick is theirs to decide; what the sequence
            # can honestly do is place enough of them, taking the ones already held first
            # and then filling in listed order so two runs on the same record agree.
            # Named courses are never optional, so they stay whole; only the pool is
            # trimmed to what is still short of its own count.
            pool = list(track.course_codes)
            outstanding = track.pool_count - sum(1 for c in pool if c in held)
            unheld_pool = [c for c in pool if c not in held]
            codes = (
                list(track.required_codes)
                + [c for c in pool if c in held]
                + unheld_pool[: max(outstanding, 0)]
            )
    elif spec.rule == "all_of":
        codes = list(spec.course_codes)
    else:
        codes = []

    for code in codes:
        if code in held:
            continue
        rule = program.courses.get(code)
        if rule is None:
            # Required by the program, absent from the loaded catalog. Cannot be scheduled
            # and must not be silently dropped from the count.
            unplaceable.append(code)
            continue
        offering = parse_offering(rule.typically_offered)
        if offering.basis is not OfferingBasis.published:
            assumptions.append(
                Assumption(
                    subject=code,
                    statement=f"{code}: {offering.describe()}.",
                    check=f"Confirm when {code} runs in Albert or with the department.",
                )
            )
        concurrent = frozenset(rule.concurrent)
        needs.append(
            CourseNeed(
                code=code,
                title=rule.title,
                credits=rule.credits,
                offering=offering,
                prerequisite_groups=rule.prerequisite_groups,
                concurrent_ok=concurrent,
                requirement=spec.name,
            )
        )

    if spec.rule == "credits":
        # `spent` is what the requirements above have already used. Global Affairs draws
        # its electives from the same courses its concentrations are made of, so counting
        # them here as well would drop nine credits out of the sequence and hand the
        # student a finish date a term too early.
        earned = sum(
            program.courses[c].credits
            for c in spec.course_codes
            if c in held and c not in spent and c in program.courses
        )
        short = max(spec.min_credits - earned, 0)
        if short:
            needs.append(
                CourseNeed(
                    code=_placeholder_code(spec.name),
                    title=f"{short} credit(s) toward {spec.name}",
                    credits=short,
                    # No identity means no offering information; the placeholder can sit in
                    # any term, and that is a genuine unknown rather than flexibility.
                    offering=parse_offering(None),
                    requirement=spec.name,
                )
            )
            assumptions.append(
                Assumption(
                    subject=spec.name,
                    statement=(
                        f"{short} credit(s) of {spec.name} are held as a placeholder: the "
                        "eligible set is open-ended, so no specific course was scheduled "
                        "and no prerequisites were checked for it."
                    ),
                    check=(
                        "Pick the course with your advisor, then re-run this with it in "
                        "your record."
                    ),
                )
            )

    return needs, unplaceable, assumptions


def _candidate_tracks(program: ProgramRules, held: frozenset[str]) -> list[str | None]:
    """Which concentrations are worth sequencing.

    A track already finished needs no sequencing. A track the student has started is not
    treated as locked in — they are allowed to change concentration, and a planner that
    quietly assumed otherwise would hide the option that fixes an impossible deadline.
    """
    for spec in program.requirements:
        if spec.rule != "one_track" or not spec.tracks:
            continue
        # `is_complete`, not "holds every listed course": a pool track is finished at its
        # own count, and the stricter test would call a finished concentration unfinished
        # and re-sequence all eight of Global Affairs' options against a student who has
        # already chosen one.
        finished = [t for t in spec.tracks if t.is_complete(held)]
        if finished:
            return [finished[0].name]
        return [t.name for t in spec.tracks]
    return [None]


def build_sequence(
    program: ProgramRules,
    stated: list[StatedCourse],
    *,
    start_term: Term,
    deadline: Term | None = None,
    max_credits_per_term: int = ASSUMED_CREDIT_CAP,
    horizon: int = DEFAULT_HORIZON,
    credit_cap_was_assumed: bool = True,
) -> SequencePlan:
    # In-progress coursework counts as held: it finishes before any term this plan touches.
    held = frozenset(
        c.code
        for c in stated
        if c.state in (CourseState.completed, CourseState.in_progress)
    )

    terms = tuple(start_term.forward(horizon))
    if deadline is not None and deadline > terms[-1]:
        terms = tuple(start_term.forward(start_term.distance_to(deadline)))

    base_assumptions: list[Assumption] = []
    if credit_cap_was_assumed:
        base_assumptions.append(
            Assumption(
                subject="Credits per term",
                statement=(
                    f"{max_credits_per_term} credits per term was assumed, not read from a "
                    "rule. The bulletin pages Path Pilot has ingested state per-term credit limits "
                    "for Stern's MBA programs only, and those do not apply to this program."
                ),
                check=(
                    "Ask your advisor what the per-term maximum is for your program, then "
                    "set it here."
                ),
            )
        )

    attempts: list[tuple[str | None, SequencePlan]] = []

    for track in _candidate_tracks(program, held):
        needs: list[CourseNeed] = []
        unplaceable: list[str] = []
        assumptions = list(base_assumptions)

        spent: set[str] = set()
        for spec in program.requirements:
            spec_needs, spec_unplaceable, spec_assumptions = _needs_for_requirement(
                spec, program, held, track_name=track, spent=frozenset(spent)
            )
            needs.extend(spec_needs)
            unplaceable.extend(spec_unplaceable)
            assumptions.extend(spec_assumptions)
            spent |= courses_applied(
                spec, set(held) - spent, program.courses, track_name=track
            )

        if unplaceable:
            assumptions.append(
                Assumption(
                    subject="Courses outside the loaded catalog",
                    statement=(
                        "Required but absent from the catalog Path Pilot has loaded, so they were "
                        "left out of the sequence entirely: "
                        + ", ".join(sorted(set(unplaceable)))
                        + "."
                    ),
                    check="Check these against the bulletin with your advisor.",
                )
            )

        needs_tuple = tuple(needs)
        try:
            placements = solve(
                needs_tuple,
                terms,
                already_held=held,
                max_credits_per_term=max_credits_per_term,
                deadline=deadline,
            )
        except DependencyCycleError as exc:
            attempts.append(
                (
                    track,
                    SequencePlan(
                        feasible=False,
                        assumptions=tuple(assumptions),
                        infeasibility=Infeasibility(
                            binding=(),
                            explanation=(
                                f"The catalog data will not allow a sequence here: {exc}"
                            ),
                        ),
                        unplaceable=tuple(sorted(set(unplaceable))),
                    ),
                )
            )
            continue

        if placements is None:
            attempts.append(
                (
                    track,
                    SequencePlan(
                        feasible=False,
                        assumptions=tuple(assumptions),
                        infeasibility=explain_infeasibility(
                            needs_tuple,
                            terms,
                            already_held=held,
                            max_credits_per_term=max_credits_per_term,
                            deadline=deadline,
                        ),
                        unplaceable=tuple(sorted(set(unplaceable))),
                    ),
                )
            )
            continue

        used = tuple(sorted({p.term for p in placements}))
        attempts.append(
            (
                track,
                SequencePlan(
                    feasible=True,
                    placements=placements,
                    chosen_track=track,
                    assumptions=tuple(assumptions),
                    terms_used=used,
                    unplaceable=tuple(sorted(set(unplaceable))),
                ),
            )
        )

    feasible = [(t, p) for t, p in attempts if p.feasible]
    if not feasible:
        # Report the first attempt's diagnosis, with the others named so the student can see
        # that changing concentration was tried and did not help either.
        track, plan = attempts[0]
        rejected = tuple(
            (name or "—", other.infeasibility.explanation if other.infeasibility else "")
            for name, other in attempts[1:]
        )
        return SequencePlan(
            feasible=False,
            chosen_track=None,
            rejected_tracks=rejected,
            assumptions=plan.assumptions,
            infeasibility=plan.infeasibility,
            unplaceable=plan.unplaceable,
        )

    # Finish soonest; among equals prefer the plan resting on fewer guesses, then name
    # order so the answer is stable across runs.
    def rank(entry: tuple[str | None, SequencePlan]):
        _, plan = entry
        guesses = sum(1 for p in plan.placements if p.rests_on_assumption)
        return (plan.finish_term, guesses, entry[0] or "")

    track, best = min(feasible, key=rank)
    rejected = tuple(
        (
            name or "—",
            other.infeasibility.explanation if other.infeasibility else "",
        )
        for name, other in attempts
        if name != track and not other.feasible
    )
    return SequencePlan(
        feasible=True,
        placements=best.placements,
        chosen_track=track,
        rejected_tracks=rejected,
        assumptions=best.assumptions,
        terms_used=best.terms_used,
        unplaceable=best.unplaceable,
    )
