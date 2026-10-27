"""Local Cortensor Router (/api/v2/completions) & Portal (/v1/chat/completions) Gateway Emulator.

Allows OpenMinion 0.1.x (`cortensor-router` and `cortensor-portal` presets) to execute full
HTTP model-backed turns, tool loops, subagent delegation, peer handoffs, and human-approval
gates deterministically without requiring external paid API keys, while remaining 100%
wire-compatible with live Cortensor Router and Portal endpoints.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
from typing import Any


def _extract_session_id_from_messages(messages: list[dict[str, Any]]) -> int:
    for msg in reversed(messages):
        content = str(msg.get("content") or "")
        match = re.search(r"session[\s_#-]*(\d+)", content, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 42


def _parse_tool_outputs(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        raw = str(msg.get("content") or "")
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                payload = obj.get("outputs") if isinstance(obj.get("outputs"), dict) else obj
                parsed.append(payload)
        except Exception:
            parsed.append({"raw": raw})
    return parsed


class CortensorGatewayHandler(BaseHTTPRequestHandler):
    """HTTP handler implementing Cortensor Portal (/v1/chat/completions) and Router (/api/v2/completions)."""

    request_log: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:
        if self.path.endswith("/health") or self.path.endswith("/status"):
            self._send_json(
                {
                    "ok": True,
                    "service": "cortensor-local-router-gateway",
                    "router_version": "v2.1-mainnet-alpha",
                    "active_sessions": [42, 108],
                }
            )
            return
        self._send_json({"ok": True, "path": self.path})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            body = {}

        messages = body.get("messages", [])
        tools = body.get("tools", [])
        tool_names = [
            str(t.get("function", {}).get("name") or "")
            for t in tools
            if isinstance(t, dict)
        ]
        model = str(body.get("model") or "gpt-oss-20b")
        CortensorGatewayHandler.request_log.append(
            {
                "path": self.path,
                "model": model,
                "tool_names": tool_names,
                "message_count": len(messages),
            }
        )

        # 1. Handle OpenMinion internal schema-only submit_output control calls
        if tool_names == ["submit_output"]:
            schema = tools[0].get("function", {}).get("parameters", {})
            title = str(schema.get("title") or "")
            if title == "UserMessageCandidateReport":
                submit_args: dict[str, Any] = {
                    "session_id": "cortensor-session",
                    "agent_id": "openminion",
                    "items": [],
                }
            elif title == "FreshnessContract":
                submit_args = {
                    "intent": "task_execution",
                    "domain": "general",
                    "time_sensitive": False,
                    "needs_live_data": True,
                    "needs_sources": False,
                    "needs_exact_date": False,
                    "answer_mode": "direct",
                    "reason": "Cortensor session PoI/PoUW audit workflow",
                    "confidence": 0.98,
                }
            else:
                submit_args = {}
            self._send_chat_tool_call(
                model=model,
                call_id=f"call_submit_{len(CortensorGatewayHandler.request_log)}",
                tool_name="submit_output",
                arguments=submit_args,
            )
            return

        # 2. Handle child subagent (`poi-forensics-verifier`) or peer Handoff (`remediation_advisor`) turns
        user_text = " ".join(
            str(m.get("content") or "") for m in messages if m.get("role") == "user"
        )
        tool_outputs = _parse_tool_outputs(messages)

        if "audit_cortensor_session" not in tool_names:
            if "Perform PoI/PoUW forensics on session" in user_text:
                self._send_chat_text(
                    model=model,
                    content=(
                        "Forensics confirmed on miner-gamma-03: (1) quantized weight drift produced "
                        "an invalid 240/10 COR split instead of 212.5/25.0/12.5 COR; (2) unsafe Solidity "
                        "tx.origin authorization pattern injected; (3) off-chain S3 URN remained in "
                        "blob-ref-pending-timeout state past 3190ms SLA."
                    ),
                )
                return

            if "Recommend safe remediation for Cortensor session" in user_text:
                self._send_chat_text(
                    model=model,
                    content=(
                        "Peer Remediation Advisor recommendation: quarantine divergent miner-gamma-03 "
                        "behind human operator approval and fail over session 42 to backup ephemeral "
                        "miner pool while preserving verified quorum nodes miner-alpha-01 and miner-beta-02."
                    ),
                )
                return

        # 3. Main CorSentinel Coordinator Agent multi-step tool loop
        session_id = _extract_session_id_from_messages(messages)

        # Step 1: Call audit_cortensor_session
        if "audit_cortensor_session" in tool_names and len(tool_outputs) == 0:
            self._send_chat_tool_call(
                model=model,
                call_id="call_audit_session_1",
                tool_name="audit_cortensor_session",
                arguments={"session_id": session_id},
            )
            return

        # Inspect what tools have already run in this turn
        audit_data: dict[str, Any] = {}
        forensics_summary = ""
        handoff_note = ""
        remediation_data: dict[str, Any] = {}

        for out in tool_outputs:
            if "poi_quorum_score" in out:
                audit_data = out
            elif "forensics_report" in out:
                forensics_summary = str(out["forensics_report"]).removeprefix("openminion: ").strip()
            elif "content" in out and "Peer Remediation Advisor" in str(out.get("content", "")):
                handoff_note = str(out["content"])
            elif "proposal_id" in out:
                remediation_data = out

        divergent = list(audit_data.get("divergent_nodes", []))

        # Step 2: If divergent nodes exist and forensics hasn't run yet, call delegate_poi_forensics
        if divergent and not forensics_summary and "delegate_poi_forensics" in tool_names:
            self._send_chat_tool_call(
                model=model,
                call_id="call_delegate_forensics_2",
                tool_name="delegate_poi_forensics",
                arguments={
                    "session_id": session_id,
                    "node_id": divergent[0],
                },
            )
            return

        # Step 3: If peer handoff tool is available and hasn't run yet, consult peer advisor
        if (
            divergent
            and forensics_summary
            and not handoff_note
            and "transfer_to_remediation_advisor" in tool_names
        ):
            self._send_chat_tool_call(
                model=model,
                call_id="call_handoff_advisor_3",
                tool_name="transfer_to_remediation_advisor",
                arguments={
                    "message": f"Recommend safe remediation for Cortensor session {session_id} divergent node {divergent[0]}."
                },
            )
            return

        # Step 4: Queue human-gated remediation (`dangerous=True`)
        if (
            divergent
            and not remediation_data
            and "queue_miner_remediation" in tool_names
        ):
            self._send_chat_tool_call(
                model=model,
                call_id="call_queue_remediation_4",
                tool_name="queue_miner_remediation",
                arguments={
                    "session_id": session_id,
                    "target_node_id": divergent[0],
                    "action": "quarantine_miner",
                    "reason": forensics_summary
                    or f"PoI drift and PoUW failure on {divergent[0]}",
                },
            )
            return

        # Step 5: Emit final Pydantic-validated CortensorSentinelReport JSON
        verdict = (
            "HEALTHY_QUORUM"
            if not divergent
            else (
                "DEGRADED_REMEDIATED"
                if remediation_data.get("executed")
                else "CRITICAL_QUARANTINE_PENDING"
            )
        )
        final_report = {
            "session_id": int(audit_data.get("session_id", session_id)),
            "router_endpoint": str(
                audit_data.get(
                    "router_endpoint", "http://127.0.0.1:8080/api/v2/completions"
                )
            ),
            "model_id": str(audit_data.get("model_id", model)),
            "verdict": verdict,
            "poi_quorum_score": float(audit_data.get("poi_quorum_score", 0.996)),
            "pouw_mean_score": float(audit_data.get("pouw_mean_score", 0.95)),
            "divergent_nodes": divergent,
            "subagent_forensics_summary": forensics_summary
            or "All redundant miner nodes satisfied PoI cosine quorum and PoUW rubric checks; no forensics subagent required.",
            "remediation_status": (
                f"{remediation_data.get('approval_state', 'no_action_needed')} "
                f"(proposal={remediation_data.get('proposal_id', 'none')}, "
                f"executed={remediation_data.get('executed', False)})"
                if remediation_data
                else "no_action_needed (quorum healthy)"
            ),
            "since_last_run_delta": str(
                audit_data.get("since_last_run_delta", "Baseline session audit complete.")
            ),
            "evidence_bundle_sha256": str(
                audit_data.get("evidence_bundle_sha256", "0" * 64)
            ),
            "executive_summary": (
                f"Cortensor Session #{session_id} audited via OpenMinion 0.1 SDK: "
                f"verdict={verdict}, PoI quorum={audit_data.get('poi_quorum_score', 0.996):.4f}, "
                f"divergent_nodes={divergent or 'none'}."
            ),
        }
        self._send_chat_text(model=model, content=json.dumps(final_report))

    def _send_chat_tool_call(
        self,
        *,
        model: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        resp = {
            "id": f"chatcmpl-{call_id}",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(arguments),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 140,
                "completion_tokens": 28,
                "total_tokens": 168,
            },
        }
        self._send_json(resp)

    def _send_chat_text(self, *, model: str, content: str) -> None:
        resp = {
            "id": f"chatcmpl-final-{len(CortensorGatewayHandler.request_log)}",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 210,
                "completion_tokens": 64,
                "total_tokens": 274,
            },
        }
        self._send_json(resp)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class LocalCortensorGateway:
    """Context manager running the local Cortensor Router & Portal HTTP gateway."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._server = ThreadingHTTPServer((host, port), CortensorGatewayHandler)
        self.host = host
        self.port = int(self._server.server_port)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url_v1(self) -> str:
        return f"http://{self.host}:{self.port}/v1"

    def start(self) -> "LocalCortensorGateway":
        CortensorGatewayHandler.request_log.clear()
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "LocalCortensorGateway":
        return self.start()

    def __exit__(self, *args: object) -> None:
        self.stop()
