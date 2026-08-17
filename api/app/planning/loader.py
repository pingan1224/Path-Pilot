"""Load encoded program rules out of the database into the engine's plain structures.

The boundary matters: everything past this module is pure functions over frozen
dataclasses. The engine cannot reach the database, so a planning verdict cannot depend on
query order, lazy loading, or session state — only on rules that were explicitly handed to
it. That is what makes the unit tests meaningful rather than decorative.

Only `source='catalog'` rows are loaded. Planning for a real student must never traverse
one of the invented demo courses.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Course,
    CoursePrerequisite,
    Program,
    Requirement,
    RequirementTrack,
)
from app.planning.rules import (
    CourseRule,
    ProgramRules,
    RequirementRuleSpec,
    TrackRule,
)


class ProgramNotEncodedError(LookupError):
    """Raised when planning is requested for a program with no encoded requirements."""


def _iso(value) -> str | None:
    return value.date().isoformat() if value else None


# The whole catalog, keyed by the fingerprint it was built from. Process-local and
# deliberately unbounded — it holds one entry.
#
# **This is a cache of reference data, not of a verdict, and the distinction is the reason
# it is allowed here at all.** "No stored status, recompute on read" exists because a
# student's situation changes underneath a stored answer and the answer keeps looking
# authoritative. The catalogue changes when someone runs an ingest, which is a deploy-shaped
# event, and nothing about a student can change it. Every plan is still recomputed on every
# read; what is reused is the 749 rows of course data those computations all read from.
#
# Staleness is made impossible rather than unlikely: the fingerprint below is one query that
# counts the catalogue and takes its newest `updated_at`, so an ingest that adds, removes or
# edits any course invalidates the entry on the next read. One round trip (~20 ms) replaces
# two and 749 rows (~87 ms), and `/missions` paid that per open mission.
_CATALOG: dict[tuple, dict[str, CourseRule]] = {}


_PROGRAM_RULES: dict[tuple, ProgramRules] = {}


def _catalog_fingerprint(session: Session) -> tuple:
    """One round trip covering everything an ingest can change.

    Counts and newest-`updated_at` for the catalogue, plus row counts for the three tables
    that carry a degree's shape. Edges and requirements are counted separately from courses
    because either can change without a course row being touched — a new prerequisite, or a
    re-encoded requirement, would otherwise be invisible to the fingerprint and the cache
    would serve the old degree until the process restarted.
    """
    row = session.execute(
        select(
            func.count(Course.id),
            func.max(Course.updated_at),
            select(func.count(CoursePrerequisite.id)).scalar_subquery(),
            select(func.count(Requirement.id)).scalar_subquery(),
            select(func.max(Requirement.updated_at)).scalar_subquery(),
            select(func.count(RequirementTrack.id)).scalar_subquery(),
        ).where(Course.source == "catalog")
    ).one()
    return tuple(row)


def load_catalog_courses(session: Session) -> dict[str, CourseRule]:
    fingerprint = _catalog_fingerprint(session)
    cached = _CATALOG.get(fingerprint)
    if cached is not None:
        return cached

    courses = session.scalars(
        select(Course).where(Course.source == "catalog")
    ).all()
    by_id = {c.id: c for c in courses}

    edges = session.scalars(
        select(CoursePrerequisite).where(
            CoursePrerequisite.course_id.in_(by_id.keys())
        )
    ).all()

    grouped: dict[int, dict[int, list[str]]] = {}
    grades: dict[int, list[tuple[str, str]]] = {}
    raw_text: dict[int, str] = {}
    concurrent: dict[int, list[str]] = {}
    for edge in edges:
        target = by_id.get(edge.prerequisite_id)
        if target is None:
            # Prerequisite outside the loaded catalog. Dropping it silently would make the
            # course look freely available; ingest.catalog already reports these, and the
            # engine will flag the course as unverifiable when it is not in `courses`.
            continue
        grouped.setdefault(edge.course_id, {}).setdefault(edge.group_index, []).append(
            target.code
        )
        if edge.min_grade:
            grades.setdefault(edge.course_id, []).append((target.code, edge.min_grade))
        if edge.raw_text:
            raw_text[edge.course_id] = edge.raw_text
        if edge.can_be_concurrent:
            concurrent.setdefault(edge.course_id, []).append(target.code)

    rules: dict[str, CourseRule] = {}
    for course in courses:
        groups = grouped.get(course.id, {})
        rules[course.code] = CourseRule(
            code=course.code,
            title=course.title,
            credits=course.credits,
            prerequisite_groups=tuple(
                tuple(groups[i]) for i in sorted(groups)
            ),
            min_grades=tuple(grades.get(course.id, ())),
            prerequisite_text=raw_text.get(course.id),
            catalog_url=course.catalog_url,
            verified_on=_iso(course.catalog_verified_at),
            concurrent=tuple(sorted(concurrent.get(course.id, ()))),
            typically_offered=course.typically_offered,
        )

    # One entry, replaced wholesale: an older fingerprint can never be read again, so
    # keeping it would only hold memory. `CourseRule` is frozen, so handing the same dict to
    # every caller cannot let one of them mutate another's catalogue.
    _CATALOG.clear()
    _CATALOG[fingerprint] = rules
    return rules


def load_program_rules(session: Session, program_code: str) -> ProgramRules:
    # Cached on the same fingerprint as the catalogue, and for the same reason: a degree's
    # encoded rules change when someone runs an ingest, never because of anything a student
    # does. The plan is still evaluated from scratch on every read — this reuses the rules
    # it is evaluated *against*.
    #
    # Worth more than the catalogue cache, because `/missions` calls this once per open
    # mission and a student's missions are almost always for the same degree. Every query it
    # avoids is a ~22 ms round trip to a database in another region, which is what this
    # endpoint's latency is actually made of.
    fingerprint = _catalog_fingerprint(session)
    cache_key = (program_code, fingerprint)
    cached = _PROGRAM_RULES.get(cache_key)
    if cached is not None:
        return cached

    program = session.scalars(
        select(Program)
        .where(Program.code == program_code, Program.source == "catalog")
        .options(
            selectinload(Program.requirements).selectinload(Requirement.courses),
            # Both track collections are loaded here, not just the tracks themselves.
            # `TrackRule` below reads `track.courses` and `track.required_courses`, and
            # with only `tracks` eager-loaded those were lazy — two extra round trips per
            # concentration. MASY has four, so a single `/plan` spent eight queries and
            # ~160ms of its ~540ms fetching them one at a time. The cost scales with
            # concentrations, so the degrees with the most choice were the slowest to open.
            selectinload(Program.requirements)
            .selectinload(Requirement.tracks)
            .selectinload(RequirementTrack.courses),
            selectinload(Program.requirements)
            .selectinload(Requirement.tracks)
            .selectinload(RequirementTrack.required_courses),
        )
    ).first()
    if program is None:
        raise ProgramNotEncodedError(
            f"No encoded catalog program with code {program_code!r}. "
            "Planning is only supported for programs whose requirements have been encoded."
        )
    if program.total_credits_required is None:
        # The program exists and is listed, but nobody has transcribed what it requires.
        # Loud rather than silent: a plan built against a null total reports every student
        # as needing zero credits, and reports it confidently.
        #
        # Worded for the student, because this string reaches the screen. Naming the ingest
        # script here — as it did once — tells the person reading it to go and run
        # something they have no access to, in a vocabulary that is not theirs.
        raise ProgramNotEncodedError(
            f"Path Pilot has not transcribed the degree requirements for {program.name}, "
            "so it cannot check your record against them. Policy answers and registration "
            "error decoding still work for your program."
        )

    courses = load_catalog_courses(session)

    specs: list[RequirementRuleSpec] = []
    for requirement in sorted(program.requirements, key=lambda r: r.sort_order):
        tracks = tuple(
            TrackRule(
                name=track.name,
                course_codes=tuple(sorted(c.code for c in track.courses)),
                min_courses=track.min_courses,
                required_codes=tuple(sorted(c.code for c in track.required_courses)),
            )
            for track in sorted(requirement.tracks, key=lambda t: t.sort_order)
        )
        specs.append(
            RequirementRuleSpec(
                name=requirement.name,
                rule=str(requirement.rule),
                min_credits=requirement.min_credits,
                course_codes=tuple(sorted(c.code for c in requirement.courses)),
                tracks=tracks,
                min_courses=requirement.min_courses,
                caveat=requirement.caveat,
                source_url=requirement.source_url,
                verified_on=_iso(requirement.source_verified_at),
            )
        )

    rules = ProgramRules(
        name=program.name,
        total_credits=program.total_credits_required,
        requirements=tuple(specs),
        courses=courses,
        source_url=program.catalog_url,
        verified_on=_iso(program.catalog_verified_at),
    )

    # Entries for a superseded fingerprint can never be read again, so they are dropped
    # rather than left to accumulate one per ingest. Bounded at the 23 encoded degrees.
    for stale in [k for k in _PROGRAM_RULES if k[1] != fingerprint]:
        del _PROGRAM_RULES[stale]
    _PROGRAM_RULES[cache_key] = rules
    return rules
