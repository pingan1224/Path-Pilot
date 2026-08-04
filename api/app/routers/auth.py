"""Sign in, sign out, and who-am-I."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import User
from app.services.auth import Identity, current_user, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MeResponse(BaseModel):
    user_id: int
    email: str
    full_name: str
    role: str
    office: str | None
    student_id: int | None
    student_number: str | None


def _me(identity: Identity) -> MeResponse:
    return MeResponse(
        user_id=identity.user.id,
        email=identity.user.email,
        full_name=identity.user.full_name,
        role=identity.role.value,
        office=identity.user.office,
        student_id=identity.subject_student_id,
        student_number=identity.student.student_number if identity.student else None,
    )


@router.post("/login", response_model=MeResponse)
def login(
    payload: LoginRequest, request: Request, session: Session = Depends(get_session)
) -> MeResponse:
    user = session.scalars(
        select(User).where(User.email == payload.email.lower())
    ).first()

    # One message for both "no such account" and "wrong password". Distinguishing them
    # turns the login form into an account-enumeration oracle.
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")

    request.session.clear()
    request.session["user_id"] = user.id

    from app.services.auth import current_user as resolve

    return _me(resolve(request, session))


@router.post("/logout", status_code=204)
def logout(request: Request) -> None:
    request.session.clear()


@router.get("/me", response_model=MeResponse)
def me(identity: Identity = Depends(current_user)) -> MeResponse:
    return _me(identity)
