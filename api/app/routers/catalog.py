"""The real course catalog, for building a profile.

Read-only and student-accessible: picking your courses from the published catalog is the
first step of self-reporting. Only `source='catalog'` rows are served — the invented demo
courses would be actively misleading here.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_session
from app.models import Course, CoursePrerequisite, Program
from app.services.auth import Identity, current_user
from app.services.profile import ENCODED_PROGRAMS

router = APIRouter(prefix="/catalog", tags=["catalog"])


class CatalogProgram(BaseModel):
    code: str
    name: str
    degree: str
    level: str
    # Whether this tool can evaluate degree requirements for this program. False is the
    # common case and is shown to the student rather than hidden: a program that is listed
    # but not encoded still gets policy answers and error decoding, and saying so is the
    # difference between a smaller promise and a broken one.
    is_encoded: bool
    # Null unless the requirements have been encoded — an unencoded program's total is
    # genuinely unknown, and a number here would be invented.
    total_credits_required: int | None
    catalog_url: str | None


@router.get("/programs", response_model=list[CatalogProgram])
def list_programs(
    _: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[CatalogProgram]:
    """The programs a student can say they are in.

    `source='catalog'` only. The demo program is a fixture that exists to drive the seeded
    degree-audit scenarios; offering it here would let a real user file themselves under an
    invented degree made of invented courses.
    """
    rows = session.scalars(
        select(Program).where(Program.source == "catalog").order_by(Program.name)
    )
    return [
        CatalogProgram(
            code=p.code,
            name=p.name,
            degree=p.degree,
            level=p.level,
            is_encoded=p.code in ENCODED_PROGRAMS,
            total_credits_required=p.total_credits_required,
            catalog_url=p.catalog_url,
        )
        for p in rows
    ]


class CatalogCourse(BaseModel):
    code: str
    title: str
    credits: int
    typically_offered: str | None
    # Rendered as the bulletin wrote it, so the student sees the requirement they will
    # actually be held to.
    prerequisites_text: str | None
    catalog_url: str | None
    verified_on: str | None


@router.get("/courses", response_model=list[CatalogCourse])
def search_courses(
    q: str = "",
    _: Identity = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[CatalogCourse]:
    query = (
        select(Course)
        .where(Course.source == "catalog")
        .options(selectinload(Course.prerequisites).selectinload(CoursePrerequisite.prerequisite))
        .order_by(Course.code)
    )
    needle = q.strip()
    if needle:
        query = query.where(
            or_(Course.code.ilike(f"%{needle}%"), Course.title.ilike(f"%{needle}%"))
        )

    out = []
    for course in session.scalars(query.limit(60)):
        raw = next((p.raw_text for p in course.prerequisites if p.raw_text), None)
        out.append(
            CatalogCourse(
                code=course.code,
                title=course.title,
                credits=course.credits,
                typically_offered=course.typically_offered,
                prerequisites_text=raw,
                catalog_url=course.catalog_url,
                verified_on=(
                    course.catalog_verified_at.date().isoformat()
                    if course.catalog_verified_at
                    else None
                ),
            )
        )
    return out
