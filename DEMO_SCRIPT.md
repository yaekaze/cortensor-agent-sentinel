# 3-Minute Demo Video Walkthrough Script — CorSentinel

- **0:00 – 0:25 | The Cortensor Operator Problem:** Show how redundant Cortensor Router sessions (`/api/v2/completions` & Portal `/v1/chat/completions`) can experience quantized miner drift, unsafe code injection (`tx.origin`), or stalled off-chain S3 URNs.
- **0:25 – 1:10 | Live CLI Run (`python run_demo.py`):** Run the 3-stage suite on `openminion==0.1.13`:
  - **Run 1 (Session #42):** Forced tool `audit_cortensor_session` flags `miner-gamma-03` (`poi_cosine_similarity=0.4941`, `pouw=0.3000`). Parent agent spawns `subagent(parent, name="poi-forensics-verifier")`, consults peer `Handoff(target=remediation_advisor)`, and triggers `approval_callback` on `@tool(dangerous=True) def queue_miner_remediation(...)`. Operator approves (`executed=True`, `DEGRADED_REMEDIATED`).
  - **Run 2 (Session #42 Repeat):** Demonstrates durable session continuity (`Run #2 on session 42 vs Run #1: PoI quorum delta +0.0000`) and operator rejection in `approval_callback` (`executed=False`, `CRITICAL_QUARANTINE_PENDING`).
  - **Run 3 (Session #108):** Audits a healthy 3-node Cortensor Portal (`oss-20b`) quorum in `276ms` with zero false positives (`HEALTHY_QUORUM`).
- **1:10 – 2:00 | Interactive Operator Dashboard (`dashboard/index.html`):** Walk through the PoI cosine matrix, subagent forensics panel, `MemoryBundle` v1 JSON export, and `APIRuntime` diagnostics.
- **2:00 – 2:50 | Building Blocks Tested & 3 Upstream SDK Bugs (`repro/` & `upstream/`):** Run `pytest -v` (`7 passed`) and execute the 3 minimal bug reproduction scripts against stock `openminion==0.1.13`.
