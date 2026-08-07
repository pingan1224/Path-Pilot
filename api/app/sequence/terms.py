"""Academic terms as values you can order and count with.

Small enough to be obvious, separate because the solver needs "three terms from now" to be
arithmetic rather than string handling, and because getting the order wrong is silent: Fall
2026 sorts before Spring 2027 by year, and Spring 2027 sorts before Fall 2027 within one
year, so a naive alphabetical or year-only comparison puts a fall course before the spring
course that is supposed to precede it and the sequence looks fine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Season(str, Enum):
    """The three terms MASY course descriptions actually name.

    NYU also runs winter and January intensive modules. They are deliberately absent:
    nothing in the ingested MASY catalog text mentions them, so a solver that scheduled
    into a January module would be inventing an opportunity rather than finding one.
    """

    spring = "Spring"
    summer = "Summer"
    fall = "Fall"


# Position inside a calendar year. Spring comes first because it does: Fall 2026 precedes
# Spring 2027, and Spring 2027 precedes Fall 2027.
_RANK = {Season.spring: 0, Season.summer: 1, Season.fall: 2}
_BY_RANK = {rank: season for season, rank in _RANK.items()}

TERM_RE = re.compile(
    r"^\s*(?:(spring|summer|fall|autumn)\s*(\d{4})|(\d{4})\s*(spring|summer|fall|autumn))\s*$",
    re.I,
)


class TermParseError(ValueError):
    """The string was not a term this tool understands."""


@dataclass(frozen=True, order=True)
class Term:
    """One academic term. Ordering is by (year, position in year), which `order=True` on
    this field layout gives for free — hence year first."""

    year: int
    season_rank: int

    @property
    def season(self) -> Season:
        return _BY_RANK[self.season_rank]

    @classmethod
    def of(cls, season: Season, year: int) -> Term:
        return cls(year=year, season_rank=_RANK[season])

    @classmethod
    def parse(cls, text: str) -> Term:
        match = TERM_RE.match(text or "")
        if match is None:
            raise TermParseError(
                f"{text!r} is not a term this tool understands. Use a form like "
                '"Fall 2026".'
            )
        name, year, year2, name2 = match.groups()
        raw = (name or name2).lower()
        # "Autumn" appears in some course text; it is the same term as Fall.
        season = Season.fall if raw in ("fall", "autumn") else Season(raw.capitalize())
        return cls.of(season, int(year or year2))

    def next(self) -> Term:
        if self.season_rank == _RANK[Season.fall]:
            return Term(year=self.year + 1, season_rank=_RANK[Season.spring])
        return Term(year=self.year, season_rank=self.season_rank + 1)

    def forward(self, count: int) -> list[Term]:
        """This term and the `count - 1` terms after it."""
        out, current = [], self
        for _ in range(max(count, 0)):
            out.append(current)
            current = current.next()
        return out

    def distance_to(self, other: Term) -> int:
        """How many terms from this one to `other`, counting both ends. 1 means the same."""
        count, current = 1, self
        while current < other:
            current = current.next()
            count += 1
        return count

    def __str__(self) -> str:
        return f"{self.season.value} {self.year}"


def parse_or_none(text: str | None) -> Term | None:
    if not text:
        return None
    try:
        return Term.parse(text)
    except TermParseError:
        return None
