"""The Artifact Contract: what the UI renders, separated from what the agent did.

Until now the frontend read `tool_trace` — the audit record — and *inferred* which cards a
turn had earned, then re-fetched each one over HTTP. It worked, but every new card meant
teaching the client another inference rule, and the audit trail was doing double duty as a
UI protocol it never promised to be.

This module makes the server say it outright. After a turn finishes, the trace is reduced
to a list of artifact *specs* (a pure function — the part with rules worth testing), and
each spec is then built by calling the same code the full pages call, so a card in the chat
and the page it links to cannot disagree about shape. `tool_trace` goes back to being an
audit record.

Three rules carried over from the client-side inference, now enforced here:

- A build failure skips the artifact, never the answer. The card is a convenience; the
  text is the product.
- Two schedules is a comparison; more is noise. Distinct sequence requests cap at two.
- Artifacts are re-read at answer time, not snapshotted mid-turn — the mission a card
  shows is the mission as it stands after the turn's last write, recomputed the same way
  every read recomputes it.

The `type` field is a closed vocabulary (`ARTIFACT_TYPES`): the model cannot invent a
card, and a client that meets a type it does not know falls back to text rather than
trusting whatever arrived.
"""

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.services.auth import Identity

log = logging.getLogger(__name__)

# The closed set. Growing it is an API change: bump the artifact `version` if an existing
# type's shape changes, add contract tests either way.
ARTIFACT_TYPES = ("mission_state", "course_sequence", "decoder_result")

MISSION_TOOLS = ("get_mission_state", "propose_mission_candidates")

MAX_SEQUENCE_ARTIFACTS = 2


class ArtifactAction(BaseModel):
    """A description of something the student can do with the artifact — never an
    endpoint. The client maps action types to its own registered calls; a URL or method
    arriving from the server (ultimately: from near a model) is not something to obey."""

    type: str
    candidate_id: int | None = None


class ArtifactOut(BaseModel):
    id: str
    type: Literal["mission_state", "course_sequence", "decoder_result"]
    version: int
    status: str
    canonical_ref: dict[str, Any] | None
    data: dict[str, Any] | None
    actions: list[ArtifactAction]
    source_ids: list[str]


class ArtifactSpec(BaseModel):
    """What the trace says should exist, before anything is fetched."""

    type: str
    args: dict[str, Any]
    source_ids: list[str]


def specs_from_trace(
    tool_trace: list[dict[str, Any]], *, student_caller: bool
) -> list[ArtifactSpec]:
    """Reduce a turn's trace to the artifacts it earned. Pure — rules only.

    `student_caller` gates the record-bound artifacts: mission and sequence read the
    caller's own record through student-only services, so an account with no student record
    behind it earns no card rather than an empty one. That is now a narrow case — an
    advisor account has no workspace to ask from — and the gate stays because "there is no
    record here" and "the record is empty" must never render the same.
    """
    specs: list[ArtifactSpec] = []

    if student_caller:
        mission_calls = [t for t in tool_trace if t.get("tool") in MISSION_TOOLS]
        if mission_calls:
            specs.append(
                ArtifactSpec(
                    type="mission_state",
                    args={},
                    source_ids=_source_union(mission_calls),
                )
            )

        seen_args: set[str] = set()
        for call in tool_trace:
            if call.get("tool") != "get_course_sequence":
                continue
            args = call.get("args") or {}
            key = json.dumps(args, sort_keys=True, default=str)
            if key in seen_args:
                continue
            seen_args.add(key)
            specs.append(
                ArtifactSpec(
                    type="course_sequence",
                    args={
                        "deadline": args.get("finish_by"),
                        "max_credits_per_term": args.get("max_credits_per_term"),
                    },
                    source_ids=list(call.get("source_ids") or []),
                )
            )
            if len(seen_args) == MAX_SEQUENCE_ARTIFACTS:
                break

    decode_call = next(
        (
            t
            for t in tool_trace
            if t.get("tool") == "decode_registration_error"
            and (t.get("args") or {}).get("error_text")
        ),
        None,
    )
    if decode_call:
        specs.append(
            ArtifactSpec(
                type="decoder_result",
                args={"error_text": decode_call["args"]["error_text"]},
                source_ids=list(decode_call.get("source_ids") or []),
            )
        )

    return specs


