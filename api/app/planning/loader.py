"""Load encoded program rules out of the database into the engine's plain structures.

The boundary matters: everything past this module is pure functions over frozen
dataclasses. The engine cannot reach the database, so a planning verdict cannot depend on
query order, lazy loading, or session state — only on rules that were explicitly handed to
it. That is what makes the unit tests meaningful rather than decorative.

Only `source='catalog'` rows are loaded. Planning for a real student must never traverse
one of the invented demo courses.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Course, CoursePrerequisite, Program, Requirement
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


def load_catalog_courses(session: Session) -> dict[str, CourseRule]:
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
    return rules


def load_program_rules(session: Session, program_code: str) -> ProgramRules:
    program = session.scalars(
        select(Program)
        .where(Program.code == program_code, Program.source == "catalog")
        .options(
            selectinload(Program.requirements).selectinload(Requirement.courses),
            selectinload(Program.requirements).selectinload(Requirement.tracks),
        )
    ).first()
    if program is None:
        raise ProgramNotEncodedError(
            f"No encoded catalog program with code {program_code!r}. "
            "Planning is only supported for programs whose requirements have been encoded."
        )

    courses = load_catalog_courses(session)

    specs: list[RequirementRuleSpec] = []
    for requirement in sorted(program.requirements, key=lambda r: r.sort_order):
        tracks = tuple(
            TrackRule(
                name=track.name,
                course_codes=tuple(sorted(c.code for c in track.courses)),
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

    return ProgramRules(
        name=program.name,
        total_credits=program.total_credits_required,
        requirements=tuple(specs),
        courses=courses,
        source_url=program.catalog_url,
        verified_on=_iso(program.catalog_verified_at),
    )
