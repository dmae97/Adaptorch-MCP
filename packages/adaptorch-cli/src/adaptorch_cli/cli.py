from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Never, Protocol, TypeAlias

from adaptorch_client import (
    AdaptOrchAPIError,
    AdaptOrchClient,
    ClientConfig,
    PollPolicy,
    ProviderCredential,
    validate_api_url,
)

from adaptorch_cli import config_store
from adaptorch_cli.parser import build_parser, parse_args

JSONValue: TypeAlias = bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"] | None
JSONMapping: TypeAlias = dict[str, JSONValue]

_MAX_SUBMIT_BYTES = 8 * 1024 * 1024


class PayloadResult(Protocol):
    def to_payload(self) -> JSONMapping: ...


def _write_json(payload: JSONMapping) -> None:
    print(json.dumps(payload, allow_nan=False, sort_keys=True, separators=(",", ":")))


def _reject_json_constant(_value: str) -> Never:
    raise ValueError("non-finite JSON number")


def _finite_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        _reject_json_constant(text)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def _validated_api_url(api_url: str, parser: argparse.ArgumentParser) -> str:
    try:
        return validate_api_url(api_url)
    except ValueError:
        parser.error(
            "invalid --api-url: expected an https:// origin (or exact loopback http://)"
            " without credentials, path, query, or fragment"
        )


def _read_submit_bytes(file_name: str, parser: argparse.ArgumentParser) -> bytes:
    try:
        if file_name == "-":
            return sys.stdin.buffer.read(_MAX_SUBMIT_BYTES + 1)
        with Path(file_name).open("rb") as stream:
            return stream.read(_MAX_SUBMIT_BYTES + 1)
    except OSError:
        parser.error("submit input must be a readable JSON object")


def _read_submit_payload(file_name: str, parser: argparse.ArgumentParser) -> JSONMapping:
    raw = _read_submit_bytes(file_name, parser)
    if len(raw) > _MAX_SUBMIT_BYTES:
        parser.error("submit input exceeds the 8 MiB limit")
    try:
        value: JSONValue = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            parse_float=_finite_float,
        )
    # pi-lens-ignore: unreachable-except
    except RecursionError:
        parser.error("submit input JSON is too deeply nested")
    except ValueError:
        parser.error("submit input must be a readable JSON object")
    if not isinstance(value, dict):
        parser.error("submit input must be a JSON object")
    return value


def _require_client(api_url: str) -> AdaptOrchClient:
    api_key, _source = config_store.resolve_api_key()
    if not api_key:
        print(
            "authentication required: run `adaptorchctl auth login` or set ADAPTORCH_API_KEY",
            file=sys.stderr,
        )
        raise SystemExit(3)
    return AdaptOrchClient(ClientConfig(api_url=api_url, api_key=api_key))


def _submission_credential() -> ProviderCredential | None:
    resolved, source = config_store.resolve_provider_credential()
    if resolved is None:
        return None
    provider, model, key = resolved
    auth_type, account_id = config_store.resolve_provider_auth(source)
    if auth_type is None and account_id is None:
        return ProviderCredential(provider, model, key)
    return ProviderCredential(provider, model, key, auth_type=auth_type, account_id=account_id)


def _read_secret(prompt: str, *, stdin_flag: bool) -> str:
    """Read a secret from stdin (piped or --value-stdin) or a hidden prompt.

    Never echoed: values on argv are rejected upstream by _CREDENTIAL_FLAGS.
    """
    if stdin_flag or not sys.stdin.isatty():
        value = sys.stdin.read().strip()
    else:
        import getpass

        value = getpass.getpass(prompt).strip()
    return value


def _result_payload(result: PayloadResult) -> JSONMapping:
    return result.to_payload()


def _auth_command(
    args: argparse.Namespace,
    api_url: str,
    parser: argparse.ArgumentParser,
) -> JSONMapping:
    sub: str = args.auth_command
    if sub == "status":
        api_key, source = config_store.resolve_api_key()
        return {
            "authenticated": api_key is not None,
            "credential_source": source,
            "api_url": api_url,
        }
    if sub == "logout":
        removed = config_store.clear_credentials()
        return {"logged_out": True, "removed_stored_key": removed}
    if sub == "login":
        login_url = getattr(args, "login_api_url", None) or api_url
        try:
            login_url = validate_api_url(login_url)
        except ValueError:
            parser.error(
                "invalid --api-url: expected an https:// origin (or exact loopback http://)"
            )
        key = _read_secret("AdaptOrch API key: ", stdin_flag=False)
        if not key:
            parser.error("no API key provided on stdin or at the prompt")
        verified: bool | None = None
        if not args.no_verify:
            try:
                whoami = AdaptOrchClient(ClientConfig(api_url=login_url, api_key=key)).whoami()
                verified = True
                _ = whoami
            except AdaptOrchAPIError as error:
                print(
                    f"login verification failed (HTTP {error.status_code}); "
                    "key not saved. Retry with --no-verify to store anyway.",
                    file=sys.stderr,
                )
                raise SystemExit(3) from error
        config_store.store_credentials(api_key=key, api_url=login_url)
        return {
            "logged_in": True,
            "api_url": login_url,
            "verified": bool(verified),
            "config_path": str(config_store.config_path()),
        }
    parser.error("unknown auth command")


