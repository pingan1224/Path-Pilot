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
    # Courses the track requires by name, on top of the pool draw.
    required: list[str] = field(default_factory=list)

    @property
    def pool_count(self) -> int:
        return self.min_courses or len(self.courses)

    @property
    def required_count(self) -> int:
        return len(self.required) + self.pool_count


@dataclass
class RequirementSpec:
    name: str
    kind: RequirementKind
    rule: str
    min_credits: float
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


# The third programme, and the one that showed which shapes do *not* need new machinery.
#
# Its electives are five courses drawn from thirty-eight. That is a closed list, but naming
# five of thirty-eight would be the tool choosing a degree plan rather than reporting one, so
# it stays a `credits` requirement: the audit counts what the student has actually taken from
# the list, and the sequence carries the credits as a placeholder. The pool machinery added
# for Financial Planning is deliberately not used here — a surplus of two is a description,
# a surplus of thirty-three is a recommendation nobody asked for.
#
# Its capstone is "thesis or practicum", which is `one_track` with one course per track. No
# new rule; the existing "pick one path and finish it" already says exactly that.
GLOBAL_SECURITY: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Curriculum",
        kind=RequirementKind.core,
        rule="all_of",
        min_credits=18,
        courses=[
            "GLOB1-GC 2510",  # Cyberspace: Technical, Operational, and Strategic Perspectives
            "GSCC1-GC 1005",  # Cyber Law
            "GSCC1-GC 1010",  # National & International Cyber Organizations
            "GSCC1-GC 1015",  # Cyberpower & Global Security
            "GSCC1-GC 1020",  # Infrastructure Security & Resilience
            "GSCC1-GC 1030",  # Mission Assurance or Continuity of Operations
        ],
    ),
    RequirementSpec(
        name="Electives",
        kind=RequirementKind.elective,
        rule="credits",
        min_credits=15,
        min_courses=5,
        courses=[
            "GSCC1-GC 1007", "GSCC1-GC 1031", "GSCC1-GC 2010", "GSCC1-GC 2020",
            "GSCC1-GC 2025", "GSCC1-GC 2030", "GSCC1-GC 2035", "GSCC1-GC 2220",
            "GSCC1-GC 2225", "GSCC1-GC 2235", "GSCC1-GC 2245", "GSCC1-GC 2500",
            "GSCC1-GC 2530", "GSCC1-GC 2900", "GLOB1-GC 1000", "GLOB1-GC 2000",
            "GLOB1-GC 2047", "GLOB1-GC 2051", "GLOB1-GC 2055", "GLOB1-GC 2065",
            "GLOB1-GC 2070", "GLOB1-GC 2080", "GLOB1-GC 2151", "GLOB1-GC 2425",
            "GLOB1-GC 2493", "GLOB1-GC 2515", "GLOB1-GC 2516", "GLOB1-GC 2518",
            "GLOB1-GC 2520", "GLOB1-GC 2600", "GLOB1-GC 2630", "GLOB1-GC 2645",
            "GLOB1-GC 2650", "GLOB1-GC 3035", "GLOB1-GC 3060", "GLOB1-GC 3064",
            "GLOB1-GC 3905", "GLOB1-GC 3915",
        ],
        caveat=(
            "Select five of the listed courses. Internship (GLOB1-GC 3905) and Independent "
            "Study (GLOB1-GC 3915) are published without a fixed credit value, so how much "
            "they contribute toward the 15 cannot be read from the catalog — confirm with "
            "your advisor and in Albert."
        ),
    ),
    RequirementSpec(
        name="Capstone, Thesis, or Practicum",
        kind=RequirementKind.capstone,
        rule="one_track",
        min_credits=3,
        tracks=[
            TrackSpec("Graduate Thesis or Capstone Project", ["GSCC1-GC 3900"]),
            TrackSpec("Cyber Practicum", ["GSCC1-GC 3000"]),
        ],
        caveat="The bulletin offers these as alternatives; complete one.",
    ),
]


ENTREPRENEURSHIP: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Curriculum", kind=RequirementKind.core, rule="all_of", min_credits=18,
        courses=[
            "ENTR1-GC 1100", "ENTR1-GC 1200", "ENTR1-GC 1300",
            "ENTR1-GC 1400", "ENTR1-GC 1500", "ENTR1-GC 1600",
        ],
    ),
    RequirementSpec(
        name="Elective Courses", kind=RequirementKind.elective, rule="credits",
        min_credits=9, min_courses=3,
        courses=[
            "ENTR1-GC 2100", "ENTR1-GC 2200", "ENTR1-GC 2300", "ENTR1-GC 2400",
            "ENTR1-GC 2500", "ENTR1-GC 2600", "ENTR1-GC 2700", "ENTR1-GC 9000",
        ],
        # The page also groups six of these into three named specialisations of two courses
        # each. They are presentation, not requirement — nothing says a specialisation must
        # be completed — so they are not encoded as tracks, which would invent a rule.
        caveat=(
            "Select 9 credits from the listed courses. The bulletin groups six of them into "
            "three optional specialisations (Social Innovation and Entrepreneurship, Family "
            "Business, Entrepreneurial Leadership) of two courses each; taking a "
            "specialisation in full is a choice, not a requirement."
        ),
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="all_of", min_credits=3,
        courses=["ENTR1-GC 3100", "ENTR1-GC 3200"],  # Launchpad I and II, 1.5 each
    ),
]


