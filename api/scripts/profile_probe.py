"""End-to-end exercise of the self-reported profile and planner, boundary attempts included.

    .venv/Scripts/python -m scripts.profile_probe

Builds a real profile through the HTTP API as a signed-in student, plans against it, runs
a what-if, and checks that staff cannot reach any of it. Leaves the profile behind so the
UI has something to render; delete via the API or reseed to clear.
"""

import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

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


# A student partway through: both cores done, one concentration course finished, its
# partner planned, plus a Stern elective the catalog cannot place.
PROFILE = [
    *[("MASY1-GC 1015", "completed", "A"), ("MASY1-GC 1115", "completed", "A-"),
      ("MASY1-GC 1215", "completed", "B+"), ("MASY1-GC 1315", "completed", "A")],
    *[("MASY1-GC 1500", "completed", "A-"), ("MASY1-GC 1600", "completed", "B+"),
      ("MASY1-GC 1700", "completed", "A"), ("MASY1-GC 1800", "completed", "B")],
    ("MASY1-GC 2400", "completed", "A-"),
    ("MASY1-GC 2500", "planned", None),
    ("MKTG-GB 2350", "planned", None),
]


def main() -> None:
    student = login("alex.chen@uax.example.edu")

    # --- build the profile
    for code, state, grade in PROFILE:
        body = {"course_code": code, "state": state}
        if grade:
            body["grade"] = grade
        r = student.put("/api/v1/profile/courses", json=body)
        if r.status_code != 200:
            check(f"add {code}", False, f"{r.status_code} {r.text[:120]}")
            return
    check("built profile", True, f"{len(PROFILE)} courses")

    r = student.get("/api/v1/profile/courses")
    entries = r.json()
    check("profile reads back", len(entries) == len(PROFILE), f"{len(entries)} entries")

    off_catalog = [e for e in entries if not e["in_catalog"]]
    check(
        "off-catalog course kept and flagged",
        len(off_catalog) == 1 and off_catalog[0]["course_code"] == "MKTG-GB 2350",
        f"{[e['course_code'] for e in off_catalog]}",
    )

    graded_plan = [e for e in entries if e["state"] == "planned" and e["grade"]]
    check("grades stripped from non-completed courses", not graded_plan, f"{graded_plan}")

    # --- plan today
    r = student.get("/api/v1/profile/plan")
    plan = r.json()
    check("plan returns", r.status_code == 200, f"{r.status_code}")
    check(
        "credits counted from catalog only",
        plan["credits_completed"] == 27,
        f"completed={plan['credits_completed']} (9 catalog courses x3)",
    )
    conc = next(f for f in plan["findings"] if f["summary"].startswith("Concentration"))
    check(
        "concentration incomplete today",
        conc["verdict"] == "not_satisfied" and "2500" in conc["detail"],
        conc["summary"],
    )
    unverifiable = [f for f in plan["findings"] if f["verdict"] == "unverifiable"]
    check(
        "off-catalog course surfaces as unverifiable",
        any("MKTG-GB 2350" in f["summary"] or "MKTG-GB 2350" in f["detail"] for f in unverifiable),
        f"{len(unverifiable)} unverifiable findings",
    )
    check("disclaimer present on plan", "Albert" in plan["disclaimer"])
    check(
        "rules cite their source",
        bool(plan["program_source_url"]) and bool(plan["rules_verified_on"]),
        f"{plan['rules_verified_on']}",
    )

    # --- plan counting what is planned
    r = student.get("/api/v1/profile/plan", params={"include_planned": "true"})
    projected = r.json()
    conc2 = next(f for f in projected["findings"] if f["summary"].startswith("Concentration"))
    check(
        "concentration completes once planned course counts",
        conc2["verdict"] == "satisfied",
        conc2["summary"],
    )

    # --- what-if without saving
    r = student.post(
        "/api/v1/profile/plan/what-if",
        json={"courses": [{"course_code": "MASY1-GC 4115", "state": "planned"}]},
    )
    whatif = r.json()
    cap = next(f for f in whatif["findings"] if f["summary"].startswith("Capstone"))
    check("what-if satisfies capstone", cap["verdict"] == "satisfied", cap["summary"])

    after = student.get("/api/v1/profile/courses").json()
    check(
        "what-if did not persist",
        not any(e["course_code"] == "MASY1-GC 4115" for e in after),
        f"{len(after)} entries still",
    )

    # --- what-if on a course whose prerequisite is unmet
    r = student.post(
        "/api/v1/profile/plan/what-if",
        json={"courses": [{"course_code": "MASY1-GC 2100", "state": "planned"}]},
    )
    blocked = r.json()
    prereq = [f for f in blocked["findings"] if "Prerequisite" in f["summary"]]
    check(
        "what-if reports the unmet prerequisite",
        any(f["verdict"] == "not_satisfied" for f in prereq),
        "; ".join(f["summary"] for f in prereq) or "no prerequisite findings",
    )

    # --- boundaries
    advisor = login("maya.patel@uax.example.edu")
    for method, path in (("get", "/api/v1/profile/courses"), ("get", "/api/v1/profile/plan")):
        r = getattr(advisor, method)(path)
        check(f"advisor blocked from {path}", r.status_code == 403, f"got {r.status_code}")

    r = advisor.put(
        "/api/v1/profile/courses", json={"course_code": "MASY1-GC 1015", "state": "completed"}
    )
    check("advisor cannot write a profile", r.status_code == 403, f"got {r.status_code}")

    anon = TestClient(app)
    r = anon.get("/api/v1/profile/plan")
    check("anonymous blocked from plan", r.status_code == 401, f"got {r.status_code}")

    # --- report
    width = max(len(n) for _, n, _ in results)
    print()
    for passed, name, detail in results:
        print(f"  [{'ok  ' if passed else 'FAIL'}] {name:<{width}}  {detail}")
    failed = [n for p, n, _ in results if not p]
    print(f"\n{len(results) - len(failed)}/{len(results)} held")

    print("\n--- plan as the student would read it ---")
    mark = {"satisfied": "OK ", "conditional": "IF ", "unverifiable": "?  ", "not_satisfied": "NO "}
    for f in plan["findings"]:
        print(f"  {mark[f['verdict']]} {f['summary']}")
    print(f"\n  counts: {json.dumps(plan['counts'])}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
