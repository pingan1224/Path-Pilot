"""Run the queries the product depends on and print the results.

    .venv/Scripts/python -m scripts.data_report

This is a schema sanity check with a purpose: each section is a question the product has to
answer. If one of these cannot be expressed cleanly in SQL, the data model is wrong and it
is much cheaper to find out now than in P2.
"""

from sqlalchemy import text

from app.db.session import get_engine

COUNTS = """
SELECT 'users' t, count(*) n FROM users
UNION ALL SELECT 'students', count(*) FROM students
UNION ALL SELECT 'programs', count(*) FROM programs
UNION ALL SELECT 'courses', count(*) FROM courses
UNION ALL SELECT 'requirements', count(*) FROM requirements
UNION ALL SELECT 'sections', count(*) FROM sections
UNION ALL SELECT 'enrollments', count(*) FROM enrollments
UNION ALL SELECT 'profile_courses', count(*) FROM profile_courses
UNION ALL SELECT 'missions', count(*) FROM missions
UNION ALL SELECT 'user_preferences', count(*) FROM user_preferences
UNION ALL SELECT 'ai_interactions', count(*) FROM ai_interactions
UNION ALL SELECT 'documents', count(*) FROM documents
UNION ALL SELECT 'document_chunks', count(*) FROM document_chunks
ORDER BY 1
"""

# The decoder's own breakdown ("why are students failing to register?") used to live here
# and is gone with `registration_attempts`, dropped on 2026-08-13. There is nothing to
# re-point it at: the product does not record registration attempts, because it never sees
# one — a student pastes an error and the decoder reads it. `eval/decoder_cases.py` is where
# that behaviour is measured now.

# Sequencing and "is it full?": which sections are under pressure right now?
CAPACITY_PRESSURE = """
SELECT c.code,
       s.enrolled_count || '/' || s.capacity AS seats,
       round(100.0 * s.enrolled_count / s.capacity) AS fill_pct,
       s.waitlist_count AS waitlisted,
       CASE WHEN s.reserved_seat_rule IS NOT NULL THEN 'reserved'
            WHEN s.requires_permission THEN 'permission'
            ELSE '' END AS restriction
FROM sections s
JOIN courses c ON c.id = s.course_id
JOIN terms t ON t.id = s.term_id
WHERE t.code = '2026FA'
ORDER BY fill_pct DESC, waitlisted DESC
LIMIT 8
"""

# Student dashboard: the "enough credits, wrong credits" calculation. Credits beyond a
# requirement's minimum do not count, which is exactly what a raw credit total hides.
REQUIREMENT_PROGRESS = """
WITH earned AS (
    SELECT st.id AS student_id, r.id AS req_id, r.name, r.min_credits,
           COALESCE(sum(co.credits), 0) AS raw_credits
    FROM students st
    JOIN users u ON u.id = st.user_id
    CROSS JOIN requirements r
    LEFT JOIN requirement_courses rc ON rc.requirement_id = r.id
    LEFT JOIN courses co ON co.id = rc.course_id
    LEFT JOIN sections se ON se.course_id = co.id
    LEFT JOIN enrollments e ON e.section_id = se.id
                           AND e.student_id = st.id
                           AND e.status = 'completed'
                           AND e.id IS NOT NULL
    WHERE u.full_name = :name AND r.program_id = st.program_id
      AND e.id IS NOT NULL
    GROUP BY st.id, r.id, r.name, r.min_credits
)
SELECT r.name,
       r.min_credits AS required,
       COALESCE(e.raw_credits, 0) AS earned_raw,
       LEAST(COALESCE(e.raw_credits, 0), r.min_credits) AS applied,
       r.min_credits - LEAST(COALESCE(e.raw_credits, 0), r.min_credits) AS remaining
FROM requirements r
LEFT JOIN earned e ON e.req_id = r.id
-- `st.`-qualified, not bare: `users` gained its own `program_id` when real accounts
-- started stating a programme, and the unqualified reference became ambiguous.
WHERE r.program_id = (SELECT st.program_id FROM students st
                      JOIN users u ON u.id = st.user_id WHERE u.full_name = :name)
ORDER BY r.sort_order
"""