def _config_command(
    args: argparse.Namespace,
    api_url: str,
    parser: argparse.ArgumentParser,
) -> JSONMapping:
    sub: str = args.config_command
    if sub == "get":
        view = config_store.config_view()
        view["api_url"] = api_url
        return view
    if sub == "set":
        key: str = args.key
        if key not in config_store.configurable_keys():
            parser.error(
                "unknown config key; expected one of: "
                + ", ".join(config_store.configurable_keys())
            )
        value = getattr(args, "value", None)
        if config_store.is_secret_key(key):
            if value is not None:
                parser.error(f"{key} is a secret; pass it via --value-stdin or a piped stdin")
            value = _read_secret("Value: ", stdin_flag=args.value_stdin)
        elif args.value_stdin:
            value = sys.stdin.read().strip()
        elif value is None:
            parser.error("config set requires a value (or --value-stdin)")
        if key == "api_url":
            try:
                value = validate_api_url(value)
            except ValueError:
                parser.error(
                    "invalid api_url: expected an https:// origin (or exact loopback http://)"
                )
        config_store.set_config_value(key, value)
        return {"set": key, "config_path": str(config_store.config_path())}
    if sub == "unset":
        removed = config_store.unset_config_value(args.key)
        return {"unset": args.key, "removed": removed}
    parser.error("unknown config command")


def _run_command(
    args: argparse.Namespace,
    api_url: str,
    parser: argparse.ArgumentParser,
) -> tuple[JSONMapping, bool]:
    command: str = args.run_command
    match command:
        case "submit":
            file_name: str = args.file
            request_id: str | None = args.request_id
            payload = _read_submit_payload(file_name, parser)
            submit_result = _require_client(api_url).submit_run(
                payload,
                idempotency_key=request_id or str(uuid.uuid4()),
                provider_credential=_submission_credential(),
            )
            return _result_payload(submit_result), False
        case "list":
            status: str | None = args.status
            project_id: str | None = args.project_id
            list_result = _require_client(api_url).list_runs(
                status=status,
                project_id=project_id,
            )
            return _result_payload(list_result), False
        case "get":
            run_id: str = args.run_id
            return _result_payload(_require_client(api_url).get_run(run_id)), True
        case "wait":
            wait_run_id: str = args.run_id
            timeout_seconds: float = args.timeout
            interval_seconds: float = args.interval
            if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
                parser.error("--timeout must be finite positive seconds")
            if not math.isfinite(interval_seconds) or interval_seconds <= 0:
                parser.error("--interval must be finite positive seconds")
            wait_result = _require_client(api_url).wait_for_run(
                wait_run_id,
                policy=PollPolicy(
                    timeout_seconds=timeout_seconds, interval_seconds=interval_seconds
                ),
            )
            wait_payload: dict[str, JSONValue] = {
                "reason": wait_result.reason.value,
                "polls": wait_result.polls,
                "elapsed_seconds": wait_result.elapsed_seconds,
            }
            if wait_result.run is not None:
                wait_payload["run"] = wait_result.run.to_payload()
            return wait_payload, True
        case "cancel":
            cancel_run_id: str = args.run_id
            reason: str | None = args.reason
            cancel_result = _require_client(api_url).cancel_run(
                cancel_run_id,
                reason=reason,
            )
            return _result_payload(cancel_result), False
        case _:
            parser.error("unknown run command")


def _execute(
    args: argparse.Namespace,
    api_url: str,
    parser: argparse.ArgumentParser,
) -> tuple[JSONMapping, bool]:
    command: str = args.command
    match command:
        case "auth":
            return _auth_command(args, api_url, parser), False
        case "config":
            return _config_command(args, api_url, parser), False
        case "whoami":
            return _result_payload(_require_client(api_url).whoami()), False
        case "capabilities":
            return _result_payload(_require_client(api_url).capabilities()), False
        case "run":
            return _run_command(args, api_url, parser)
        case "evidence":
            evidence_run_id: str = args.run_id
            return _result_payload(_require_client(api_url).get_evidence(evidence_run_id)), False
        case "artifact":
            artifact_run_id: str = args.run_id
            return _result_payload(_require_client(api_url).list_artifacts(artifact_run_id)), False
        case _:
            parser.error("unknown command")


def _api_exit_code(error: AdaptOrchAPIError) -> int:
    status_code = error.status_code
    if status_code in {401, 403}:
        return 3
    if status_code == 404:
        return 4
    if status_code == 409:
        return 5
    if status_code == 429:
        return 6
    if status_code is None or 500 <= status_code <= 599:
        return 7
    return 10


def _payload_status(payload: JSONMapping) -> str:
    status = payload.get("status")
    if isinstance(status, str):
        return status
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("status")
        if isinstance(nested, str):
            return nested
    return ""


def _run_status_exit(payload: JSONMapping) -> int:
    normalized = _payload_status(payload).lower()
    if normalized == "failed":
        return 8
    if normalized == "cancelled":
        return 9
    if normalized == "inconclusive":
        return 10
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parse_args(argv)
    flag_url = getattr(args, "api_url", None)
    if flag_url is not None and not flag_url.strip():
        parser.error("invalid --api-url: expected an https:// origin (or exact loopback http://)")
    resolved_url, _url_source = config_store.resolve_api_url(flag_url)
    api_url = _validated_api_url(resolved_url, parser)
    try:
        payload, check_run_status = _execute(args, api_url, parser)
        try:
            _write_json(payload)
        except ValueError:
            print("response contained non-encodable JSON values", file=sys.stderr)
            return 7
        return _run_status_exit(payload) if check_run_status else 0
    # pi-lens-ignore: unreachable-except
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    # pi-lens-ignore: unreachable-except
    except AdaptOrchAPIError as error:
        code = _api_exit_code(error)
        print(f"request failed (HTTP {error.status_code})", file=sys.stderr)
        return code
    except ValueError:
        parser.error("invalid CLI input")


def entrypoint() -> None:
    raise SystemExit(main())
