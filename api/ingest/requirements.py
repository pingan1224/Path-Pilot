"""Stage 6 — encode the MASY degree requirements as rules the planner can evaluate.

    .venv/Scripts/python -m ingest.requirements --dry-run
    .venv/Scripts/python -m ingest.requirements

Hand-encoded, unlike the course catalog. The requirements table is prose and layout — an
area header, an indented list, a footnote that redefines what "elective" means — and a
parser guessing at it would be a parser silently guessing at the thing the whole planner
depends on. Encoding it by hand and citing the source line is honest; the risk moves from
"the parser was wrong" to "the bulletin changed", which `source_verified_at` makes visible.

Everything here is checked against the ingested page at load time: every course code must
exist in the catalog, and the credits must sum to the stated total. A requirement set that
does not add up is a transcription error, and it fails loudly rather than producing a
planner that quietly mis-advises.

Source: bulletins.nyu.edu/graduate/professional-studies/programs/management-analytics-ms/
"""

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import Course, Program, Requirement, RequirementKind, RequirementTrack

SECTIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "sections"
PAGE_SLUG = "graduate__professional-studies__programs__management-analytics-ms"

PROGRAM_CODE = "MASY-MS-REAL"
PROGRAM_NAME = "Management and Analytics"
TOTAL_CREDITS = 36


@dataclass
class TrackSpec:
    name: str
    courses: list[str]


@dataclass
class RequirementSpec:
    name: str
    kind: RequirementKind
    rule: str
    min_credits: int
    courses: list[str] = field(default_factory=list)
    tracks: list[TrackSpec] = field(default_factory=list)
    min_courses: int | None = None
    caveat: str | None = None


# Transcribed from the Program Requirements table. Course codes are the bulletin's.
REQUIREMENTS: list[RequirementSpec] = [
    RequirementSpec(
        name="Management Core",
        kind=RequirementKind.core,
        rule="all_of",
        min_credits=12,
        courses=[
            "MASY1-GC 1015",  # Quantitative Methods for Business Analysis
            "MASY1-GC 1115",  # Management Skills for Technology Professionals
            "MASY1-GC 1215",  # Data-Driven Decision-Making
            "MASY1-GC 1315",  # Managing Change and Innovation
        ],
    ),
    RequirementSpec(
        name="Technical Core",
        kind=RequirementKind.core,
        rule="all_of",
        min_credits=12,
        courses=[
            "MASY1-GC 1500",  # Database Management
            "MASY1-GC 1600",  # Managing Technical Projects
            "MASY1-GC 1700",  # Organizational Risk Management and Information Security
            "MASY1-GC 1800",  # Emerging Technologies
        ],
    ),
    RequirementSpec(
        name="Concentration",
        kind=RequirementKind.elective,
        # Not a credit pool. One course from each of two concentrations is six credits and
        # completes neither; the bulletin says "select one of the following concentrations".
        rule="one_track",
        min_credits=6,
        tracks=[
            TrackSpec("Business Analytics", ["MASY1-GC 2000", "MASY1-GC 2100"]),
            TrackSpec("Risk Analytics", ["MASY1-GC 2200", "MASY1-GC 2300"]),
            TrackSpec("Business Informatics", ["MASY1-GC 2400", "MASY1-GC 2500"]),
            TrackSpec("Applied Research", ["MASY1-GC 2600", "MASY1-GC 2700"]),
        ],
        caveat="Students are required to select one of the following concentrations.",
    ),
    RequirementSpec(
        name="Electives",
        kind=RequirementKind.elective,
        rule="credits",
        min_credits=3,
        min_courses=1,
        courses=[
            "MASY1-GC 3030",  # Syntax Language Programming
            "MASY1-GC 3100",  # Application-Based Programming
            "MASY1-GC 3260",  # Advanced Data Warehousing Applications
            "MASY1-GC 3415",  # Special Topics in Management and Analytics
            "MASY1-GC 3910",  # Internship
        ],
        # The listed courses are not the whole story, and a planner that treats them as
        # closed would wrongly reject a legitimate choice. This is the cross-school
        # selective: the scope is wider than anything the catalog models.
        caveat=(
            "Students select one elective course. They may select a foundational course "
            "from any of the other concentrations or from any of the courses listed in "
            "this elective category, including the Internship course. Additionally, "
            "students may select a course offered within other graduate programs within "
            "the Division of Programs in Business, or the Real World Course "
            "(RWLD1-GC 3050). Courses outside this list cannot be verified here — confirm "
            "eligibility with your advisor and in Albert. Internship (MASY1-GC 3910) "
            "additionally requires a minimum of 18 completed credits and a minimum GPA "
            "of 3.0 to be eligible to apply."
        ),
    ),
    RequirementSpec(
        name="Capstone",
        kind=RequirementKind.capstone,
        rule="all_of",
        min_credits=3,
        courses=["MASY1-GC 4115"],  # Applied Technical Project
    ),
]


