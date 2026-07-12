from __future__ import annotations

import json
from pathlib import Path

from cli_test_support import CliRunner


def _json_stdout(result_stdout: str) -> dict[str, object]:
    assert result_stdout.count("\n") == 1
    parsed = json.loads(result_stdout)
    assert isinstance(parsed, dict)
    return parsed


def test_auth_status_reads_environment_only(run_cli: CliRunner) -> None:
    result = run_cli(["--output", "json", "auth", "status"])

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {"authenticated": True}
    assert result.stderr == ""
    assert "env-test-key" not in result.stdout


def test_config_get_reports_global_api_url(run_cli: CliRunner) -> None:
    result = run_cli(
        ["--api-url", "https://api.example.test", "--output", "json", "config", "get"]
    )

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {"api_url": "https://api.example.test"}
    assert result.stderr == ""


def test_whoami_uses_global_api_url_and_environment_token(run_cli: CliRunner) -> None:
    result = run_cli(
        ["--api-url", "https://api.example.test", "--output", "json", "whoami"]
    )

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {"email": "user@example.test", "id": "user-1"}
    assert result.stderr == ""
    calls = [json.loads(line) for line in result.client_log.splitlines()]
    assert calls[0] == {
        "args": ["https://api.example.test", "env-test-key"],
        "kwargs": {},
        "method": "init",
    }


def test_capabilities_prints_client_json(run_cli: CliRunner) -> None:
    result = run_cli(["--output", "json", "capabilities"])

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {
        "capabilities": ["runs", "evidence", "artifacts"]
    }
    assert result.stderr == ""


def test_run_submit_reads_json_file_and_forwards_request_id(
    run_cli: CliRunner,
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text('{"goal":"verify release"}\n', encoding="utf-8")

    result = run_cli(
        [
            "--output",
            "json",
            "run",
            "submit",
            "--file",
            str(request_path),
            "--request-id",
            "11111111-1111-4111-8111-111111111111",
        ]
    )

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {"id": "run-1", "status": "QUEUED"}
    calls = [json.loads(line) for line in result.client_log.splitlines()]
    assert calls[-1] == {
        "args": [{"goal": "verify release"}],
        "kwargs": {"idempotency_key": "11111111-1111-4111-8111-111111111111"},
        "method": "submit_run",
    }


def test_run_submit_reads_json_from_stdin(run_cli: CliRunner) -> None:
    result = run_cli(
        ["--output", "json", "run", "submit", "--file", "-"],
        '{"goal":"from stdin"}\n',
    )

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {"id": "run-1", "status": "QUEUED"}
    calls = [json.loads(line) for line in result.client_log.splitlines()]
    assert calls[-1]["args"] == [{"goal": "from stdin"}]


def test_run_list_prints_client_json(run_cli: CliRunner) -> None:
    result = run_cli(["--output", "json", "run", "list"])

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {
        "runs": [{"id": "run-1", "status": "QUEUED"}]
    }


def test_run_get_prints_client_json(run_cli: CliRunner) -> None:
    result = run_cli(["--output", "json", "run", "get", "run-1"])

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {"id": "run-1", "status": "RUNNING"}


def test_run_cancel_prints_client_json(run_cli: CliRunner) -> None:
    result = run_cli(["--output", "json", "run", "cancel", "run-1"])

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {"id": "run-1", "status": "CANCELLED"}


def test_evidence_show_prints_client_json(run_cli: CliRunner) -> None:
    result = run_cli(["--output", "json", "evidence", "show", "run-1"])

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {
        "evidence": [{"kind": "test", "run_id": "run-1"}]
    }


def test_artifact_list_prints_client_json(run_cli: CliRunner) -> None:
    result = run_cli(["--output", "json", "artifact", "list", "run-1"])

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {
        "artifacts": [{"name": "result.json", "run_id": "run-1"}]
    }
