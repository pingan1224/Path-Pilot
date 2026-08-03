"""Populate the database with a coherent demo dataset.

    .venv/Scripts/python -m scripts.seed --reset

Two layers of data, deliberately:

* Three hand-authored students carrying the scenarios the product exists to solve —
  a financial hold blocking registration, a prerequisite ordering conflict, and enough
  credits in the wrong distribution. These are what the demo walks through.
* Around forty generated students producing enough volume for the registrar aggregates
  to mean something. A failure-reason breakdown over three students is not a dashboard.

All people are fictional and all identifiers are invented.
"""

import argparse
import random
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.models import (
    ActorKind,
    AiInteraction,
    Case,
    CaseCategory,
    CaseEvent,
    CasePriority,
    CaseStatus,
    Course,
    CoursePrerequisite,
    Document,
    DocumentChunk,
    Enrollment,
    EnrollmentStatus,
    FailureReason,
    Hold,
    HoldType,
    Intent,
    InteractionDecision,
    Office,
    Program,
    RegistrationAttempt,
    RegistrationOutcome,
    Requirement,
    RequirementKind,
    Section,
    SourceFreshnessPolicy,
    Student,
    Term,
    User,
    UserRole,
)

RNG = random.Random(20260803)

# Anchored to the real clock, not a fixed date. Every timestamp below is expressed as an
# offset from this, so a seed run in six months still produces a registration period that
# is happening now — balances minutes old, deadlines days away. Freshness is the feature
# this project is built to demonstrate; hard-coding the anchor would rot it within a day.
NOW = datetime.now(UTC)

REGISTRATION_OPENS_IN_DAYS = 7  # Alex's window, the reference point for the demo narrative.

ALL_ROLES = ["student", "advisor", "registrar", "finance"]


# --------------------------------------------------------------------------------------
# Freshness policy
# --------------------------------------------------------------------------------------

FRESHNESS_POLICIES = [
    (
        "registrar_student",
        "Student record",
        "registrar",
        86_400,
        "Student records sync nightly. Changes made today may not appear until tomorrow.",
    ),
    (
        "registrar_enrollment",
        "Enrollment record",
        "registrar",
        3_600,
        "Enrollment data refreshes hourly. A registration completed in the last hour may not be reflected.",
    ),
    (
        "registrar_section",
        "Section capacity",
        "registrar",
        900,
        "Seat counts refresh every 15 minutes and move quickly during registration.",
    ),
    (
        "bursar_balance",
        "Account balance",
        "bursar",
        900,
        "Balances update every 15 minutes. A payment made just now may not have posted yet.",
    ),
    (
        "financial_aid",
        "Financial aid status",
        "financial_aid",
        86_400,
        "Aid status updates once daily. Documents submitted today are typically reviewed within two business days.",
    ),
    (
        "degree_audit",
        "Degree audit",
        "registrar",
        86_400,
        "Degree audit recalculates nightly. Grade changes posted today are not yet included.",
    ),
    (
        "policy_doc",
        "Published policy",
        "registrar",
        2_592_000,
        "Policy text is reviewed monthly. Check the linked page for the authoritative current version.",
    ),
]


def seed_freshness(session: Session) -> None:
    for key, label, office, max_age, disclosure in FRESHNESS_POLICIES:
        session.add(
            SourceFreshnessPolicy(
                source_key=key,
                label=label,
                owning_office=office,
                max_age_seconds=max_age,
                stale_disclosure=disclosure,
            )
        )
    session.flush()


# --------------------------------------------------------------------------------------
# Terms, program, catalog
# --------------------------------------------------------------------------------------


def seed_terms(session: Session) -> dict[str, Term]:
    rows = [
        ("2025FA", "Fall 2025", date(2025, 9, 2), date(2025, 12, 19), date(2025, 9, 15), 1),
        ("2026SP", "Spring 2026", date(2026, 1, 26), date(2026, 5, 15), date(2026, 2, 6), 2),
        ("2026FA", "Fall 2026", date(2026, 9, 1), date(2026, 12, 18), date(2026, 9, 14), 3),
        ("2027SP", "Spring 2027", date(2027, 1, 25), date(2027, 5, 14), date(2027, 2, 5), 4),
    ]
    terms = {}
    for code, name, starts, ends, add_drop, order in rows:
        term = Term(
            code=code,
            name=name,
            starts_on=starts,
            ends_on=ends,
            add_drop_ends_on=add_drop,
            sort_order=order,
        )
        session.add(term)
        terms[code] = term
    session.flush()
    return terms


CORE_COURSES = [
    ("MASY-GC 1200", "Foundations of Business Informatics", 3),
    ("MASY-GC 1230", "Database Technologies", 3),
    ("MASY-GC 1250", "Systems Analysis and Design", 3),
    ("MASY-GC 1500", "Project Management", 3),
    ("MASY-GC 1800", "Data Analytics for Managers", 3),
    ("MASY-GC 1900", "Information Systems Security", 3),
]

ELECTIVE_COURSES = [
    ("MASY-GC 2100", "Cloud Architecture", 3),
    ("MASY-GC 2200", "Machine Learning Applications", 3),
    ("MASY-GC 2300", "Enterprise Systems Integration", 3),
    ("MASY-GC 2400", "Digital Transformation Strategy", 3),
    ("MASY-GC 2500", "Business Process Automation", 3),
    ("MASY-GC 2600", "IT Governance and Risk", 3),
    ("MASY-GC 2700", "Data Visualization", 3),
]

CAPSTONE_COURSES = [
    ("MASY-GC 3100", "Capstone Project I", 3),
    ("MASY-GC 3200", "Capstone Project II", 3),
]