EVENT_MANAGEMENT: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Curriculum", kind=RequirementKind.core, rule="all_of", min_credits=16.5,
        courses=[
            "MSEM1-GC 1005", "MSEM1-GC 1010", "MSEM1-GC 1015", "MSEM1-GC 1020",
            "MSEM1-GC 1025", "MSEM1-GC 1030", "MSEM1-GC 1035",
        ],
    ),
    RequirementSpec(
        name="Internship", kind=RequirementKind.core, rule="all_of", min_credits=1.5,
        courses=["MSEM1-GC 1100"],
        caveat=(
            "Students with at least two years of relevant full-time work experience, or the "
            "part-time equivalent, may qualify for a waiver; waiving it allows an additional "
            "1.5 credits of electives. Whether you qualify is not something this tool can "
            "check — ask your adviser."
        ),
    ),
    RequirementSpec(
        name="Electives", kind=RequirementKind.elective, rule="credits", min_credits=15,
        # The union of the three published tracks. The bulletin says students may select
        # across all three rather than complete one, so these are a pool, not `one_track`.
        courses=[
            "MSEM1-GC 2000", "MSEM1-GC 2005", "MSEM1-GC 2010", "MSEM1-GC 2015",
            "TCSB1-GC 2140", "TCSB1-GC 2040", "TCSB1-GC 2010", "MSEM1-GC 2020",
            "MSEM1-GC 2025",
            "MSEM1-GC 2030", "MSEM1-GC 2035", "MSEM1-GC 2040", "MSEM1-GC 2045",
            "MSEM1-GC 2055", "MSEM1-GC 2050", "MSEM1-GC 2060",
        ],
        caveat=(
            "Select 15 credits across the Business Development, Sport Event Management and "
            "Event Operations tracks. Up to 6 credits may come from the MS in Tourism "
            "Management, the MS in Hospitality Industry Studies or related programmes in "
            "consultation with your adviser — those cannot be counted here. Current Issues "
            "in Events (MSEM1-GC 2050) is published as 1.5-3 credits, so how much it "
            "contributes is not fixed."
        ),
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="one_track", min_credits=3,
        tracks=[
            TrackSpec("Consulting Practicum", ["MSEM1-GC 3000"]),
            TrackSpec("Individual Thesis", ["MSEM1-GC 3005"]),
        ],
        caveat="The bulletin offers these as alternatives; complete one.",
    ),
]


EXECUTIVE_COACHING: list[RequirementSpec] = [
    # Every listed course is required; the page's "Module 1 / Module 2" headings order the
    # cohort's residencies rather than offering a choice, so they are presentation.
    RequirementSpec(
        name="Fundamental Core Requirements", kind=RequirementKind.core, rule="all_of",
        min_credits=27,
        courses=[
            "ECOC1-GC 1000", "ECOC1-GC 1010", "ECOC1-GC 1020", "ECOC1-GC 1030",
            "ECOC1-GC 1040", "ECOC1-GC 2010", "ECOC1-GC 2020", "ECOC1-GC 2030",
            "ECOC1-GC 2040", "ECOC1-GC 3010", "ECOC1-GC 3020",
        ],
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="all_of", min_credits=3,
        courses=["ECOC1-GC 4000"],
        caveat=(
            "The bulletin states this capstone's prerequisites as course titles rather than "
            "codes, so they are recorded but not checked here — see the course entry."
        ),
    ),
]


EXECUTIVE_MARKETING: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Requirements", kind=RequirementKind.core, rule="all_of", min_credits=21,
        courses=[
            "EMSC1-GC 10", "EMSC1-GC 20", "EMSC1-GC 30", "EMSC1-GC 40", "EMSC1-GC 50",
            "EMSC1-GC 60", "EMSC1-GC 70", "EMSC1-GC 80", "EMSC1-GC 90", "EMSC1-GC 100",
        ],
    ),
    RequirementSpec(
        name="Electives", kind=RequirementKind.elective, rule="credits",
        min_credits=6, min_courses=4,
        courses=[
            "EMSC1-GC 200", "EMSC1-GC 210", "EMSC1-GC 220",
            "EMSC1-GC 230", "EMSC1-GC 240", "EMSC1-GC 250",
        ],
        caveat="Select four electives from the listed courses.",
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="all_of", min_credits=3,
        courses=["EMSC1-GC 300"],
    ),
]


