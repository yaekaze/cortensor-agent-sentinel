# Release Notes — CorSentinel `v0.1.0` (2026-10-27)

## Highlights
- **Full OpenMinion `0.1.13` Python SDK Integration:** Built on top of `APIRuntime`, `Agent.run_stream()`, `@tool(min_scope="READ_ONLY", idempotent=True)`, `@tool(dangerous=True)`, `forced_tools`, `subagent()`, `Handoff`, `MemoryBundle`, and `output_type=CortensorSentinelReport`.
- **Deterministic Cortensor PoI & PoUW Verification:** Computes word + character-3gram cosine similarity against the weighted session centroid, evaluates PoUW rubric compliance, checks off-chain URN resolution and latency SLAs (`<= 2500ms`), and emits tamper-evident SHA-256 evidence bundles.
- **Cross-Session Continuity & Human Airlock:** Persists miner EMA reputation scores across runs, computes `"Since Last Run"` deltas per session ID, and enforces explicit operator confirmation via `approval_callback` before executing any miner quarantine.
- **Three Upstream `openminion==0.1.13` Bug Reports & Patches:** Includes standalone reproduction scripts in `repro/` and unified patch diffs in `upstream/`.