# (course, prerequisite, min_grade, can_be_concurrent)
PREREQUISITES = [
    ("MASY-GC 1800", "MASY-GC 1230", None, False),
    ("MASY-GC 2200", "MASY-GC 1800", "B-", False),
    ("MASY-GC 2300", "MASY-GC 1250", None, False),
    ("MASY-GC 2700", "MASY-GC 1230", None, True),
    ("MASY-GC 3100", "MASY-GC 1250", None, False),
    ("MASY-GC 3200", "MASY-GC 3100", "B-", False),
]


def seed_catalog(session: Session) -> tuple[Program, dict[str, Course]]:
    program = Program(
        code="MASY-MS",
        name="Management and Systems",
        degree="MS",
        school="School of Professional Studies",
        total_credits_required=36,
    )
    session.add(program)
    session.flush()

    courses: dict[str, Course] = {}
    for code, title, credits in CORE_COURSES + ELECTIVE_COURSES + CAPSTONE_COURSES:
        course = Course(
            code=code,
            title=title,
            credits=credits,
            department="Management and Systems",
            description=f"{title}. Graduate-level coursework in the Management and Systems program.",
        )
        session.add(course)
        courses[code] = course
    session.flush()

    core = Requirement(
        program_id=program.id,
        name="Core Requirements",
        kind=RequirementKind.core,
        min_credits=18,
        min_courses=6,
        sort_order=1,
        notes="All six core courses are required. No substitutions without advisor approval.",
    )
    elective = Requirement(
        program_id=program.id,
        name="Electives",
        kind=RequirementKind.elective,
        min_credits=12,
        min_courses=4,
        sort_order=2,
        notes="Any four elective courses. Credits beyond twelve do not count toward the degree.",
    )
    capstone = Requirement(
        program_id=program.id,
        name="Capstone",
        kind=RequirementKind.capstone,
        min_credits=6,
        min_courses=2,
        sort_order=3,
        notes="Capstone I and II must be taken in sequence in consecutive terms.",
    )
    session.add_all([core, elective, capstone])
    session.flush()

    core.courses = [courses[c] for c, _, _ in CORE_COURSES]
    elective.courses = [courses[c] for c, _, _ in ELECTIVE_COURSES]
    capstone.courses = [courses[c] for c, _, _ in CAPSTONE_COURSES]

    for course_code, prereq_code, min_grade, concurrent in PREREQUISITES:
        session.add(
            CoursePrerequisite(
                course_id=courses[course_code].id,
                prerequisite_id=courses[prereq_code].id,
                min_grade=min_grade,
                can_be_concurrent=concurrent,
            )
        )
    session.flush()
    return program, courses


# --------------------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------------------

# code, capacity, enrolled, waitlist_cap, waitlisted, permission, reserved rule
FALL_2026_SECTIONS = [
    ("MASY-GC 1200", 40, 31, 10, 0, False, None),
    ("MASY-GC 1230", 35, 35, 10, 6, False, None),
    ("MASY-GC 1250", 35, 28, 10, 0, False, None),
    ("MASY-GC 1500", 40, 22, 10, 0, False, None),
    (
        "MASY-GC 1800",
        30,
        30,
        10,
        9,
        False,
        "Seats reserved for students in their final two terms until Aug 20, 2026.",
    ),
    ("MASY-GC 1900", 35, 14, 10, 0, False, None),
    ("MASY-GC 2100", 30, 27, 5, 0, False, None),
    ("MASY-GC 2200", 25, 25, 8, 7, False, None),
    (
        "MASY-GC 2300",
        30,
        19, 5, 0, False,
        "Seats held for Management and Systems majors until Aug 15, 2026.",
    ),
    ("MASY-GC 2400", 30, 12, 5, 0, False, None),
    ("MASY-GC 2500", 30, 16, 5, 0, False, None),
    ("MASY-GC 2600", 30, 9, 5, 0, False, None),
    ("MASY-GC 2700", 30, 24, 5, 0, False, None),
    ("MASY-GC 3100", 20, 19, 0, 0, True, None),
    ("MASY-GC 3200", 20, 11, 0, 0, True, None),
]


def seed_sections(
    session: Session, courses: dict[str, Course], terms: dict[str, Term]
) -> dict[str, Section]:
    sections: dict[str, Section] = {}

    # Historical terms: capacity data is not the point, so one full section each.
    for term_code in ("2025FA", "2026SP"):
        for code, course in courses.items():
            section = Section(
                course_id=course.id,
                term_id=terms[term_code].id,
                section_code="001",
                capacity=35,
                enrolled_count=RNG.randint(18, 34),
                waitlist_capacity=10,
                waitlist_count=0,
                instructor="Staff",
                meeting_pattern="Wed 18:00-20:30",
                modality="In person",
                source_key="registrar_section",
                verified_at=NOW - timedelta(days=200),
            )
            session.add(section)
            sections[f"{term_code}:{code}"] = section

    patterns = ["Mon 18:00-20:30", "Tue 18:00-20:30", "Wed 18:00-20:30", "Thu 18:00-20:30"]
    for idx, (code, cap, enrolled, wl_cap, wl, permission, reserved) in enumerate(
        FALL_2026_SECTIONS
    ):
        section = Section(
            course_id=courses[code].id,
            term_id=terms["2026FA"].id,
            section_code="001",
            capacity=cap,
            enrolled_count=enrolled,
            waitlist_capacity=wl_cap,
            waitlist_count=wl,
            instructor="Staff",
            meeting_pattern=patterns[idx % len(patterns)],
            modality="In person",
            reserved_seat_rule=reserved,
            requires_permission=permission,
            source_key="registrar_section",
            # Capacity is the fastest-moving data in the system; 8 minutes old is fresh.
            verified_at=NOW - timedelta(minutes=8),
        )
        session.add(section)
        sections[f"2026FA:{code}"] = section

    session.flush()
    return sections


# --------------------------------------------------------------------------------------
# Staff and hero students
# --------------------------------------------------------------------------------------


