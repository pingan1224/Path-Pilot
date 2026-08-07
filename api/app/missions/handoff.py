"""The advisor handoff, as a deterministic template over mission facts.

A template rather than a generated summary, and that is a considered choice rather than a
placeholder. This document goes to a human who will act on it, and the two properties that
matter are that it is faithful and that it is the same every time. A template is both by
construction. Prose quality is a distant third — an advisor reading a slightly stiff email
that accurately lists what the student reported is better served than one reading a fluent
email that dropped a course.

It also gives the agent version somewhere to be measured against. The plan was always to
try an agent-written handoff that retrieves policy for each unresolved item; without a
deterministic baseline that comparison would be a demo instead of an experiment.

The five sections are the same ones the planner's client-side handoff uses, plus what the
mission knows and the planner does not: which courses were chosen for the term, and which
risks the student has explicitly decided to carry. That last section is the one an advisor
most needs, because it is the difference between a student who missed a problem and one who
saw it and made a call.
"""

from __future__ import annotations

from app.missions.steps import unverifiable_for_handoff
from app.missions.types import MissionFacts
from app.planning.types import CourseState, Verdict

NOTHING = "  (none)"


def _courses(facts: MissionFacts, state: CourseState) -> str:
    lines = [
        f"  - {c.code}" + (f" — {c.grade}" if c.grade else "")
        for c in facts.stated_courses
        if c.state is state
    ]
    return "\n".join(lines) or NOTHING


def build_handoff(
    facts: MissionFacts,
    *,
    program_name: str,
    rules_verified_on: str | None,
    question: str | None = None,
) -> str:
    chosen = "\n".join(f"  - {c.course_code}" for c in facts.confirmed) or NOTHING

    settled = (
        "\n".join(
            f"  - [{'met' if f.verdict is Verdict.satisfied else 'not met'}] {f.summary}"
            for f in facts.findings
            if f.verdict in (Verdict.satisfied, Verdict.not_satisfied)
        )
        or NOTHING
    )

    open_items = (
        "\n".join(f"  - {f.summary}: {f.detail}" for f in unverifiable_for_handoff(facts))
        or "  (nothing outstanding)"
    )

    # Written as decisions, not as problems. The student accepted these knowingly, and
    # presenting them as oversights would misrepresent them to the person reading.
    accepted = (
        "\n".join(
            f"  - {r.accepted_summary or r.finding_key}"
            + (f" — my reasoning: {r.note}" if r.note else "")
            for r in facts.accepted_risks
        )
        or NOTHING
    )

    questions = (
        "\n".join(
            dict.fromkeys(
                f"  - {f.next_step}"
                for f in facts.findings
                if f.next_step and f.verdict is not Verdict.satisfied
            )
        )
        or "  - Does this plan look right to you?"
    )

    rules_line = f"the {program_name} bulletin"
    if rules_verified_on:
        rules_line += f", rules checked {rules_verified_on}"

    return f"""Subject: Registration preparation for {facts.term} — advising question

Hi,

{(question or '').strip() or f"I am getting ready to register for {facts.term} and would like to check my plan with you."}

WHAT I PLAN TO REGISTER FOR ({facts.term}):
{chosen}

MY RECORD AS I UNDERSTAND IT (self-reported — please correct me if Albert says otherwise):

Completed:
{_courses(facts, CourseState.completed)}

Taking now:
{_courses(facts, CourseState.in_progress)}

Planning to take:
{_courses(facts, CourseState.planned)}

WHAT THE PUBLISHED RULES SAY (checked against {rules_line}):
{settled}

WHAT I COULD NOT CONFIRM MYSELF:
{open_items}

RISKS I AM KNOWINGLY CARRYING:
{accepted}

MY QUESTIONS:
{questions}

Generated with UAX, an independent planning tool — not an NYU system, and with no access to
Albert. Everything above is my own report of my record and should be verified.

Thanks!"""
