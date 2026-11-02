"""Strict argument validation against a discovered command's schema."""

from __future__ import annotations

from typing import Any

from cli_mcp.errors import SchemaError
from cli_mcp.models import CommandSpec, Parameter, normalize_identifier
from cli_mcp.schema.jsonschema import argument_name, coerce_choices

_TYPE_CHECKERS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _type_matches(param: Parameter, value: Any) -> bool:
    """Whether *value* satisfies the parameter's declared type."""
    expected = _TYPE_CHECKERS.get(param.type)
    if expected is None:
        return True
    if param.type == "integer" and isinstance(value, bool):
        return False
    if param.type == "number" and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _check(param: Parameter, name: str, value: Any) -> list[str]:
    """Problems for one supplied argument."""
    problems: list[str] = []
    if not _type_matches(param, value):
        problems.append(f"argument {name!r} must be of type {param.type}, got {type(value).__name__}")
        return problems
    choices = coerce_choices(param)
    if choices:
        if param.type == "array" and isinstance(value, list):
            invalid = [item for item in value if item not in choices]
            if invalid:
                problems.append(f"argument {name!r} has invalid items {invalid}; allowed: {choices}")
        elif value not in choices:
            problems.append(f"argument {name!r} must be one of {choices}, got {value!r}")
    return problems


def validate_arguments(spec: CommandSpec, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Validate tool arguments and return them keyed by canonical argument names.

    Unknown keys are rejected: an MCP client must not silently pass options the
    CLI does not understand.
    """
    lookup: dict[str, Parameter] = {}
    for param in spec.parameters:
        lookup[argument_name(param)] = param
    supplied = arguments or {}
    problems: list[str] = []
    missing: set[str] = set()
    normalized: dict[str, Any] = {}
    for key, value in supplied.items():
        name = normalize_identifier(str(key))
        matched = lookup.get(name)
        if matched is None:
            hint = ", ".join(sorted(lookup)) or "none"
            problems.append(f"unknown argument {key!r} for tool {spec.name!r}; supported arguments: {hint}")
            continue
        if value is None:
            if not matched.required:
                continue  # the SDK passes None for omitted optional arguments
            missing.add(name)
            problems.append(f"missing required argument {name!r} for tool {spec.name!r}")
            continue
        problems.extend(_check(matched, name, value))
        normalized[argument_name(matched)] = value
    for param in spec.parameters:
        name = argument_name(param)
        if param.required and name not in normalized and name not in missing:
            problems.append(f"missing required argument {name!r} for tool {spec.name!r}")
    if problems:
        raise SchemaError(f"invalid arguments for tool {spec.name}: " + "; ".join(problems))
    return normalized