def seed_staff(session: Session) -> dict[str, User]:
    people = [
        ("maya.patel@uax.example.edu", "Maya Patel", UserRole.advisor, "Advising"),
        ("tom.becker@uax.example.edu", "Tom Becker", UserRole.advisor, "Advising"),
        ("jordan.lee@uax.example.edu", "Jordan Lee", UserRole.registrar, "Registrar"),
        ("sam.okafor@uax.example.edu", "Sam Okafor", UserRole.finance, "Bursar"),
        ("rina.gupta@uax.example.edu", "Rina Gupta", UserRole.finance, "Financial Aid"),
    ]
    staff: dict[str, User] = {}
    for email, name, role, office in people:
        user = User(email=email, full_name=name, role=role, office=office)
        session.add(user)
        staff[email.split("@")[0]] = user
    session.flush()
    return staff


def make_student(
    session: Session,
    *,
    email: str,
    name: str,
    number: str,
    program: Program,
    advisor: User,
    terms: dict[str, Term],
    grad_term: str,
    registration_opens: date,
) -> Student:
    user = User(email=email, full_name=name, role=UserRole.student)
    session.add(user)
    session.flush()

    student = Student(
        student_number=number,
        user_id=user.id,
        advisor_id=advisor.id,
        program_id=program.id,
        admitted_term_id=terms["2025FA"].id,
        expected_graduation_term_id=terms[grad_term].id,
        registration_opens_at=registration_opens,
        transfer_credits=0,
        source_key="registrar_student",
        verified_at=NOW - timedelta(hours=6),
    )
    session.add(student)
    session.flush()
    return student


def enroll(
    session: Session,
    student: Student,
    sections: dict[str, Section],
    term_code: str,
    course_codes: list[str],
    status: EnrollmentStatus,
    grades: dict[str, tuple[str, float]] | None = None,
) -> None:
    for code in course_codes:
        section = sections[f"{term_code}:{code}"]
        grade, points = (grades or {}).get(code, (None, None))
        session.add(
            Enrollment(
                student_id=student.id,
                section_id=section.id,
                status=status,
                grade=grade,
                grade_points=points,
                enrolled_at=NOW - timedelta(days=300),
                source_key="registrar_enrollment",
                verified_at=NOW - timedelta(minutes=45),
            )
        )
    session.flush()


GRADES_A = ("A", 4.0)
GRADES_AM = ("A-", 3.7)
GRADES_B = ("B+", 3.3)


def seed_hero_students(
    session: Session,
    program: Program,
    staff: dict[str, User],
    terms: dict[str, Term],
    sections: dict[str, Section],
) -> dict[str, Student]:
    heroes: dict[str, Student] = {}

    # --- Alex Chen: on pace academically, but a financial aid hold blocks registration.
    alex = make_student(
        session,
        email="alex.chen@uax.example.edu",
        name="Alex Chen",
        number="N10234567",
        program=program,
        advisor=staff["maya.patel"],
        terms=terms,
        grad_term="2027SP",
        registration_opens=(NOW + timedelta(days=REGISTRATION_OPENS_IN_DAYS)).date(),
    )
    enroll(
        session, alex, sections, "2025FA",
        ["MASY-GC 1200", "MASY-GC 1230", "MASY-GC 1250"],
        EnrollmentStatus.completed,
        {"MASY-GC 1200": GRADES_A, "MASY-GC 1230": GRADES_AM, "MASY-GC 1250": GRADES_B},
    )
    enroll(
        session, alex, sections, "2026SP",
        ["MASY-GC 1500", "MASY-GC 1800", "MASY-GC 1900", "MASY-GC 2100"],
        EnrollmentStatus.completed,
        {
            "MASY-GC 1500": GRADES_A,
            "MASY-GC 1800": GRADES_B,
            "MASY-GC 1900": GRADES_AM,
            "MASY-GC 2100": GRADES_A,
        },
    )
    heroes["alex"] = alex

    # --- Priya Raman: on track, but wants a course whose prerequisite she has not taken.
    priya = make_student(
        session,
        email="priya.raman@uax.example.edu",
        name="Priya Raman",
        number="N10891234",
        program=program,
        advisor=staff["maya.patel"],
        terms=terms,
        grad_term="2027SP",
        registration_opens=(NOW + timedelta(days=2)).date(),
    )
    enroll(
        session, priya, sections, "2025FA",
        ["MASY-GC 1200", "MASY-GC 1230", "MASY-GC 1250"],
        EnrollmentStatus.completed,
        {"MASY-GC 1200": GRADES_AM, "MASY-GC 1230": GRADES_A, "MASY-GC 1250": GRADES_A},
    )
    enroll(
        session, priya, sections, "2026SP",
        ["MASY-GC 1500", "MASY-GC 2100", "MASY-GC 2400"],
        EnrollmentStatus.completed,
        {"MASY-GC 1500": GRADES_B, "MASY-GC 2100": GRADES_AM, "MASY-GC 2400": GRADES_A},
    )
    heroes["priya"] = priya

    # --- Diego Morales: 27 credits earned, but six of them are electives beyond the cap
    #     and three core courses plus the entire capstone remain. The classic "enough
    #     credits, wrong credits" case, which a raw credit count would show as 75% done.
    diego = make_student(
        session,
        email="diego.morales@uax.example.edu",
        name="Diego Morales",
        number="N10456789",
        program=program,
        advisor=staff["tom.becker"],
        terms=terms,
        grad_term="2026FA",
        registration_opens=(NOW + timedelta(days=9)).date(),
    )
    enroll(
        session, diego, sections, "2025FA",
        ["MASY-GC 1200", "MASY-GC 1230", "MASY-GC 1250", "MASY-GC 2100"],
        EnrollmentStatus.completed,
        {
            "MASY-GC 1200": GRADES_B,
            "MASY-GC 1230": GRADES_B,
            "MASY-GC 1250": GRADES_AM,
            "MASY-GC 2100": GRADES_A,
        },
    )
    enroll(
        session, diego, sections, "2026SP",
        [
            "MASY-GC 2300", "MASY-GC 2400", "MASY-GC 2500",
            "MASY-GC 2600", "MASY-GC 2700",
        ],
        EnrollmentStatus.completed,
        {
            "MASY-GC 2300": GRADES_B,
            "MASY-GC 2400": GRADES_B,
            "MASY-GC 2500": GRADES_AM,
            "MASY-GC 2600": GRADES_B,
            "MASY-GC 2700": GRADES_A,
        },
    )
    heroes["diego"] = diego

    return heroes