# The eighth programme, and the one the `required` field on a track was added for. Each of
# its eight concentrations is one named course plus five drawn from thirty-odd; folding the
# named course into the pool would let a student complete a concentration without the course
# it is built around.
#
# Two departures from the page's own layout, both deliberate:
#
# The bulletin lists the thesis inside the core table. It is carried here as a separate
# `capstone` requirement because that kind is what tells the sequence planner a capstone
# needs a term of its own; leaving it in the core would have the planner schedule a thesis
# alongside a full load.
#
# The elective pool is the union of all eight concentrations, which is what "additional
# credits from any of the concentrations" names. It therefore overlaps the concentration
# lists completely — see the caveat.
GLOBAL_AFFAIRS: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Requirements",
        kind=RequirementKind.core,
        rule="all_of",
        min_credits=12,
        courses=[
            "GLOB1-GC 1000",  # International Relations in The Post-Cold War Era
            "GLOB1-GC 1030",  # International Political Economy
            "GLOB1-GC 1040",  # International Law
            "GLOB1-GC 3035",  # Analytic Skills for Global Affairs
        ],
    ),
    RequirementSpec(
        name="Concentration",
        kind=RequirementKind.elective,
        rule="one_track",
        min_credits=18,
        tracks=[
            TrackSpec(
                "International Relations/Global Futures",
                [
                    "GLOB1-GC 1010", "GLOB1-GC 1020", "GLOB1-GC 1075", "GLOB1-GC 2000",
                    "GLOB1-GC 2010", "GLOB1-GC 2030", "GLOB1-GC 2040", "GLOB1-GC 2046",
                    "GLOB1-GC 2047", "GLOB1-GC 2051", "GLOB1-GC 2055", "GLOB1-GC 2065",
                    "GLOB1-GC 2070", "GLOB1-GC 2080", "GLOB1-GC 2245", "GLOB1-GC 2340",
                    "GLOB1-GC 2345", "GLOB1-GC 2385", "GLOB1-GC 2390", "GLOB1-GC 2405",
                    "GLOB1-GC 2410", "GLOB1-GC 2470", "GLOB1-GC 2494", "GLOB1-GC 2500",
                    "GLOB1-GC 2515", "GLOB1-GC 2516", "GLOB1-GC 2518", "GLOB1-GC 2610",
                    "GLOB1-GC 2620", "GLOB1-GC 2625", "GLOB1-GC 2630", "GLOB1-GC 2645",
                    "GLOB1-GC 2650", "GLOB1-GC 2670", "GLOB1-GC 3060", "GLOB1-GC 3061",
                    "GLOB1-GC 3075", "GLOB1-GC 3920",
                ],
                min_courses=5,
                required=["GLOB1-GC 2045"],
            ),
            TrackSpec(
                "Transnational Security",
                [
                    "GLOB1-GC 1010", "GLOB1-GC 1075", "GLOB1-GC 2005", "GLOB1-GC 2010",
                    "GLOB1-GC 2030", "GLOB1-GC 2040", "GLOB1-GC 2047", "GLOB1-GC 2051",
                    "GLOB1-GC 2055", "GLOB1-GC 2065", "GLOB1-GC 2070", "GLOB1-GC 2075",
                    "GLOB1-GC 2080", "GLOB1-GC 2115", "GLOB1-GC 2151", "GLOB1-GC 2205",
                    "GLOB1-GC 2215", "GLOB1-GC 2226", "GLOB1-GC 2245", "GLOB1-GC 2247",
                    "GLOB1-GC 2281", "GLOB1-GC 2293", "GLOB1-GC 2320", "GLOB1-GC 2330",
                    "GLOB1-GC 2405", "GLOB1-GC 2410", "GLOB1-GC 2470", "GLOB1-GC 2494",
                    "GLOB1-GC 2515", "GLOB1-GC 2516", "GLOB1-GC 2518", "GLOB1-GC 2520",
                    "GLOB1-GC 2525", "GLOB1-GC 2546", "GLOB1-GC 2590", "GLOB1-GC 2600",
                    "GLOB1-GC 2620", "GLOB1-GC 2625", "GLOB1-GC 2630", "GLOB1-GC 2645",
                    "GLOB1-GC 2650", "GLOB1-GC 3045", "GLOB1-GC 3064", "GLOB1-GC 3075",
                    "GLOB1-GC 3920", "GSCC1-GC 1015", "GSCC1-GC 1020", "GSCC1-GC 2020",
                    "GSCC1-GC 2225", "GSCC1-GC 2510", "GSCC1-GC 2530",
                ],
                min_courses=5,
                required=["GLOB1-GC 2000"],
            ),
            TrackSpec(
                "Global Economy",
                [
                    "GLOB1-GC 1020", "GLOB1-GC 2125", "GLOB1-GC 2130", "GLOB1-GC 2146",
                    "GLOB1-GC 2147", "GLOB1-GC 2151", "GLOB1-GC 2158", "GLOB1-GC 2180",
                    "GLOB1-GC 2226", "GLOB1-GC 2281", "GLOB1-GC 2292", "GLOB1-GC 2410",
                    "GLOB1-GC 2420", "GLOB1-GC 2425", "GLOB1-GC 2485", "GLOB1-GC 2490",
                    "GLOB1-GC 2494", "GLOB1-GC 2515", "GLOB1-GC 2516", "GLOB1-GC 2530",
                    "GLOB1-GC 2600", "GLOB1-GC 2610", "GLOB1-GC 2615", "GLOB1-GC 2620",
                    "GLOB1-GC 2625", "GLOB1-GC 2630", "GLOB1-GC 2645", "GLOB1-GC 2660",
                    "GLOB1-GC 3060", "GLOB1-GC 3061", "GLOB1-GC 3065", "GLOB1-GC 3920",
                    "GSCC1-GC 2030",
                ],
                min_courses=5,
                # The page states this one as "GLOB1-GC 2295 or GLOB1-GC 2130". A track can
                # name a required course but not an alternative between two, and inventing
                # the machinery for a single programme's single row is not worth it — 2130
                # is in the pool either way, so the caveat carries the choice.
                required=["GLOB1-GC 2295"],
            ),
            TrackSpec(
                "Human Rights and International Law",
                [
                    "GLOB1-GC 1010", "GLOB1-GC 2005", "GLOB1-GC 2035", "GLOB1-GC 2115",
                    "GLOB1-GC 2151", "GLOB1-GC 2205", "GLOB1-GC 2215", "GLOB1-GC 2275",
                    "GLOB1-GC 2320", "GLOB1-GC 2322", "GLOB1-GC 2340", "GLOB1-GC 2345",
                    "GLOB1-GC 2360", "GLOB1-GC 2385", "GLOB1-GC 2386", "GLOB1-GC 2390",
                    "GLOB1-GC 2425", "GLOB1-GC 2494", "GLOB1-GC 2510", "GLOB1-GC 2515",
                    "GLOB1-GC 2516", "GLOB1-GC 2535", "GLOB1-GC 2540", "GLOB1-GC 2545",
                    "GLOB1-GC 2590", "GLOB1-GC 2625", "GLOB1-GC 2630", "GLOB1-GC 2645",
                    "GLOB1-GC 2670", "GLOB1-GC 3045", "GLOB1-GC 3075", "GLOB1-GC 3920",
                ],
                min_courses=5,
                required=["GLOB1-GC 2240"],
            ),
            TrackSpec(
                "International Development and Humanitarian Assistance",
                [
                    "GLOB1-GC 1010", "GLOB1-GC 2035", "GLOB1-GC 2125", "GLOB1-GC 2146",
                    "GLOB1-GC 2151", "GLOB1-GC 2205", "GLOB1-GC 2215", "GLOB1-GC 2226",
                    "GLOB1-GC 2240", "GLOB1-GC 2251", "GLOB1-GC 2261", "GLOB1-GC 2275",
                    "GLOB1-GC 2281", "GLOB1-GC 2282", "GLOB1-GC 2292", "GLOB1-GC 2320",
                    "GLOB1-GC 2322", "GLOB1-GC 2330", "GLOB1-GC 2340", "GLOB1-GC 2345",
                    "GLOB1-GC 2350", "GLOB1-GC 2360", "GLOB1-GC 2385", "GLOB1-GC 2386",
                    "GLOB1-GC 2390", "GLOB1-GC 2425", "GLOB1-GC 2440", "GLOB1-GC 2470",
                    "GLOB1-GC 2494", "GLOB1-GC 2515", "GLOB1-GC 2516", "GLOB1-GC 2518",
                    "GLOB1-GC 2525", "GLOB1-GC 2540", "GLOB1-GC 2545", "GLOB1-GC 2546",
                    "GLOB1-GC 2550", "GLOB1-GC 2610", "GLOB1-GC 2620", "GLOB1-GC 2625",
                    "GLOB1-GC 2630", "GLOB1-GC 2645", "GLOB1-GC 2660", "GLOB1-GC 3045",
                    "GLOB1-GC 3064", "GLOB1-GC 3065", "GLOB1-GC 3075", "GLOB1-GC 3920",
                    "GSCC1-GC 2530",
                ],
                min_courses=5,
                required=["GLOB1-GC 1020"],
            ),
            TrackSpec(
                "Environment and Energy Policy",
                [
                    "GLOB1-GC 1075", "GLOB1-GC 2125", "GLOB1-GC 2130", "GLOB1-GC 2151",
                    "GLOB1-GC 2281", "GLOB1-GC 2292", "GLOB1-GC 2410", "GLOB1-GC 2412",
                    "GLOB1-GC 2420", "GLOB1-GC 2425", "GLOB1-GC 2440", "GLOB1-GC 2445",
                    "GLOB1-GC 2485", "GLOB1-GC 2490", "GLOB1-GC 2491", "GLOB1-GC 2494",
                    "GLOB1-GC 2515", "GLOB1-GC 2516", "GLOB1-GC 2518", "GLOB1-GC 2525",
                    "GLOB1-GC 2540", "GLOB1-GC 2546", "GLOB1-GC 2555", "GLOB1-GC 2615",
                    "GLOB1-GC 2620", "GLOB1-GC 2625", "GLOB1-GC 2630", "GLOB1-GC 2645",
                    "GLOB1-GC 3030", "GLOB1-GC 3060", "GLOB1-GC 3065", "GLOB1-GC 3920",
                    "GSCC1-GC 2530",
                ],
                min_courses=5,
                required=["GLOB1-GC 2430"],
            ),
            TrackSpec(
                "Peacebuilding",
                [
                    "GLOB1-GC 2005", "GLOB1-GC 2151", "GLOB1-GC 2215", "GLOB1-GC 2251",
                    "GLOB1-GC 2261", "GLOB1-GC 2275", "GLOB1-GC 2320", "GLOB1-GC 2350",
                    "GLOB1-GC 2380", "GLOB1-GC 2515", "GLOB1-GC 2518", "GLOB1-GC 2560",
                    "GLOB1-GC 2590", "GLOB1-GC 2595", "GLOB1-GC 2625", "GLOB1-GC 2630",
                    "GLOB1-GC 2645", "GLOB1-GC 2675", "GLOB1-GC 3045", "GLOB1-GC 3075",
                ],
                min_courses=5,
                required=["GLOB1-GC 1010"],
            ),
            TrackSpec(
                "Global Gender Studies",
                [
                    "GLOB1-GC 1010", "GLOB1-GC 1075", "GLOB1-GC 2035", "GLOB1-GC 2130",
                    "GLOB1-GC 2151", "GLOB1-GC 2240", "GLOB1-GC 2251", "GLOB1-GC 2261",
                    "GLOB1-GC 2281", "GLOB1-GC 2282", "GLOB1-GC 2322", "GLOB1-GC 2330",
                    "GLOB1-GC 2360", "GLOB1-GC 2385", "GLOB1-GC 2386", "GLOB1-GC 2390",
                    "GLOB1-GC 2425", "GLOB1-GC 2430", "GLOB1-GC 2470", "GLOB1-GC 2492",
                    "GLOB1-GC 2515", "GLOB1-GC 2516", "GLOB1-GC 2518", "GLOB1-GC 2630",
                    "GLOB1-GC 2645", "GLOB1-GC 2660", "GLOB1-GC 3045", "GLOB1-GC 3075",
                    "GLOB1-GC 3920", "GSCC1-GC 2025", "GSCC1-GC 2530",
                ],
                min_courses=5,
                required=["GLOB1-GC 2340"],
            ),
        ],
        caveat=(
            "Select one of the eight concentrations, take its required course, and select "
            "five of its listed elective courses. Concentration electives are subject to "
            "change and not all are offered every semester. The Global Economy "
            "concentration's required course may be satisfied by either Fundamentals of "
            "Corporate Finance (GLOB1-GC 2295) or The Integration of Profit & Purpose "
            "(GLOB1-GC 2130); only the first is checked here, so if you are taking 2130 in "
            "its place, confirm with your advisor. Many courses appear under several "
            "concentrations, so holding one does not by itself indicate which concentration "
            "you are pursuing."
        ),
    ),
    RequirementSpec(
        name="Electives",
        kind=RequirementKind.elective,
        rule="credits",
        min_credits=9,
        min_courses=3,
        # "From any of the concentrations" — so the pool is their union, which is also why
        # every course here appears in the concentration requirement above.
        courses=[
            "GLOB1-GC 1010", "GLOB1-GC 1020", "GLOB1-GC 1075", "GLOB1-GC 2000",
            "GLOB1-GC 2005", "GLOB1-GC 2010", "GLOB1-GC 2030", "GLOB1-GC 2035",
            "GLOB1-GC 2040", "GLOB1-GC 2045", "GLOB1-GC 2046", "GLOB1-GC 2047",
            "GLOB1-GC 2051", "GLOB1-GC 2055", "GLOB1-GC 2065", "GLOB1-GC 2070",
            "GLOB1-GC 2075", "GLOB1-GC 2080", "GLOB1-GC 2115", "GLOB1-GC 2125",
            "GLOB1-GC 2130", "GLOB1-GC 2146", "GLOB1-GC 2147", "GLOB1-GC 2151",
            "GLOB1-GC 2158", "GLOB1-GC 2180", "GLOB1-GC 2205", "GLOB1-GC 2215",
            "GLOB1-GC 2226", "GLOB1-GC 2240", "GLOB1-GC 2245", "GLOB1-GC 2247",
            "GLOB1-GC 2251", "GLOB1-GC 2261", "GLOB1-GC 2275", "GLOB1-GC 2281",
            "GLOB1-GC 2282", "GLOB1-GC 2292", "GLOB1-GC 2293", "GLOB1-GC 2295",
            "GLOB1-GC 2320", "GLOB1-GC 2322", "GLOB1-GC 2330", "GLOB1-GC 2340",
            "GLOB1-GC 2345", "GLOB1-GC 2350", "GLOB1-GC 2360", "GLOB1-GC 2380",
            "GLOB1-GC 2385", "GLOB1-GC 2386", "GLOB1-GC 2390", "GLOB1-GC 2405",
            "GLOB1-GC 2410", "GLOB1-GC 2412", "GLOB1-GC 2420", "GLOB1-GC 2425",
            "GLOB1-GC 2430", "GLOB1-GC 2440", "GLOB1-GC 2445", "GLOB1-GC 2470",
            "GLOB1-GC 2485", "GLOB1-GC 2490", "GLOB1-GC 2491", "GLOB1-GC 2492",
            "GLOB1-GC 2494", "GLOB1-GC 2500", "GLOB1-GC 2510", "GLOB1-GC 2515",
            "GLOB1-GC 2516", "GLOB1-GC 2518", "GLOB1-GC 2520", "GLOB1-GC 2525",
            "GLOB1-GC 2530", "GLOB1-GC 2535", "GLOB1-GC 2540", "GLOB1-GC 2545",
            "GLOB1-GC 2546", "GLOB1-GC 2550", "GLOB1-GC 2555", "GLOB1-GC 2560",
            "GLOB1-GC 2590", "GLOB1-GC 2595", "GLOB1-GC 2600", "GLOB1-GC 2610",
            "GLOB1-GC 2615", "GLOB1-GC 2620", "GLOB1-GC 2625", "GLOB1-GC 2630",
            "GLOB1-GC 2645", "GLOB1-GC 2650", "GLOB1-GC 2660", "GLOB1-GC 2670",
            "GLOB1-GC 2675", "GLOB1-GC 3030", "GLOB1-GC 3045", "GLOB1-GC 3060",
            "GLOB1-GC 3061", "GLOB1-GC 3064", "GLOB1-GC 3065", "GLOB1-GC 3075",
            "GLOB1-GC 3920", "GSCC1-GC 1015", "GSCC1-GC 1020", "GSCC1-GC 2020",
            "GSCC1-GC 2025", "GSCC1-GC 2030", "GSCC1-GC 2225", "GSCC1-GC 2510",
            "GSCC1-GC 2530",
        ],
        caveat=(
            "Select up to 9 additional credits from any of the concentrations. These are "
            "courses beyond the six that make up your concentration; because the same "
            "courses appear in both lists, which of them count here rather than toward the "
            "concentration is a question for your advisor. With the approval of your faculty "
            "advisor or the program director you may instead take a maximum of two courses "
            "from NYU's Wagner Graduate School of Public Service or elsewhere within NYU — "
            "those are outside this catalog and cannot be checked here."
        ),
    ),
    RequirementSpec(
        name="Capstone",
        kind=RequirementKind.capstone,
        rule="all_of",
        min_credits=3,
        courses=["GLOB1-GC 3900"],  # Graduate Thesis or Capstone Project
    ),
]


