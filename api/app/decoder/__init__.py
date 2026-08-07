"""The registration error decoder.

A student pastes the message Albert showed them when enrollment failed; this package
turns that text into a named cause, an explanation with citations, and a next step.

Why it exists as its own package rather than as a prompt: the classification is a
decision, and decisions in this codebase are computed, not generated. See `patterns.py`
for the rule table and `classify.py` for the scoring.
"""

from app.decoder.classify import classify
from app.decoder.service import decode
from app.decoder.types import (
    Candidate,
    Classification,
    DecodeOutcome,
    DecodeResult,
    Evidence,
    Extracted,
    FollowUp,
)

__all__ = [
    "Candidate",
    "Classification",
    "DecodeOutcome",
    "DecodeResult",
    "Evidence",
    "Extracted",
    "FollowUp",
    "classify",
    "decode",
]