# --------------------------------------------------------------------------------------
# Holds
# --------------------------------------------------------------------------------------


def seed_holds(session: Session, heroes: dict[str, Student]) -> dict[str, Hold]:
    holds: dict[str, Hold] = {}

    alex_hold = Hold(
        student_id=heroes["alex"].id,
        hold_type=HoldType.aid_document_missing,
        office=Office.financial_aid,
        title="Financial aid verification document outstanding",
        explanation=(
            "Your 2026-2027 aid package requires a signed Verification Worksheet. "
            "Financial Aid received your FAFSA but has not received the worksheet, so your "
            "aid has not been finalized and a registration hold remains on your record."
        ),
        required_action=(
            "Upload the signed Verification Worksheet to the Financial Aid document portal. "
            "Processing takes up to two business days after upload."
        ),
        blocks_registration=True,
        placed_at=NOW - timedelta(days=14),
        # Deliberately two days before the registration window opens: the deadline and the
        # window are in tension, which is the whole point of surfacing both together.
        deadline_at=NOW + timedelta(days=REGISTRATION_OPENS_IN_DAYS - 2),
        resolution_url="https://example.edu/financial-aid/documents",
        source_key="financial_aid",
        verified_at=NOW - timedelta(hours=19),
    )
    session.add(alex_hold)
    holds["alex_aid"] = alex_hold

    diego_hold = Hold(
        student_id=heroes["diego"].id,
        hold_type=HoldType.advising_required,
        office=Office.advising,
        title="Advisor meeting required before registration",
        explanation=(
            "Your degree audit shows three remaining core courses and no capstone progress, "
            "which is not compatible with your recorded expected graduation term of Fall 2026. "
            "Advising placed this hold so your plan can be revised before you register."
        ),
        required_action=(
            "Schedule a planning meeting with Tom Becker. The hold is released at the end of "
            "the meeting."
        ),
        blocks_registration=True,
        placed_at=NOW - timedelta(days=6),
        deadline_at=NOW + timedelta(days=9),
        resolution_url="https://example.edu/advising/appointments",
        source_key="registrar_student",
        verified_at=NOW - timedelta(hours=6),
    )
    session.add(diego_hold)
    holds["diego_advising"] = diego_hold

    # A cleared hold, so the UI has a resolved state to render and the assistant has a case
    # where the correct answer is "this is no longer blocking you".
    priya_hold = Hold(
        student_id=heroes["priya"].id,
        hold_type=HoldType.financial_balance,
        office=Office.bursar,
        title="Outstanding balance from Spring 2026",
        explanation="A balance of $450.00 remained on your Spring 2026 account.",
        required_action="Pay the outstanding balance or enroll in a payment plan.",
        amount_cents=45_000,
        blocks_registration=True,
        placed_at=NOW - timedelta(days=63),
        deadline_at=NOW - timedelta(days=19),
        cleared_at=NOW - timedelta(days=23),
        source_key="bursar_balance",
        verified_at=NOW - timedelta(minutes=11),
    )
    session.add(priya_hold)
    holds["priya_cleared"] = priya_hold

    session.flush()
    return holds


# --------------------------------------------------------------------------------------
# Background population
# --------------------------------------------------------------------------------------

FIRST_NAMES = [
    "Amara", "Nikhil", "Sofia", "Wei", "Leila", "Marcus", "Yuki", "Tomas", "Hana", "Idris",
    "Camila", "Arjun", "Noor", "Elena", "Kwame", "Mei", "Rafael", "Zara", "Oscar", "Ingrid",
    "Dmitri", "Aisha", "Felipe", "Naomi", "Hugo", "Anya", "Kenji", "Lucia", "Omar", "Freya",
    "Santiago", "Divya", "Mateo", "Rin", "Ayo", "Clara", "Viktor", "Priyanka", "Andre", "Suki",
    "Bilal", "Greta", "Nadia", "Emeka", "Isabel",
]

LAST_NAMES = [
    "Okonkwo", "Sharma", "Rossi", "Zhang", "Haddad", "Bennett", "Tanaka", "Silva", "Kim",
    "Abdi", "Torres", "Menon", "Rahman", "Petrova", "Mensah", "Chen", "Duarte", "Malik",
    "Lindqvist", "Novak", "Volkov", "Diallo", "Costa", "Watanabe", "Muller", "Sokolov",
    "Ito", "Ramirez", "Farah", "Olsen", "Vega", "Iyer", "Guzman", "Sato", "Adeyemi",
    "Fischer", "Popov", "Nair", "Laurent", "Park", "Yilmaz", "Berg", "Hassan", "Eze", "Moreau",
]


