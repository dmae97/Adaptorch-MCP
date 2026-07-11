from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli_test_support import CliRunner

_SENSITIVE = "forbidden-cli-value"
_MAX_SUBMIT_BYTES = 8 * 1024 * 1024


def test_module_help_exposes_required_command_groups(run_cli: CliRunner) -> None:
    result = run_cli(["--help"])

    assert result.returncode == 0
    for command in ("auth", "config", "whoami", "capabilities", "run", "evidence", "artifact"):
        assert command in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["--token", _SENSITIVE, "whoami"],
        [f"--token={_SENSITIVE}", "whoami"],
        [f"--token{_SENSITIVE}", "whoami"],
        ["--api-key", _SENSITIVE, "whoami"],
        [f"--api-key={_SENSITIVE}", "whoami"],
        [f"--api-key{_SENSITIVE}", "whoami"],
        ["run", "get", f"--token{_SENSITIVE}"],
    ],
)
def test_credential_argv_tokens_are_rejected_without_echoing(
    run_cli: CliRunner,
    argv: list[str],
) -> None:
    result = run_cli(argv)

    assert result.returncode == 2
    assert result.stdout == ""
    assert _SENSITIVE not in result.stderr
    assert _SENSITIVE not in result.stdout
    assert result.stderr
    assert result.client_log == ""


def test_credentialed_api_url_is_rejected_without_leaking_config_get(
    run_cli: CliRunner,
) -> None:
    result = run_cli(
        ["--api-url", "https://user:hunter2secret@api.example.test", "config", "get"]
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "hunter2secret" not in result.stderr
    assert "api.example.test" not in result.stderr
    assert result.stderr
    assert result.client_log == ""


@pytest.mark.parametrize(
    "api_url",
    [
        "ftp://api.example.test",
        "http://api.example.test",
        "https://api.example.test/path",
        "https://api.example.test?query=1",
        "not a url",
        "",
    ],
)
def test_invalid_api_url_is_usage_error_before_any_output(
    run_cli: CliRunner,
    api_url: str,
) -> None:
    result = run_cli(["--api-url", api_url, "config", "get"])

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr
    assert result.client_log == ""


def test_authenticated_command_requires_environment_token(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADAPTORCH_API_KEY")

    result = run_cli(["--output", "json", "whoami"])

    assert result.returncode == 3
    assert result.stdout == ""
    assert result.stderr


@pytest.mark.parametrize(
    "input_text",
    [
        pytest.param("not-json\n", id="invalid-json"),
        pytest.param('["not-an-object"]\n', id="non-object-json"),
        pytest.param('{"a": NaN}\n', id="nan-literal"),
        pytest.param('{"a": Infinity}\n', id="infinity-literal"),
        pytest.param('{"a": -Infinity}\n', id="negative-infinity-literal"),
        pytest.param('{"a": 1e999}\n', id="overflowing-float"),
        pytest.param('{"a":' + "[" * 100_000 + "]" * 100_000 + "}", id="too-deep-nesting"),
    ],
)
def test_rejected_submit_payloads_are_usage_errors(
    run_cli: CliRunner,
    input_text: str,
) -> None:
    result = run_cli(["--output", "json", "run", "submit", "--file", "-"], input_text)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr
    assert result.client_log == ""


def test_invalid_request_id_is_usage_error(run_cli: CliRunner) -> None:
    result = run_cli(
        [
            "run",
            "submit",
            "--file",
            "-",
            "--request-id",
            "x" * 201,
        ],
        '{"goal":"verify"}',
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr
    calls = [json.loads(line) for line in result.client_log.splitlines()]
    assert [call["method"] for call in calls] == ["init"]


def test_oversized_submit_stdin_is_usage_error(run_cli: CliRunner) -> None:
    oversized = '{"goal":"' + "x" * _MAX_SUBMIT_BYTES + '"}'

    result = run_cli(["--output", "json", "run", "submit", "--file", "-"], oversized)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr
    assert result.client_log == ""


def test_oversized_submit_file_is_usage_error(run_cli: CliRunner, tmp_path: Path) -> None:
    request_path = tmp_path / "oversized.json"
    request_path.write_bytes(b'{"goal":"' + b"x" * _MAX_SUBMIT_BYTES + b'"}')

    result = run_cli(
        ["--output", "json", "run", "submit", "--file", str(request_path)]
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr
    assert result.client_log == ""


def test_submit_at_size_limit_is_accepted(run_cli: CliRunner) -> None:
    padding = "x" * (_MAX_SUBMIT_BYTES - len('{"goal":""}'))

    result = run_cli(
        ["--output", "json", "run", "submit", "--file", "-"],
        '{"goal":"' + padding + '"}',
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"id": "run-1", "status": "QUEUED"}


@pytest.mark.parametrize(
    ("fake_error", "expected_code"),
    [
        ("auth", 3),
        ("not_found", 4),
        ("conflict", 5),
        ("rate_limit", 6),
        ("transport", 7),
        ("api", 7),
    ],
)
def test_client_errors_map_to_stable_exit_codes(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    fake_error: str,
    expected_code: int,
) -> None:
    monkeypatch.setenv("FAKE_CLIENT_ERROR", fake_error)

    result = run_cli(["--output", "json", "whoami"])

    assert result.returncode == expected_code
    assert result.stdout == ""
    assert result.stderr
    assert "env-test-key" not in result.stderr


@pytest.mark.parametrize("status", ["FAILED", "failed"])
def test_failed_run_maps_to_exit_8(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    monkeypatch.setenv("FAKE_RUN_STATUS", status)

    result = run_cli(["--output", "json", "run", "get", "run-1"])

    assert result.returncode == 8
    assert json.loads(result.stdout) == {"id": "run-1", "status": status}
    assert result.stderr == ""


def test_cancelled_run_maps_to_exit_9(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_RUN_STATUS", "CANCELLED")

    result = run_cli(["--output", "json", "run", "get", "run-1"])

    assert result.returncode == 9
    assert json.loads(result.stdout) == {"id": "run-1", "status": "CANCELLED"}
    assert result.stderr == ""


@pytest.mark.parametrize("status", ["INCONCLUSIVE", "Inconclusive", "inconclusive"])
def test_inconclusive_run_maps_to_exit_10(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    monkeypatch.setenv("FAKE_RUN_STATUS", status)

    result = run_cli(["--output", "json", "run", "get", "run-1"])

    assert result.returncode == 10
    assert json.loads(result.stdout) == {"id": "run-1", "status": status}
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [("Failed", 8), ("cancelled", 9), ("INCONCLUSIVE", 10), ("RUNNING", 0)],
)
def test_data_wrapped_run_status_maps_case_insensitively(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected_code: int,
) -> None:
    monkeypatch.setenv("FAKE_RUN_STATUS", status)
    monkeypatch.setenv("FAKE_RUN_WRAP", "data")

    result = run_cli(["--output", "json", "run", "get", "run-1"])

    assert result.returncode == expected_code
    assert json.loads(result.stdout) == {"data": {"id": "run-1", "status": status}}
    assert result.stderr == ""


def test_keyboard_interrupt_maps_to_exit_130(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_CLIENT_ERROR", "interrupt")

    result = run_cli(["--output", "json", "whoami"])

    assert result.returncode == 130
    assert result.stdout == ""
    assert result.stderr
