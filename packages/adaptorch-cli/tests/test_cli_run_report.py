from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from cli_test_support import CliRunner

_TOKEN = "adaptorch-report-placeholder"
_PDF = b"%PDF-1.7\nsynthetic report\n%%EOF\n"


class _ReportHandler(BaseHTTPRequestHandler):
    paths: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        self.paths.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(_PDF)))
        self.end_headers()
        self.wfile.write(_PDF)

    def log_message(self, format: str, *args: object) -> None:
        return


def _real_env() -> dict[str, str]:
    root = Path(__file__).parents[2]
    env = {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in {"all_proxy", "https_proxy", "http_proxy"}
    }
    env["PYTHONPATH"] = os.pathsep.join(
        (str(root / "adaptorch-cli" / "src"), str(root / "adaptorch-client" / "src"))
    )
    env["ADAPTORCH_API_KEY"] = _TOKEN
    return env


def test_run_report_writes_the_real_client_download_to_a_new_file(tmp_path: Path) -> None:
    out = tmp_path / "report.pdf"
    env = _real_env()
    env["ADAPTORCH_CONFIG_DIR"] = str(tmp_path / "config")
    with HTTPServer(("127.0.0.1", 0), _ReportHandler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "adaptorch_cli",
                    "--api-url",
                    f"http://127.0.0.1:{server.server_port}",
                    "run",
                    "report",
                    "run-real",
                    "--format",
                    "pdf",
                    "--locale",
                    "ko",
                    "--out",
                    str(out),
                ],
                check=False,
                capture_output=True,
                env=env,
                text=True,
                timeout=10,
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)

    assert completed.returncode == 0, completed.stderr
    assert _ReportHandler.paths == ["/v1/runs/run-real/report.pdf?locale=ko"]
    assert out.read_bytes() == _PDF
    summary = json.loads(completed.stdout)
    assert summary["path"] == str(out)
    assert summary["sha256"] == hashlib.sha256(_PDF).hexdigest()
    assert summary["format"] == "pdf"
    assert _TOKEN not in completed.stdout + completed.stderr


def test_run_report_defaults_to_json_and_reports_the_written_file(
    run_cli: CliRunner, tmp_path: Path
) -> None:
    out = tmp_path / "report.json"
    result = run_cli(["run", "report", "run-1", "--out", str(out)])
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == b'{"run":{"run_id":"run-1"}}'
    assert json.loads(result.stdout)["path"] == str(out)
    calls = [json.loads(line) for line in result.client_log.splitlines()]
    assert calls[-1] == {
        "args": ["run-1"],
        "kwargs": {"format": "json", "locale": None},
        "method": "get_run_report",
    }


def test_run_report_refuses_to_overwrite_before_any_request(
    run_cli: CliRunner, tmp_path: Path
) -> None:
    out = tmp_path / "report.pdf"
    out.write_bytes(b"keep me")
    result = run_cli(["run", "report", "run-1", "--format", "pdf", "--out", str(out)])
    assert result.returncode == 2
    assert "already exists" in result.stderr
    assert out.read_bytes() == b"keep me"
    assert "get_run_report" not in result.client_log


def test_run_report_rejects_locale_for_json(run_cli: CliRunner, tmp_path: Path) -> None:
    result = run_cli(
        ["run", "report", "run-1", "--locale", "ko", "--out", str(tmp_path / "r.json")]
    )
    assert result.returncode == 2
    assert "get_run_report" not in result.client_log
    assert not (tmp_path / "r.json").exists()


def test_run_report_api_failure_maps_exit_code_and_leaves_no_file(
    run_cli: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_CLIENT_ERROR", "conflict")
    out = tmp_path / "report.pdf"
    result = run_cli(["run", "report", "run-1", "--format", "pdf", "--out", str(out)])
    assert result.returncode == 5
    assert not out.exists()
