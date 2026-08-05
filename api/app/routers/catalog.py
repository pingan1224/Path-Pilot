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
from app.models import Course, CoursePrerequisite
from app.services.auth import Identity, current_user

router = APIRouter(prefix="/catalog", tags=["catalog"])


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
