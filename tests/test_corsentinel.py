"""Automated test suite for CorSentinel (Cortensor Hackathon #5, OpenMinion 0.1.13 SDK)."""

from __future__ import annotations

from pathlib import Path
from openminion import MemoryBundle

from cortensor_sentinel.agent import (
    bootstrap_openminion_config,
    run_cortensor_sentinel,
)
from cortensor_sentinel.mock_router import LocalCortensorGateway
from cortensor_sentinel.models import MinerNodeSample
from cortensor_sentinel.poi_engine import (
    CortensorTrustLedger,
    _tokenize_shingles,
    compute_pouw_rubric_score,
    cosine_similarity,
    evaluate_session_poi_pouw,
)
from repro.repro_bug1_cortensor_fallback_tools import reproduce_bug1
from repro.repro_bug2_subagent_decorated_tools import reproduce_bug2
from repro.repro_bug3_cortensor_urn_s3_false_retry import reproduce_bug3


def test_poi_cosine_similarity_identical_and_divergent() -> None:
    vec_a = _tokenize_shingles("Miner receives 212.5 COR (85%) and Validator receives 25.0 COR (10%).")
    vec_b = _tokenize_shingles("Miner receives 212.5 COR (85%) and Validator receives 25.0 COR (10%).")
    vec_c = _tokenize_shingles("Completely unrelated faulty response with tx.origin == owner.")
    assert cosine_similarity(vec_a, vec_b) == 1.0
    assert cosine_similarity(vec_a, vec_c) < 0.35


def test_pouw_rubric_score_penalizes_unsafe_and_slow_miner() -> None:
    good_sample = MinerNodeSample(
        node_id="miner-alpha-01",
        model="gpt-oss-20b",
        latency_ms=380,
        precommit_ms=110,
        token_count=60,
        urn_blob=None,
        output_text="Verified SessionQueueV2 commitment via keccak256: 212.5 COR, 25.0 COR, 12.5 COR.",
    )
    bad_sample = MinerNodeSample(
        node_id="miner-gamma-03",
        model="gpt-oss-20b",
        latency_ms=3200,
        precommit_ms=1400,
        token_count=15,
        urn_blob="blob-ref-pending-timeout",
        output_text="Bad split using tx.origin == owner and selfdestruct().",
    )
    keywords = ["212.5", "25.0", "12.5", "keccak256", "sessionqueuev2"]
    assert compute_pouw_rubric_score(good_sample, keywords) >= 0.95
    assert compute_pouw_rubric_score(bad_sample, keywords) <= 0.40


def test_session_42_flags_miner_gamma_and_tracks_since_last_run(tmp_path: Path) -> None:
    ledger = CortensorTrustLedger(tmp_path / "ledger")
    ev1 = evaluate_session_poi_pouw(42, ledger=ledger)
    assert ev1["divergent_nodes"] == ["miner-gamma-03"]
    assert ev1["poi_quorum_score"] > 0.85
    assert "Initial baseline audit recorded" in ev1["since_last_run_delta"]
    assert len(ev1["evidence_bundle_sha256"]) == 64

    ev2 = evaluate_session_poi_pouw(42, ledger=ledger)
    assert "Run #2 on session 42 vs Run #1" in ev2["since_last_run_delta"]
    assert ledger.get_node_trust("miner-gamma-03") < ledger.get_node_trust("miner-alpha-01")


def test_session_108_healthy_quorum_has_zero_divergent_nodes(tmp_path: Path) -> None:
    ledger = CortensorTrustLedger(tmp_path / "ledger")
    ev = evaluate_session_poi_pouw(108, ledger=ledger)
    assert ev["divergent_nodes"] == []
    assert ev["pouw_mean_score"] == 1.0


def test_openminion_memory_bundle_roundtrip() -> None:
    bundle = MemoryBundle(
        items=[{"session_id": "corsentinel-session-42", "verdict": "DEGRADED_REMEDIATED"}],
        metadata={"agent": "corsentinel_coordinator"},
    )
    raw = bundle.to_json()
    restored = MemoryBundle.from_json(raw)
    assert restored.version == "memory_bundle.v1"
    assert restored.items[0]["verdict"] == "DEGRADED_REMEDIATED"


def test_openminion_0_1_13_bug_reproductions() -> None:
    b1 = reproduce_bug1()
    assert b1["bug_present"] is True
    assert b1["actual_tool_calls_len"] == 0

    b2 = reproduce_bug2()
    assert b2["bug_present"] is True
    assert b2["error_type"] == "TypeError"

    b3 = reproduce_bug3()
    assert b3["bug_present"] is True
    assert b3["extracted_retry_reason"] == "offchain_result_pending"


def test_end_to_end_openminion_agent_workflow_approved_and_rejected(tmp_path: Path) -> None:
    with LocalCortensorGateway() as gw:
        cfg = bootstrap_openminion_config(
            tmp_path,
            api_url=gw.base_url_v1,
            api_mode="openai_chat",
        )
        # Run 1: Session 42 with operator approval
        art1 = run_cortensor_sentinel(
            42,
            home_dir=tmp_path,
            config_path=cfg,
            auto_approve=True,
        )
        assert art1.report.verdict == "DEGRADED_REMEDIATED"
        assert art1.report.divergent_nodes == ["miner-gamma-03"]
        assert "Forensics confirmed on miner-gamma-03" in art1.report.subagent_forensics_summary
        assert "approved_by_operator" in art1.report.remediation_status
        assert any(a["tool_name"] == "queue_miner_remediation" and a["approved"] for a in art1.approvals_recorded)

        # Run 2: Session 42 with operator rejection in approval_callback
        art2 = run_cortensor_sentinel(
            42,
            home_dir=tmp_path,
            config_path=cfg,
            auto_approve=False,
            approval_decider=lambda t, a, i: t != "queue_miner_remediation",
        )
        assert art2.report.verdict == "CRITICAL_QUARANTINE_PENDING"
        assert "rejected_by_operator" in art2.report.remediation_status
        assert "Run #2 on session 42 vs Run #1" in art2.report.since_last_run_delta

        # Run 3: Session 108 healthy quorum
        art3 = run_cortensor_sentinel(
            108,
            home_dir=tmp_path,
            config_path=cfg,
            auto_approve=True,
        )
        assert art3.report.verdict == "HEALTHY_QUORUM"
        assert art3.report.divergent_nodes == []
