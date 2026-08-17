"""Half credits, end to end.

62 of the ingested courses are worth 1.5 credits, and three encoded degrees — MSEM, TCTM,
TCHS — are built out of them: a 16.5-credit core plus a 1.5-credit internship or capstone.
MSEM's internship is a single 1.5-credit *required* course, so for those students a
fractional total is not an edge case, it is the first thing entering their record produces.

Everything below guards one of the two ways that fact used to break:

1.  `PlanOut` declared its credit fields `int`. Pydantic will not coerce `1.5` into an int,
    so `/plan` and `/plan/what-if` — what the planner, the rail and the chat card all read —
    returned a 500 the moment such a course was stated.
2.  A float renders as `15.0`, so findings read "Electives: 15.0 credit(s) short" next to
    the bulletin's own quoted "Select 15 credits". That one shipped and was visible on every
    `credits` requirement in all 22 encoded degrees.
"""

import pytest

from app.planning.format import fmt_credits
from app.planning.rules import (
    CourseRule,
    ProgramRules,
    RequirementRuleSpec,
    evaluate_plan,
    evaluate_requirement,
)
from app.planning.types import CourseState, StatedCourse
from app.routers.profile import PlanOut, _plan_response
from app.schemas import RequirementProgress

META = {
    "program_name": "Event Management",
    "program_source_url": None,
    "rules_verified_on": None,
    "courses_stated": 1,
    "profile_last_updated": None,
    "profile_age_days": None,
    "profile_is_stale": False,
}


def half_credit_program() -> ProgramRules:
    """MSEM in miniature: a 1.5-credit required internship and a fractional core."""
    return ProgramRules(
        name="Event Management",
        total_credits=30,
        requirements=(
            RequirementRuleSpec(
                name="Internship",
                rule="all_of",
                min_credits=1.5,
                course_codes=("MSEM1-GC 1100",),
            ),
            RequirementRuleSpec(
                name="Electives",
                rule="credits",
                min_credits=15.0,
                course_codes=("MSEM1-GC 2040", "MSEM1-GC 2000"),
            ),
        ),
        courses={
            "MSEM1-GC 1100": CourseRule(code="MSEM1-GC 1100", title="Internship", credits=1.5),
            "MSEM1-GC 2040": CourseRule(code="MSEM1-GC 2040", title="Elective A", credits=1.5),
            "MSEM1-GC 2000": CourseRule(code="MSEM1-GC 2000", title="Elective B", credits=3.0),
        },
    )


# --------------------------------------------------------------------------------------
# The 500
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state,field",
    [
        (CourseState.completed, "credits_completed"),
        (CourseState.in_progress, "credits_in_progress"),
        (CourseState.planned, "credits_planned"),
    ],
)
def test_plan_response_survives_a_fractional_credit_course(state, field):
    result = evaluate_plan(
        half_credit_program(),
        [StatedCourse(code="MSEM1-GC 1100", state=state)],
        include_planned=True,
    )
    assert getattr(result, field) == 1.5

    out = _plan_response(result, META)
    assert getattr(out, field) == 1.5


def test_plan_out_does_not_round_a_half_credit_away():
    """The failure mode if someone ever "fixes" this by coercing: a silent half credit."""
    out = PlanOut(
        program_name="x",
        program_source_url=None,
        rules_verified_on=None,
        credits_completed=16.5,
        credits_in_progress=0.0,
        credits_planned=1.5,
        credits_required=30.0,
        courses_stated=1,
        profile_last_updated=None,
        profile_age_days=None,
        profile_is_stale=False,
        counts={},
        findings=[],
    )
    assert out.credits_completed == 16.5
    assert out.credits_planned == 1.5


def test_requirement_progress_accepts_fractional_credits():
    """Six encoded requirements are 16.5 or 1.5; readiness reads `min_credits` directly."""
    progress = RequirementProgress(
        name="Core Curriculum",
        kind="core",
        required_credits=16.5,
        earned_credits=1.5,
        applied_credits=1.5,
        remaining_credits=15.0,
        unapplied_credits=0.0,
        satisfied=False,
    )
    assert progress.required_credits == 16.5
    assert progress.remaining_credits == 15.0


# --------------------------------------------------------------------------------------
# The prose
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (15.0, "15"),
        (1.5, "1.5"),
        (16.5, "16.5"),
        (0.0, "0"),
        (0.25, "0.25"),  # not rounded away — see fmt_credits' docstring
    ],
)
def test_fmt_credits(value, expected):
    assert fmt_credits(value) == expected


def test_credits_requirement_prose_carries_no_trailing_zero():
    program = half_credit_program()
    spec = program.requirements[1]  # Electives, 15.0

    finding = evaluate_requirement(
        spec, {}, program.courses, counting_states=frozenset({CourseState.completed})
    )
    assert "15.0" not in finding.summary
    assert "15.0" not in finding.detail
    assert "15 credit(s) short" in finding.summary
    assert finding.detail.startswith("0 of 15 credits")


def test_a_half_credit_shortfall_keeps_its_half():
    """The other direction: `.5` must survive the formatter, not be tidied into an int."""
    program = half_credit_program()
    spec = program.requirements[1]
    held = {
        "MSEM1-GC 2000": StatedCourse(code="MSEM1-GC 2000", state=CourseState.completed),
        "MSEM1-GC 2040": StatedCourse(code="MSEM1-GC 2040", state=CourseState.completed),
    }

    finding = evaluate_requirement(
        spec, held, program.courses, counting_states=frozenset({CourseState.completed})
    )
    # 15 required, 4.5 held -> 10.5 short.
    assert "10.5 credit(s) short" in finding.summary
    assert "4.5 of 15 credits" in finding.detail
