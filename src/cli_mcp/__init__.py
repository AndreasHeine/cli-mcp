"""cli-mcp: expose any command-line application as a compliant MCP server."""

from cli_mcp.errors import (
    ApprovalRequired,
    BinaryNotFoundError,
    CliMcpError,
    ConfigError,
    DiscoveryError,
    ExecutionError,
    SchemaError,
    SecurityViolation,
    TransportError,
)
from cli_mcp.models import CommandSpec, DiscoveryResult, Parameter, ParamKind
from cli_mcp.version import __version__

__all__ = [
    "ApprovalRequired",
    "BinaryNotFoundError",
    "CliMcpError",
    "CommandSpec",
    "ConfigError",
    "DiscoveryError",
    "DiscoveryResult",
    "ExecutionError",
    "ParamKind",
    "Parameter",
    "SchemaError",
    "SecurityViolation",
    "TransportError",
    "__version__",
]
