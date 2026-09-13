"""Portable JSON nesting bound, independent of the interpreter's C recursion limit."""

from typing import Final

from adaptorch_client.errors import AdaptOrchAPIError

MAX_JSON_DEPTH: Final = 64


def require_json_depth(text: str) -> None:
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise AdaptOrchAPIError("AdaptOrch JSON nesting exceeds 64 levels")
        elif char in "]}":
            depth -= 1
