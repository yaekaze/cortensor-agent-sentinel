"""CLI entrypoint and interactive dashboard server for CorSentinel."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from typing import Any

from cortensor_sentinel.agent import (
    bootstrap_openminion_config,
    run_cortensor_sentinel,
)
from cortensor_sentinel.mock_router import LocalCortensorGateway


def _format_console_summary(artifacts: Any, label: str) -> str:
    rep = artifacts.report
    lines = [
        f"================================================================================",
        f" {label}",
        f"================================================================================",
        f"  OpenMinion Run ID      : {artifacts.run_id} (state={artifacts.run_state})",
        f"  OpenMinion Session ID  : {artifacts.session_id}",
        f"  Cortensor Session ID   : #{rep.session_id} ({rep.router_endpoint})",
        f"  Model                  : {rep.model_id}",
        f"  Verdict                : {rep.verdict}",
        f"  PoI Quorum Similarity  : {rep.poi_quorum_score:.4f}",
        f"  PoUW Mean Rubric Score : {rep.pouw_mean_score:.4f}",
        f"  Divergent Miner Nodes  : {', '.join(rep.divergent_nodes) if rep.divergent_nodes else 'None (All Verified)'}",
        f"  Subagent Forensics     : {rep.subagent_forensics_summary}",
        f"  Remediation Status     : {rep.remediation_status}",
        f"  Since Last Run Delta   : {rep.since_last_run_delta}",
        f"  Evidence Bundle SHA256 : {rep.evidence_bundle_sha256}",
        f"  SDK Stats              : {json.dumps(artifacts.stats, sort_keys=True)}",
        f"  Approvals Recorded     : {len(artifacts.approvals_recorded)} ({', '.join(a['tool_name'] + '=' + ('APPROVED' if a['approved'] else 'REJECTED') for a in artifacts.approvals_recorded) or 'none'})",
        f"  Stream Events Captured : {artifacts.stream_events_count} events (kinds={artifacts.stream_event_kinds})",
        f"================================================================================",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cortensor_sentinel",
        description="CorSentinel: Cortensor Router & Session PoI/PoUW Verification Agent (OpenMinion 0.1 SDK)",
    )
    parser.add_argument(
        "--session",
        type=int,
        default=42,
        help="Cortensor Router session ID to audit (default: 42; use 108 for healthy quorum)",
    )
    parser.add_argument(
        "--demo-suite",
        action="store_true",
        help="Run the complete 3-stage verification suite (Session 42 initial + Session 42 repeat delta + Session 108 healthy quorum)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        default=True,
        help="Automatically approve dangerous remediation tools in non-interactive mode (default: True)",
    )
    parser.add_argument(
        "--reject-remediation",
        action="store_true",
        help="Simulate operator rejecting the miner quarantine proposal in approval_callback",
    )
    parser.add_argument(
        "--home-dir",
        default=".runtime_home",
        help="Project-local OpenMinion home directory (default: .runtime_home)",
    )
    parser.add_argument(
        "--out-dir",
        default="runs",
        help="Directory to write JSON reports, MemoryBundle snapshots, and transcripts (default: runs)",
    )
    parser.add_argument(
        "--live-provider",
        action="store_true",
        help="Use live configured CORTENSOR_API_URL / provider instead of starting the built-in local Cortensor Router emulator",
    )
    parser.add_argument(
        "--serve-dashboard",
        type=int,
        default=0,
        metavar="PORT",
        help="Serve the interactive CorSentinel Web Dashboard on PORT (e.g. 8787)",
    )
    args = parser.parse_args(argv)

    home_dir = Path(args.home_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    auto_approve = not args.reject_remediation

    gateway_ctx = LocalCortensorGateway() if not args.live_provider else None
    if gateway_ctx is not None:
        gateway_ctx.start()
        api_url = gateway_ctx.base_url_v1
    else:
        api_url = None

    try:
        cfg_path = bootstrap_openminion_config(
            home_dir,
            provider_preset="cortensor-router",
            model_id="gpt-oss-20b",
            api_url=api_url,
            api_mode="openai_chat",
        )

        if args.demo_suite:
            runs_spec = [
                (42, True, "RUN 1: Session #42 — Byzantine Drift Detection, Subagent Forensics & Operator-Approved Quarantine"),
                (42, False, "RUN 2: Session #42 — Cross-Session Continuity ('Since Last Run' Delta) & Operator-Rejected Override"),
                (108, True, "RUN 3: Session #108 — Healthy 3-Node Cortensor Portal Quorum (Zero False Positives)"),
            ]
        else:
            runs_spec = [
                (
                    args.session,
                    auto_approve,
                    f"CorSentinel Audit — Cortensor Session #{args.session}",
                )
            ]

        all_results: list[dict[str, Any]] = []
        transcript_blocks: list[str] = []

        for idx, (sess_id, approve_flag, title) in enumerate(runs_spec, start=1):
            def _decider(tool_name: str, tool_args: dict[str, Any], approval_id: str) -> bool:
                if tool_name == "queue_miner_remediation":
                    return approve_flag
                return True

            artifacts = run_cortensor_sentinel(
                sess_id,
                home_dir=home_dir,
                state_dir=home_dir / ".corsentinel",
                auto_approve=approve_flag,
                approval_decider=_decider,
                config_path=cfg_path,
            )
            summary_text = _format_console_summary(artifacts, title)
            print(summary_text)
            transcript_blocks.append(summary_text)

            payload = {
                "run_index": idx,
                "title": title,
                "run_id": artifacts.run_id,
                "run_state": artifacts.run_state,
                "session_id": artifacts.session_id,
                "report": artifacts.report.model_dump(),
                "stats": artifacts.stats,
                "approvals_recorded": artifacts.approvals_recorded,
                "stream_events_count": artifacts.stream_events_count,
                "stream_event_kinds": artifacts.stream_event_kinds,
                "runtime_diagnostics": artifacts.runtime_diagnostics,
                "raw_evidence": artifacts.raw_evidence,
            }
            all_results.append(payload)

            (out_dir / f"run_{idx}_session_{sess_id}.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            (out_dir / f"memory_bundle_run_{idx}_session_{sess_id}.json").write_text(
                artifacts.memory_bundle_json,
                encoding="utf-8",
            )

        (out_dir / "latest_suite_summary.json").write_text(
            json.dumps({"runs": all_results}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (out_dir / "latest_transcript.txt").write_text(
            "\n\n".join(transcript_blocks) + "\n",
            encoding="utf-8",
        )

        if args.serve_dashboard > 0:
            dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"
            (dashboard_dir / "latest_suite_summary.json").write_text(
                json.dumps({"runs": all_results}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            print(f"\nServing CorSentinel Dashboard at http://127.0.0.1:{args.serve_dashboard} ...")
            handler = lambda *h_args, **h_kwargs: SimpleHTTPRequestHandler(
                *h_args, directory=str(dashboard_dir), **h_kwargs
            )
            httpd = ThreadingHTTPServer(("127.0.0.1", args.serve_dashboard), handler)
            httpd.serve_forever()

        return 0
    finally:
        if gateway_ctx is not None:
            gateway_ctx.stop()


if __name__ == "__main__":
    raise SystemExit(main())
