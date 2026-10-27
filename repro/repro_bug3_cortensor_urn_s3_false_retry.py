#!/usr/bin/env python3
"""Minimal reproduction for OM-0.1.13-BUG-3:
CortensorProvider._looks_like_offchain_result_pending (adapter.py:778) serializes the entire
response JSON to lowercase and checks if 'urn:blob' and 's3' appear anywhere in the payload,
even when _response_has_text_or_tool_calls(payload) is True.
"""

from __future__ import annotations

from openminion.modules.llm.providers.cortensor.adapter import CortensorProvider


def reproduce_bug3() -> dict[str, object]:
    provider = CortensorProvider()
    valid_response_payload = {
        "id": "chatcmpl-valid-1",
        "object": "chat.completion",
        "model": "gpt-oss-20b",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Forensics complete: miner node off-chain S3 URN urn:blob:123 was verified.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 18, "total_tokens": 68},
    }
    has_text = provider._response_has_text_or_tool_calls(valid_response_payload)
    false_positive_pending = provider._looks_like_offchain_result_pending(
        valid_response_payload
    )
    retry_reason = provider._extract_retryable_reason(valid_response_payload)
    return {
        "response_has_valid_text": has_text,
        "looks_like_offchain_result_pending": false_positive_pending,
        "extracted_retry_reason": retry_reason,
        "bug_present": bool(has_text and false_positive_pending),
    }


if __name__ == "__main__":
    out = reproduce_bug3()
    print("OM-0.1.13-BUG-3 Reproduction:", out)
    assert out["bug_present"] is True
