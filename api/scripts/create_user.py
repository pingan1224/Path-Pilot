"""Create a real account, or reset its password.

    .venv/Scripts/python -m scripts.create_user ada@example.com --name "Ada Lovelace"
    .venv/Scripts/python -m scripts.create_user ada@example.com --name "Ada Lovelace" \
        --program MASY-MS-REAL
    .venv/Scripts/python -m scripts.create_user ada@example.com --reset

Until this existed the only way to admit a real user was a hand-written INSERT with a
hand-computed scrypt hash, which is why the product had no real users. This is the F1 tier
of three: an operator runs it, reads the password out, and sends it to the person by
whatever channel they already trust. F2 (invite codes the user redeems) and F3 (self-serve
registration) both wait on the M12 rate limiting, and are the reason this one stays
deliberately small.

**"One-time password" is what the plan called it, and it would be a lie here.** There is
no redemption step and no change-password flow yet, so what this prints is the account's
standing credential until F2 lands. Treat it as one: send it over something private, and
use `--reset` rather than digging it out of a terminal buffer later. It is hashed on the
way in and printed exactly once, because storing it in recoverable form is the thing this
script exists to avoid.

Three things it deliberately cannot do:

- **Create anything but a student.** Advisor accounts exist so a handoff has a name on it,
  and their `password_hash` is null precisely so no staff surface can be reached by
  signing in — `scripts/authz_probe.py` checks that from both directions. A `--role` flag
  would put one command between that property and its opposite.
- **Create a `Student` row.** The absence of one is what puts a turn in live mode, where
  the agent gets the nine-tool surface and no fixture record. A real account with a
  student fixture attached would be a demo account wearing a real email.
- **Touch a `@pathpilot.example.edu` address.** Every seeded fixture lives on that domain,
  including the live probe account four test modules sign in as with the shared demo
  password. Resetting one of those to a fresh random password breaks those tests in a way
  that looks like a code failure. The seed owns that domain; this script owns the rest.
"""

from __future__ import annotations

import argparse
import secrets
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.models import Program, Student, User, UserRole
from app.services.auth import hash_password
from app.services.profile import ENCODED_PROGRAMS

# The *same* validator `POST /auth/login` puts its payload through, and it has to be. A
# hand-rolled "is there an @ in it" check passed addresses the login schema then rejected
# with a 422 — so the operator would create an account, hand over a password, and the
# person on the other end could not sign in with it and could not tell why. Caught by
# driving the script end to end; no unit test of this script would have found it, because
# the bug lives in the gap between two validators.
_EMAIL = TypeAdapter(EmailStr)

# The domain every seeded fixture lives on. Reserved — see the module docstring.
FIXTURE_DOMAIN = "@pathpilot.example.edu"

# No I/l/1/O/0: this gets read off a terminal and typed into a login form, and a password
# that cannot be transcribed is a support ticket rather than a security measure.
ALPHABET = "abcdefghijkmnpqrstuvwxyzACDEFGHJKLMNPQRSTUVWXYZ23456789"
GROUPS, GROUP_LEN = 4, 5


class RefusedError(Exception):
    """Something the operator asked for that this script will not do."""


def generate_password() -> str:
    """Twenty characters from a 54-symbol alphabet, hyphenated for reading aloud."""
    return "-".join(
        "".join(secrets.choice(ALPHABET) for _ in range(GROUP_LEN)) for _ in range(GROUPS)
    )


def _check_email(email: str) -> str:
    email = email.strip().lower()
    try:
        _EMAIL.validate_python(email)
    except ValidationError as error:
        reason = error.errors()[0]["msg"].removeprefix("value is not a valid email address: ")
        raise RefusedError(
            f"{email!r} is not an address this app can sign in with: {reason} "
            "(the login endpoint applies the same rule, so an account created with it "
            "could never be used)."
        ) from error
    if email.endswith(FIXTURE_DOMAIN):
        raise RefusedError(
            f"{email} is on the seed's fixture domain ({FIXTURE_DOMAIN}). Those accounts "
            "are created and owned by `python -m scripts.seed --reset`, and resetting one "
            "here would give it a password the tests that sign in as it do not know."
        )
    return email


