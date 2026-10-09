"""Real verifier -> hosted API/MCP -> hardened MCP -> SDK -> CLI, synthetic only."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from adaptorch.cloud_auth import CloudAuthService
from adaptorch.control_plane import ControlPlaneService, create_control_plane_app
from adaptorch.n8n_connector import build_n8n_node_output
from adaptorch.verification import CommandVerifier, SandboxLimits
from fastapi.testclient import TestClient

from adaptorch_client import AdaptOrchClient, ClientConfig, EvidenceReport, Run
from adaptorch_mcp.hardening import HardenedMCPServer
from adaptorch_mcp.output_schema import project_tool_output
from mcp_test_support import FakeBackend


@pytest.mark.parametrize("scenario", ["node_missing", "tool_missing", "pdf_ok", "content_fail"])
def test_actual_verifier_flows_through_every_public_surface_without_changing_failure(
    tmp_path: Path, scenario: str
) -> None:
    if scenario != "node_missing":
        node = shutil.which("node")
        if node is None:
            pytest.skip("optional Node project-helper integration")
        helper = str(files("adaptorch").joinpath("assets/pdf_tool_preflight.cjs"))
        if scenario == "tool_missing":
            source = f"require({json.dumps(helper)}).preflightPdfTool('pdftotext');"
        else:
            from fpdf import FPDF

            pdftotext = shutil.which("pdftotext", path="/usr/bin:/bin")
            if pdftotext is None:
                pytest.skip("optional Poppler PDF integration")
            (tmp_path / "pdftotext").symlink_to(pdftotext)
            pdf_path = tmp_path / "synthetic.pdf"
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.cell(text="SYNTHETIC PDF CONTENT")
            pdf.output(str(pdf_path))
            required = "WRONG_CONTENT" if scenario == "content_fail" else "SYNTHETIC PDF CONTENT"
            source = (
                f"const result=require({json.dumps(helper)}).runPdfTool("
                f"'pdftotext',[{json.dumps(str(pdf_path))},'-']); "
                f"if (!result.stdout.includes({json.dumps(required)})) "
                "throw new Error('actual PDF content assertion failed');"
            )
        command = shlex.join([node, "-e", source])
    else:
        command = "node --version"
    verifier = CommandVerifier(
        [command], environment={"PATH": str(tmp_path)},
        # RLIMIT_NPROC includes other hosted-runner threads under the same UID.
        # Let this synthetic Node fixture reach the child-tool check.
        sandbox_limits=SandboxLimits(max_memory_bytes=512 * 1024**3, max_processes=None),
    )
    outcome = verifier.verify_candidate(candidate="synthetic", candidate_index=0, candidates=["x"])
    passed = scenario == "pdf_ok"
    assert outcome.passed == passed and outcome.pass_rate == int(passed)
    assert outcome.failure_category == (
        None if passed else "command_not_found" if scenario == "node_missing" else "command_failed"
    )
    assert outcome.command_results[0].exit_code == (
        0 if passed else 127 if scenario == "node_missing" else 1
    )
    expected = outcome.to_payload().get("diagnostics", [])
    if scenario == "tool_missing":
        assert expected[0]["tool"] == "pdftotext"

    service = ControlPlaneService(
        artifact_root=tmp_path / "artifacts", state_path=tmp_path / "state.json",
        mark_abandoned_on_startup=False,
    )
    cloud = CloudAuthService()
    key, _ = cloud.create_api_key(tenant_id="synthetic-tenant", plan_level="starter")
    record = service.create_run(
        payload={"subtasks": [{"id": "synthetic", "description": "not executed"}]},
        tenant_id="synthetic-tenant",
    )
    record.status = "SUCCEEDED" if passed else "FAILED"
    record.result_status = "OK" if passed else "FAILED"
    record.diagnostics = {"verification": {"attempted": [outcome.to_payload()]}}
    raw_receipt = {"original": "synthetic-receipt", "status": "FAIL"}
    record.receipt = raw_receipt
    headers = {"Authorization": f"Bearer {key}"}
    with TestClient(create_control_plane_app(
        service=service, auth_token="test-admin", cloud_auth_service=cloud
    )) as http:
        # create_run returns a snapshot; mutate the stored synthetic record after
        # application startup, without scheduling any model execution.
        record = service._runs[record.run_id]
        record.status = "SUCCEEDED" if passed else "FAILED"
        record.result_status = "OK" if passed else "FAILED"
        record.diagnostics = {"verification": {"attempted": [outcome.to_payload()]}}
        record.receipt = raw_receipt
        with service._lock:
            service._persist_runs_unlocked()
        run_response = http.get(f"/v1/runs/{record.run_id}", headers=headers)
        evidence_response = http.get(f"/v1/runs/{record.run_id}/evidence", headers=headers)
        assert run_response.status_code == evidence_response.status_code == 200
        run_payload, evidence_payload = run_response.json(), evidence_response.json()
        assert (run_payload.get("verification_diagnostics") or []) == expected
        assert (evidence_payload.get("verification_diagnostics") or []) == expected
        assert evidence_payload["checks"][0]["status"] == ("PASSED" if passed else "FAILED")
        assert record.receipt == raw_receipt
        sdk_run = Run.from_payload(run_payload)
        sdk_evidence = EvidenceReport.from_payload(evidence_payload)
        assert (sdk_run.verification_diagnostics is not None) == bool(expected)
        assert sdk_evidence.verification_diagnostics == sdk_run.verification_diagnostics
        assert sdk_run.to_payload()["status"] == record.status

        hosted_response = http.post("/mcp", headers={"X-API-Key": key}, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "adaptorch_get_run", "arguments": {"run_id": record.run_id}},
        })
        assert hosted_response.status_code == 200
        hosted = json.loads(hosted_response.json()["result"]["content"][0]["text"])
        assert (hosted.get("verification_diagnostics") or []) == expected
        assert hosted["status"] == record.status and hosted["result_status"] == record.result_status

        class Backend(FakeBackend):
            def get_run(self, run_id: str) -> dict[str, Any]:
                assert run_id == record.run_id
                return hosted

        remote = HardenedMCPServer(backend=Backend(), exposure_profile="remote")
        message = remote.handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "adaptorch_get_run", "arguments": {"run_id": record.run_id}},
        })
        assert message is not None
        safe = json.loads(message["result"]["content"][0]["text"])
        assert (safe.get("verification_diagnostics") or []) == expected
        assert safe["status"] == record.status
        assert "diagnostics" not in safe and "telemetry" not in safe
        assert "test-secret" not in json.dumps(safe)
        assert command not in json.dumps(safe)
        collected = build_n8n_node_output(run_payload=run_payload)
        assert (collected.get("verification_diagnostics") or []) == expected
        projected_collection = project_tool_output("adaptorch_run", collected)
        assert projected_collection is not None
        assert (projected_collection.get("verification_diagnostics") or []) == expected

        # A loopback relay serves the actual hosted endpoint bytes to the standard-
        # library SDK and a separate real CLI process. No provider is called.
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                response = http.get(self.path, headers=headers)
                body = response.content
                if scenario == "content_fail":
                    # A buggy/new server's optional field must not break an
                    # otherwise valid failed run or leak values through CLI JSON.
                    malformed = response.json()
                    targets = malformed.get("items", [malformed])
                    for target in targets:
                        target["verification_diagnostics_schema_version"] = (
                            "verification.diagnostics/v1"
                        )
                        target["verification_diagnostics"] = [{
                            "code": "ENV_DEPENDENCY_MISSING", "source": "project_report",
                            "scope": "child_tool", "secret": "synthetic-reflected-secret",
                        }]
                    body = json.dumps(malformed).encode()
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        api_url = f"http://127.0.0.1:{server.server_port}"
        try:
            client = AdaptOrchClient(ClientConfig(api_url=api_url, api_key="synthetic-key"))
            assert client.get_run(record.run_id).verification_diagnostics == (
                sdk_run.verification_diagnostics
            )
            assert client.get_evidence(record.run_id).verification_diagnostics == (
                sdk_run.verification_diagnostics
            )
            env = {
                "PATH": os.defpath, "ADAPTORCH_API_KEY": "synthetic-key",
                "XDG_CONFIG_HOME": str(tmp_path / "config"), "HOME": str(tmp_path),
            }
            for args, expected_exit in [
                (["run", "get", record.run_id], 0 if passed else 8),
                (["run", "wait", record.run_id], 0 if passed else 8),
                (["evidence", "show", record.run_id], 0),
                (["run", "list"], 0),
            ]:
                completed = subprocess.run(
                    [sys.executable, "-m", "adaptorch_cli", "--api-url", api_url, *args],
                    env=env, capture_output=True, text=True, check=False, timeout=10,
                )
                assert completed.returncode == expected_exit, completed.stderr
                payload = json.loads(completed.stdout)
                if "run" in payload:
                    payload = payload["run"]
                if "items" in payload:
                    payload = payload["items"][0]
                assert (payload.get("verification_diagnostics") or []) == expected
                assert "synthetic-reflected-secret" not in completed.stdout
                assert completed.stderr == ""
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