def seed_background_students(
    session: Session,
    program: Program,
    staff: dict[str, User],
    terms: dict[str, Term],
    count: int = 45,
) -> list[Student]:
    advisors = [staff["maya.patel"], staff["tom.becker"]]
    students: list[Student] = []

    for i in range(count):
        first = FIRST_NAMES[i % len(FIRST_NAMES)]
        last = LAST_NAMES[(i * 7 + 3) % len(LAST_NAMES)]
        email = f"{first.lower()}.{last.lower()}{i}@uax.example.edu"

        user = User(email=email, full_name=f"{first} {last}", role=UserRole.student)
        session.add(user)
        session.flush()

        student = Student(
            student_number=f"N{20_000_000 + i * 137:08d}",
            user_id=user.id,
            advisor_id=advisors[i % 2].id,
            program_id=program.id,
            admitted_term_id=terms["2025FA"].id,
            expected_graduation_term_id=terms[RNG.choice(["2026FA", "2027SP"])].id,
            registration_opens_at=(NOW + timedelta(days=RNG.randint(1, 14))).date(),
            transfer_credits=RNG.choice([0, 0, 0, 3, 6]),
            source_key="registrar_student",
            verified_at=NOW - timedelta(hours=RNG.randint(1, 23)),
        )
        session.add(student)
        students.append(student)

    session.flush()
    return students


# Weighted so the breakdown looks like a real registration period rather than a uniform
# distribution. Financial holds and prerequisite errors dominate, which is what the source
# RFP's pain-point ranking claimed — the dashboard should be able to confirm or refute it.
FAILURE_WEIGHTS = [
    (FailureReason.financial_hold, 26),
    (FailureReason.prerequisite_not_met, 22),
    (FailureReason.section_full, 18),
    (FailureReason.time_conflict, 11),
    (FailureReason.reserved_seat_restriction, 8),
    (FailureReason.appointment_not_open, 7),
    (FailureReason.permission_required, 5),
    (FailureReason.max_credits_exceeded, 2),
    (FailureReason.duplicate_enrollment, 1),
]

RAW_ERRORS = {
    FailureReason.financial_hold: "ERR_HOLD_ACTIVE: Registration blocked (hold code SF2)",
    FailureReason.prerequisite_not_met: "ERR_PREREQ: Requisites not met for this class",
    FailureReason.section_full: "ERR_CLOSED: Class 12043 is full",
    FailureReason.time_conflict: "ERR_CONFLICT: Time conflict with class 11987",
    FailureReason.reserved_seat_restriction: "ERR_RESERVE: Reserved capacity requirement not met",
    FailureReason.appointment_not_open: "ERR_APPT: Enrollment appointment has not begun",
    FailureReason.permission_required: "ERR_PERM: Department consent required",
    FailureReason.max_credits_exceeded: "ERR_MAXUNT: Maximum term unit load exceeded",
    FailureReason.duplicate_enrollment: "ERR_DUPL: Duplicate enrollment for this course",
}


def seed_registration_attempts(
    session: Session,
    heroes: dict[str, Student],
    holds: dict[str, Hold],
    background: list[Student],
    sections: dict[str, Section],
    terms: dict[str, Term],
) -> None:
    fall = terms["2026FA"]

    # --- Hero attempts. These are the ones the demo narrates.
    session.add(
        RegistrationAttempt(
            student_id=heroes["alex"].id,
            section_id=sections["2026FA:MASY-GC 2400"].id,
            term_id=fall.id,
            attempted_at=NOW - timedelta(days=1, hours=3),
            outcome=RegistrationOutcome.failed,
            failure_reason=FailureReason.financial_hold,
            raw_error=RAW_ERRORS[FailureReason.financial_hold],
            blocking_hold_id=holds["alex_aid"].id,
        )
    )
    session.add(
        RegistrationAttempt(
            student_id=heroes["priya"].id,
            section_id=sections["2026FA:MASY-GC 2200"].id,
            term_id=fall.id,
            attempted_at=NOW - timedelta(hours=5),
            outcome=RegistrationOutcome.failed,
            failure_reason=FailureReason.prerequisite_not_met,
            raw_error=RAW_ERRORS[FailureReason.prerequisite_not_met],
        )
    )
    session.add(
        RegistrationAttempt(
            student_id=heroes["diego"].id,
            section_id=sections["2026FA:MASY-GC 3100"].id,
            term_id=fall.id,
            attempted_at=NOW - timedelta(days=2, hours=1),
            outcome=RegistrationOutcome.failed,
            failure_reason=FailureReason.permission_required,
            raw_error=RAW_ERRORS[FailureReason.permission_required],
        )
    )
    session.add(
        RegistrationAttempt(
            student_id=heroes["diego"].id,
            section_id=sections["2026FA:MASY-GC 1800"].id,
            term_id=fall.id,
            attempted_at=NOW - timedelta(days=2, hours=1, minutes=4),
            outcome=RegistrationOutcome.failed,
            failure_reason=FailureReason.section_full,
            raw_error=RAW_ERRORS[FailureReason.section_full],
        )
    )

    # --- Background volume for the registrar aggregates.
    reasons = [r for r, _ in FAILURE_WEIGHTS]
    weights = [w for _, w in FAILURE_WEIGHTS]
    fall_section_keys = [k for k in sections if k.startswith("2026FA:")]

    for student in background:
        for _ in range(RNG.randint(1, 5)):
            key = RNG.choice(fall_section_keys)
            succeeded = RNG.random() < 0.55
            attempted = NOW - timedelta(
                days=RNG.randint(0, 13), hours=RNG.randint(0, 23), minutes=RNG.randint(0, 59)
            )
            if succeeded:
                session.add(
                    RegistrationAttempt(
                        student_id=student.id,
                        section_id=sections[key].id,
                        term_id=fall.id,
                        attempted_at=attempted,
                        outcome=RegistrationOutcome.succeeded,
                    )
                )
            else:
                reason = RNG.choices(reasons, weights=weights, k=1)[0]
                session.add(
                    RegistrationAttempt(
                        student_id=student.id,
                        section_id=sections[key].id,
                        term_id=fall.id,
                        attempted_at=attempted,
                        outcome=RegistrationOutcome.failed,
                        failure_reason=reason,
                        raw_error=RAW_ERRORS[reason],
                    )
                )

    session.flush()


