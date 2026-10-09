"""Closed optional verification observations; no logs or verdict inference."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from adaptorch_mcp.run_output import JSONValue

DIAGNOSTIC_CODES: Final = (
    "ENV_DEPENDENCY_MISSING",
    "ENV_DEPENDENCY_NOT_EXECUTABLE",
    "PDF_TOOL_EXECUTION_FAILED",
)
MAX_DIAGNOSTICS: Final = 16
VERIFICATION_DIAGNOSTICS_SCHEMA_VERSION: Final = "verification.diagnostics/v1"
PDF_DIAGNOSTIC_TOOLS: Final = ("pdftotext", "pdffonts", "pdftoppm", "pdfinfo")


def project_verification_diagnostics(value: object) -> list[JSONValue] | None:
    if not isinstance(value, list) or len(value) > MAX_DIAGNOSTICS:
        return None
    result: list[JSONValue] = []
    for item in value:
        if (
            not isinstance(item, Mapping)
            or not {"code", "source", "scope"} <= set(item) <= {"code", "source", "scope", "tool"}
        ):
            return None
        code, source, scope = (item.get(key) for key in ("code", "source", "scope"))
        if not all(isinstance(part, str) for part in (code, source, scope)):
            return None
        if code not in DIAGNOSTIC_CODES or (source, scope) not in {
            ("process_spawn", "verification_command"),
            ("project_report", "child_tool"),
        }:
            return None
        if source == "process_spawn" and code == "PDF_TOOL_EXECUTION_FAILED":
            return None
        projected: dict[str, JSONValue] = {
            "code": str(code), "source": str(source), "scope": str(scope)
        }
        if "tool" in item:
            tool = item["tool"]
            if not isinstance(tool, str) or tool not in PDF_DIAGNOSTIC_TOOLS:
                return None
            projected["tool"] = tool
        result.append(projected)
    return result


def verification_diagnostics_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": MAX_DIAGNOSTICS,
        "description": (
            "Optional bounded observations. project_report is an untrusted project claim; "
            "process_spawn is a verifier launch observation. Neither changes a verdict."
        ),
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["code", "source", "scope"],
            "properties": {
                "code": {"type": "string", "enum": list(DIAGNOSTIC_CODES)},
                "source": {"type": "string", "enum": ["process_spawn", "project_report"]},
                "scope": {"type": "string", "enum": ["verification_command", "child_tool"]},
                "tool": {"type": "string", "enum": list(PDF_DIAGNOSTIC_TOOLS)},
            },
            "oneOf": [
                {"properties": {
                    "source": {"const": "process_spawn"},
                    "scope": {"const": "verification_command"},
                    "code": {"enum": list(DIAGNOSTIC_CODES[:2])},
                }},
                {"properties": {
                    "source": {"const": "project_report"},
                    "scope": {"const": "child_tool"},
                }},
            ],
        },
    }
