"""Run the queries the dashboards depend on and print the results.

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
UNION ALL SELECT 'courses', count(*) FROM courses
UNION ALL SELECT 'sections', count(*) FROM sections
UNION ALL SELECT 'enrollments', count(*) FROM enrollments
UNION ALL SELECT 'holds', count(*) FROM holds
UNION ALL SELECT 'registration_attempts', count(*) FROM registration_attempts
UNION ALL SELECT 'cases', count(*) FROM cases
UNION ALL SELECT 'case_events', count(*) FROM case_events
UNION ALL SELECT 'ai_interactions', count(*) FROM ai_interactions
UNION ALL SELECT 'documents', count(*) FROM documents
UNION ALL SELECT 'document_chunks', count(*) FROM document_chunks
ORDER BY 1
"""

# Registrar dashboard: why are students failing to register?
FAILURE_BREAKDOWN = """
SELECT failure_reason::text AS reason,
       count(*) AS attempts,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
FROM registration_attempts
WHERE outcome = 'failed'
GROUP BY failure_reason
ORDER BY attempts DESC
"""

# Registrar dashboard: which sections are under pressure right now?
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
WHERE r.program_id = (SELECT program_id FROM students st
                      JOIN users u ON u.id = st.user_id WHERE u.full_name = :name)
ORDER BY r.sort_order
"""

# Rule 4: which mirrored rows are past their source's tolerance right now?
FRESHNESS_AUDIT = """
SELECT p.label,
       p.max_age_seconds,
       count(*) AS rows_checked,
       count(*) FILTER (
           WHERE now() - h.verified_at > make_interval(secs => p.max_age_seconds)
       ) AS stale_rows
FROM holds h
JOIN source_freshness_policy p ON p.source_key = h.source_key
GROUP BY p.label, p.max_age_seconds
ORDER BY stale_rows DESC, p.label
"""

# Rule 3: the retrieval candidate set differs by role, enforced in the index.
#
# Totals alone prove nothing here — every role happens to see 13 of 15 chunks, which would
# look identical whether the filter worked or was ignored entirely. What proves it is
# *which* restricted documents each role can reach, and which are absent.
ROLE_VISIBILITY = """
SELECT r.role,
       count(dc.id) AS visible,
       (SELECT count(*) FROM document_chunks) AS total,
       COALESCE(
           string_agg(DISTINCT d.title, '; ')
               FILTER (WHERE array_length(dc.visible_to_roles, 1) < 4),
           '(none)'
       ) AS restricted_docs_reachable
FROM unnest(ARRAY['student','advisor','registrar','finance']) AS r(role)
LEFT JOIN document_chunks dc ON dc.visible_to_roles @> ARRAY[r.role]::varchar(16)[]
LEFT JOIN documents d ON d.id = dc.document_id
GROUP BY r.role
ORDER BY r.role
"""

ADVISOR_QUEUE = """
SELECT u.full_name AS student,
       count(DISTINCT h.id) FILTER (WHERE h.cleared_at IS NULL) AS active_holds,
       count(DISTINCT ca.id) FILTER (WHERE ca.status <> 'resolved') AS open_cases,
       count(DISTINCT ra.id) FILTER (WHERE ra.outcome = 'failed') AS failed_attempts
FROM students st
JOIN users u ON u.id = st.user_id
JOIN users adv ON adv.id = st.advisor_id
LEFT JOIN holds h ON h.student_id = st.id
LEFT JOIN cases ca ON ca.student_id = st.id
LEFT JOIN registration_attempts ra ON ra.student_id = st.id
WHERE adv.full_name = 'Maya Patel'
GROUP BY u.full_name
HAVING count(DISTINCT h.id) FILTER (WHERE h.cleared_at IS NULL) > 0
    OR count(DISTINCT ca.id) FILTER (WHERE ca.status <> 'resolved') > 0
ORDER BY open_cases DESC, active_holds DESC
LIMIT 8
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
        show(conn, "Registrar — failed registration attempts by reason", FAILURE_BREAKDOWN)
        show(conn, "Registrar — Fall 2026 capacity pressure (top 8)", CAPACITY_PRESSURE)
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
        show(conn, "Governance — hold freshness against source policy", FRESHNESS_AUDIT)
        show(conn, "Retrieval — chunks visible per role (pre-filter)", ROLE_VISIBILITY)
        show(conn, "Advisor — Maya Patel triage queue", ADVISOR_QUEUE)
        print()


if __name__ == "__main__":
    main()
