"""End-to-end orchestration: config, binary detection, discovery, schemas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cli_mcp.config.loader import load_settings
from cli_mcp.config.settings import ApprovalMode, Settings
from cli_mcp.detect import TargetInfo, fingerprint, launch_for, resolve_binary
from cli_mcp.discovery.base import DiscoveryContext
from cli_mcp.discovery.pipeline import discover
from cli_mcp.models import DiscoveryResult
from cli_mcp.plugins import registry_with_plugins
from cli_mcp.security.policy import AccessPolicy


@dataclass(frozen=True)
class PreparedCli:
    """Everything needed to publish one binary as an MCP server."""

    settings: Settings
    target: TargetInfo
    result: DiscoveryResult

    @property
    def binary_path(self) -> str:
        """Absolute path of the resolved CLI binary."""
        return self.result.resolved_path or self.target.resolved_path

    @property
    def launch(self) -> list[str]:
        """Command that runs the CLI: interpreter plus script path when needed."""
        return launch_for(self.binary_path)


def _apply_server_overrides(settings: Settings, flags: dict[str, Any]) -> None:
    """Apply transport and publishing flags."""
    if flags.get("transport"):
        settings.mcp.transport = str(flags["transport"])  # type: ignore[assignment]
    if flags.get("host"):
        settings.mcp.host = str(flags["host"])
    if flags.get("port"):
        settings.mcp.port = int(flags["port"])
    if flags.get("tool_prefix") is not None:
        settings.mcp.tool_prefix = bool(flags["tool_prefix"])
    if flags.get("docs") is not None:
        settings.mcp.include_docs_tool = bool(flags["docs"])


def _apply_security_overrides(settings: Settings, flags: dict[str, Any]) -> None:
    """Apply allow list, read-only, approval and timeout flags."""
    if flags.get("readonly") is not None:
        settings.security.readonly = bool(flags["readonly"])
    if flags.get("approval") is not None:
        settings.security.approval = bool(flags["approval"])
    if flags.get("approval_mode"):
        settings.security.approval_mode = str(flags["approval_mode"])  # type: ignore[assignment]
    allow = flags.get("allow")
    if allow:
        settings.security.allowlist = [item.strip() for item in allow if item.strip()]
    if flags.get("timeout"):
        settings.security.timeout_seconds = float(flags["timeout"])


def _apply_discovery_overrides(settings: Settings, flags: dict[str, Any]) -> None:
    """Apply strategy, filter and depth flags."""
    if flags.get("strategies"):
        settings.discovery.strategies = list(flags["strategies"])
    if flags.get("include"):
        settings.discovery.include = list(flags["include"])
    if flags.get("exclude"):
        settings.discovery.exclude = list(flags["exclude"])
    if flags.get("max_depth") is not None:
        settings.discovery.max_depth = int(flags["max_depth"])
    if flags.get("allow_reflection") is not None:
        settings.discovery.allow_import_reflection = bool(flags["allow_reflection"])


def apply_overrides(settings: Settings, **flags: Any) -> Settings:
    """Apply command-line overrides onto a settings object."""
    _apply_server_overrides(settings, flags)
    _apply_security_overrides(settings, flags)
    _apply_discovery_overrides(settings, flags)
    return settings


def prepare(
    binary: str | None = None,
    config: str | Path | None = None,
    cwd: Path | None = None,
    overrides: dict[str, Any] | None = None,
    *,
    load_plugins: bool = True,
) -> PreparedCli:
    """Resolve *binary*, discover its commands and build the settings for it."""
    working_dir = cwd or Path.cwd()
    config_path = Path(config) if isinstance(config, str) else config
    settings = load_settings(path=config_path, binary=binary, cwd=working_dir)
    if overrides:
        apply_overrides(settings, **overrides)

    working_dir = settings.execution.cwd or working_dir
    AccessPolicy(settings.security).authorize_binary(settings.binary)
    target = resolve_binary(settings.binary)
    help_suffix = "-h" if Path(target.resolved_path).stem.casefold() == "git" else "--help"
    context = DiscoveryContext(settings.discovery, cwd=working_dir, help_argv_suffix=help_suffix)

    if target.framework is None:
        root_help = context.help_for(target)
        if root_help.ok:
            detected = fingerprint(root_help.text)
            if detected:
                target = target.with_help(root_help.text)

    registry = registry_with_plugins(settings, load_plugins=load_plugins)
    result = discover(target, settings, context, registry)
    return PreparedCli(settings=settings, target=target, result=result)


def transport_endpoint(settings: Settings) -> str:
    """Where the server listens, for user-facing output."""
    if settings.mcp.transport == "stdio":
        return "stdio"
    if settings.mcp.transport == "sse":
        return f"http://{settings.mcp.host}:{settings.mcp.port}{settings.mcp.path} (SSE, deprecated)"
    return f"http://{settings.mcp.host}:{settings.mcp.port}{settings.mcp.path}"


def approval_mode(settings: Settings) -> ApprovalMode:
    """Return the active approval mode."""
    return settings.security.approval_mode
