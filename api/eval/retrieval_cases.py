"""The retrieval golden set: 50 labelled queries against the ingested NYU corpus.

Replaces the 15 cases written against the hand-authored corpus, which became invalid when
the synthetic public policy was deleted in favour of ~1,000 real chunks.

**Composition is a measurement decision, not a formality.** An ablation's conclusion is
decided by what the label set contains. A set made only of queries whose wording matches
the source text will crown lexical search; one made only of colloquial paraphrases will
crown vector search. The families below are sized deliberately so neither wins by
construction, and each family's size is stated so a reader can discount accordingly:

  home_scope   12  the answer exists at several schools; only the student's own counts
  generic      10  school-agnostic policy, any correct source is fine
  course        8  MASY1-GC catalog entries — atomic records, not prose
  lexical       6  exact policy terms and codes; expected to favour BM25/hybrid
  paraphrase    8  student-voice phrasing far from the policy's wording; favours vectors
  restricted    4  role-gated synthetic fixtures; also a leakage check
  multi         2  the answer genuinely spans two sections

`home_scope` is the family that exists because of a defect this corpus exposed: asked how
many credits count as full-time, retrieval returned Nursing, Engineering, and Steinhardt
before the student's own school — and those schools' answers differ. Fifteen hand-written
chunks could never have surfaced that.

Labels reference `slug#heading_path`, never chunk ids, so one label set stays valid across
every chunking strategy. `validate()` asserts each key exists in the extracted corpus, so
a typo fails loudly instead of quietly scoring zero.
"""

import json
from dataclasses import dataclass
from pathlib import Path

SECTIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "sections"

# Page slugs, spelled once.
SPS = "graduate__professional-studies__academic-policies"
SPS_COURSES = "graduate__professional-studies__courses__masy1-gc"
SPS_AID = "graduate__professional-studies__cost-attendance__financial-aid-scholarships"
SPS_TUITION = "graduate__professional-studies__cost-attendance__tuition-fees"
SPS_ADVISING = "graduate__professional-studies__student-services__advising"
SPS_CALENDAR = "graduate__professional-studies__academic-calendar"
SPS_UG = "undergraduate__professional-studies__academic-policies"
SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class RetrievalCase:
    id: str
    role: str
    query: str
    # Section keys (`slug#heading_path`) that answer the query. A retrieved chunk counts
    # as a hit when it covers any of them.
    expected: tuple[str, ...]
    family: str
    note: str = ""


def k(slug: str, path: str) -> str:
    return f"{slug}#{path}"


AP = "Academic Policies"
COURSES = "Management & Systems MA/GC (MASY1-GC)"


# --------------------------------------------------------------------------------------
# home_scope (12) — the same question is answered differently by several schools
# --------------------------------------------------------------------------------------

HOME_SCOPE = [
    RetrievalCase("R01", "student", "how many credits count as full-time for me as a graduate student",
        (k(SPS, f"{AP} > Academic Standing and Progress > Enrollment Status > Full-Time, Part-Time, and Half-Time Status"),),
        "home_scope", "Nursing/Engineering/Steinhardt all answer this differently."),
    RetrievalCase("R02", "student", "what counts as full-time equivalency when I am finishing my thesis",
        (k(SPS, f"{AP} > Academic Standing and Progress > Enrollment Status > Full-Time Equivalency and Half-Time Equivalency"),),
        "home_scope"),
    RetrievalCase("R03", "student", "how long do I have to finish my master's degree",
        (k(SPS, f"{AP} > Academic Standing and Progress > Time to Complete a Graduate Program"),),
        "home_scope"),
    RetrievalCase("R04", "student", "what GPA do I need to stay in good academic standing",
        (k(SPS, f"{AP} > Academic Standing and Progress > Satisfactory Academic Progress > Good Academic Standing"),),
        "home_scope"),
    RetrievalCase("R05", "student", "how do I take a semester off without losing my place in the program",
        (k(SPS, f"{AP} > Academic Standing and Progress > Leave of Absence"),
         k(SPS, f"{AP} > Academic Standing and Progress > Maintenance of Matriculation")),
        "home_scope"),
    RetrievalCase("R06", "student", "how many of my credits have to be taken at NYU rather than transferred",
        (k(SPS, f"{AP} > Residency Requirements > Master's Programs"),),
        "home_scope", "The source page repeats this heading for two related rules; both count."),
    RetrievalCase("R07", "student", "what is the grading scale for graduate courses in my program",
        (k(SPS, f"{AP} > Grading > Graduate Grading Scale"),),
        "home_scope"),
    RetrievalCase("R08", "student", "can I substitute a different course for a required one",
        (k(SPS, f"{AP} > Residency Requirements > Course Substitutions"),),
        "home_scope"),
    RetrievalCase("R09", "student", "what do I have to do to actually graduate and get my diploma",
        (k(SPS, f"{AP} > Graduation"),),
        "home_scope"),
    RetrievalCase("R10", "student", "how many times can I retake a course I did badly in",
        (k(SPS, f"{AP} > Grading > Repeating a Course"),),
        "home_scope"),
    RetrievalCase("R11", "student", "what is the attendance policy for my classes",
        (k(SPS, f"{AP} > Attendance Policy"),),
        "home_scope"),
    RetrievalCase("R12", "student", "I am an international student, how does a leave of absence affect my visa",
        (k(SPS, f"{AP} > Academic Standing and Progress > Leave of Absence > Leave of Absence Policies for International Students"),),
        "home_scope"),
]

