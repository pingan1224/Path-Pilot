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
    # A real user's academic record. There is no Albert integration and there will not be
    # one, so this is what the student told us — stored as a claim, never as a fact.
    #
    # `course_code` is text rather than a foreign key on purpose: students take courses
    # outside the loaded catalog (the cross-school elective), and a constraint that
    # rejected those would force the product to pretend they do not exist.
    """CREATE TABLE IF NOT EXISTS profile_courses (
           id SERIAL PRIMARY KEY,
           user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
           course_code VARCHAR(24) NOT NULL,
           state VARCHAR(16) NOT NULL,
           term VARCHAR(16),
           grade VARCHAR(4),
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           UNIQUE (user_id, course_code)
       )""",
    "CREATE INDEX IF NOT EXISTS ix_profile_courses_user ON profile_courses (user_id)",
    # Which encoded program the student says they are in. Planning needs it, and it is a
    # claim like everything else here.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS stated_program_code VARCHAR(24)",
    # Registration missions. Note what is absent: no status or current_step column. A
    # mission's progress is recomputed from these rows on every read, because a stored
    # status is a second source of truth that drifts from the profile and the candidate
    # list, and drifts invisibly — it still looks authoritative while it lies.
    """CREATE TABLE IF NOT EXISTS missions (
           id SERIAL PRIMARY KEY,
           user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
           term VARCHAR(32) NOT NULL,
           program_code VARCHAR(24) NOT NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           closed_at TIMESTAMPTZ,
           close_reason VARCHAR(200),
           UNIQUE (user_id, term, program_code)
       )""",
    "CREATE INDEX IF NOT EXISTS ix_missions_user ON missions (user_id)",
    # `confirmed_at` is the boundary between the assistant proposing and the student
    # deciding. The agent tool that inserts here cannot reach this column — see
    # app/models/missions.py.
    """CREATE TABLE IF NOT EXISTS mission_candidates (
           id SERIAL PRIMARY KEY,
           mission_id INTEGER NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
           course_code VARCHAR(24) NOT NULL,
           proposed_by VARCHAR(16) NOT NULL DEFAULT 'student',
           rationale TEXT,
           confirmed_at TIMESTAMPTZ,
           declined_at TIMESTAMPTZ,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           UNIQUE (mission_id, course_code)
       )""",
    "CREATE INDEX IF NOT EXISTS ix_mission_candidates_mission ON mission_candidates (mission_id)",
    # `finding_summary` records how a finding read when the student accepted it, so a risk
    # that later got worse cannot hide behind an acceptance of its smaller self.
    """CREATE TABLE IF NOT EXISTS mission_decisions (
           id SERIAL PRIMARY KEY,
           mission_id INTEGER NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
           kind VARCHAR(24) NOT NULL,
           finding_key VARCHAR(200),
           finding_summary VARCHAR(400),
           note TEXT,
           decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
    "CREATE INDEX IF NOT EXISTS ix_mission_decisions_mission ON mission_decisions (mission_id)",
    # Loop length, stored rather than derived. `tool_calls` carries an iteration number per
    # call, but the final turn produces the answer and calls nothing, so the trace
    # systematically undercounts by one — and iterations is the number that says whether a
    # change made the agent wander.
    "ALTER TABLE ai_interactions ADD COLUMN IF NOT EXISTS iterations INTEGER",
    # Who opened the mission. The assistant may open an empty container (approved
    # 2026-08-07) because that decides nothing; every choice inside it is still the
    # student's. Recording the origin keeps that visible rather than implicit.
    "ALTER TABLE missions ADD COLUMN IF NOT EXISTS created_by VARCHAR(16) NOT NULL DEFAULT 'student'",
    # Level as a stated fact rather than one inferred from the degree abbreviation. The old
    # inference (`degree in ("MS", "MA", "PhD")`) reads every undergraduate degree as
    # graduate, and level is half the retrieval scope — an undergraduate scoped to graduate
    # gets the wrong credit-load rules with a real citation attached. Existing rows are all
    # graduate, so the default backfills them correctly; new undergraduate programs must
    # set it explicitly.
    "ALTER TABLE programs ADD COLUMN IF NOT EXISTS level VARCHAR(16) NOT NULL DEFAULT 'graduate'",
    # A real signed-in user's program. Demo accounts carry theirs on the `students` fixture;
    # live accounts had nowhere to put it, which is why every live user was planned against
    # the one encoded program regardless of who they were.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS program_id INTEGER REFERENCES programs(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_users_program ON users (program_id)",
    # A program the picker can offer but the planner cannot audit has no known credit
    # total. NULL says that; 0 would say the degree requires no credits.
    "ALTER TABLE programs ALTER COLUMN total_credits_required DROP NOT NULL",
    # Which degree a corpus page belongs to, for the pages that belong to exactly one.
    # Null means school-wide, which is the right answer for everybody.
    #
    # School and level stopped discriminating once a page per degree was ingested: all 23
    # SPS graduate programmes share both, and each page carries its own "Policies" section.
    # Backfilled from the URL by ingest.load, which is where the seed list's facets are
    # already applied.
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS program_slug VARCHAR(120)",
    "CREATE INDEX IF NOT EXISTS ix_documents_program ON documents (program_slug)",
    # Backfill for the column above.
    #
    # Seeded students belong to the *demo* program, whose requirements are written against
    # invented MASY-GC courses and exist to feed the demo degree-audit path
    # (`services.readiness`, which reads `students.program_id` and is untouched by this).
    # What they self-report on the profile page is real MASY1-GC coursework, identical to
    # what a live user enters, so the self-reported planner must evaluate them against the
    # ingested catalog rules — which is exactly what the old hardcoded default did by
    # accident. Making the program per-user turned that accident into a 409, so the
    # intent is written down here instead.
    #
    # Idempotent twice over: only fills nulls, and matches no rows at all if the catalog
    # program has not been ingested yet.
    #
    # Demo fixtures are excluded: the seed states the heroes' program explicitly (it is
    # part of their persona, alongside their self-reported record), and this statement
    # originally swept them too — which happened to make the demo planner work, but as an
    # accident of migration order that a database reset silently undid. A fixture's
    # identity belongs in the seed, not in a backfill written for live accounts — which
    # are exactly the accounts with no Student row.
    """
    UPDATE users u
       SET program_id = p.id
      FROM programs p
     WHERE u.program_id IS NULL
       AND u.role = 'student'
       AND NOT EXISTS (SELECT 1 FROM students st WHERE st.user_id = u.id)
       AND p.source = 'catalog'
       AND p.code = 'MASY-MS-REAL'
    """,
    # A course whose prerequisite clause the parser could not resolve into codes. Without
    # this the failure is invisible in the worst possible direction: the row lands with zero
    # prerequisite edges, which every reader downstream cannot tell from "this course has no
    # prerequisites", so the planner offers it as available.
    #
    # Three capstones in the SPS catalogues state their prerequisites as course *titles*
    # rather than codes ("Workforce Planning AND Quantitative Methods and Metrics AND …"),
    # and resolving titles is not safe to automate: a title can match courses under four
    # different prefixes, the AND separator also occurs inside titles, and the published
    # text carries truncations. So the clause is stored verbatim and the planner is expected
    # to say it cannot verify, which is true, instead of staying quiet, which is not.
    "ALTER TABLE courses ADD COLUMN IF NOT EXISTS prerequisite_unparsed TEXT",
    # How many of a concentration's courses complete it. NULL keeps the previous meaning —
    # all of them — which is correct for Management & Analytics, where each concentration is
    # two courses and both are required. Financial Planning lists five and asks for three.
    "ALTER TABLE requirement_tracks ADD COLUMN IF NOT EXISTS min_courses INTEGER",
    # 1.5-credit courses truncated to 1 under the old integer column. See the note on
    # Course.credits; the cast is safe in this direction and the re-ingest restores the
    # fractions the parser had been discarding.
    "ALTER TABLE courses ALTER COLUMN credits TYPE double precision",
    "ALTER TABLE requirements ALTER COLUMN min_credits TYPE double precision",
    # A track can name courses it requires outright alongside the pool it draws the rest
    # from — Global Affairs states each concentration as one named course plus five chosen.
    """CREATE TABLE IF NOT EXISTS requirement_track_required_courses (
           track_id INTEGER NOT NULL REFERENCES requirement_tracks(id) ON DELETE CASCADE,
           course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
           PRIMARY KEY (track_id, course_id)
       )""",
    # Hold-reading was removed on 2026-08-13 (see CLAUDE.md, "Holds: what changed").
    # These two tables held invented rows that nothing reads any more, and leaving them in
    # place would be worse than dropping them: a fixture that still exists is a fixture
    # something can start reading again.
    #
    # `registration_attempts` goes first — it carries a foreign key to `holds`.
    "DROP TABLE IF EXISTS registration_attempts",
    "DROP TABLE IF EXISTS holds",
    # The enum types outlive their tables in Postgres and would silently block a future
    # column reusing the name.
    "DROP TYPE IF EXISTS hold_type",
    "DROP TYPE IF EXISTS registration_outcome",
    # 2026-08-16: the assistant defers instead of escalating. Path Pilot is a third-party
    # planning tool that submits nothing to anyone, so a `Case` row with a quotable number
    # promised a queue that never existed — live mode had already stopped creating them,
    # and the demo's rows were worked by nobody.
    #
    # The new label is ADDed rather than the old one renamed, and the old one is left in
    # place: `escalated` is the literal stored on every audit row written before today,
    # and those rows are the eval's own dataset. Renaming would rewrite history to say
    # something the system did not do at the time.
    "ALTER TYPE interaction_decision ADD VALUE IF NOT EXISTS 'deferred'",
    # `case_id` went with them. The referral lives in `escalation_reason`, which keeps its
    # column name because renaming it would break the same historical rows.
    "ALTER TABLE ai_interactions DROP COLUMN IF EXISTS case_id",
    "DROP TABLE IF EXISTS case_events",
    "DROP TABLE IF EXISTS cases",
    "DROP TYPE IF EXISTS case_category",
    "DROP TYPE IF EXISTS case_status",
    "DROP TYPE IF EXISTS case_priority",
    "DROP TYPE IF EXISTS actor_kind",
    # 2026-08-16: a mission is identified by programme as well as term. The old constraint
    # let "one mission per term" hand a student the mission they opened under a programme
    # they have since left, evaluated against its rules and labelled only by term.
    # What the student wants, kept apart from what they have taken. Nullable throughout:
    # unset is a real answer, and a default written here would be the product deciding
    # when someone wants to graduate and then solving against it.
    """CREATE TABLE IF NOT EXISTS user_preferences (
           id SERIAL PRIMARY KEY,
           user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
           target_finish_term VARCHAR(16),
           max_credits_per_term INTEGER,
           summers_ok BOOLEAN,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
    "CREATE INDEX IF NOT EXISTS ix_user_preferences_user ON user_preferences (user_id)",
    "ALTER TABLE missions DROP CONSTRAINT IF EXISTS missions_user_id_term_key",
    """DO $$ BEGIN
           ALTER TABLE missions ADD CONSTRAINT missions_user_id_term_program_key
               UNIQUE (user_id, term, program_code);
       EXCEPTION WHEN duplicate_table THEN NULL;
       END $$""",
    # 2026-08-17: scheduling is out of scope, so the column that carried invented meeting
    # times goes with it. It existed only on the 45 demo sections, reached the model through
    # `tool_get_course_info`, and was the last place the product asserted a fabricated fact
    # about availability as confidently as a computed one. Dropped rather than left empty:
    # a nullable column is an invitation to fill it, and there is no compliant source to
    # fill it from. The rest of `sections` stays — seat counts are what "is it full?"
    # resolves to, and `readiness` reaches enrollments through this table.
    "ALTER TABLE sections DROP COLUMN IF EXISTS meeting_pattern",
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
