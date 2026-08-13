"""Rule engine tests.

Weighted towards the cases where a wrong answer costs a student something: a prerequisite
waved through, a concentration counted by credits, a course the tool cannot place quietly
ignored. Happy paths are here to stop regressions; the rest is the point.
"""

import pytest

from app.planning.rules import (
    CourseRule,
    ProgramRules,
    RequirementRuleSpec,
    TrackRule,
    check_prerequisites,
    evaluate_plan,
    evaluate_requirement,
    grade_meets,
)
from app.planning.types import CourseState, StatedCourse, Verdict


def course(code, credits=3, prereqs=(), min_grades=(), title="Course"):
    return CourseRule(
        code=code,
        title=title,
        credits=credits,
        prerequisite_groups=prereqs,
        min_grades=min_grades,
        prerequisite_text="test fixture",
        catalog_url="https://example.edu/catalog",
        verified_on="2026-08-05",
    )


def stated(*pairs):
    """stated(("A", "completed"), ("B", "planned", "A-")) -> {code: StatedCourse}"""
    out = {}
    for pair in pairs:
        code, state = pair[0], pair[1]
        grade = pair[2] if len(pair) > 2 else None
        out[code] = StatedCourse(code=code, state=CourseState(state), grade=grade)
    return out


# --------------------------------------------------------------------------------------
# Grade comparison — the tri-state that keeps unknowns out of the pass column
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "actual,minimum,expected",
    [
        ("A", "B-", True),
        ("B-", "B-", True),
        ("C+", "B-", False),
        ("F", "D", False),
        (None, "B-", None),       # student did not say
        ("P", "B-", None),        # pass/fail: not on the scale
        ("incomplete", "B-", None),
    ],
)
def test_grade_meets_is_tri_state(actual, minimum, expected):
    assert grade_meets(actual, minimum) is expected


# --------------------------------------------------------------------------------------
# Prerequisites
# --------------------------------------------------------------------------------------


def test_and_groups_are_both_required():
    target = course("T", prereqs=(("A",), ("B",)))
    findings = check_prerequisites(target, stated(("A", "completed")))
    verdicts = [f.verdict for f in findings]
    assert Verdict.satisfied in verdicts
    assert Verdict.not_satisfied in verdicts, "second AND group must not be waved through"


def test_or_group_needs_only_one():
    target = course("T", prereqs=(("A", "B"),))
    findings = check_prerequisites(target, stated(("B", "completed")))
    assert [f.verdict for f in findings] == [Verdict.satisfied]


def test_in_progress_does_not_satisfy_by_default():
    """Prerequisites are enforced at enrollment, so a course in flight is not credit yet."""
    target = course("T", prereqs=(("A",),))
    findings = check_prerequisites(target, stated(("A", "in_progress")))
    assert findings[0].verdict is Verdict.not_satisfied
    assert "enforced at the time you enroll" in findings[0].detail


def test_in_progress_counts_when_planning_a_later_term_but_stays_conditional():
    """It holds — provided they pass. And the engine must not restate an in-progress
    course as completed; misquoting the student's own record back to them costs trust in
    everything else on the page."""
    target = course("T", prereqs=(("A",),))
    findings = check_prerequisites(
        target, stated(("A", "in_progress")), allow_in_progress=True
    )
    assert findings[0].verdict is Verdict.conditional
    assert "taking A now" in findings[0].detail
    assert "completing" not in findings[0].detail


def test_concentration_underway_is_not_reported_as_not_started():
    spec = RequirementRuleSpec(
        "Concentration", "one_track", 6, tracks=(TrackRule("Risk", ("R1", "R2")),)
    )
    finding = evaluate_requirement(spec, stated(("R1", "in_progress")), {})
    assert "not started" not in finding.summary
    assert "underway" in finding.summary
    assert "R2" in finding.detail


def test_missing_grade_is_unverifiable_not_a_pass():
    """The failure this guards: a minimum-grade prerequisite silently treated as met."""
    target = course("T", prereqs=(("A",),), min_grades=(("A", "B-"),))
    findings = check_prerequisites(target, stated(("A", "completed")))  # no grade given
    assert findings[0].verdict is Verdict.unverifiable
    assert findings[0].check_in_albert is True


def test_missing_grade_is_also_not_a_failure():
    target = course("T", prereqs=(("A",),), min_grades=(("A", "B-"),))
    findings = check_prerequisites(target, stated(("A", "completed")))
    assert findings[0].verdict is not Verdict.not_satisfied


