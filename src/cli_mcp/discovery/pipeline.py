"""Discovery orchestration: configured strategies, then the manifest override."""

from __future__ import annotations

from pathlib import Path

from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo
from cli_mcp.discovery.base import DiscoveryContext
from cli_mcp.discovery.manifest import apply_filters, read_manifest
from cli_mcp.discovery.registry import ProviderRegistry
from cli_mcp.errors import DiscoveryError
from cli_mcp.models import CommandSpec, DiscoveryResult


def discover(
    target: TargetInfo,
    settings: Settings,
    ctx: DiscoveryContext | None = None,
    registry: ProviderRegistry | None = None,
) -> DiscoveryResult:
    """Run the configured strategies and merge manifest metadata into the result."""
    context = ctx or DiscoveryContext(settings.discovery, cwd=Path.cwd())
    provider_registry = registry or ProviderRegistry(settings)
    manifest = read_manifest(settings, context.cwd)

    result: DiscoveryResult | None = None
    strategies: list[str] = []
    for strategy in settings.discovery.strategies:
        found = provider_registry.run(strategy, target, context)
        if found is not None and found.commands:
            result = found
            strategies.extend(found.strategies or [strategy])
            break

    commands = list(result.commands) if result is not None else []
    warnings = list(result.warnings) if result is not None else []
    if result is None:
        warnings.append(f"no commands discovered by strategies: {', '.join(settings.discovery.strategies)}")

    if manifest.tools:
        commands = merge_manifest(commands, manifest.tools, warnings)
        strategies.append("manifest")

    include = list(settings.discovery.include or []) + manifest.include
    exclude = list(settings.discovery.exclude or []) + manifest.exclude
    if include or exclude:
        filtered = apply_filters(commands, include, exclude)
        if len(filtered) < len(commands):
            dropped = len(commands) - len(filtered)
            warnings.append(f"filtered out {dropped} command(s) by include/exclude")
        commands = filtered

    commands = _dedupe(commands, warnings)
    if len(commands) > settings.discovery.max_commands:
        commands = commands[: settings.discovery.max_commands]
        warnings.append(f"discovery capped at {settings.discovery.max_commands} commands")

    if manifest.binary and manifest.binary != target.binary:
        warnings.append(f"manifest declares binary {manifest.binary!r}, exposing {target.binary!r}")
    if not commands:
        raise DiscoveryError(
            f"no commands found for {target.binary!r}. Check the binary, or declare commands in a cli-mcp manifest."
        )

    return DiscoveryResult(
        binary=target.binary,
        resolved_path=target.resolved_path,
        framework=result.framework if result is not None else ("manifest" if manifest.tools else None),
        commands=commands,
        strategies=_ordered_unique(strategies),
        warnings=warnings,
    )


def merge_manifest(commands: list[CommandSpec], tools: list[CommandSpec], warnings: list[str]) -> list[CommandSpec]:
    """Manifest entries replace discovered commands of the same tool name."""
    merged: dict[str, CommandSpec] = {command.name: command for command in commands}
    for tool in tools:
        if tool.name in merged:
            warnings.append(f"manifest overrides tool {tool.name!r}")
        merged[tool.name] = tool
    ordered = list(commands) + [tool for tool in tools if tool.name not in {command.name for command in commands}]
    return [merged[command.name] for command in ordered]


def _dedupe(commands: list[CommandSpec], warnings: list[str]) -> list[CommandSpec]:
    """Drop later commands whose tool name already exists."""
    seen: set[str] = set()
    kept: list[CommandSpec] = []
    for command in commands:
        if command.name in seen:
            warnings.append(f"duplicate tool name {command.name!r} dropped")
            continue
        seen.add(command.name)
        kept.append(command)
    return kept


def _ordered_unique(items: list[str]) -> list[str]:
    """Return unique items, preserving first-seen order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
