#!/usr/bin/env python3
"""Minimal reproduction for OM-0.1.13-BUG-1:
CortensorProvider._parse_response_payload hardcodes fallback_enabled=False (line 480)
and _complete_via_completion_mode deletes tool_call_strategy (line 301).
"""

from __future__ import annotations

from openminion.modules.llm.providers.behavior import resolve_behavior_profile
from openminion.modules.llm.providers.cortensor.adapter import CortensorProvider
from openminion.modules.llm.schemas import LLMRequest, Message, ToolSpec


def reproduce_bug1() -> dict[str, object]:
    provider = CortensorProvider()
    req = LLMRequest(
        provider="cortensor",
        model="gpt-oss-20b",
        messages=[Message(role="user", content="Audit Cortensor session 42")],
        tools=[
            ToolSpec(
                name="audit_cortensor_session",
                description="Audit a Cortensor session",
                input_schema={
                    "type": "object",
                    "properties": {"session_id": {"type": "integer"}},
                    "required": ["session_id"],
                },
            )
        ],
    )
    profile = resolve_behavior_profile(
        provider="cortensor",
        model="gpt-oss-20b",
        base_url="http://127.0.0.1:8080/api/v2/completions",
        metadata={},
        env={},
    )
    # Cortensor Router /api/v2/completions response emitting fallback tool call JSON in choices[0].text
    router_payload = {
        "model": "gpt-oss-20b",
        "choices": [
            {
                "text": '{"tool_calls": [{"name": "audit_cortensor_session", "arguments": {"session_id": 42}}]}',
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 64, "completion_tokens": 22, "total_tokens": 86},
    }
    parsed = provider._parse_response_payload(
        response_payload=router_payload,
        request=req,
        tool_call_strategy="hybrid",
        fallback_model="gpt-oss-20b",
        behavior_profile=profile,
    )
    return {
        "expected_tool_calls_len": 1,
        "actual_tool_calls_len": len(parsed["tool_calls"]),
        "leaked_raw_text": parsed["text"],
        "bug_present": len(parsed["tool_calls"]) == 0,
    }


if __name__ == "__main__":
    out = reproduce_bug1()
    print("OM-0.1.13-BUG-1 Reproduction:", out)
    assert out["bug_present"] is True