def test_grade_below_minimum_fails():
    target = course("T", prereqs=(("A",),), min_grades=(("A", "B-"),))
    findings = check_prerequisites(target, stated(("A", "completed", "C")))
    assert findings[0].verdict is Verdict.not_satisfied


def test_prerequisite_findings_carry_the_catalog_sentence():
    target = course("T", prereqs=(("A",),))
    findings = check_prerequisites(target, stated())
    assert findings[0].citations[0].quote == "test fixture"
    assert findings[0].citations[0].verified_on == "2026-08-05"


# --------------------------------------------------------------------------------------
# Requirements
# --------------------------------------------------------------------------------------


def test_all_of_requires_every_course():
    spec = RequirementRuleSpec("Core", "all_of", 6, course_codes=("A", "B"))
    finding = evaluate_requirement(spec, stated(("A", "completed")), {})
    assert finding.verdict is Verdict.not_satisfied
    assert "B" in finding.detail


def test_one_track_rejects_credits_spread_across_tracks():
    """The modelling bug this rule exists to prevent.

    Two courses from two different concentrations is the full six credits and completes
    neither. A credit-threshold model would call this satisfied.
    """
    spec = RequirementRuleSpec(
        "Concentration",
        "one_track",
        6,
        tracks=(TrackRule("Business Analytics", ("A1", "A2")), TrackRule("Risk", ("R1", "R2"))),
    )
    finding = evaluate_requirement(spec, stated(("A1", "completed"), ("R1", "completed")), {})
    assert finding.verdict is Verdict.not_satisfied
    assert "more than one option" in finding.detail


def test_one_track_satisfied_when_a_track_is_complete():
    spec = RequirementRuleSpec(
        "Concentration",
        "one_track",
        6,
        tracks=(TrackRule("Business Analytics", ("A1", "A2")), TrackRule("Risk", ("R1", "R2"))),
    )
    finding = evaluate_requirement(spec, stated(("A1", "completed"), ("A2", "completed")), {})
    assert finding.verdict is Verdict.satisfied
    assert "Business Analytics" in finding.summary


def test_one_track_partial_names_what_remains():
    spec = RequirementRuleSpec(
        "Concentration", "one_track", 6, tracks=(TrackRule("Risk", ("R1", "R2")),)
    )
    finding = evaluate_requirement(spec, stated(("R1", "completed")), {})
    assert finding.verdict is Verdict.not_satisfied
    assert "R2" in finding.detail


def test_credits_requirement_counts_listed_courses():
    catalog = {"E1": course("E1"), "E2": course("E2")}
    spec = RequirementRuleSpec("Electives", "credits", 3, course_codes=("E1", "E2"))
    finding = evaluate_requirement(spec, stated(("E1", "completed")), catalog)
    assert finding.verdict is Verdict.satisfied


def test_course_outside_the_catalog_is_unverifiable_not_ignored():
    """The cross-school elective. Silence would wrongly reject a legitimate choice."""
    catalog = {"E1": course("E1")}
    spec = RequirementRuleSpec(
        "Electives",
        "credits",
        3,
        course_codes=("E1",),
        caveat="Students may select a course offered within other graduate programs.",
    )
    finding = evaluate_requirement(spec, stated(("OTHER-GC 9000", "completed")), catalog)
    assert finding.verdict is Verdict.unverifiable
    assert "OTHER-GC 9000" in finding.detail
    assert finding.check_in_albert is True


def test_requirement_caveat_reaches_the_student():
    spec = RequirementRuleSpec(
        "Electives", "credits", 3, course_codes=("E1",), caveat="Internship needs a 3.0 GPA."
    )
    finding = evaluate_requirement(spec, stated(), {"E1": course("E1")})
    assert "Internship needs a 3.0 GPA." in finding.detail


# --------------------------------------------------------------------------------------
# Whole-plan evaluation
# --------------------------------------------------------------------------------------


@pytest.fixture
def program():
    catalog = {
        "C1": course("C1"),
        "C2": course("C2"),
        "A1": course("A1"),
        "A2": course("A2", prereqs=(("A1",),)),
        "R1": course("R1"),
        "R2": course("R2", prereqs=(("R1",),)),
        "CAP": course("CAP", prereqs=(("C1",), ("C2",))),
    }
    return ProgramRules(
        name="Test MS",
        total_credits=15,
        courses=catalog,
        requirements=(
            RequirementRuleSpec("Core", "all_of", 6, course_codes=("C1", "C2")),
            RequirementRuleSpec(
                "Concentration",
                "one_track",
                6,
                tracks=(TrackRule("Analytics", ("A1", "A2")), TrackRule("Risk", ("R1", "R2"))),
            ),
            RequirementRuleSpec("Capstone", "all_of", 3, course_codes=("CAP",)),
        ),
        source_url="https://example.edu/program",
        verified_on="2026-08-05",
    )


