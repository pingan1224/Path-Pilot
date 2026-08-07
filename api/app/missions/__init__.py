"""Registration missions: the resumable task of getting ready to register for one term.

Three modules, split by what they are allowed to touch:

- `types.py`  — the shapes, including `MissionFacts`, the frozen bundle the engine reads
- `steps.py`  — pure state computation from those facts, and nothing else
- `service.py` — the only module that touches the database
- `handoff.py` — a deterministic template over the facts

The mission's value to the rest of the system is that it gives the assistant a
**termination condition**. Every turn before this one was a stateless question and answer,
so "done" was not a concept the agent had. See `types.py` for why the end had to be
decidable rather than merely describable.
"""

from app.missions.handoff import build_handoff
from app.missions.steps import compute_state, unverifiable_for_handoff
from app.missions.types import (
    STEP_ORDER,
    AcceptedRisk,
    Candidate,
    CandidateState,
    MissionFacts,
    MissionState,
    Step,
    StepId,
    StepState,
)

__all__ = [
    "STEP_ORDER",
    "AcceptedRisk",
    "Candidate",
    "CandidateState",
    "MissionFacts",
    "MissionState",
    "Step",
    "StepId",
    "StepState",
    "build_handoff",
    "compute_state",
    "unverifiable_for_handoff",
]