# Every listed course is required; the page's three headings group them rather than offer
# a choice. Two of the eleven major courses are 1.5 credits — Sports Finance I and II are a
# split course — which is what makes the major 30 rather than 33.
GLOBAL_SPORT: list[RequirementSpec] = [
    RequirementSpec(
        name="Major Requirements", kind=RequirementKind.core, rule="all_of", min_credits=30,
        courses=[
            "GLSP1-GC 1000", "GLSP1-GC 1005", "TCSB1-GC 2085", "GLSP1-GC 1010",
            "GLSP1-GC 1015", "GLSP1-GC 1020", "GLSP1-GC 1025", "TCSB1-GC 1040",
            "GLSP1-GC 1030", "GLSP1-GC 1035", "GLSP1-GC 1040",
        ],
    ),
    RequirementSpec(
        name="Seminar", kind=RequirementKind.core, rule="all_of", min_credits=3,
        courses=["GLSP1-GC 1045"],  # Seminar in Sports Leadership
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="all_of", min_credits=3,
        courses=["GLSP1-GC 3000"],  # Capstone in Global Sport
    ),
]


PROJECT_MANAGEMENT: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Requirements", kind=RequirementKind.core, rule="all_of", min_credits=18,
        courses=[
            "MSPM1-GC 1000", "MSPM1-GC 1005", "MSPM1-GC 1010",
            "MSPM1-GC 1015", "MSPM1-GC 1020", "MSPM1-GC 1025",
        ],
    ),
    RequirementSpec(
        name="Specialization Courses", kind=RequirementKind.elective, rule="credits",
        min_credits=15, min_courses=5,
        courses=[
            "MSPM1-GC 2000", "MSPM1-GC 2010", "MSPM1-GC 2020", "MSPM1-GC 2030",
            "MSPM1-GC 2040", "MSPM1-GC 3000", "MSPM1-GC 3910",
        ],
        # Seven listed and five required, but the footnote opens the set beyond the page, so
        # this is a credit pool rather than a track: naming five would close a set the
        # bulletin deliberately leaves open.
        caveat=(
            "Select five of the listed courses, including the Internship if you wish. With "
            "departmental approval you may instead take a course from another graduate "
            "program in the Division of Programs in Business, or the Real World Course "
            "(RWLD1-GC 3050) — those are outside this catalog and cannot be checked here. "
            "The Internship (MSPM1-GC 3910) additionally requires 18 completed credits and "
            "a minimum GPA of 3.0 to be eligible to apply."
        ),
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="all_of", min_credits=3,
        courses=["MSPM1-GC 4000"],  # Enterprise Project Management
    ),
]


