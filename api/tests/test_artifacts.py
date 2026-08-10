"""Artifact Contract tests.

Written the way the mission tests are written: here is a trace, here are the artifacts
that must follow. No database — `specs_from_trace` is pure, and the schema itself is
exercised by constructing artifacts the way the builder does.

The properties defended here are the contract's actual promises, not implementation
details: the type vocabulary is closed, sequence artifacts cap at a comparison of two,
a caller with no student record earns no record-bound cards, and a decode with no pasted
text earns no decoder card.
"""

import pytest
from pydantic import ValidationError

from app.services.artifacts import (
    ARTIFACT_TYPES,
    MAX_SEQUENCE_ARTIFACTS,
    ArtifactAction,
    ArtifactOut,
    specs_from_trace,
)


def call(tool, args=None, source_ids=None, failed=False, iteration=1):
    return {
        "tool": tool,
        "args": args or {},
        "iteration": iteration,
        "source_ids": source_ids or [],
        "failed": failed,
    }


# ---- specs_from_trace: which artifacts a trace earns -------------------------------


def test_empty_trace_earns_nothing():
    assert specs_from_trace([], student_caller=True) == []


def test_mission_tools_earn_one_mission_artifact():
    trace = [
        call("get_mission_state", source_ids=["mission:42"]),
        call("propose_mission_candidates", source_ids=["mission:42", "course:MASY1-GC-2400"]),
    ]
    specs = specs_from_trace(trace, student_caller=True)
    assert [s.type for s in specs] == ["mission_state"]
    # Source ids are the union across the mission calls, deduplicated and stable.
    assert specs[0].source_ids == ["course:MASY1-GC-2400", "mission:42"]


def test_caller_without_a_student_record_earns_no_record_bound_artifacts():
    trace = [
        call("get_mission_state"),
        call("get_course_sequence"),
        call("decode_registration_error", args={"error_text": "ERR_PREREQ for MASY1-GC 3100"}),
    ]
    specs = specs_from_trace(trace, student_caller=False)
    # The decoder needs nothing but the pasted text; mission and sequence read a record.
    assert [s.type for s in specs] == ["decoder_result"]


def test_sequence_deduplicates_identical_requests():
    trace = [
        call("get_course_sequence", args={"finish_by": "Spring 2028"}),
        call("get_course_sequence", args={"finish_by": "Spring 2028"}),
    ]
    specs = specs_from_trace(trace, student_caller=True)
    assert [s.type for s in specs] == ["course_sequence"]
    assert specs[0].args == {"deadline": "Spring 2028", "max_credits_per_term": None}


def test_sequence_caps_at_a_comparison_of_two():
    trace = [
        call("get_course_sequence", args={"finish_by": f"Fall {year}"})
        for year in (2027, 2028, 2029)
    ]
    specs = specs_from_trace(trace, student_caller=True)
    assert len([s for s in specs if s.type == "course_sequence"]) == MAX_SEQUENCE_ARTIFACTS
    # The first two distinct requests win — the model's later retries are the noise.
    assert [s.args["deadline"] for s in specs] == ["Fall 2027", "Fall 2028"]


def test_decode_without_pasted_text_earns_no_card():
    specs = specs_from_trace(
        [call("decode_registration_error", args={})], student_caller=True
    )
    assert specs == []


def test_decode_keeps_the_text_it_will_reclassify():
    trace = [
        call(
            "decode_registration_error",
            args={"error_text": "You cannot add this class due to a hold on your record."},
            source_ids=["policy:holds-overview"],
        )
    ]
    (spec,) = specs_from_trace(trace, student_caller=True)
    assert spec.type == "decoder_result"
    assert spec.args["error_text"].startswith("You cannot add")
    assert spec.source_ids == ["policy:holds-overview"]


def test_unrelated_tools_earn_nothing():
    trace = [call("search_policy"), call("get_holds"), call("albert_checklist")]
    assert specs_from_trace(trace, student_caller=True) == []


def test_artifact_order_is_mission_then_sequences_then_decode():
    trace = [
        call("decode_registration_error", args={"error_text": "ERR_PREREQ"}),
        call("get_course_sequence"),
        call("get_mission_state"),
    ]
    specs = specs_from_trace(trace, student_caller=True)
    assert [s.type for s in specs] == ["mission_state", "course_sequence", "decoder_result"]


# ---- the schema: a closed vocabulary with required fields --------------------------


def artifact(**overrides):
    base = dict(
        id="a1",
        type="mission_state",
        version=1,
        status="in_progress",
        canonical_ref={"resource": "mission", "id": 42},
        data={"id": 42, "term": "Spring 2027"},
        actions=[ArtifactAction(type="mission_candidate_decision", candidate_id=7)],
        source_ids=["mission:42"],
    )
    base.update(overrides)
    return ArtifactOut(**base)


def test_artifact_serializes_with_every_contract_field():
    out = artifact().model_dump()
    assert set(out) == {
        "id",
        "type",
        "version",
        "status",
        "canonical_ref",
        "data",
        "actions",
        "source_ids",
    }
    assert out["actions"] == [{"type": "mission_candidate_decision", "candidate_id": 7}]


def test_unknown_type_is_structurally_impossible():
    with pytest.raises(ValidationError):
        artifact(type="kpi_dashboard")


def test_every_allowlisted_type_constructs():
    for kind in ARTIFACT_TYPES:
        assert artifact(type=kind, canonical_ref=None, data=None, actions=[]).type == kind


def test_actions_carry_no_endpoints():
    # The action model has no field a URL or HTTP method could arrive through — the
    # client's registry owns the mapping. If this test breaks, the contract changed.
    assert set(ArtifactAction.model_fields) == {"type", "candidate_id"}
