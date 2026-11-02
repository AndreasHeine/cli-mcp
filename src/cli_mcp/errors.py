"""Errors raised across cli-mcp layers."""


class CliMcpError(Exception):
    """Base class for every cli-mcp failure."""


class ConfigError(CliMcpError):
    """Configuration could not be read or is invalid."""


class BinaryNotFoundError(CliMcpError):
    """The requested binary is not installed or not on the allow list."""


class DiscoveryError(CliMcpError):
    """Discovery produced no usable command definitions."""


class SchemaError(CliMcpError):
    """A tool definition or argument payload failed validation."""


class SecurityViolation(CliMcpError):
    """A request was rejected by the security policy."""


class ApprovalRequired(SecurityViolation):
    """The request needs a human decision before it can run."""


class ExecutionError(CliMcpError):
    """The underlying process could not be started or failed unexpectedly."""


class TransportError(CliMcpError):
    """The requested MCP transport is unavailable."""