def _source_union(calls: list[dict[str, Any]]) -> list[str]:
    ids: set[str] = set()
    for call in calls:
        ids.update(call.get("source_ids") or [])
    return sorted(ids)


def build_artifacts(
    session: Session, identity: Identity, specs: list[ArtifactSpec]
) -> list[ArtifactOut]:
    """Fetch each spec's data by calling the same code the full pages call.

    The imports live inside the function because the routers import this module's models;
    at module level the two layers would import each other.
    """
    built: list[ArtifactOut] = []
    for spec in specs:
        try:
            artifact = _build_one(session, identity, spec, id=f"a{len(built) + 1}")
        except Exception:  # noqa: BLE001 — the card is a convenience; the answer must survive it
            log.warning("artifact %s failed to build; skipped", spec.type, exc_info=True)
            # A failed statement can leave the transaction aborted, which would take the
            # remaining artifacts down with it — the same poisoned-transaction failure
            # fault injection found in the agent loop.
            session.rollback()
            continue
        built.append(artifact)
    return built


def _build_one(
    session: Session, identity: Identity, spec: ArtifactSpec, *, id: str
) -> ArtifactOut:
    if spec.type == "mission_state":
        from app.routers.missions import list_missions

        missions = list_missions(identity=identity, session=session)
        mission = next((m for m in missions if not m.complete), None)
        if mission is None:
            return ArtifactOut(
                id=id,
                type="mission_state",
                version=1,
                status="none_open",
                canonical_ref=None,
                data=None,
                actions=[ArtifactAction(type="mission_create")],
                source_ids=spec.source_ids,
            )
        proposed = [c for c in mission.candidates if c.state == "proposed"]
        return ArtifactOut(
            id=id,
            type="mission_state",
            version=1,
            status="awaiting_student" if proposed else "in_progress",
            canonical_ref={"resource": "mission", "id": mission.id},
            data=mission.model_dump(mode="json"),
            actions=[
                ArtifactAction(type="mission_candidate_decision", candidate_id=c.id)
                for c in proposed
            ],
            source_ids=spec.source_ids,
        )

    if spec.type == "course_sequence":
        from app.routers.sequence import get_sequence

        plan = get_sequence(
            start_term=None,
            deadline=spec.args.get("deadline"),
            max_credits_per_term=spec.args.get("max_credits_per_term"),
            identity=identity,
            session=session,
        )
        return ArtifactOut(
            id=id,
            type="course_sequence",
            # v2 (2026-08-13) carries `delay_costs`: what each of next term's courses costs
            # if it waits. Deliberately *not* a new artifact type. The data is computed with
            # the plan and travels with it, so a second type would mean a second builder and
            # a second card producing the same numbers — the parallel-surface mistake this
            # codebase has now paid for twice, in four personas and in two tool surfaces.
            # An older client ignores the field and renders the grid it always did.
            version=2,
            status="feasible" if plan.feasible else "infeasible",
            canonical_ref=None,
            data=plan.model_dump(mode="json"),
            actions=[],
            source_ids=spec.source_ids,
        )

    if spec.type == "decoder_result":
        from app.routers.decoder import DecodeRequest, post_decode

        decoded = post_decode(
            DecodeRequest(text=spec.args["error_text"]),
            identity=identity,
            session=session,
        )
        return ArtifactOut(
            id=id,
            type="decoder_result",
            version=1,
            status=decoded.outcome,
            canonical_ref=None,
            data=decoded.model_dump(mode="json"),
            actions=[],
            source_ids=spec.source_ids,
        )

    raise ValueError(f"unknown artifact spec type {spec.type!r}")