# "Select six of the following: 9" reads as a contradiction until you check the catalogue:
# every course in this pool is 1.5 credits, so six of them is nine. The core mixes 3s and
# 1.5s for the same reason.
HUMAN_CAPITAL_ANALYTICS: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Requirements", kind=RequirementKind.core, rule="all_of", min_credits=18,
        courses=[
            "HCAT1-GC 1000", "HCAT1-GC 1005", "HCAT1-GC 1010", "HCAT1-GC 1015",
            "HCAT1-GC 1020", "HCAT1-GC 1025", "HRCM1-GC 1210",
        ],
    ),
    RequirementSpec(
        name="Electives", kind=RequirementKind.elective, rule="credits",
        min_credits=9, min_courses=6,
        courses=[
            "HCAT1-GC 2000", "HCAT1-GC 2005", "HCAT1-GC 2010",
            "HCAT1-GC 2015", "HCAT1-GC 2020", "HCAT1-GC 2025", "HCAT1-GC 2030",
        ],
        caveat=(
            "Select six of the seven listed courses. The Internship (HCAT1-GC 2030) "
            "additionally requires 18 completed credits and a minimum GPA of 3.0 to be "
            "eligible to apply."
        ),
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="all_of", min_credits=3,
        courses=["HCAT1-GC 3000"],  # Capstone Project
    ),
]