def seed_background_holds(session: Session, background: list[Student]) -> None:
    """Give roughly a third of the background population an active hold."""
    templates = [
        (
            HoldType.financial_balance, Office.bursar, "Outstanding balance",
            "An unpaid balance remains on your student account.",
            "Pay the balance or enroll in a payment plan.", "bursar_balance",
        ),
        (
            HoldType.aid_document_missing, Office.financial_aid, "Aid document outstanding",
            "Financial Aid is waiting on a required document.",
            "Upload the requested document to the Financial Aid portal.", "financial_aid",
        ),
        (
            HoldType.immunization, Office.registrar, "Immunization record incomplete",
            "Student Health has not received a complete immunization record.",
            "Submit your immunization record to Student Health.", "registrar_student",
        ),
        (
            HoldType.advising_required, Office.advising, "Advisor meeting required",
            "Your advisor has requested a planning meeting before registration.",
            "Schedule a meeting with your advisor.", "registrar_student",
        ),
    ]

    for i, student in enumerate(background):
        if i % 3 != 0:
            continue
        hold_type, office, title, explanation, action, source = templates[i % len(templates)]
        # Age the row against its own source's tolerance rather than uniformly, so the
        # freshness audit shows a realistic mix instead of marking every balance stale.
        if source == "bursar_balance":
            verified_at = NOW - timedelta(minutes=RNG.choice([3, 7, 11, 22, 40, 95]))
        else:
            verified_at = NOW - timedelta(hours=RNG.randint(1, 30))
        session.add(
            Hold(
                student_id=student.id,
                hold_type=hold_type,
                office=office,
                title=title,
                explanation=explanation,
                required_action=action,
                amount_cents=RNG.choice([None, 25_000, 45_000, 120_000]),
                blocks_registration=True,
                placed_at=NOW - timedelta(days=RNG.randint(5, 45)),
                deadline_at=NOW + timedelta(days=RNG.randint(2, 20)),
                source_key=source,
                verified_at=verified_at,
            )
        )
    session.flush()


# --------------------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------------------


def seed_cases(session: Session, heroes: dict[str, Student], staff: dict[str, User]) -> None:
    alex_case = Case(
        case_number="UAX-1001",
        student_id=heroes["alex"].id,
        owner_user_id=staff["rina.gupta"].id,
        category=CaseCategory.financial_hold,
        status=CaseStatus.in_review,
        priority=CasePriority.urgent,
        title="Aid verification hold blocking Fall 2026 registration",
        student_message=(
            "My registration window opens Aug 10 and the aid hold is still there. "
            "I uploaded something last week. Can someone confirm what is still missing?"
        ),
        ai_summary=(
            "Student has an active aid_document_missing hold, last verified against Financial "
            "Aid 19 hours ago. The hold deadline falls two days before the student's "
            "registration window opens, so clearing it late still costs them their window. "
            "The student reports uploading a document; receipt was not retrievable from an "
            "authorized source, so the assistant asserted nothing either way."
        ),
        opened_by=ActorKind.ai,
        opened_at=NOW - timedelta(days=1, hours=2),
    )
    session.add(alex_case)
    session.flush()

    session.add_all([
        CaseEvent(
            case_id=alex_case.id,
            actor_kind=ActorKind.ai,
            action="Opened case after failing to verify document receipt",
            note="Escalated rather than answering: aid document status was not retrievable "
                 "from an authorized source, and the question is high-stakes.",
            to_status=CaseStatus.new,
            occurred_at=NOW - timedelta(days=1, hours=2),
        ),
        CaseEvent(
            case_id=alex_case.id,
            actor_kind=ActorKind.staff,
            actor_user_id=staff["rina.gupta"].id,
            action="Picked up for review",
            note="Checking the document queue for an upload under this student number.",
            from_status=CaseStatus.new,
            to_status=CaseStatus.in_review,
            occurred_at=NOW - timedelta(hours=20),
        ),
    ])

    priya_case = Case(
        case_number="UAX-1002",
        student_id=heroes["priya"].id,
        owner_user_id=staff["maya.patel"].id,
        category=CaseCategory.prerequisite_conflict,
        status=CaseStatus.resolved,
        priority=CasePriority.routine,
        title="Prerequisite ordering for Machine Learning Applications",
        student_message="I tried to add ML Applications and it rejected me. What do I take instead?",
        ai_summary=(
            "MASY-GC 2200 requires MASY-GC 1800 with a minimum grade of B-. Student has not "
            "completed 1800. Answered directly with citation; no escalation needed for the "
            "explanation itself, but the substitution question was routed to advising."
        ),
        opened_by=ActorKind.student,
        opened_at=NOW - timedelta(days=4),
        resolved_at=NOW - timedelta(days=3, hours=6),
    )
    session.add(priya_case)
    session.flush()

    session.add_all([
        CaseEvent(
            case_id=priya_case.id,
            actor_kind=ActorKind.student,
            action="Submitted case",
            note="I tried to add ML Applications and it rejected me. What do I take instead?",
            to_status=CaseStatus.new,
            occurred_at=NOW - timedelta(days=4),
        ),
        CaseEvent(
            case_id=priya_case.id,
            actor_kind=ActorKind.staff,
            actor_user_id=staff["maya.patel"].id,
            action="Resolved case",
            note="Take MASY-GC 1800 this fall and 2200 in spring. Graduation term unaffected.",
            from_status=CaseStatus.new,
            to_status=CaseStatus.resolved,
            occurred_at=NOW - timedelta(days=3, hours=6),
        ),
    ])

    diego_case = Case(
        case_number="UAX-1003",
        student_id=heroes["diego"].id,
        owner_user_id=staff["tom.becker"].id,
        category=CaseCategory.degree_planning,
        status=CaseStatus.new,
        priority=CasePriority.elevated,
        title="Expected graduation term not achievable with remaining requirements",
        student_message="I have 27 credits out of 36. Why does it say I am at risk?",
        ai_summary=(
            "Student has 27 earned credits but only 9 apply to core and 12 to electives, with "
            "6 elective credits beyond the 12-credit cap. Three core courses and both capstone "
            "courses remain — 15 applicable credits — against a recorded graduation term of "
            "Fall 2026. Capstone I and II must be taken in consecutive terms, so Fall 2026 is "
            "not reachable. Routed to advising rather than stating a revised graduation date."
        ),
        opened_by=ActorKind.ai,
        opened_at=NOW - timedelta(days=2, hours=1),
    )
    session.add(diego_case)
    session.flush()

    session.add(
        CaseEvent(
            case_id=diego_case.id,
            actor_kind=ActorKind.ai,
            action="Opened case for advisor review",
            note="Graduation timing is a high-stakes category; the assistant explained the "
                 "requirement gap but did not assert a revised graduation term.",
            to_status=CaseStatus.new,
            occurred_at=NOW - timedelta(days=2, hours=1),
        )
    )
    session.flush()


