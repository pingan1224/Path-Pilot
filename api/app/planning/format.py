"""Rendering credit counts as prose.

Credits are floats because half credits are real (`Course.credits`,
`Requirement.min_credits`), but a float renders as `15.0` and a bulletin never writes it
that way. Left alone, the planner produced findings reading

    Electives: 15.0 credit(s) short
    0 of 15.0 credits so far. Select 15 credits across the ...

with the tool's own number and the bulletin's quoted number disagreeing in the same
sentence — on the one surface whose whole claim is that every figure has a provenance.

This lives in `planning` rather than `services` because the rule engine is the lowest
layer and must not import upward; `sequence` and `readiness` both already depend on it.
"""

from __future__ import annotations


def fmt_credits(value: float) -> str:
    """`15.0` -> `"15"`, `1.5` -> `"1.5"`, `0.0` -> `"0"`.

    Deliberately not a rounding function: `0.25` renders as `0.25`, not `0.2`. A credit
    total the student cannot reconcile against the bulletin is worth more noise than a
    tidy number that quietly lost a quarter credit.
    """
    return f"{value:g}"
