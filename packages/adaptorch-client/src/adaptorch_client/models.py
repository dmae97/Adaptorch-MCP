"""Typed v1 contract records parsed from direct (envelope-free) JSON responses."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Self, TypeAlias

from adaptorch_client.errors import AdaptOrchAPIError

JSONValue: TypeAlias = bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"] | None
JSONMapping: TypeAlias = dict[str, JSONValue]


def contract_error(path: str, expected: str) -> AdaptOrchAPIError:
    """Return a sanitized contract-violation error naming only the field path."""
    return AdaptOrchAPIError(f"AdaptOrch response field {path!r} must be {expected}")


def field_path(path: str, key: str) -> str:
    """Compose a dotted field path that stays readable at the response root."""
    return f"{path}.{key}" if path else key


def require_object(value: JSONValue, path: str) -> JSONMapping:
    """Return ``value`` when it is a JSON object, else raise a contract error."""
    if not isinstance(value, dict):
        raise contract_error(path, "a JSON object")
    return value


def require_array(value: JSONValue, path: str) -> list[JSONValue]:
    """Return ``value`` when it is a JSON array, else raise a contract error."""
    if not isinstance(value, list):
        raise contract_error(path, "a JSON array")
    return value


def stored_copy(payload: Mapping[str, JSONValue]) -> JSONMapping:
    """Return an independent deep copy of a raw response payload."""
    return deepcopy(dict(payload))


def string_at(record: JSONMapping, key: str, path: str) -> str:
    """Return the required string field ``key``, else raise a contract error."""
    value = record.get(key)
    if not isinstance(value, str):
        raise contract_error(field_path(path, key), "a string")
    return value


def optional_string_at(record: JSONMapping, key: str, path: str) -> str | None:
    """Return the optional string field ``key``; absent or null becomes ``None``."""
    if record.get(key) is None:
        return None
    return string_at(record, key, path)


def _string_tuple_at(record: JSONMapping, key: str, path: str) -> tuple[str, ...]:
    values: list[str] = []
    array_path = field_path(path, key)
    for index, item in enumerate(require_array(record.get(key), array_path)):
        if not isinstance(item, str):
            raise contract_error(f"{array_path}[{index}]", "a string")
        values.append(item)
    return tuple(values)


def _optional_size_at(record: JSONMapping, key: str, path: str) -> int | None:
    value = record.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise contract_error(field_path(path, key), "a non-negative integer")
    return value


def _optional_links_at(record: JSONMapping, key: str, path: str) -> dict[str, str] | None:
    value = record.get(key)
    if value is None:
        return None
    links_path = field_path(path, key)
    links: dict[str, str] = {}
    for relation, target in require_object(value, links_path).items():
        if not isinstance(target, str):
            raise contract_error(f"{links_path}.{relation}", "a string")
        links[relation] = target
    return links


@dataclass(frozen=True, slots=True)
class PayloadResult:
    """A record that keeps its raw JSON payload, unknown additive fields included."""

    _payload: JSONMapping

    def to_payload(self) -> JSONMapping:
        """Return an independent JSON-compatible payload."""
        return deepcopy(self._payload)


@dataclass(frozen=True, slots=True)
class CapabilitySet(PayloadResult):
    """Direct ``GET /v1/capabilities`` record; unknown run kinds are preserved."""

    api_version: str
    run_types: tuple[str, ...]
    features: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, JSONValue]) -> Self:
        """Validate one raw capability response against the v1 contract."""
        record = stored_copy(payload)
        return cls(
            record,
            api_version=string_at(record, "api_version", ""),
            run_types=_string_tuple_at(record, "run_types", "") if "run_types" in record else (),
            features=_string_tuple_at(record, "features", ""),
        )


@dataclass(frozen=True, slots=True)
class Principal(PayloadResult):
    """Direct ``GET /v1/whoami`` record from the v1 contract."""

    subject_id: str
    project_id: str | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, JSONValue]) -> Self:
        """Validate one raw principal response against the v1 contract."""
        record = stored_copy(payload)
        return cls(
            record,
            subject_id=string_at(record, "subject_id", ""),
            project_id=optional_string_at(record, "project_id", ""),
        )


@dataclass(frozen=True, slots=True)
class Run(PayloadResult):
    """Direct ``Run`` record; unknown ``status`` enum strings are preserved."""

    run_id: str
    status: str
    kind: str | None
    phase: str | None
    created_at: str | None
    policy_version: str | None
    links: dict[str, str] | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, JSONValue]) -> Self:
        """Validate one raw run response against the v1 contract."""
        return cls._parse(stored_copy(payload), "")

    @classmethod
    def parse_at(cls, value: JSONValue, path: str) -> Self:
        """Parse one nested run record located at ``path``."""
        return cls._parse(deepcopy(require_object(value, path)), path)

    @classmethod
    def _parse(cls, record: JSONMapping, path: str) -> Self:
        return cls(
            record,
            run_id=string_at(record, "run_id", path),
            status=string_at(record, "status", path),
            kind=optional_string_at(record, "kind", path),
            phase=optional_string_at(record, "phase", path),
            created_at=optional_string_at(record, "created_at", path),
            policy_version=optional_string_at(record, "policy_version", path),
            links=_optional_links_at(record, "links", path),
        )


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    """One evidence check; unknown ``status`` strings are preserved."""

    name: str
    status: str

    @classmethod
    def parse_at(cls, value: JSONValue, path: str) -> Self:
        """Parse one contract record located at ``path``."""
        record = require_object(value, path)
        return cls(
            name=string_at(record, "name", path),
            status=string_at(record, "status", path),
        )


@dataclass(frozen=True, slots=True)
class Artifact:
    """``Artifact`` record; only ``artifact_id`` and ``name`` are required."""

    artifact_id: str
    name: str
    media_type: str | None
    size_bytes: int | None
    sha256: str | None
    download_url: str | None

    @classmethod
    def parse_at(cls, value: JSONValue, path: str) -> Self:
        """Parse one contract record located at ``path``."""
        record = require_object(value, path)
        return cls(
            artifact_id=string_at(record, "artifact_id", path),
            name=string_at(record, "name", path),
            media_type=optional_string_at(record, "media_type", path),
            size_bytes=_optional_size_at(record, "size_bytes", path),
            sha256=optional_string_at(record, "sha256", path),
            download_url=optional_string_at(record, "download_url", path),
        )