def seed_interactions(session: Session, heroes: dict[str, Student]) -> None:
    """A couple of audit rows so the log is not empty before P3 exists."""
    alex_user_id = heroes["alex"].user_id
    session.add(
        AiInteraction(
            occurred_at=NOW - timedelta(days=1, hours=2, minutes=4),
            user_id=alex_user_id,
            acting_role=UserRole.student,
            subject_student_id=heroes["alex"].id,
            question="Why is my registration blocked?",
            intent=Intent.explain_blocker,
            intent_confidence=0.94,
            retrieved_chunks=[],
            tool_calls=[{"name": "get_active_holds", "args": {"student_id": "self"}}],
            response_text=(
                "Your registration is blocked by a Financial Aid hold placed on July 20 for a "
                "missing verification document, with a deadline of August 8."
            ),
            citations=[
                {
                    "claim": "aid verification document outstanding",
                    "source_id": "hold:financial_aid",
                    "verified_at": (NOW - timedelta(hours=19)).isoformat(),
                }
            ],
            decision=InteractionDecision.answered,
            degraded_modes=[],
            model="pending-p3",
            latency_ms=1840,
        )
    )
    session.add(
        AiInteraction(
            occurred_at=NOW - timedelta(days=1, hours=2),
            user_id=alex_user_id,
            acting_role=UserRole.student,
            subject_student_id=heroes["alex"].id,
            question="I already uploaded that document last week. Can you check?",
            intent=Intent.check_status,
            intent_confidence=0.88,
            retrieved_chunks=[],
            tool_calls=[{"name": "get_aid_document_status", "args": {"student_id": "self"}}],
            response_text=(
                "I can confirm the hold is still active as of 19 hours ago, but I cannot verify "
                "whether your upload was received — document receipt is not available to me from "
                "an authorized source. I have opened case UAX-1001 with Financial Aid."
            ),
            citations=[],
            decision=InteractionDecision.escalated,
            escalation_reason="document_receipt_unverifiable",
            degraded_modes=[],
            model="pending-p3",
            latency_ms=2210,
        )
    )
    session.flush()


# --------------------------------------------------------------------------------------
# Policy corpus
# --------------------------------------------------------------------------------------