def _resolve_program(session: Session, code: str) -> Program:
    """Catalog programmes only, mirroring `PUT /profile/program`.

    The demo programme is built from invented courses, so pointing a real account at it
    would produce a degree audit against a degree that does not exist — a confident,
    correctly-cited answer to a question nobody asked.
    """
    program = session.scalars(
        select(Program).where(Program.code == code, Program.source == "catalog")
    ).first()
    if program is None:
        raise RefusedError(
            f"No catalog programme with code {code!r}. Demo programmes are not selectable "
            "for a real account."
        )
    return program


def create_user(
    session: Session, *, email: str, full_name: str, program_code: str | None = None
) -> tuple[User, str]:
    """Returns the new user and their password. The password is not stored anywhere."""
    email = _check_email(email)
    if session.scalars(select(User).where(User.email == email)).first() is not None:
        raise RefusedError(
            f"{email} already exists. Use --reset to give it a new password."
        )

    program = _resolve_program(session, program_code) if program_code else None

    password = generate_password()
    user = User(
        email=email,
        full_name=full_name.strip(),
        role=UserRole.student,
        password_hash=hash_password(password),
        program_id=program.id if program else None,
    )
    session.add(user)
    session.commit()
    return user, password


def reset_password(session: Session, *, email: str) -> tuple[User, str]:
    email = _check_email(email)
    user = session.scalars(select(User).where(User.email == email)).first()
    if user is None:
        raise RefusedError(f"No account for {email}.")
    if user.role is not UserRole.student:
        # An advisor with a password is a staff login, and there is no staff surface to
        # log in to. See the module docstring.
        raise RefusedError(
            f"{email} is a {user.role.value} account. Only student accounts can sign in."
        )

    password = generate_password()
    user.password_hash = hash_password(password)
    session.commit()
    return user, password


def _report(session: Session, user: User, password: str, *, created: bool) -> None:
    print(f"{'created' if created else 'reset'} : {user.email}  (id {user.id})")
    print(f"name    : {user.full_name}")

    if user.program_id is None:
        print("program : not stated - they pick one on the program page after signing in")
    else:
        program = session.get(Program, user.program_id)
        print(f"program : {program.name} ({program.code})")
        # Said here because it decides what the account can actually do: an unencoded
        # programme still gets policy answers and error decoding, and no degree audit.
        capability = (
            "requirements are encoded - full planning"
            if program.code in ENCODED_PROGRAMS
            else "requirements are NOT encoded - policy answers and decoding only"
        )
        print(f"          {capability}")

    # No Student row, deliberately, and worth stating: it is the difference between a real
    # account and a demo one, and it is invisible from the outside.
    has_student = (
        session.scalars(select(Student).where(Student.user_id == user.id)).first()
        is not None
    )
    print(f"mode    : {'DEMO (has a student fixture!)' if has_student else 'live (no student fixture)'}")

    print()
    print(f"  password: {password}")
    print()
    print("Shown once and not recoverable - it is stored only as a scrypt hash. Send it")
    print("over a private channel; there is no change-password flow until F2, so run")
    print("this again with --reset if it leaks.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a real (non-demo) student account, or reset its password."
    )
    parser.add_argument("email")
    parser.add_argument("--name", help="full name; required unless --reset")
    parser.add_argument(
        "--program",
        help="catalog programme code, e.g. MASY-MS-REAL. Optional - they can pick one "
        "themselves after signing in.",
    )
    parser.add_argument(
        "--reset", action="store_true", help="reset an existing account's password"
    )
    args = parser.parse_args()

    if args.reset and (args.name or args.program):
        parser.error("--reset only changes the password; drop --name and --program.")
    if not args.reset and not args.name:
        parser.error("--name is required when creating an account.")

    with get_sessionmaker()() as session:
        try:
            if args.reset:
                user, password = reset_password(session, email=args.email)
            else:
                user, password = create_user(
                    session,
                    email=args.email,
                    full_name=args.name,
                    program_code=args.program,
                )
        except RefusedError as error:
            raise SystemExit(f"refused: {error}") from error
        _report(session, user, password, created=not args.reset)


if __name__ == "__main__":
    sys.exit(main())
