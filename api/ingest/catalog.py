"""Stage 5 — parse the published course catalog into a structured prerequisite graph.

    .venv/Scripts/python -m ingest.catalog --dry-run   # parse and report, touch nothing
    .venv/Scripts/python -m ingest.catalog             # write courses + prerequisites
    .venv/Scripts/python -m ingest.catalog --strict    # exit 1 if anything failed to parse

The planner needs a graph, not prose. Everything here converts bulletin text into rows a
deterministic rule engine can traverse, with the source sentence carried alongside so a
verdict can quote the catalog rather than assert a parse.

**Unparseable input is reported, never skipped.** A prerequisite the parser does not
understand and silently drops becomes a course the planner declares available when it is
not — the single most damaging failure this tool could have, because the student only
finds out at the registration screen. Anything unrecognised is surfaced loudly and, under
--strict, fails the build.

Observed forms in the MASY1-GC catalog as of 2026-08: `A AND B` and bare `A`, with
inconsistent spacing before the terminating period. OR and comma forms are handled because
other programs use them and discovering that at runtime is not acceptable.
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import Course, CoursePrerequisite

SECTIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "sections"

# Course codes as the bulletin writes them, e.g. "MASY1-GC 2100".
#
# The number is 1-4 digits, not 4. It was 4 while MASY1-GC was the only catalogue read, and
# every code there happens to be four digits. Executive Masters in Marketing numbers its
# courses `EMSC1-GC 10` through `EMSC1-GC 300`, so a four-digit pattern matched none of its
# seventeen — and matched them to *nothing*, silently: a page that parses to zero courses is
# indistinguishable from a page with no courses on it. `--strict` could not catch that,
# because there was no failed parse to report, which is why the empty-page check below
# exists alongside this.
COURSE_CODE = re.compile(r"\b([A-Z]{4}\d?-[A-Z]{2}\s?\d{1,4})\b")
HEADING_CODE = re.compile(r"^([A-Z]{4}\d?-[A-Z]{2}\s?\d{1,4})\s+(.*)$")
CREDITS = re.compile(r"Credits:\s*\((\d+(?:\.\d+)?)\s*Credits?\)", re.IGNORECASE)
FIELD_LINE = re.compile(r"^(Prerequisites?|Typically offered|Grading|Repeatability):?\s*(.*)$")

# Splits alternatives within a group. Deliberately not splitting on bare "/" — course
# codes contain one.
OR_SPLIT = re.compile(r"\s+(?:OR|or)\s+|\s*\|\s*")
AND_SPLIT = re.compile(r"\s+(?:AND|and)\s+|\s*,\s*|\s*;\s*|\s*&\s*")


@dataclass
class ParsedCourse:
    code: str
    title: str
    credits: float
    description: str
    typically_offered: str | None
    # Each inner list is one OR-group; all groups must be satisfied.
    prerequisite_groups: list[list[str]] = field(default_factory=list)
    prerequisite_raw: str | None = None
    parse_problem: str | None = None


def normalise_code(code: str) -> str:
    """`MASY1-GC2100` and `MASY1-GC 2100` are the same course."""
    return re.sub(r"\s+", " ", code.strip()).replace("- ", "-")


def parse_prerequisites(raw: str) -> tuple[list[list[str]], str | None]:
    """Return (groups, problem). A non-null problem means do not trust the groups."""
    text = raw.strip().rstrip(".").strip()
    if not text:
        return [], None

    # Several catalogues write the absence of prerequisites out longhand. That is an answer,
    # not an unreadable clause, and conflating the two would have the planner warn "cannot
    # verify" on fourteen courses the bulletin says are open to anyone.
    if text.lower() in {"none", "n/a", "na", "no prerequisites"}:
        return [], None

    groups: list[list[str]] = []
    for clause in AND_SPLIT.split(text):
        clause = clause.strip()
        if not clause:
            continue
        alternatives = [
            normalise_code(match.group(1))
            for part in OR_SPLIT.split(clause)
            if (match := COURSE_CODE.search(part))
        ]
        if not alternatives:
            # A clause with no recognisable course code: a narrative requirement such as
            # "permission of the department". Real, but not something the graph can model.
            return groups, f"clause carries no course code: {clause!r}"
        groups.append(alternatives)

    if not groups:
        return [], f"no course codes found in {raw!r}"
    return groups, None


def parse_course_section(section: dict) -> ParsedCourse | None:
    heading = section["heading"].strip()
    match = HEADING_CODE.match(heading)
    if not match:
        return None

    code = normalise_code(match.group(1))
    title = match.group(2).strip()
    text = section["text"]

    credits_match = CREDITS.search(text)
    credits = float(credits_match.group(1)) if credits_match else 0.0

    description_lines: list[str] = []
    prerequisite_raw: str | None = None
    typically_offered: str | None = None

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        field_match = FIELD_LINE.match(line)
        if field_match:
            label, value = field_match.group(1).lower(), field_match.group(2).strip()
            if label.startswith("prerequisite"):
                prerequisite_raw = value
            elif label.startswith("typically"):
                typically_offered = value or line
            continue
        if line.lower().startswith("credits:"):
            continue
        description_lines.append(line)

    groups: list[list[str]] = []
    problem: str | None = None
    if prerequisite_raw:
        groups, problem = parse_prerequisites(prerequisite_raw)

    return ParsedCourse(
        code=code,
        title=title,
        credits=credits,
        description=" ".join(description_lines).strip(),
        typically_offered=typically_offered,
        prerequisite_groups=groups,
        prerequisite_raw=prerequisite_raw,
        parse_problem=problem,
    )


def load_catalog_pages() -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(SECTIONS_DIR.glob("*.json"))
        if json.loads(path.read_text(encoding="utf-8")).get("topic") == "courses"
    ]


def parse_all() -> tuple[list[tuple[ParsedCourse, dict]], list[str]]:
    parsed: list[tuple[ParsedCourse, dict]] = []
    problems: list[str] = []
    for page in load_catalog_pages():
        before = len(parsed)
        for section in page["sections"]:
            course = parse_course_section(section)
            if course is None:
                problems.append(f"{page['slug']}: heading not a course: {section['heading']!r}")
                continue
            if course.credits == 0:
                problems.append(f"{course.code}: no credit value found")
            if course.parse_problem:
                problems.append(f"{course.code}: {course.parse_problem}")
            parsed.append((course, page))
        # A catalogue page that yields nothing is the one failure this module could not
        # otherwise see. Every check above fires on a course it half-understood; none fires
        # when the code pattern matches no heading at all, because then there is no course to
        # attach a complaint to. That is not hypothetical — a four-digit-only code pattern
        # read all seventeen Executive Masters courses as zero, and reported success.
        if len(parsed) == before:
            problems.append(
                f"{page['slug']}: catalogue page parsed to zero courses — the code pattern "
                f"matched no heading among {len(page['sections'])} sections"
            )
    return parsed, problems


def write(parsed: list[tuple[ParsedCourse, dict]]) -> tuple[int, int, list[str]]:
    now = datetime.now(UTC)
    unresolved: list[str] = []

    with get_sessionmaker()() as session:
        by_code: dict[str, Course] = {}
        for course, page in parsed:
            row = session.scalars(select(Course).where(Course.code == course.code)).first()
            if row is None:
                row = Course(code=course.code, department="Management and Systems", credits=0)
                session.add(row)
            row.title = course.title
            row.credits = course.credits
            row.description = course.description or None
            row.typically_offered = course.typically_offered
            # Carry the unreadable clause into the row. A course that states prerequisites
            # the parser could not resolve must not be storable as one that has none: the
            # edge list is empty either way, and only this field tells them apart.
            row.prerequisite_unparsed = (
                course.prerequisite_raw
                if course.parse_problem and not course.prerequisite_groups
                else None
            )
            row.source = "catalog"
            row.catalog_url = page["url"]
            row.catalog_verified_at = datetime.fromisoformat(page["fetched_at"])
            session.flush()
            by_code[course.code] = row

        # Prerequisites second: an edge can point at a course defined later in the file.
        edges = 0
        for course, _ in parsed:
            row = by_code[course.code]
            session.query(CoursePrerequisite).filter(
                CoursePrerequisite.course_id == row.id
            ).delete()
            for group_index, alternatives in enumerate(course.prerequisite_groups):
                for code in alternatives:
                    target = by_code.get(code)
                    if target is None:
                        # Cross-program prerequisite: real, but outside the ingested
                        # catalog. Recorded rather than dropped — the planner has to say
                        # "this requires a course I cannot verify" instead of staying quiet.
                        unresolved.append(f"{course.code} requires {code} (not in catalog)")
                        continue
                    session.add(
                        CoursePrerequisite(
                            course_id=row.id,
                            prerequisite_id=target.id,
                            group_index=group_index,
                            raw_text=course.prerequisite_raw,
                        )
                    )
                    edges += 1
        session.commit()
    return len(parsed), edges, unresolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit 1 on any parse problem")
    args = parser.parse_args()

    parsed, problems = parse_all()
    with_prereqs = [c for c, _ in parsed if c.prerequisite_groups]

    print(f"parsed {len(parsed)} courses · {len(with_prereqs)} carry prerequisites")
    print(f"credits: {sum(c.credits for c, _ in parsed)} total across catalog")

    print("\nprerequisite graph:")
    for course, _ in parsed:
        if not course.prerequisite_groups:
            continue
        rendered = " AND ".join(
            "(" + " OR ".join(group) + ")" if len(group) > 1 else group[0]
            for group in course.prerequisite_groups
        )
        print(f"  {course.code:<16} <- {rendered}")

    if problems:
        print(f"\nPARSE PROBLEMS ({len(problems)}) — these are not skipped silently:")
        for problem in problems:
            print(f"  ! {problem}")
    else:
        print("\nno parse problems")

    if args.dry_run:
        print("\ndry run: nothing written")
        return

    courses, edges, unresolved = write(parsed)
    print(f"\nwrote {courses} catalog courses, {edges} prerequisite edges")
    if unresolved:
        print(f"unresolved prerequisite targets ({len(unresolved)}):")
        for item in unresolved:
            print(f"  ? {item}")

    if args.strict and (problems or unresolved):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
