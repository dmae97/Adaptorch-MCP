from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from adaptorch_mcp.correctness_wall_output import get_run_output_schema

_BLOCKED_REMOTE_RUN_ARGUMENTS: Final = frozenset({"trace", "verification_commands"})
_JSON_TYPES: Final = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)


class ParentContractError(RuntimeError):
    """Raised when the installed parent cannot provide a safe MCP contract."""


def _valid_property_schema(schema: Mapping[str, Any], *, depth: int = 0) -> bool:
    if depth > 8:
        return False
    raw_type = schema.get("type")
    valid_type = (
        raw_type is None
        or isinstance(raw_type, str)
        and raw_type in _JSON_TYPES
        or isinstance(raw_type, list)
        and bool(raw_type)
        and all(isinstance(item, str) and item in _JSON_TYPES for item in raw_type)
    )
    if not valid_type:
        return False

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping) or not all(
            isinstance(key, str)
            and isinstance(value, Mapping)
            and _valid_property_schema(value, depth=depth + 1)
            for key, value in properties.items()
        ):
            return False
        required = schema.get("required")
        if required is not None and (
            not isinstance(required, list)
            or not all(isinstance(key, str) and key in properties for key in required)
        ):
            return False

    items = schema.get("items")
    if items is not None and (
        not isinstance(items, Mapping) or not _valid_property_schema(items, depth=depth + 1)
    ):
        return False
    additional = schema.get("additionalProperties")
    if additional is None or isinstance(additional, bool):
        return True
    return isinstance(additional, Mapping) and _valid_property_schema(
        additional, depth=depth + 1
    )


def _project_property_schema(
    schema: Mapping[str, Any],
    *,
    depth: int = 0,
) -> dict[str, Any]:
    if not _valid_property_schema(schema, depth=depth):
        raise ParentContractError("parent MCP tool property schema is invalid")
    projected: dict[str, Any] = {}
    raw_type = schema.get("type")
    if raw_type is not None:
        projected["type"] = list(raw_type) if isinstance(raw_type, list) else raw_type
    for key in ("description", "pattern", "format"):
        value = schema.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise ParentContractError(f"parent MCP tool schema {key} must be a string")
            projected[key] = value
    if "default" in schema:
        default = schema["default"]
        if default is not None and not isinstance(default, str | int | float | bool):
            raise ParentContractError("parent MCP tool schema default must be scalar")
        projected["default"] = default
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not enum or not all(
            item is None or isinstance(item, str | int | float | bool) for item in enum
        ):
            raise ParentContractError("parent MCP tool schema enum must contain scalars")
        projected["enum"] = list(enum)
    for key in ("minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength"):
        value = schema.get(key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ParentContractError(f"parent MCP tool schema {key} must be numeric")
            projected[key] = value

    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        projected["properties"] = {
            key: _project_property_schema(value, depth=depth + 1)
            for key, value in properties.items()
            if isinstance(key, str) and isinstance(value, Mapping)
        }
    required = schema.get("required")
    if isinstance(required, list):
        projected["required"] = list(required)
    items = schema.get("items")
    if isinstance(items, Mapping):
        projected["items"] = _project_property_schema(items, depth=depth + 1)
    additional = schema.get("additionalProperties")
    if isinstance(additional, bool):
        projected["additionalProperties"] = additional
    if isinstance(additional, Mapping):
        projected["additionalProperties"] = _project_property_schema(
            additional,
            depth=depth + 1,
        )
    return projected


def _project_annotations(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get("title"), str):
        raise ParentContractError("parent MCP tool annotations must define a title")
    hint_keys = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
    if not all(isinstance(value.get(key), bool) for key in hint_keys):
        raise ParentContractError("parent MCP tool annotations must define boolean hints")
    return {"title": value["title"], **{key: value[key] for key in hint_keys}}


def project_remote_tool(tool: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and project one parent tool descriptor for remote exposure."""
    name = tool.get("name")
    description = tool.get("description")
    schema = tool.get("inputSchema")
    if not isinstance(name, str) or not isinstance(description, str):
        raise ParentContractError("parent MCP tool must define name and description")
    if (
        not isinstance(schema, Mapping)
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
    ):
        raise ParentContractError("parent MCP tool must have a closed object input schema")
    properties = schema.get("properties")
    if (
        not isinstance(properties, Mapping)
        or not all(isinstance(key, str) for key in properties)
        or not all(
            isinstance(value, Mapping) and _valid_property_schema(value)
            for value in properties.values()
        )
    ):
        raise ParentContractError("parent MCP tool input schema must define properties")
    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list)
        or not all(isinstance(key, str) and key in properties for key in required)
    ):
        raise ParentContractError("parent MCP tool required fields must reference properties")

    projected_schema = _project_property_schema(schema)
    projected_properties = projected_schema["properties"]
    if name == "adaptorch_run":
        projected_schema["properties"] = {
            key: value
            for key, value in projected_properties.items()
            if key not in _BLOCKED_REMOTE_RUN_ARGUMENTS
        }
        if isinstance(required, list):
            projected_schema["required"] = [
                key for key in required if key not in _BLOCKED_REMOTE_RUN_ARGUMENTS
            ]
    projected = {
        "name": name,
        "description": description,
        "annotations": _project_annotations(tool.get("annotations")),
        "inputSchema": projected_schema,
    }
    if name == "adaptorch_get_run":
        projected["outputSchema"] = get_run_output_schema()
    return projected


def tool_argument_names(tool: Mapping[str, Any]) -> frozenset[str]:
    """Return validated top-level argument names from a projected descriptor."""
    schema = tool["inputSchema"]
    return frozenset(str(key) for key in schema["properties"])
