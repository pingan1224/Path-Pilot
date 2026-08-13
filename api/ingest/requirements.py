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


@dataclass
class TrackSpec:
    name: str
    courses: list[str]
    # How many of `courses` complete the track. None means all of them — Management &
    # Analytics states each concentration as two courses and requires both. Financial
    # Planning lists five and asks for three, so its courses are a pool.
    min_courses: int | None = None

    @property
    def required_count(self) -> int:
        return self.min_courses or len(self.courses)


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


@dataclass
class ProgramSpec:
    page_slug: str
    code: str
    name: str
    total_credits: int
    requirements: list[RequirementSpec]


# Transcribed from the Program Requirements table. Course codes are the bulletin's.
MANAGEMENT_ANALYTICS: list[RequirementSpec] = [
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


# The second programme, and the one that showed the engine what it could not yet say.
# Management & Analytics states each concentration as two courses and requires both, so
# "complete the track" and "complete every course in the track" were the same sentence.
# Financial Planning lists five per concentration and asks for three. Encoding that as the
# old shape would have told a student they owed two courses they do not.
FINANCIAL_PLANNING: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Curriculum",
        kind=RequirementKind.core,
        rule="all_of",
        min_credits=18,
        courses=[
            "MSFP1-GC 1000",  # Financial Planning Analysis and Risk Management
            "MSFP1-GC 1005",  # Investment and Wealth Management
            "MSFP1-GC 1010",  # Income Taxation and Strategy
            "MSFP1-GC 1015",  # Retirement Planning Strategies
            "MSFP1-GC 1020",  # Estates, Gifts, and Trusts
            "MSFP1-GC 1025",  # Research Applications in Financial Planning
        ],
    ),
    RequirementSpec(
        name="Concentration",
        kind=RequirementKind.elective,
        rule="one_track",
        min_credits=9,
        tracks=[
            TrackSpec(
                "Financial Analytics",
                [
                    "MSFP1-GC 2015",  # Applied Statistics
                    "MSFP1-GC 2020",  # Investment Data Analytics
                    "MSFP1-GC 2025",  # Personal Finance Analytics
                    "MSFP1-GC 2100",  # Internship
                    "MSFP1-GC 2200",  # Special Topic
                ],
                min_courses=3,
            ),
            TrackSpec(
                "Behavioral Finance",
                [
                    "MSFP1-GC 2000",  # Applied Behavioral Finance
                    "MSFP1-GC 2005",  # Communication for the Professional Engagement
                    "MSFP1-GC 2010",  # Money and Relationships
                    "MSFP1-GC 2100",  # Internship
                    "MSFP1-GC 2200",  # Special Topic
                ],
                min_courses=3,
            ),
        ],
        # Internship and Special Topic appear under both concentrations. That is the
        # bulletin's own layout, not a transcription slip, and it means a student holding
        # only those two has not committed to either — which the "spread across tracks"
        # reading already handles, since neither reaches three.
        caveat=(
            "Select one of the following concentrations and complete three courses. "
            "Internship (MSFP1-GC 2100) and Special Topic (MSFP1-GC 2200) are listed under "
            "both concentrations; which one they count toward is a question for your "
            "advisor."
        ),
    ),
    RequirementSpec(
        name="Capstone",
        kind=RequirementKind.capstone,
        rule="all_of",
        min_credits=3,
        courses=["MSFP1-GC 4000"],  # Capstone
    ),
]


PROGRAMS: list[ProgramSpec] = [
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__management-analytics-ms",
        code="MASY-MS-REAL",
        name="Management and Analytics",
        total_credits=36,
        requirements=MANAGEMENT_ANALYTICS,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__financial-planning-ms",
        code="MSFP-MS-REAL",
        name="Financial Planning",
        total_credits=30,
        requirements=FINANCIAL_PLANNING,
    ),
]


def page_provenance(page_slug: str) -> tuple[str, datetime]:
    page = json.loads((SECTIONS_DIR / f"{page_slug}.json").read_text(encoding="utf-8"))
    return page["url"], datetime.fromisoformat(page["fetched_at"])


