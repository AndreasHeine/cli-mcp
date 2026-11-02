"""Recursive help walk: turn help pages into :class:`CommandSpec` definitions.

The generic help strategy and every framework grammar provider share this walk;
providers only contribute a *preprocess* hook (to normalise their own marker
spellings) and a *refine* hook (to adjust the resulting command).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo, launch_for
from cli_mcp.discovery.base import DiscoveryContext, HelpResult
from cli_mcp.discovery.help_parser import ParsedHelp, is_help_noise, parse_help
from cli_mcp.models import CommandSpec, DiscoveryResult, Parameter, ParamKind, sanitize_tool_name

SKIP_SUBCOMMANDS = frozenset(
    {
        "help",
        "completion",
        "completions",
        "__complete",
        "__complete_no_color",
        "--help",
        "-h",
        "--version",
    }
)

SKIP_PARAMETERS = frozenset({"help", "h", "?", "install_completion", "show_completion", "completion"})

Preprocess = Callable[[str], str]
Refine = Callable[[CommandSpec, HelpResult], CommandSpec]


def coerce_default(type_name: str, value: str | None) -> Any:
    """Convert a help-text default into the declared JSON Schema type."""
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("'")
    lowered = cleaned.lower()
    if not cleaned or lowered in {"none", "null", "nil"}:
        return None
    if type_name == "boolean":
        if lowered in {"true", "yes", "1", "on"}:
            return True
        if lowered in {"false", "no", "0", "off"}:
            return False
        return None
    if type_name == "integer":
        try:
            return int(lowered)
        except ValueError:
            return None
    if type_name == "number":
        try:
            return float(lowered)
        except ValueError:
            return None
    return cleaned


def parameters_from(parsed: ParsedHelp) -> list[Parameter]:
    """Build parameters from a parsed help page, skipping help boilerplate."""
    parameters: list[Parameter] = []
    for option in parsed.options:
        if option.name.lower() in SKIP_PARAMETERS:
            continue
        description = option.description or (f"Value for --{option.name}" if not option.is_flag else "Toggle flag")
        default = coerce_default(option.type, option.default)
        parameters.append(
            Parameter(
                name=option.name,
                kind=ParamKind.FLAG if option.is_flag else ParamKind.OPTION,
                cli_name=option.name,
                short=option.short,
                type=option.type,
                description=description,
                required=option.required,
                default=default,
                choices=option.choices,
                metavar=option.metavar,
            )
        )
    for positional in parsed.positionals:
        parameters.append(
            Parameter(
                name=positional.name,
                kind=ParamKind.POSITIONAL,
                type=positional.type,
                description=positional.description or f"Positional argument {positional.name}",
                required=positional.required,
            )
        )
    return parameters


def tool_base(target: TargetInfo) -> str:
    """Tool name for the root command: the binary's file name without its suffix."""
    stem = Path(target.resolved_path).stem if target.resolved_path else target.binary
    return sanitize_tool_name(stem or target.binary)


def command_for(
    target: TargetInfo,
    path: list[str],
    parsed: ParsedHelp,
    provider: str,
    help_result: HelpResult | None = None,
    refine: Refine | None = None,
    prefix: str | None = None,
) -> CommandSpec:
    """Build one command definition from a parsed help page."""
    name_parts = ([prefix] if prefix else []) + (path or [tool_base(target)])
    description = parsed.description.strip()
    if not description or is_help_noise(description):
        command_label = " ".join([target.binary, *path])
        description = f"Run {command_label}"
    spec = CommandSpec(
        name="_".join(name_parts),
        path=list(path),
        description=description,
        parameters=parameters_from(parsed),
        provider=provider,
        examples=[f"{target.binary} {' '.join(path)}".strip()],
        has_subcommands=bool(parsed.subcommands),
    )
    if refine is not None and help_result is not None:
        spec = refine(spec, help_result)
    return spec


def discover_from_help(
    target: TargetInfo,
    ctx: DiscoveryContext,
    settings: Settings,
    provider: str,
    preprocess: Preprocess | None = None,
    refine: Refine | None = None,
    child_suffix: str | None = None,
) -> DiscoveryResult:
    """Walk ``--help`` recursively and collect command definitions.

    *child_suffix* is a fallback help flag for subcommands whose ``--help``
    prints nothing, e.g. ``git status --help`` opens a man pager and ``-h`` does not.
    """
    result = DiscoveryResult(
        binary=target.binary,
        resolved_path=target.resolved_path,
        framework=target.framework,
        strategies=[provider],
    )
    prefix = sanitize_tool_name(target.binary) if settings.mcp.tool_prefix else None

    root_result = ctx.help_for(target)
    if not root_result.ok and child_suffix is not None:
        root_result = ctx.help_for(target, suffix=child_suffix)
    root_text = preprocess_text(target.root_help or root_result.text, preprocess)
    if not root_result.ok:
        result.add_warning(f"no help output from {target.binary} --help")
        return result

    limit = settings.discovery.max_commands
    seen: set[tuple[str, ...]] = set()
    queue: list[tuple[list[str], str]] = [([], root_text)]
    commands: list[CommandSpec] = []

    while queue:
        path, text = queue.pop(0)
        if len(commands) >= limit:
            result.add_warning(f"discovery capped at {limit} commands")
            break
        parsed = parse_help(text)
        help_result = ctx.cache.get(tuple([*launch_for(target.resolved_path), *path, ctx.help_argv_suffix]))
        if path and len(path) > settings.discovery.max_depth:
            continue
        emits_root = not path and (parsed.options or not parsed.subcommands)
        if path or emits_root:
            commands.append(command_for(target, path, parsed, provider, help_result, refine, prefix))
        seen.add(tuple(path))
        _enqueue_children(target, ctx, path, parsed, settings, seen, queue, result, child_suffix, preprocess)

    result.commands = commands
    return result


def _enqueue_children(
    target: TargetInfo,
    ctx: DiscoveryContext,
    path: list[str],
    parsed: ParsedHelp,
    settings: Settings,
    seen: set[tuple[str, ...]],
    queue: list[tuple[list[str], str]],
    result: DiscoveryResult,
    child_suffix: str | None,
    preprocess: Preprocess | None,
) -> None:
    """Fetch and queue the help page of every subcommand below *path*."""
    if len(path) >= settings.discovery.max_depth:
        return
    for subcommand in sorted(parsed.subcommands, key=lambda item: item.name):
        name = subcommand.name
        if name.lower() in SKIP_SUBCOMMANDS or (tuple([*path, name]) in seen):
            continue
        child = ctx.help_for(target, [*path, name])
        if not child.ok and child_suffix is not None:
            child = ctx.help_for(target, [*path, name], suffix=child_suffix)
        if not child.ok:
            result.add_warning(f"no help output for {target.binary} {' '.join([*path, name])} --help")
            continue
        queue.append(([*path, name], preprocess_text(child.text, preprocess)))


def preprocess_text(text: str, preprocess: Preprocess | None) -> str:
    """Apply a provider-specific preprocessing step to help text."""
    return preprocess(text) if preprocess is not None else text
