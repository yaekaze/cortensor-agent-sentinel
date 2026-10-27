#!/usr/bin/env python3
"""Minimal reproduction for OM-0.1.13-BUG-2:
subagent(parent, tools=[decorated_tool]) passes callable function objects into
SubagentRunContext.tool_allowlist (handoff.py:278), crashing as_inbound_metadata()
at handoff.py:98 with TypeError: sequence item 0: expected str instance, function found.
"""

from __future__ import annotations

from openminion import tool
from openminion.api.handoff import SubagentRunContext


@tool(min_scope="READ_ONLY", idempotent=True)
def inspect_divergent_sample(session_id: int, node_id: str) -> dict[str, object]:
    """Inspect a divergent Cortensor miner sample."""
    return {"session_id": session_id, "node_id": node_id}


def reproduce_bug2() -> dict[str, object]:
    # Mirrors openminion/api/handoff.py:278 inside subagent(parent, tools=[inspect_divergent_sample])
    ctx = SubagentRunContext(
        context_id="subagent-demo123456",
        parent_agent_id="corsentinel_coordinator",
        child_agent_id="poi-forensics-verifier",
        parent_run_id="agent:corsentinel_coordinator",
        child_run_id="subagent-demo123456:poi-forensics-verifier",
        trace_parent_id="agent:corsentinel_coordinator",
        tool_allowlist=tuple([inspect_divergent_sample]),  # type: ignore[list-item]
    )
    try:
        ctx.as_inbound_metadata()
        return {"bug_present": False, "error": None}
    except TypeError as exc:
        return {"bug_present": True, "error_type": type(exc).__name__, "error": str(exc)}


if __name__ == "__main__":
    out = reproduce_bug2()
    print("OM-0.1.13-BUG-2 Reproduction:", out)
    assert out["bug_present"] is True
