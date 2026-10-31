"""End-to-end action tests against a local, scripted HTTP control plane."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ACTION = Path(__file__).resolve().parents[1] / "main.py"
TOKEN = "ado_test_control_secret"
PROVIDER_KEY = "test_provider_secret"
IDEMPOTENCY = "11111111-1111-4111-8111-111111111111"


class ScriptedServer(ThreadingHTTPServer):
    def __init__(self, replies: list[tuple[int, dict]]) -> None:
        self.replies = list(replies)
        self.requests: list[tuple[str, str, dict, bytes]] = []
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(BaseHTTPRequestHandler):
    server: ScriptedServer

    def do_POST(self) -> None:
        self._reply()

    def do_GET(self) -> None:
        self._reply()

    def _reply(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.requests.append((self.command, self.path, dict(self.headers), body))
        status, reply = self.server.replies.pop(0) if self.server.replies else (500, {})
        encoded = json.dumps(reply).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args: object) -> None:
        pass


def outputs(path: Path) -> dict[str, str]:
    lines = path.read_text().splitlines()
    result: dict[str, str] = {}
    while lines:
        key, delimiter = lines.pop(0).split("<<", 1)
        values: list[str] = []
        while lines[0] != delimiter:
            values.append(lines.pop(0))
        lines.pop(0)
        result[key] = "\n".join(values)
    return result


class ActionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "outputs"
        self.output.touch()
        self.summary = self.root / "summary"
        self.server: ScriptedServer | None = None

    def tearDown(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        self.temp.cleanup()

    def start(self, replies: list[tuple[int, dict]]) -> None:
        self.server = ScriptedServer(replies)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def run_action(self, **changes: str) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        assert self.server is not None
        env = {key: value for key, value in os.environ.items() if not key.startswith("AO_")}
        env.update({
            "GITHUB_WORKSPACE": str(self.root),
            "GITHUB_OUTPUT": str(self.output),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "AO_API_URL": f"http://127.0.0.1:{self.server.server_port}",
            "AO_API_KEY": TOKEN,
            "AO_PROMPT": "Private task contents",
            "AO_IDEMPOTENCY_KEY": IDEMPOTENCY,
            "AO_PROVIDER": "openai",
            "AO_PROVIDER_MODEL": "example-model",
            "AO_PROVIDER_KEY": PROVIDER_KEY,
            "AO_WAIT_TIMEOUT": "5",
            "AO_POLL_INTERVAL": "1",
        })
        env.update(changes)
        process = subprocess.run(
            [sys.executable, "-I", str(ACTION)], env=env, capture_output=True, text=True, timeout=10
        )
        return process, outputs(self.output)

    def test_submit_poll_evidence_and_report_without_leaking_secrets(self) -> None:
        self.start([
            (201, {"run_id": "run-1", "status": "QUEUED"}),
            (200, {"run_id": "run-1", "status": "RUNNING"}),
            (200, {"run_id": "run-1", "status": "SUCCEEDED", "result_status": "DEGRADED",
                   "evaluation_status": "PENDING"}),
            (200, {"run_id": "run-1", "checks": [], "verification_status": "PASSED"}),
            (200, {"run": {"run_id": "run-1"}, "snapshot_sha256": "a" * 64,
                   "io": {"output": "private output"}}),
        ])
        (self.root / "context.txt").write_text("Private context", encoding="utf-8")
        process, result = self.run_action(
            AO_CONTEXT_FILE="context.txt", AO_VERIFICATION="required", AO_REPORT_FILE="report.json"
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result["run-id"], "run-1")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["result-status"], "DEGRADED")
        self.assertEqual(result["evaluation-status"], "PENDING")
        self.assertEqual(result["verification-status"], "PASSED")
        self.assertEqual(result["idempotency-key"], IDEMPOTENCY)
        self.assertEqual(len(result["report-sha256"]), 64)
        self.assertEqual(json.loads((self.root / "report.json").read_text())["io"]["output"],
                         "private output")
        assert self.server is not None
        self.assertEqual([request[0] for request in self.server.requests],
                         ["POST", "GET", "GET", "GET", "GET"])
        headers = {key.lower(): value for key, value in self.server.requests[0][2].items()}
        self.assertEqual(headers["idempotency-key"], IDEMPOTENCY)
        self.assertEqual(headers["x-provider-key"], PROVIDER_KEY)
        self.assertEqual(json.loads(self.server.requests[0][3])["global_context"], "Private context")
        for _, _, headers, _ in self.server.requests[1:]:
            self.assertFalse(any(key.lower().startswith("x-provider") for key in headers))
        visible = process.stdout + process.stderr + self.summary.read_text() + self.output.read_text()
        for secret in (TOKEN, PROVIDER_KEY, "Private task contents", "Private context", "private output"):
            self.assertNotIn(secret, visible)

    def test_required_verification_does_not_treat_execution_as_pass(self) -> None:
        self.start([(201, {"run_id": "r1", "status": "QUEUED"}),
                    (200, {"run_id": "r1", "status": "SUCCEEDED"}),
                    (200, {"run_id": "r1", "checks": [], "verification_status": "NOT_RUN"})])
        process, result = self.run_action(AO_VERIFICATION="required")
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["verification-status"], "NOT_RUN")

    def test_optional_unavailable_evidence_does_not_claim_verification(self) -> None:
        self.start([(201, {"run_id": "r1", "status": "QUEUED"}),
                    (200, {"run_id": "r1", "status": "SUCCEEDED"}), (404, {})])
        process, result = self.run_action()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result["verification-status"], "UNAVAILABLE")

    def test_resume_is_read_only(self) -> None:
        self.start([(200, {"run_id": "r1", "status": "SUCCEEDED"})])
        process, result = self.run_action(
            AO_PROMPT="", AO_IDEMPOTENCY_KEY="", AO_PROVIDER="", AO_PROVIDER_MODEL="",
            AO_PROVIDER_KEY="", AO_RESUME_RUN_ID="r1", AO_VERIFICATION="off"
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result["verification-status"], "NOT_REQUESTED")
        self.assertNotIn("idempotency-key", result)
        assert self.server is not None
        self.assertEqual([request[0] for request in self.server.requests], ["GET"])

    def test_failed_submission_is_not_retried_or_logged(self) -> None:
        self.start([(503, {"error": {"message": f"{TOKEN} {PROVIDER_KEY}"}})])
        process, result = self.run_action()
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["idempotency-key"], IDEMPOTENCY)
        assert self.server is not None
        self.assertEqual(len(self.server.requests), 1)
        for secret in (TOKEN, PROVIDER_KEY):
            self.assertNotIn(secret, process.stdout + process.stderr + self.summary.read_text())

    def test_mismatched_run_fails_closed(self) -> None:
        self.start([(201, {"run_id": "r1", "status": "QUEUED"}),
                    (200, {"run_id": "other", "status": "SUCCEEDED"})])
        process, result = self.run_action(AO_VERIFICATION="off")
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["run-id"], "r1")
        self.assertNotIn("verification-status", result)

    def test_unknown_status_fails_without_inventing_a_result(self) -> None:
        self.start([(201, {"run_id": "r1", "status": "QUEUED"}),
                    (200, {"run_id": "r1", "status": "FUTURE_STATE"})])
        process, result = self.run_action()
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertNotIn("verification-status", result)

    def test_missing_required_evidence_fails_closed(self) -> None:
        self.start([(201, {"run_id": "r1", "status": "QUEUED"}),
                    (200, {"run_id": "r1", "status": "SUCCEEDED"}), (404, {})])
        process, result = self.run_action(AO_VERIFICATION="required")
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["verification-status"], "UNAVAILABLE")

    def test_run_spec_file_is_submitted_without_a_prompt(self) -> None:
        self.start([(201, {"run_id": "r1", "status": "QUEUED"}),
                    (200, {"run_id": "r1", "status": "SUCCEEDED"})])
        spec = {"subtasks": [{"id": "a", "description": "spec input"}], "dependencies": []}
        (self.root / "spec.json").write_text(json.dumps(spec))
        process, _ = self.run_action(AO_PROMPT="", AO_SPEC_FILE="spec.json", AO_VERIFICATION="off")
        self.assertEqual(process.returncode, 0, process.stderr)
        assert self.server is not None
        self.assertEqual(json.loads(self.server.requests[0][3]), spec)

    def test_nonfinite_run_spec_rejected_before_submission(self) -> None:
        self.start([])
        (self.root / "spec.json").write_text('{"subtasks":[{"value":NaN}]}')
        process, _ = self.run_action(AO_PROMPT="", AO_SPEC_FILE="spec.json")
        self.assertNotEqual(process.returncode, 0)
        assert self.server is not None
        self.assertEqual(self.server.requests, [])

    def test_poll_deadline_preserves_id_without_cancelling_or_resubmitting(self) -> None:
        self.start([(201, {"run_id": "r1", "status": "QUEUED"}),
                    (200, {"run_id": "r1", "status": "RUNNING"})])
        process, result = self.run_action(AO_WAIT_TIMEOUT="1")
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(result["run-id"], "r1")
        self.assertEqual(result["status"], "RUNNING")
        self.assertIn("AdaptOrch run ID: r1", process.stdout)
        assert self.server is not None
        self.assertEqual([request[0] for request in self.server.requests], ["POST", "GET"])

    def test_generated_idempotency_key_is_the_key_sent_on_submission(self) -> None:
        self.start([(201, {"run_id": "r1", "status": "QUEUED"}),
                    (200, {"run_id": "r1", "status": "SUCCEEDED"})])
        process, result = self.run_action(AO_IDEMPOTENCY_KEY="", AO_VERIFICATION="off")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(str(uuid.UUID(result["idempotency-key"])), result["idempotency-key"])
        assert self.server is not None
        headers = {key.lower(): value for key, value in self.server.requests[0][2].items()}
        self.assertEqual(headers["idempotency-key"], result["idempotency-key"])

    def test_unsafe_inputs_are_rejected_before_submission(self) -> None:
        self.start([])
        (self.root / "report.json").write_text("keep")
        process, _ = self.run_action(AO_REPORT_FILE="report.json")
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual((self.root / "report.json").read_text(), "keep")
        assert self.server is not None
        self.assertEqual(self.server.requests, [])

    def test_outside_context_and_partial_provider_are_rejected(self) -> None:
        self.start([])
        process, _ = self.run_action(AO_CONTEXT_FILE="../outside")
        self.assertNotEqual(process.returncode, 0)
        self.output.write_text("")
        process, _ = self.run_action(AO_PROVIDER_KEY="")
        self.assertNotEqual(process.returncode, 0)
        assert self.server is not None
        self.assertEqual(self.server.requests, [])

    def test_unsafe_server_run_id_is_not_written_to_workflow_commands(self) -> None:
        self.start([(201, {"run_id": "r1\n::warning::injected", "status": "QUEUED"})])
        process, result = self.run_action()
        self.assertNotEqual(process.returncode, 0)
        self.assertNotIn("run-id", result)
        self.assertNotIn("injected", process.stdout + process.stderr + self.output.read_text())


if __name__ == "__main__":
    unittest.main()
