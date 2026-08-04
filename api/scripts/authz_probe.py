"""Attempt to break the authorization boundary, and report what held.

    .venv/Scripts/python -m scripts.authz_probe

Every check is an attack, not a happy path. A permissions test that only confirms allowed
actions succeed proves nothing — the claim being made is that forbidden actions *fail*,
and that is what has to be exercised. Runs in-process against the real app, so it
exercises the same dependency graph the deployed API uses.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db.session import get_sessionmaker
from app.main import app
from app.models import Student, User, UserRole

PASSWORD = settings.demo_password
results: list[tuple[bool, str, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    results.append((passed, name, detail))


def client_for(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    return c


def main() -> None:
    with get_sessionmaker()() as session:
        alex = session.scalars(
            select(Student).join(User, User.id == Student.user_id)
            .where(User.full_name == "Alex Chen")
        ).first()
        diego = session.scalars(
            select(Student).join(User, User.id == Student.user_id)
            .where(User.full_name == "Diego Morales")
        ).first()
        # Diego's advisor is Tom Becker; Maya Patel advises Alex. Cross-caseload access
        # is therefore a real boundary and not an artefact of the fixture.
        maya = session.scalars(
            select(User).where(User.full_name == "Maya Patel")
        ).first()
        alex_id, diego_id = alex.id, diego.id
        alex_email = alex.user.email
        assert diego.advisor_id != maya.id, "fixture no longer exercises cross-caseload"

    anon = TestClient(app)

    # --- unauthenticated
    for path in (
        f"/api/v1/students/{alex_id}/readiness",
        "/api/v1/registrar/pressure",
        "/api/v1/advisors/queue",
    ):
        r = anon.get(path)
        check(f"anon GET {path}", r.status_code == 401, f"got {r.status_code}")

    r = anon.post("/api/v1/assistant/ask", json={"question": "why am I blocked?"})
    check("anon POST /assistant/ask", r.status_code == 401, f"got {r.status_code}")

    # --- student
    student = client_for(alex_email)

    r = student.get(f"/api/v1/students/{alex_id}/readiness")
    check("student reads own readiness", r.status_code == 200, f"got {r.status_code}")

    r = student.get(f"/api/v1/students/{diego_id}/readiness")
    check(
        "student CANNOT read another student's readiness",
        r.status_code == 403,
        f"got {r.status_code}",
    )

    r = student.get(f"/api/v1/students/{diego_id}/blockers")
    check(
        "student CANNOT read another student's blockers",
        r.status_code == 403,
        f"got {r.status_code}",
    )

    r = student.get("/api/v1/registrar/pressure")
    check("student CANNOT open registrar dashboard", r.status_code == 403, f"got {r.status_code}")

    r = student.get("/api/v1/advisors/queue")
    check("student CANNOT open an advising queue", r.status_code == 403, f"got {r.status_code}")

    r = student.get("/api/v1/students")
    check("student CANNOT list the student roster", r.status_code == 403, f"got {r.status_code}")

    # The old API took `role` and `student_id` in the body. Sending them now must not
    # change anything: extra fields are ignored and identity comes from the session.
    r = student.post(
        "/api/v1/assistant/ask",
        json={
            "question": "Do I have any holds?",
            "role": "advisor",
            "student_id": diego_id,
        },
    )
    ok = r.status_code == 200
    detail = f"got {r.status_code}"
    if ok:
        body = r.json()
        # The answer must be about Alex, from a student-scoped session.
        leaked = "Tom Becker" in body["answer"] or "Diego" in body["answer"]
        ok = not leaked
        detail = "answered without leaking the other student" if ok else "LEAKED other student"
    check("role/student_id in body are ignored (privilege escalation)", ok, detail)

    # --- advisor
    advisor = client_for("maya.patel@uax.example.edu")

    r = advisor.get("/api/v1/advisors/queue")
    ok = r.status_code == 200
    caseload = r.json()["caseload"] if ok else 0
    check("advisor reads own queue", ok, f"caseload {caseload}")

    r = advisor.get(f"/api/v1/students/{alex_id}/readiness")
    check("advisor reads an advisee", r.status_code == 200, f"got {r.status_code}")

    r = advisor.get(f"/api/v1/students/{diego_id}/readiness")
    check(
        "advisor CANNOT read a colleague's advisee",
        r.status_code == 403,
        f"got {r.status_code}",
    )

    r = advisor.get("/api/v1/students")
    ok = r.status_code == 200
    n = len(r.json()) if ok else -1
    check("advisor roster is scoped to caseload", ok and n == caseload, f"{n} rows vs caseload {caseload}")

    r = advisor.get("/api/v1/registrar/pressure")
    check("advisor CANNOT open registrar dashboard", r.status_code == 403, f"got {r.status_code}")

    # --- registrar
    registrar = client_for("jordan.lee@uax.example.edu")
    r = registrar.get("/api/v1/registrar/pressure")
    check("registrar reads own dashboard", r.status_code == 200, f"got {r.status_code}")
    r = registrar.get("/api/v1/advisors/queue")
    check("registrar CANNOT open an advising queue", r.status_code == 403, f"got {r.status_code}")

    # --- session hygiene
    student.post("/api/v1/auth/logout")
    r = student.get(f"/api/v1/students/{alex_id}/readiness")
    check("session is dead after logout", r.status_code == 401, f"got {r.status_code}")

    bad = TestClient(app)
    r = bad.post("/api/v1/auth/login", json={"email": alex_email, "password": "wrong"})
    check("wrong password rejected", r.status_code == 401, f"got {r.status_code}")
    r2 = bad.post(
        "/api/v1/auth/login", json={"email": "nobody@uax.example.edu", "password": "wrong"}
    )
    check(
        "unknown account and wrong password are indistinguishable",
        r.json() == r2.json(),
        "identical responses" if r.json() == r2.json() else "responses differ (enumeration oracle)",
    )

    # --- report
    width = max(len(name) for _, name, _ in results)
    print()
    for passed, name, detail in results:
        print(f"  [{'ok  ' if passed else 'FAIL'}] {name:<{width}}  {detail}")
    failed = [n for p, n, _ in results if not p]
    print(f"\n{len(results) - len(failed)}/{len(results)} held")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
