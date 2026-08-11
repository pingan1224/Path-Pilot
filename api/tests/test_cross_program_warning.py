"""Flagging a policy passage written for a different degree than the student's own.

The sibling of `test_cross_school_warning`, and it exists for the same reason one level
down. Ingesting a page per SPS graduate degree (WP2) put 23 near-identical "Policies"
sections into the corpus, all sharing a school and a level — so neither scope facet can
tell them apart, and the boost cannot either.

Measured the moment those pages landed, on labelled case R11: asked "what is the attendance
policy for my classes" as a Management & Analytics student, retrieval returned

    1. Publishing (MS) > Policies > Program Policies     <- another degree's page
    2. Academic Policies > Attendance Policy             <- the school-wide answer

Real chunk, accurate quote, wrong degree. The school matches, the level matches, and the
heading says "Publishing (MS)" — which is exactly the signal the model was already shown to
read past when it was "(MSW)" in the cross-school case.

So the mismatch is computed here as a fact rather than left in prose, and these tests are
about that computation. Ranking is deliberately untouched: adding a program boost means
re-sweeping every boost pair against the enlarged corpus, and a soft boost would not have
prevented this anyway — the cross-school one did not.
"""

import pytest

from app.models import UserRole
from app.services import agent_tools
from app.services.agent_tools import ToolContext, tool_search_policy
from app.services.retrieval import RetrievalResult, RetrievalScope, RetrievedChunk


@pytest.fixture
def ctx():
    return ToolContext(session=None, acting_role=UserRole.student, subject_student_id=None)


def _serve(monkeypatch, *, asker_program, chunk_programs, school="professional-studies"):
    """Scope the asker to `asker_program`, return one chunk per entry in `chunk_programs`.

    Every chunk shares the asker's school and level, which is the whole point: this is the
    case the existing facets cannot separate.
    """
    monkeypatch.setattr(
        agent_tools,
        "_scope_for",
        lambda ctx: RetrievalScope(
            school=school, level="graduate", program_slug=asker_program
        ),
    )

    def fake_search(session, query, role, k=5, scope=None, **kwargs):
        return RetrievalResult(
            chunks=[
                RetrievedChunk(
                    chunk_id=i,
                    text="Students must attend...",
                    heading_path="Policies > Program Policies",
                    section_keys=[],
                    document_title="A Program (MS)",
                    url="https://example.edu/programs/x/",
                    office="department",
                    fetched_at="2026-08-01T00:00:00+00:00",
                    score=0.7,
                    rank=i + 1,
                    school=school,
                    program_slug=program,
                )
                for i, program in enumerate(chunk_programs)
            ],
            degraded=False,
        )

    monkeypatch.setattr(agent_tools, "search_policy", fake_search)


def test_another_degrees_page_is_flagged(ctx, monkeypatch):
    """The reproduction: a Management & Analytics student, a Publishing passage ranks first."""
    _serve(
        monkeypatch,
        asker_program="management-analytics-ms",
        chunk_programs=["publishing-ms"],
    )
    result = tool_search_policy(ctx, "what is the attendance policy for my classes")

    passage = result["passages"][0]
    assert passage["written_for_program"] == "publishing-ms"
    assert passage["program_differs_from_students_own"] is True
    assert result["cross_program_warning"] is not None
    assert "different degree program" in result["cross_program_warning"].lower()


def test_the_students_own_program_is_not_flagged(ctx, monkeypatch):
    _serve(
        monkeypatch,
        asker_program="management-analytics-ms",
        chunk_programs=["management-analytics-ms"],
    )
    result = tool_search_policy(ctx, "what does my program require")

    assert result["passages"][0]["program_differs_from_students_own"] is False
    assert result["cross_program_warning"] is None


def test_school_wide_policy_is_never_flagged(ctx, monkeypatch):
    """A page belonging to no program applies to every program.

    This is the null case and it must read as "no signal", not as a mismatch. Getting it
    backwards would flag the school-wide Attendance Policy — the correct answer — as
    somebody else's rule, and the warning would fire on nearly every turn until it meant
    nothing.
    """
    _serve(
        monkeypatch, asker_program="management-analytics-ms", chunk_programs=[None, None]
    )
    result = tool_search_policy(ctx, "what is the attendance policy")

    assert all(not p["program_differs_from_students_own"] for p in result["passages"])
    assert result["cross_program_warning"] is None


def test_an_asker_with_no_program_gets_no_false_mismatch(ctx, monkeypatch):
    """Unknown on the asker's side is also no signal.

    A student who has not said what they study cannot have a passage contradict them, and
    claiming otherwise would put a warning on a turn where nothing is known.
    """
    _serve(monkeypatch, asker_program=None, chunk_programs=["publishing-ms"])
    result = tool_search_policy(ctx, "what is the attendance policy")

    assert result["passages"][0]["program_differs_from_students_own"] is False
    assert result["cross_program_warning"] is None


def test_a_mixed_result_set_flags_only_the_foreign_passage(ctx, monkeypatch):
    """The realistic shape: one sibling program's page among school-wide answers."""
    _serve(
        monkeypatch,
        asker_program="management-analytics-ms",
        chunk_programs=["publishing-ms", None, "management-analytics-ms"],
    )
    result = tool_search_policy(ctx, "what is the attendance policy")

    flags = [p["program_differs_from_students_own"] for p in result["passages"]]
    assert flags == [True, False, False]
    assert result["cross_program_warning"] is not None