def page_provenance() -> tuple[str, datetime]:
    page = json.loads((SECTIONS_DIR / f"{PAGE_SLUG}.json").read_text(encoding="utf-8"))
    return page["url"], datetime.fromisoformat(page["fetched_at"])


def validate(session) -> list[str]:
    """Every referenced course must exist, and the credits must sum to the stated total."""
    problems: list[str] = []

    codes = {c for spec in REQUIREMENTS for c in spec.courses}
    codes |= {c for spec in REQUIREMENTS for t in spec.tracks for c in t.courses}
    known = {
        row.code
        for row in session.scalars(
            select(Course).where(Course.source == "catalog", Course.code.in_(codes))
        )
    }
    for code in sorted(codes - known):
        problems.append(f"course not in catalog: {code}")

    for spec in REQUIREMENTS:
        if spec.rule == "one_track":
            for track in spec.tracks:
                credits = sum(
                    session.scalar(select(Course.credits).where(Course.code == c)) or 0
                    for c in track.courses
                )
                if credits != spec.min_credits:
                    problems.append(
                        f"{spec.name}/{track.name}: {credits} credits, requirement says "
                        f"{spec.min_credits}"
                    )
        elif spec.rule == "all_of":
            credits = sum(
                session.scalar(select(Course.credits).where(Course.code == c)) or 0
                for c in spec.courses
            )
            if credits != spec.min_credits:
                problems.append(
                    f"{spec.name}: listed courses total {credits}, requirement says "
                    f"{spec.min_credits}"
                )

    total = sum(spec.min_credits for spec in REQUIREMENTS)
    if total != TOTAL_CREDITS:
        problems.append(f"requirements sum to {total}, bulletin states {TOTAL_CREDITS}")

    return problems


def write(session) -> tuple[int, int]:
    url, verified_at = page_provenance()

    program = session.scalars(select(Program).where(Program.code == PROGRAM_CODE)).first()
    if program is None:
        program = Program(code=PROGRAM_CODE)
        session.add(program)
    program.name = PROGRAM_NAME
    program.degree = "MS"
    program.school = "School of Professional Studies"
    program.total_credits_required = TOTAL_CREDITS
    program.source = "catalog"
    program.catalog_url = url
    program.catalog_verified_at = verified_at
    session.flush()

    for existing in session.scalars(
        select(Requirement).where(Requirement.program_id == program.id)
    ):
        session.delete(existing)
    session.flush()

    by_code = {
        row.code: row
        for row in session.scalars(select(Course).where(Course.source == "catalog"))
    }

    tracks_written = 0
    for order, spec in enumerate(REQUIREMENTS, start=1):
        requirement = Requirement(
            program_id=program.id,
            name=spec.name,
            kind=spec.kind,
            rule=spec.rule,
            min_credits=spec.min_credits,
            min_courses=spec.min_courses,
            sort_order=order,
            caveat=spec.caveat,
            source_url=url,
            source_verified_at=verified_at,
        )
        session.add(requirement)
        session.flush()

        requirement.courses = [by_code[c] for c in spec.courses if c in by_code]

        for track_order, track in enumerate(spec.tracks, start=1):
            row = RequirementTrack(
                requirement_id=requirement.id, name=track.name, sort_order=track_order
            )
            session.add(row)
            session.flush()
            row.courses = [by_code[c] for c in track.courses if c in by_code]
            tracks_written += 1

    session.commit()
    return len(REQUIREMENTS), tracks_written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with get_sessionmaker()() as session:
        problems = validate(session)
        print(f"{PROGRAM_NAME} — {TOTAL_CREDITS} credits, {len(REQUIREMENTS)} requirements")
        for spec in REQUIREMENTS:
            detail = (
                f"{len(spec.tracks)} tracks"
                if spec.tracks
                else f"{len(spec.courses)} courses"
            )
            print(f"  {spec.name:<18} {spec.rule:<10} {spec.min_credits:>2}cr  {detail}")

        if problems:
            print(f"\nVALIDATION FAILED ({len(problems)}):")
            for problem in problems:
                print(f"  ! {problem}")
            raise SystemExit(1)
        print("\nvalidation passed: every course exists, credits reconcile to 36")

        if args.dry_run:
            print("dry run: nothing written")
            return

        requirements, tracks = write(session)
        print(f"wrote {requirements} requirements, {tracks} concentration tracks")


if __name__ == "__main__":
    main()
