"""Shared conversion from an introspection JSON payload into canonical commands.

Both reflection providers (Python and Node.js) emit the same JSON document, so
the conversion lives here rather than in each provider.
"""

from __future__ import annotations

import json
from typing import Any

from cli_mcp.detect import TargetInfo
from cli_mcp.discovery.engine import coerce_default, tool_base
from cli_mcp.models import CommandSpec, Parameter, ParamKind


def parse_payload(stdout: str) -> dict[str, Any] | None:
    """Parse an introspection JSON document, or ``None`` when nothing usable came back."""
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("commands"), list):
        return None
    return payload


def parameter_from(raw: dict[str, Any]) -> Parameter:
    """Convert one introspected parameter into the canonical model."""
    kind_raw = raw.get("kind") or "option"
    kind = (
        ParamKind.POSITIONAL
        if kind_raw == "positional"
        else ParamKind.FLAG
        if kind_raw == "flag"
        else ParamKind.OPTION
    )
    declared = str(raw.get("type") or "string")
    default = raw.get("default")
    if default is not None:
        expected: dict[str, type | tuple[type, ...]] = {
            "boolean": bool,
            "integer": int,
            "number": (int, float),
            "string": str,
            "array": list,
        }
        if not isinstance(default, expected.get(declared, object)):
            default = coerce_default(declared, str(default))
    choices = raw.get("choices")
    return Parameter(
        name=str(raw.get("name") or "arg"),
        kind=kind,
        cli_name=raw.get("cli_name"),
        short=raw.get("short"),
        type=declared,
        description=raw.get("description") or None,
        required=bool(raw.get("required", False)),
        default=default,
        choices=list(choices) if choices else None,
        repeatable=bool(raw.get("repeatable", False)),
        metavar=raw.get("metavar"),
    )


def commands_from_payload(payload: dict[str, Any], target: TargetInfo, prefix: bool) -> list[CommandSpec]:
    """Convert introspected command entries into :class:`CommandSpec` objects."""
    commands: list[CommandSpec] = []
    for raw in payload.get("commands", []):
        if not isinstance(raw, dict):
            continue
        path = [str(part) for part in raw.get("path", [])]
        parameters = [parameter_from(item) for item in raw.get("parameters", []) if isinstance(item, dict)]
        has_subcommands = bool(raw.get("has_subcommands"))
        if not path and has_subcommands and not parameters:
            continue  # a bare group is not executable
        binary_name = tool_base(target)
        name_parts = ([binary_name] if prefix else []) + (path or [binary_name])
        description = str(raw.get("description") or "").strip() or f"Run {' '.join([target.binary, *path])}".strip()
        commands.append(
            CommandSpec(
                name="_".join(name_parts),
                path=path,
                description=description,
                parameters=parameters,
                provider=f"reflection-{target.origin}",
                examples=[f"{target.binary} {' '.join(path)}".strip()],
                has_subcommands=has_subcommands,
            )
        )
    return commands
