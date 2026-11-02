"""Transport selection: stdio, Streamable HTTP, JSON-over-HTTP and SSE."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from cli_mcp.config.settings import ServerSettings
from cli_mcp.errors import TransportError

SSE_MESSAGE_PATH = "/messages/"


def run_server(server: MCPServer, settings: ServerSettings) -> None:
    """Start *server* on the configured transport and block until it exits."""
    if settings.transport == "stdio":
        server.run("stdio")
        return
    if settings.transport == "streamable-http":
        server.run(
            "streamable-http",
            host=settings.host,
            port=settings.port,
            streamable_http_path=settings.path,
            json_response=settings.json_response,
            stateless_http=settings.stateless_http,
        )
        return
    if settings.transport == "http":
        # Plain HTTP clients get JSON responses; MCP clients use the same endpoint.
        server.run(
            "streamable-http",
            host=settings.host,
            port=settings.port,
            streamable_http_path=settings.path,
            json_response=True,
            stateless_http=settings.stateless_http,
        )
        return
    if settings.transport == "sse":
        # Server-Sent Events is deprecated in the MCP spec; prefer streamable-http.
        server.run(
            "sse",
            host=settings.host,
            port=settings.port,
            sse_path=settings.path,
            message_path=SSE_MESSAGE_PATH,
        )
        return
    raise TransportError(f"unknown transport {settings.transport!r}; use stdio, http, streamable-http or sse")
