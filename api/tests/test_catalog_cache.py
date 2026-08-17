"""The catalogue cache, and the one property that makes it safe.

`/plan` and `/missions` were slow for a reason that turned out not to be a slow query:
every remaining statement takes ~22 ms, because the database is in another region, and the
endpoints were making 19 and 35 of them. `/missions` made them once per open mission.

So the fix is fewer round trips, and the reusable part is the reference data — the
catalogue and each degree's encoded rules. **Caching those is not caching a verdict.** "No
stored status, recompute on read" exists because a student's situation moves underneath a
stored answer while the answer still looks authoritative; a course's credit count does not
move for that reason, it moves when someone runs an ingest. Every plan is still evaluated
from scratch on every read.

Which leaves exactly one way for this to be wrong: serving rules from before an ingest. The
fingerprint is what prevents it, so the fingerprint is what these tests are about. A cache
whose invalidation has quietly stopped working is worse than no cache, because it fails by
being confidently out of date.
"""

import pytest
from sqlalchemy import select, text

from app.db.session import get_sessionmaker
from app.models import Program, User
from app.planning import loader

PROGRAM = "MASY-MS-REAL"


def _db_available() -> bool:
    try:
        with get_sessionmaker()() as session:
            session.scalar(select(User.id).limit(1))
            loader.load_program_rules(session, PROGRAM)
        return True
    except Exception:  # noqa: BLE001 — the suite must skip, not fail, without a database
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="needs the seeded dev database with catalog programmes"
)


@pytest.fixture(autouse=True)
def cold():
    """Every test starts cold, and leaves the caches cold for the next one — otherwise a
    test that warms them changes what the following test is measuring."""
    loader._CATALOG.clear()
    loader._PROGRAM_RULES.clear()
    yield
    loader._CATALOG.clear()
    loader._PROGRAM_RULES.clear()


def _queries(session, fn):
    """How many statements one call actually issues."""
    from sqlalchemy import event

    engine = session.get_bind()
    count = {"n": 0}

    def after(*_args, **_kwargs):
        count["n"] += 1

    event.listen(engine, "after_cursor_execute", after)
    try:
        fn()
    finally:
        event.remove(engine, "after_cursor_execute", after)
    return count["n"]


# --------------------------------------------------------------------------------------
# It caches
# --------------------------------------------------------------------------------------


def test_a_warm_read_costs_one_round_trip_instead_of_the_whole_catalogue():
    with get_sessionmaker()() as session:
        cold_n = _queries(session, lambda: loader.load_catalog_courses(session))
        warm_n = _queries(session, lambda: loader.load_catalog_courses(session))
        assert warm_n < cold_n
        # The fingerprint, and nothing else.
        assert warm_n == 1


def test_program_rules_are_cached_per_programme():
    with get_sessionmaker()() as session:
        cold_n = _queries(session, lambda: loader.load_program_rules(session, PROGRAM))
        warm_n = _queries(session, lambda: loader.load_program_rules(session, PROGRAM))
        assert warm_n == 1 < cold_n

        # Must be an *encoded* one: the 23rd programme (the HCM/HCAT dual degree) is
        # deliberately unencoded and raises rather than returning rules.
        from app.services.profile import ENCODED_PROGRAMS

        other = session.scalar(
            select(Program.code).where(
                Program.source == "catalog",
                Program.code != PROGRAM,
                Program.code.in_(ENCODED_PROGRAMS),
            )
        )
        # A second degree is a separate entry, not a cache hit on the first one — the
        # failure this rules out is every student being audited against one programme.
        second = _queries(session, lambda: loader.load_program_rules(session, other))
        assert second > 1


def test_the_rules_are_equal_warm_and_cold():
    """A cache that returns something subtly different is worse than a slow read."""
    with get_sessionmaker()() as session:
        first = loader.load_program_rules(session, PROGRAM)
        second = loader.load_program_rules(session, PROGRAM)
        assert first is second
        assert first.total_credits == second.total_credits
        assert [r.name for r in first.requirements] == [
            r.name for r in second.requirements
        ]
        assert len(first.courses) == len(second.courses)


# --------------------------------------------------------------------------------------
# It notices an ingest — the only way this can be wrong
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        # A course edited: what `ingest.catalog` does on a re-run.
        "UPDATE courses SET updated_at = now() "
        "WHERE id = (SELECT id FROM courses WHERE source = 'catalog' LIMIT 1)",
        # A requirement re-encoded: `ingest.requirements`. Counted separately from courses
        # because this touches no course row, so a courses-only fingerprint would miss it
        # and keep serving the previous degree shape.
        "UPDATE requirements SET updated_at = now() "
        "WHERE id = (SELECT id FROM requirements LIMIT 1)",
    ],
)
def test_a_change_invalidates_the_cache(statement):
    with get_sessionmaker()() as session:
        loader.load_program_rules(session, PROGRAM)
        assert _queries(session, lambda: loader.load_program_rules(session, PROGRAM)) == 1

        session.execute(text(statement))
        session.commit()

        after = _queries(session, lambda: loader.load_program_rules(session, PROGRAM))
        assert after > 1, "the cache served rules from before the change"


def test_only_one_catalogue_generation_is_kept():
    """Otherwise every ingest leaves its predecessor in memory for the process's life."""
    with get_sessionmaker()() as session:
        loader.load_catalog_courses(session)
        assert len(loader._CATALOG) == 1
        session.execute(
            text(
                "UPDATE courses SET updated_at = now() "
                "WHERE id = (SELECT id FROM courses WHERE source = 'catalog' LIMIT 1)"
            )
        )
        session.commit()
        loader.load_catalog_courses(session)
        assert len(loader._CATALOG) == 1
