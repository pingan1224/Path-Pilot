"""Shapes the mission engine speaks in.

The mission exists to give the assistant something it has never had: **a termination
condition**. Every previous turn in this system was a stateless question and answer, which
means the agent had no notion of a task being finished — only of a reply being sent. A task
with a decidable end changes what the agent is for. It also changes what can go wrong, so
the end has to be decidable in the strict sense: computable from stored facts, with no
judgement call and no model in the loop.

Five steps, each requiring a human act. An earlier draft had six, with a separate
"prerequisite checks" step between choosing courses and collecting open items. It was cut
because the student does nothing there — the engine evaluates candidates the instant they
are confirmed, so the step would complete itself the moment the previous one did. A step
that cannot be worked on is not a step; it is a progress bar pretending to be one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.missions.albert import AlbertCheck, ChecklistItem
from app.planning.types import Finding, StatedCourse


class StepId(str, Enum):
    profile = "profile"
    gaps = "gaps"
    candidates = "candidates"
    open_items = "open_items"
    # Sixth, added 2026-08-17, and positioned *before* the handoff on purpose: the handoff
    # lists what was checked and what was skipped, so producing it first would send an
    # advisor a document that omits the answer to the question they would ask next.
    #
    # It raises the bar, which is the point — "complete" now also means the Albert-only
    # facts have been declared looked at. An existing mission that was complete reopens
    # here, correctly: it was completed against the older, weaker criterion.
    albert_check = "albert_check"
    handoff = "handoff"


# Declaration order is the mission order, and the engine reads it from here rather than
# hard-coding a sequence in two places.
STEP_ORDER: tuple[StepId, ...] = tuple(StepId)


class StepState(str, Enum):
    done = "done"
    # The one thing to work on now. Exactly one step is active in an unfinished mission.
    active = "active"
    # An earlier step is unfinished. Deliberately not "pending": the student needs to know
    # this is waiting on something specific, not merely later in a list.
    blocked = "blocked"


class CandidateState(str, Enum):
    proposed = "proposed"
    confirmed = "confirmed"
    declined = "declined"


@dataclass(frozen=True)
class Candidate:
    """A course under consideration, and who put it there."""

    course_code: str
    state: CandidateState
    proposed_by: str  # 'student' | 'ai'
    rationale: str | None = None
    created_at: datetime | None = None
    decided_at: datetime | None = None

    @property
    def counts_toward_the_plan(self) -> bool:
        """Only a confirmed candidate is planned coursework.

        This property is the whole proposal/confirmation boundary in one line. An
        assistant suggestion sits in the mission visibly and changes nothing about its
        state until a person says yes.
        """
        return self.state is CandidateState.confirmed


@dataclass(frozen=True)
class AcceptedRisk:
    """A blocker the student has seen and chosen to carry anyway."""

    finding_key: str
    # How the finding read when they accepted it. Compared against the current wording so
    # a risk that has since grown is re-surfaced rather than silently covered.
    accepted_summary: str | None
    accepted_at: datetime
    note: str | None = None


@dataclass(frozen=True)
class MissionFacts:
    """Everything the engine is allowed to look at.

    A frozen bundle rather than a session, for the same reason `planning.rules` takes rules
    and a stated record: the step computation cannot reach the database, so a step's state
    cannot depend on query order, lazy loading, or what happened to be cached. Every branch
    below is reachable from a literal in a test.
    """

    term: str
    stated_courses: tuple[StatedCourse, ...]
    candidates: tuple[Candidate, ...]
    # Findings from evaluating the profile *plus* the confirmed candidates as planned work.
    findings: tuple[Finding, ...]
    accepted_risks: tuple[AcceptedRisk, ...] = ()
    # What the student says they went and looked at in Albert. Declarations only — see
    # `missions.albert` on why no outcome is stored alongside them.
    albert_checks: tuple[AlbertCheck, ...] = ()
    acknowledged_gaps_at: datetime | None = None
    handoff_recorded_at: datetime | None = None
    # The most recent time any of the above materially changed: a profile edit, a candidate
    # confirmed or declined, a risk accepted. Used to decide whether an acknowledgement or
    # a generated handoff still describes the current situation.
    last_material_change_at: datetime | None = None

    @property
    def confirmed(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.counts_toward_the_plan)

    @property
    def proposed(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.state is CandidateState.proposed)

    @property
    def accepted_keys(self) -> frozenset[str]:
        return frozenset(r.finding_key for r in self.accepted_risks)


@dataclass(frozen=True)
class Step:
    id: StepId
    title: str
    # What has to be true for this step to be done, in words the student can check against
    # the screen. A criterion nobody can read is indistinguishable from a stored flag.
    criterion: str
    state: StepState
    # What to do next, when there is something to do.
    what_now: str | None = None
    # The facts that produced this state, for the UI and for the audit trail.
    evidence: tuple[str, ...] = ()
    # A caveat that does not change the state: "you reviewed this before your last edit".
    note: str | None = None


@dataclass(frozen=True)
class MissionState:
    term: str
    steps: tuple[Step, ...]
    complete: bool
    # None when the mission is complete.
    current: StepId | None
    # Blockers on the confirmed candidates that are neither resolved nor accepted. This is
    # the list that has to be empty for the mission to finish.
    open_blockers: tuple[Finding, ...] = ()
    # Accepted risks whose finding now reads differently than it did when accepted.
    stale_acceptances: tuple[AcceptedRisk, ...] = ()
    # The Albert checklist as it currently derives, each item carrying its declaration or
    # none. Exposed on the state because the UI, the handoff and the audit trail all read
    # the same derivation rather than each recomputing it from decisions.
    albert_items: tuple[ChecklistItem, ...] = field(default_factory=tuple)
    # Degree-level findings — the content of the gaps step. Kept separate from
    # open_blockers on purpose: "your capstone is still outstanding" is true and is not a
    # reason you cannot register for next term, and pooling the two would either block a
    # registration on a future requirement or bury a real blocker in a list of them.
    degree_findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps if s.state is StepState.done)

    def step(self, step_id: StepId) -> Step:
        return next(s for s in self.steps if s.id == step_id)
