"""Attempt to break the authorization boundary, and report what held.

    .venv/Scripts/python -m scripts.authz_probe

Every check is an attack, not a happy path. A permissions test that only confirms allowed
actions succeed proves nothing — the claim being made is that forbidden actions *fail*,
and that is what has to be exercised. Runs in-process against the real app, so it
exercises the same dependency graph the deployed API uses.

This probe used to have four actors and spent most of its length on the boundaries between
them: a student refused the registrar board, an advisor refused a colleague's advisee, a
finance officer seeing financial cases and nothing else. Those surfaces are gone, and the
probe did not shrink to match by deleting the interesting half. Two things replaced them:

  * The boundary that always mattered most is now exercised from both sides. Alex and Diego
    are both signable, so "a student cannot read another student's record" is checked in
    each direction rather than inferred from one.
  * The staff surfaces are checked for absence, at two layers. The routes must be gone
    (404, not 403 — a 403 would mean the endpoint is still mounted and merely guarded), and
    an advisor account must not be able to authenticate at all. A login that cannot happen
    is a stronger statement than a dashboard that answers 403.
"""

from pathlib import Path

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
        advisor_account = session.scalars(
            select(User).where(User.role == UserRole.advisor)
        ).first()
        alex_id, diego_id = alex.id, diego.id
        alex_email, diego_email = alex.user.email, diego.user.email
        advisor_email = advisor_account.email if advisor_account else None
        assert alex_id != diego_id, "fixture no longer exercises two distinct students"

    anon = TestClient(app)

    # --- unauthenticated
    for path in (
        f"/api/v1/students/{alex_id}/readiness",
        f"/api/v1/students/{alex_id}/blockers",
        "/api/v1/cases",
    ):
        r = anon.get(path)
        check(f"anon GET {path}", r.status_code == 401, f"got {r.status_code}")

    r = anon.post("/api/v1/assistant/ask", json={"question": "why am I blocked?"})
    check("anon POST /assistant/ask", r.status_code == 401, f"got {r.status_code}")

    # --- the removed staff surfaces. 404 rather than 403 is the point: these are not
    #     endpoints behind a permission check, they are endpoints that no longer exist.
    student = client_for(alex_email)
    for path in ("/api/v1/registrar/pressure", "/api/v1/advisors/queue", "/api/v1/students"):
        r = student.get(path)
        check(f"{path} is gone, not guarded", r.status_code == 404, f"got {r.status_code}")

    if advisor_email:
        r = TestClient(app).post(
            "/api/v1/auth/login", json={"email": advisor_email, "password": PASSWORD}
        )
        check(
            "an advisor account cannot authenticate at all",
            r.status_code == 401,
            f"got {r.status_code}",
        )
    else:
        check("an advisor account cannot authenticate at all", False, "no advisor seeded")

    # --- one student against another, in both directions
    other = client_for(diego_email)

    r = student.get(f"/api/v1/students/{alex_id}/readiness")
    check("student reads own readiness", r.status_code == 200, f"got {r.status_code}")

    r = student.get(f"/api/v1/students/{diego_id}/readiness")
    check(
        "student CANNOT read another student's readiness",
        r.status_code == 403,
        f"got {r.status_code}",
    )

    r = other.get(f"/api/v1/students/{alex_id}/blockers")
    check(
        "the same refusal holds in the other direction",
        r.status_code == 403,
        f"got {r.status_code}",
    )

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
        leaked = "Diego" in body["answer"] or "Morales" in body["answer"]
        ok = not leaked
        detail = "answered without leaking the other student" if ok else "LEAKED other student"
    check("role/student_id in body are ignored (privilege escalation)", ok, detail)

    # --- cases
    r = student.post(
        "/api/v1/cases",
        json={"category": "general_support", "title": "Probe case", "message": "from authz_probe"},
    )
    ok = r.status_code == 201
    probe_case_id = r.json()["id"] if ok else None
    check("student opens a case about self", ok, f"got {r.status_code}")

    if probe_case_id:
        r = student.get(f"/api/v1/cases/{probe_case_id}")
        check("student reads own case", r.status_code == 200, f"got {r.status_code}")

        # 404, not 403. Whether case 812 exists is itself information about another
        # student's record, so a case that is not yours reads exactly like one that is not
        # there — the same answer an id plucked out of the air gets.
        r = other.get(f"/api/v1/cases/{probe_case_id}")
        check(
            "another student's case is indistinguishable from a missing one",
            r.status_code == 404,
            f"got {r.status_code}",
        )

        leaked = any(c["id"] == probe_case_id for c in other.get("/api/v1/cases").json())
        check("case list is scoped to the caller", not leaked, "scoped" if not leaked else "LEAKED")

        # Status transitions were staff-only; with no staff there is no writer at all, so
        # the route is gone rather than forbidden.
        r = student.patch(f"/api/v1/cases/{probe_case_id}", json={"status": "resolved"})
        check("nobody can move a case status", r.status_code == 405, f"got {r.status_code}")

    # --- error decoder. It reads the pasted message and the caller's own self-reported
    # courses, so the boundary that matters is whose record it reaches — never a path
    # parameter's, always the session's.
    r = anon.post("/api/v1/decoder/decode", json={"text": "ERR_PREREQ: Requisites not met"})
    check("decoder rejects an unauthenticated caller", r.status_code == 401, f"got {r.status_code}")

    r = student.post(
        "/api/v1/decoder/decode",
        json={"text": "ERR_PREREQ: Requisites not met for this class (MASY1-GC 2100)"},
    )
    check(
        "decoder answers the signed-in student",
        r.status_code == 200 and r.json()["reason"] == "prerequisite_not_met",
        f"got {r.status_code}",
    )

    # --- sequence planner. Scoped to the caller's own record, like the planner it derives
    # from, and it must say out loud what it assumed.
    r = anon.get("/api/v1/sequence")
    check("unauthenticated sequence rejected", r.status_code == 401, f"got {r.status_code}")

    r = student.get("/api/v1/sequence")
    if r.status_code == 200:
        body = r.json()
        # A schedule that omitted what it assumes would be the most authoritative-looking
        # thing this product prints and the least examinable.
        check(
            "a sequence always states what it assumes",
            body["credit_cap_was_assumed"] is True and len(body["assumptions"]) > 0,
            f"{len(body['assumptions'])} assumption(s)",
        )
    else:
        check("a sequence always states what it assumes", False, f"got {r.status_code}")

    # --- transcript intake. The most sensitive upload in the product, so the reading writes
    # nothing until a separate confirm, and it lands on the uploader's own record only.
    fixture = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "transcript_table.pdf"
    if fixture.exists():
        pdf = fixture.read_bytes()
        files = {"file": ("t.pdf", pdf, "application/pdf")}

        r = anon.post("/api/v1/intake/transcript", files=files)
        check("unauthenticated upload rejected", r.status_code == 401, f"got {r.status_code}")

        r = student.post(
            "/api/v1/intake/transcript",
            files={"file": ("x.pdf", b"not a pdf at all", "application/pdf")},
        )
        check(
            "a file that is not a PDF is refused, not guessed at",
            r.status_code == 422,
            f"got {r.status_code}",
        )

        before = len(student.get("/api/v1/profile/courses").json())
        other_before = len(other.get("/api/v1/profile/courses").json())

        r = student.post("/api/v1/intake/transcript", files=files)

        after = len(student.get("/api/v1/profile/courses").json())
        check(
            "READING A TRANSCRIPT WRITES NOTHING",
            r.status_code == 200 and before == after,
            f"{before} -> {after} course(s) after upload",
        )

        other_after = len(other.get("/api/v1/profile/courses").json())
        check(
            "and nothing lands on the other student either",
            other_before == other_after,
            f"{other_before} -> {other_after} course(s) on the other student",
        )
    else:
        check(
            "transcript fixtures present",
            False,
            "run tests.fixtures.make_transcripts",
        )

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
