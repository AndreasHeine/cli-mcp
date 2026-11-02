"""JSON Schema generation from discovered command metadata."""

from __future__ import annotations

from typing import Any

from cli_mcp.models import CommandSpec, Parameter, ParamKind, normalize_identifier


def argument_name(param: Parameter) -> str:
    """Return the MCP-facing argument name for a parameter."""
    return normalize_identifier(param.cli_name or param.name)


def cli_hint(param: Parameter) -> str:
    """Describe how the parameter appears on the command line."""
    if param.kind is ParamKind.POSITIONAL:
        metavar = param.metavar or param.cli_name or param.name
        return f"Positional argument: {metavar}"
    flag = param.cli_flag
    if param.kind is ParamKind.FLAG:
        return f"CLI flag: {flag}"
    metavar = param.metavar or param.cli_name or param.name
    return f"CLI option: {flag} {metavar}"


def coerce_choices(param: Parameter) -> list[Any]:
    """Choices narrowed to the parameter's declared numeric type.

    Help text spells enum values as text (``[choices: 1, 2, 3]``), so numeric
    parameters need numeric values to stay schema-valid.
    """
    choices = list(param.choices or [])
    if param.type not in {"integer", "number"}:
        return choices
    coerced: list[Any] = []
    for choice in choices:
        try:
            value = float(choice)
        except ValueError:
            return choices
        coerced.append(int(value) if value.is_integer() else value)
    return coerced


def parameter_schema(param: Parameter) -> dict[str, Any]:
    """Build the JSON Schema for one parameter, keeping description, enum and default."""
    schema: dict[str, Any] = {"type": param.type}
    choices = coerce_choices(param)
    if param.type == "array":
        items: dict[str, Any] = {"type": "string"}
        if choices:
            items["enum"] = choices
        schema["items"] = items
    elif choices:
        schema["enum"] = choices
    if param.default is not None:
        schema["default"] = param.default
    description = param.description or ("Toggle flag" if param.kind is ParamKind.FLAG else "Required value")
    schema["description"] = f"{description} ({cli_hint(param)})"
    if param.repeatable:
        schema["description"] += " May be passed multiple times as an array."
    return schema


def input_schema(spec: CommandSpec) -> dict[str, Any]:
    """Build the MCP ``inputSchema`` for a discovered command."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in spec.parameters:
        name = argument_name(param)
        properties[name] = parameter_schema(param)
        if param.required:
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def execution_result_schema() -> dict[str, Any]:
    """JSON Schema for the tool result cli-mcp returns after running a command."""
    return {
        "type": "object",
        "properties": {
            "stdout": {"type": "string", "description": "Standard output of the CLI process"},
            "stderr": {"type": "string", "description": "Standard error of the CLI process"},
            "exitCode": {"type": "integer", "description": "Process exit code"},
            "executionTimeMs": {"type": "integer", "description": "Wall-clock execution time in milliseconds"},
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact argv the CLI process was started with",
            },
            "truncated": {"type": "boolean", "description": "Whether output was truncated"},
        },
        "required": ["stdout", "stderr", "exitCode", "executionTimeMs"],
        "additionalProperties": False,
    }