PROFESSIONAL_WRITING: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Requirements", kind=RequirementKind.core, rule="all_of", min_credits=18,
        courses=[
            "PWRT1-GC 1000", "PWRT1-GC 1005", "PWRT1-GC 1010",
            "PWRT1-GC 1015", "PWRT1-GC 1020", "PWRT1-GC 1025",
        ],
    ),
    RequirementSpec(
        name="Electives", kind=RequirementKind.elective, rule="credits",
        min_credits=12, min_courses=4,
        courses=[
            "PWRT1-GC 3000", "PWRT1-GC 3005", "PWRT1-GC 3010", "PWRT1-GC 3015",
            "PWRT1-GC 3020", "PWRT1-GC 3025", "PWRT1-GC 3030", "PWRT1-GC 1011",
            "PWRT1-GC 1021", "PWRT1-GC 3035", "PWRT1-GC 3040",
        ],
        caveat="Select four of the listed courses.",
    ),
    # The page files both of these under one "Additional Major Requirements" heading. They
    # are separated here because they are different rules: the portfolio is fixed and is the
    # degree's capstone, the other is a choice between two courses.
    RequirementSpec(
        name="Portfolio/Thesis", kind=RequirementKind.capstone, rule="all_of", min_credits=3,
        courses=["PWRT1-GC 3900"],  # Portfolio/Thesis Requirement
    ),
    RequirementSpec(
        name="Internship or Directed Study", kind=RequirementKind.core, rule="one_track",
        min_credits=3,
        tracks=[
            TrackSpec("Internship", ["PWRT1-GC 3905"]),
            TrackSpec("Directed Study", ["PWRT1-GC 3910"]),
        ],
        caveat=(
            "Complete either a professional internship or a mock-freelance directed study."
        ),
    ),
]


HUMAN_CAPITAL_MANAGEMENT: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Requirements", kind=RequirementKind.core, rule="all_of", min_credits=21,
        courses=[
            "HRCM1-GC 1300", "HRCM1-GC 1210", "HRCM1-GC 1240", "HRCM1-GC 1310",
            "HRCM1-GC 1320", "HRCM1-GC 1330", "HRCM1-GC 2025", "HRCM1-GC 2015",
            "HRCM1-GC 2200",
        ],
    ),
    RequirementSpec(
        name="Electives", kind=RequirementKind.elective, rule="credits", min_credits=6,
        # No `min_courses`. This pool mixes 1.5- and 3-credit courses, so six credits is two
        # courses or four depending on which; stating a count would be inventing one.
        courses=[
            "HRCM1-GC 1220", "HRCM1-GC 1900", "HRCM1-GC 2210", "HRCM1-GC 2220",
            "HRCM1-GC 2230", "HRCM1-GC 2240", "HRCM1-GC 2310", "HRCM1-GC 2340",
            "HRCM1-GC 2350", "HRCM1-GC 2400", "HRCM1-GC 3021", "HRCM1-GC 3022",
            "HRCM1-GC 3207", "HRCM1-GC 3500", "HRCM1-GC 3510", "HRCM1-GC 3550",
            "HCAT1-GC 2010", "HCAT1-GC 2025",
        ],
        # A dependency between two requirements, which nothing in the rule vocabulary can
        # express: the elective you must take is decided by the capstone you pick.
        caveat=(
            "Select 6 credits from the listed courses. These range from 1.5 to 3 credits "
            "each, so how many courses that is depends on which you choose. Students who "
            "choose the Thesis capstone (HRCM1-GC 1901) must take Research Process & "
            "Methodology (HRCM1-GC 1900) as one of these electives — a link between the two "
            "requirements that this tool does not check."
        ),
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="one_track", min_credits=3,
        tracks=[
            TrackSpec("Research Project: Thesis", ["HRCM1-GC 1901"]),
            TrackSpec("Special Project: Applied Human Resource Strategies", ["HRCM1-GC 4000"]),
            TrackSpec("Capstone Applied Project", ["HRCM1-GC 5000"]),
        ],
        caveat="The bulletin offers these as alternatives; complete one.",
    ),
]


