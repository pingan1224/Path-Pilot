"""One real degree gets one row, whichever stage wrote it first.

Two ingest stages write to `programs`, and they derive the code differently on purpose:
`ingest.programs` lists a degree from its own bulletin page under a code derived from the
name (`FP-MS`), and `ingest.requirements` encodes it under the code its spec names
(`MSFP-MS-REAL`). While the encoding stage matched on its own code alone, encoding a degree
that had already been listed added a *second* row for one real degree.

That is not a tidiness problem. `routers.catalog.list_programs` orders by name and does not
deduplicate, so the student saw their own degree twice under identical names, one of the two
carrying no requirements and reporting itself unauditable — a coin flip that silently
switched the planner off. Twenty-one of twenty-three degrees were in that state when it was
found.

These tests hold the property from both directions: adopt the listing row when it exists,
and merge away a duplicate that a previous run already created, carrying its students with
it.
"""

import pytest
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models import Program, User
from ingest.requirements import ProgramSpec, _row_for

NAME = "Ztest Nonexistent Programme"
LISTED_CODE = "ZZT-MS"
ENCODED_CODE = "ZZT-MS-REAL"


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

SPEC = ProgramSpec(
    page_slug="graduate__professional-studies__programs__ztest",
    code=ENCODED_CODE,
    name=NAME,
    total_credits=30,
    requirements=[],
)


@pytest.fixture
def session():
    """A session whose work is always rolled back.

    `_row_for` deletes rows and repoints foreign keys, so a test that committed would edit
    the dev database it is reading from.
    """
    with get_sessionmaker()() as s:
        try:
            yield s
        finally:
            s.rollback()


def _listing_row(name: str = NAME, code: str = LISTED_CODE) -> Program:
    """What `ingest.programs` writes: named and cited, with no credit total, because
    nobody has transcribed the requirements yet."""
    return Program(
        code=code,
        name=name,
        degree="MS",
        school="School of Professional Studies",
        level="graduate",
        source="catalog",
        total_credits_required=None,
    )


def _catalog_rows_named(session, name: str) -> list[Program]:
    return [
        row
        for row in session.scalars(select(Program).where(Program.source == "catalog"))
        if row.name.strip().lower() == name.strip().lower()
    ]


def test_encoding_a_listed_degree_adopts_its_row_instead_of_adding_one(session):
    listed = _listing_row()
    session.add(listed)
    session.flush()
    listed_id = listed.id

    row = _row_for(session, SPEC)

    assert row.id == listed_id, "the listing row must be adopted, not replaced"
    assert row.code == ENCODED_CODE, "the surviving row must carry the encoded code"
    assert len(_catalog_rows_named(session, NAME)) == 1


def test_a_duplicate_from_an_earlier_run_is_merged_away(session):
    """The state this bug left behind: both rows already exist."""
    listed = _listing_row()
    encoded = _listing_row(code=ENCODED_CODE)
    encoded.total_credits_required = 30
    session.add_all([listed, encoded])
    session.flush()
    listed_id, encoded_id = listed.id, encoded.id

    row = _row_for(session, SPEC)

    assert row.id == encoded_id, "the encoded row is the one that survives"
    survivors = _catalog_rows_named(session, NAME)
    assert len(survivors) == 1
    assert listed_id not in {s.id for s in survivors}


def test_a_student_who_picked_the_duplicate_moves_with_it(session):
    """A student who chose the twin chose *this degree*. Deleting the row they point at
    without moving them would either fail on the foreign key or lose the one thing they
    told us about themselves."""
    listed = _listing_row()
    encoded = _listing_row(code=ENCODED_CODE)
    session.add_all([listed, encoded])
    session.flush()

    student = session.scalars(select(User).limit(1)).one()
    student.program_id = listed.id
    session.flush()
    listed_id = listed.id

    row = _row_for(session, SPEC)

    assert student.program_id == row.id, "the student must follow their degree"
    assert student.program_id != listed_id, "and must not still point at the deleted row"


def test_an_unlisted_degree_still_gets_a_row(session):
    """Nothing above may stop the first-ever encoding of a degree from creating its row.

    A brand-new row is deliberately returned unflushed — `name` is NOT NULL and `write`
    fills it — so this completes the caller's half before asserting, the way `write` does.
    """
    assert _catalog_rows_named(session, NAME) == []

    row = _row_for(session, SPEC)
    assert row.code == ENCODED_CODE

    row.name = SPEC.name
    row.degree = "MS"
    row.school = "School of Professional Studies"
    row.source = "catalog"
    session.flush()

    assert len(_catalog_rows_named(session, NAME)) == 1
