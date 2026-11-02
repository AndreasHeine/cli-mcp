"""Typed configuration for cli-mcp.

Everything the tool needs is expressed here: which binary to expose, how to
discover it, how to execute it and how to publish it over MCP.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TransportName = Literal["stdio", "http", "streamable-http", "sse"]
ApprovalMode = Literal["auto", "prompt", "explicit"]
DEFAULT_STRATEGIES: tuple[str, ...] = ("reflection", "help", "manifest")


class SandboxSettings(BaseModel):
    """Run the exposed CLI inside a container runtime."""

    model_config = ConfigDict(extra="forbid")

    backend: Literal["docker", "podman"] = "docker"
    image: str = "alpine:3.20"
    workdir_mount: bool = Field(True, description="Mount the current directory into the container")
    container_workdir: str = "/work"
    network: bool = False
    extra_args: list[str] = Field(default_factory=list)

    @field_validator("image")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sandbox image must be non-empty")
        return value.strip()


class SecuritySettings(BaseModel):
    """Allow list, read-only mode, approval gate and execution limits."""

    model_config = ConfigDict(extra="forbid")

    allowlist: list[str] = Field(default_factory=list, description="Binaries that may be exposed")
    readonly: bool = False
    approval: bool = False
    approval_mode: ApprovalMode = "auto"
    block_patterns: list[str] = Field(default_factory=list, description="Extra regexes rejected in argv")
    allow_patterns: list[str] = Field(default_factory=list, description="Regexes that re-admit blocked verbs")
    timeout_seconds: float = Field(60.0, gt=0)
    max_output_bytes: int = Field(200_000, gt=0)
    sandbox: SandboxSettings | None = None

    @field_validator("allowlist")
    @classmethod
    def _normalise_allowlist(cls, value: list[str]) -> list[str]:
        return [item.strip().lower() for item in value if item.strip()]

    @field_validator("block_patterns", "allow_patterns")
    @classmethod
    def _strip_patterns(cls, value: list[str]) -> list[str]:
        return [item for item in value if item.strip()]


class DiscoverySettings(BaseModel):
    """Strategy order and limits for CLI discovery."""

    model_config = ConfigDict(extra="forbid")

    strategies: list[str] = Field(default_factory=lambda: list(DEFAULT_STRATEGIES))
    include: list[str] | None = None
    exclude: list[str] | None = None
    max_depth: int = Field(2, ge=0, le=6)
    max_commands: int = Field(120, ge=1, le=1000)
    allow_import_reflection: bool = Field(
        False,
        description="Allow Python/Node reflection, which imports the target module and may run code",
    )
    help_timeout_seconds: float = Field(10.0, gt=0)

    @field_validator("strategies")
    @classmethod
    def _ordered(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for item in value:
            name = item.strip().lower()
            if name and name not in seen:
                seen.append(name)
        return seen or list(DEFAULT_STRATEGIES)


class ServerSettings(BaseModel):
    """MCP server identity and transport choice."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    title: str | None = None
    description: str | None = None
    instructions: str | None = None
    version: str = Field("0.1.0", description="Server version reported over MCP")
    transport: TransportName = "stdio"
    host: str = "127.0.0.1"
    port: int = Field(8801, ge=1, le=65535)
    path: str = "/mcp"
    json_response: bool = False
    stateless_http: bool = False
    include_docs_tool: bool = True
    tool_prefix: bool = Field(
        False,
        description="Prefix tool names with the binary name, to avoid collisions when exposing several CLIs",
    )

    @field_validator("path")
    @classmethod
    def _leading_slash(cls, value: str) -> str:
        return value if value.startswith("/") else f"/{value}"


class Settings(BaseModel):
    """Complete configuration for one exposed binary."""

    model_config = ConfigDict(extra="forbid")

    binary: str
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    discovery: DiscoverySettings = Field(default_factory=DiscoverySettings)
    mcp: ServerSettings = Field(default_factory=ServerSettings)
    manifest: str | None = Field(None, description="Optional manifest file that overrides discovery")

    @field_validator("binary")
    @classmethod
    def _binary_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("binary must be non-empty")
        return cleaned

    @property
    def server_name(self) -> str:
        """Default MCP server name derived from the binary."""
        from cli_mcp.models import sanitize_tool_name

        return self.mcp.name or sanitize_tool_name(self.binary)
