"""The program picker's API contract.

The picker exists because "which program are you in?" used to be answered by a constant.
These tests hold the two properties that made it worth building:

* Only real, catalog-sourced programs are offerable. The demo program is a fixture of
  invented courses, and a live account filed under it would get a degree audit for a degree
  that does not exist.
* An unencoded program is reported as unencoded rather than quietly substituted. That is
  the same boundary the cross-school warning defends, one level up: the failure mode is not
  an error message, it is a fully-cited answer about somebody else's degree.

The endpoints are exercised through the real app so the auth dependency, the session
cookie, and the global exception handlers are all in the path — the handlers are half the
behaviour here, since the UI branches on the error *code*.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.main import app
from app.models import Program, User
from app.services.profile import ENCODED_PROGRAMS

PROBE_EMAIL = "live.probe@pathpilot.example.edu"
PROBE_PASSWORD = "path-pilot-demo-2026"


def _db_available() -> bool:
    try:
        with get_sessionmaker()() as session:
            session.scalar(select(Program.id).limit(1))
        return True
    except Exception:  # noqa: BLE001 — the suite must skip, not fail, without a database
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="needs the seeded dev database"
)


@pytest.fixture
def client():
    """A signed-in client whose program is restored afterwards.

    These tests write: `PUT /profile/program` is the thing under test. Restoring in a
    fixture keeps a failed assertion from leaving the dev database pointing the probe
    account at whatever the last test set.
    """
    with get_sessionmaker()() as session:
        user = session.scalars(select(User).where(User.email == PROBE_EMAIL)).first()
        # The three sibling modules skip here; this one used to read a null program off a
        # missing user and then error nine times on a 401 from the login below, which said
        # nothing about the cause. The seed owns the account now, so this branch should be
        # unreachable — it exists to name itself if that ever stops being true.
        if user is None:
            pytest.skip("live probe account is not seeded")
        original = user.program_id

    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/login",
        json={"email": PROBE_EMAIL, "password": PROBE_PASSWORD},
    )
    assert response.status_code == 200, response.text
    try:
        yield c
    finally:
        with get_sessionmaker()() as session:
            user = session.scalars(
                select(User).where(User.email == PROBE_EMAIL)
            ).first()
            user.program_id = original
            session.commit()


def _unencoded_code(client) -> str:
    programs = client.get("/api/v1/catalog/programs").json()
    return next(p["code"] for p in programs if not p["is_encoded"])


def test_only_catalog_programs_are_listed(client):
    """The demo program must never be selectable by a real account."""
    programs = client.get("/api/v1/catalog/programs").json()
    assert programs, "no programs listed"

    with get_sessionmaker()() as session:
        demo_codes = {
            row.code
            for row in session.scalars(select(Program).where(Program.source == "demo"))
        }
    assert not ({p["code"] for p in programs} & demo_codes)


def test_unencoded_programs_report_no_credit_total(client):
    """An unencoded program's credit total is unknown, and says so with null.

    Zero would assert the degree requires no credits — a number a student could act on.
    """
    for program in client.get("/api/v1/catalog/programs").json():
        if not program["is_encoded"]:
            assert program["total_credits_required"] is None


def test_selecting_a_program_changes_the_reported_capabilities(client):
    encoded = sorted(ENCODED_PROGRAMS)[0]

    body = client.put(
        "/api/v1/profile/program", json={"program_code": encoded}
    ).json()
    assert body["is_encoded"] is True
    assert "degree_audit" in body["capabilities"]

    body = client.put(
        "/api/v1/profile/program", json={"program_code": _unencoded_code(client)}
    ).json()
    assert body["is_encoded"] is False
    # The capability list is the promise. Auditing must disappear from it, not merely fail
    # when tried.
    assert "degree_audit" not in body["capabilities"]
    assert "policy_answers" in body["capabilities"]


def test_an_unknown_program_code_is_rejected(client):
    response = client.put(
        "/api/v1/profile/program", json={"program_code": "NOT-A-PROGRAM"}
    )
    assert response.status_code == 404


def test_a_demo_program_cannot_be_selected(client):
    """Settable is `source='catalog'` only, enforced server-side rather than by omission
    from the list — a client can send any code it likes."""
    with get_sessionmaker()() as session:
        demo = session.scalars(select(Program).where(Program.source == "demo")).first()
    if demo is None:
        pytest.skip("no demo program seeded")

    response = client.put("/api/v1/profile/program", json={"program_code": demo.code})
    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/api/v1/profile/plan", "/api/v1/sequence"])
def test_rule_evaluating_endpoints_refuse_for_an_unencoded_program(client, path):
    """The property this whole change exists for.

    Not merely "does not crash": the response must be the *refusal*, carrying a code the
    UI can distinguish from "you have not said what you study". A 200 here would mean some
    other program's requirements were applied.
    """
    client.put("/api/v1/profile/program", json={"program_code": _unencoded_code(client)})

    response = client.get(path)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "program_not_encoded"


def test_a_refused_mission_writes_nothing(client):
    """Refuse before writing, not after.

    Creating the row and then failing to render it leaves a mission that can never be
    read — `mission_state` raises on load — and that each retry reopens. Found by probing
    this exact path.
    """
    client.put("/api/v1/profile/program", json={"program_code": _unencoded_code(client)})

    with get_sessionmaker()() as session:
        user_id = session.scalar(select(User.id).where(User.email == PROBE_EMAIL))
        from app.models import Mission

        before = len(
            session.scalars(select(Mission).where(Mission.user_id == user_id)).all()
        )

    response = client.post("/api/v1/missions", json={"term": "Spring 2027"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "program_not_encoded"

    with get_sessionmaker()() as session:
        from app.models import Mission

        after = len(
            session.scalars(select(Mission).where(Mission.user_id == user_id)).all()
        )
    assert after == before, "a refused mission left a row behind"


def test_me_reports_the_program_so_the_ui_need_not_guess(client):
    client.put("/api/v1/profile/program", json={"program_code": _unencoded_code(client)})

    me = client.get("/api/v1/auth/me").json()
    assert me["program_code"] is not None
    assert me["program_is_encoded"] is False
