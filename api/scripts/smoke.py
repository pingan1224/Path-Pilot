"""Exercise every endpoint against a running API and print a condensed result.

    .venv/Scripts/python -m scripts.smoke

Uses FastAPI's in-process test client, so no server needs to be running. This is a smoke
test, not a test suite — it confirms the wiring holds end to end and prints enough of each
payload to eyeball. Real assertions arrive with the P4 harness.

Caveat worth fixing before P4: the write-path checks create a real case in whatever
database DATABASE_URL points at, so running this against the demo database leaves a stray
"Smoke test case" behind. Re-run `scripts.seed --reset` afterwards, or point the tests at a
separate database once one exists.
"""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def call(method: str, path: str, **kwargs) -> tuple[int, object]:
    response = getattr(client, method)(path, **kwargs)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text


def show(
    title: str, status: int, body: object, keys: list[str] | None = None, expect: int = 0
) -> None:
    # `expect` exists because the error-contract checks are supposed to return 4xx. Marking
    # them FAIL made a passing run look broken.
    ok = status == expect if expect else status < 400
    flag = "ok  " if ok else "FAIL"
    print(f"\n[{flag}] {status}  {title}")
    if keys and isinstance(body, dict):
        for key in keys:
            print(f"       {key} = {json.dumps(body.get(key), default=str)[:150]}")
    elif isinstance(body, list):
        print(f"       {len(body)} items")
        if body:
            print(f"       first = {json.dumps(body[0], default=str)[:220]}")
    else:
        print(f"       {json.dumps(body, default=str)[:220]}")


def main() -> None:
    status, body = call("get", "/api/v1/health/ready")
    show("health/ready", status, body, ["status", "checks"])

    status, students = call("get", "/api/v1/students")
    show("students", status, students)

    by_name = {s["full_name"]: s["id"] for s in students} if isinstance(students, list) else {}

    for name in ("Alex Chen", "Priya Raman", "Diego Morales"):
        student_id = by_name.get(name)
        if student_id is None:
            print(f"\n[FAIL] {name} not found in roster")
            continue

        status, body = call("get", f"/api/v1/students/{student_id}/readiness")
        show(
            f"readiness — {name}",
            status,
            body,
            ["status", "status_label", "status_action", "status_reason",
             "credits_applied", "credits_unapplied", "percent_complete",
             "terms_required", "terms_remaining"],
        )

        status, body = call("get", f"/api/v1/students/{student_id}/blockers")
        show(f"blockers — {name}", status, body)

    status, advisors = call("get", "/api/v1/advisors")
    show("advisors", status, advisors)

    if isinstance(advisors, list) and advisors:
        advisor_id = advisors[0]["id"]
        status, body = call("get", f"/api/v1/advisors/{advisor_id}/queue")
        show(
            f"advisor queue — {advisors[0]['full_name']}",
            status,
            body,
            ["caseload", "at_risk_count", "open_escalations", "resolved_this_week"],
        )
        if isinstance(body, dict):
            groups: dict[str, int] = {}
            for entry in body.get("entries", []):
                groups[entry["group"]] = groups.get(entry["group"], 0) + 1
            print(f"       groups = {json.dumps(groups)}")

    status, body = call("get", "/api/v1/registrar/pressure")
    show(
        "registrar pressure",
        status,
        body,
        ["term_name", "total_attempts", "failed_attempts", "failure_rate_percent",
         "sections_at_capacity", "students_with_blocking_holds"],
    )
    if isinstance(body, dict):
        top = body.get("failure_breakdown", [])[:3]
        print(f"       top reasons = {json.dumps([(b['label'], b['attempts']) for b in top])}")

    status, body = call("get", "/api/v1/cases")
    show("cases", status, body)

    # --- Write path: create a case, then move it forward.
    student_id = by_name.get("Priya Raman")
    status, created = call(
        "post",
        "/api/v1/cases",
        json={
            "student_id": student_id,
            "category": "registration_issue",
            "title": "Smoke test case",
            "message": "Created by scripts/smoke.py",
        },
    )
    show("create case", status, created, ["case_number", "status", "status_label"])

    if status == 201 and isinstance(created, dict):
        status, updated = call(
            "patch",
            f"/api/v1/cases/{created['id']}",
            json={"status": "in_review", "note": "Picked up by smoke test"},
        )
        show("patch case", status, updated, ["case_number", "status", "status_label"])
        if isinstance(updated, dict):
            print(f"       events = {len(updated.get('events', []))}")

    # --- Error contract.
    status, body = call("get", "/api/v1/students/999999/readiness")
    show("404 shape (expected)", status, body, expect=404)

    status, body = call(
        "post", "/api/v1/cases", json={"student_id": 1, "category": "nope", "title": "x", "message": ""}
    )
    show("422 shape (expected)", status, body, expect=422)

    print()


if __name__ == "__main__":
    main()
