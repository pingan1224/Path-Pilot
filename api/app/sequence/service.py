"""Database glue for sequence planning.

Thin on purpose: load the program rules and the user's own stated record, hand both to the
pure planner, return what came back. Every decision worth arguing about lives in `plan.py`
and `solver.py`, where it is testable without a database.

Like the profile and mission services, this reads `user_id`'s own record and nothing else —
there is no path here that takes a student id from a caller.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.planning.loader import load_program_rules
from app.planning.types import StatedCourse
from app.sequence.delay import delay_costs
from app.sequence.plan import ASSUMED_CREDIT_CAP, DEFAULT_HORIZON, build_sequence
from app.sequence.terms import Season, Term
from app.sequence.types import SequencePlan
from app.services.profile import program_for_user, stated_record

# Roughly when each term starts, for picking a sensible default start term. Approximate on
# purpose: this only decides which term the form is pre-filled with, and the alternative —
# reading real term dates — would tie the planner to the `terms` table, which holds demo
# fixtures a real student has nothing to do with.
_TERM_START_MONTH = {Season.spring: 1, Season.summer: 6, Season.fall: 9}


def next_registerable_term(today: datetime | None = None) -> Term:
    """The next term a student could plausibly be planning for.

    A default, not a claim. Path Pilot cannot see enrollment appointment dates, so it has no way to
    know which term is actually open to them — the UI lets them change it, and the answer
    says which term it was computed for.
    """
    now = today or datetime.now(UTC)
    for season in (Season.spring, Season.summer, Season.fall):
        if now.month < _TERM_START_MONTH[season]:
            return Term.of(season, now.year)
    return Term.of(Season.spring, now.year + 1)


def sequence_for_user(
    session: Session,
    user_id: int,
    *,
    start_term: Term | None = None,
    deadline: Term | None = None,
    max_credits_per_term: int | None = None,
    horizon: int = DEFAULT_HORIZON,
    program_code: str | None = None,
    defer: str | None = None,
) -> tuple[SequencePlan, dict]:
    if program_code is None:
        program_code = program_for_user(session, user_id).code
    program = load_program_rules(session, program_code)
    # The same record the planner evaluates, mission-confirmed courses included: a course
    # the student confirmed for next term is one the sequence must place, not one it gets
    # to rediscover as still outstanding.
    stated = stated_record(session, user_id)

    start = start_term or next_registerable_term()
    cap = max_credits_per_term or ASSUMED_CREDIT_CAP

    plan = build_sequence(
        program,
        stated,
        start_term=start,
        deadline=deadline,
        max_credits_per_term=cap,
        horizon=horizon,
        credit_cap_was_assumed=max_credits_per_term is None,
        defer=defer,
    )

    # What each of next term's courses costs if it waits. Computed alongside the plan
    # rather than behind a second endpoint: the reason a course is on the list is not a
    # detail view of the list, it is the answer.
    costs = delay_costs(
        program,
        stated,
        start_term=start,
        deadline=deadline,
        max_credits_per_term=cap,
        horizon=horizon,
    )

    meta = {
        "program_name": program.name,
        "program_source_url": program.source_url,
        "rules_verified_on": program.verified_on,
        "start_term": str(start),
        "deadline": str(deadline) if deadline else None,
        "max_credits_per_term": cap,
        "credit_cap_was_assumed": max_credits_per_term is None,
        "courses_stated": len(stated),
        "delay_costs": costs,
        # Echoed so the caller can tell a what-if answer from the baseline one. The
        # sequence endpoint computes and stores nothing, so a deferral is a question
        # asked, never a plan saved — and the UI has to be able to say which it is
        # looking at.
        "deferred": defer,
    }
    return plan, meta


__all__ = ["next_registerable_term", "sequence_for_user"]
