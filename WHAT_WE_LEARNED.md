# What We Learned — Actionable Product & DX Feedback for OpenMinion 0.1 & Cortensor

Building **CorSentinel** on `openminion==0.1.13` against Cortensor Router (`/api/v2/completions`) and Cortensor Portal (`/v1/chat/completions`) surfaced high-signal lessons and concrete product improvements for the Cortensor and OpenMinion maintainers.

---

## 1. What Improved Dramatically in OpenMinion `0.1.9` → `0.1.13`
Comparing earlier `0.1.4`–`0.1.9` builds with `0.1.13` (released October 27, 2026):
- **Decorated `@tool` Exposure Works Out-of-the-Box:** In `0.1.4`, passing `@tool` functions to `Agent(tools=[...])` required manual `register_module_manifest` workarounds. In `0.1.13`, `decorator.py` automatically attaches a default-active `ToolExposureProfile` (`_user_tool_exposure_profile_id`), and `Agent._register_tools_for_run` registers both the tool spec and its exposure profile cleanly inside a `temporary_registration_scope()`.
- **Clean `APIRuntime` Introspection Surface:** `runtime.runtime_posture()`, `runtime.capability_report()`, and `runtime.runtime_self_model()` give operators deterministic JSON diagnostics without reaching into private runtime internals.

---

## 2. Actionable SDK & Runtime Improvements Needed

### A. Enable Fallback Tool-Call Parsing in `CortensorProvider` (`OM-0.1.13-BUG-1`)
- **Observation:** `CortensorProvider._build_completion_prompt` (`cortensor/adapter.py:626`) and `_build_openai_chat_payload` (`cortensor/adapter.py:522`) inject `build_fallback_tool_call_instruction(request.tools)` when `tool_call_strategy` is `"hybrid"` or `"fallback"`, instructing Cortensor miner nodes to return `{"tool_calls": [...]}` in text. However, `_parse_response_payload` (`cortensor/adapter.py:480`) hardcodes `fallback_enabled=False`, and `_complete_via_completion_mode` (`line 301`) deletes `tool_call_strategy`.
- **Recommendation:** Pass `fallback_enabled=bool(request.tools and supports_fallback_tool_calling(tool_call_strategy))` in `_parse_response_payload` and clear `text` when `tool_call_resolution.selected_source != "native"`. See `upstream/0001-fix-cortensor-fallback-tool-calls.patch`.

### B. Normalize `@tool` Callables in `subagent(parent, tools=[...])` (`OM-0.1.13-BUG-2`)
- **Observation:** `Agent(tools=[my_fn])` accepts `@openminion.tool` callables, and `subagent()` documents that its parameters mirror `Agent`. However, `subagent()` (`api/handoff.py:278`) copies `tools` directly into `SubagentRunContext.tool_allowlist` without extracting `fn.tool_decl.name`, causing `SubagentRunContext.as_inbound_metadata()` to crash with `TypeError: sequence item 0: expected str instance, function found`.
- **Also Observed:** If a parent `Agent` with temporary `@tool` functions calls `child.run()` inside one of the parent's `@tool` handlers (which executes on a `ThreadPoolExecutor` worker thread via `asyncio.to_thread`), and the child agent also has temporary `@tool` functions, `ToolRegistry.temporary_registration_scope()` raises `RuntimeError: Temporary tool registration in a cross-thread shared-runtime handoff would deadlock`.
- **Recommendation:** Resolve callable tools to their string names in `subagent()`, and automatically register any new `@tool` callables passed to `subagent()` on the parent runtime before entering the worker thread (or allow re-entrant registration when the parent turn is paused waiting on the synchronous tool call). See `upstream/0002-fix-subagent-decorated-tool-allowlist.patch`.

### C. Scope `CortensorProvider._looks_like_offchain_result_pending` to Error/Empty Responses (`OM-0.1.13-BUG-3`)
- **Observation:** During our first multi-agent test run, `CorSentinel` took 88 seconds instead of 5.6 seconds because our forensics text mentioned `"urn:blob"` and `"s3"`. `CortensorProvider._looks_like_offchain_result_pending` (`cortensor/adapter.py:778`) serializes the entire response payload to lowercase and checks if `"urn:blob"` and `"s3"` appear anywhere in the JSON—even when `_response_has_text_or_tool_calls(payload)` is `True`! That caused `CortensorProvider` to treat a valid assistant response as an unresolved S3 URN and retry the HTTP POST 6 times (`_OFFCHAIN_RESULT_MIN_WAIT_ATTEMPTS = 6`).
- **Recommendation:** Only inspect `pending_tokens` against `_extract_error_message(payload)` (or when `_response_has_text_or_tool_calls(payload)` is `False`), and remove the overly broad 2-letter `"s3"` token from `pending_tokens`. See `upstream/0003-fix-cortensor-offchain-urn-false-retry.patch`.

### D. Infer `min_scope="READ_ONLY"` When `@tool(idempotent=True, dangerous=False)` Is Used
- **Observation:** In `openminion/tools/decorator.py:167`, `_family_spec` defaults `min_scope_default="WRITE_SAFE"`. Under the default `agents.json` policy (`default_action: "require_confirm"`, `allow_read_only_without_prompt: true`), any `@tool` that omits `min_scope="READ_ONLY"` triggers `approval_callback` as if it were a mutating tool.
- **Recommendation:** Default `min_scope` to `"READ_ONLY"` when `idempotent=True` and `dangerous=False`, or highlight `min_scope="READ_ONLY"` in the SDK quickstart (`examples/sdk/tool_agent.py`).

### E. Preserve `output_type` Contract or Raise a Dedicated `ApprovalDeniedError` When `approval_callback` Returns `False`
- **Observation:** When `approval_callback` returns `False`, `APIRuntime.run_turn` short-circuits with `body = "openminion: Confirmation denied. The action was not run."`. When `Agent(output_type=MyPydanticModel)` is used, `Agent._run_once` attempts `MyPydanticModel.model_validate_json(reply_text)` on that plain-English denial notice and raises `AgentOutputValidationError`.
- **Recommendation:** Either feed the tool denial back into the model so it can produce a schema-valid `output_type` JSON reflecting the rejection, or raise a dedicated `ToolApprovalDeniedError` with `run_state="cancelled"`.
