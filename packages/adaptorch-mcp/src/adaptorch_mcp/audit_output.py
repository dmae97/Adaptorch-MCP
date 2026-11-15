"""Pinned opt-in audit contract, validated without importing the private engine."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from functools import cache
from importlib.resources import files
from typing import Any

AUDIT_TOOL_NAMES = ('adaptorch_audit', 'adaptorch_get_audit', 'adaptorch_get_audit_artifact')


@cache
def _contracts() -> dict[str, dict[str, Any]]:
    text = files('adaptorch_mcp').joinpath('audit_tool_contracts.json').read_text('utf-8')
    data = json.loads(text)
    return {item['name']: item for item in data['tools']}


def audit_contract(name: str) -> dict[str, Any]:
    return deepcopy(_contracts()[name])


def _valid(value: Any, schema: dict[str, Any], root: dict[str, Any], depth: int = 0) -> bool:
    """Only constructs in the pinned audit DTO schemas; never an upstream evaluator."""
    if depth > 12:
        return False
    if '$ref' in schema:
        target = root['$defs'][schema['$ref'].removeprefix('#/$defs/')]
        return _valid(value, target, root, depth + 1)
    if 'anyOf' in schema:
        return any(_valid(value, branch, root, depth + 1) for branch in schema['anyOf'])
    kind = schema.get('type')
    if kind == 'object':
        if not isinstance(value, Mapping):
            return False
        properties = schema['properties']
        return (all(key in value for key in schema.get('required', []))
                and not set(value) - set(properties)
                and all(_valid(item, properties[key], root, depth + 1)
                        for key, item in value.items()))
    if kind == 'array':
        return (isinstance(value, list) and len(value) <= schema.get('maxItems', 64)
                and all(_valid(item, schema['items'], root, depth + 1) for item in value))
    if kind == 'string':
        if not isinstance(value, str):
            return False
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 16384):
            return False
        if 'pattern' in schema and re.fullmatch(schema['pattern'], value) is None:
            return False
        try:
            value.encode('utf-8')
        except UnicodeError:
            return False
    elif kind in {'integer', 'number'}:
        allowed = (int,) if kind == 'integer' else (int, float)
        if type(value) not in allowed:
            return False
        try:
            if not math.isfinite(value):
                return False
        except OverflowError:
            return False
        if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf):
            return False
    elif kind == 'boolean':
        if not isinstance(value, bool):
            return False
    elif kind == 'null':
        if value is not None:
            return False
    else:
        return False
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        return False
    return 'enum' not in schema or value in schema['enum']


def valid_audit_arguments(name: str, arguments: Mapping[str, Any]) -> bool:
    schema = _contracts()[name]['inputSchema']
    return _valid(arguments, schema, schema)


def project_audit_output(name: str, value: Mapping[str, Any]) -> dict[str, Any] | None:
    schema = _contracts()[name]['outputSchema']
    if not _valid(value, schema, schema):
        return None
    if name == 'adaptorch_get_audit_artifact':
        returned = len(value['text'].encode('utf-8'))
        end = value['offset_bytes'] + returned
        if (returned != value['returned_bytes'] or end > value['total_bytes']
                or value['has_more'] != (end < value['total_bytes'])
                or value['has_more'] != (value['next_cursor'] is not None)):
            return None
    return deepcopy(dict(value))
