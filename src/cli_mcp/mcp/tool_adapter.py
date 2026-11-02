"""Adapting a discovered command into an MCP tool with a faithful input schema."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from pydantic import WithJsonSchema

from cli_mcp.config.settings import Settings
from cli_mcp.errors import SecurityViolation
from cli_mcp.executor.approval import ApprovalGate
from cli_mcp.executor.argv import build_argv
from cli_mcp.executor.runner import run
from cli_mcp.models import CommandSpec
from cli_mcp.schema.jsonschema import input_schema
from cli_mcp.schema.validate import validate_arguments
from cli_mcp.security.policy import AccessPolicy

#: Control argument clients use to approve a risky execution.
APPROVE_ARGUMENT = "approve"
APPROVE_SCHEMA: dict[str, Any] = {
    "type": "boolean",
    "description": "Set true to approve this execution when the security policy requires approval.",
}


@dataclass(frozen=True)
class ToolDefinition:
    """One MCP tool: name, description, exact input schema and async handler."""

    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[..., Awaitable[str]]


def tool_description(spec: CommandSpec, binary: str, policy: AccessPolicy) -> str:
    """Tool description: what the command does plus its security status."""
    parts = [spec.description or f"Run {spec.invocation(binary)}"]
    parts.append(f"Runs the CLI command `{spec.invocation(binary)}`.")
    if spec.destructive or policy.assess(binary, spec).destructive:
        parts.append("This command is considered destructive and needs approval before it runs.")
    if spec.examples:
        parts.append("Example: " + spec.examples[0])
    return " ".join(parts)


def build_tool(
    spec: CommandSpec,
    launch: list[str],
    settings: Settings,
    policy: AccessPolicy,
    gate: ApprovalGate,
    cwd: Path | None = None,
) -> ToolDefinition:
    """Build an MCP tool for one discovered command.

    *launch* is the command that runs the CLI: an interpreter prefix when the
    target is a script, otherwise the resolved binary path.
    """
    schema = input_schema(spec)
    risk = policy.assess(settings.binary, spec).destructive
    approval_enabled = settings.security.approval or spec.destructive or risk
    published = dict(schema)
    properties = dict(published.get("properties", {}))
    if approval_enabled:
        properties[APPROVE_ARGUMENT] = dict(APPROVE_SCHEMA)
    published["properties"] = properties
    published["additionalProperties"] = False

    async def handler(**arguments: Any) -> str:
        """Validate, gate and run the command, returning the execution payload as JSON."""
        approve = bool(arguments.get(APPROVE_ARGUMENT, False))
        payload_arguments = {key: value for key, value in arguments.items() if key != APPROVE_ARGUMENT}
        validated = validate_arguments(spec, payload_arguments)
        argv = build_argv(launch, spec, validated)
        decision = policy.evaluate(settings.binary, spec, argv)
        if not decision.allowed:
            raise SecurityViolation(decision.reason or "command rejected by security policy")
        gate.approve(spec.name, argv, decision, approved=approve)
        result = await asyncio.to_thread(run, argv, settings.security, cwd)
        return json.dumps(result.as_payload())

    handler.__doc__ = published.get("description") or spec.description
    handler.__signature__ = _signature(published, approval_enabled)  # type: ignore[attr-defined]
    description = tool_description(spec, settings.binary, policy)
    return ToolDefinition(name=spec.name, description=description, schema=published, handler=handler)


def _signature(schema: dict[str, Any], approval_enabled: bool) -> inspect.Signature:
    """Keyword-only signature whose JSON Schema matches *schema* exactly."""
    parameters: list[inspect.Parameter] = []
    for name, definition in schema.get("properties", {}).items():
        annotation = Annotated[Any, WithJsonSchema(definition)]
        required = name in schema.get("required", [])
        default = inspect.Parameter.empty if required else None
        parameters.append(
            inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation)
        )
    if approval_enabled and APPROVE_ARGUMENT not in schema.get("properties", {}):
        parameters.append(
            inspect.Parameter(
                APPROVE_ARGUMENT,
                inspect.Parameter.KEYWORD_ONLY,
                default=False,
                annotation=Annotated[Any, WithJsonSchema(APPROVE_SCHEMA)],
            )
        )
    return inspect.Signature(parameters, return_annotation=str)


def docs_tool_name(binary: str) -> str:
    """Name of the generated documentation tool."""
    from pathlib import Path

    from cli_mcp.models import sanitize_tool_name

    stem = Path(binary).stem or binary
    return sanitize_tool_name(f"{stem}_docs")


def build_docs_tool(docs: str, name: str) -> ToolDefinition:
    """Build a tool that returns the generated Markdown documentation for the CLI."""

    async def handler() -> str:
        """Return the generated documentation."""
        return docs

    handler.__signature__ = inspect.Signature([], return_annotation=str)  # type: ignore[attr-defined]
    description = (
        "Documentation for this CLI: list every tool, its arguments and example invocations before running commands."
    )
    return ToolDefinition(
        name=name,
        description=description,
        schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
    )
