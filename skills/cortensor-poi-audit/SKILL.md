---
name: cortensor-poi-audit
description: Deterministic Proof of Inference (PoI) and Proof of Useful Work (PoUW) verification skill for Cortensor Router sessions.
version: 0.1.0
---

# Cortensor PoI / PoUW Session Audit Skill

Use this skill when auditing redundant Cortensor Router (`/api/v2/completions`) or Cortensor Portal (`/v1/chat/completions`) inference sessions:

1. **Deterministic First Step (`forced_tools=["audit_cortensor_session"]`)**:
   - Always compute PoI vector cosine similarity, PoUW rubric scores, latency SLA compliance (`<= 2500ms`), and SHA-256 evidence digests in Python before reasoning.
2. **Bounded Subagent Forensics (`openminion.subagent`)**:
   - When `divergent_nodes` is non-empty, delegate deep root-cause inspection to `poi-forensics-verifier` with `tools=[]` and a bounded 120s timeout.
3. **Peer Remediation Handoff (`openminion.Handoff`)**:
   - Consult `transfer_to_remediation_advisor` (`remediation_advisor`) to validate failover strategy across `dedicated_session_ids` and `ephemeral_session_ids`.
4. **Human-in-the-Loop Airlock (`@tool(dangerous=True)`)**:
   - Never mutate the Cortensor Router node pool autonomously. Call `queue_miner_remediation` so the operator approves or rejects the quarantine via `approval_callback`.