# --------------------------------------------------------------------------------------
# generic (10) — school-agnostic; any correct source is acceptable
# --------------------------------------------------------------------------------------

GENERIC = [
    RetrievalCase("R13", "student", "what happens if I miss the deadline to drop a course",
        (k(SPS, f"{AP} > Registration and Schedule Changes > Dropping / Withdrawing from Courses"),),
        "generic"),
    RetrievalCase("R14", "student", "can I still register after registration has closed",
        (k(SPS, f"{AP} > Registration and Schedule Changes > Late Registration"),),
        "generic"),
    RetrievalCase("R15", "student", "how do I register for my courses",
        (k(SPS, f"{AP} > Registration and Schedule Changes > Registering for Courses"),),
        "generic"),
    RetrievalCase("R16", "student", "what happens if I withdraw from the whole semester",
        (k(SPS, f"{AP} > Withdrawals > Semester Withdrawals"),),
        "generic"),
    RetrievalCase("R17", "student", "how is my grade point average calculated",
        (k(SPS, f"{AP} > Grading > Computing the Grade Point Average"),),
        "generic"),
    RetrievalCase("R18", "student", "what are the rules about cheating and plagiarism",
        (k(SPS, f"{AP} > Academic Integrity Policy"),),
        "generic"),
    RetrievalCase("R19", "student", "what counts as a level 3 academic integrity offense",
        (k(SPS, f"{AP} > Academic Integrity Policy > Academic Offenses > Level 3 Offense Sample Violations"),),
        "generic"),
    RetrievalCase("R20", "student", "how do I file a formal complaint against the school",
        (k(SPS, f"{AP} > Redress of Grievances > Formal Complaint"),),
        "generic"),
    RetrievalCase("R21", "student", "can I do an internship for credit",
        (k(SPS, f"{AP} > Internships"),),
        "generic"),
    RetrievalCase("R22", "student", "when does the fall 2026 term start and end",
        (k(SPS_CALENDAR, "Academic Calendar > 2026-2027 Academic Calendar > Fall 2026"),),
        "generic"),
]

# --------------------------------------------------------------------------------------
# course (8) — atomic catalog records
# --------------------------------------------------------------------------------------

