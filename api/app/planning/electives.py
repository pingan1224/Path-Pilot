"""Which courses could fill a `credits` requirement, and which of them are open now.

The planner reports "3 of 6 credits so far" and stops there, honestly: a credits
requirement is a pool, not a list of things to finish. But the product's own question is
*what should I take next term*, and a shortfall with no candidates is where that question
goes unanswered — the student is told there is a hole and left to find the courses
themselves in a bulletin this tool has already read.

**Nothing here is inferred from a course code.** The obvious implementation is "every
catalogue course sharing the programme's subject prefix", and it is wrong three ways: it
sweeps in the core courses the student is required to take elsewhere, it misses the
cross-programme courses the bulletin explicitly allows, and it is a guess dressed as a
list — the same invention the HCM/HCAT dual degree is left unencoded rather than commit.

What it uses instead is what the requirement already says:

* the courses the requirement lists, which the bulletin named;
* the courses of the concentrations the student is *not* taking, where the caveat says a
  foundational course from another concentration is eligible — those are encoded, in the
  `one_track` requirement sitting beside this one.

Everything else the caveat allows — another graduate programme in the division, a named
course from outside the subject — is quoted rather than enumerated. This tool has not
loaded those catalogues, and a list that silently omits an option is worse than one that
says what it cannot see.

Eligibility itself is never asserted. Whether a given course counts toward this
requirement is the bulletin's judgement and the advisor's; what is computed here is
narrower and checkable: this course exists, you have not taken it, and its prerequisites
are or are not satisfied by what you have told us.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.planning.rules import (
    CourseRule,
    ProgramRules,
    RequirementRuleSpec,
    check_prerequisites,
)
from app.planning.types import StatedCourse, Verdict


@dataclass(frozen=True)
class ElectiveOption:
    """One course that could fill the gap, with the two facts a student needs first."""

    code: str
    title: str
    credits: float
    typically_offered: str | None
    # Where the course comes from: "listed" (named by the requirement) or the name of the
    # concentration it belongs to. This is not decoration, and it is not only provenance:
    # it decides whether the audit will *count* the course.
    source: str
    # Whether adding this course will move the credit total.
    #
    # The rule engine counts a `credits` requirement from the courses the requirement
    # lists, and nothing else. The caveat's other allowances — a foundational course from
    # another concentration — are prose it cannot execute, so a student who takes one has
    # a course the bulletin permits and the audit will not credit until an advisor says
    # so. Both facts are true and the row has to carry both, or a student adds a course
    # the product suggested and watches the gap not move.
    counts_automatically: bool
    # True when this student's record satisfies the prerequisites, False when it does not,
    # None when the course has none to check. Never a recommendation — a course whose
    # prerequisites are open is not thereby a good idea.
    prerequisites_met: bool | None
    prerequisite_text: str | None


def _eligible_codes(program: ProgramRules, spec: RequirementRuleSpec) -> list[tuple[str, str]]:
    """(code, source) for everything this requirement could be filled with, in code order.

    Concentration courses come from the sibling `one_track` requirement rather than from
    any parsing of the caveat: the bulletin's sentence says "a foundational course from
    any of the other concentrations", and the concentrations are already encoded next
    door. Reading them from there keeps this a lookup rather than an interpretation.
    """
    out: list[tuple[str, str]] = [(code, "listed") for code in spec.course_codes]
    for other in program.requirements:
        if other.rule != "one_track" or not other.tracks:
            continue
        for track in other.tracks:
            out.extend((code, track.name) for code in track.course_codes)
    # A course named twice keeps its first source, and "listed" is enumerated first, so a
    # course the requirement names outright is never relabelled as somebody's track.
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for code, source in out:
        if code not in seen:
            seen.add(code)
            unique.append((code, source))
    return sorted(unique)


def _started_track(program: ProgramRules, held: set[str]) -> str | None:
    """The concentration the student has begun, inferred from courses they hold.

    Read from the record rather than from the plan's own findings: a finding's fields are
    written for display and change when its wording does, and "which track am I doing" has
    to survive that. Holding any of a track's courses is the signal — a student does not
    take Advanced Risk Analytics by accident.
    """
    for spec in program.requirements:
        if spec.rule != "one_track" or not spec.tracks:
            continue
        for track in spec.tracks:
            if held & set(track.course_codes):
                return track.name
    return None


def elective_options(
    program: ProgramRules,
    spec: RequirementRuleSpec,
    stated: list[StatedCourse],
) -> list[ElectiveOption]:
    """Courses that could fill `spec`, minus everything the student already holds.

    Sorted by code, deliberately. Any other order — soonest offered, fewest
    prerequisites — would read as a ranking, and this tool has no basis for ranking one
    elective above another: that is a question about what the student wants to study.
    """
    held = {c.code for c in stated}
    by_code = {c.code: c for c in stated}
    chosen_track = _started_track(program, held)
    options: list[ElectiveOption] = []

    for code, source in _eligible_codes(program, spec):
        if code in held:
            continue
        # The concentration the student is doing is not an elective pool: those courses
        # are required by the one_track requirement, and offering them here would invite
        # them to spend an elective on something they must take anyway.
        if chosen_track is not None and source == chosen_track:
            continue
        course: CourseRule | None = program.courses.get(code)
        if course is None:
            # Named by a requirement but absent from the loaded catalogue. Skipped rather
            # than listed as a bare code: a row this tool can say nothing about is not a
            # candidate, it is a gap in the ingest, and the requirement's own caveat
            # already tells the student the list is not exhaustive.
            continue

        findings = check_prerequisites(course, by_code)
        met: bool | None
        if not course.prerequisite_groups:
            met = None
        else:
            met = all(f.verdict is Verdict.satisfied for f in findings)

        options.append(
            ElectiveOption(
                code=code,
                title=course.title,
                credits=course.credits,
                typically_offered=course.typically_offered,
                source=source,
                counts_automatically=source == "listed",
                prerequisites_met=met,
                prerequisite_text=course.prerequisite_text,
            )
        )
    return options


__all__ = ["ElectiveOption", "elective_options"]
