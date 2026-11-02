"""Strategy 1 for Python CLIs: reflect on click, typer and argparse objects."""

from __future__ import annotations

import os

from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo
from cli_mcp.discovery.base import DiscoveryContext
from cli_mcp.discovery.reflection_payload import commands_from_payload, parse_payload
from cli_mcp.models import DiscoveryResult

MODULE = "cli_mcp.discovery.introspect"


class PythonReflectionProvider:
    """Import a Python CLI in a subprocess and read its declared command objects."""

    name = "reflection-python"
    strategy = "reflection"
    frameworks: tuple[str, ...] = ("python", "click", "typer", "argparse")

    def __init__(self, settings: Settings) -> None:
        """Store the settings that gate reflection."""
        self.settings = settings

    def supports(self, target: TargetInfo) -> bool:
        """Reflection imports the target, so it needs a Python target and explicit opt-in."""
        if not self.settings.discovery.allow_import_reflection:
            return False
        return target.origin == "python"

    def discover(self, target: TargetInfo, ctx: DiscoveryContext) -> DiscoveryResult | None:
        """Run the introspection helper and convert its JSON document."""
        interpreter = os.environ.get("CLI_MCP_PYTHON") or ctx.interpreter("python")
        if not interpreter:
            return None
        argv = [interpreter, "-m", MODULE, "--target", target.resolved_path]
        help_result = ctx.run(argv, timeout=self.settings.discovery.help_timeout_seconds)
        payload = parse_payload(help_result.stdout)
        if payload is None:
            return None
        commands = commands_from_payload(payload, target, self.settings.mcp.tool_prefix)
        if not commands:
            return None
        warnings = [f"reflection error: {payload['error']}"] if payload.get("error") else []
        return DiscoveryResult(
            binary=target.binary,
            resolved_path=target.resolved_path,
            framework=payload.get("framework") or target.framework,
            commands=commands,
            strategies=[self.name],
            warnings=warnings,
        )