TRANSLATION_INTERPRETING: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Courses", kind=RequirementKind.core, rule="all_of", min_credits=18,
        courses=[
            "TRAN1-GC 1000", "TRAN1-GC 1010", "TRAN1-GC 1020",
            "TRAN1-GC 3015", "TRAN1-GC 3045", "TRAN1-GC 3356",
        ],
    ),
    RequirementSpec(
        name="Electives", kind=RequirementKind.elective, rule="credits",
        min_credits=15, min_courses=5,
        courses=[
            "TRAN1-GC 3010", "TRAN1-GC 3025", "TRAN1-GC 3035", "TRAN1-GC 3195",
            "TRAN1-GC 3390", "TRAN1-GC 3401", "TRAN1-GC 3403", "TRAN1-GC 3406",
            "TRAN1-GC 3510", "TRAN1-GC 3520", "TRAN1-GC 3525", "TRAN1-GC 3530",
            "TRAN1-GC 3535", "TRAN1-GC 3540", "TRAN1-GC 3550", "TRAN1-GC 3900",
            "TRAN1-GC 4010", "TRAN1-GC 1115",
        ],
        caveat="Select five of the listed courses.",
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="all_of", min_credits=3,
        courses=["TRAN1-GC 4000"],  # Thesis Project
    ),
]


SPORTS_BUSINESS: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Requirements", kind=RequirementKind.core, rule="all_of", min_credits=18,
        courses=[
            "TCSB1-GC 1040", "TCSB1-GC 1050", "TCSB1-GC 1060",
            "TCSB1-GC 1080", "TCSB1-GC 2085", "TCSB1-GC 2160",
        ],
    ),
    RequirementSpec(
        name="Electives", kind=RequirementKind.elective, rule="credits",
        min_credits=15, min_courses=5,
        courses=[
            "TCSB1-GC 1010", "TCSB1-GC 2010", "TCSB1-GC 2015", "TCSB1-GC 2025",
            "TCSB1-GC 2040", "TCSB1-GC 2045", "TCSB1-GC 2055", "TCSB1-GC 2090",
            "TCSB1-GC 2975", "TCSB1-GC 2050", "TCSB1-GC 2070", "TCSB1-GC 2130",
            "TCSB1-GC 2095", "TCSB1-GC 2140", "TCSB1-GC 2150", "TCSB1-GC 3045",
            "TCSB1-GC 2190", "TCSB1-GC 2195", "TCSB1-GC 2180", "TCSB1-GC 1090",
            "RWLD1-GC 3050", "TCSB1-GC 2005", "TCSB1-GC 2170", "TCSB1-GC 3900",
        ],
        caveat=(
            "Select 15 credits from the listed courses, or from other NYU SPS graduate "
            "programs with adviser approval — courses outside this list cannot be checked "
            "here."
        ),
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="all_of", min_credits=3,
        courses=["TCSB1-GC 3000"],  # Sports Business Capstone
    ),
]


# Travel and Tourism and Global Hospitality are sibling degrees from the same department and
# have the same shape: a 16.5-credit core that already contains the internship, 18 credits of
# electives, and a 1.5-credit Leadership course the page files under "Capstone". Both elective
# pools mix 1.5 and 3 credit courses and each contains one course published with no fixed
# credit value at all, so neither can state a course count.
TRAVEL_TOURISM: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Requirements", kind=RequirementKind.core, rule="all_of", min_credits=16.5,
        courses=[
            "TCTM1-GC 3350", "TCTM1-GC 3650", "TCTM1-GC 3560", "TCTM1-GC 3705",
            "TCTM1-GC 3340", "TCTM1-GC 3520", "TCTM1-GC 3920",
        ],
    ),
    RequirementSpec(
        name="Electives", kind=RequirementKind.elective, rule="credits", min_credits=18,
        courses=[
            "TCTM1-GC 1040", "TCTM1-GC 3245", "TCTM1-GC 3205", "TCTM1-GC 3250",
            "TCTM1-GC 3260", "TCTM1-GC 3265", "TCTM1-GC 3605", "TCTM1-GC 3120",
            "TCTM1-GC 3545", "TCTM1-GC 3370", "TCTM1-GC 3105", "TCTM1-GC 3115",
            "TCTM1-GC 1060", "TCTM1-GC 3320", "TCTM1-GC 3345", "TCTM1-GC 3925",
            "TCTM1-GC 4000", "TCTM1-GC 3900",
        ],
        caveat=(
            "Select 18 credits from the listed courses. They range from 1.5 to 3 credits "
            "each, so how many courses that is depends on which you choose, and Special "
            "Topics (TCTM1-GC 3925) is published without a fixed credit value — how much it "
            "contributes cannot be read from the catalog."
        ),
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="all_of", min_credits=1.5,
        courses=["TCTM1-GC 1015"],  # Leadership
    ),
]


