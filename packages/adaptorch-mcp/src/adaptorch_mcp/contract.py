"""Fixed remote policy; descriptors never grant permissions or introduce tools."""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping
from typing import Any

from adaptorch_mcp.public_schema import ParentContractError, project_remote_tool

TOOL_NAMES = (
    "adaptorch_run",
    "adaptorch_get_run",
    "adaptorch_get_artifacts",
    "adaptorch_list_runs",
    "adaptorch_cancel_run",
    "adaptorch_server_metrics",
    "adaptorch_capabilities",
    "adaptorch_usage",
    "adaptorch_plan_catalog",
)
RESOURCE_URIS = ("adaptorch://server-info", "adaptorch://plans/cloud")
PROMPT_NAMES = ("adaptorch_run_prompt", "adaptorch_get_run_prompt")
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PROTOCOL_VERSION = "2025-06-18"
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_UNSUPPORTED = frozenset({"trace", "verification_commands", "idempotency_key", "resume_run_id"})
# Public documented controls only. Algorithms and prompt normalization remain hosted.
_RUN_FIELDS: dict[str, dict[str, Any]] = {
    "prompt": {"type": "string", "minLength": 1, "maxLength": 100000},
    "context": {"type": "string", "maxLength": 100000},
    "connector_name": {"type": "string", "minLength": 1, "maxLength": 256, "default": "mcp"},
    "payload": {"type": "object"},
    "synthesis_mode": {
        "type": "string",
        "enum": ["auto", "paper", "robust", "robust_lite", "stable_hybrid", "fourier_aggressive"],
    },
    "model": {"type": "string", "minLength": 1, "maxLength": 256},
    "budget_policy": {"type": "object"},
    "wait_for_terminal": {"type": "boolean", "default": True},
    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 300, "default": 120},
    "poll_interval_seconds": {
        "type": "number",
        "exclusiveMinimum": 0,
        "maximum": 300,
        "default": 1,
    },
    "ensemble_members": {
        "type": "array",
        "minItems": 2,
        "maxItems": 5,
        "items": {"type": "string", "minLength": 1, "maxLength": 256},
    },
    "output_extractor": {
        "type": "string",
        "enum": ["none", "final_answer", "multiple_choice_letter"],
    },
    "prefer_ensemble_singleton": {"type": ["boolean", "null"], "default": None},
}
_ID_FIELD = {"type": "string", "pattern": RUN_ID.pattern, "minLength": 1, "maxLength": 256}
_FIELDS: dict[str, dict[str, dict[str, Any]]] = {
    "adaptorch_run": _RUN_FIELDS,
    "adaptorch_get_run": {"run_id": _ID_FIELD},
    "adaptorch_get_artifacts": {"run_id": _ID_FIELD},
    "adaptorch_cancel_run": {"run_id": _ID_FIELD},
    "adaptorch_list_runs": {
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        "status": {"type": "string", "minLength": 1, "maxLength": 64},
    },
    **{name: {} for name in TOOL_NAMES[5:]},
}
_DESCRIPTIONS = {
    "adaptorch_run": "Submit a hosted task, optionally waiting for a bounded result. "
    "No automatic retry; an observer timeout may leave a submitted run active. "
    "Idempotency and resume are unavailable in this version.",
    "adaptorch_get_run": "Read a bounded hosted run summary by run ID.",
    "adaptorch_get_artifacts": "Read validated artifact references without downloading files.",
    "adaptorch_cancel_run": "Request cancellation of a hosted run. This is a destructive write.",
    "adaptorch_list_runs": "List recent runs for the authenticated tenant.",
    "adaptorch_server_metrics": "Read metrics measured by this client process only.",
    "adaptorch_capabilities": "Read hosted capabilities restricted by this client policy.",
    "adaptorch_usage": "Read usage for the authenticated tenant; no tenant override.",
    "adaptorch_plan_catalog": "Read the hosted cloud plan catalog.",
}


