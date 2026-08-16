"""An empty answer is a failure, not an answer.

Found live 2026-08-07, one run in four: the model called `submit_answer` with no `answer`
field at all. `answer` is a required property in the tool schema, but a schema constrains
what the *API* will accept as a shape — it does not stop a model emitting arguments that
lack it. The loop took the payload, `response_text` was written as NULL, and the audit row
said `decision = answered`.

So the student saw an empty reply from a system whose own record claimed it had answered
them — a silent failure, and the audit log agreeing with the silence is the part that makes
it bad. Rule 6 says every failure is visible; this one was invisible in the one place that
is supposed to be able to reconstruct what happened.

These run the real loop with a stubbed model, so they cover the actual control flow rather
than a re-implementation of it.
"""

import json
from types import SimpleNamespace

import pytest

from app.models import InteractionDecision, UserRole
from app.services import agent as agent_module
from app.services.agent import run_agent


class FakeToolCall:
    def __init__(self, name, arguments, call_id="call_1"):
        self.id = call_id
        self.type = "function"
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments))


class FakeMessage:
    def __init__(self, tool_calls=None, content=""):
        self.tool_calls = tool_calls or []
        self.content = content


@pytest.fixture
def scripted(monkeypatch):
    """Drive `run_agent` with a fixed sequence of model replies."""

    def install(replies):
        calls = {"n": 0}

        def fake_chat(messages, tools=None, tool_choice=None, **kw):
            index = min(calls["n"], len(replies) - 1)
            calls["n"] += 1
            return replies[index], {"input_tokens": 1, "output_tokens": 1}

        monkeypatch.setattr(agent_module, "chat", fake_chat)
        return calls

    return install


def _answer_call(**overrides):
    args = {
        "answer": "Here is the answer.",
        "intent": "explain_blocker",
        "citations": [],
        "confidence": "high",
        "defer": False,
    }
    args.update(overrides)
    return FakeMessage([FakeToolCall("submit_answer", args)])


@pytest.fixture
def session(monkeypatch):
    """A session stub: the turn writes one audit row and never reads a student."""
    captured = {}

    class FakeSession:
        def add(self, obj):
            captured["row"] = obj

        def commit(self):
            pass

        def flush(self):
            pass

        def rollback(self):
            pass

        def get(self, model, pk):
            return None

        def scalar(self, *a, **kw):
            return None

    monkeypatch.setattr(agent_module, "schemas_for", lambda ctx: [])
    monkeypatch.setattr(agent_module, "tools_for", lambda ctx: {})
    return FakeSession(), captured


def _run(session_pair, question="Why is my registration blocked?"):
    session, captured = session_pair
    result = run_agent(
        session,
        question=question,
        acting_role=UserRole.student,
        subject_student_id=None,
        user_id=None,
    )
    return result, captured


# --------------------------------------------------------------------------------------
# The live failure
# --------------------------------------------------------------------------------------


def test_a_missing_answer_field_gets_one_retry(scripted, session):
    """First blank submission is a correction round, not a failure — models recover."""
    scripted([
        FakeMessage([FakeToolCall("submit_answer", {"intent": "explain_blocker",
                                                    "citations": [], "confidence": "high",
                                                    "defer": False})]),
        _answer_call(answer="Recovered: here is the real answer."),
    ])
    result, _ = _run(session)
    assert result.answer == "Recovered: here is the real answer."
    assert result.decision is not InteractionDecision.deferred


def test_a_blank_string_answer_counts_as_empty(scripted, session):
    scripted([
        _answer_call(answer="   "),
        _answer_call(answer="Recovered."),
    ])
    result, _ = _run(session)
    assert result.answer == "Recovered."


def test_twice_empty_becomes_a_deferral_not_a_blank_reply(scripted, session):
    """The outcome that matters: the student never receives nothing."""
    scripted([_answer_call(answer=""), _answer_call(answer="")])
    result, _ = _run(session)
    assert result.answer.strip()
    assert result.decision is InteractionDecision.deferred
    assert "empty_answer" in result.degraded_modes


def test_the_audit_row_never_records_an_empty_answer_as_answered(scripted, session):
    """The part that made this bad: the log agreed with the silence."""
    scripted([_answer_call(answer=""), _answer_call(answer="")])
    result, captured = _run(session)
    row = captured["row"]
    assert (row.response_text or "").strip()
    assert row.decision is InteractionDecision.deferred


# --------------------------------------------------------------------------------------
# The normal path is untouched
# --------------------------------------------------------------------------------------


def test_a_normal_answer_is_unaffected(scripted, session):
    scripted([_answer_call()])
    result, _ = _run(session)
    assert result.answer == "Here is the answer."
    assert result.decision is InteractionDecision.answered
    assert "empty_answer" not in result.degraded_modes


def test_a_deferral_with_real_text_is_unaffected(scripted, session):
    scripted([
        _answer_call(
            answer="Advising owns this one.",
            defer=True,
            referral={
                "office": "advising",
                "question": "can 1800 be waived",
                "bring": "transcript",
            },
        )
    ])
    result, _ = _run(session)
    assert result.decision is InteractionDecision.deferred
    assert result.answer == "Advising owns this one."
    # The referral reaches the caller: without it a deferral is a dead end, which is
    # what removing the case number would otherwise have made every one of them.
    assert result.referral["office"] == "advising"
