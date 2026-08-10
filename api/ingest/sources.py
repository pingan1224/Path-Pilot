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

# Politeness. bulletins.nyu.edu publishes no Crawl-delay, so this is our own restraint.
REQUEST_DELAY_SECONDS = 1.5
USER_AGENT = (
    "path-pilot-portfolio-project/0.1 (personal learning project; +mailto:lsttc1224@gmail.com)"
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
    _sps("/graduate/professional-studies/courses/masy1-gc/", "courses", "department"),
    # Degree requirements for the program the planner supports. The bulletin has no
    # "Management and Systems MS" page; MASY1-GC coursework belongs to Management
    # Analytics, which is the page that states the credit structure.
    _sps("/graduate/professional-studies/programs/management-analytics-ms/", "requirements", "registrar"),
]

# --- Same school, different level. Graduate and undergraduate policies diverge on credit
#     loads, standing, and registration order, so this pair tests whether retrieval keeps
#     the levels apart instead of blending them.
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

SOURCES: list[Source] = SPS_GRADUATE + SPS_UNDERGRADUATE + PEER_SCHOOLS


def by_slug() -> dict[str, Source]:
    return {s.slug: s for s in SOURCES}
