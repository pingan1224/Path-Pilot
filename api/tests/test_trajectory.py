"""Trajectory scoring tests.

Pure functions over hand-built traces, so every branch is reachable without a model call.

The cases that matter are the ones where a metric could quietly become wrong in a way that
makes the agent look better than it is: a repeat that is not counted because the arguments
were serialised in a different key order, an uncited lookup that is not counted because the
trace predates per-call attribution, or a rate that a long clean run dilutes.
"""

from eval.trajectory import aggregate, score_trace


def call(tool, args=None, iteration=1, source_ids=None, failed=False):
    entry = {"tool": tool, "args": args or {}, "iteration": iteration}
    if source_ids is not None:
        entry["source_ids"] = source_ids
    if failed:
        entry["failed"] = True
    return entry


# --------------------------------------------------------------------------------------
# Counting
# --------------------------------------------------------------------------------------


def test_an_empty_trace_scores_zero_rather_than_dividing_by_it():
    score = score_trace([], [])
    assert score.tool_calls == 0
    assert score.iterations == 0
    assert score.parallelism == 0.0


def test_distinct_tools_counts_the_tool_not_the_call():
    trace = [
        call("get_course_info", {"course_code": "A"}),
        call("get_course_info", {"course_code": "B"}),
        call("get_holds"),
    ]
    score = score_trace(trace, [])
    assert score.tool_calls == 3
    assert score.distinct_tools == 2


def test_different_arguments_are_not_a_repeat():
    """Four course lookups for four different courses is diligence, not waste."""
    trace = [call("get_course_info", {"course_code": c}) for c in "ABCD"]
    assert score_trace(trace, []).redundant_calls == 0


def test_an_identical_call_is_a_repeat():
    trace = [call("get_holds"), call("get_holds")]
    score = score_trace(trace, [])
    assert score.redundant_calls == 1
    assert score.redundant_detail


def test_three_identical_calls_count_as_two_repeats():
    score = score_trace([call("get_holds")] * 3, [])
    assert score.redundant_calls == 2


def test_argument_key_order_does_not_hide_a_repeat():
    """The same call with its JSON keys in a different order is the same call."""
    trace = [
        call("get_course_sequence", {"finish_by": "Fall 2026", "max_credits_per_term": 9}),
        call("get_course_sequence", {"max_credits_per_term": 9, "finish_by": "Fall 2026"}),
    ]
    assert score_trace(trace, []).redundant_calls == 1


def test_unserialisable_arguments_do_not_crash_the_scorer():
    score = score_trace([{"tool": "x", "args": {1, 2, 3}, "iteration": 1}], [])
    assert score.tool_calls == 1


# --------------------------------------------------------------------------------------
# Iterations and parallelism
# --------------------------------------------------------------------------------------


def test_stored_iterations_are_preferred_over_the_trace():
    """The answering turn calls no tool, so the trace always undercounts it."""
    trace = [call("get_holds", iteration=1)]
    assert score_trace(trace, [], iterations=2).iterations == 2


def test_iterations_fall_back_to_the_trace_when_not_stored():
    trace = [call("a", iteration=1), call("b", iteration=3)]
    assert score_trace(trace, []).iterations == 3


def test_parallelism_rewards_batching_independent_lookups():
    batched = score_trace([call("a", iteration=1), call("b", iteration=1)], [], iterations=1)
    serial = score_trace([call("a", iteration=1), call("b", iteration=2)], [], iterations=2)
    assert batched.parallelism == 2.0
    assert serial.parallelism == 1.0


# --------------------------------------------------------------------------------------
# Uncited work
# --------------------------------------------------------------------------------------


def test_a_lookup_whose_sources_are_cited_is_used():
    trace = [call("get_holds", source_ids=["record:hold:1"])]
    citations = [{"source_id": "record:hold:1", "claim": "x"}]
    assert score_trace(trace, citations).unused_results == 0


def test_a_lookup_whose_sources_are_never_cited_is_flagged():
    trace = [call("get_course_info", {"course_code": "X"}, source_ids=["record:course:X"])]
    assert score_trace(trace, []).unused_results == 1


