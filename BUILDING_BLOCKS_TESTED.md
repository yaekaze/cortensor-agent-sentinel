# Building Blocks Tested — OpenMinion 0.1.13 Python SDK

**Project:** CorSentinel (`cortensor-agent-sentinel`)  
**SDK Version Tested:** `openminion==0.1.13` (verified on Python `3.13.5`)  
**Target Cortensor Surfaces:** Cortensor Router (`cortensor-router`, `/api/v2/completions`) & Cortensor Portal (`cortensor-portal`, `/v1/chat/completions`)

---

## Executive Matrix of All 10 OpenMinion 0.1 Building Blocks

| # | Building Block | OpenMinion 0.1.13 Surface Exercised | How CorSentinel Uses It | What Worked | What Broke / Rough Edges Found |
|---|---|---|---|---|---|
| **1** | **Agent Execution** | `Agent.run_stream()`, `APIRuntime`, `forced_tools=["audit_cortensor_session"]` | Drives the 4-step session audit -> forensics -> peer handoff -> remediation workflow with live `on_delta` event streaming. | `forced_tools` reliably forces `audit_cortensor_session` on turn entry before the model reasons. `run_stream` emits `tool_started`, `tool_completed`, and `budget_event` callbacks. | When `approval_callback` returns `False` on a `dangerous=True` tool and `output_type=BaseModel` is configured, `Agent._run_once` passes the literal string `"openminion: Confirmation denied..."` into `_coerce_output()`, raising `AgentOutputValidationError`. |
| **2** | **Models & Providers** | `openminion setup --provider cortensor-router` & `cortensor-portal`, `CortensorProvider` | Connects to Cortensor Router (`gpt-oss-20b`) and Cortensor Portal (`oss-20b`), plus local/hosted OpenAI-compatible gateways via `CORTENSOR_API_URL`. | `CORTENSOR_API_URL` and `CORTENSOR_API_MODE` environment overrides cleanly configure `CortensorProvider` without hardcoding secrets in `agents.json`. | **OM-0.1.13-BUG-1:** `CortensorProvider._parse_response_payload` hardcodes `fallback_enabled=False` (line 480) and deletes `tool_call_strategy` (line 301). **OM-0.1.13-BUG-3:** `_looks_like_offchain_result_pending` triggers a 6× retry loop if valid assistant text mentions `"urn:blob"` and `"s3"`. |
| **3** | **Tools** | `@openminion.tool(min_scope="READ_ONLY", idempotent=True)` & `@openminion.tool(dangerous=True)` | Registers `audit_cortensor_session`, `inspect_divergent_sample`, `delegate_poi_forensics`, and `queue_miner_remediation`. | Temporary run-scoped tool registration (`_register_tools_for_run`) automatically creates `ToolExposureProfile` entries so user tools are visible to the model without manual manifest hacks. | Plain `@tool` without `min_scope="READ_ONLY"` defaults to `min_scope_default="WRITE_SAFE"` (`decorator.py:167`), causing `ActionPolicyService` to prompt for human confirmation on read-only tools unless `min_scope="READ_ONLY"` is explicitly set. |
| **4** | **Permissions** | `ActionPolicyService`, `dangerous=True`, `approval_callback` | Gates `queue_miner_remediation` behind an explicit operator approval callback (`approved_by_operator` vs `rejected_by_operator`). | `action_policy.temporary_tool_risks` binds run-scoped risk metadata to temporary tools, and `approval_callback(tool_name, args, approval_id)` intercepts `dangerous=True` calls before execution. | Generated `Handoff` tools (`build_delegate_family_spec` in `handoff.py:208`) hardcode `min_scope_default="WRITE_SAFE"`, so peer handoffs also trigger `approval_callback` under default `require_confirm` policy. |
| **5** | **Sessions** | `Agent(session_id="corsentinel-session-42")`, SQLite session store | Maintains durable per-session state across repeat audits of the same Cortensor session ID and computes `"Since Last Run"` deltas. | SQLite migrations (`v1`–`v10`) initialize automatically under `.openminion/` in ~90ms; session transcripts persist cleanly across processes. | In `Agent.run_stream()`, `session_id` is scoped to the OpenMinion conversation thread, while `CortensorProvider` requires a positive integer `session_id` (`CORTENSOR_SESSION_ID`) for `/api/v2/completions`. |
| **6** | **Memory** | `openminion.MemoryBundle` (`to_json()`, `from_json()`), SophiaGraph capture, `CortensorTrustLedger` | Exports portable `memory_bundle.v1` JSON snapshots of each session audit and maintains EMA miner reputation scores locally. | `MemoryBundle(items=[...], metadata={...}).to_json()` and `MemoryBundle.from_json()` provide clean, deterministic cross-node memory portability. | Each turn invokes internal `submit_output` LLM calls (`UserMessageCandidateReport`) for background memory extraction, adding 2–4 extra provider requests per user turn. |
| **7** | **Skills** | `skills/cortensor-poi-audit/SKILL.md` | Packages Cortensor PoI cosine similarity thresholds (`<= 0.25` drift) and PoUW rubric rules as a Markdown-first OpenMinion skill. | Markdown-first skill format with YAML frontmatter is clean, human-readable, and version-controllable alongside agent code. | Loading project-local skills into `Agent()` via Python SDK requires setting `skill` / `skill_catalog` in `agents.json` rather than passing `skills=[...]` directly to `Agent.__init__`. |
| **8** | **Tasks & Structured Output** | `output_type=CortensorSentinelReport`, `AgentOutputValidationError`, `TurnTimeoutError` | Validates the final coordinator output against a 12-field Pydantic `CortensorSentinelReport` model. | `_extract_json_object` in `agent.py:424` gracefully recovers valid JSON even if a model wraps the JSON object in markdown fences or prose. | `output_type` validates the model's final text after the turn but does not automatically inject `output_type.model_json_schema()` into the system prompt unless the caller describes the fields in `instructions`. |
| **9** | **Delegation** | `subagent(parent, name="poi-forensics-verifier", tools=[])` & `Handoff(target=remediation_advisor)` | Exercises both hierarchical child delegation (`subagent`) for root-cause forensics and peer transfer (`Handoff`) for remediation planning. | `subagent()` shares the parent's `APIRuntime` without closing it on exit and attaches explicit `SubagentRunContext` lineage (`context_id`, `parent_run_id`, `child_run_id`). | **OM-0.1.13-BUG-2:** Passing `@tool` callables to `subagent(parent, tools=[fn])` crashes `SubagentRunContext.as_inbound_metadata()` with `TypeError`. Also, `tools=None` on `subagent()` exposes all 104 built-in tools, whereas `tools=[]` isolates the child. |
| **10** | **Diagnostics** | `APIRuntime.runtime_posture()`, `capability_report()`, `runtime_self_model()`, `AgentRunResult.stats` | Captures canonical turn path, active provider resolution, token counts, tool call counts, and wall-clock latency (`duration_ms`). | `runtime_posture()`, `capability_report()`, and `runtime_self_model()` provide rich, structured introspection without private attribute access. | `AgentRunResult.stats["llm_calls"]` reports `1` even when a multi-tool turn made 4 model inference calls + 6 `submit_output` control calls (`input_tokens: 980` is summed across calls, but `llm_calls` is not incremented per tool loop step). |

---

## Detailed Verification Evidence

All 10 building blocks are exercised automatically by running:

```bash
python run_demo.py
pytest -v
```

Recorded outputs from real OpenMinion `0.1.13` runs are committed in:
- `runs/run_1_session_42.json` (Byzantine drift on `miner-gamma-03` -> `subagent` forensics -> `Handoff` advisor -> `approval_callback` approved -> `DEGRADED_REMEDIATED`)
- `runs/run_2_session_42.json` (Repeat session #42 run -> `"Since Last Run"` continuity delta -> `approval_callback` rejected -> `CRITICAL_QUARANTINE_PENDING`)
- `runs/run_3_session_108.json` (Healthy 3-node Cortensor Portal quorum -> `HEALTHY_QUORUM` in `276ms`)
- `runs/memory_bundle_run_1_session_42.json` (`memory_bundle.v1` portable snapshot)
