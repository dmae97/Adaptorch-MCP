"""Bounded, unambiguous JSON decoding at the parent-to-public response boundary."""

from __future__ import annotations

import json
import math
from typing import Final, Never

from adaptorch_client.json_limits import max_nesting_exceeds
from adaptorch_mcp.run_output import JSONValue

MAX_RESPONSE_BYTES: Final = 8 * 1024 * 1024
MAX_JSON_DEPTH: Final = 64


def within_json_depth(text: str) -> bool:
    return not max_nesting_exceeds(text, MAX_JSON_DEPTH)


def _reject_constant(value: str) -> Never:
    raise ValueError("non-finite JSON")


def _finite_float(value: str) -> float:
    # ValueError is the JSON hook protocol; the outer decoder normalizes it.
    try:
        number = float(value)
    except ValueError:
        raise ValueError("invalid JSON number") from None
    if not math.isfinite(number):
        raise ValueError("non-finite JSON")
    return number


def _unique_object(pairs: list[tuple[str, JSONValue]]) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def decode_response_text(text: str) -> dict[str, JSONValue] | None:
    if len(text) > MAX_RESPONSE_BYTES or not within_json_depth(text):
        return None
    try:
        if len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
            return None
        value: JSONValue = json.loads(
            text,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            object_pairs_hook=_unique_object,
        )
    except (ValueError, UnicodeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None
