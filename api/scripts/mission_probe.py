"""Walk a registration mission from empty to complete, and try to cheat it.

    .venv/Scripts/python -m scripts.mission_probe

The unit tests prove the step engine computes the right state from given facts. This proves
the facts arrive correctly through the real HTTP surface — and, more importantly, that the
paths which must *not* advance a mission do not:

- an assistant proposal sitting on the mission does not complete the candidates step
- the agent tool layer has no way to confirm one
- a handoff produced before a later change stops counting
- another student's mission id is not readable

Runs in-process against the real app, so the same dependency graph the deployed API uses.
Leaves the mission behind for the UI to render.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db.session import get_sessionmaker
from app.main import app
from app.models import Mission, User

TERM = "Fall 2026"
STUDENT = "priya.raman@pathpilot.example.edu"
OTHER_STUDENT = "diego.morales@pathpilot.example.edu"

# Requires MASY1-GC 2000, which the profile below does not report — so confirming it is
# guaranteed to produce a blocker, and the accept-a-risk path is actually exercised rather
# than skipped whenever the fixture happens to be clean.
BLOCKED_COURSE = "MASY1-GC 2100"

# Confirmed after the handoff is generated, to prove a later change un-finishes the mission.
LATE_ADDITION = "MASY1-GC 1600"

# A term the student never asks for, so the assistant-opened container is unambiguous.
AI_TERM = "Summer 2028"


def _default_term_is_disclosed(user_id: int) -> bool:
    """An omitted term must be filled in AND flagged, not silently chosen.

    Run against a throwaway term so it cannot collide with the rest of the probe: what is
    asserted is the disclosure flag, not which term the default landed on.
    """
    from app.models import UserRole
    from app.services.agent_tools import ToolContext, tool_start_mission

    with get_sessionmaker()() as session:
        ctx = ToolContext(
            session=session, acting_role=UserRole.student, subject_student_id=None,
            user_id=user_id, mode="live",
        )
        result = tool_start_mission(ctx)  # no term
        ok = result.get("term_was_assumed") is True and bool(result.get("term"))

        # Clean up so the defaulted mission does not linger into later assertions.
        from app.missions.service import close_mission, open_missions

        for mission in open_missions(session, user_id):
            if mission.term == result.get("term"):
                close_mission(session, user_id, mission.id, reason="probe cleanup")
    return ok

results: list[tuple[bool, str, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((passed, name, detail))


def login(email: str) -> TestClient:
    client = TestClient(app)
    r = client.post(
        "/api/v1/auth/login", json={"email": email, "password": settings.demo_password}
    )
    assert r.status_code == 200, f"{email}: {r.status_code} {r.text[:150]}"
    return client


def step(mission: dict, step_id: str) -> dict:
    return next(s for s in mission["steps"] if s["id"] == step_id)


def main() -> None:
    student = login(STUDENT)

    # --- start clean: close and delete any mission left by an earlier run
    with get_sessionmaker()() as session:
        user_id = session.scalar(select(User.id).where(User.email == STUDENT))
        other_id = session.scalar(select(User.id).where(User.email == OTHER_STUDENT))
        for row in session.scalars(
            select(Mission).where(Mission.user_id == user_id)
        ).all():
            session.delete(row)
        session.commit()

    # --- the profile has to exist first. profile_probe leaves one behind; if it has not
    #     run, seed the minimum so this probe is not silently testing an empty record.
    existing = student.get("/api/v1/profile/courses").json()
    if not existing:
        for code, state in (("MASY1-GC 1500", "completed"), ("MASY1-GC 2400", "completed")):
            student.put("/api/v1/profile/courses", json={"course_code": code, "state": state})
        existing = student.get("/api/v1/profile/courses").json()
    check("profile exists to plan against", len(existing) > 0, f"{len(existing)} course(s)")

    # --- the assistant opening a container. Approved 2026-08-07: the widest write the
    #     agent has, so the probe pins down exactly how wide it is.
    with get_sessionmaker()() as session:
        from app.models import UserRole
        from app.services.agent_tools import ToolContext, tool_start_mission

        ctx = ToolContext(
            session=session, acting_role=UserRole.student, subject_student_id=None,
            user_id=user_id, mode="live",
        )
        opened = tool_start_mission(ctx, term=AI_TERM)
        opened_again = tool_start_mission(ctx, term=AI_TERM)

    ai_missions = [m for m in student.get("/api/v1/missions").json() if m["term"] == AI_TERM]
    check(
        "the assistant can open an empty mission container",
        len(ai_missions) == 1 and ai_missions[0]["created_by"] == "ai",
        f"{len(ai_missions)} mission(s), created_by={ai_missions[0]['created_by'] if ai_missions else None}",
    )
    check(
        "opening one twice does not duplicate it",
        opened_again.get("already_existed") is True and len(ai_missions) == 1,
        f"already_existed={opened_again.get('already_existed')}",
    )
    check(
        "AN AGENT-OPENED MISSION DECIDES NOTHING",
        ai_missions[0]["candidates"] == []
        and not ai_missions[0]["complete"]
        and ai_missions[0]["accepted_risks"] == [],
        f"candidates={len(ai_missions[0]['candidates'])} complete={ai_missions[0]['complete']}",
    )
    check(
        "an omitted term is defaulted and disclosed as assumed",
        _default_term_is_disclosed(user_id),
        "",
    )
    student.post(f"/api/v1/missions/{ai_missions[0]['id']}/close", json={"reason": "probe cleanup"})

    # --- create
    r = student.post("/api/v1/missions", json={"term": TERM})
    check("mission created", r.status_code == 201, f"got {r.status_code} {r.text[:120]}")
    if r.status_code != 201:
        report()
        raise SystemExit(1)
    mission = r.json()
    mission_id = mission["id"]

    check(
        "a fresh mission starts past the profile step",
        step(mission, "profile")["state"] == "done"
        and mission["current_step"] == "gaps",
        f"current={mission['current_step']}",
    )
    check(
        "later steps are blocked, not merely pending",
        all(
            step(mission, s)["state"] == "blocked"
            for s in ("candidates", "open_items", "handoff")
        ),
        "",
    )

    # --- the assistant proposes. This is the boundary that matters.
    with get_sessionmaker()() as session:
        from app.models import UserRole
        from app.services.agent_tools import (
            ToolContext,
            tool_get_mission_state,
            tool_propose_mission_candidates,
        )

        ctx = ToolContext(
            session=session,
            acting_role=UserRole.student,
            subject_student_id=None,
            user_id=user_id,
            mode="live",
        )
        proposal = tool_propose_mission_candidates(
            ctx,
            courses=[
                {"course_code": "MASY1-GC 2500", "why": "finishes the concentration"},
                {"course_code": "MASY1-GC 4115", "why": "the capstone"},
            ],
        )
        tool_view = tool_get_mission_state(ctx)

    check(
        "the assistant can propose courses",
        len(proposal.get("proposed", [])) == 2,
        f"proposed={proposal.get('proposed')}",
    )
    check(
        "a proposal reports itself as awaiting the student",
        proposal.get("status") == "awaiting the student's confirmation",
        proposal.get("status", ""),
    )

    mission = student.get(f"/api/v1/missions/{mission_id}").json()
    proposed = [c for c in mission["candidates"] if c["state"] == "proposed"]
    check(
        "proposals land on the mission unconfirmed",
        len(proposed) == 2 and all(c["proposed_by"] == "ai" for c in proposed),
        f"{len(proposed)} proposed",
    )
    check(
        "TWO AI PROPOSALS DO NOT COMPLETE THE CANDIDATES STEP",
        step(mission, "candidates")["state"] != "done",
        f"candidates step = {step(mission, 'candidates')['state']}",
    )
    check(
        "the agent's own view of the mission agrees it is not advanced",
        tool_view["current_step"] in ("gaps", "candidates") and not tool_view["complete"],
        f"tool says current={tool_view['current_step']}",
    )
    check(
        "the propose tool exposes no way to confirm",
        "confirmed" not in str(
            next(
                s
                for s in __import__(
                    "app.services.agent_tools", fromlist=["TOOL_SCHEMAS"]
                ).TOOL_SCHEMAS
                if s["function"]["name"] == "propose_mission_candidates"
            )["function"]["parameters"]
        ),
        "no confirm parameter in the schema",
    )

    # --- the student acknowledges the gap review
    mission = student.post(f"/api/v1/missions/{mission_id}/acknowledge-gaps").json()
    check(
        "acknowledging gaps advances to choosing courses",
        step(mission, "gaps")["state"] == "done"
        and mission["current_step"] == "candidates",
        f"current={mission['current_step']}",
    )

    # --- the student confirms one proposal and declines the other
    to_confirm = next(c for c in mission["candidates"] if c["course_code"] == "MASY1-GC 2500")
    to_decline = next(c for c in mission["candidates"] if c["course_code"] == "MASY1-GC 4115")

    mission = student.post(
        f"/api/v1/missions/{mission_id}/candidates/{to_confirm['id']}/decision",
        json={"confirm": True},
    ).json()
    check(
        "the student's confirmation is what completes the step",
        step(mission, "candidates")["state"] == "done",
        f"current={mission['current_step']}",
    )

    student.post(
        f"/api/v1/missions/{mission_id}/candidates/{to_decline['id']}/decision",
        json={"confirm": False},
    )
    mission = student.get(f"/api/v1/missions/{mission_id}").json()
    declined = next(c for c in mission["candidates"] if c["course_code"] == "MASY1-GC 4115")
    check("a declined proposal stays declined", declined["state"] == "declined", "")

    # --- an assistant re-proposal must not undo the student's decline
    with get_sessionmaker()() as session:
        from app.models import UserRole
        from app.services.agent_tools import ToolContext, tool_propose_mission_candidates

        ctx = ToolContext(
            session=session, acting_role=UserRole.student, subject_student_id=None,
            user_id=user_id, mode="live",
        )
        again = tool_propose_mission_candidates(
            ctx, courses=[{"course_code": "MASY1-GC 4115", "why": "reconsider the capstone"}]
        )
    mission = student.get(f"/api/v1/missions/{mission_id}").json()
    declined = next(c for c in mission["candidates"] if c["course_code"] == "MASY1-GC 4115")
    check(
        "re-proposing a declined course does not reopen it",
        declined["state"] == "declined" and again.get("proposed") == [],
        f"state={declined['state']} proposed={again.get('proposed')}",
    )

    # --- open items. Forced rather than hoped for: MASY1-GC 2100 requires 2000, which this
    #     profile does not report, so confirming it must produce a blocker. Leaving this to
    #     whatever the fixture happened to contain would let the probe pass without ever
    #     exercising the accept-a-risk path — the same trap the chunking ablation fell into.
    mission = student.post(
        f"/api/v1/missions/{mission_id}/candidates", json={"course_code": BLOCKED_COURSE}
    ).json()
    blockers = mission["open_blockers"]
    check(
        f"choosing {BLOCKED_COURSE} with its prerequisite unreported creates a blocker",
        len(blockers) > 0,
        f"{len(blockers)} blocker(s)",
    )
    check(
        "a blocker on a chosen course holds the mission open",
        mission["current_step"] == "open_items" and not mission["complete"],
        f"current={mission['current_step']}",
    )
    if not blockers:
        report()
        raise SystemExit(1)

    first = blockers[0]
    check(
        "the blocker names the course the student chose, not a degree requirement",
        first["subject"] == BLOCKED_COURSE,
        f"subject={first['subject']}",
    )

    # Accepting a *different* key must not release it.
    mission = student.post(
        f"/api/v1/missions/{mission_id}/accepted-risks",
        json={"finding_key": "requirement:Electives", "finding_summary": "unrelated"},
    ).json()
    check(
        "accepting an unrelated finding does not release the blocker",
        step(mission, "open_items")["state"] != "done",
        f"open_items={step(mission, 'open_items')['state']}",
    )
    student.delete(f"/api/v1/missions/{mission_id}/accepted-risks/requirement:Electives")

    mission = student.post(
        f"/api/v1/missions/{mission_id}/accepted-risks",
        json={
            "finding_key": first["key"],
            "finding_summary": first["summary"],
            "note": "I have taken the equivalent elsewhere and will ask my advisor.",
        },
    ).json()
    check(
        "accepting the blocker by name releases the step",
        step(mission, "open_items")["state"] == "done" and not mission["open_blockers"],
        f"current={mission['current_step']}",
    )
    check(
        "the acceptance is recorded with how the finding read at the time",
        any(
            r["finding_key"] == first["key"] and r["accepted_summary"] == first["summary"]
            for r in mission["accepted_risks"]
        ),
        "",
    )
    check(
        "withdrawing an acceptance brings the blocker back",
        step(
            student.delete(
                f"/api/v1/missions/{mission_id}/accepted-risks/{first['key']}"
            ).json(),
            "open_items",
        )["state"]
        != "done",
        "",
    )
    # Put it back so the mission can finish.
    mission = student.post(
        f"/api/v1/missions/{mission_id}/accepted-risks",
        json={
            "finding_key": first["key"],
            "finding_summary": first["summary"],
            "note": "I have taken the equivalent elsewhere and will ask my advisor.",
        },
    ).json()

    # --- degree gaps must not be blockers
    check(
        "degree-level gaps are reported separately from blockers",
        len(mission["degree_findings"]) > 0
        and all(f["subject"] is None for f in mission["degree_findings"]),
        f"{len(mission['degree_findings'])} degree finding(s)",
    )

    # --- handoff completes the mission
    r = student.post(f"/api/v1/missions/{mission_id}/handoff", json={"question": None})
    body = r.json()
    mission = body["mission"]
    check("handoff generated", r.status_code == 200 and len(body["text"]) > 200, "")
    check(
        "the handoff names the term and the chosen course",
        TERM in body["text"] and "MASY1-GC 2500" in body["text"],
        "",
    )
    check("MISSION COMPLETE", mission["complete"] is True, f"current={mission['current_step']}")

    # --- the assistant must not be able to un-finish it either.
    #
    # The obvious direction of this boundary is "a proposal cannot complete a step". The
    # direction that actually broke was the reverse: a pending suggestion counted as a
    # material change, so the assistant could reopen a finished mission just by suggesting
    # something. Found by running the real agent against a completed mission.
    with get_sessionmaker()() as session:
        from app.models import UserRole
        from app.services.agent_tools import ToolContext, tool_propose_mission_candidates

        ctx = ToolContext(
            session=session, acting_role=UserRole.student, subject_student_id=None,
            user_id=user_id, mode="live",
        )
        tool_propose_mission_candidates(
            ctx, courses=[{"course_code": "MASY1-GC 1700", "why": "an idea for later"}]
        )
    mission = student.get(f"/api/v1/missions/{mission_id}").json()
    check(
        "A PROPOSAL CANNOT UN-FINISH A COMPLETED MISSION",
        mission["complete"] is True,
        f"complete={mission['complete']} current={mission['current_step']}",
    )
    check(
        "but the suggestion is still visible for the student to consider",
        any(
            c["course_code"] == "MASY1-GC 1700" and c["state"] == "proposed"
            for c in mission["candidates"]
        ),
        "",
    )

    # --- and a later change must un-finish it.
    #
    # Confirming another course rather than re-saving a profile row: an idempotent PUT that
    # writes the same values changes no timestamp, so on the probe's second run it was not a
    # change at all and this assertion passed or failed depending on run order. Correct
    # behaviour, useless test.
    mission = student.post(
        f"/api/v1/missions/{mission_id}/candidates", json={"course_code": LATE_ADDITION}
    ).json()
    check(
        "A CHANGE AFTER THE HANDOFF REOPENS IT",
        mission["complete"] is False and mission["current_step"] == "handoff",
        f"complete={mission['complete']} current={mission['current_step']}",
    )
    check(
        "and says why, rather than silently reverting",
        bool(step(mission, "handoff")["note"]),
        (step(mission, "handoff")["note"] or "")[:70],
    )

    # --- cross-student boundary
    other = login(OTHER_STUDENT)
    r = other.get(f"/api/v1/missions/{mission_id}")
    check(
        "another student cannot read this mission",
        r.status_code == 404,
        f"got {r.status_code} (404 not 403 — an id that is not yours must not be confirmed as real)",
    )
    r = other.post(
        f"/api/v1/missions/{mission_id}/candidates", json={"course_code": "MASY1-GC 2100"}
    )
    check("another student cannot add to it", r.status_code == 404, f"got {r.status_code}")

    anon = TestClient(app)
    r = anon.get(f"/api/v1/missions/{mission_id}")
    check("unauthenticated read rejected", r.status_code == 401, f"got {r.status_code}")

    assert other_id is not None  # used only to prove the fixture has a second student
    report()
    if [n for p, n, _ in results if not p]:
        raise SystemExit(1)

    print("\n--- the mission as the student would read it ---")
    mission = student.get(f"/api/v1/missions/{mission_id}").json()
    marks = {"done": "[x]", "active": "[>]", "blocked": "[ ]"}
    for s in mission["steps"]:
        print(f"  {marks[s['state']]} {s['title']}")
        print(f"        {s['criterion']}")
        if s["what_now"]:
            print(f"        next: {s['what_now']}")
        if s["note"]:
            print(f"        note: {s['note']}")


def report() -> None:
    width = max(len(n) for _, n, _ in results)
    print()
    for passed, name, detail in results:
        print(f"  [{'ok  ' if passed else 'FAIL'}] {name:<{width}}  {detail}")
    failed = [n for p, n, _ in results if not p]
    print(f"\n{len(results) - len(failed)}/{len(results)} held")


if __name__ == "__main__":
    main()
