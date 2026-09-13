"""Primitive projection shared by bounded public response views."""

from collections.abc import Mapping
from typing import Any


def project_scalars(value: Mapping[str, Any], keys: frozenset[str]) -> dict[str, Any] | None:
    projected: dict[str, Any] = {}
    for key in keys:
        if key not in value:
            continue
        item = value[key]
        if item is not None and not isinstance(item, str | int | float | bool):
            return None
        projected[key] = item
    return projected


def project_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)