# (source_key, title, url, office, published, roles, [(heading, text), ...])
DOCUMENTS = [
    (
        "policy_doc",
        "Registration Holds and How to Clear Them",
        "https://example.edu/registrar/holds",
        "registrar",
        date(2026, 3, 14),
        ALL_ROLES,
        [
            (
                "Registration > Holds > Overview",
                "A hold is a condition on your student record that may prevent registration, "
                "transcript release, or diploma release. Each hold names the office that placed "
                "it. Only that office can remove it. Holds are visible in Albert under Tasks.",
            ),
            (
                "Registration > Holds > Financial holds",
                "Financial holds are placed by the Bursar when a past-due balance remains on "
                "your account. Payment posts to your account within one business day. The hold "
                "is released automatically once the balance reaches zero; no separate request "
                "is needed.",
            ),
            (
                "Registration > Holds > Advising holds",
                "An advising hold requires a planning meeting before you register. Your advisor "
                "releases the hold at the end of the meeting. Advising holds are most often "
                "placed when a degree audit shows a mismatch between remaining requirements and "
                "your recorded expected graduation term.",
            ),
        ],
    ),
    (
        "policy_doc",
        "Prerequisite Enforcement Policy",
        "https://example.edu/registrar/prerequisites",
        "registrar",
        date(2026, 1, 8),
        ALL_ROLES,
        [
            (
                "Enrollment > Prerequisites > Enforcement",
                "Prerequisites are enforced at the moment of enrollment. If you have not "
                "completed the prerequisite with the required minimum grade, the system will "
                "reject the enrollment with error ERR_PREREQ. Courses in progress do not "
                "satisfy a prerequisite unless the prerequisite is marked as allowing "
                "concurrent enrollment.",
            ),
            (
                "Enrollment > Prerequisites > Exceptions",
                "A prerequisite waiver requires approval from the department offering the "
                "course. Advisors cannot waive prerequisites on their own authority. Submit the "
                "waiver request at least five business days before your registration window "
                "opens.",
            ),
        ],
    ),
    (
        "policy_doc",
        "Enrollment Appointment Times",
        "https://example.edu/registrar/appointments",
        "registrar",
        date(2026, 6, 2),
        ALL_ROLES,
        [
            (
                "Registration > Appointments",
                "Your enrollment appointment is the earliest date and time you may register for "
                "a term. Appointments are assigned by earned credit count, with continuing "
                "students registering before newly admitted students. Attempting to enroll "
                "before your appointment returns error ERR_APPT.",
            ),
            (
                "Registration > Appointments > Holds interaction",
                "An enrollment appointment does not override a hold. If you have a registration "
                "hold when your appointment opens, you cannot register until the hold is "
                "cleared, and seats are not reserved for you in the meantime.",
            ),
        ],
    ),
    (
        "policy_doc",
        "Financial Aid Verification Requirements",
        "https://example.edu/financial-aid/verification",
        "financial_aid",
        date(2026, 5, 20),
        ALL_ROLES,
        [
            (
                "Aid > Verification > Required documents",
                "Students selected for verification must submit a signed Verification Worksheet "
                "and, in some cases, tax transcripts. Aid is not disbursed until verification "
                "is complete. A registration hold is placed if verification is outstanding "
                "within thirty days of the term start.",
            ),
            (
                "Aid > Verification > Processing time",
                "Documents are reviewed within two business days of upload. The document portal "
                "shows a received timestamp once processing begins. Uploads made outside "
                "business hours are timestamped the next business day.",
            ),
        ],
    ),
    (
        "policy_doc",
        "Waitlist Policy",
        "https://example.edu/registrar/waitlists",
        "registrar",
        date(2026, 4, 30),
        ALL_ROLES,
        [
            (
                "Enrollment > Waitlists",
                "Joining a waitlist does not guarantee a seat. Waitlists process automatically "
                "each night until the add/drop deadline. You must have no registration holds "
                "and no time conflicts for the waitlist to promote you into an open seat.",
            ),
            (
                "Enrollment > Waitlists > Credit limits",
                "Waitlisted credits count toward your maximum term credit load. If promotion "
                "from a waitlist would exceed your credit limit, the promotion is skipped and "
                "your position is forfeited.",
            ),
        ],
    ),
    # --- Staff-only. This document is the concrete demonstration of rule 3: a student
    #     asking about overrides must never retrieve it, and the pre-filter is what
    #     guarantees that rather than a prompt instruction not to mention it.
    (
        "policy_doc",
        "Advisor Override and Substitution Procedure",
        "https://example.edu/internal/advising/overrides",
        "advising",
        date(2026, 2, 11),
        ["advisor", "registrar"],
        [
            (
                "Internal > Overrides > Authority",
                "Advisors may approve course substitutions within an elective requirement "
                "without department sign-off. Core course substitutions require the program "
                "director. Capstone sequencing may not be waived under any circumstance.",
            ),
            (
                "Internal > Overrides > Escalation thresholds",
                "Route to the program director when a substitution would change the student's "
                "graduation term, when the student has already been granted two substitutions, "
                "or when the request follows a denied appeal.",
            ),
        ],
    ),
    # --- Student and finance only; advisors and registrar have no need for payment plan
    #     mechanics, so they do not receive it.
    (
        "policy_doc",
        "Payment Plan Terms and Enrollment",
        "https://example.edu/bursar/payment-plans",
        "bursar",
        date(2026, 6, 18),
        ["student", "finance"],
        [
            (
                "Bursar > Payment plans > Eligibility",
                "Payment plans are available for the current term only and require a balance of "
                "at least $500. Enrolling in a payment plan releases a financial hold "
                "immediately, before the first installment is paid.",
            ),
            (
                "Bursar > Payment plans > Missed installments",
                "A missed installment reinstates the financial hold within one business day and "
                "incurs a late fee. Two missed installments remove eligibility for payment "
                "plans in future terms.",
            ),
        ],
    ),
]


def seed_documents(session: Session) -> None:
    """Load the policy corpus. Embeddings stay null until P3 fills them in."""
    for source_key, title, url, office, published, roles, chunks in DOCUMENTS:
        document = Document(
            source_key=source_key,
            title=title,
            url=url,
            office=office,
            published_at=published,
            fetched_at=NOW - timedelta(days=2),
            content_hash=f"{abs(hash((title, len(chunks)))):016x}",
            is_active=True,
        )
        session.add(document)
        session.flush()

        for ordinal, (heading, text) in enumerate(chunks):
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    ordinal=ordinal,
                    text=text,
                    heading_path=heading,
                    token_count=max(len(text) // 4, 1),
                    visible_to_roles=list(roles),
                )
            )
    session.flush()


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------

TABLES_IN_DELETE_ORDER = [
    "case_events", "ai_interactions", "cases", "registration_attempts", "enrollments",
    "holds", "sections", "requirement_courses", "course_prerequisites", "requirements",
    "students", "users", "courses", "programs", "terms", "document_chunks", "documents",
    "source_freshness_policy",
]


def reset(session: Session) -> None:
    from sqlalchemy import text

    # cases and ai_interactions reference each other, so break the link before deleting.
    session.execute(text("UPDATE cases SET origin_interaction_id = NULL"))
    for table in TABLES_IN_DELETE_ORDER:
        session.execute(text(f"DELETE FROM {table}"))
        session.execute(text(f"ALTER SEQUENCE IF EXISTS {table}_id_seq RESTART WITH 1"))
    session.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete existing rows first")
    args = parser.parse_args()

    with get_sessionmaker()() as session:
        if args.reset:
            print("resetting ...")
            reset(session)

        if session.scalar(select(Program).limit(1)) is not None:
            raise SystemExit("Database already seeded. Re-run with --reset to rebuild.")

        print("seeding ...")
        seed_freshness(session)
        terms = seed_terms(session)
        program, courses = seed_catalog(session)
        sections = seed_sections(session, courses, terms)
        staff = seed_staff(session)
        heroes = seed_hero_students(session, program, staff, terms, sections)
        holds = seed_holds(session, heroes)
        background = seed_background_students(session, program, staff, terms)
        seed_background_holds(session, background)
        seed_registration_attempts(session, heroes, holds, background, sections, terms)
        seed_cases(session, heroes, staff)
        seed_interactions(session, heroes)
        seed_documents(session)
        session.commit()

    print("done.")


if __name__ == "__main__":
    main()
