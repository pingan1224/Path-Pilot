"""The semantics of `--repeat`, held by tests rather than by whether a flake happens to
show up in a run.

Repetition exists because every failure this suite has ever produced turned out to be
intermittent: B05, then B20, and B35's write-tool call at 2 of 6. At one attempt per case
the gate reports a coin flip as a verdict. What repetition must buy, and what these tests
pin down:

* a three-state verdict, so a case that disagrees with itself is neither passed nor failed;
* hard zeros counted across every attempt, so N attempts is N chances to catch a rare
  violation rather than a vote that can outnumber it;
* rates that are means over attempts, so 2-of-3 contributes 0.67 instead of rounding.

`_aggregate_behavior` is a pure fold over recorded attempts, so this needs no database and
no model — it runs on every push.
"""

import pytest

from scripts.run_eval import _aggregate_behavior


class _Case:
    """Only the attributes the fold reads."""

    def __init__(self, cid, expect="answered", high_stakes=False):
        self.id = cid
        self.expect = expect
        self.high_stakes = high_stakes
        self.question = f"question for {cid}"
        self.note = ""


def _attempt(cid, attempt, *, passed, decision="answered", failures=(), high_stakes=False,
             expect="answered", citations=1):
    return {
        "id": cid,
        "attempt": attempt,
        "question": f"question for {cid}",
        "expect": expect,
        "high_stakes": high_stakes,
        "passed": passed,
        "failures": list(failures),
        "decision": decision,
        "intent": None,
        "intent_expected": None,
        "iterations": 2,
        "latency_ms": 1000,
        "tools": [],
        "citations": citations,
        "note": "",
        "trajectory": None,
    }


def test_a_case_that_agrees_with_itself_passes():
    cases = [_Case("B01")]
    rows = [_attempt("B01", i, passed=True) for i in (1, 2, 3)]

    out = _aggregate_behavior(cases, rows, repeat=3)

    assert out["by_case"][0]["verdict"] == "pass"
    assert out["passed"] == 1
    assert out["flaky"] == 0
    assert out["total"] == 1
    assert out["attempts_total"] == 3


def test_a_case_that_fails_every_attempt_is_a_failure_not_a_flake():
    cases = [_Case("B01")]
    rows = [
        _attempt("B01", i, passed=False, decision="escalated", failures=["expected answered"])
        for i in (1, 2, 3)
    ]

    out = _aggregate_behavior(cases, rows, repeat=3)

    assert out["by_case"][0]["verdict"] == "fail"
    assert out["passed"] == 0
    assert out["flaky"] == 0


def test_a_case_that_disagrees_with_itself_is_flaky_and_counted_as_neither():
    """The state the suite could not express before.

    Two of three passing is not a pass — shipping on it means the next run may say
    something else — and it is not a failure either. Counting it as either is how a coin
    flip became a verdict.
    """
    cases = [_Case("B20")]
    rows = [
        _attempt("B20", 1, passed=False, decision="escalated", failures=["expected answered, got escalated"]),
        _attempt("B20", 2, passed=True),
        _attempt("B20", 3, passed=True),
    ]

    out = _aggregate_behavior(cases, rows, repeat=3)

    entry = out["by_case"][0]
    assert entry["verdict"] == "flaky"
    assert entry["passed"] == 2 and entry["attempts"] == 3
    assert out["flaky"] == 1
    # Neither bucket claims it.
    assert out["passed"] == 0
    # The shape of the flake travels with it, so it can be argued about without a re-run.
    assert entry["decisions"] == ["escalated", "answered", "answered"]
    assert entry["failures"] == ["expected answered, got escalated"]


def test_repeated_identical_failures_are_not_listed_three_times():
    cases = [_Case("B01")]
    rows = [
        _attempt("B01", i, passed=False, failures=["same reason"]) for i in (1, 2, 3)
    ]

    out = _aggregate_behavior(cases, rows, repeat=3)
    assert out["by_case"][0]["failures"] == ["same reason"]


def test_one_leak_in_nine_attempts_still_fails_the_run():
    """The direction repetition must NOT go.

    A leak is a leak. If the hard zeros were majority votes, three attempts would let two
    clean runs outvote a real violation — turning the instrument that catches rare bugs
    into the one that hides them.
    """
    cases = [_Case("B24"), _Case("B25"), _Case("B26")]
    rows = [_attempt(c.id, i, passed=True) for c in cases for i in (1, 2, 3)]
    rows[4] = _attempt(
        "B25", 2, passed=False, failures=["LEAK: forbidden phrase present: 'denied appeal'"]
    )

    out = _aggregate_behavior(cases, rows, repeat=3)

    assert out["leakage_failures"] == 1
    assert out["flaky"] == 1  # and it is visible as a flake, not silently averaged away


def test_assistant_failures_are_counted_across_every_attempt():
    cases = [_Case("B35", expect="any")]
    rows = [
        _attempt("B35", 1, passed=True),
        _attempt(
            "B35", 2, passed=False, decision="escalated",
            failures=["ASSISTANT FAILED: llm_error — the model was never reached"],
        ),
        _attempt("B35", 3, passed=True),
    ]

    out = _aggregate_behavior(cases, rows, repeat=3)
    assert out["assistant_failures"] == 1


def test_rates_are_means_over_attempts_not_over_cases():
    """A high-stakes case that escalates twice in three contributes 0.67, not 1.0 or 0.0.

    Rounding to whichever side one sample landed on is exactly what made the headline
    number unstable between runs that changed nothing.
    """
    cases = [_Case("B13", expect="escalated", high_stakes=True)]
    rows = [
        _attempt("B13", 1, passed=True, decision="escalated", expect="escalated", high_stakes=True),
        _attempt("B13", 2, passed=True, decision="escalated", expect="escalated", high_stakes=True),
        _attempt("B13", 3, passed=False, decision="answered", expect="escalated", high_stakes=True),
    ]

    out = _aggregate_behavior(cases, rows, repeat=3)
    assert out["high_stakes_escalation_recall"] == pytest.approx(0.6667, abs=1e-4)


def test_single_attempt_behaves_exactly_as_before():
    """`--repeat 1` is the default and must not change any existing number."""
    cases = [_Case("B01"), _Case("B02")]
    rows = [_attempt("B01", 1, passed=True), _attempt("B02", 1, passed=False)]

    out = _aggregate_behavior(cases, rows, repeat=1)

    assert out["passed"] == 1
    assert out["total"] == 2
    assert out["flaky"] == 0
    assert out["attempts_total"] == 2
