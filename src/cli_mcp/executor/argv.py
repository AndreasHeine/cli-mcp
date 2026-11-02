"""Turning validated tool arguments back into a CLI argv."""

from __future__ import annotations

from typing import Any

from cli_mcp.models import CommandSpec, Parameter, ParamKind


def format_value(param: Parameter, value: Any) -> str:
    """Render one argument value as a CLI token."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return ""
    return str(value)


def _tokens_for(param: Parameter, value: Any) -> list[str]:
    """CLI tokens contributed by one parameter value."""
    flag = param.cli_flag
    if param.kind is ParamKind.FLAG:
        if isinstance(value, bool):
            return [flag] if value else []
        if value in (1, "true", "yes", "on"):
            return [flag]
        return []
    if isinstance(value, list):
        tokens: list[str] = []
        for item in value:
            tokens.append(flag)
            rendered = format_value(param, item)
            if rendered:
                tokens.append(rendered)
        return tokens
    return [flag, format_value(param, value)]


def build_argv(command: list[str], spec: CommandSpec, arguments: dict[str, Any]) -> list[str]:
    """Build the argv that runs *command* with the validated arguments.

    Options and flags come first, positional values afterwards in declaration
    order, which every supported framework accepts.
    """
    argv = [*command, *spec.argv_path]
    for param in spec.parameters:
        if param.kind is ParamKind.POSITIONAL:
            continue
        value = arguments.get(param.name)
        if value is None:
            continue
        argv.extend(_tokens_for(param, value))
    for param in spec.ordered_positionals():
        value = arguments.get(param.name)
        if value is None:
            continue
        if isinstance(value, list):
            argv.extend(format_value(param, item) for item in value)
        else:
            argv.append(format_value(param, value))
    return argv
