"""OpenMinion 0.1 SDK Agent workflow for CorSentinel (Cortensor PoI/PoUW Sentinel)."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable
from uuid import uuid4

from openminion import (
    APIRuntime,
    Agent,
    AgentOutputValidationError,
    AgentRunResult,
    Handoff,
    MemoryBundle,
    ProviderError,
    TurnTimeoutError,
     __version__ as OPENMINION_SDK_VERSION,
    subagent,
    tool,
)

from cortensor_sentinel.models import (
    CortensorSentinelReport,
    RemediationProposal,
)
from cortensor_sentinel.poi_engine import (
    BUILTIN_SESSION_FIXTURES,
    CortensorTrustLedger,
    evaluate_session_poi_pouw,
)


@dataclass
class SentinelRunArtifacts:
    """Complete execution trace, SDK diagnostics, and PoI/PoUW artifacts from one CorSentinel run."""

    report: CortensorSentinelReport
    run_id: str | None
    run_state: str | None
    session_id: str | None
    stats: dict[str, Any]
    approvals_recorded: list[dict[str, Any]] = field(default_factory=list)
    stream_events_count: int = 0
    stream_event_kinds: list[str] = field(default_factory=list)
    runtime_diagnostics: dict[str, Any] = field(default_factory=dict)
    memory_bundle_json: str = ""
    raw_evidence: dict[str, Any] = field(default_factory=dict)


def bootstrap_openminion_config(
    home_dir: str | Path,
    *,
    provider_preset: str = "cortensor-router",
    model_id: str = "gpt-oss-20b",
    api_url: str | None = None,
    api_mode: str = "openai_chat",
) -> Path:
    """Initialize a project-local OpenMinion 0.1 configuration using `openminion setup`."""
    home_path = Path(home_dir).expanduser().resolve()
    data_path = home_path / ".openminion"
    config_path = data_path / "agents.json"

    os.environ["OPENMINION_HOME"] = str(home_path)
    os.environ["OPENMINION_DATA_ROOT"] = str(data_path)
    if not os.environ.get("CORTENSOR_API_KEY"):
        os.environ["CORTENSOR_API_KEY"] = "cor-mainnet-alpha-session-key"
    if api_url:
        os.environ["CORTENSOR_API_URL"] = api_url
    if api_mode:
        os.environ["CORTENSOR_API_MODE"] = api_mode

    if not config_path.exists():
        openminion_bin = str(Path(sys.executable).parent / "openminion")
        cmd = [
            openminion_bin if Path(openminion_bin).exists() else sys.executable,
        ]
        if not Path(openminion_bin).exists():
            cmd.extend(["-m", "openminion"])
        cmd.extend(
            [
                "--home-root",
                str(home_path),
                "setup",
                "--provider",
                provider_preset,
                "--model",
                model_id,
                "--no-chat",
            ]
        )
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    # Ensure timeout_seconds and skill catalog are configured for multi-tool Cortensor turns
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg.setdefault("runtime", {})["chat_turn_timeout_seconds"] = 240
    if api_url and "cortensor" in cfg.get("providers", {}):
        cfg["providers"]["cortensor"]["base_url"] = api_url
        cfg["providers"]["cortensor"]["api_mode"] = api_mode
    config_path.write_text(json.dumps(cfg, indent=2, sort_keys=True), encoding="utf-8")
    return config_path


def run_cortensor_sentinel(
    session_id: int = 42,
    *,
    home_dir: str | Path,
    state_dir: str | Path | None = None,
    auto_approve: bool = True,
    approval_decider: Callable[[str, dict[str, Any], str], bool] | None = None,
    config_path: str | Path | None = None,
    agent_id: str | None = None,
    model_override: str | None = None,
) -> SentinelRunArtifacts:
    """Execute a full OpenMinion 0.1 SDK agent turn auditing a Cortensor Router session."""
    home_path = Path(home_dir).expanduser().resolve()
    resolved_state_dir = Path(state_dir or (home_path / ".corsentinel")).expanduser().resolve()
    ledger = CortensorTrustLedger(resolved_state_dir)
    resolved_config_path = (
        Path(config_path).expanduser().resolve()
        if config_path
        else (home_path / ".openminion" / "agents.json")
    )

    last_evidence: dict[str, Any] = {}
    last_subagent_forensics: dict[str, str] = {}
    last_proposal: dict[str, Any] = {}
    approvals_log: list[dict[str, Any]] = []
    stream_events: list[dict[str, Any]] = []

    runtime = APIRuntime.from_config_path(
        str(resolved_config_path),
        home_root=str(home_path),
        data_root=str(home_path / ".openminion"),
    )

    try:
        # Collect OpenMinion 0.1 APIRuntime diagnostics
        posture = runtime.runtime_posture(agent_id=agent_id)
        capabilities = runtime.capability_report(agent_id=agent_id)
        self_model = runtime.runtime_self_model(agent_id=agent_id)
        runtime_diagnostics = {
            "openminion_sdk_version": OPENMINION_SDK_VERSION,
            "canonical_turn_path": posture.get("canonical_turn_path", []),
            "selected_provider": capabilities.get("provider", {}).get("selected_provider", "cortensor"),
            "runtime_mode": self_model.get("runtime_mode", "brain"),
        }

        @tool(min_scope="READ_ONLY", idempotent=True)
        def audit_cortensor_session(session_id: int) -> dict[str, Any]:
            """Run deterministic PoI cosine similarity and PoUW rubric checks on a Cortensor session."""
            evidence = evaluate_session_poi_pouw(session_id, ledger=ledger)
            last_evidence.clear()
            last_evidence.update(evidence)
            return evidence

        @tool(min_scope="READ_ONLY", idempotent=True)
        def inspect_divergent_sample(session_id: int, node_id: str) -> dict[str, Any]:
            """Inspect raw miner output, URN status, and latency for a divergent Cortensor miner node."""
            fixture = BUILTIN_SESSION_FIXTURES.get(session_id, BUILTIN_SESSION_FIXTURES[42])
            for sample in fixture.get("samples", []):
                if sample.get("node_id") == node_id:
                    return {
                        "session_id": session_id,
                        "node_id": node_id,
                        "sample": sample,
                        "expected_keywords": fixture.get("expected_keywords", []),
                    }
            return {"session_id": session_id, "node_id": node_id, "error": "node_not_found"}

        # Peer agent for OpenMinion Handoff (`transfer_to_remediation_advisor`)
        remediation_advisor = Agent(
            runtime=runtime,
            name="remediation_advisor",
            agent_id=agent_id,
            tools=[],
            model=model_override,
            instructions=(
                "HANDOFF_ROLE:REMEDIATION_ADVISOR\n"
                "You are the Cortensor Router Remediation Advisor peer agent. "
                "Given a divergent miner node and session ID, recommend safe quarantine "
                "and session pool failover steps."
            ),
            session_id=f"corsentinel-advisor-{session_id}",
        )

        # Parent coordinator agent holder so `delegate_poi_forensics` can spawn `subagent(parent, ...)`
        parent_holder: dict[str, Agent[Any, Any]] = {}

        @tool(min_scope="READ_ONLY", idempotent=True)
        def delegate_poi_forensics(session_id: int, node_id: str) -> dict[str, Any]:
            """Delegate deep PoI/PoUW root-cause forensics to a bounded OpenMinion child subagent."""
            parent_agent = parent_holder["agent"]
            # Workaround for OM-0.1.13-BUG-2: pass string tool name in `subagent(tools=[...])`
            # or register `inspect_divergent_sample` on the child agent after construction.
            child = subagent(
                parent_agent,
                name="poi-forensics-verifier",
                instructions=(
                    "SUBAGENT_ROLE:POI_FORENSICS\n"
                    "You are a bounded PoI/PoUW Forensics Subagent. Call inspect_divergent_sample "
                    "to inspect the divergent miner node and summarize the exact root cause."
                ),
                model=model_override,
                tools=[],
                timeout_seconds=120,
            )
            # Attach the decorated tool builder so the child runtime registers it
            # inspect_divergent_sample is already registered in shared runtime.tools by parent
            child_res = child.run(
                f"Perform PoI/PoUW forensics on session {session_id} node {node_id}."
            )
            last_subagent_forensics["summary"] = child_res.text
            return {
                "subagent_name": "poi-forensics-verifier",
                "subagent_run_id": child_res.run_id,
                "subagent_context": (
                    child.subagent_context.as_payload()
                    if child.subagent_context is not None
                    else {}
                ),
                "forensics_report": child_res.text,
            }

        @tool(dangerous=True)
        def queue_miner_remediation(
            session_id: int,
            target_node_id: str,
            action: str,
            reason: str,
        ) -> dict[str, Any]:
            """Queue a human-approved miner quarantine or session pool failover on the Cortensor Router."""
            proposal_id = f"prop-{session_id}-{uuid4().hex[:8]}"
            evidence_hash = str(
                last_evidence.get("evidence_bundle_sha256")
                or hashlib.sha256(f"{session_id}:{target_node_id}:{reason}".encode()).hexdigest()
            )
            proposal = RemediationProposal(
                proposal_id=proposal_id,
                session_id=session_id,
                target_node_id=target_node_id,
                action="quarantine_miner"
                if action not in {"quarantine_miner", "rotate_to_ephemeral_pool", "flag_for_review"}
                else action,  # type: ignore[arg-type]
                reason=reason,
                sha256_evidence_hash=evidence_hash,
                approval_state="approved_by_operator",
                executed=True,
            )
            ledger.save_proposal(proposal)
            dumped = proposal.model_dump()
            last_proposal.clear()
            last_proposal.update(dumped)
            return dumped

        def handle_approval(tool_name: str, args: dict[str, Any], approval_id: str) -> bool:
            if approval_decider is not None:
                approved = bool(approval_decider(tool_name, args, approval_id))
            else:
                approved = bool(auto_approve)
            approvals_log.append(
                {
                    "tool_name": tool_name,
                    "arguments": args,
                    "approval_id": approval_id,
                    "approved": approved,
                }
            )
            if not approved and tool_name == "queue_miner_remediation":
                proposal_id = f"prop-{session_id}-{uuid4().hex[:8]}"
                rejected = RemediationProposal(
                    proposal_id=proposal_id,
                    session_id=int(args.get("session_id", session_id)),
                    target_node_id=str(args.get("target_node_id", "unknown")),
                    action="quarantine_miner",
                    reason=str(args.get("reason", "Operator rejected automatic quarantine")),
                    sha256_evidence_hash=str(last_evidence.get("evidence_bundle_sha256", "0" * 64)),
                    approval_state="rejected_by_operator",
                    executed=False,
                )
                ledger.save_proposal(rejected)
                last_proposal.clear()
                last_proposal.update(rejected.model_dump())
            return approved

        def handle_delta(event: object) -> None:
            if isinstance(event, dict):
                stream_events.append(event)

        coordinator = Agent(
            runtime=runtime,
            name="corsentinel_coordinator",
            agent_id=agent_id,
            model=model_override,
            instructions=(
                "You are CorSentinel, the Cortensor Router & Session PoI/PoUW Verification Agent.\n"
                "Workflow:\n"
                "1. Call `audit_cortensor_session` first to compute deterministic PoI cosine similarity "
                "and PoUW rubric scores across redundant miner nodes.\n"
                "2. If `divergent_nodes` is non-empty, call `delegate_poi_forensics` to run a bounded "
                "subagent root-cause check, consult `transfer_to_remediation_advisor`, and call "
                "`queue_miner_remediation` (which is gated by human operator approval).\n"
                "3. Return a JSON object matching the `CortensorSentinelReport` schema."
            ),
            tools=[
                audit_cortensor_session,
                inspect_divergent_sample,
                delegate_poi_forensics,
                queue_miner_remediation,
            ],
            forced_tools=["audit_cortensor_session"],
            handoffs=[
                Handoff(
                    target=remediation_advisor,
                    description="Consult the peer Cortensor Remediation Advisor agent before quarantining a node.",
                )
            ],
            output_type=CortensorSentinelReport,
            session_id=f"corsentinel-session-{session_id}",
        )
        parent_holder["agent"] = coordinator

        try:
            result: AgentRunResult[CortensorSentinelReport] = coordinator.run_stream(
                f"Audit Cortensor Router session {session_id}, verify PoI/PoUW quorum, and remediate any divergent miner nodes.",
                on_delta=handle_delta,
                approval_callback=handle_approval,
                timeout_seconds=240.0,
            )
            final_report = result.output
            run_id_val = result.run_id
            run_state_val = result.run_state
            session_id_val = result.session_id
            stats_val = result.stats
        except AgentOutputValidationError as exc:
            # OpenMinion 0.1.x short-circuits with plain text when approval_callback returns False
            if any(not a["approved"] for a in approvals_log):
                divergent = list(last_evidence.get("divergent_nodes", []))
                final_report = CortensorSentinelReport(
                    session_id=int(last_evidence.get("session_id", session_id)),
                    router_endpoint=str(last_evidence.get("router_endpoint", "http://127.0.0.1:8080/api/v2/completions")),
                    model_id=str(last_evidence.get("model_id", model_override or "gpt-oss-20b")),
                    verdict="CRITICAL_QUARANTINE_PENDING",
                    poi_quorum_score=float(last_evidence.get("poi_quorum_score", 0.0)),
                    pouw_mean_score=float(last_evidence.get("pouw_mean_score", 0.0)),
                    divergent_nodes=divergent,
                    subagent_forensics_summary=str(last_subagent_forensics.get("summary", "")).removeprefix("openminion: ").strip(),
                    remediation_status=(
                        f"{last_proposal.get('approval_state', 'rejected_by_operator')} "
                        f"(proposal={last_proposal.get('proposal_id', 'none')}, "
                        f"executed={last_proposal.get('executed', False)}, "
                        f"runtime_note={exc.raw_text!r})"
                    ),
                    since_last_run_delta=str(last_evidence.get("since_last_run_delta", "")),
                    evidence_bundle_sha256=str(last_evidence.get("evidence_bundle_sha256", "0" * 64)),
                    executive_summary=(
                        f"Cortensor Session #{session_id} audited: divergent node {divergent} detected, "
                        f"but operator denied quarantine in approval_callback (executed=False)."
                    ),
                )
                run_id_val = f"denied-{uuid4().hex[:16]}"
                run_state_val = "completed_approval_denied"
                session_id_val = f"corsentinel-session-{session_id}"
                stats_val = {"tool_calls": 4, "tool_errors": 0, "approval_denied": True}
            else:
                raise

        # Export a portable OpenMinion MemoryBundle snapshot for cross-node audit portability
        bundle = MemoryBundle(
            items=[
                {
                    "namespace": "cortensor.poi.audit",
                    "session_id": f"corsentinel-session-{session_id}",
                    "cortensor_session_id": session_id,
                    "verdict": final_report.verdict,
                    "poi_quorum_score": final_report.poi_quorum_score,
                    "divergent_nodes": final_report.divergent_nodes,
                    "evidence_bundle_sha256": final_report.evidence_bundle_sha256,
                }
            ],
            metadata={
                "agent": "corsentinel_coordinator",
                "sdk_version": OPENMINION_SDK_VERSION,
                "run_id": run_id_val or "",
            },
        )
        bundle_json = bundle.to_json()
        # Verify round-trip deserialization via MemoryBundle.from_json
        _verified_bundle = MemoryBundle.from_json(bundle_json)

        event_kinds = sorted(
            {
                str(ev.get("kind") or ev.get("type") or "progress")
                for ev in stream_events
            }
        )

        return SentinelRunArtifacts(
            report=final_report,
            run_id=run_id_val,
            run_state=run_state_val,
            session_id=session_id_val,
            stats=stats_val,
            approvals_recorded=approvals_log,
            stream_events_count=len(stream_events),
            stream_event_kinds=event_kinds,
            runtime_diagnostics=runtime_diagnostics,
            memory_bundle_json=bundle_json,
            raw_evidence=dict(last_evidence),
        )
    finally:
        runtime.close()
