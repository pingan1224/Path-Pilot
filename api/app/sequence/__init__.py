"""Sequence planning: laying the remaining requirements across future terms.

The technically hardest part of the product, and deliberately not the thing the earlier
sketch called it. "Find an alternative course" sounds like graph search over prerequisites,
but the MASY prerequisite chain is two levels deep at most — search over it degenerates into
a lookup. The real constraint problem is *ordering the terms*: prerequisite order, when each
course is actually offered, how many credits fit in a term, one concentration chosen in
full, and a term to finish by. Those interact, and the interaction is what a student cannot
work out on paper.

Modules, by what they may touch:

- `terms.py`      — term values and arithmetic
- `offerings.py`  — the bulletin's offering text, parsed with its confidence kept
- `types.py`      — the shapes, including what each placement rests on
- `solver.py`     — backtracking search, and infeasibility attributed by relaxation
- `plan.py`       — requirement kinds into needs; the only module that knows about programs
- `service.py`    — the only module that touches the database
"""

from app.sequence.offerings import Offering, OfferingBasis, parse_offering
from app.sequence.plan import ASSUMED_CREDIT_CAP, build_sequence
from app.sequence.solver import explain_infeasibility, solve, topological_order
from app.sequence.terms import Season, Term
from app.sequence.types import (
    Assumption,
    Constraint,
    CourseNeed,
    Infeasibility,
    Placement,
    SequencePlan,
)

__all__ = [
    "ASSUMED_CREDIT_CAP",
    "Assumption",
    "Constraint",
    "CourseNeed",
    "Infeasibility",
    "Offering",
    "OfferingBasis",
    "Placement",
    "Season",
    "SequencePlan",
    "Term",
    "build_sequence",
    "explain_infeasibility",
    "parse_offering",
    "solve",
    "topological_order",
]
