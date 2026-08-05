"""The planning rule engine: pure functions over encoded rules and a stated record.

No database, no model, no I/O. Callers load the program's rules and hand them in; that is
what makes every branch here unit-testable and what keeps a wrong answer fixable at one
point rather than probabilistically.

Two invariants the tests hold it to:

* **Absence of evidence never becomes a pass.** A missing grade, an unrecognised course, a
  prerequisite outside the encoded catalog — each produces `unverifiable`, never
  `satisfied`. The failure mode this exists to prevent is telling a student they can
  register when they cannot; they find out at the registration screen.
* **A rule the engine cannot evaluate is reported, not skipped.** Requirement caveats are
  carried into the output verbatim, because the parts a tool cannot check are exactly the
  parts a student needs pointed at.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.planning.types import (
    Citation,
    CourseState,
    Finding,
    PlanResult,
    StatedCourse,
    Verdict,
)

# Grade ordering for minimum-grade prerequisites. Anything outside this list is a grade
# the engine does not understand, which makes the comparison unverifiable rather than
# false — a pass/fail guess about someone's transcript is not a guess worth making.
GRADE_ORDER = ["F", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]


@dataclass(frozen=True)
class CourseRule:
    """A course as the engine needs it: identity, weight, and its prerequisite groups."""

    code: str
    title: str
    credits: int
    # Each inner tuple is one OR-group; every group must be satisfied.
    prerequisite_groups: tuple[tuple[str, ...], ...] = ()
    min_grades: tuple[tuple[str, str], ...] = ()  # (prereq_code, min_grade)
    prerequisite_text: str | None = None
    catalog_url: str | None = None
    verified_on: str | None = None


@dataclass(frozen=True)
class TrackRule:
    name: str
    course_codes: tuple[str, ...]


@dataclass(frozen=True)
class RequirementRuleSpec:
    name: str
    rule: str  # all_of | credits | one_track
    min_credits: int
    course_codes: tuple[str, ...] = ()
    tracks: tuple[TrackRule, ...] = ()
    min_courses: int | None = None
    caveat: str | None = None
    source_url: str | None = None
    verified_on: str | None = None


@dataclass(frozen=True)
class ProgramRules:
    name: str
    total_credits: int
    requirements: tuple[RequirementRuleSpec, ...]
    courses: dict[str, CourseRule]
    source_url: str | None = None
    verified_on: str | None = None


def _cite(spec_or_course) -> Citation:
    return Citation(
        label=getattr(spec_or_course, "name", None) or getattr(spec_or_course, "code", ""),
        url=getattr(spec_or_course, "source_url", None) or getattr(spec_or_course, "catalog_url", None),
        verified_on=getattr(spec_or_course, "verified_on", None),
    )


def grade_meets(actual: str | None, minimum: str) -> bool | None:
    """True / False / None, where None means the comparison could not be made.

    None is returned when the student stated no grade or stated something the scale does
    not contain. Collapsing that into False would invent a failing grade; collapsing it
    into True would wave through a prerequisite nobody checked.
    """
    if actual is None:
        return None
    a, m = actual.strip().upper(), minimum.strip().upper()
    if a not in GRADE_ORDER or m not in GRADE_ORDER:
        return None
    return GRADE_ORDER.index(a) >= GRADE_ORDER.index(m)


def check_prerequisites(
    course: CourseRule,
    stated: dict[str, StatedCourse],
    *,
    allow_in_progress: bool = False,
) -> list[Finding]:
    """Evaluate one course's prerequisite groups against what the student says they hold.

    `allow_in_progress` models planning a future term, where a course being taken now will
    be complete before the target term starts. It is off by default because prerequisites
    are enforced at enrollment.
    """
    findings: list[Finding] = []
    if not course.prerequisite_groups:
        return findings

    min_grade_by_code = dict(course.min_grades)
    citation = Citation(
        label=f"{course.code} prerequisites",
        url=course.catalog_url,
        verified_on=course.verified_on,
        quote=course.prerequisite_text,
    )

    satisfying_states = {CourseState.completed}
    if allow_in_progress:
        satisfying_states.add(CourseState.in_progress)

    for group in course.prerequisite_groups:
        alternatives_met: list[str] = []
        alternatives_unknown: list[str] = []

        for code in group:
            held = stated.get(code)
            if held is None or held.state not in satisfying_states:
                continue
            minimum = min_grade_by_code.get(code)
            if minimum is None:
                alternatives_met.append(code)
                continue
            meets = grade_meets(held.grade, minimum)
            if meets is True:
                alternatives_met.append(code)
            elif meets is None:
                alternatives_unknown.append(code)

        options = " or ".join(group)
        if alternatives_met:
            met = alternatives_met[0]
            held_state = stated[met].state
            if held_state is CourseState.in_progress:
                # Correct verdict, but it depends on finishing the course first — and the
                # engine must not describe an in-progress course as completed. Restating
                # the student's own record back to them incorrectly is the fastest way to
                # lose their trust in everything else on the page.
                findings.append(
                    Finding(
                        verdict=Verdict.conditional,
                        summary=f"Prerequisite met if you pass {met}",
                        detail=(
                            f"{course.code} requires {options}. You are taking {met} now, "
                            "so this holds provided you complete it before the term starts."
                        ),
                        citations=(citation,),
                        next_step=f"Confirm your {met} result before registering.",
                    )
                )
            else:
                findings.append(
                    Finding(
                        verdict=Verdict.satisfied,
                        summary=f"Prerequisite met: {met}",
                        detail=(
                            f"{course.code} requires {options}. You have reported "
                            f"completing {met}."
                        ),
                        citations=(citation,),
                    )
                )
            continue

        if alternatives_unknown:
            code = alternatives_unknown[0]
            minimum = min_grade_by_code[code]
            findings.append(
                Finding(
                    verdict=Verdict.unverifiable,
                    summary=f"Grade needed for {code}",
                    detail=(
                        f"{course.code} requires {code} with a minimum grade of {minimum}. "
                        "You reported taking it but did not give a grade this tool can "
                        "compare, so the requirement cannot be confirmed here."
                    ),
                    citations=(citation,),
                    next_step=f"Check your grade for {code} in Albert.",
                    check_in_albert=True,
                )
            )
            continue

        missing_known = [c for c in group if c in stated]
        detail = f"{course.code} requires {options}."
        if missing_known:
            held = stated[missing_known[0]]
            detail += (
                f" You listed {missing_known[0]} as {held.state.value.replace('_', ' ')}, "
                "and prerequisites are enforced at the time you enroll."
            )
        else:
            detail += " You have not reported completing it."

        findings.append(
            Finding(
                verdict=Verdict.not_satisfied,
                summary=f"Prerequisite missing: {options}",
                detail=detail,
                citations=(citation,),
                next_step=f"Complete {options} before registering for {course.code}.",
            )
        )

    return findings


def evaluate_requirement(
    spec: RequirementRuleSpec,
    stated: dict[str, StatedCourse],
    courses: dict[str, CourseRule],
    *,
    counting_states: frozenset[CourseState] = frozenset({CourseState.completed}),
) -> Finding:
    """One requirement, one finding. Dispatches on `rule` rather than inferring intent."""
    citation = Citation(
        label=spec.name, url=spec.source_url, verified_on=spec.verified_on, quote=spec.caveat
    )
    held = {code for code, c in stated.items() if c.state in counting_states}

    if spec.rule == "all_of":
        missing = [c for c in spec.course_codes if c not in held]
        if not missing:
            return Finding(
                verdict=Verdict.satisfied,
                summary=f"{spec.name} complete",
                detail=f"All {len(spec.course_codes)} required courses reported complete.",
                citations=(citation,),
            )
        return Finding(
            verdict=Verdict.not_satisfied,
            summary=f"{spec.name}: {len(missing)} course(s) remaining",
            detail="Still required: " + ", ".join(missing) + ".",
            citations=(citation,),
            next_step=f"Plan {', '.join(missing)}.",
        )

    if spec.rule == "one_track":
        # Credit counting answers this wrong: one course from each of two tracks is the
        # full credit total and completes neither.
        progress = [
            (track, [c for c in track.course_codes if c in held]) for track in spec.tracks
        ]
        complete = [t for t, done in progress if len(done) == len(t.course_codes)]
        if complete:
            return Finding(
                verdict=Verdict.satisfied,
                summary=f"{spec.name} complete: {complete[0].name}",
                detail=f"You have completed the {complete[0].name} concentration.",
                citations=(citation,),
            )

        started = [(t, done) for t, done in progress if done]
        if len(started) > 1:
            names = ", ".join(t.name for t, _ in started)
            return Finding(
                verdict=Verdict.not_satisfied,
                summary=f"{spec.name}: courses spread across tracks",
                detail=(
                    f"You have courses in more than one concentration ({names}). "
                    f"{spec.caveat or 'One concentration must be completed in full.'} "
                    "Credits from a concentration you do not finish do not satisfy this "
                    "requirement."
                ),
                citations=(citation,),
                next_step="Pick one concentration and complete both of its courses.",
            )
        if started:
            track, done = started[0]
            remaining = [c for c in track.course_codes if c not in done]
            return Finding(
                verdict=Verdict.not_satisfied,
                summary=f"{spec.name}: {track.name} in progress",
                detail=f"Remaining in {track.name}: {', '.join(remaining)}.",
                citations=(citation,),
                next_step=f"Plan {', '.join(remaining)}.",
            )
        # Nothing counted yet — but "not started" is wrong if a track course is in flight,
        # and a student reading that about a course they are sitting in stops believing
        # the rest of the page.
        underway = [
            (t, [c for c in t.course_codes if c in stated
                 and stated[c].state is CourseState.in_progress])
            for t in spec.tracks
        ]
        underway = [(t, c) for t, c in underway if c]
        if underway:
            track, courses_now = underway[0]
            remaining = [c for c in track.course_codes if c not in courses_now]
            return Finding(
                verdict=Verdict.not_satisfied,
                summary=f"{spec.name}: {track.name} underway",
                detail=(
                    f"You are taking {', '.join(courses_now)} now. Once complete, "
                    f"{track.name} still needs {', '.join(remaining)}."
                ),
                citations=(citation,),
                next_step=f"Plan {', '.join(remaining)}.",
            )

        options = ", ".join(t.name for t in spec.tracks)
        return Finding(
            verdict=Verdict.not_satisfied,
            summary=f"{spec.name} not started",
            detail=f"Choose one concentration: {options}.",
            citations=(citation,),
            next_step="Choose a concentration with your advisor.",
        )

    # rule == "credits"
    listed_credits = sum(
        courses[c].credits for c in spec.course_codes if c in held and c in courses
    )
    # Courses the student holds that this tool cannot place: the elective scope is wider
    # than the listed set, so silence here would wrongly reject a legitimate choice.
    unknown_held = [c for c in held if c not in courses]

    if listed_credits >= spec.min_credits:
        return Finding(
            verdict=Verdict.satisfied,
            summary=f"{spec.name} complete",
            detail=f"{listed_credits} of {spec.min_credits} credits from the listed courses.",
            citations=(citation,),
        )

    detail = f"{listed_credits} of {spec.min_credits} credits so far."
    if spec.caveat:
        detail += f" {spec.caveat}"
    if unknown_held:
        detail += (
            " You also listed "
            + ", ".join(sorted(unknown_held))
            + ", which is not in this program's catalog — whether it counts here cannot be "
            "confirmed by this tool."
        )
    return Finding(
        verdict=Verdict.unverifiable if unknown_held else Verdict.not_satisfied,
        summary=f"{spec.name}: {spec.min_credits - listed_credits} credit(s) short",
        detail=detail,
        citations=(citation,),
        next_step="Confirm your elective choice with your advisor and in Albert.",
        check_in_albert=bool(unknown_held) or bool(spec.caveat),
    )


def evaluate_plan(
    program: ProgramRules,
    stated_courses: list[StatedCourse],
    *,
    include_planned: bool = False,
) -> PlanResult:
    """Full degree evaluation against a self-reported record.

    `include_planned` answers "if I take everything on my plan, where do I stand?" — the
    what-if mode — by counting planned courses as held. Off by default so the same engine
    answers "where do I stand today?" without a second implementation.
    """
    stated = {c.code: c for c in stated_courses}
    counting = {CourseState.completed}
    if include_planned:
        counting |= {CourseState.in_progress, CourseState.planned}

    result = PlanResult(credits_required=program.total_credits)

    for course in stated_courses:
        rule = program.courses.get(course.code)
        credits = rule.credits if rule else 0
        if course.state is CourseState.completed:
            result.credits_completed += credits
        elif course.state is CourseState.in_progress:
            result.credits_in_progress += credits
        else:
            result.credits_planned += credits

    for spec in program.requirements:
        result.add(
            evaluate_requirement(
                spec, stated, program.courses, counting_states=frozenset(counting)
            )
        )

    # Prerequisites only matter for what the student has not yet taken.
    for course in stated_courses:
        if course.state is CourseState.completed:
            continue
        rule = program.courses.get(course.code)
        if rule is None:
            result.add(
                Finding(
                    verdict=Verdict.unverifiable,
                    summary=f"{course.code} is not in this catalog",
                    detail=(
                        f"{course.code} is not part of the {program.name} catalog this tool "
                        "has loaded, so its prerequisites and whether it counts toward your "
                        "degree cannot be checked here."
                    ),
                    next_step="Confirm with your advisor and in Albert.",
                    check_in_albert=True,
                )
            )
            continue
        result.findings.extend(
            check_prerequisites(rule, stated, allow_in_progress=course.state is CourseState.planned)
        )

    return result
