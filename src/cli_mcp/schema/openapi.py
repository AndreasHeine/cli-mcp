"""OpenAPI export: each MCP tool becomes an endpoint, plus the result schema."""

from __future__ import annotations

from typing import Any

from cli_mcp.config.settings import ServerSettings
from cli_mcp.models import DiscoveryResult
from cli_mcp.schema.jsonschema import execution_result_schema, input_schema

OPENAPI_VERSION = "3.1.0"


def tool_endpoint(command: Any, binary: str) -> dict[str, Any]:
    """Build the OpenAPI operation for one MCP tool."""
    description = command.description or f"Run {command.invocation(binary)}"
    return {
        "description": description,
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": input_schema(command)}},
        },
        "responses": {
            "200": {
                "description": "CLI execution result",
                "content": {"application/json": {"schema": execution_result_schema()}},
            },
            "400": {"description": "Arguments rejected by schema validation"},
            "403": {"description": "Rejected by the security policy (allow list, read-only mode or approval)"},
        },
    }


def build_openapi(result: DiscoveryResult, server: ServerSettings | None = None) -> dict[str, Any]:
    """Build an OpenAPI 3.1 document describing the published tools."""
    settings = server or ServerSettings(name=result.binary)
    paths: dict[str, Any] = {}
    for command in result.commands:
        paths[f"/tools/{command.name}"] = {"post": tool_endpoint(command, result.binary)}
    document: dict[str, Any] = {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": settings.title or settings.name or result.binary,
            "description": settings.description or f"{result.binary} exposed as an MCP server by cli-mcp",
            "version": settings.version or "0.1.0",
        },
        "paths": paths,
        "components": {"schemas": {"ExecutionResult": execution_result_schema()}},
        "x-cli-mcp": {
            "binary": result.binary,
            "framework": result.framework,
            "strategies": result.strategies,
            "transport": settings.transport,
            "tool_count": len(result.commands),
        },
    }
    return document
