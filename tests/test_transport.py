"""Tests for transport selection."""

from typing import Any

import pytest

from cli_mcp.config.settings import ServerSettings
from cli_mcp.errors import TransportError
from cli_mcp.transport import SSE_MESSAGE_PATH, run_server


class RecordingServer:
    """Stand-in for MCPServer that records the run() call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, transport: str, **kwargs: Any) -> None:
        self.calls.append((transport, kwargs))


def server_settings(**overrides: Any) -> ServerSettings:
    """Server settings with only the transport knobs a test cares about."""
    return ServerSettings(**overrides)


def test_stdio_transport_is_plain() -> None:
    server = RecordingServer()
    run_server(server, server_settings(transport="stdio"))
    assert server.calls == [("stdio", {})]


def test_streamable_http_transport_passes_endpoint_options() -> None:
    server = RecordingServer()
    run_server(
        server,
        server_settings(transport="streamable-http", host="0.0.0.0", port=9000, path="/mcp", stateless_http=True),
    )
    transport, kwargs = server.calls[0]
    assert transport == "streamable-http"
    assert kwargs == {
        "host": "0.0.0.0",
        "port": 9000,
        "streamable_http_path": "/mcp",
        "json_response": False,
        "stateless_http": True,
    }


def test_http_transport_forces_json_responses() -> None:
    server = RecordingServer()
    run_server(server, server_settings(transport="http", port=8802, json_response=False))
    transport, kwargs = server.calls[0]
    assert transport == "streamable-http"
    assert kwargs["json_response"] is True
    assert kwargs["port"] == 8802


def test_sse_transport_uses_the_message_endpoint() -> None:
    server = RecordingServer()
    run_server(server, server_settings(transport="sse", host="127.0.0.1", port=8803, path="/sse"))
    transport, kwargs = server.calls[0]
    assert transport == "sse"
    assert kwargs["sse_path"] == "/sse"
    assert kwargs["message_path"] == SSE_MESSAGE_PATH


def test_unknown_transport_is_rejected() -> None:
    settings = server_settings()
    settings.transport = "grpc"  # bypasses the typed settings, as a malformed config would
    with pytest.raises(TransportError, match="unknown transport 'grpc'"):
        run_server(RecordingServer(), settings)
