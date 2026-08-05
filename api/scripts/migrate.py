"""Idempotent DDL for columns added after the tables were first created.

    .venv/Scripts/python -m scripts.migrate

`Base.metadata.create_all` creates missing tables but never alters existing ones, so a
column added later needs help. A real project would use Alembic; here the alternative was
dropping the database and re-embedding 2,836 chunks to add one generated column, which is
a poor trade for a demo. Every statement is written to be safe to run repeatedly.
"""

from sqlalchemy import text

from app.db.session import get_engine

STATEMENTS = [
    # Full-text vector over heading path and body, maintained by Postgres itself so it can
    # never drift from the text it indexes. The heading is included deliberately: course
    # codes like "MASY1-GC 2100" live in headings, and they are exactly the queries dense
    # retrieval handles worst.
    """
    ALTER TABLE document_chunks
      ADD COLUMN IF NOT EXISTS tsv tsvector
      GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(heading_path, '') || ' ' || text)
      ) STORED
    """,
    "CREATE INDEX IF NOT EXISTS ix_chunk_tsv ON document_chunks USING gin (tsv)",
    # Authentication. Until now the API took the caller's role from the request body,
    # which meant every permission check in the system was validating a claim the caller
    # made about themselves.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(256)",
    # Real catalog data alongside the fictional demo courses. `source` keeps them
    # distinguishable: a planner answering a real student must never reason over an
    # invented course, and the demo scenarios must keep working.
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'demo'",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS catalog_url VARCHAR(1024)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS typically_offered VARCHAR(120)",
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS catalog_verified_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS ix_courses_source ON courses (source)",
    # Prerequisites in the same group are alternatives (OR); groups are required together
    # (AND). A flat list can only express AND, which happens to fit the MASY data today —
    # and would silently mis-answer the first program that writes "A or B".
    "ALTER TABLE course_prerequisites ADD COLUMN IF NOT EXISTS group_index INTEGER NOT NULL DEFAULT 0",
    # The exact sentence the requirement was parsed from, so a planner verdict can quote
    # its source rather than assert a parsed structure the student cannot check.
    "ALTER TABLE course_prerequisites ADD COLUMN IF NOT EXISTS raw_text VARCHAR(512)",
    # Programs, like courses, now come in real and demo flavours.
    "ALTER TABLE programs ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'demo'",
    "ALTER TABLE programs ADD COLUMN IF NOT EXISTS catalog_url VARCHAR(1024)",
    "ALTER TABLE programs ADD COLUMN IF NOT EXISTS catalog_verified_at TIMESTAMPTZ",
    # A requirement can be "take all of these", "take N credits from these", or "pick one
    # of these mutually exclusive tracks and take all of it". The third is the MASY
    # concentration, and a credit-threshold model answers it wrong: a student with one
    # course from Business Analytics and one from Risk Analytics has 6 concentration
    # credits and satisfies nothing.
    "ALTER TABLE requirements ADD COLUMN IF NOT EXISTS rule VARCHAR(24) NOT NULL DEFAULT 'credits'",
    # Free text from the bulletin that the rule engine cannot model but a student must
    # still be told — eligibility conditions, approval requirements, scope of choice.
    "ALTER TABLE requirements ADD COLUMN IF NOT EXISTS caveat TEXT",
    "ALTER TABLE requirements ADD COLUMN IF NOT EXISTS source_url VARCHAR(1024)",
    "ALTER TABLE requirements ADD COLUMN IF NOT EXISTS source_verified_at TIMESTAMPTZ",
    # Mutually exclusive tracks inside one requirement (the four concentrations). Null for
    # ordinary requirements; rows sharing a name are one track.
    """CREATE TABLE IF NOT EXISTS requirement_tracks (
           id SERIAL PRIMARY KEY,
           requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
           name VARCHAR(120) NOT NULL,
           sort_order INTEGER NOT NULL DEFAULT 0,
           UNIQUE (requirement_id, name)
       )""",
    """CREATE TABLE IF NOT EXISTS requirement_track_courses (
           track_id INTEGER NOT NULL REFERENCES requirement_tracks(id) ON DELETE CASCADE,
           course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
           PRIMARY KEY (track_id, course_id)
       )""",
]


def main() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        for statement in STATEMENTS:
            label = " ".join(statement.split())[:80]
            conn.execute(text(statement))
            print(f"  ok  {label}…")

        n = conn.execute(
            text("SELECT count(*) FROM document_chunks WHERE tsv IS NOT NULL")
        ).scalar_one()
        total = conn.execute(text("SELECT count(*) FROM document_chunks")).scalar_one()
    print(f"\ntsv populated on {n}/{total} chunks")


if __name__ == "__main__":
    main()
