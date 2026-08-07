"""The policy-search budget.

The defect this guards against is not a wrong answer — B26 refused correctly. It is a turn
that spends 13 tool calls and 8 uncited searches reformulating its way towards a document
it is never going to retrieve, because retrieval always returns its five nearest chunks and
so never signals "there is nothing here".

`scripts/measure_giveup.py` records why the mechanism is a count and not a quality
judgement: a relevance floor, query similarity, and result novelty were all measured and
all failed to separate circling from diligence, two of them backwards. So these tests are
about the budget behaving like a budget — spent by calls, refusing without retrieving,
visible to the model before it runs out — and deliberately not about the server deciding
which search was worth making.
"""

import pytest

from app.models import UserRole
from app.services import agent_tools
from app.services.agent_tools import MAX_POLICY_SEARCHES, ToolContext, tool_search_policy
from app.services.retrieval import RetrievalResult, RetrievedChunk


@pytest.fixture
def ctx():
    # No subject student, so nothing in this path touches the session.
    return ToolContext(session=None, acting_role=UserRole.student, subject_student_id=None)


@pytest.fixture
def searches(monkeypatch):
    """Replace retrieval with a recorder that always returns one passage."""
    calls: list[str] = []

    def fake_search(session, query, role, k=5, scope=None, **kwargs):
        calls.append(query)
        return RetrievalResult(
            chunks=[
                RetrievedChunk(
                    chunk_id=len(calls),
                    text="...",
                    heading_path="Policy > Section",
                    section_keys=["slug#Policy > Section"],
                    document_title="Academic Policies",
                    url="https://example.edu/policy",
                    office="registrar",
                    fetched_at="2026-08-01T00:00:00+00:00",
                    score=0.7,
                    rank=1,
                )
            ],
            degraded=False,
        )

    monkeypatch.setattr(agent_tools, "search_policy", fake_search)
    return calls


# --------------------------------------------------------------------------------------
# Spending it
# --------------------------------------------------------------------------------------


def test_searches_within_the_budget_are_served(ctx, searches):
    for i in range(MAX_POLICY_SEARCHES):
        result = tool_search_policy(ctx, f"query {i}")
        assert result["passages"]
    assert len(searches) == MAX_POLICY_SEARCHES


def test_the_remaining_balance_counts_down(ctx, searches):
    first = tool_search_policy(ctx, "a")
    assert first["searches_remaining_this_turn"] == MAX_POLICY_SEARCHES - 1
    last = None
    for i in range(MAX_POLICY_SEARCHES - 1):
        last = tool_search_policy(ctx, f"b{i}")
    assert last["searches_remaining_this_turn"] == 0


def test_the_model_is_warned_before_it_runs_out(ctx, searches):
    """A stop the model saw coming, not one it discovers by being refused."""
    notes = [
        tool_search_policy(ctx, f"q{i}")["budget_note"] for i in range(MAX_POLICY_SEARCHES)
    ]
    assert notes[0] is None
    assert notes[-1] is not None


# --------------------------------------------------------------------------------------
# Running out
# --------------------------------------------------------------------------------------


def test_the_call_past_the_budget_is_refused(ctx, searches):
    for i in range(MAX_POLICY_SEARCHES):
        tool_search_policy(ctx, f"q{i}")
    refused = tool_search_policy(ctx, "one more wording")
    assert refused["error"] == "search_budget_exhausted"
    assert "passages" not in refused


def test_a_refused_search_does_not_reach_retrieval(ctx, searches):
    """No embedding call, no query, and no fresh passages to tempt another reformulation."""
    for i in range(MAX_POLICY_SEARCHES):
        tool_search_policy(ctx, f"q{i}")
    tool_search_policy(ctx, "one more wording")
    assert len(searches) == MAX_POLICY_SEARCHES
    assert "one more wording" not in ctx.policy_queries


def test_the_refusal_shows_what_was_already_tried(ctx, searches):
    """So the model reports what it looked for, rather than claiming it did not look."""
    for i in range(MAX_POLICY_SEARCHES):
        tool_search_policy(ctx, f"query {i}")
    refused = tool_search_policy(ctx, "again")
    assert refused["queries_already_tried"] == [f"query {i}" for i in range(MAX_POLICY_SEARCHES)]


def test_running_out_is_recorded_as_a_degradation(ctx, searches):
    """The audit row has to show the turn answered on less evidence than it wanted."""
    for i in range(MAX_POLICY_SEARCHES):
        tool_search_policy(ctx, f"q{i}")
    assert "retrieval_budget_exhausted" not in ctx.degraded_modes
    tool_search_policy(ctx, "again")
    assert "retrieval_budget_exhausted" in ctx.degraded_modes


def test_a_refusal_adds_no_citable_source(ctx, searches):
    for i in range(MAX_POLICY_SEARCHES):
        tool_search_policy(ctx, f"q{i}")
    before = set(ctx.seen_source_ids)
    tool_search_policy(ctx, "again")
    assert ctx.seen_source_ids == before


# --------------------------------------------------------------------------------------
# What the budget deliberately does not do
# --------------------------------------------------------------------------------------


def test_the_budget_is_per_turn_not_per_process(searches):
    """Each turn gets its own context, so a long conversation is not slowly starved."""
    first = ToolContext(session=None, acting_role=UserRole.student, subject_student_id=None)
    for i in range(MAX_POLICY_SEARCHES):
        tool_search_policy(first, f"q{i}")
    second = ToolContext(session=None, acting_role=UserRole.student, subject_student_id=None)
    assert tool_search_policy(second, "fresh turn")["passages"]


def test_a_repeated_query_still_costs_a_search(ctx, searches):
    """No special case for repeats.

    Deduplicating would be a judgement about which search was worth making, and the
    measurement says the server cannot make that judgement: the most repetitive turn in the
    audit log is four legitimate prerequisite lookups. The trajectory scorer already counts
    identical calls as redundant; the budget only counts.
    """
    for _ in range(MAX_POLICY_SEARCHES):
        tool_search_policy(ctx, "same question")
    assert tool_search_policy(ctx, "same question")["error"] == "search_budget_exhausted"


def test_the_budget_does_not_second_guess_low_scoring_results(ctx, monkeypatch):
    """A weak-looking passage is still returned. The floor was measured and does not exist."""

    def weak(session, query, role, k=5, scope=None, **kwargs):
        return RetrievalResult(
            chunks=[
                RetrievedChunk(
                    chunk_id=1, text="...", heading_path=None, section_keys=[],
                    document_title="d", url="u", office="registrar",
                    fetched_at="2026-08-01T00:00:00+00:00", score=0.31, rank=1,
                )
            ],
            degraded=False,
        )

    monkeypatch.setattr(agent_tools, "search_policy", weak)
    assert tool_search_policy(ctx, "obscure")["passages"]