COURSE = [
    RetrievalCase("R23", "student", "what are the prerequisites for Data-Driven Decision-Making",
        (k(SPS_COURSES, f"{COURSES} > MASY1-GC 1215 Data-Driven Decision-Making"),),
        "course"),
    RetrievalCase("R24", "student", "MASY1-GC 2100 prerequisites",
        (k(SPS_COURSES, f"{COURSES} > MASY1-GC 2100 Advanced Business Analytics"),),
        "course"),
    RetrievalCase("R25", "student", "which course teaches foundations of business analytics",
        (k(SPS_COURSES, f"{COURSES} > MASY1-GC 2000 Foundations of Business Analytics"),),
        "course"),
    RetrievalCase("R26", "student", "is there a class about emerging technologies and how do I qualify for it",
        (k(SPS_COURSES, f"{COURSES} > MASY1-GC 1800 Emerging Technologies"),),
        "course"),
    RetrievalCase("R27", "student", "course on managing organizational change and innovation",
        (k(SPS_COURSES, f"{COURSES} > MASY1-GC 1315 Managing Change and Innovation"),),
        "course"),
    RetrievalCase("R28", "student", "how many credits is MASY1-GC 1215 worth",
        (k(SPS_COURSES, f"{COURSES} > MASY1-GC 1215 Data-Driven Decision-Making"),),
        "course"),
    RetrievalCase("R29", "student", "which semesters is Data-Driven Decision-Making typically offered",
        (k(SPS_COURSES, f"{COURSES} > MASY1-GC 1215 Data-Driven Decision-Making"),),
        "course"),
    RetrievalCase("R30", "student", "what do I need to take before Advanced Business Analytics",
        (k(SPS_COURSES, f"{COURSES} > MASY1-GC 2100 Advanced Business Analytics"),),
        "course"),
]

# --------------------------------------------------------------------------------------
# lexical (6) — exact policy vocabulary; expected to favour term matching
# --------------------------------------------------------------------------------------

LEXICAL = [
    RetrievalCase("R31", "student", "Maintenance of Matriculation",
        (k(SPS, f"{AP} > Academic Standing and Progress > Maintenance of Matriculation"),),
        "lexical"),
    RetrievalCase("R32", "student", "Incomplete Pass Incomplete Fail IP/IF",
        (k(SPS, f"{AP} > Grading > Incomplete Pass/Incomplete Fail (IP/IF)"),),
        "lexical"),
    RetrievalCase("R33", "student", "Notice of Continued Academic Concern Pre-Dismissal Status",
        (k(SPS, f"{AP} > Academic Standing and Progress > Academic Concern > Notice of Continued Academic Concern: Pre-Dismissal Status"),),
        "lexical"),
    RetrievalCase("R34", "student", "Pass/Fail P/F option",
        (k(SPS, f"{AP} > Grading > Pass/Fail (P/F)"),),
        "lexical"),
    RetrievalCase("R35", "student", "Withdrawal W grade",
        (k(SPS, f"{AP} > Grading > Withdrawal (W)"),),
        "lexical"),
    RetrievalCase("R36", "student", "SPS Academic Standing Committee",
        (k(SPS, f"{AP} > Academic Standing and Progress > SPS Academic Standing Committee"),),
        "lexical"),
]

# --------------------------------------------------------------------------------------
# paraphrase (8) — colloquial phrasing, little lexical overlap with the source
# --------------------------------------------------------------------------------------

PARAPHRASE = [
    RetrievalCase("R37", "student", "my professor gave me a grade I think is unfair, what can I do about it",
        (k(SPS, f"{AP} > Grading > Grade Changes and Appeals"),
         k(SPS, f"{AP} > Grading > Grade Changes and Appeals > Level 1: Faculty")),
        "paraphrase"),
    RetrievalCase("R38", "student", "I got kicked out of my program, is there any way to fight it",
        (k(SPS, f"{AP} > Academic Standing and Progress > Academic Dismissal > Appeal of Academic Dismissal"),),
        "paraphrase"),
    RetrievalCase("R39", "student", "my grades slipped and the school sent me a warning letter, what does it mean",
        (k(SPS, f"{AP} > Academic Standing and Progress > Academic Concern"),
         k(SPS, f"{AP} > Academic Standing and Progress > Academic Concern > Criteria of Academic Concern")),
        "paraphrase"),
    RetrievalCase("R40", "student", "I could not finish my coursework because I got sick, what grade do I get",
        (k(SPS, f"{AP} > Grading > Incomplete Pass/Incomplete Fail (IP/IF)"),),
        "paraphrase"),
    RetrievalCase("R41", "student", "am I allowed to do less if I am on academic warning",
        (k(SPS, f"{AP} > Academic Standing and Progress > Academic Concern > Restrictions While on Notice of Academic Concern"),),
        "paraphrase"),
    RetrievalCase("R42", "student", "who is supposed to help me plan my classes and what are they responsible for",
        (k(SPS_ADVISING, "Advising > Academic Advising > How Advising Works > Role of Advisor"),),
        "paraphrase"),
    RetrievalCase("R43", "student", "I want to talk to someone before I escalate a problem formally",
        (k(SPS, f"{AP} > Redress of Grievances > Informal Resolution"),),
        "paraphrase"),
    RetrievalCase("R44", "student", "my employer said they will cover my tuition, how does that work here",
        (k(SPS_AID, "Financial Aid > Explore Your Options > Loans and Payment Plans > Employer Tuition Reimbursement"),),
        "paraphrase"),
]