GLOBAL_HOSPITALITY: list[RequirementSpec] = [
    RequirementSpec(
        name="Core Requirements", kind=RequirementKind.core, rule="all_of", min_credits=16.5,
        courses=[
            "TCHS1-GC 1005", "TCHS1-GC 1015", "TCHS1-GC 1020", "TCHS1-GC 1035",
            "TCHS1-GC 1045", "TCHS1-GC 1055", "TCHS1-GC 3930",
        ],
    ),
    RequirementSpec(
        name="Electives", kind=RequirementKind.elective, rule="credits", min_credits=18,
        courses=[
            "TCHS1-GC 1320", "TCHS1-GC 3020", "TCHS1-GC 3010", "TCHS1-GC 3430",
            "TCHS1-GC 3400", "TCHS1-GC 2045", "TCHS1-GC 3455", "TCHS1-GC 1025",
            "TCHS1-GC 3255", "TCHS1-GC 3025", "TCHS1-GC 3060", "TCHS1-GC 3035",
            "TCHS1-GC 3045", "TCHS1-GC 3055", "TCHS1-GC 3065", "TCHS1-GC 3070",
            "TCHS1-GC 2060", "TCHS1-GC 3235", "TCHS1-GC 2080", "TCHS1-GC 2090",
            "TCHS1-GC 3420", "TCHS1-GC 3105", "TCHS1-GC 3115", "TCHS1-GC 3130",
            "TCHS1-GC 3135", "TCHS1-GC 3280", "TCHS1-GC 3305", "TCHS1-GC 3075",
            "TCHS1-GC 3905", "TCHS1-GC 3925", "TCHS1-GC 3920",
        ],
        caveat=(
            "Select 18 credits from the listed courses. They range from 1.5 to 3 credits "
            "each, so how many courses that is depends on which you choose, and Special "
            "Topics in Hospitality (TCHS1-GC 3905) is published without a fixed credit "
            "value — how much it contributes cannot be read from the catalog."
        ),
    ),
    RequirementSpec(
        name="Capstone", kind=RequirementKind.capstone, rule="all_of", min_credits=1.5,
        courses=["TCHS1-GC 1930"],  # Leadership
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
    ProgramSpec(
        page_slug=(
            "graduate__professional-studies__programs__"
            "global-security-conflict-cyber-crime-ms"
        ),
        code="GSCC-MS-REAL",
        name="Global Security, Conflict, and Cyber Crime",
        total_credits=36,
        requirements=GLOBAL_SECURITY,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__entrepreneurship-management-ms",
        code="ENTR-MS-REAL",
        name="Entrepreneurship and Management",
        total_credits=30,
        requirements=ENTREPRENEURSHIP,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__event-management-ms",
        code="MSEM-MS-REAL",
        name="Event Management",
        total_credits=36,
        requirements=EVENT_MANAGEMENT,
    ),
    ProgramSpec(
        page_slug=(
            "graduate__professional-studies__programs__"
            "executive-coaching-organizational-consulting-ms"
        ),
        code="ECOC-MS-REAL",
        name="Executive Coaching and Organizational Consulting",
        total_credits=30,
        requirements=EXECUTIVE_COACHING,
    ),
    ProgramSpec(
        page_slug=(
            "graduate__professional-studies__programs__"
            "executive-masters-marketing-strategic-communications"
        ),
        code="EMSC-MS-REAL",
        name="Marketing and Strategic Communications, Executive",
        total_credits=30,
        requirements=EXECUTIVE_MARKETING,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__global-affairs-ms",
        code="GLOB-MS-REAL",
        name="Global Affairs",
        total_credits=42,
        requirements=GLOBAL_AFFAIRS,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__global-sport-ms",
        code="GLSP-MS-REAL",
        name="Global Sport",
        total_credits=36,
        requirements=GLOBAL_SPORT,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__project-management-ms",
        code="MSPM-MS-REAL",
        name="Project Management",
        total_credits=36,
        requirements=PROJECT_MANAGEMENT,
    ),
    ProgramSpec(
        page_slug=(
            "graduate__professional-studies__programs__"
            "human-capital-analytics-technology-ms"
        ),
        code="HCAT-MS-REAL",
        name="Human Capital Analytics and Technology",
        total_credits=30,
        requirements=HUMAN_CAPITAL_ANALYTICS,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__professional-writing-ms",
        code="PWRT-MS-REAL",
        name="Professional Writing",
        total_credits=36,
        requirements=PROFESSIONAL_WRITING,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__human-capital-management-ms",
        code="HRCM-MS-REAL",
        name="Human Capital Management",
        total_credits=30,
        requirements=HUMAN_CAPITAL_MANAGEMENT,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__translation-interpreting-ms",
        code="TRAN-MS-REAL",
        name="Translation and Interpreting",
        total_credits=36,
        requirements=TRANSLATION_INTERPRETING,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__sports-business-ms",
        code="TCSB-MS-REAL",
        name="Sports Business",
        total_credits=36,
        requirements=SPORTS_BUSINESS,
    ),
    ProgramSpec(
        page_slug="graduate__professional-studies__programs__travel-tourism-management-ms",
        code="TCTM-MS-REAL",
        name="Travel and Tourism Management",
        total_credits=36,
        requirements=TRAVEL_TOURISM,
    ),
    ProgramSpec(
        page_slug=(
            "graduate__professional-studies__programs__global-hospitality-management-ms"
        ),
        code="TCHS-MS-REAL",
        name="Global Hospitality Management",
        total_credits=36,
        requirements=GLOBAL_HOSPITALITY,
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
    codes |= {c for spec in requirements for t in spec.tracks for c in t.required}
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
                per_course = {credits_of(c) for c in track.courses + track.required}
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
            row.required_courses = [by_code[c] for c in track.required if c in by_code]
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
