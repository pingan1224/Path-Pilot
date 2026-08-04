"""Password hashing and session identity.

scrypt from the standard library rather than a bcrypt dependency: it is memory-hard, it
ships with Python, and adding a wheel for a demo login would be the wrong trade. Salt is
per-user and stored with the hash; the format is `scrypt$<n>$<r>$<p>$<salt>$<key>` so the
parameters travel with the record and can be raised later without invalidating old rows.

The important part of this module is not the hashing. It is that `current_user` reads the
caller's identity from a signed session cookie and nothing else — no header, no query
parameter, no request body. Before this, `POST /assistant/ask` accepted `role` from the
client, so every downstream permission check was validating the caller's own claim about
themselves.
"""

import hashlib
import hmac
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import Student, User, UserRole

# Deliberately modest so a demo login stays snappy on free-tier hosting. Production would
# raise n; the parameters live in the stored hash precisely so that is a one-line change.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_LEN
    )
    return "$".join(
        [
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            urlsafe_b64encode(salt).decode(),
            urlsafe_b64encode(key).decode(),
        ]
    )


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_b64, key_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = urlsafe_b64decode(salt_b64)
        expected = urlsafe_b64decode(key_b64)
        actual = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    # Constant-time: a timing-variable comparison here would leak the hash byte by byte.
    return hmac.compare_digest(actual, expected)


class Identity:
    """Who the caller is, resolved server-side.

    `subject_student_id` is the student whose record this caller may act on: their own if
    they are a student, and never populated from a request parameter. Staff roles get
    None here and reach student data through explicitly scoped endpoints instead.
    """

    def __init__(self, user: User, student: Student | None) -> None:
        self.user = user
        self.student = student

    @property
    def role(self) -> UserRole:
        return self.user.role

    @property
    def subject_student_id(self) -> int | None:
        return self.student.id if self.student else None


def current_user(
    request: Request, session: Session = Depends(get_session)
) -> Identity:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not signed in.")

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session is no longer valid.")

    student = session.scalars(select(Student).where(Student.user_id == user.id)).first()
    return Identity(user, student)


def require_roles(*roles: UserRole):
    """Dependency factory restricting an endpoint to specific roles."""

    allowed = set(roles)

    def dependency(identity: Identity = Depends(current_user)) -> Identity:
        if identity.role not in allowed:
            # 403, not 404: the caller is authenticated, the resource exists, and they
            # are not permitted. Pretending otherwise makes real access bugs harder to see.
            raise HTTPException(
                status_code=403,
                detail=f"This view is available to {', '.join(r.value for r in allowed)}.",
            )
        return identity

    return dependency


def require_student_access(identity: Identity, student_id: int, session: Session) -> None:
    """Assert this caller may read that student's record.

    Students may read only their own. Advisors may read their advisees. Registrar and
    finance staff have institution-wide read access within their own scoped views. The
    check lives here so every endpoint touching a student record uses the same rule
    rather than re-deriving it.
    """
    if identity.role == UserRole.student:
        if identity.subject_student_id != student_id:
            raise HTTPException(status_code=403, detail="You may only view your own record.")
        return

    if identity.role == UserRole.advisor:
        student = session.get(Student, student_id)
        if student is None or student.advisor_id != identity.user.id:
            raise HTTPException(
                status_code=403, detail="That student is not on your advising caseload."
            )
        return

    # registrar and finance: institution-wide, but their views are scoped by design.
    return
