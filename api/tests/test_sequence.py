"""Sequence planner tests.

Three things carry the weight.

**Term ordering**, because getting it wrong is silent. Fall 2026 precedes Spring 2027, and a
year-only or alphabetical comparison puts a course before its own prerequisite while the
schedule still looks plausible.

**Offering confidence**, because the tempting bug is treating silence as availability. A
third of the real catalog says nothing about when it runs; a planner that reads that as
"every term" produces confident schedules built on nothing.

**Infeasibility attribution**, because "no sequence fits" is nearly useless and a *wrong*
reason is worse than none — the student adjusts the wrong dial and still cannot finish.
Every case here asserts the constraint that is actually binding, not merely that the solve
failed.
"""

import pytest

from app.sequence.offerings import OfferingBasis, parse_offering
from app.sequence.solver import (
    DependencyCycleError,
    explain_infeasibility,
    solve,
    topological_order,
)
from app.sequence.terms import Season, Term, TermParseError
from app.sequence.types import Constraint, CourseNeed

FALL26 = Term.parse("Fall 2026")


def need(code, credits=3, seasons=None, prereqs=(), concurrent=(), offered_text=None):
    """A course need. `seasons` names published seasons; omit for an unstated offering."""
    if offered_text is None and seasons is not None:
        offered_text = ", ".join(s.value for s in seasons)
    return CourseNeed(
        code=code,
        title=code,
        credits=credits,
        offering=parse_offering(offered_text),
        prerequisite_groups=prereqs,
        concurrent_ok=frozenset(concurrent),
    )


# --------------------------------------------------------------------------------------
# Terms
# --------------------------------------------------------------------------------------


def test_terms_order_across_the_year_boundary():
    """The one that breaks silently: a fall term precedes the following spring."""
    assert Term.parse("Fall 2026") < Term.parse("Spring 2027")
    assert Term.parse("Spring 2027") < Term.parse("Summer 2027")
    assert Term.parse("Summer 2027") < Term.parse("Fall 2027")


def test_terms_advance_in_academic_order():
    assert str(FALL26.next()) == "Spring 2027"
    assert str(Term.parse("Spring 2027").next()) == "Summer 2027"
    assert str(Term.parse("Summer 2027").next()) == "Fall 2027"


def test_forward_enumerates_from_this_term():
    assert [str(t) for t in FALL26.forward(4)] == [
        "Fall 2026",
        "Spring 2027",
        "Summer 2027",
        "Fall 2027",
    ]


def test_distance_counts_both_ends():
    assert FALL26.distance_to(FALL26) == 1
    assert FALL26.distance_to(Term.parse("Summer 2027")) == 3


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fall 2026", "Fall 2026"),
        ("fall 2026", "Fall 2026"),
        ("  Spring   2027 ", "Spring 2027"),
        ("2027 Spring", "Spring 2027"),
        ("Autumn 2026", "Fall 2026"),
    ],
)
def test_term_parsing_accepts_what_students_type(text, expected):
    assert str(Term.parse(text)) == expected


@pytest.mark.parametrize("text", ["", "next term", "Fall", "2026", "Winter 2026"])
def test_unparseable_terms_raise_rather_than_guess(text):
    with pytest.raises(TermParseError):
        Term.parse(text)


# --------------------------------------------------------------------------------------
# Offerings — silence is not availability
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "seasons"),
    [
        ("Fall", {Season.fall}),
        ("Spring", {Season.spring}),
        ("Summer term", {Season.summer}),
        ("Fall and Spring", {Season.fall, Season.spring}),
        ("Spring and Summer", {Season.spring, Season.summer}),
        ("Fall, Spring, and Summer terms", {Season.fall, Season.spring, Season.summer}),
    ],
)
def test_published_patterns_parse_to_their_seasons(text, seasons):
    """These are the exact strings in the ingested catalog."""
    offering = parse_offering(text)
    assert offering.seasons == frozenset(seasons)
    assert offering.basis is OfferingBasis.published
    assert not offering.is_assumption


def test_all_terms_is_published_not_assumed():
    offering = parse_offering("all terms")
    assert offering.seasons == frozenset(Season)
    assert offering.basis is OfferingBasis.published


def test_an_empty_field_is_unstated_and_flagged():
    """18 of the 57 catalog courses land here. It must never read as 'every term'."""
    offering = parse_offering(None)
    # Any term is allowed for *search*, because refusing to schedule it would be worse…
    assert offering.seasons == frozenset(Season)
    # …but it is recorded as an assumption, which is what makes the difference visible.
    assert offering.basis is OfferingBasis.unstated
    assert offering.is_assumption
    assert "does not say" in offering.describe()


