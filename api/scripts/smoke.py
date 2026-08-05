"""Exercise every endpoint as a signed-in caller and print a condensed result.

    .venv/Scripts/python -m scripts.smoke

In-process TestClient, one session per role, demo credentials from settings. This is the
happy-path sweep; the adversarial counterpart is scripts/authz_probe.py, and the pair is
the point — this file proves the allowed paths work, the probe proves the forbidden ones
fail.

Writes one probe case into whatever database DATABASE_URL points at; re-run
`scripts.seed --reset` for a pristine demo state.
"""

import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def login(email: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": settings.demo_password}
    )
    assert response.status_code == 200, f"{email}: {response.status_code} {response.text[:150]}"
    return client


def show(title: str, response, keys: list[str] | None = None, expect: int = 200) -> None:
    ok = response.status_code == expect
    print(f"\n[{'ok  ' if ok else 'FAIL'}] {response.status_code}  {title}")
    try:
        body = response.json()
    except ValueError:
        return
    if keys and isinstance(body, dict):
        for key in keys:
            print(f"       {key} = {json.dumps(body.get(key), default=str)[:140]}")
    elif isinstance(body, list):
        print(f"       {len(body)} items")


def main() -> None:
    student = login("alex.chen@uax.example.edu")
    advisor = login("maya.patel@uax.example.edu")
    registrar = login("jordan.lee@uax.example.edu")

    me = student.get("/api/v1/auth/me")
    show("auth/me (student)", me, ["full_name", "role", "student_id"])
    student_id = me.json()["student_id"]

    show(
        "own readiness",
        student.get(f"/api/v1/students/{student_id}/readiness"),
        ["status", "status_reason", "credits_applied", "percent_complete"],
    )
    show("own blockers", student.get(f"/api/v1/students/{student_id}/blockers"))
    show("own cases", student.get("/api/v1/cases"))

    created = student.post(
        "/api/v1/cases",
        json={"category": "registration_issue", "title": "Smoke test case", "message": "from smoke.py"},
    )
    show("create case (self)", created, ["case_number", "status_label"], expect=201)

    show(
        "advisor queue",
        advisor.get("/api/v1/advisors/queue"),
        ["advisor_name", "caseload", "at_risk_count", "open_escalations"],
    )
    show("advisor roster (caseload-scoped)", advisor.get("/api/v1/students"))
    if created.status_code == 201:
        show(
            "advisor patches the new case",
            advisor.patch(f"/api/v1/cases/{created.json()['id']}", json={"status": "in_review"}),
            ["case_number", "status_label"],
        )

    show(
        "registrar pressure",
        registrar.get("/api/v1/registrar/pressure"),
        ["term_name", "total_attempts", "failure_rate_percent", "sections_at_capacity"],
    )

    show("health/ready", TestClient(app).get("/api/v1/health/ready"), ["status", "checks"])
    print()


if __name__ == "__main__":
    main()
