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
from app.sequence.terms import Season, Term, parse_or_none
from app.sequence.types import SequencePlan
from app.services.profile import get_preferences, program_for_user, stated_record

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
    track: str | None = None,
) -> tuple[SequencePlan, dict]:
    if program_code is None:
        program_code = program_for_user(session, user_id).code
    program = load_program_rules(session, program_code)
    # The same record the planner evaluates, mission-confirmed courses included: a course
    # the student confirmed for next term is one the sequence must place, not one it gets
    # to rediscover as still outstanding.
    stated = stated_record(session, user_id)

    # Three places a constraint can come from, and which one it was is part of the answer.
    # A cap the student saved is their decision; the fallback is the product's guess, and
    # it is already disclosed on screen as "assumed, not a rule". Collapsing them would
    # let a guess wear the authority of a choice — and, in the other direction, would stop
    # the model from saying "your saved 9-credit cap" when it can.
    prefs = get_preferences(session, user_id)

    if max_credits_per_term is not None:
        cap, cap_source = max_credits_per_term, "request"
    elif prefs.max_credits_per_term is not None:
        cap, cap_source = prefs.max_credits_per_term, "saved"
    else:
        cap, cap_source = ASSUMED_CREDIT_CAP, "assumed"

    if deadline is not None:
        deadline_source = "request"
    elif prefs.target_finish_term:
        # Already validated on the way in (PreferencesIn.parseable), so an unparseable
        # value here means the row predates that check — treat it as unsaid rather than
        # failing a solve the student did not ask a question about.
        saved_deadline = parse_or_none(prefs.target_finish_term)
        deadline, deadline_source = saved_deadline, "saved" if saved_deadline else None
    else:
        deadline_source = None

    start = start_term or next_registerable_term()
    start_was_assumed = start_term is None

    plan = build_sequence(
        program,
        stated,
        start_term=start,
        deadline=deadline,
        max_credits_per_term=cap,
        horizon=horizon,
        credit_cap_was_assumed=cap_source == "assumed",
        defer=defer,
        track=track,
    )

    # What each of next term's courses costs if it waits. Computed alongside the plan
    # rather than behind a second endpoint: the reason a course is on the list is not a
    # detail view of the list, it is the answer.
    #
    # **Not computed under an active deferral, and that is the fix rather than a shortcut.**
    # A delay cost is priced against a baseline, and when `defer` is set the baseline on
    # screen is not the one these were solved from: every remaining card kept a price that
    # assumed the deferred course was still in the starting term. `delay_costs` already
    # refuses to answer when there is no baseline to compare against — the same reasoning
    # covers a baseline the caller has replaced. Pricing "what if Y waits *as well*" would
    # be a different question, and the UI does not ask it: it disables deferring while a
    # deferral is up. The what-if's own price is still shown, from the client's remembered
    # un-deferred answer.
    costs = (
        ()
        if defer
        else delay_costs(
            program,
            stated,
            start_term=start,
            deadline=deadline,
            max_credits_per_term=cap,
            horizon=horizon,
        )
    )

    meta = {
        "program_name": program.name,
        "program_source_url": program.source_url,
        "rules_verified_on": program.verified_on,
        "start_term": str(start),
        # The start was disclosed nowhere while the credit cap was labelled "assumed, not
        # a rule" three inches away. Both are guesses when nobody named them, and a
        # schedule that silently begins a term earlier than the student intends is the
        # more expensive of the two to be wrong about.
        "start_was_assumed": start_was_assumed,
        "deadline": str(deadline) if deadline else None,
        "max_credits_per_term": cap,
        "credit_cap_was_assumed": cap_source == "assumed",
        # "request" | "saved" | "assumed" — and None for a deadline nobody has stated.
        # The date is carried with it so the UI and the model can say *when* the student
        # said it: intent goes stale like any other source.
        "credit_cap_source": cap_source,
        "deadline_source": deadline_source,
        "preferences_updated_at": (
            prefs.updated_at.isoformat() if prefs.updated_at else None
        ),
        "courses_stated": len(stated),
        "delay_costs": costs,
        # Echoed so the caller can tell a what-if answer from the baseline one. The
        # sequence endpoint computes and stores nothing, so a deferral is a question
        # asked, never a plan saved — and the UI has to be able to say which it is
        # looking at.
        "deferred": defer,
        # Echoed so the UI can tell "the solver recommended this" from "I asked to see
        # this one" — the same distinction the deferral echo exists for.
        "track_requested": track,
    }
    return plan, meta


__all__ = ["next_registerable_term", "sequence_for_user"]
