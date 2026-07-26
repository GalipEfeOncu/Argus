"""Supported JSON-Schema subset for custom local evidence contracts."""

from __future__ import annotations

from typing import Any


_KEYS_BY_TYPE = {
    "object": {"type", "required", "properties", "additionalProperties", "enum"},
    "array": {"type", "items", "minItems", "enum"},
    "string": {"type", "minLength", "enum"},
    "integer": {"type", "minimum", "enum"},
    "number": {"type", "minimum", "enum"},
    "boolean": {"type", "enum"},
}


def is_supported_json_schema(schema: object) -> bool:
    """Reject unsupported keywords rather than silently weakening a contract."""

    if not isinstance(schema, dict) or not isinstance(schema.get("type"), str):
        return False
    kind = schema["type"]
    if kind not in _KEYS_BY_TYPE or set(schema) - _KEYS_BY_TYPE[kind]:
        return False
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        return False
    if kind == "object":
        required, properties = schema.get("required", []), schema.get("properties", {})
        if not isinstance(required, list) or not all(isinstance(key, str) for key in required):
            return False
        if not isinstance(properties, dict) or not all(isinstance(key, str) and is_supported_json_schema(value) for key, value in properties.items()):
            return False
        return isinstance(schema.get("additionalProperties", True), bool)
    if kind == "array":
        return (
            isinstance(schema.get("items"), dict) and is_supported_json_schema(schema["items"])
            and ("minItems" not in schema or isinstance(schema["minItems"], int) and schema["minItems"] >= 0)
        )
    if kind == "string":
        return "minLength" not in schema or isinstance(schema["minLength"], int) and schema["minLength"] >= 0
    if kind in {"integer", "number"}:
        return "minimum" not in schema or isinstance(schema["minimum"], (int, float)) and not isinstance(schema["minimum"], bool)
    return True


def matches_json_schema(value: object, schema: dict[str, Any]) -> bool:
    """Validate a value against an already-validated supported schema."""

    if "enum" in schema and value not in schema["enum"]:
        return False
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict):
            return False
        required, properties = schema.get("required", []), schema.get("properties", {})
        if any(key not in value for key in required):
            return False
        if schema.get("additionalProperties", True) is False and any(key not in properties for key in value):
            return False
        return all(matches_json_schema(value[key], child) for key, child in properties.items() if key in value)
    if kind == "array":
        return isinstance(value, list) and len(value) >= schema.get("minItems", 0) and all(matches_json_schema(item, schema["items"]) for item in value)
    if kind == "string":
        return isinstance(value, str) and len(value) >= schema.get("minLength", 0)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool) and value >= schema.get("minimum", value)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= schema.get("minimum", value)
    return isinstance(value, bool)
