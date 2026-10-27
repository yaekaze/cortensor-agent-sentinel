# Project Status — CorSentinel (`cortensor-agent-sentinel`)

- **Hackathon:** Cortensor Hackathon #5 (Mainnet Full Alpha Builder Round)
- **SDK Version Tested:** `openminion==0.1.13` (Python 3.11+ / verified on Python 3.13.5)
- **Current Release:** `v0.1.0` (`2026-10-27`)
- **Automated Test Suite:** `7/7 passed` (`pytest -v`)
- **OpenMinion Building Blocks Exercised:** `10 / 10` (`execution`, `models`, `tools`, `permissions`, `sessions`, `memory`, `skills`, `tasks`, `delegation`, `diagnostics`)
- **Upstream OpenMinion 0.1.13 Bugs Reproduced & Patched:** `3` (`OM-0.1.13-BUG-1`, `OM-0.1.13-BUG-2`, `OM-0.1.13-BUG-3`)

## Component Readiness

| Component | File / Surface | Status |
|---|---|---|
| OpenMinion Coordinator Agent | `cortensor_sentinel/agent.py` | Complete (`Agent.run_stream`, `forced_tools`, `output_type`) |
| Deterministic PoI/PoUW Engine | `cortensor_sentinel/poi_engine.py` | Complete (Cosine similarity, PoUW rubric, EMA trust ledger) |
| Subagent & Peer Handoff | `cortensor_sentinel/agent.py` | Complete (`subagent()` + `Handoff`) |
| Human Permission Airlock | `cortensor_sentinel/agent.py` | Complete (`@tool(dangerous=True)` + `approval_callback`) |
| Local Cortensor Router Gateway | `cortensor_sentinel/mock_router.py` | Complete (`/v1/chat/completions` & `/api/v2/completions`) |
| Interactive Operator Dashboard | `dashboard/index.html` | Complete |
| Recorded Real Runs & Bundles | `runs/` | Complete (`run_1_session_42.json`, `run_2_session_42.json`, `run_3_session_108.json`) |
| Bug Repros & Upstream Patches | `repro/` & `upstream/` | Complete (3 reproducible scripts + 3 unified git diffs) |
