"""The curated seed list: which pages get ingested, and what we know about each.

Curated rather than crawled. bulletins.nyu.edu publishes 3,048 URLs; the great majority
are per-program course listings irrelevant to "why can I not register". Picking the pages
a student actually reads when registration fails is a design decision, and it keeps the
corpus small enough to label properly.

**Why so many near-duplicate pages.** Thirty-one NYU schools publish structurally similar
`academic-policies` pages that differ in substance. Including seven of them alongside the
home school is deliberate: "which school's policy applies to me?" is the realistic hard
retrieval problem, and it is what makes recall@5 mean something. A corpus with no
near-duplicates measures lookup, not retrieval.

**Provenance and licensing.** These are publicly published academic bulletins, fetched
politely, stored as a dated snapshot, and cited back to their source URL. bulletins.nyu.edu
allows the paths below in robots.txt (its Disallow list covers only /admin/, /css/,
/search/ and similar infrastructure). Nothing here is republished as authoritative; the
project presents it as a snapshot with a fetch date.

**Honesty note on role visibility.** Everything in this corpus is public, so every chunk
is visible to every role. The advisor-only document used by the leakage tests is synthetic
and authored by us — it is marked as such in the seed script. The permission machinery is
real; the restricted document is a fixture, because no genuinely internal NYU document
would be appropriate to scrape.
"""

from dataclasses import dataclass

BASE = "https://bulletins.nyu.edu"

# Which levels this release actually serves.
#
# Graduate only, decided 2026-08-11. Undergraduate support needs things this release does
# not have: the undergraduate overview page is not ingested, so undergraduate degrees
# cannot even be listed in the programme picker, and the rule vocabulary (core / elective /
# capstone, over all_of / credits / one_track) cannot express general education, minors,
# level-distribution credits or a GPA threshold.
#
# **Deciding that had to change the corpus, not only the roadmap.** The four undergraduate
# policy pages below were ingested as the level-discrimination comparison set, and measured
# on 2026-08-11 they were reaching the top 5 for a *graduate* asker on 55 of 250 labelled
# results — 22%. Not near-misses either: "Residency Requirements > Bachelor's" at rank 2,
# undergraduate "Advanced Standing > Transfer Credit" at rank 3, the undergraduate grading
# page at rank 2. Undergraduate and graduate policy diverge on exactly those topics, which
# is why they were included as a comparison set in the first place, and the 0.05 level
# boost does not come close to separating them.
#
# So pages whose level is not served are loaded but marked inactive: retrieval filters on
# `documents.is_active` in all three query paths, so they cannot be returned, while the
# seed entries, the fetched snapshot and the extracted text all stay in the repository.
# Supporting undergraduates later is this constant plus a re-run of `ingest.load` — not a
# re-scrape and not a rewrite of this list.
SUPPORTED_LEVELS = {"graduate"}

# Politeness. bulletins.nyu.edu publishes no Crawl-delay, so this is our own restraint.
REQUEST_DELAY_SECONDS = 1.5
# The contact is a URL rather than a mailbox. Crawler etiquette is that an operator who
# sees this in their logs can reach whoever is responsible, and the repository's issues
# satisfy that — while a bare address in a public repository is a harvested address.
USER_AGENT = (
    "path-pilot-portfolio-project/0.1 "
    "(personal learning project; +https://github.com/pingan1224/Path-Pilot)"
)


@dataclass(frozen=True)
class Source:
    """One page to ingest.

    `office` becomes the document's owning office and drives the UI's "who do I contact"
    routing. `scope` distinguishes the home school from the near-duplicate comparison set,
    which the eval uses to check that retrieval discriminates rather than just matches.
    """

    path: str
    school: str
    level: str  # graduate | undergraduate
    topic: str  # policies | registration | financial | calendar | advising | courses | overview
    office: str  # registrar | bursar | financial_aid | advising | department
    scope: str  # home | comparison

    @property
    def url(self) -> str:
        return f"{BASE}{self.path}"

    @property
    def slug(self) -> str:
        return self.path.strip("/").replace("/", "__")


def _sps(path: str, topic: str, office: str, level: str = "graduate") -> Source:
    return Source(
        path=path, school="professional-studies", level=level,
        topic=topic, office=office, scope="home",
    )


