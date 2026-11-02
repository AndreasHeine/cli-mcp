"""MCP layer: tool adapters and server construction."""

from __future__ import annotations

from cli_mcp.mcp.server import build_server, publish_schema, tool_definitions, tool_schemas
from cli_mcp.mcp.tool_adapter import (
    APPROVE_ARGUMENT,
    APPROVE_SCHEMA,
    ToolDefinition,
    build_docs_tool,
    build_tool,
    docs_tool_name,
)

__all__ = [
    "APPROVE_ARGUMENT",
    "APPROVE_SCHEMA",
    "ToolDefinition",
    "build_docs_tool",
    "build_server",
    "build_tool",
    "docs_tool_name",
    "publish_schema",
    "tool_definitions",
    "tool_schemas",
]
