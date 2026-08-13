"""Every tool name a case labels must be a tool that exists.

A label naming a tool the registry does not have is not a failing test — it is a check that
cannot fire, which is worse. `must_call=("get_degree_progress",)` on a case whose tool was
deleted fails loudly, but `must_not_call` and the default write-tool ban fail *silently*:
a ban on a name nothing can call is satisfied by every run forever.

This was live on 2026-08-13. Hold-reading was removed, three tools went with it, and the
only guard on the golden set's tool names lived inline in the CI workflow and covered
`WRITE_TOOLS` alone — so three `must_call` labels went on pointing at a deleted tool, and
the workflow itself broke on an import of two registries that no longer existed. Both would
have surfaced here in the local suite, seconds after the deletion.

`WRITE_TOOLS` keeps its own assertion because it carries the strongest consequence: it is
banned by default across the whole set, so a rename that broke it would quietly un-ban the
write tools everywhere at once.
"""

from app.services.agent_tools import TOOL_IMPLS
from eval.golden import BEHAVIOR_CASES, RETRIEVAL_CASES, WRITE_TOOLS, forbidden_tools_for

KNOWN_TOOLS = set(TOOL_IMPLS)


def test_case_ids_are_unique():
    ids = [c.id for c in RETRIEVAL_CASES] + [c.id for c in BEHAVIOR_CASES]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicate case ids: {duplicates}"


def test_write_tool_names_still_resolve():
    missing = sorted(t for t in WRITE_TOOLS if t not in KNOWN_TOOLS)
    assert not missing, (
        f"WRITE_TOOLS names no longer exist: {missing}. The write tools are banned by "
        "default across the behavior set; a name that resolves to nothing bans nothing."
    )


def test_every_must_call_names_a_real_tool():
    broken = sorted(
        {(c.id, t) for c in BEHAVIOR_CASES for t in c.must_call if t not in KNOWN_TOOLS}
    )
    assert not broken, f"must_call names a tool that does not exist: {broken}"


def test_every_must_not_call_names_a_real_tool():
    """The silent half. A `must_not_call` on a deleted tool passes every run and proves
    nothing, so it needs the check more than `must_call`, which at least fails loudly."""
    broken = sorted(
        {
            (c.id, t)
            for c in BEHAVIOR_CASES
            for t in forbidden_tools_for(c)
            if t not in KNOWN_TOOLS
        }
    )
    assert not broken, f"a tool ban names a tool that does not exist: {broken}"


def test_the_write_tools_are_actually_banned_somewhere():
    """Guards the guard: if `forbidden_tools_for` ever returned empty for every case, all
    four tests above would still pass while nothing was banned at all."""
    banned = sum(1 for c in BEHAVIOR_CASES if forbidden_tools_for(c))
    assert banned > len(BEHAVIOR_CASES) // 2, (
        f"write tools banned on only {banned}/{len(BEHAVIOR_CASES)} cases; the default is "
        "supposed to be banned-unless-opted-in"
    )
