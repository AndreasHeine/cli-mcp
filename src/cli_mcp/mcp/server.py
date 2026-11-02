"""Build a fully MCP-compliant server from discovered commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from cli_mcp.config.settings import Settings
from cli_mcp.detect import launch_for
from cli_mcp.errors import SchemaError
from cli_mcp.executor.approval import ApprovalGate
from cli_mcp.mcp.tool_adapter import ToolDefinition, build_docs_tool, build_tool, docs_tool_name
from cli_mcp.models import DiscoveryResult
from cli_mcp.schema.docgen import render_docs
from cli_mcp.security.policy import AccessPolicy


def tool_definitions(settings: Settings, result: DiscoveryResult, cwd: Path | None = None) -> list[ToolDefinition]:
    """Tool definitions for *result*, usable for exports without a server."""
    policy = AccessPolicy(settings.security)
    policy.authorize_binary(settings.binary)
    resolved = result.resolved_path or settings.binary
    launch = launch_for(resolved)
    gate = ApprovalGate(settings.security)
    definitions = [build_tool(spec, launch, settings, policy, gate, cwd) for spec in result.commands]
    if settings.mcp.include_docs_tool:
        definitions.append(build_docs_tool(render_docs(result, settings.mcp), docs_tool_name(resolved)))
    return definitions


def build_server(
    settings: Settings,
    result: DiscoveryResult,
    cwd: Path | None = None,
    gate: ApprovalGate | None = None,
) -> MCPServer:
    """Create an MCP server that publishes every discovered command as a tool."""
    policy = AccessPolicy(settings.security)
    policy.authorize_binary(settings.binary)
    resolved = result.resolved_path or settings.binary
    launch = launch_for(resolved)
    approval_gate = gate or ApprovalGate(settings.security)
    server = MCPServer(
        name=settings.server_name,
        title=settings.mcp.title,
        description=settings.mcp.description,
        instructions=settings.mcp.instructions,
        version=settings.mcp.version,
    )
    for spec in result.commands:
        tool = build_tool(spec, launch, settings, policy, approval_gate, cwd)
        server.add_tool(tool.handler, name=tool.name, description=tool.description)
        publish_schema(server, tool.name, tool.schema)
    if settings.mcp.include_docs_tool:
        docs_tool = build_docs_tool(render_docs(result, settings.mcp), docs_tool_name(resolved))
        server.add_tool(docs_tool.handler, name=docs_tool.name, description=docs_tool.description)
        publish_schema(server, docs_tool.name, docs_tool.schema)
    return server


def publish_schema(server: MCPServer, name: str, schema: dict[str, Any]) -> None:
    """Replace the SDK-derived input schema with cli-mcp's exact schema.

    The SDK derives schemas from the handler signature; cli-mcp synthesises that
    signature from the discovered metadata, and then pins the published schema so
    descriptions, enums and defaults survive exactly as discovered.
    """
    manager = server._tool_manager
    tool = manager.get_tool(name)
    if tool is None:
        raise SchemaError(f"tool {name!r} is not published on the server")
    tool.parameters = schema


def tool_schemas(server: MCPServer) -> dict[str, dict[str, Any]]:
    """Return the published input schemas by tool name, used by ``cli-mcp export-schema``."""
    manager = server._tool_manager
    return {tool.name: dict(tool.parameters) for tool in manager.list_tools()}
