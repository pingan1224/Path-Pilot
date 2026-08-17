"""The Albert verification checklist: what only the registrar's system can answer.

"Mission complete" used to mean "you looked at the steps and settled the risks", while the
student reads it as "you can go and register". This closes that distance — but the only
honest way to close it is to record *that the student went and looked*, because this product
has no Albert access and will not have one.

So the whole module is a bookkeeping exercise over declarations, and its design is set by
the two red lines in `tests/test_albert_redlines.py`, which were written first:

  **No result is ever stored.** `AlbertCheck` has a key, a kind and a date, and no field
  that could hold what the student saw. That is deliberate to the point of being the main
  design constraint: a `clear: bool` would be filled in within a release, and from then on
  every sentence this product prints about holds would be derived from a fixture-shaped
  fact about somebody's official record. Not storing it makes "you have no holds"
  unsayable rather than discouraged.

  **A declaration without a date is not expressible.** `decided_at` is required. A
  dateless tick reads as the system having confirmed something, which is the precise claim
  this product must never make.

Items are derived on every read from the confirmed candidates and the term, exactly as
mission progress is — there is no checklist table and no `checked` column. That also gives
the re-open behaviour for free and without a staleness rule: confirming another course
produces another `seats:` key, which has no matching declaration, so the step is unfinished
again because the checklist *is* the derivation. The roadmap proposed invalidating prior
checks on any material change; that would also reopen `holds` when a course was swapped,
which nothing about a course swap invalidates, and would keep the step permanently open for
a student still editing — the failure the skip escape exists to prevent. Checks older than
the last material change are noted instead (see `steps`), never revoked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.services.agent_tools import ALBERT_ONLY_TOPICS

# The topics a student must go and look at before registering, and the only three left.
# Time conflicts were the fourth until scheduling was ruled out of scope on 2026-08-17 —
# Albert refuses to register a clashing section anyway, so there was never anything for the
# student to *check*, only something for a scheduler to arrange.
#
# Keys are finding-key shaped (`topic` or `topic:subject`) so they read the same as an
# accepted risk in the audit trail and can be matched the same way.
# Not term-scoped and not course-scoped: a hold is on the student, so its key is bare.
RECORD_TOPICS: tuple[str, ...] = ("holds",)
# Term-scoped: an appointment belongs to the term being registered for, so the key carries
# it and a mission for a later term starts this item unchecked.
APPOINTMENT_TOPIC = "enrollment_appointment"
# Course-scoped, one per confirmed candidate.
SEAT_TOPIC = "seats"

# Seat counts are the one item that can be true when checked and false an hour later, so it
# says so beside itself rather than in a footnote.
MOVES_FAST_NOTE = "Seat counts move quickly during registration — check this one last."


class CheckKind(str, Enum):
    checked = "checked"
    # Recorded, not absent. A skip is a decision the student made and the handoff says so;
    # without it the step could never complete for someone with no time to open Albert, and
    # an uncompletable step is a progress bar pretending to be a checklist.
    skipped = "skipped"


@dataclass(frozen=True)
class AlbertCheck:
    """A student's declaration about one checklist item.

    Three fields, and the absence of a fourth is the point — see the module docstring.
    """

    key: str
    kind: CheckKind
    # Required, no default. See `tests/test_albert_redlines.py`.
    decided_at: datetime


# `ALBERT_ONLY_TOPICS` labels address the student ("Holds on your record") because the
# assistant wrote them. The handoff is an email the student sends, so the same item needs a
# phrase in their own voice — "Holds on your record — I checked this" reads as though
# somebody else is speaking in the middle of their sentence.
OWN_WORDS = {
    "holds": "my holds",
    "enrollment_appointment": "when my registration window opens",
}


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    topic: str
    label: str
    where: str
    what: str
    # The same item as the student would say it, for the handoff.
    own_words: str
    check: AlbertCheck | None = None
    moves_fast: bool = False

    @property
    def settled(self) -> bool:
        """Checked or deliberately skipped. Both close the item; only one of them means
        the student looked, which is why the handoff prints them differently."""
        return self.check is not None

    def status_line(self) -> str:
        """What the student is told about this item.

        Every branch is about the declaration and none is about the record. There is
        nothing to read a result from, so there is no branch that could grow into one.
        """
        if self.check is None:
            return "Not checked yet."
        when = self.check.decided_at.date().isoformat()
        if self.check.kind is CheckKind.checked:
            return f"You checked this in Albert on {when}."
        return f"You chose to skip this on {when}."


def _item(
    key: str,
    topic: str,
    check: AlbertCheck | None,
    *,
    label: str | None = None,
    own_words: str | None = None,
):
    default_label, where, what = ALBERT_ONLY_TOPICS[topic]
    return ChecklistItem(
        key=key,
        topic=topic,
        label=label or default_label,
        where=where,
        what=what,
        own_words=own_words or OWN_WORDS[topic],
        check=check,
        moves_fast=topic == SEAT_TOPIC,
    )


def checklist(
    *,
    term: str,
    confirmed_codes: tuple[str, ...],
    checks: tuple[AlbertCheck, ...] = (),
) -> tuple[ChecklistItem, ...]:
    """The current checklist. Recomputed on every read; nothing here is stored.

    Ordered holds → appointment → seats, which is the order they gate each other in: a hold
    stops registration whatever the seats say, and an appointment that has not opened stops
    it whatever the holds say. Seats are per confirmed course and sorted by code so two
    reads of one record agree.
    """
    by_key = {c.key: c for c in checks}

    items = [_item(topic, topic, by_key.get(topic)) for topic in RECORD_TOPICS]

    appointment_key = f"appointment:{term}"
    items.append(_item(appointment_key, APPOINTMENT_TOPIC, by_key.get(appointment_key)))

    for code in sorted(set(confirmed_codes)):
        key = f"{SEAT_TOPIC}:{code}"
        items.append(
            _item(
                key,
                SEAT_TOPIC,
                by_key.get(key),
                label=f"Seats in {code}",
                own_words=f"seats in {code}",
            )
        )

    return tuple(items)


def outstanding(items: tuple[ChecklistItem, ...]) -> tuple[ChecklistItem, ...]:
    return tuple(i for i in items if not i.settled)


def checked_items(items: tuple[ChecklistItem, ...]) -> tuple[ChecklistItem, ...]:
    return tuple(
        i for i in items if i.check is not None and i.check.kind is CheckKind.checked
    )


def skipped_items(items: tuple[ChecklistItem, ...]) -> tuple[ChecklistItem, ...]:
    return tuple(
        i for i in items if i.check is not None and i.check.kind is CheckKind.skipped
    )
