"""Deliberate failure injection, so the degraded paths are something we have watched run.

Rule 6 says no silent failures: every dependency has a visible degraded path. Those paths
were designed, documented, and — measured across 121 audited turns before this module
existed — **executed exactly zero times**. An `except` branch that has never run is not a
fallback, it is a guess with good intentions, and the place it fails is in front of a
student who has no way to know the answer got worse.

The point is not to test the `except` clause. A unit test with a monkeypatched exception
proves the syntax parses. What has to be proved is what the *student* ends up reading when
the embedding provider is down: that the caveat reaches the screen, that the audit row says
what happened, and — the failure mode that actually matters — that the model does not paper
over thinner evidence with a confident answer. So faults are injected into the real
dependencies and the real agent loop runs on top of them.

Two safety properties, because a fault injector reachable in production is a much worse bug
than the ones it finds:

1. **Inert unless the setting says otherwise.** `settings.fault_injection` defaults to
   False, and `active()` returns nothing when it is off. Arming a fault on a server that
   did not opt in does nothing at all.
2. **Scoped to the caller, not the process.** The armed set is a ContextVar, so one probe
   run cannot leak a fault into a concurrent request, and `injected()` restores the previous
   set on the way out even if the body raises.

Unknown fault names raise. A probe that quietly injects nothing would report a passing
degraded path that never degraded — the same class of bug as a leakage probe that cannot
detect a leak.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from app.config import settings

# Every fault this codebase knows how to inject, and the dependency each one stands in for.
#
# `tool.error` is parameterised — `tool.error:get_holds` — because the interesting question
# is not "do tools have an except branch" but "does the loop carry on usefully when the one
# lookup this question needed is the one that died".
FAULT_POINTS: dict[str, str] = {
    "embeddings.unavailable": "The embedding provider is down; retrieval must fall back to keyword ranking.",
    "llm.error": "The chat model call fails; the turn must end as a routed escalation, not a 500.",
    "retrieval.empty": "Retrieval runs but matches nothing. No exception, no degraded flag — the honest-answer path with zero evidence.",
    "tool.error": "A named record tool raises. Parameterise as `tool.error:<tool_name>`.",
    "freshness.all_stale": "Every record reads as past its freshness policy; disclosures must reach the answer.",
    "ocr.unavailable": (
        "The vision endpoint that reads photographed transcripts fails; intake must fall "
        "back to the honest refusal rather than to an empty reading."
    ),
    "search.budget_spent": (
        "The policy-search budget is already gone, so the first search is refused. Not a "
        "broken dependency — it forces M8's refusal branch, which shipped without anyone "
        "watching it run in a real turn."
    ),
}

_armed: ContextVar[frozenset[str]] = ContextVar("armed_faults", default=frozenset())


class InjectedFault(RuntimeError):
    """Raised at an injection point. Never raised unless a fault was deliberately armed."""


def _known(name: str) -> bool:
    return name.split(":", 1)[0] in FAULT_POINTS


def active() -> frozenset[str]:
    """The faults armed for this context, or nothing at all when injection is disabled."""
    if not settings.fault_injection:
        return frozenset()
    return _armed.get()


def is_armed(name: str) -> bool:
    return name in active()


def armed_for_tool(tool_name: str) -> bool:
    return f"tool.error:{tool_name}" in active()


@contextmanager
def injected(*names: str):
    """Arm faults for the duration of the block.

    Raises if injection is disabled, rather than running the body with nothing armed — a
    probe that silently measures the happy path is worse than one that fails to start.
    """
    if not settings.fault_injection:
        raise RuntimeError(
            "Fault injection is disabled. Set FAULT_INJECTION=true to run the fault probe; "
            "it must never be enabled on a deployed instance."
        )
    for name in names:
        if not _known(name):
            raise ValueError(
                f"Unknown fault {name!r}. Known points: {sorted(FAULT_POINTS)}"
            )
    token = _armed.set(frozenset(names))
    try:
        yield
    finally:
        _armed.reset(token)


def fail_if_armed(name: str) -> None:
    """Injection point. A no-op in every configuration except a probe that armed `name`."""
    if is_armed(name):
        raise InjectedFault(f"injected fault: {name}")