def test_plan_counts_credits_by_state(program):
    result = evaluate_plan(
        program,
        [
            StatedCourse("C1", CourseState.completed),
            StatedCourse("C2", CourseState.in_progress),
            StatedCourse("A1", CourseState.planned),
        ],
    )
    assert result.credits_completed == 3
    assert result.credits_in_progress == 3
    assert result.credits_planned == 3


def test_what_if_mode_counts_planned_courses(program):
    taken = [
        StatedCourse(c, CourseState.completed) for c in ("C1", "C2", "A1", "A2")
    ] + [StatedCourse("CAP", CourseState.planned)]

    today = evaluate_plan(program, taken)
    what_if = evaluate_plan(program, taken, include_planned=True)

    capstone_today = next(f for f in today.findings if f.summary.startswith("Capstone"))
    capstone_planned = next(f for f in what_if.findings if f.summary.startswith("Capstone"))
    assert capstone_today.verdict is Verdict.not_satisfied
    assert capstone_planned.verdict is Verdict.satisfied


def test_completed_courses_do_not_trigger_prerequisite_checks(program):
    """Re-litigating a finished course's prerequisites would be noise, and often wrong."""
    result = evaluate_plan(program, [StatedCourse("A2", CourseState.completed)])
    assert not any("Prerequisite" in f.summary for f in result.findings)


def test_planned_course_with_unmet_prerequisite_blocks(program):
    result = evaluate_plan(program, [StatedCourse("A2", CourseState.planned)])
    assert any(
        f.verdict is Verdict.not_satisfied and "Prerequisite missing" in f.summary
        for f in result.findings
    )


def test_unknown_planned_course_is_surfaced(program):
    result = evaluate_plan(program, [StatedCourse("XYZ-GC 1", CourseState.planned)])
    finding = next(f for f in result.findings if "XYZ-GC 1" in f.summary)
    assert finding.verdict is Verdict.unverifiable
    assert finding.check_in_albert is True


def test_needs_human_collects_everything_the_engine_cannot_settle(program):
    result = evaluate_plan(
        program,
        [
            StatedCourse("C1", CourseState.completed),
            StatedCourse("XYZ-GC 1", CourseState.planned),
        ],
    )
    assert any(f.verdict is Verdict.unverifiable for f in result.needs_human)


def test_no_finding_is_satisfied_without_a_citation(program):
    """A verified claim with nothing to check it against is the shape of a hallucination,
    even when a rule engine produced it."""
    result = evaluate_plan(program, [StatedCourse("C1", CourseState.completed)])
    for finding in result.findings:
        if finding.verdict is Verdict.satisfied:
            assert finding.citations, f"{finding.summary} claims satisfied with no source"


# --------------------------------------------------------------------------------------
# Finding identity — what makes a student's "I know about this one" survive a re-evaluation
# --------------------------------------------------------------------------------------


def test_every_finding_carries_a_key(program):
    result = evaluate_plan(
        program,
        [
            StatedCourse("C1", CourseState.completed),
            StatedCourse("A2", CourseState.planned),
            StatedCourse("XYZ-GC 1", CourseState.planned),
        ],
    )
    for finding in result.findings:
        assert finding.key, f"{finding.summary!r} has no key"


def test_finding_keys_are_unique_within_one_plan(program):
    """Two findings sharing a key would make an accepted risk ambiguous — accepting one
    would silently accept the other."""
    result = evaluate_plan(
        program,
        [
            StatedCourse("C1", CourseState.completed),
            StatedCourse("A2", CourseState.planned),
            StatedCourse("XYZ-GC 1", CourseState.planned),
        ],
    )
    keys = [f.key for f in result.findings]
    assert len(keys) == len(set(keys)), f"duplicate keys: {keys}"


def test_a_key_survives_both_the_summary_and_the_verdict_changing(program):
    """The whole point. The same requirement keeps its key as the situation moves under it,
    including the count in its summary — which is why the summary cannot be the key."""

    def core(result):
        return next(f for f in result.findings if f.key == "requirement:Core")

    empty = core(evaluate_plan(program, []))
    partial = core(evaluate_plan(program, [StatedCourse("C1", CourseState.completed)]))
    done = core(
        evaluate_plan(
            program,
            [
                StatedCourse("C1", CourseState.completed),
                StatedCourse("C2", CourseState.completed),
            ],
        )
    )

    assert empty.key == partial.key == done.key
    # The count moved, so a summary-derived key would have changed identity here.
    assert empty.summary != partial.summary
    # And the verdict moved, so a verdict-derived key would have changed it here.
    assert partial.verdict is Verdict.not_satisfied
    assert done.verdict is Verdict.satisfied