# Rule 4: which mirrored rows are past their source's tolerance right now?
#
# This read `FROM holds` and had been broken since that table was dropped on 2026-08-13.
# Re-pointed at every table that still carries a `source_key`, which makes it a wider check
# than it ever was — it covers each mirrored family rather than the one that happened to be
# the demo's headline. Add a table here whenever one gains `SourcedMixin`; a mirrored row
# with no freshness policy behind it is exactly what rule 4 forbids, and the `policy`
# column below says `(none)` when that happens instead of the row quietly not appearing.
FRESHNESS_AUDIT = """
WITH mirrored AS (
    SELECT 'students'    AS source_table, source_key, verified_at AS checked_at FROM students
    UNION ALL SELECT 'enrollments', source_key, verified_at FROM enrollments
    UNION ALL SELECT 'sections',    source_key, verified_at FROM sections
    -- `fetched_at`, not `verified_at`: a document is a page that was retrieved, not a
    -- record mirrored from a system of record, and the column name says which.
    UNION ALL SELECT 'documents',   source_key, fetched_at  FROM documents
)
SELECT m.source_table,
       COALESCE(p.label, '(none)') AS policy,
       p.max_age_seconds,
       count(*) AS rows_checked,
       count(*) FILTER (
           WHERE p.max_age_seconds IS NOT NULL
             AND now() - m.checked_at > make_interval(secs => p.max_age_seconds)
       ) AS stale_rows
FROM mirrored m
LEFT JOIN source_freshness_policy p ON p.source_key = m.source_key
GROUP BY m.source_table, p.label, p.max_age_seconds
ORDER BY stale_rows DESC, m.source_table
"""

# Rule 3: the retrieval candidate set differs by role, enforced in the index.
#
# Totals alone prove nothing here — both roles see nearly every chunk, which would look
# identical whether the filter worked or was ignored entirely. What proves it is *which*
# restricted documents each role can reach, and which are absent. Two roles is the minimum
# at which this is a test at all, which is why `advisor` outlived the advisor dashboard.
ROLE_VISIBILITY = """
SELECT r.role,
       count(dc.id) AS visible,
       (SELECT count(*) FROM document_chunks) AS total,
       COALESCE(
           string_agg(DISTINCT d.title, '; ')
               FILTER (WHERE array_length(dc.visible_to_roles, 1) < 2),
           '(none)'
       ) AS restricted_docs_reachable
FROM unnest(ARRAY['student','advisor']) AS r(role)
LEFT JOIN document_chunks dc ON dc.visible_to_roles @> ARRAY[r.role]::varchar(16)[]
LEFT JOIN documents d ON d.id = dc.document_id
GROUP BY r.role
ORDER BY r.role
"""

def show(conn, title: str, sql: str, **params) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    result = conn.execute(text(sql), params)
    rows = result.fetchall()
    if not rows:
        print("(no rows)")
        return

    headers = list(result.keys())
    widths = [
        max(len(h), max((len(str(r[i])) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))


def main() -> None:
    with get_engine().connect() as conn:
        show(conn, "Row counts", COUNTS)
        show(conn, "Sections — Fall 2026 capacity pressure (top 8)", CAPACITY_PRESSURE)
        show(
            conn,
            "Student — Diego Morales requirement progress (27 credits earned)",
            REQUIREMENT_PROGRESS,
            name="Diego Morales",
        )
        show(
            conn,
            "Student — Alex Chen requirement progress (21 credits earned)",
            REQUIREMENT_PROGRESS,
            name="Alex Chen",
        )
        show(
            conn,
            "Governance — mirrored-row freshness against source policy",
            FRESHNESS_AUDIT,
        )
        show(conn, "Retrieval — chunks visible per role (pre-filter)", ROLE_VISIBILITY)
        print()


if __name__ == "__main__":
    main()
