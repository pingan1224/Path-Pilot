"""What a readiness verdict is allowed to claim, and the one number behind it.

Both properties here were unguarded until 2026-08-13, and both were changed that day with
the suite staying green — 377 tests had nothing to say about either. That is the reason
this file exists rather than a note in a commit message.

**The verdict may only talk about degree progress.** Readiness used to read hold status and
its healthiest verdict ended "and nothing is currently blocking registration". The data
behind that sentence was a fixture, and the sentence is the half a student acts on: believe
it and you skip the Albert check that mattered. Removing the data without removing the
reassurance would have left the worse half of the change.

**One assumed per-term load, not two.** `services.readiness` assumed 12 credits and
`sequence.plan` assumed 9, so the same student got two different finish dates depending on
which surface they asked. Survivable while readiness was a badge; not once the graduation
date became the constraint the whole plan is justified against.
"""

import re

from app.models import ReadinessStatus
from app.sequence.plan import ASSUMED_CREDIT_CAP
from app.services.readiness import MAX_CREDITS_PER_TERM, _classify

# Words that would put the verdict back inside Albert. `clear` catches "your record is
# clear"; `block` catches the sentence this file was written about.
ALBERT_CLAIMS = re.compile(
    r"\bhold(s)?\b|\bblock(s|ing|ed)?\b|\bcleared?\b|\bbalance\b|\bappointment\b",
    re.IGNORECASE,
)

# Every branch `_classify` can reach, as (kwargs, expected status).
BRANCHES = [
    (
        dict(can_finish=False, terms_required=4, terms_remaining=2,
             capstone_remaining=3, credits_remaining=30),
        ReadinessStatus.at_risk,
    ),
    (
        dict(can_finish=True, terms_required=3, terms_remaining=3,
             capstone_remaining=0, credits_remaining=18),
        ReadinessStatus.watchlist,
    ),
    (
        dict(can_finish=True, terms_required=1, terms_remaining=4,
             capstone_remaining=0, credits_remaining=6),
        ReadinessStatus.on_track,
    ),
    (
        dict(can_finish=True, terms_required=0, terms_remaining=None,
             capstone_remaining=0, credits_remaining=0),
        ReadinessStatus.on_track,
    ),
]


def test_no_verdict_claims_anything_only_albert_knows():
    offenders = []
    for kwargs, _ in BRANCHES:
        _, reason = _classify(**kwargs)
        # The on-track verdict is allowed to name the boundary — "whether anything else
        # blocks registration ... is only visible in Albert" is the disclosure, not a
        # claim. It is distinguished by pointing at Albert in the same sentence.
        if ALBERT_CLAIMS.search(reason) and "Albert" not in reason:
            offenders.append(reason)
    assert offenders == [], (
        "a readiness verdict asserted something only Albert knows: " + repr(offenders)
    )


def test_every_branch_still_returns_the_status_it_is_for():
    """Guards the deletion itself: dropping the hold branch must not have shifted a
    student from one verdict into another."""
    for kwargs, expected in BRANCHES:
        status, reason = _classify(**kwargs)
        assert status is expected, f"{kwargs} -> {status}, expected {expected}"
        assert reason.strip(), "every verdict must say why"


def test_the_two_assumed_credit_caps_are_one_number():
    """Not "they happen to be equal" — readiness imports the planner's constant, so they
    cannot drift apart again without someone deleting that import on purpose."""
    assert MAX_CREDITS_PER_TERM is ASSUMED_CREDIT_CAP