def test_course_findings_name_their_subject_and_requirement_findings_do_not(program):
    result = evaluate_plan(
        program,
        [
            StatedCourse("A2", CourseState.planned),
            StatedCourse("XYZ-GC 1", CourseState.planned),
        ],
    )
    prereq = next(f for f in result.findings if "Prerequisite" in f.summary)
    unknown = next(f for f in result.findings if "XYZ-GC 1" in f.summary)
    requirement = next(f for f in result.findings if f.key.startswith("requirement:"))

    assert prereq.subject == "A2"
    assert unknown.subject == "XYZ-GC 1"
    assert requirement.subject is None


# --- Pool concentrations: a track that lists more courses than it requires.
#
# Management & Analytics states each concentration as exactly two courses and requires both,
# so "complete the track" and "hold every course in it" were the same sentence and the rule
# was written that way. Financial Planning lists five per concentration and asks for three.
# Encoding that under the old reading told a student they owed two courses they do not,
# which is the direction of error this whole engine exists to avoid.


def _pool(name="Financial Analytics"):
    return TrackRule(name, ("F1", "F2", "F3", "F4", "F5"), min_courses=3)


def test_a_pool_track_completes_at_its_required_count_not_its_length():
    spec = RequirementRuleSpec("Concentration", "one_track", 9, tracks=(_pool(),))
    finding = evaluate_requirement(
        spec, stated(("F1", "completed"), ("F2", "completed"), ("F3", "completed")), {}
    )
    assert finding.verdict is Verdict.satisfied, finding.detail


def test_a_pool_track_short_of_its_count_says_how_many_more_not_which():
    """Naming every untaken course would overstate the requirement by the pool's surplus."""
    spec = RequirementRuleSpec("Concentration", "one_track", 9, tracks=(_pool(),))
    finding = evaluate_requirement(
        spec, stated(("F1", "completed"), ("F2", "completed")), {}
    )
    assert finding.verdict is Verdict.not_satisfied
    assert "2 of 3" in finding.detail
    assert "Choose 1 more" in finding.detail
    # The surplus must not be presented as owed.
    assert "F4" in finding.detail and "F5" in finding.detail  # offered as options
    assert "Choose 1 more" in finding.next_step


def test_a_full_track_still_requires_every_course():
    """The default is unchanged: no min_courses means all of them, the stricter reading."""
    spec = RequirementRuleSpec(
        "Concentration", "one_track", 6, tracks=(TrackRule("Risk", ("R1", "R2")),)
    )
    finding = evaluate_requirement(spec, stated(("R1", "completed")), {})
    assert finding.verdict is Verdict.not_satisfied
    assert "R2" in finding.detail


# --- A track that names a required course and draws the rest from a pool.
#
# Global Affairs states every concentration as one named course plus five chosen from
# thirty-odd. Folding the named one into the pool would let a student complete the
# concentration while skipping the course it is built around — a wrong pass, which is the
# direction of error this engine exists to prevent.


def _named_plus_pool():
    return RequirementRuleSpec(
        "Concentration", "one_track", 18,
        tracks=(
            TrackRule(
                "Peacebuilding",
                ("E1", "E2", "E3", "E4", "E5", "E6", "E7"),
                min_courses=5,
                required_codes=("R1",),
            ),
        ),
    )


def test_the_named_course_is_not_optional():
    """Five pool courses is the right count and still not the requirement."""
    finding = evaluate_requirement(
        _named_plus_pool(),
        stated(*[(c, "completed") for c in ("E1", "E2", "E3", "E4", "E5")]),
        {},
    )
    assert finding.verdict is Verdict.not_satisfied
    assert "R1" in finding.detail


def test_the_track_completes_with_the_named_course_and_the_pool_draw():
    finding = evaluate_requirement(
        _named_plus_pool(),
        stated(*[(c, "completed") for c in ("R1", "E1", "E2", "E3", "E4", "E5")]),
        {},
    )
    assert finding.verdict is Verdict.satisfied, finding.detail


def test_an_outstanding_named_course_is_reported_before_the_pool_shortfall():
    """"Choose 2 more" would describe a free choice while a fixed course is owed."""
    finding = evaluate_requirement(
        _named_plus_pool(), stated(("E1", "completed"), ("E2", "completed"), ("E3", "completed")), {}
    )
    assert "R1" in finding.detail
    assert "R1" in finding.next_step