def _peer(school: str, path: str, topic: str, office: str) -> Source:
    return Source(
        path=path, school=school, level="graduate",
        topic=topic, office=office, scope="comparison",
    )


# One catalogue page per course prefix used by an SPS graduate degree, read off the
# programme pages rather than guessed: every code appearing in a "Program Requirements"
# table was collected, reduced to its prefix, and each resulting URL confirmed to answer 200
# before being listed here. All 24 exist at the same predictable path.
#
# The count is 24 against 23 degrees because the mapping is not one-to-one in either
# direction. Real Estate and Real Estate Development share DEVE/REAL/CONM between them;
# Global Affairs and Global Security share GLOB and GSCC; RWLD ("real world") is a small
# cross-programme prefix appearing in three degrees. A degree's requirements can therefore
# only be assembled from several of these pages, which is why the prefix — not the degree —
# is the unit here.
COURSE_PREFIXES = (
    "conm1-gc", "deve1-gc", "ecoc1-gc", "emsc1-gc", "entr1-gc", "glob1-gc",
    "glsp1-gc", "gscc1-gc", "hcat1-gc", "hrcm1-gc", "intg1-gc", "masy1-gc",
    "msem1-gc", "msfp1-gc", "mspm1-gc", "prcc1-gc", "pubb1-gc", "pwrt1-gc",
    "real1-gc", "rwld1-gc", "tchs1-gc", "tcsb1-gc", "tctm1-gc", "tran1-gc",
)

# --- Home school: SPS graduate. This is the program the source RFP was written about,
#     and MASY-GC is the course prefix used throughout the demo data.
SPS_GRADUATE = [
    _sps("/graduate/professional-studies/", "overview", "registrar"),
    _sps("/graduate/professional-studies/academic-policies/", "policies", "registrar"),
    _sps("/graduate/professional-studies/academic-calendar/", "calendar", "registrar"),
    _sps("/graduate/professional-studies/admissions/", "overview", "registrar"),
    _sps("/graduate/professional-studies/student-services/", "overview", "advising"),
    _sps("/graduate/professional-studies/student-services/registration/", "registration", "registrar"),
    _sps("/graduate/professional-studies/student-services/advising/", "advising", "advising"),
    _sps("/graduate/professional-studies/cost-attendance/", "financial", "bursar"),
    _sps("/graduate/professional-studies/cost-attendance/tuition-fees/", "financial", "bursar"),
    _sps("/graduate/professional-studies/cost-attendance/financial-aid-scholarships/", "financial", "financial_aid"),
    *[
        _sps(f"/graduate/professional-studies/courses/{prefix}/", "courses", "department")
        for prefix in COURSE_PREFIXES
    ],
]

# --- One page per SPS graduate degree.
#
# The overview page above names 23 programs; these are the pages those names link to, and
# each states what its own degree requires. Two things they are for:
#
# 1. **A student who is not in the one encoded program still gets their own school's
#    answer.** Before this, "what does my degree require" retrieved either Management &
#    Analytics or nothing, for everybody. Twenty-two programs' students were being answered
#    from a page about somebody else's degree, which is the cross-school failure with the
#    school held constant.
# 2. **Encoding a program starts here.** `ingest.requirements` transcribes by hand from an
#    ingested page (a parser guessing at a requirements table would be guessing at the
#    thing the planner depends on), so a program cannot be promoted to encoded until its
#    page is in the corpus.
#
# **The paths are extracted from the overview page's own links, never slugified from the
# names.** `Marketing and Strategic Communications, Executive (MS)` lives at
# `executive-masters-marketing-strategic-communications/` — no rule derives that from the
# title, and a constructed URL that 404s is a page silently missing from the corpus rather
# than a loud failure.
#
# `office` is `department`: a question about what a degree requires goes to the program,
# not to the registrar. Management & Analytics keeps `registrar` below for the same reason
# it always had it — it is the planner's rules source, not just a reading page.
SPS_GRADUATE_PROGRAMS = [
    _sps("/graduate/professional-studies/programs/entrepreneurship-management-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/event-management-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/executive-coaching-organizational-consulting-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/financial-planning-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/global-affairs-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/global-hospitality-management-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/global-security-conflict-cyber-crime-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/global-sport-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/human-capital-analytics-technology-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/human-capital-management-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/human-capital-management-human-capital-analytics-technology-ms-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/integrated-marketing-ms/", "requirements", "department"),
    # Management & Analytics is the encoded program: its requirements are transcribed in
    # ingest/requirements.py and the planner evaluates against them.
    _sps("/graduate/professional-studies/programs/management-analytics-ms/", "requirements", "registrar"),
    _sps("/graduate/professional-studies/programs/executive-masters-marketing-strategic-communications/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/professional-writing-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/project-management-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/public-relations-corporate-communication-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/publishing-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/real-estate-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/real-estate-development-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/sports-business-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/translation-interpreting-ms/", "requirements", "department"),
    _sps("/graduate/professional-studies/programs/travel-tourism-management-ms/", "requirements", "department"),
]