def input_schema(name: str, upstream_fields: set[str] | None = None) -> dict[str, Any]:
    fields = _FIELDS[name]
    if upstream_fields is not None:
        fields = {key: value for key, value in fields.items() if key in upstream_fields}
    required = ["run_id"] if "run_id" in fields else []
    return {
        "type": "object",
        "properties": copy.deepcopy(fields),
        "required": required,
        "additionalProperties": False,
    }


def tool_descriptors(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > 64:
        raise ParentContractError("invalid tool inventory")
    selected: dict[str, dict[str, Any]] = {}
    for value in raw:
        if not isinstance(value, Mapping) or not isinstance(value.get("name"), str):
            raise ParentContractError("invalid tool descriptor")
        name = value["name"]
        if name not in TOOL_NAMES:
            continue
        if name in selected:
            raise ParentContractError("duplicate tool descriptor")
        projected = project_remote_tool(value)
        upstream_fields = set(projected["inputSchema"]["properties"])
        schema = input_schema(name, upstream_fields)
        if set(projected["inputSchema"].get("required", [])) - set(schema["properties"]):
            raise ParentContractError("unsupported required upstream fields")
        required_local = set(input_schema(name)["required"])
        if not required_local.issubset(schema["properties"]):
            raise ParentContractError("missing required tool fields")
        if name == "adaptorch_run" and not {"prompt", "payload"} & upstream_fields:
            raise ParentContractError("missing hosted task input")
        read_only = name not in {"adaptorch_run", "adaptorch_cancel_run"}
        selected[name] = {
            "name": name,
            "description": _DESCRIPTIONS[name],
            "inputSchema": schema,
            "annotations": {
                "title": name,
                "readOnlyHint": read_only,
                "destructiveHint": name == "adaptorch_cancel_run",
                "idempotentHint": read_only
                and name not in {"adaptorch_server_metrics", "adaptorch_list_runs"},
                "openWorldHint": name
                not in {
                    "adaptorch_server_metrics",
                    "adaptorch_capabilities",
                    "adaptorch_plan_catalog",
                },
            },
        }
        if "outputSchema" in projected:
            selected[name]["outputSchema"] = projected["outputSchema"]
    if set(selected) != set(TOOL_NAMES):
        raise ParentContractError("upstream is missing required remote tools")
    return [selected[name] for name in TOOL_NAMES]


def _valid(value: Any, schema: Mapping[str, Any]) -> bool:
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    actual = (
        "null"
        if value is None
        else "boolean"
        if isinstance(value, bool)
        else "integer"
        if isinstance(value, int)
        else "number"
        if isinstance(value, float)
        else "string"
        if isinstance(value, str)
        else "object"
        if isinstance(value, dict)
        else "array"
        if isinstance(value, list)
        else "invalid"
    )
    if actual not in kinds and not (actual == "integer" and "number" in kinds):
        return False
    if isinstance(value, int | float) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return False
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 100000):
            return False
        if "\x00" in value:
            return False
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            return False
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 1000):
            return False
        if "items" in schema and not all(_valid(item, schema["items"]) for item in value):
            return False
    return True


def forbidden_nested(value: Any) -> bool:
    if isinstance(value, dict):
        if set(value) & _UNSUPPORTED:
            return True
        return any(forbidden_nested(item) for item in value.values())
    return isinstance(value, list) and any(forbidden_nested(item) for item in value)


def validate_arguments(name: str, arguments: Any, schema: Mapping[str, Any]) -> bool:
    if not isinstance(arguments, dict):
        return False
    properties = schema["properties"]
    if set(arguments) - set(properties) or set(schema.get("required", [])) - set(arguments):
        return False
    if not all(_valid(value, properties[key]) for key, value in arguments.items()):
        return False
    if name == "adaptorch_run":
        if not ("prompt" in arguments or "payload" in arguments):
            return False
        if forbidden_nested(arguments):
            return False
        budget = arguments.get("budget_policy", {})
        if any(not isinstance(v, str | int | float | bool) for v in budget.values()):
            return False
    return True
