from __future__ import annotations

import argparse
import json
import math
import os
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Never, Protocol, TypeAlias

from adaptorch_client import (
    AdaptOrchAPIError,
    AdaptOrchClient,
    ClientConfig,
    validate_api_url,
)

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
    value = float(text)
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
    except RecursionError:
        parser.error("submit input JSON is too deeply nested")
    except ValueError:
        parser.error("submit input must be a readable JSON object")
    if not isinstance(value, dict):
        parser.error("submit input must be a JSON object")
    return value


def _require_client(api_url: str) -> AdaptOrchClient:
    api_key = os.environ.get("ADAPTORCH_API_KEY")
    if not api_key:
        print("authentication required: set ADAPTORCH_API_KEY", file=sys.stderr)
        raise SystemExit(3)
    return AdaptOrchClient(ClientConfig(api_url=api_url, api_key=api_key))


def _result_payload(result: PayloadResult) -> JSONMapping:
    return result.to_payload()


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
            return {"authenticated": bool(os.environ.get("ADAPTORCH_API_KEY"))}, False
        case "config":
            return {"api_url": api_url}, False
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
    api_url = _validated_api_url(str(args.api_url), parser)
    try:
        payload, check_run_status = _execute(args, api_url, parser)
        try:
            _write_json(payload)
        except ValueError:
            print("response contained non-encodable JSON values", file=sys.stderr)
            return 7
        return _run_status_exit(payload) if check_run_status else 0
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except AdaptOrchAPIError as error:
        code = _api_exit_code(error)
        print(f"request failed (HTTP {error.status_code})", file=sys.stderr)
        return code
    except ValueError:
        parser.error("invalid CLI input")


def entrypoint() -> None:
    raise SystemExit(main())