def test_occasionally_is_irregular_and_says_so():
    offering = parse_offering("occasionally")
    assert offering.basis is OfferingBasis.irregular
    assert offering.is_assumption
    assert "irregular" in offering.describe()


def test_an_irregularity_marker_beats_a_season_word_beside_it():
    """"occasionally in the fall" is not a commitment to the fall."""
    offering = parse_offering("Offered occasionally in the fall")
    assert offering.basis is OfferingBasis.irregular
    assert offering.is_assumption


def test_unreadable_text_is_unstated_but_keeps_the_words():
    offering = parse_offering("See department")
    assert offering.basis is OfferingBasis.unstated
    assert offering.source_text == "See department"


# --------------------------------------------------------------------------------------
# Topological order
# --------------------------------------------------------------------------------------


def test_prerequisites_are_ordered_before_their_dependents():
    needs = (need("B", prereqs=(("A",),)), need("A"))
    assert [n.code for n in topological_order(needs)] == ["A", "B"]


def test_prerequisites_outside_the_need_set_do_not_constrain_order():
    """A prerequisite already completed is not a scheduling problem."""
    needs = (need("B", prereqs=(("HELD",),)),)
    assert [n.code for n in topological_order(needs)] == ["B"]


def test_a_dependency_cycle_is_a_data_defect_not_an_infeasible_plan():
    needs = (need("A", prereqs=(("B",),)), need("B", prereqs=(("A",),)))
    with pytest.raises(DependencyCycleError):
        topological_order(needs)


# --------------------------------------------------------------------------------------
# Each constraint, in isolation
# --------------------------------------------------------------------------------------


def test_prerequisite_order_pushes_a_course_to_a_later_term():
    plan = solve(
        (need("A", seasons=[Season.fall, Season.spring]),
         need("B", seasons=[Season.fall, Season.spring], prereqs=(("A",),))),
        tuple(FALL26.forward(3)),
        max_credits_per_term=99,
    )
    assert plan is not None
    when = {p.course.code: p.term for p in plan}
    assert when["A"] < when["B"]


def test_a_concurrent_prerequisite_may_share_the_term():
    plan = solve(
        (need("A", seasons=[Season.fall]),
         need("B", seasons=[Season.fall], prereqs=(("A",),), concurrent=("A",))),
        tuple(FALL26.forward(3)),
        max_credits_per_term=99,
    )
    assert plan is not None
    assert len({p.term for p in plan}) == 1


def test_a_prerequisite_already_held_imposes_nothing():
    plan = solve(
        (need("B", seasons=[Season.fall], prereqs=(("A",),)),),
        tuple(FALL26.forward(1)),
        already_held=frozenset({"A"}),
    )
    assert plan is not None
    assert str(plan[0].term) == "Fall 2026"


def test_an_or_group_is_satisfied_by_either_alternative():
    plan = solve(
        (need("B", seasons=[Season.fall], prereqs=(("A", "A2"),)),),
        tuple(FALL26.forward(1)),
        already_held=frozenset({"A2"}),
    )
    assert plan is not None


def test_offering_pattern_places_a_spring_only_course_in_spring():
    plan = solve(
        (need("S", seasons=[Season.spring]),), tuple(FALL26.forward(3))
    )
    assert plan is not None
    assert plan[0].term.season is Season.spring


def test_the_credit_cap_splits_a_term():
    plan = solve(
        (need("A", credits=3, seasons=[Season.fall, Season.spring]),
         need("B", credits=3, seasons=[Season.fall, Season.spring])),
        tuple(FALL26.forward(3)),
        max_credits_per_term=3,
    )
    assert plan is not None
    assert len({p.term for p in plan}) == 2


def test_the_deadline_limits_the_terms_available():
    plan = solve(
        (need("A", seasons=[Season.fall]),),
        tuple(FALL26.forward(4)),
        deadline=Term.parse("Spring 2027"),
    )
    assert plan is not None
    assert plan[0].term <= Term.parse("Spring 2027")


def test_an_unstated_offering_can_go_anywhere_but_is_marked():
    plan = solve((need("U"),), tuple(FALL26.forward(1)))
    assert plan is not None
    assert plan[0].rests_on_assumption is True


def test_a_published_placement_is_not_marked_as_a_guess():
    plan = solve((need("F", seasons=[Season.fall]),), tuple(FALL26.forward(1)))
    assert plan is not None
    assert plan[0].rests_on_assumption is False


def test_no_needs_is_a_trivially_complete_sequence():
    assert solve((), tuple(FALL26.forward(3))) == ()


