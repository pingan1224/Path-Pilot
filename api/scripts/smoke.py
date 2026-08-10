"""Exercise every endpoint as a signed-in caller and print a condensed result.

    .venv/Scripts/python -m scripts.smoke

In-process TestClient, one signed-in student, demo credentials from settings. This is the
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
    student = login("alex.chen@pathpilot.example.edu")

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

    if created.status_code == 201:
        show(
            "read the new case back",
            student.get(f"/api/v1/cases/{created.json()['id']}"),
            ["case_number", "status_label", "owner_name"],
        )

    show("own profile courses", student.get("/api/v1/profile/courses"))
    show("own missions", student.get("/api/v1/missions"))
    show(
        "own sequence",
        student.get("/api/v1/sequence"),
        ["credit_cap_was_assumed", "assumptions"],
    )

    show("health/ready", TestClient(app).get("/api/v1/health/ready"), ["status", "checks"])
    print()


if __name__ == "__main__":
    main()
