"""One-attempt HTTP boundary; task, polling and collection stay engine-owned.

Compatibility dependencies: n8n_connector._quota_exceeded_usage owns quota
classification/projection; _redact_connector_secrets masks its string values.
Neither the parent's unbounded body readers nor its retry loop are called.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from http.client import HTTPException
from typing import Any, Final, NoReturn
from urllib import parse, request
from urllib.error import HTTPError

from adaptorch.connector_stability import caller_fixable_status
from adaptorch.control_plane.request_credential import KEY_HEADER, MODEL_HEADER, PROVIDER_HEADER
from adaptorch.n8n_connector import (
    N8nConnectorError,
    N8nControlPlaneConnector,
    N8nHttpError,
    N8nQuotaExceededError,
    _quota_exceeded_usage,
    _redact_connector_secrets,
)

from adaptorch_mcp.response_json import within_json_depth

_MAX_JSON_BYTES: Final = 8 * 1024 * 1024
_SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})


def _reject_constant(value: str) -> NoReturn:
    raise ValueError("Non-finite JSON number")


def _finite_float(value: str) -> float:
    # json routes only syntactically valid float tokens here, but an invalid one
    # must still fail closed as a rejected number rather than escape as a
    # different exception type the caller does not catch.
    try:
        number = float(value)
    except ValueError:
        _reject_constant(value)
    if not math.isfinite(number):
        _reject_constant(value)
    return number


# Any is restricted to the inherited engine JSON contract, not domain logic.
def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON key")
    return result


def _json_object(raw: bytes) -> dict[str, Any]:
    if len(raw) > _MAX_JSON_BYTES:
        raise N8nConnectorError("Control-plane response exceeds 8 MiB")
    try:
        text = raw.decode("utf-8")
        if not within_json_depth(text):
            raise N8nConnectorError("Control-plane JSON nesting exceeds 64 levels")
        result = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (ValueError, RecursionError):
        raise N8nConnectorError("Control-plane response must be valid finite JSON") from None
    if not isinstance(result, dict):
        raise N8nConnectorError("Control-plane response must be a JSON object")
    return result


def _validate_path(path: str) -> None:
    # Validate before urlsplit can discard controls or urljoin can change origin.
    decoded = parse.unquote(path, errors="strict")
    if (
        not path.startswith("/")
        or not path.isascii()
        or any(ord(char) <= 32 for char in path)
        or decoded.startswith("//")
        or "\\" in decoded
        or "#" in path
        or any(ord(char) < 32 or 127 <= ord(char) < 160 for char in decoded)
        or any(part in {".", ".."} for part in parse.unquote(parse.urlsplit(path).path).split("/"))
    ):
        raise N8nConnectorError("Invalid control-plane API path")


def _check_subject(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    if payload.get("run_id") != run_id.strip():
        raise N8nConnectorError("Control-plane response subject mismatch")
    return payload


class SafeControlPlaneConnector(N8nControlPlaneConnector):
    """Use the parent config/constructor; each HTTP call has exactly one attempt."""

    def get_run(self, run_id: str) -> dict[str, Any]:
        return _check_subject(super().get_run(run_id), run_id)

    def get_artifacts(self, run_id: str) -> dict[str, Any]:
        return _check_subject(super().get_artifacts(run_id), run_id)

    def _caller_message(self, payload: Mapping[str, Any]) -> str:
        value = payload.get("detail", payload.get("message"))
        error = payload.get("error")
        if not isinstance(value, str) and isinstance(error, Mapping):
            value = error.get("message")
        if not isinstance(value, str):
            return "Control-plane request rejected"
        secrets = [self._config.api_token]
        credential = self._config.provider_credential
        if credential is not None:
            resolve = getattr(credential, "resolve_api_key", None)
            try:
                resolved = resolve() if callable(resolve) else credential.api_key
            except Exception:
                resolved = credential.api_key
            if isinstance(resolved, str) and resolved:
                secrets.append(resolved)
        for secret in sorted(set(secrets), key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        value = "".join(char if char.isprintable() else " " for char in value)
        for secret in sorted(set(secrets), key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        return value[:512]

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        include_provider_credential: bool = False,
    ) -> dict[str, Any]:
        try:
            _validate_path(path)
            if not method.isascii() or not method.isalpha() or not method.isupper():
                raise N8nConnectorError("Invalid control-plane HTTP method")
            payload_bytes = None
            headers = {
                "Accept": "application/json",
                "X-AdaptOrch-Connector-Source": self._config.connector_source,
            }
            if self._config.api_token.startswith("ado_"):
                headers["X-API-Key"] = self._config.api_token
            else:
                headers["Authorization"] = f"Bearer {self._config.api_token}"
            if idempotency_key is not None:
                headers["Idempotency-Key"] = idempotency_key
            if include_provider_credential and method == "POST" and path == "/v1/runs":
                credential = self._config.provider_credential
                if credential is not None:
                    headers[PROVIDER_HEADER] = credential.provider
                    headers[MODEL_HEADER] = credential.model
                    resolve = getattr(credential, "resolve_api_key", None)
                    try:
                        resolved = resolve() if callable(resolve) else credential.api_key
                    except ValueError as exc:
                        raise N8nConnectorError("Provider credential resolution failed") from exc
                    if isinstance(resolved, str) and resolved:
                        headers[KEY_HEADER] = resolved
            if any(
                not value.isascii() or any(ord(char) < 32 or ord(char) == 127 for char in value)
                for value in headers.values()
            ):
                raise N8nConnectorError("Invalid control-plane request headers")
            if body is not None:
                text = json.dumps(body, ensure_ascii=True, allow_nan=False)
                if not within_json_depth(text):
                    raise N8nConnectorError("Control-plane JSON nesting exceeds 64 levels")
                payload_bytes = text.encode("utf-8")
                if len(payload_bytes) > _MAX_JSON_BYTES:
                    raise N8nConnectorError("Control-plane request exceeds 8 MiB")
                headers["Content-Type"] = "application/json"
            target = parse.urljoin(f"{self._config.base_url}/", path.lstrip("/"))
            req = request.Request(target, data=payload_bytes, headers=headers, method=method)
        except (ValueError, TypeError, RecursionError):
            raise N8nConnectorError("Invalid control-plane request") from None

        # An explicit handler set excludes redirects, ambient proxies and auth retries.
        opener = request.OpenerDirector()
        for handler in (
            request.HTTPHandler(),
            request.HTTPSHandler(),
            request.HTTPDefaultErrorHandler(),
            request.HTTPErrorProcessor(),
        ):
            opener.add_handler(handler)
        try:
            try:
                response = opener.open(req, timeout=self._config.timeout_seconds)
            except HTTPError as exc:
                response = exc
            with response:
                status = response.code
                length_text = response.headers.get("Content-Length")
                length = int(length_text) if length_text is not None else None
                if length is not None and not 0 <= length <= _MAX_JSON_BYTES:
                    raise N8nConnectorError("Invalid control-plane response length (8 MiB limit)")
                raw = response.read(_MAX_JSON_BYTES + 1)
                if length is not None and len(raw) != length:
                    raise N8nConnectorError("Incomplete control-plane response")
        except (OSError, HTTPException, ValueError):
            raise N8nConnectorError("Control-plane request failed") from None

        try:
            payload = _json_object(raw)
        except N8nConnectorError:
            if not 200 <= status < 300:
                raise N8nHttpError(
                    status_code=status,
                    message="Invalid control-plane response",
                ) from None
            raise
        if not 200 <= status < 300:
            usage = _quota_exceeded_usage(status, payload)
            if usage is not None:
                safe_usage = {
                    key: _redact_connector_secrets(value, self._config)
                    if isinstance(value, str)
                    else value
                    for key, value in usage.items()
                }
                raise N8nQuotaExceededError(
                    message="Tenant quota exhausted for the current period",
                    usage=safe_usage,
                )
            # This wrapper owns its own one-attempt transport, so it must also
            # produce the recovery record the engine's error payload reads.
            # Without it a 4xx reaches the caller as the generic "inspect the
            # run" sentence and a keyless caller never learns which headers to
            # send. `_caller_message` has already redacted the known secrets.
            caller_fixable = caller_fixable_status(status)
            message = (
                self._caller_message(payload)
                if caller_fixable
                else "Control-plane request rejected"
            )
            error = N8nHttpError(status_code=status, message=message)
            error.__dict__["recovery"] = {
                "schema_version": 1,
                "reason": "authentication" if status in {401, 403} else "request_rejected",
                "attempts": 1,
                "retryable": False,
                "replay_safe": False,
                "request_outcome": "read_only" if method in _SAFE_METHODS else "response_received",
                "status_code": status,
                **({"detail": message} if caller_fixable else {}),
            }
            raise error
        if method == "POST" and path == "/v1/runs":
            run_id = payload.get("run_id")
            if not isinstance(run_id, str) or not run_id.strip():
                raise N8nConnectorError("Control-plane run admission has no valid subject")
        return payload
