# Bug Reports & Ready-to-Submit Upstream Patches (`openminion==0.1.13`)

**Target Package:** `openminion==0.1.13` (Python 3.13.5, Linux)  
**Upstream Repository:** `https://github.com/OpenMinion/openminion`

All 3 bugs below were discovered while building and running **CorSentinel** on stock `openminion==0.1.13`. Each bug has a standalone zero-key reproduction script in `repro/` (verified in `pytest`) and a clean unified git patch in `upstream/`.

---

## Summary Table

| Bug ID | Affected File & Lines | Severity | Summary | Repro Script | Patch Diff |
|---|---|---|---|---|---|
| **OM-0.1.13-BUG-1** | `openminion/modules/llm/providers/cortensor/adapter.py:301, 480, 501` | **High** | `CortensorProvider._parse_response_payload` hardcodes `fallback_enabled=False` and `_complete_via_completion_mode` drops `tool_call_strategy`, breaking fallback tool calls on Cortensor Router `/api/v2/completions`. | `repro/repro_bug1_cortensor_fallback_tools.py` | `upstream/0001-fix-cortensor-fallback-tool-calls.patch` |
| **OM-0.1.13-BUG-2** | `openminion/api/handoff.py:98, 228, 278` | **High** | `subagent(parent, tools=[decorated_fn])` puts raw function objects into `SubagentRunContext.tool_allowlist`, crashing `as_inbound_metadata()` with `TypeError`. | `repro/repro_bug2_subagent_decorated_tools.py` | `upstream/0002-fix-subagent-decorated-tool-allowlist.patch` |
| **OM-0.1.13-BUG-3** | `openminion/modules/llm/providers/cortensor/adapter.py:778–807` | **Medium** | `CortensorProvider._looks_like_offchain_result_pending` matches `"urn:blob"` + `"s3"` anywhere in serialized response JSON even when valid assistant text/tool calls exist, forcing a 6× false retry loop. | `repro/repro_bug3_cortensor_urn_s3_false_retry.py` | `upstream/0003-fix-cortensor-offchain-urn-false-retry.patch` |

---

## Bug #1 (`OM-0.1.13-BUG-1`): `CortensorProvider` Disables Fallback Tool-Call Parsing (`fallback_enabled=False`)

### Environment & Version
- `openminion==0.1.13`, Python `3.13.5`
- File: `openminion/modules/llm/providers/cortensor/adapter.py` (lines 301, 458–507, 626–631)

### Steps to Reproduce
```bash
python repro/repro_bug1_cortensor_fallback_tools.py
```

### Expected vs. Actual Behavior
- **Expected:** When `tool_call_strategy="hybrid"` or `"fallback"`, `CortensorProvider` injects `build_fallback_tool_call_instruction(request.tools)` into the prompt (`adapter.py:522` and `629`) and builds 5 fallback sources via `_cortensor_fallback_sources(...)` (`adapter.py:472`). When a Cortensor Router node returns `{"tool_calls": [{"name": "audit_cortensor_session", "arguments": {"session_id": 42}}]}` in `choices[0].text`, `_parse_response_payload` should parse 1 `ToolCall` and clear the raw JSON from `text`.
- **Actual:** Line 480 hardcodes `fallback_enabled=False` (and line 301 executes `del tool_call_strategy` in `_complete_via_completion_mode`). As a result, `parsed["tool_calls"]` is `[]` and the raw JSON string is leaked as plain assistant text.

### Proposed Fix (`upstream/0001-fix-cortensor-fallback-tool-calls.patch`)
Pass `fallback_enabled=bool(request.tools and supports_fallback_tool_calling(tool_call_strategy))` to `resolve_tool_call_source_precedence`, forward `tool_call_strategy` into `_build_completion_payload`, and clear `text` when `tool_calls` are resolved from a non-native source (matching `openai/adapter.py:805`).

---

## Bug #2 (`OM-0.1.13-BUG-2`): `subagent(parent, tools=[decorated_tool])` Crashes with `TypeError` in `SubagentRunContext.as_inbound_metadata()`

### Environment & Version
- `openminion==0.1.13`, Python `3.13.5`
- File: `openminion/api/handoff.py` (lines 98, 228, 278)

### Steps to Reproduce
```bash
python repro/repro_bug2_subagent_decorated_tools.py
```

### Expected vs. Actual Behavior
- **Expected:** `subagent()`'s docstring states `"Parameters mirror :class:\`Agent\` for ergonomic parity"`. Passing a function decorated with `@openminion.tool` in `tools=[inspect_divergent_sample]` should resolve its tool name (`"inspect_divergent_sample"`) for `SubagentRunContext.tool_allowlist`.
- **Actual:** `subagent()` passes `tool_allowlist=tuple(tools or ())` containing the raw Python function object into `SubagentRunContext`, and `SubagentRunContext.as_inbound_metadata()` (`handoff.py:98`) executes `",".join(self.tool_allowlist)`, raising `TypeError: sequence item 0: expected str instance, function found`.

### Proposed Fix (`upstream/0002-fix-subagent-decorated-tool-allowlist.patch`)
Extract `item.tool_decl.name` for callable items in `subagent()` before constructing `SubagentRunContext.tool_allowlist`.

---

## Bug #3 (`OM-0.1.13-BUG-3`): `CortensorProvider._looks_like_offchain_result_pending` Triggers 6× False Retries on Valid Responses Mentioning `"urn:blob"` and `"s3"`

### Environment & Version
- `openminion==0.1.13`, Python `3.13.5`
- File: `openminion/modules/llm/providers/cortensor/adapter.py` (lines 404–412, 778–807)

### Steps to Reproduce
```bash
python repro/repro_bug3_cortensor_urn_s3_false_retry.py
```

### Expected vs. Actual Behavior
- **Expected:** When a Cortensor model returns a valid completion or tool call (`_response_has_text_or_tool_calls(payload) == True`) with no error field, `_looks_like_offchain_result_pending(payload)` should return `False` even if the assistant's text discusses Cortensor's off-chain `urn:blob` and S3 storage.
- **Actual:** `_looks_like_offchain_result_pending` serializes the entire response dict to lowercase and returns `True` whenever `"urn:blob"` and `"s3"` appear anywhere in the response, causing `_post_with_retries` to sleep and re-send the completion request 6 times (`_OFFCHAIN_RESULT_MIN_WAIT_ATTEMPTS = 6`).

### Proposed Fix (`upstream/0003-fix-cortensor-offchain-urn-false-retry.patch`)
When `_response_has_text_or_tool_calls(payload)` is `True`, only match `pending_tokens` against `self._extract_error_message(payload)` and remove the ambiguous 2-letter `"s3"` substring match.
