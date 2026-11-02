"""Strategy 3: user-provided manifest metadata, which overrides discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from cli_mcp.config.loader import find_config_file, load_yaml, unwrap
from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo
from cli_mcp.discovery.base import DiscoveryContext
from cli_mcp.errors import ConfigError
from cli_mcp.models import CommandSpec, DiscoveryResult, Parameter, sanitize_tool_name


@dataclass(frozen=True)
class ManifestDocument:
    """The parts of a manifest that affect discovery."""

    path: Path | None = None
    binary: str | None = None
    tools: list[CommandSpec] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


def manifest_path(settings: Settings, cwd: Path | None = None) -> Path | None:
    """Locate the manifest file: explicit path first, then a config file in *cwd*."""
    if settings.manifest:
        explicit = Path(settings.manifest)
        if not explicit.is_absolute() and cwd is not None:
            explicit = cwd / explicit
        if explicit.is_file():
            return explicit
        raise ConfigError(f"manifest file {settings.manifest} does not exist")
    if cwd is not None:
        return find_config_file(cwd)
    return None


#: Manifest spellings that map onto :class:`Parameter` fields.
_PARAMETER_ALIASES = {"cli-name": "cli_name", "cliName": "cli_name", "enum": "choices"}


def _parameter_from(raw: dict[str, Any]) -> Parameter:
    """Build a parameter from a manifest entry."""
    payload: dict[str, Any] = {str(key): value for key, value in raw.items()}
    for alias, canonical in _PARAMETER_ALIASES.items():
        if alias in payload and canonical not in payload:
            payload[canonical] = payload.pop(alias)
    name = str(payload.get("name") or "arg")
    payload.setdefault("kind", "option")
    payload.setdefault("type", "string")
    payload["name"] = name
    try:
        return Parameter.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid manifest parameter {name!r}: {exc}") from exc


def _tool_from(raw: dict[str, Any], default_provider: str) -> CommandSpec:
    """Build a command from a manifest entry."""
    payload: dict[str, Any] = dict(raw)
    name = str(payload.get("name") or payload.get("command") or "tool")
    path_value = payload.get("path") or payload.get("command") or name
    path = [str(part) for part in path_value] if isinstance(path_value, list) else str(path_value).split()
    parameters_raw: list[Any] = payload.get("parameters") or []
    parameters = [_parameter_from(item) for item in parameters_raw if isinstance(item, dict)]
    examples_raw: list[Any] = payload.get("examples") or []
    try:
        return CommandSpec(
            name=sanitize_tool_name(name),
            path=path,
            description=str(payload.get("description") or ""),
            parameters=parameters,
            provider=default_provider,
            examples=[str(item) for item in examples_raw],
            destructive=bool(payload.get("destructive", False)),
            has_subcommands=bool(payload.get("has_subcommands", False)),
        )
    except ValidationError as exc:
        raise ConfigError(f"Invalid manifest tool {name!r}: {exc}") from exc


def read_manifest(settings: Settings, cwd: Path | None = None) -> ManifestDocument:
    """Read manifest metadata from the configured file, if there is one."""
    path = manifest_path(settings, cwd)
    if path is None:
        return ManifestDocument()
    payload: dict[str, Any] = unwrap(load_yaml(path))
    tools_raw: list[Any] = payload.get("tools") or []
    tools = [_tool_from(item, "manifest") for item in tools_raw if isinstance(item, dict)]
    include = [str(item) for item in (payload.get("include") or [])]
    exclude = [str(item) for item in (payload.get("exclude") or [])]
    binary = payload.get("binary")
    return ManifestDocument(
        path=path,
        binary=str(binary) if binary else None,
        tools=tools,
        include=include,
        exclude=exclude,
    )


class ManifestProvider:
    """Publish commands declared in the manifest; manifest data is authoritative."""

    name = "manifest"
    strategy = "manifest"
    frameworks: tuple[str, ...] = ()

    def __init__(self, settings: Settings) -> None:
        """Store the settings that locate the manifest file."""
        self.settings = settings

    def supports(self, target: TargetInfo) -> bool:
        """Report whether a manifest can apply to any binary; :meth:`discover` decides whether one exists."""
        del target
        return True

    def discover(self, target: TargetInfo, ctx: DiscoveryContext) -> DiscoveryResult | None:
        """Return manifest-declared commands for *target*."""
        document = read_manifest(self.settings, ctx.cwd)
        if not document.tools:
            return None
        return DiscoveryResult(
            binary=target.binary,
            resolved_path=target.resolved_path,
            framework=target.framework or self.name,
            commands=document.tools,
            strategies=[self.name],
            warnings=[f"manifest: {document.path}"] if document.path else [],
        )


def matches(name: str, path: list[str], patterns: list[str]) -> bool:
    """Whether a command matches one of the include/exclude patterns."""
    lowered_name = name.lower()
    lowered_last = path[-1].lower() if path else ""
    for pattern in patterns:
        candidate = pattern.lower().strip()
        if not candidate:
            continue
        if lowered_name == candidate or lowered_last == candidate:
            return True
        if lowered_name.startswith(f"{candidate}_"):
            return True
    return False


def apply_filters(commands: list[CommandSpec], include: list[str], exclude: list[str]) -> list[CommandSpec]:
    """Keep commands matching *include* (when given) and drop those matching *exclude*."""
    kept = commands
    if include:
        kept = [command for command in kept if matches(command.name, command.path, include)]
    if exclude:
        kept = [command for command in kept if not matches(command.name, command.path, exclude)]
    return kept
