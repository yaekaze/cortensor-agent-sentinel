"""Deterministic Proof of Inference (PoI) and Proof of Useful Work (PoUW) verification engine.

All numerical metrics (cosine similarity, embedding distance, SLA compliance, EMA reputation,
and SHA-256 evidence hashes) are computed deterministically in Python rather than relying on
LLM arithmetic.
"""

from __future__ import annotations

import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from cortensor_sentinel.models import (
    MinerAuditMetrics,
    MinerNodeSample,
    RemediationProposal,
)

DEFAULT_SLA_TIMEOUT_MS = 2500
DEFAULT_POI_DRIFT_THRESHOLD = 0.25
DEFAULT_POUW_MIN_SCORE = 0.70


def _tokenize_shingles(text: str) -> Counter[str]:
    """Build deterministic word + character-3gram frequency vector for PoI cosine distance."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not cleaned:
        return Counter()
    words = re.findall(r"[a-z0-9_]+", cleaned)
    trigrams = [cleaned[i : i + 3] for i in range(max(0, len(cleaned) - 2))]
    counts: Counter[str] = Counter()
    for w in words:
        counts[f"w:{w}"] += 2
    for tg in trigrams:
        counts[f"c:{tg}"] += 1
    return counts


def cosine_similarity(vec_a: Counter[str], vec_b: Mapping[str, float] | Counter[str]) -> float:
    """Compute exact cosine similarity in [0.0, 1.0] between two sparse vectors."""
    if not vec_a or not vec_b:
        return 0.0
    common = set(vec_a.keys()) & set(vec_b.keys())
    dot = sum(float(vec_a[k]) * float(vec_b[k]) for k in common)
    norm_a = math.sqrt(sum(float(v) ** 2 for v in vec_a.values()))
    norm_b = math.sqrt(sum(float(v) ** 2 for v in vec_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return round(min(1.0, max(0.0, dot / (norm_a * norm_b))), 4)


def compute_pouw_rubric_score(sample: MinerNodeSample, expected_keywords: list[str]) -> float:
    """Evaluate deterministic Proof of Useful Work (PoUW) rubric on a miner output."""
    text = (sample.output_text or "").strip()
    if not text:
        return 0.0

    score = 0.0
    # 1. Completeness & non-truncation (0.30)
    if len(text) >= 40 and sample.token_count >= 10:
        score += 0.30
    elif len(text) >= 15:
        score += 0.15

    # 2. Expected domain keyword coverage (0.35)
    if expected_keywords:
        lower_text = text.lower()
        hits = sum(1 for kw in expected_keywords if kw.lower() in lower_text)
        score += 0.35 * (hits / len(expected_keywords))
    else:
        score += 0.35

    # 3. Structural / code / JSON safety check (0.20)
    has_unsafe_pattern = any(
        bad in text
        for bad in ("tx.origin ==", "selfdestruct(", "eval(", "os.system(", "blob-ref-pending")
    )
    if not has_unsafe_pattern:
        score += 0.20

    # 4. Off-chain URN resolution & latency SLA (0.15)
    urn_ok = not (sample.urn_blob and "pending" in sample.urn_blob.lower())
    if urn_ok and sample.latency_ms <= DEFAULT_SLA_TIMEOUT_MS:
        score += 0.15
    elif urn_ok:
        score += 0.07

    return round(min(1.0, max(0.0, score)), 4)


# Built-in realistic Cortensor session scenarios (used when probing simulated or offline router sessions)
BUILTIN_SESSION_FIXTURES: dict[int, dict[str, Any]] = {
    42: {
        "session_id": 42,
        "router_endpoint": "http://127.0.0.1:8080/api/v2/completions",
        "model_id": "gpt-oss-20b",
        "session_pool": "dedicated",
        "prompt": "Verify Cortensor SessionQueueV2 task commitment hash and calculate 85/10/5 validator fee split for 250 COR.",
        "expected_keywords": ["212.5", "25.0", "12.5", "keccak256", "sessionqueuev2"],
        "samples": [
            {
                "node_id": "miner-alpha-01",
                "model": "gpt-oss-20b",
                "latency_ms": 385,
                "precommit_ms": 110,
                "token_count": 64,
                "urn_blob": None,
                "output_text": (
                    "SessionQueueV2 commitment verified via keccak256(task_id, miner_addr, output_root). "
                    "For 250 COR reward pool: Miner receives 212.5 COR (85%), Oracle Validator receives "
                    "25.0 COR (10%), and Protocol Treasury receives 12.5 COR (5%)."
                ),
            },
            {
                "node_id": "miner-beta-02",
                "model": "gpt-oss-20b",
                "latency_ms": 412,
                "precommit_ms": 124,
                "token_count": 61,
                "urn_blob": None,
                "output_text": (
                    "Verified SessionQueueV2 task commitment using keccak256 digest over task parameters. "
                    "The 250 COR split allocates 212.5 COR (85%) to Miner, 25.0 COR (10%) to Validator, "
                    "and 12.5 COR (5%) to Protocol Treasury."
                ),
            },
            {
                "node_id": "miner-gamma-03",
                "model": "gpt-oss-20b-q2-drift",
                "latency_ms": 3190,
                "precommit_ms": 1420,
                "token_count": 19,
                "urn_blob": "blob-ref-pending-timeout",
                "output_text": (
                    "Task split is 240 COR to miner and 10 COR fee. Authorization check uses tx.origin == owner "
                    "with unresolved blob-ref-pending state."
                ),
            },
        ],
    },
    108: {
        "session_id": 108,
        "router_endpoint": "https://api.cortensor.app/v1/chat/completions",
        "model_id": "oss-20b",
        "session_pool": "ephemeral",
        "prompt": "Generate OpenMinion @tool declaration with min_scope READ_ONLY for Cortensor router healthcheck.",
        "expected_keywords": ["@tool", "min_scope", "READ_ONLY", "healthcheck"],
        "samples": [
            {
                "node_id": "miner-alpha-01",
                "model": "oss-20b",
                "latency_ms": 290,
                "precommit_ms": 88,
                "token_count": 48,
                "urn_blob": None,
                "output_text": (
                    "Use @tool(min_scope='READ_ONLY', idempotent=True) on def router_healthcheck(endpoint: str) -> dict "
                    "so OpenMinion ActionPolicyService executes the probe without human confirmation prompts."
                ),
            },
            {
                "node_id": "miner-beta-02",
                "model": "oss-20b",
                "latency_ms": 315,
                "precommit_ms": 95,
                "token_count": 50,
                "urn_blob": None,
                "output_text": (
                    "Decorate def router_healthcheck(endpoint: str) -> dict with @tool(min_scope='READ_ONLY', idempotent=True) "
                    "to allow read-only Cortensor router healthcheck execution without interactive prompts."
                ),
            },
            {
                "node_id": "miner-delta-04",
                "model": "oss-20b",
                "latency_ms": 304,
                "precommit_ms": 91,
                "token_count": 46,
                "urn_blob": None,
                "output_text": (
                    "Apply @tool(min_scope='READ_ONLY', idempotent=True) to router_healthcheck so OpenMinion "
                    "permits read-only router diagnostics under default action_policy rules."
                ),
            },
        ],
    },
}


class CortensorTrustLedger:
    """Persistent local reputation & session evidence ledger for Cortensor miner nodes."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.state_dir / "node_trust_ledger.json"
        self.proposals_path = self.state_dir / "remediation_proposals.json"
        self.runs_path = self.state_dir / "session_audit_history.json"

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def get_node_trust(self, node_id: str) -> float:
        ledger = self._read_json(self.ledger_path, {})
        entry = ledger.get(node_id, {})
        return float(entry.get("trust_score", 90.0))

    def update_node_trust(
        self,
        *,
        node_id: str,
        poi_similarity: float,
        pouw_score: float,
        sla_compliant: bool,
        status: str,
    ) -> tuple[float, float]:
        ledger = self._read_json(self.ledger_path, {})
        entry = ledger.get(
            node_id,
            {
                "node_id": node_id,
                "trust_score": 90.0,
                "audits": 0,
                "faults": 0,
                "quarantined": False,
            },
        )
        before = float(entry.get("trust_score", 90.0))
        instant_quality = (poi_similarity * 55.0) + (pouw_score * 35.0) + (10.0 if sla_compliant else 0.0)
        if status == "BYZANTINE_FAULT":
            after = max(5.0, round(before * 0.55 + instant_quality * 0.15, 2))
            entry["faults"] = int(entry.get("faults", 0)) + 1
        elif status == "DRIFT_WARNING":
            after = max(20.0, round(before * 0.80 + instant_quality * 0.20, 2))
        else:
            after = min(100.0, round(before * 0.75 + instant_quality * 0.25, 2))
        entry["trust_score"] = after
        entry["audits"] = int(entry.get("audits", 0)) + 1
        entry["last_status"] = status
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        ledger[node_id] = entry
        self._write_json(self.ledger_path, ledger)
        return before, after

    def record_session_audit(self, session_id: int, summary_payload: dict[str, Any]) -> str:
        """Store audit snapshot and return a human-readable 'Since Last Run' delta."""
        history = self._read_json(self.runs_path, {})
        key = str(session_id)
        prior_runs = list(history.get(key, []))
        if not prior_runs:
            delta = (
                f"Initial baseline audit recorded for session {session_id} "
                f"(quorum={summary_payload['poi_quorum_score']:.4f}, "
                f"divergent={summary_payload['divergent_nodes'] or 'none'})."
            )
        else:
            prev = prior_runs[-1]
            prev_q = float(prev.get("poi_quorum_score", 0.0))
            curr_q = float(summary_payload.get("poi_quorum_score", 0.0))
            diff_q = curr_q - prev_q
            prev_div = set(prev.get("divergent_nodes", []))
            curr_div = set(summary_payload.get("divergent_nodes", []))
            newly_flagged = sorted(curr_div - prev_div)
            resolved = sorted(prev_div - curr_div)
            delta = (
                f"Run #{len(prior_runs) + 1} on session {session_id} vs Run #{len(prior_runs)}: "
                f"PoI quorum delta {diff_q:+.4f} ({prev_q:.4f} -> {curr_q:.4f}); "
                f"newly flagged={newly_flagged or 'none'}, resolved={resolved or 'none'}."
            )
        prior_runs.append(
            {
                **summary_payload,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        history[key] = prior_runs
        self._write_json(self.runs_path, history)
        return delta

    def save_proposal(self, proposal: RemediationProposal) -> None:
        proposals = self._read_json(self.proposals_path, [])
        proposals.append(proposal.model_dump())
        self._write_json(self.proposals_path, proposals)
        if proposal.executed and proposal.action == "quarantine_miner":
            ledger = self._read_json(self.ledger_path, {})
            if proposal.target_node_id in ledger:
                ledger[proposal.target_node_id]["quarantined"] = True
                self._write_json(self.ledger_path, ledger)

    def get_all_state(self) -> dict[str, Any]:
        return {
            "ledger": self._read_json(self.ledger_path, {}),
            "proposals": self._read_json(self.proposals_path, []),
            "session_history": self._read_json(self.runs_path, {}),
        }


def evaluate_session_poi_pouw(
    session_id: int,
    *,
    ledger: CortensorTrustLedger,
    custom_fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run deterministic PoI + PoUW evaluation across all miner samples for a session."""
    fixture = custom_fixture or BUILTIN_SESSION_FIXTURES.get(
        session_id, BUILTIN_SESSION_FIXTURES[42]
    )
    samples = [MinerNodeSample.model_validate(item) for item in fixture["samples"]]
    expected_keywords = list(fixture.get("expected_keywords", []))

    vectors = {s.node_id: _tokenize_shingles(s.output_text) for s in samples}
    # Build consensus centroid weighted by inverse latency & non-pending URN
    centroid: Counter[str] = Counter()
    for s in samples:
        weight = 2 if (not s.urn_blob and s.latency_ms <= DEFAULT_SLA_TIMEOUT_MS) else 1
        for token, count in vectors[s.node_id].items():
            centroid[token] += count * weight

    metrics_list: list[MinerAuditMetrics] = []
    divergent_nodes: list[str] = []

    for s in samples:
        sim = cosine_similarity(vectors[s.node_id], centroid)
        drift = round(1.0 - sim, 4)
        pouw = compute_pouw_rubric_score(s, expected_keywords)
        sla_ok = s.latency_ms <= DEFAULT_SLA_TIMEOUT_MS
        urn_ok = not (s.urn_blob and "pending" in s.urn_blob.lower())

        if drift > DEFAULT_POI_DRIFT_THRESHOLD or pouw < DEFAULT_POUW_MIN_SCORE or not urn_ok:
            status = "BYZANTINE_FAULT" if (drift > 0.25 or not urn_ok or pouw < 0.5) else "DRIFT_WARNING"
            divergent_nodes.append(s.node_id)
        else:
            status = "VERIFIED"

        before, after = ledger.update_node_trust(
            node_id=s.node_id,
            poi_similarity=sim,
            pouw_score=pouw,
            sla_compliant=sla_ok,
            status=status,
        )
        metrics_list.append(
            MinerAuditMetrics(
                node_id=s.node_id,
                poi_cosine_similarity=sim,
                poi_drift_distance=drift,
                pouw_rubric_score=pouw,
                sla_compliant=sla_ok,
                urn_resolved=urn_ok,
                trust_score_before=before,
                trust_score_after=after,
                status=status,
            )
        )

    verified_sims = [m.poi_cosine_similarity for m in metrics_list if m.status == "VERIFIED"]
    poi_quorum_score = round(
        sum(verified_sims) / len(verified_sims) if verified_sims else 0.0, 4
    )
    pouw_mean_score = round(
        sum(m.pouw_rubric_score for m in metrics_list) / len(metrics_list), 4
    )

    canonical_evidence = {
        "session_id": session_id,
        "router_endpoint": fixture["router_endpoint"],
        "model_id": fixture["model_id"],
        "poi_quorum_score": poi_quorum_score,
        "pouw_mean_score": pouw_mean_score,
        "divergent_nodes": divergent_nodes,
        "node_metrics": [m.model_dump() for m in metrics_list],
    }
    evidence_sha256 = hashlib.sha256(
        json.dumps(canonical_evidence, sort_keys=True).encode("utf-8")
    ).hexdigest()
    canonical_evidence["evidence_bundle_sha256"] = evidence_sha256
    canonical_evidence["since_last_run_delta"] = ledger.record_session_audit(
        session_id,
        {
            "poi_quorum_score": poi_quorum_score,
            "pouw_mean_score": pouw_mean_score,
            "divergent_nodes": divergent_nodes,
            "evidence_bundle_sha256": evidence_sha256,
        },
    )
    return canonical_evidence