def validate(session, program: ProgramSpec) -> list[str]:
    """Every referenced course must exist, and the credits must sum to the stated total."""
    problems: list[str] = []
    requirements = program.requirements

    codes = {c for spec in requirements for c in spec.courses}
    codes |= {c for spec in requirements for t in spec.tracks for c in t.courses}
    known = {
        row.code
        for row in session.scalars(
            select(Course).where(Course.source == "catalog", Course.code.in_(codes))
        )
    }
    for code in sorted(codes - known):
        problems.append(f"course not in catalog: {code}")

    def credits_of(code: str) -> int:
        return session.scalar(select(Course.credits).where(Course.code == code)) or 0

    for spec in requirements:
        if spec.rule == "one_track":
            for track in spec.tracks:
                # A pool track lists more courses than it needs, so summing all of them
                # would fail a correct transcription. What has to reconcile is the credits
                # of the number actually required. Mixed-credit pools would make that
                # ambiguous; asserting they are uniform is what keeps this check meaningful.
                per_course = {credits_of(c) for c in track.courses}
                if len(per_course) > 1:
                    problems.append(
                        f"{spec.name}/{track.name}: pool mixes credit values {sorted(per_course)}, "
                        "so a course count cannot be reconciled against a credit total"
                    )
                    continue
                credits = per_course.pop() * track.required_count if per_course else 0
                if credits != spec.min_credits:
                    problems.append(
                        f"{spec.name}/{track.name}: {track.required_count} course(s) is "
                        f"{credits} credits, requirement says {spec.min_credits}"
                    )
        elif spec.rule == "all_of":
            credits = sum(credits_of(c) for c in spec.courses)
            if credits != spec.min_credits:
                problems.append(
                    f"{spec.name}: listed courses total {credits}, requirement says "
                    f"{spec.min_credits}"
                )

    total = sum(spec.min_credits for spec in requirements)
    if total != program.total_credits:
        problems.append(
            f"requirements sum to {total}, bulletin states {program.total_credits}"
        )

    return problems


def write(session, spec_program: ProgramSpec) -> tuple[int, int]:
    url, verified_at = page_provenance(spec_program.page_slug)

    program = session.scalars(
        select(Program).where(Program.code == spec_program.code)
    ).first()
    if program is None:
        program = Program(code=spec_program.code)
        session.add(program)
    program.name = spec_program.name
    program.degree = "MS"
    program.school = "School of Professional Studies"
    program.total_credits_required = spec_program.total_credits
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
    for order, spec in enumerate(spec_program.requirements, start=1):
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
                requirement_id=requirement.id,
                name=track.name,
                sort_order=track_order,
                min_courses=track.min_courses,
            )
            session.add(row)
            session.flush()
            row.courses = [by_code[c] for c in track.courses if c in by_code]
            tracks_written += 1

    session.commit()
    return len(spec_program.requirements), tracks_written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", help="encode a single programme by code")
    args = parser.parse_args()

    targets = [p for p in PROGRAMS if not args.only or p.code == args.only]
    if not targets:
        raise SystemExit(f"no programme matches {args.only!r}")

    with get_sessionmaker()() as session:
        failed = False
        for spec_program in targets:
            problems = validate(session, spec_program)
            print(
                f"\n{spec_program.name} — {spec_program.total_credits} credits, "
                f"{len(spec_program.requirements)} requirements"
            )
            for spec in spec_program.requirements:
                if spec.tracks:
                    detail = "; ".join(
                        f"{t.name} {t.required_count}/{len(t.courses)}" for t in spec.tracks
                    )
                else:
                    detail = f"{len(spec.courses)} courses"
                print(f"  {spec.name:<18} {spec.rule:<10} {spec.min_credits:>2}cr  {detail}")

            if problems:
                print(f"  VALIDATION FAILED ({len(problems)}):")
                for problem in problems:
                    print(f"    ! {problem}")
                failed = True
                continue
            print(
                f"  validation passed: every course exists, credits reconcile to "
                f"{spec_program.total_credits}"
            )

            if args.dry_run:
                continue
            requirements, tracks = write(session, spec_program)
            print(f"  wrote {requirements} requirements, {tracks} concentration tracks")

        if failed:
            raise SystemExit(1)
        if args.dry_run:
            print("\ndry run: nothing written")


if __name__ == "__main__":
    main()
