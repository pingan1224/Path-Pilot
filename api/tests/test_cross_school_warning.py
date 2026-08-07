"""Flagging a policy passage that belongs to a different school than the student's own.

Found live (2026-08-07), not in eval: an SPS Management and Analytics student asked whether
a Stern elective could count toward their program. One run out of six retrieved, top-ranked,
a School of Social Work cross-registration passage — real chunk, accurate quote, MSW-specific
credit rules — and the model narrated it as this student's own applicable procedure,
concluding "yes you can," never noticing the "(MSW)" sitting in the section heading it was
quoting.

The scope boost in `retrieval.py` is deliberately soft (a hard filter would sometimes hide
the only correct answer — a university-wide policy). Soft means a genuinely on-topic
passage from a *named, different* school can still outrank the student's own thin page, so
the fix is not a stronger filter; it is not leaving the mismatch for the model to infer from
prose. The tool now computes it as a fact and states it, and these tests are about that
computation being right — not about whether the model, given the fact, uses it well.
"""

import pytest

from app.models import UserRole
from app.services import agent_tools
from app.services.agent_tools import ToolContext, tool_search_policy
from app.services.retrieval import RetrievalResult, RetrievedChunk, RetrievalScope


@pytest.fixture
def ctx():
    return ToolContext(session=None, acting_role=UserRole.student, subject_student_id=None)


def _serve(monkeypatch, *, asker_school, chunk_schools):
    """Scope the asker to `asker_school` and return one chunk per entry in `chunk_schools`."""
    monkeypatch.setattr(agent_tools, "_scope_for", lambda ctx: RetrievalScope(school=asker_school))

    def fake_search(session, query, role, k=5, scope=None, **kwargs):
        return RetrievalResult(
            chunks=[
                RetrievedChunk(
                    chunk_id=i,
                    text="...",
                    heading_path="Academic Policies > Cross-School Registration",
                    section_keys=[],
                    document_title="Academic Policies",
                    url="https://example.edu/policy",
                    office="registrar",
                    fetched_at="2026-08-01T00:00:00+00:00",
                    score=0.7,
                    rank=i + 1,
                    school=school,
                )
                for i, school in enumerate(chunk_schools)
            ],
            degraded=False,
        )

    monkeypatch.setattr(agent_tools, "search_policy", fake_search)


# --------------------------------------------------------------------------------------
# The exact live case
# --------------------------------------------------------------------------------------


def test_a_different_named_school_is_flagged(ctx, monkeypatch):
    """The reproduction: SPS student, a social-work passage ranks first."""
    _serve(monkeypatch, asker_school="professional-studies", chunk_schools=["social-work"])
    result = tool_search_policy(ctx, "take courses at Stern as graduate student")
    assert result["passages"][0]["school"] == "social-work"
    assert result["passages"][0]["school_differs_from_students_own"] is True
    assert result["cross_school_warning"] is not None
    assert "different school" in result["cross_school_warning"].lower()


def test_a_matching_school_is_not_flagged(ctx, monkeypatch):
    _serve(monkeypatch, asker_school="professional-studies", chunk_schools=["professional-studies"])
    result = tool_search_policy(ctx, "elective options")
    assert result["passages"][0]["school_differs_from_students_own"] is False
    assert result["cross_school_warning"] is None


def test_one_mismatched_passage_among_several_still_warns(ctx, monkeypatch):
    """The live failure was one bad passage among five; the flag must not average away."""
    _serve(
        monkeypatch,
        asker_school="professional-studies",
        chunk_schools=["professional-studies", "social-work", "business"],
    )
    result = tool_search_policy(ctx, "cross registration")
    flags = [p["school_differs_from_students_own"] for p in result["passages"]]
    assert flags == [False, True, True]
    assert result["cross_school_warning"] is not None


# --------------------------------------------------------------------------------------
# Where the flag correctly stays quiet
# --------------------------------------------------------------------------------------


def test_a_university_wide_passage_is_not_flagged(ctx, monkeypatch):
    """`school IS NULL` means the policy applies everywhere — not a mismatch."""
    _serve(monkeypatch, asker_school="professional-studies", chunk_schools=[None])
    result = tool_search_policy(ctx, "academic integrity policy")
    assert result["passages"][0]["school_differs_from_students_own"] is False
    assert result["cross_school_warning"] is None


def test_the_synthetic_fixture_school_is_never_flagged(ctx, monkeypatch):
    """The role-restricted eval fixtures carry school='synthetic'; not a real mismatch."""
    _serve(monkeypatch, asker_school="professional-studies", chunk_schools=["synthetic"])
    result = tool_search_policy(ctx, "advisor override procedure")
    assert result["passages"][0]["school_differs_from_students_own"] is False


def test_an_unscoped_asker_gets_no_mismatch_claims(ctx, monkeypatch):
    """No signal on the asker's side must not be read as 'matches everything'.

    Policy-only questions (no subject student) have no school to compare against — the flag
    must stay False rather than silently asserting a match it cannot know.
    """
    _serve(monkeypatch, asker_school=None, chunk_schools=["social-work"])
    result = tool_search_policy(ctx, "cross registration")
    assert result["passages"][0]["school_differs_from_students_own"] is False
    assert result["cross_school_warning"] is None


def test_an_unknown_passage_school_is_not_claimed_as_a_mismatch(ctx, monkeypatch):
    """Missing data on the passage's side is the same 'no signal' case, not evidence either way."""
    _serve(monkeypatch, asker_school="professional-studies", chunk_schools=[None])
    result = tool_search_policy(ctx, "grading policy")
    assert result["passages"][0]["school_differs_from_students_own"] is False
