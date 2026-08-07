"""When a course is offered, read out of the bulletin's own words.

`courses.typically_offered` is free text lifted from the course descriptions, and the
distribution across the 57 ingested MASY courses is the reason this module has three
outcomes instead of one:

    18  (nothing at all)
    16  "Fall, Spring, and Summer terms"
     7  "Fall and Spring"
     5  "Fall"
     4  "Spring"
     2  "all terms"
     2  "Spring and Summer"
     2  "occasionally"
     1  "Summer term"

So a third of the catalog says nothing about when it runs, and two courses say
"occasionally", which is the bulletin telling you not to plan around them.

The tempting default is to treat silence as "available every term" — it makes the solver
succeed more often and every schedule it produces look confident. It is also the one choice
that can hurt somebody: a student builds a three-term plan around a course that runs in
alternate springs, finds out at registration, and has lost the term they would have used to
take it. Silence is `unstated`, it is carried through to the answer as an assumption the
student has to check, and a placement that rests on it says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.sequence.terms import Season

ALL_SEASONS = frozenset(Season)

_SEASON_WORDS = {
    "fall": Season.fall,
    "autumn": Season.fall,
    "spring": Season.spring,
    "summer": Season.summer,
}

# Phrases meaning "all of them", which no season-word scan would catch.
_EVERY_TERM = ("all terms", "every term", "each term", "all semesters")

# The bulletin declining to commit. Distinguished from silence because it is *evidence*
# that the course is irregular, which is more actionable than an absent field.
_IRREGULAR = ("occasional", "varies", "as needed", "on demand", "tbd", "alternate")


class OfferingBasis(str, Enum):
    published = "published"
    # The bulletin says the schedule is irregular. Treated as any-term for search, and
    # flagged harder than silence, because here the source is actively warning you.
    irregular = "irregular"
    # The field is empty. Not evidence of anything, and must not be read as "every term".
    unstated = "unstated"


@dataclass(frozen=True)
class Offering:
    seasons: frozenset[Season]
    basis: OfferingBasis
    # The bulletin's own words, kept so a placement can quote what it was based on.
    source_text: str | None = None

    @property
    def is_assumption(self) -> bool:
        """True when the season set was assumed rather than read."""
        return self.basis is not OfferingBasis.published

    def allows(self, season: Season) -> bool:
        return season in self.seasons

    def describe(self) -> str:
        if self.basis is OfferingBasis.published:
            return "offered " + ", ".join(s.value for s in _ordered(self.seasons))
        if self.basis is OfferingBasis.irregular:
            return (
                "the bulletin says this runs irregularly, so any term here is a guess"
            )
        return "the bulletin does not say when this runs, so any term here is a guess"


def _ordered(seasons: frozenset[Season]) -> list[Season]:
    order = {Season.fall: 0, Season.spring: 1, Season.summer: 2}
    return sorted(seasons, key=lambda s: order[s])


def parse_offering(text: str | None) -> Offering:
    raw = (text or "").strip()
    if not raw:
        return Offering(seasons=ALL_SEASONS, basis=OfferingBasis.unstated)

    lowered = raw.lower()

    if any(phrase in lowered for phrase in _EVERY_TERM):
        return Offering(
            seasons=ALL_SEASONS, basis=OfferingBasis.published, source_text=raw
        )

    found = {season for word, season in _SEASON_WORDS.items() if word in lowered}

    # An irregularity marker beats a season word it appears alongside: "occasionally in the
    # fall" is not a commitment to the fall, and reading it as one is the whole failure this
    # module is arranged to avoid.
    if any(marker in lowered for marker in _IRREGULAR):
        return Offering(
            seasons=frozenset(found) or ALL_SEASONS,
            basis=OfferingBasis.irregular,
            source_text=raw,
        )

    if found:
        return Offering(
            seasons=frozenset(found), basis=OfferingBasis.published, source_text=raw
        )

    # Text present but unreadable. Same treatment as silence, and the text is kept so the
    # gap is visible rather than looking like an empty field.
    return Offering(
        seasons=ALL_SEASONS, basis=OfferingBasis.unstated, source_text=raw
    )