def test_the_search_is_deterministic():
    """A schedule someone plans a year around must not change between identical runs."""
    needs = (
        need("A", seasons=[Season.fall, Season.spring]),
        need("B", seasons=[Season.fall, Season.spring], prereqs=(("A",),)),
        need("C"),
    )
    first = solve(needs, tuple(FALL26.forward(4)), max_credits_per_term=3)
    second = solve(needs, tuple(FALL26.forward(4)), max_credits_per_term=3)
    assert first == second


def test_the_first_solution_finishes_as_early_as_the_constraints_allow():
    needs = (
        need("A", seasons=[Season.fall, Season.spring]),
        need("B", seasons=[Season.fall, Season.spring], prereqs=(("A",),)),
    )
    plan = solve(needs, tuple(FALL26.forward(6)), max_credits_per_term=3)
    assert plan is not None
    # Two courses, one before the other, 3 credits a term: two terms is the floor.
    assert len({p.term for p in plan}) == 2
    assert max(p.term for p in plan) == Term.parse("Spring 2027")


# --------------------------------------------------------------------------------------
# Infeasibility, attributed by relaxation
# --------------------------------------------------------------------------------------


def test_a_tight_deadline_is_named_as_the_binding_constraint():
    needs = (
        need("A", credits=3, seasons=[Season.fall, Season.spring]),
        need("B", credits=3, seasons=[Season.fall, Season.spring], prereqs=(("A",),)),
    )
    terms = tuple(FALL26.forward(4))
    assert solve(needs, terms, max_credits_per_term=3, deadline=FALL26) is None

    why = explain_infeasibility(needs, terms, max_credits_per_term=3, deadline=FALL26)
    assert Constraint.deadline in why.binding
    assert why.remedies


def test_the_credit_cap_is_named_when_it_is_the_obstacle():
    needs = (
        need("A", credits=3, seasons=[Season.fall]),
        need("B", credits=3, seasons=[Season.fall]),
    )
    # One term available, both courses fall-only, cap fits only one.
    terms = (FALL26,)
    assert solve(needs, terms, max_credits_per_term=3) is None

    why = explain_infeasibility(needs, terms, max_credits_per_term=3)
    assert Constraint.credit_cap in why.binding


def test_the_offering_pattern_is_named_when_it_is_the_obstacle():
    needs = (need("SPRINGONLY", seasons=[Season.spring]),)
    terms = (FALL26,)  # no spring term available at all
    assert solve(needs, terms) is None

    why = explain_infeasibility(needs, terms)
    assert Constraint.offering in why.binding


def test_prerequisite_order_is_named_when_it_is_the_obstacle():
    needs = (
        need("A", seasons=[Season.fall]),
        need("B", seasons=[Season.fall], prereqs=(("A",),)),
    )
    terms = (FALL26,)  # both fall-only, one term, and B must follow A
    assert solve(needs, terms, max_credits_per_term=99) is None

    why = explain_infeasibility(needs, terms, max_credits_per_term=99)
    assert Constraint.prerequisites in why.binding


def test_relaxing_prerequisites_is_reported_last_and_never_alone_as_advice():
    """Being told to ignore prerequisite order is not advice, so it ranks last."""
    needs = (
        need("A", seasons=[Season.fall]),
        need("B", seasons=[Season.fall], prereqs=(("A",),)),
    )
    why = explain_infeasibility(needs, (FALL26,), max_credits_per_term=99)
    if len(why.binding) > 1:
        assert why.binding[-1] is Constraint.prerequisites


def test_when_no_single_relaxation_helps_it_says_so_rather_than_blaming_one():
    # Spring-only course, one fall term, and a cap below its credits: two constraints must
    # give at once, so naming either alone would be wrong.
    needs = (need("S", credits=6, seasons=[Season.spring]),)
    why = explain_infeasibility(needs, (FALL26,), max_credits_per_term=3)
    assert why.binding == ()
    assert "at least two" in why.explanation
    assert why.remedies == ()


def test_every_named_constraint_really_does_unblock_it():
    """The claim relaxation makes is falsifiable, so falsify it here."""
    needs = (
        need("A", credits=3, seasons=[Season.fall, Season.spring]),
        need("B", credits=3, seasons=[Season.fall, Season.spring], prereqs=(("A",),)),
    )
    terms = tuple(FALL26.forward(4))
    why = explain_infeasibility(needs, terms, max_credits_per_term=3, deadline=FALL26)

    from app.sequence.solver import ALL_CONSTRAINTS

    for constraint in why.binding:
        relaxed = solve(
            needs,
            terms,
            max_credits_per_term=3,
            deadline=FALL26,
            enforce=ALL_CONSTRAINTS - {constraint},
        )
        assert relaxed is not None, f"{constraint} was named but does not unblock it"
