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
            "not-a-uuid",
        ],
        '{"goal":"verify"}',
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr
    assert result.client_log == ""


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


def test_closed_stdout_pipe_does_not_crash_the_command(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    fake_root = tmp_path / "fake"
    (fake_root / "adaptorch_client").mkdir(parents=True)
    from cli_test_support import _FAKE_CLIENT

    (fake_root / "adaptorch_client" / "__init__.py").write_text(_FAKE_CLIENT, encoding="utf-8")
    source_root = Path(__file__).parents[1] / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(fake_root), str(source_root))),
        "FAKE_CLIENT_LOG": str(tmp_path / "client.jsonl"),
        "ADAPTORCH_API_KEY": "env-test-key",
        "ADAPTORCH_CONFIG_DIR": str(tmp_path / "config"),
        "FAKE_RUN_STATUS": "FAILED",
    }
    read_end, write_end = os.pipe()
    os.close(read_end)  # the consumer is already gone, like `| head` after its lines
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "adaptorch_cli", "run", "get", "run-1"],
            stdout=write_end,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
            text=True,
            timeout=30,
        )
    finally:
        os.close(write_end)

    assert completed.returncode == 8
    assert "Traceback" not in completed.stderr
    assert "BrokenPipeError" not in completed.stderr


def test_network_failure_message_names_the_missing_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from adaptorch_client import AdaptOrchAPIError

    from adaptorch_cli import cli

    def fail(*_args: object) -> tuple[cli.JSONMapping, bool]:
        raise AdaptOrchAPIError("AdaptOrch network request failed")

    monkeypatch.setattr(cli, "_execute", fail)
    monkeypatch.setenv("ADAPTORCH_CONFIG_DIR", str(tmp_path / "isolated-config"))

    assert cli.main(["whoami"]) == 7
    err = capsys.readouterr().err
    assert "no HTTP response" in err
    assert "HTTP None" not in err