def test_partial_citation_counts_as_used():
    """One of three sources cited is still a lookup that earned its place."""
    trace = [call("search_policy", source_ids=["policy:chunk:1", "policy:chunk:2"])]
    citations = [{"source_id": "policy:chunk:2", "claim": "x"}]
    assert score_trace(trace, citations).unused_results == 0


def test_a_trace_without_attribution_is_not_scored_as_unused():
    """Rows predating per-call attribution must not be turned into a fake regression."""
    trace = [call("get_holds")]  # no source_ids key at all
    assert score_trace(trace, []).unused_results == 0


def test_a_call_that_produced_nothing_is_not_counted_as_unused():
    """A tool can legitimately return no citable source — an empty checklist, an error."""
    trace = [call("get_holds", source_ids=[])]
    assert score_trace(trace, []).unused_results == 0


def test_the_legacy_trace_key_is_still_read():
    """The two oldest audit rows use `name`, from before the key was renamed."""
    trace = [{"name": "get_active_holds", "args": {"student_id": "self"}, "iteration": 1}]
    score = score_trace(trace, [])
    assert score.tool_calls == 1
    assert score.distinct_tools == 1
    # and it is identifiable, not scored as an unnamed tool
    assert "?" not in score.redundant_detail


# --------------------------------------------------------------------------------------
# Forbidden tools and path ratio
# --------------------------------------------------------------------------------------


def test_a_forbidden_tool_is_reported_by_name():
    trace = [call("propose_mission_candidates", {"courses": []})]
    score = score_trace(trace, [], must_not_call=("propose_mission_candidates",))
    assert score.forbidden_calls == ("propose_mission_candidates",)


def test_forbidden_counting_survives_repeats():
    trace = [call("propose_mission_candidates", {"courses": [1]}),
             call("propose_mission_candidates", {"courses": [2]})]
    score = score_trace(trace, [], must_not_call=("propose_mission_candidates",))
    assert len(score.forbidden_calls) == 2


def test_a_failed_call_is_counted():
    trace = [call("search_policy", failed=True), call("get_holds")]
    assert score_trace(trace, []).failed_calls == 1


def test_path_ratio_is_none_without_a_labelled_minimum():
    """A guessed minimum would make the ratio look rigorous and mean nothing."""
    assert score_trace([call("a")], []).path_ratio is None


def test_path_ratio_reports_overshoot():
    trace = [call("a"), call("b"), call("c")]
    assert score_trace(trace, [], min_tool_calls=1).path_ratio == 3.0


def test_path_ratio_of_one_is_an_optimal_run():
    assert score_trace([call("a")], [], min_tool_calls=1).path_ratio == 1.0


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------


def test_aggregating_nothing_gives_nulls_not_zeros():
    """Zero would read as 'measured and clean'; null reads as 'not measured'."""
    stats = aggregate([])
    assert stats["runs"] == 0
    assert stats["redundant_call_rate"] is None
    assert stats["tool_calls_mean"] is None


def test_rates_are_per_run_so_one_clean_long_run_cannot_absorb_a_bad_short_one():
    clean = score_trace([call(f"t{i}") for i in range(12)], [])
    messy = score_trace([call("x"), call("x")], [])
    stats = aggregate([clean, messy])
    # Per call, two repeats in fourteen would look like 0.07. Per run it is a half.
    assert stats["redundant_call_rate"] == 0.5


def test_path_ratio_mean_states_the_size_of_its_subset():
    labelled = score_trace([call("a")], [], min_tool_calls=1)
    unlabelled = score_trace([call("a"), call("b")], [])
    stats = aggregate([labelled, unlabelled])
    assert stats["path_ratio_n"] == 1
    assert stats["path_ratio_mean"] == 1.0


def test_forbidden_calls_aggregate_as_a_count_not_a_rate():
    """A hard-zero gate needs the count; a rate would round a single breach away."""
    one = score_trace(
        [call("propose_mission_candidates")], [], must_not_call=("propose_mission_candidates",)
    )
    clean = score_trace([call("get_holds")], [])
    assert aggregate([one] + [clean] * 40)["forbidden_calls"] == 1
