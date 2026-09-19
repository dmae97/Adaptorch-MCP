from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from cli_test_support import CliRunner


def _json_stdout(result_stdout: str) -> dict[str, object]:
    assert result_stdout.count("\n") == 1
    parsed = json.loads(result_stdout)
    assert isinstance(parsed, dict)
    return parsed


def _config_file(config_dir: Path) -> Path:
    return config_dir / "config.json"


def test_auth_login_persists_key_with_0600_and_verifies(
    run_cli: CliRunner,
) -> None:
    result = run_cli(
        ["--output", "json", "auth", "login"],
        "stored-login-key\n",
    )

    assert result.returncode == 0
    payload = _json_stdout(result.stdout)
    assert payload["logged_in"] is True
    assert payload["verified"] is True
    assert payload["api_url"] == "https://adaptorch.com"
    assert "stored-login-key" not in result.stdout
    assert result.stderr == ""

    config_path = Path(str(payload["config_path"]))
    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored["api_key"] == "stored-login-key"
    assert stored["api_url"] == "https://adaptorch.com"
    mode = stat.S_IMODE(config_path.stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_auth_login_then_whoami_uses_stored_key_without_env(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = run_cli(["auth", "login"], "stored-login-key\n")
    assert login.returncode == 0

    monkeypatch.delenv("ADAPTORCH_API_KEY")
    result = run_cli(["--output", "json", "whoami"])

    assert result.returncode == 0
    calls = [json.loads(line) for line in result.client_log.splitlines()]
    assert calls[0] == {
        "args": ["https://adaptorch.com", "stored-login-key"],
        "kwargs": {},
        "method": "init",
    }
    assert "stored-login-key" not in result.stdout


def test_env_key_wins_over_stored_key(
    run_cli: CliRunner,
) -> None:
    login = run_cli(["auth", "login"], "stored-login-key\n")
    assert login.returncode == 0

    result = run_cli(["--output", "json", "auth", "status"])

    payload = _json_stdout(result.stdout)
    assert payload["credential_source"] == "env"
    calls = (
        [json.loads(line) for line in result.client_log.splitlines()] if result.client_log else []
    )
    for call in calls:
        assert "stored-login-key" not in json.dumps(call)


def test_auth_logout_removes_stored_key(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = run_cli(["auth", "login"], "stored-login-key\n")
    assert login.returncode == 0

    result = run_cli(["--output", "json", "auth", "logout"])
    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {
        "logged_out": True,
        "removed_stored_key": True,
    }

    monkeypatch.delenv("ADAPTORCH_API_KEY")
    status = run_cli(["--output", "json", "auth", "status"])
    assert _json_stdout(status.stdout)["credential_source"] == "none"
    assert _json_stdout(status.stdout)["authenticated"] is False


def test_auth_logout_without_login_is_idempotent(run_cli: CliRunner) -> None:
    result = run_cli(["--output", "json", "auth", "logout"])

    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {
        "logged_out": True,
        "removed_stored_key": False,
    }


def test_auth_login_failed_verification_does_not_store(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_CLIENT_ERROR", "auth")

    result = run_cli(["auth", "login"], "bad-key\n")

    assert result.returncode == 3
    assert result.stdout == ""
    assert "bad-key" not in result.stderr
    config_dir = Path(os.environ["ADAPTORCH_CONFIG_DIR"])
    assert not _config_file(config_dir).exists()


def test_auth_login_no_verify_stores_without_network(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_CLIENT_ERROR", "transport")

    result = run_cli(["auth", "login", "--no-verify"], "offline-key\n")

    assert result.returncode == 0
    payload = _json_stdout(result.stdout)
    assert payload["logged_in"] is True
    assert payload["verified"] is False
    assert result.client_log == ""  # no whoami call was made


def test_auth_login_persists_flag_api_url(run_cli: CliRunner) -> None:
    result = run_cli(
        ["--api-url", "https://api.example.test", "auth", "login"],
        "stored-login-key\n",
    )

    assert result.returncode == 0
    payload = _json_stdout(result.stdout)
    assert payload["api_url"] == "https://api.example.test"
    calls = [json.loads(line) for line in result.client_log.splitlines()]
    assert calls[0]["args"][0] == "https://api.example.test"


def test_config_set_and_get_provider_model(
    run_cli: CliRunner,
) -> None:
    result = run_cli(["config", "set", "provider.model", "deepseek/deepseek-v4.1-flash"])
    assert result.returncode == 0
    assert _json_stdout(result.stdout)["set"] == "provider.model"

    result = run_cli(["--output", "json", "config", "get"])
    payload = _json_stdout(result.stdout)
    provider = payload["provider"]
    assert isinstance(provider, dict)
    assert provider["model"] == "deepseek/deepseek-v4.1-flash"


def test_config_set_provider_secret_requires_stdin(
    run_cli: CliRunner,
) -> None:
    rejected = run_cli(["config", "set", "provider.api_key", "sk-on-argv"])
    assert rejected.returncode == 2
    assert "sk-on-argv" not in rejected.stderr

    accepted = run_cli(
        ["config", "set", "provider.api_key", "--value-stdin"],
        "sk-from-stdin\n",
    )
    assert accepted.returncode == 0
    assert "sk-from-stdin" not in accepted.stdout

    view = run_cli(["--output", "json", "config", "get"])
    provider = _json_stdout(view.stdout)["provider"]
    assert isinstance(provider, dict)
    assert provider["api_key"] != "sk-from-stdin"
    assert provider["api_key"].startswith("sk-f")
    assert "sk-from-stdin" not in view.stdout


def test_stored_provider_credential_flows_into_submit(
    run_cli: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in (
        ("provider.name", "openrouter"),
        ("provider.model", "openrouter/google/gemini-3.8-flash"),
    ):
        result = run_cli(["config", "set", key, value])
        assert result.returncode == 0
    secret = run_cli(
        ["config", "set", "provider.api_key", "--value-stdin"],
        "provider-secret\n",
    )
    assert secret.returncode == 0

    for env_key in (
        "ADAPTORCH_PROVIDER",
        "ADAPTORCH_PROVIDER_MODEL",
        "ADAPTORCH_PROVIDER_API_KEY",
    ):
        monkeypatch.delenv(env_key, raising=False)

    request_path = tmp_path / "request.json"
    request_path.write_text('{"goal":"wire provider"}\n', encoding="utf-8")
    result = run_cli(["--output", "json", "run", "submit", "--file", str(request_path)])

    assert result.returncode == 0
    calls = [json.loads(line) for line in result.client_log.splitlines()]
    submit = calls[-1]
    assert submit["method"] == "submit_run"
    assert submit["kwargs"]["provider_credential"] == {
        "provider": "openrouter",
        "model": "openrouter/google/gemini-3.8-flash",
        "api_key": "provider-secret",
    }
    assert "provider-secret" not in result.stdout


def test_env_provider_overrides_stored_provider(
    run_cli: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_cli(["config", "set", "provider.model", "stored-model"]).returncode == 0
    monkeypatch.setenv("ADAPTORCH_PROVIDER_MODEL", "env-model")

    request_path = tmp_path / "request.json"
    request_path.write_text('{"goal":"env wins"}\n', encoding="utf-8")
    result = run_cli(["--output", "json", "run", "submit", "--file", str(request_path)])

    assert result.returncode == 0
    calls = [json.loads(line) for line in result.client_log.splitlines()]
    credential = calls[-1]["kwargs"]["provider_credential"]
    assert credential["model"] == "env-model"
    assert credential["provider"] == ""
    assert credential["api_key"] == ""


def test_config_unset_removes_key(
    run_cli: CliRunner,
) -> None:
    assert run_cli(["config", "set", "provider.model", "m"]).returncode == 0

    result = run_cli(["--output", "json", "config", "unset", "provider.model"])
    assert result.returncode == 0
    assert _json_stdout(result.stdout) == {"unset": "provider.model", "removed": True}

    view = run_cli(["--output", "json", "config", "get"])
    provider = _json_stdout(view.stdout)["provider"]
    assert isinstance(provider, dict)
    assert provider["model"] is None


def test_config_set_rejects_unknown_key(run_cli: CliRunner) -> None:
    result = run_cli(["config", "set", "bogus.key", "x"])

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr


def test_config_set_api_url_is_validated(run_cli: CliRunner) -> None:
    result = run_cli(["config", "set", "api_url", "not a url"])

    assert result.returncode == 2
    assert result.stdout == ""

    ok = run_cli(["config", "set", "api_url", "https://api.example.test"])
    assert ok.returncode == 0
    view = run_cli(["--output", "json", "config", "get"])
    assert _json_stdout(view.stdout)["api_url"] == "https://api.example.test"


def test_login_key_never_leaks_to_stdout_or_stderr(
    run_cli: CliRunner,
) -> None:
    secret = "sk-live-should-not-echo-9f8e7d"
    result = run_cli(["auth", "login"], f"{secret}\n")

    assert result.returncode == 0
    assert secret not in result.stdout
    assert secret not in result.stderr

    status = run_cli(["--output", "json", "auth", "status"])
    assert secret not in status.stdout
    view = run_cli(["--output", "json", "config", "get"])
    assert secret not in view.stdout
