"""Typed Pydantic models for Cortensor PoI/PoUW verification and OpenMinion structured output."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class MinerNodeSample(BaseModel):
    """Telemetry and output sample from a single Cortensor miner node in a redundant session."""

    node_id: str = Field(description="Miner node identifier in the Cortensor Router pool")
    model: str = Field(description="Model identifier served by the miner node")
    latency_ms: int = Field(description="End-to-end completion latency in milliseconds")
    precommit_ms: int = Field(description="Precommit phase latency in milliseconds")
    output_text: str = Field(description="Raw completion output returned by the miner")
    urn_blob: str | None = Field(default=None, description="Off-chain URN reference if present")
    token_count: int = Field(default=0, description="Completion token count")


class MinerAuditMetrics(BaseModel):
    """Deterministic PoI (Proof of Inference) and PoUW (Proof of Useful Work) scores per miner."""

    node_id: str
    poi_cosine_similarity: float = Field(description="Cosine similarity against session consensus centroid (0.0-1.0)")
    poi_drift_distance: float = Field(description="1.0 - poi_cosine_similarity")
    pouw_rubric_score: float = Field(description="Deterministic PoUW structural/schema/logic score (0.0-1.0)")
    sla_compliant: bool = Field(description="True if latency is within Cortensor Router precommit/timeout SLA")
    urn_resolved: bool = Field(description="True if no dangling off-chain urn:blob pending state")
    trust_score_before: float = Field(description="Historical EMA node trust score before this session (0-100)")
    trust_score_after: float = Field(description="Updated EMA node trust score after this session (0-100)")
    status: Literal["VERIFIED", "DRIFT_WARNING", "BYZANTINE_FAULT"]


class RemediationProposal(BaseModel):
    """Human-gated remediation proposal queued behind OpenMinion approval_callback."""

    proposal_id: str
    session_id: int
    target_node_id: str
    action: Literal["quarantine_miner", "rotate_to_ephemeral_pool", "flag_for_review"]
    reason: str
    sha256_evidence_hash: str
    approval_state: Literal["approved_by_operator", "rejected_by_operator", "pending_human"]
    executed: bool = Field(
        default=False,
        description="Whether the router pool mutation was applied after explicit human approval",
    )


class CortensorSentinelReport(BaseModel):
    """Structured final output validated by OpenMinion Agent(output_type=CortensorSentinelReport)."""

    session_id: int = Field(description="Audited Cortensor Router session ID")
    router_endpoint: str = Field(description="Cortensor Router or Portal endpoint audited")
    model_id: str = Field(description="Target model ID (e.g., gpt-oss-20b or oss-20b)")
    verdict: Literal["HEALTHY_QUORUM", "DEGRADED_REMEDIATED", "CRITICAL_QUARANTINE_PENDING"]
    poi_quorum_score: float = Field(description="Aggregate Proof of Inference consensus score (0.0-1.0)")
    pouw_mean_score: float = Field(description="Mean Proof of Useful Work score across quorum nodes (0.0-1.0)")
    divergent_nodes: list[str] = Field(default_factory=list, description="Miner node IDs flagged for PoI/PoUW drift")
    subagent_forensics_summary: str = Field(description="Root-cause forensics returned by the delegated OpenMinion subagent")
    remediation_status: str = Field(description="Human-in-the-loop approval status for router pool remediation")
    since_last_run_delta: str = Field(description="Cross-session continuity comparison against prior runs on this session_id")
    evidence_bundle_sha256: str = Field(description="SHA-256 digest of the deterministic PoI/PoUW evidence bundle")
    executive_summary: str = Field(description="Concise operator summary of session health and next actions")
