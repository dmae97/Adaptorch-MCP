"""Collect engine-bound test modules only where the private engine is installed.

A public install has no ``adaptorch`` engine. A module that imports it, or the
``adaptorch_mcp_legacy`` bridge, at module level cannot be imported there, so it is
skipped at collection instead of erroring. Detection follows sibling helper modules
such as ``mcp_test_support``. ``make engine-check`` installs the engine and runs all.
"""

from __future__ import annotations

import ast
import importlib.util
from functools import cache
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_ENGINE_ROOTS = frozenset({"adaptorch", "adaptorch_mcp_legacy"})


def _engine_installed() -> bool:
    try:
        return importlib.util.find_spec("adaptorch.mcp_server") is not None
    except ModuleNotFoundError:
        return False


ENGINE_INSTALLED = _engine_installed()


@cache
def _engine_bound(path: Path) -> bool:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots = [node.module.split(".")[0]]
        else:
            continue
        for root in roots:
            helper = _TESTS / f"{root}.py"
            if root in _ENGINE_ROOTS:
                return True
            if helper.is_file() and helper != path and _engine_bound(helper):
                return True
    return False


def pytest_ignore_collect(collection_path: Path) -> bool | None:
    if ENGINE_INSTALLED or collection_path.suffix != ".py":
        return None
    return True if _engine_bound(collection_path) else None