# --- Same school, different level. Graduate and undergraduate policies diverge on credit
#     loads, standing, and registration order, so this pair tests whether retrieval keeps
#     the levels apart instead of blending them.
#
#     **Ingested but inactive in this release** — see SUPPORTED_LEVELS. They stay listed
#     because the curation decision and its reasoning are worth keeping, and because
#     re-activating them is a constant change rather than a re-scrape. They are also the
#     evidence for the level facet: it was never measurable while every labelled query was
#     graduate, and it turned out the damage ran the other way, with undergraduate pages
#     answering graduate questions.
SPS_UNDERGRADUATE = [
    _sps("/undergraduate/professional-studies/academic-policies/", "policies", "registrar", level="undergraduate"),
    _sps("/undergraduate/professional-studies/academic-calendar/", "calendar", "registrar", level="undergraduate"),
    _sps("/undergraduate/professional-studies/student-services/registration/", "registration", "registrar", level="undergraduate"),
    _sps("/undergraduate/professional-studies/cost-attendance/financial-aid/", "financial", "financial_aid", level="undergraduate"),
]

# --- Peer graduate schools. The discrimination challenge.
PEER_SCHOOLS = [
    _peer("arts-science", "/graduate/arts-science/academic-policies/", "policies", "registrar"),
    _peer("arts-science", "/graduate/arts-science/cost-attendance/financial-aid/", "financial", "financial_aid"),
    _peer("business", "/graduate/business/academic-policies/", "policies", "registrar"),
    _peer("business", "/graduate/business/student-services/registration/", "registration", "registrar"),
    _peer("engineering", "/graduate/engineering/academic-policies/", "policies", "registrar"),
    _peer("engineering", "/graduate/engineering/cost-attendance/financial-aid/", "financial", "financial_aid"),
    _peer("public-service", "/graduate/public-service/academic-policies/", "policies", "registrar"),
    _peer("public-service", "/graduate/public-service/student-services/registration/", "registration", "registrar"),
    _peer("public-service", "/graduate/public-service/cost-attendance/financial-aid/", "financial", "financial_aid"),
    _peer("social-work", "/graduate/social-work/academic-policies/", "policies", "registrar"),
    _peer("social-work", "/graduate/social-work/cost-attendance/financial-aid/", "financial", "financial_aid"),
    _peer("nursing", "/graduate/nursing/academic-policies/", "policies", "registrar"),
    _peer("nursing", "/graduate/nursing/student-services/registration/", "registration", "registrar"),
    _peer("nursing", "/graduate/nursing/cost-attendance/financial-aid/", "financial", "financial_aid"),
    _peer("culture-education-human-development", "/graduate/culture-education-human-development/academic-policies/", "policies", "registrar"),
    _peer("culture-education-human-development", "/graduate/culture-education-human-development/cost-attendance/financial-aid/", "financial", "financial_aid"),
    _peer("global-public-health", "/graduate/global-public-health/academic-policies/", "policies", "registrar"),
    _peer("individualized-study", "/graduate/individualized-study/academic-policies/", "policies", "registrar"),
    _peer("arts", "/graduate/arts/academic-policies/", "policies", "registrar"),
]

SOURCES: list[Source] = (
    SPS_GRADUATE + SPS_GRADUATE_PROGRAMS + SPS_UNDERGRADUATE + PEER_SCHOOLS
)


def by_slug() -> dict[str, Source]:
    return {s.slug: s for s in SOURCES}