# --------------------------------------------------------------------------------------
# restricted (4) — role-gated fixtures; also the leakage boundary
# --------------------------------------------------------------------------------------

RESTRICTED = [
    RetrievalCase("R45", "advisor", "can I approve an elective substitution myself without department signoff",
        (k(SYNTHETIC, "Internal > Overrides > Authority"),),
        "restricted"),
    RetrievalCase("R46", "advisor", "when must a substitution request go to the program director",
        (k(SYNTHETIC, "Internal > Overrides > Escalation thresholds"),),
        "restricted"),
    RetrievalCase("R47", "student", "how do I enroll in a payment plan for my outstanding balance",
        (k(SYNTHETIC, "Bursar > Payment plans > Eligibility"),),
        "restricted"),
    RetrievalCase("R48", "student", "what happens if I miss an installment on my payment plan",
        (k(SYNTHETIC, "Bursar > Payment plans > Missed installments"),),
        "restricted"),
]

# --------------------------------------------------------------------------------------
# multi (2) — the answer genuinely spans sections
# --------------------------------------------------------------------------------------

MULTI = [
    RetrievalCase("R49", "student", "what is the full process for appealing a grade all the way up",
        (k(SPS, f"{AP} > Grading > Grade Changes and Appeals > Level 1: Faculty"),
         k(SPS, f"{AP} > Grading > Grade Changes and Appeals > Level 2: Written Appeal to the Director of Your Program"),
         k(SPS, f"{AP} > Grading > Grade Changes and Appeals > Level 3: Written Appeal to the Associate Dean/Divisional Dean")),
        "multi", "Scored on recall across all three levels."),
    RetrievalCase("R50", "student", "what are my options to pay for the program",
        (k(SPS_AID, "Financial Aid > Explore Your Options > Scholarships and Grants"),
         k(SPS_AID, "Financial Aid > Explore Your Options > Loans and Payment Plans"),
         k(SPS_TUITION, "Tuition and Fees")),
        "multi"),
]

RETRIEVAL_CASES: list[RetrievalCase] = (
    HOME_SCOPE + GENERIC + COURSE + LEXICAL + PARAPHRASE + RESTRICTED + MULTI
)


def corpus_keys() -> set[str]:
    """Every section key present in the extracted corpus, plus the synthetic fixtures."""
    keys = set()
    for path in SECTIONS_DIR.glob("*.json"):
        page = json.loads(path.read_text(encoding="utf-8"))
        for section in page["sections"]:
            keys.add(f"{page['slug']}#{section['heading_path']}")
    # Synthetic fixtures live in the seed script, not the extracted corpus.
    for heading in (
        "Internal > Overrides > Authority",
        "Internal > Overrides > Escalation thresholds",
        "Bursar > Payment plans > Eligibility",
        "Bursar > Payment plans > Missed installments",
    ):
        keys.add(f"{SYNTHETIC}#{heading}")
    return keys


def validate() -> list[str]:
    """Return labels that point at sections which do not exist.

    Called at the start of every eval run. A mistyped label would otherwise score a
    permanent zero and look like a retrieval failure — the most expensive kind of bug in
    an evaluation harness, because it produces a plausible number.
    """
    known = corpus_keys()
    problems = []
    for case in RETRIEVAL_CASES:
        for key in case.expected:
            if key not in known:
                problems.append(f"{case.id}: no such section -> {key}")
    return problems


def family_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in RETRIEVAL_CASES:
        counts[case.family] = counts.get(case.family, 0) + 1
    return counts
