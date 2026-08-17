"""Admitting a real user, and the four things that must not be possible while doing it.

The happy path is one INSERT and a hash; it is the refusals that carry the weight, because
each one is a property some other part of the system is relying on:

- an advisor that can sign in would be a staff login, and `scripts/authz_probe.py` asserts
  from both directions that no such thing exists;
- a `Student` row would make the account demo-shaped, and the absence of one is the whole
  mechanism that puts a turn in live mode;
- a fixture-domain address would hand a fresh random password to the account four test
  modules sign in as with the shared demo password;
- a demo programme would audit a real person against invented courses.
"""

import pytest
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import Program, Student, User, UserRole
from app.services.auth import verify_password
from scripts.create_user import (
    ALPHABET,
    FIXTURE_DOMAIN,
    RefusedError,
    create_user,
    generate_password,
    reset_password,
)

EMAIL = "regression.create-user@example.com"


def _db_available() -> bool:
    try:
        with get_sessionmaker()() as session:
            session.scalar(select(User.id).limit(1))
        return True
    except Exception:  # noqa: BLE001 — the suite must skip, not fail, without a database
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="needs the seeded dev database"
)


def _purge(email: str = EMAIL) -> None:
    with get_sessionmaker()() as session:
        for user in session.scalars(select(User).where(User.email == email)).all():
            session.delete(user)
        session.commit()


@pytest.fixture(autouse=True)
def clean():
    _purge()
    yield
    _purge()


# --------------------------------------------------------------------------------------
# What it does
# --------------------------------------------------------------------------------------


def test_the_account_can_sign_in_with_the_printed_password():
    with get_sessionmaker()() as session:
        user, password = create_user(session, email=EMAIL, full_name="Ada Lovelace")
        assert verify_password(password, user.password_hash)
        # The plaintext is returned to be printed and never written.
        assert password not in (user.password_hash or "")


def test_a_real_account_is_live_mode_shaped():
    """No `Student` row and the student role — the two halves of "not a demo account"."""
    with get_sessionmaker()() as session:
        user, _ = create_user(session, email=EMAIL, full_name="Ada Lovelace")
        assert user.role is UserRole.student
        linked = session.scalars(
            select(Student).where(Student.user_id == user.id)
        ).first()
        assert linked is None


def test_email_is_normalised_so_case_cannot_create_a_second_account():
    with get_sessionmaker()() as session:
        user, _ = create_user(session, email=EMAIL.upper(), full_name="Ada Lovelace")
        assert user.email == EMAIL
    with get_sessionmaker()() as session:
        with pytest.raises(RefusedError, match="already exists"):
            create_user(session, email=EMAIL, full_name="Ada Lovelace")


def test_reset_invalidates_the_previous_password():
    with get_sessionmaker()() as session:
        _, first = create_user(session, email=EMAIL, full_name="Ada Lovelace")
    with get_sessionmaker()() as session:
        user, second = reset_password(session, email=EMAIL)
        assert first != second
        assert verify_password(second, user.password_hash)
        assert not verify_password(first, user.password_hash)


def test_a_catalog_programme_can_be_set_at_creation():
    with get_sessionmaker()() as session:
        code = session.scalar(
            select(Program.code).where(Program.source == "catalog").limit(1)
        )
        if code is None:
            pytest.skip("catalog programmes are not ingested")
        user, _ = create_user(
            session, email=EMAIL, full_name="Ada Lovelace", program_code=code
        )
        assert user.program_id is not None


def test_the_password_is_transcribable_and_not_short():
    """It gets read off a terminal and typed into a form; l/1/O/0 are excluded for that."""
    password = generate_password()
    assert len(password.replace("-", "")) == 20
    assert not set("Il1O0") & set(password)
    assert all(c in ALPHABET or c == "-" for c in password)
    assert generate_password() != generate_password()


# --------------------------------------------------------------------------------------
# What it refuses
# --------------------------------------------------------------------------------------


def test_the_seeds_fixture_domain_is_refused():
    """Resetting `live.probe` here would break the modules that sign in as it."""
    with get_sessionmaker()() as session:
        with pytest.raises(RefusedError, match="fixture domain"):
            create_user(
                session, email=f"someone{FIXTURE_DOMAIN}", full_name="Someone"
            )
        with pytest.raises(RefusedError, match="fixture domain"):
            reset_password(session, email=f"live.probe{FIXTURE_DOMAIN}")


def test_an_advisor_cannot_be_given_a_password():
    """Their null hash is what makes "no staff surface" structural rather than a claim."""
    with get_sessionmaker()() as session:
        advisor = session.scalars(
            select(User).where(User.role == UserRole.advisor).limit(1)
        ).first()
        if advisor is None:
            pytest.skip("no advisor accounts seeded")
        # Belt and braces: the fixture-domain guard catches the seeded ones first, and the
        # role check is what would catch an advisor on any other domain.
        with pytest.raises(RefusedError):
            reset_password(session, email=advisor.email)
        session.refresh(advisor)
        assert advisor.password_hash is None


def test_there_is_no_way_to_create_a_non_student():
    """Not a default that can be overridden — no parameter for it exists at all."""
    import inspect

    from scripts import create_user as module

    assert "role" not in inspect.signature(module.create_user).parameters
    parser_source = inspect.getsource(module.main)
    assert "--role" not in parser_source


def test_a_demo_programme_is_refused():
    with get_sessionmaker()() as session:
        code = session.scalar(
            select(Program.code).where(Program.source == "demo").limit(1)
        )
        if code is None:
            pytest.skip("no demo programme seeded")
        with pytest.raises(RefusedError, match="No catalog programme"):
            create_user(
                session, email=EMAIL, full_name="Ada Lovelace", program_code=code
            )
    # And nothing was written on the way to refusing.
    with get_sessionmaker()() as session:
        assert session.scalars(select(User).where(User.email == EMAIL)).first() is None


def test_an_address_the_login_endpoint_would_reject_is_refused_here():
    """The two validators have to be the same one.

    They were not: this script checked for an `@` while `POST /auth/login` runs the payload
    through pydantic's `EmailStr`. Every address in `bad` below is one the old check waved
    through and the login schema then 422s — so the account existed, the operator handed
    over a password, and the person could not sign in and could not tell why. Found by
    driving the script end to end, which is the only place the gap is visible.
    """
    from app.routers.auth import LoginRequest

    bad = ("not-an-email", "@example.com", "trailing@", "ada@example.test", "a b@example.com")
    with get_sessionmaker()() as session:
        for address in bad:
            # First: the login endpoint really would reject it, so the case is not invented.
            with pytest.raises(Exception):
                LoginRequest(email=address, password="x")
            with pytest.raises(RefusedError, match="cannot sign in with|sign in with"):
                create_user(session, email=address, full_name="Ada Lovelace")
