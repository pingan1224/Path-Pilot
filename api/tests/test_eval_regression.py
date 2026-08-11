"""Per-case comparison against the last complete run.

`latest.json` had been written since this harness existed and read by nothing but a
21-line viewer. Every threshold in GATE is an absolute floor over an average, and the
averages are wide: one case flipping from pass to fail moves high-stakes recall by 1/9 and
over-escalation by 1/15, neither far enough to break a floor. The suite could go green
while something that worked yesterday stopped working.

What these tests hold:

* both report shapes are readable, so the comparison works on the *first* run after the
  feature lands rather than one run later;
* only `pass -> fail` gates, because gating a move into `flaky` would gate flakiness
  through the back door — and one extra sample of a borderline case produces exactly that
  transition on its own;
* a missing or corrupt baseline degrades to "no comparison", never to a crash. A safety
  net that can take down the thing it protects is worse than no net.

Pure functions over recorded results: no database, no model, free on every push.
"""

from scripts.run_eval import _verdicts_from, compare_to_baseline


def _report(verdicts: dict[str, str], *, stamp="20260810-000000", repeat=3) -> dict:
    return {
        "stamp": stamp,
        "behavior": {
            "repeat": repeat,
            "by_case": [{"id": k, "verdict": v} for k, v in verdicts.items()],
        },
    }


def _current(verdicts: dict[str, str], repeat=3) -> dict:
    return {
        "repeat": repeat,
        "by_case": [{"id": k, "verdict": v} for k, v in verdicts.items()],
    }


# --- reading both shapes -------------------------------------------------------------


def test_a_pre_repeat_baseline_is_still_readable():
    """Runs recorded before --repeat have no by_case and one entry per case.

    Refusing to read them would make the comparison useless exactly when it is first
    switched on, which in practice means it never starts being useful.
    """
    old = {
        "cases": [
            {"id": "B01", "passed": True},
            {"id": "B02", "passed": False},
        ]
    }
    assert _verdicts_from(old) == {"B01": "pass", "B02": "fail"}


def test_the_new_shape_wins_when_both_are_present():
    both = {
        "by_case": [{"id": "B01", "verdict": "flaky"}],
        "cases": [{"id": "B01", "attempt": 1, "passed": True}],
    }
    assert _verdicts_from(both) == {"B01": "flaky"}


# --- what counts as a regression -----------------------------------------------------


def test_pass_to_fail_is_the_gating_regression():
    out = compare_to_baseline(
        _current({"B01": "fail"}), _report({"B01": "pass"})
    )
    assert out["regressed"] == [{"id": "B01", "from": "pass", "to": "fail"}]
    assert out["destabilised"] == []


def test_pass_to_flaky_is_reported_but_not_a_regression():
    """Destabilising is real and worth seeing, but it is not gated.

    Flakiness itself is deliberately not gated, so gating a transition *into* it would
    gate it through the back door — and a borderline case sampled once more produces this
    transition without anything having changed.
    """
    out = compare_to_baseline(
        _current({"B20": "flaky"}), _report({"B20": "pass"})
    )
    assert out["regressed"] == []
    assert out["destabilised"] == [{"id": "B20", "from": "pass", "to": "flaky"}]


def test_recovering_from_fail_or_flaky_counts_as_improved():
    out = compare_to_baseline(
        _current({"B20": "pass", "B35": "pass"}),
        _report({"B20": "flaky", "B35": "fail"}),
    )
    assert {m["id"] for m in out["improved"]} == {"B20", "B35"}
    assert out["regressed"] == []


def test_flaky_to_fail_is_movement_but_not_gated():
    out = compare_to_baseline(_current({"B20": "fail"}), _report({"B20": "flaky"}))
    assert out["regressed"] == []
    assert out["other"] == [{"id": "B20", "from": "flaky", "to": "fail"}]


def test_an_unchanged_set_reports_nothing():
    verdicts = {"B01": "pass", "B02": "pass", "B20": "flaky"}
    out = compare_to_baseline(_current(verdicts), _report(verdicts))
    assert out["regressed"] == []
    assert out["destabilised"] == []
    assert out["improved"] == []
    assert out["other"] == []
    assert out["added"] == [] and out["removed"] == []


# --- set membership changes ----------------------------------------------------------


def test_added_and_removed_cases_are_named_not_treated_as_movement():
    """A case that did not exist yesterday has not regressed, and one that is gone has not
    been fixed. Folding either into the verdict counts would fabricate a change."""
    out = compare_to_baseline(
        _current({"B01": "pass", "B36": "fail"}),
        _report({"B01": "pass", "B02": "pass"}),
    )
    assert out["added"] == ["B36"]
    assert out["removed"] == ["B02"]
    assert out["regressed"] == []


# --- degrading safely ----------------------------------------------------------------


def test_no_baseline_means_no_comparison_not_a_failure():
    assert compare_to_baseline(_current({"B01": "pass"}), None) is None


def test_an_empty_baseline_behaviour_block_is_ignored():
    assert compare_to_baseline(_current({"B01": "pass"}), {"stamp": "x"}) is None
    assert compare_to_baseline(_current({"B01": "pass"}), {"behavior": {}}) is None


def test_the_baselines_repeat_count_travels_with_the_comparison():
    """A baseline of one attempt per case makes any single-case movement weaker evidence,
    and the report says so rather than presenting the diff as settled."""
    out = compare_to_baseline(_current({"B01": "pass"}), _report({"B01": "pass"}, repeat=1))
    assert out["baseline_repeat"] == 1


# --- the baseline is a ratchet --------------------------------------------------------


def test_a_failing_run_must_not_become_the_baseline(tmp_path, monkeypatch):
    """The failure mode found the first time a baseline was written.

    That run had one turn where the model was never reached, declared its own measurement
    void — and recorded itself as the thing every later run would be compared against. A
    baseline containing a failure means the next run sees no movement and reports green:
    the gate would launder its own failures into the definition of normal.
    """
    from scripts import run_eval

    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    retrieval = {
        "cases": [], "strategy": "heading", "recall_at_5": 1.0, "mrr": 1.0,
        "sections_per_chunk": 1.0, "families": {},
    }
    behavior = {
        "cases": [], "by_case": [], "repeat": 1, "flaky": 0, "trajectory": {},
        "model": "test", "passed": 1, "total": 1, "attempts_total": 1,
        "high_stakes_escalation_recall": 1.0, "over_escalation_rate": 0.0,
        "citation_coverage_answered": 1.0, "intent_accuracy": 1.0,
        "leakage_failures": 0, "leaks": [], "assistant_failures": 0,
        "latency_p50_ms": 1, "latency_p95_ms": 1, "iterations_mean": 1.0,
    }
    decoder = {
        "cases": [], "counts": {}, "passed": 1, "total": 1, "coverage": 1.0,
        "accuracy_when_named": 1.0, "confidently_wrong": 0, "ambiguity_held": 1.0,
        "unsafe_hold_reads": 0, "families": {},
    }
    parts = (retrieval, behavior, decoder, None)

    run_eval.write_report(*parts, ["assistant never reached on 1 run(s)"], 1.0)
    assert not (tmp_path / "latest.json").exists(), "a failing run wrote the baseline"

    run_eval.write_report(*parts, [], 1.0)
    assert (tmp_path / "latest.json").exists(), "a passing run failed to write the baseline"
