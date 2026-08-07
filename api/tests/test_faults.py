"""The fault injector's own safety properties.

A fault injector that can be armed on a deployed instance is a worse bug than anything it
finds, so the properties worth testing are the ones that keep it inert: off by default,
un-armable when off, scoped to the caller, and restored even when the body raises.

The one about unknown names matters for a different reason. A probe that arms
`embedings.unavailable` and silently injects nothing would report a degraded path that
never degraded — the same shape as a leakage probe that cannot detect a leak, which this
project has already been bitten by once.
"""

import pytest

from app import faults
from app.config import settings


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "fault_injection", True)
    return settings


# --------------------------------------------------------------------------------------
# Inert by default
# --------------------------------------------------------------------------------------


def test_injection_is_off_in_the_default_configuration():
    assert settings.fault_injection is False


def test_nothing_can_be_armed_while_injection_is_disabled():
    with pytest.raises(RuntimeError, match="disabled"):
        with faults.injected("llm.error"):
            pass


def test_an_injection_point_is_a_no_op_when_disabled():
    faults.fail_if_armed("llm.error")  # must not raise
    assert faults.active() == frozenset()


def test_a_leaked_arming_still_does_nothing_when_disabled(enabled, monkeypatch):
    """Belt and braces: even with faults armed, flipping the setting off disarms them."""
    with faults.injected("llm.error"):
        assert faults.is_armed("llm.error")
        monkeypatch.setattr(settings, "fault_injection", False)
        assert not faults.is_armed("llm.error")
        faults.fail_if_armed("llm.error")


# --------------------------------------------------------------------------------------
# Arming
# --------------------------------------------------------------------------------------


def test_an_armed_point_raises(enabled):
    with faults.injected("llm.error"):
        with pytest.raises(faults.InjectedFault):
            faults.fail_if_armed("llm.error")


def test_an_unarmed_point_does_not_raise_while_another_is_armed(enabled):
    with faults.injected("llm.error"):
        faults.fail_if_armed("retrieval.empty")


def test_an_unknown_fault_name_is_refused(enabled):
    """A typo must fail loudly, not measure the happy path and call it a degraded run."""
    with pytest.raises(ValueError, match="Unknown fault"):
        with faults.injected("embedings.unavailable"):
            pass


def test_a_parameterised_tool_fault_is_matched_by_tool_name(enabled):
    with faults.injected("tool.error:get_holds"):
        assert faults.armed_for_tool("get_holds")
        assert not faults.armed_for_tool("get_course_info")


def test_the_parameterised_prefix_is_still_validated(enabled):
    with pytest.raises(ValueError):
        with faults.injected("tool.oops:get_holds"):
            pass


# --------------------------------------------------------------------------------------
# Scoping
# --------------------------------------------------------------------------------------


def test_faults_are_disarmed_when_the_block_ends(enabled):
    with faults.injected("llm.error"):
        pass
    assert faults.active() == frozenset()


def test_faults_are_disarmed_even_when_the_body_raises(enabled):
    """The probe runs a real agent turn inside this block; turns fail."""
    with pytest.raises(ValueError):
        with faults.injected("llm.error"):
            raise ValueError("the turn blew up")
    assert faults.active() == frozenset()


def test_nesting_restores_the_outer_set_rather_than_clearing_it(enabled):
    with faults.injected("llm.error"):
        with faults.injected("retrieval.empty"):
            assert faults.is_armed("retrieval.empty")
            assert not faults.is_armed("llm.error")
        assert faults.is_armed("llm.error")


def test_every_declared_point_is_documented():
    """The probe reads FAULT_POINTS to explain itself; an undocumented point is a silent one."""
    assert faults.FAULT_POINTS
    assert all(desc.strip() for desc in faults.FAULT_POINTS.values())
