"""Portable JSON nesting bound, independent of the interpreter's C recursion limit."""

import re
from itertools import accumulate, islice
from typing import Final

from adaptorch_client.errors import AdaptOrchAPIError

MAX_JSON_DEPTH: Final = 64

# Everything that is not structure: quoted strings (escapes included, an unterminated
# string runs to the end like the quoted state it opens) and runs of other text. The
# possessive quantifiers never backtrack, so the scan stays linear on hostile input.
_NOT_STRUCTURE: Final = re.compile(r'"[^"\\]*+(?:\\.[^"\\]*+)*+"?|[^\[\]{}"]++', re.DOTALL)
_STEP: Final = {"[": 1, "{": 1, "]": -1, "}": -1}.__getitem__
_CHUNK: Final = 65_536


def max_nesting_exceeds(text: str, limit: int) -> bool:
    """Return whether any prefix opens more than ``limit`` unclosed containers.

    Brackets inside strings never count. The regex and the running sum run in C,
    so a multi-megabyte body costs milliseconds instead of a per-character loop.
    """
    structure = iter(_NOT_STRUCTURE.sub("", text))
    depth = 0
    while chunk := tuple(map(_STEP, islice(structure, _CHUNK))):
        sums = tuple(accumulate(chunk, initial=depth))
        if max(sums) > limit:
            return True
        depth = sums[-1]
    return False


def require_json_depth(text: str) -> None:
    if max_nesting_exceeds(text, MAX_JSON_DEPTH):
        raise AdaptOrchAPIError("AdaptOrch JSON nesting exceeds 64 levels")
