"""Markdown documentation generated from discovered command metadata."""

from __future__ import annotations

from pathlib import Path

from cli_mcp.config.settings import ServerSettings
from cli_mcp.models import CommandSpec, DiscoveryResult, Parameter
from cli_mcp.schema.jsonschema import argument_name, cli_hint


def _display_binary(binary: str) -> str:
    """Return the name a user types, not the absolute path that resolved it."""
    return Path(binary).name if "\\" in binary or "/" in binary else binary


def _escape(text: str) -> str:
    """Make text safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def _arguments_table(command: CommandSpec) -> list[str]:
    """Markdown table rows for a command's parameters."""
    lines = ["| Argument | CLI | Type | Required | Default | Description |", "| --- | --- | --- | --- | --- | --- |"]
    for param in command.parameters:
        default = "" if param.default is None else str(param.default)
        choices = f" one of: {', '.join(param.choices)}" if param.choices else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    argument_name(param),
                    _escape(cli_hint(param)),
                    param.type,
                    "yes" if param.required else "no",
                    _escape(default),
                    _escape((param.description or "") + choices),
                ]
            )
            + " |"
        )
    return lines


def command_section(command: CommandSpec, binary: str) -> list[str]:
    """Markdown block for one tool."""
    lines = [f"### `{command.name}`", "", command.description or "No description available.", ""]
    lines.append(f"CLI invocation: `{command.invocation(_display_binary(binary))}`")
    lines.append("")
    if command.parameters:
        lines.extend(_arguments_table(command))
        lines.append("")
    else:
        lines.append("This tool takes no arguments.")
        lines.append("")
    if command.examples:
        lines.append("Examples:")
        lines.append("")
        lines.append("```bash")
        display = _display_binary(binary)
        lines.extend(example.replace(f"{binary} ", f"{display} ") for example in command.examples)
        lines.append("```")
        lines.append("")
    if command.destructive:
        lines.append("> **Security:** this command is treated as destructive and needs approval.")
        lines.append("")
    if command.has_subcommands:
        lines.append("> This command also exposes nested subcommands as separate tools.")
        lines.append("")
    return lines


def render_docs(result: DiscoveryResult, server: ServerSettings | None = None) -> str:
    """Render the full documentation document for a discovery result."""
    name = server.name if server else result.binary
    display = _display_binary(result.binary)
    lines = [f"# `{display}` as an MCP server", ""]
    lines.append(f"Server name: `{name}`")
    if result.framework:
        lines.append(f"Discovery framework: `{result.framework}`")
    if result.strategies:
        lines.append(f"Strategies used: {', '.join(result.strategies)}")
    lines.append(f"Published tools: {len(result.commands)}")
    lines.append("")
    lines.append("Every tool below maps to one CLI command. Arguments are validated against the")
    lines.append("schema below before the command runs, and unknown arguments are rejected.")
    lines.append("")
    lines.append("## Tools")
    lines.append("")
    for command in result.commands:
        lines.extend(command_section(command, display))
    if result.warnings:
        lines.append("## Discovery notes")
        lines.append("")
        for warning in result.warnings:
            lines.append(f"- {warning}")
        lines.append("")
    return "\n".join(lines)


def parameter_summary(param: Parameter) -> str:
    """One-line summary of a parameter, used by ``cli-mcp inspect``."""
    required = "required" if param.required else "optional"
    return f"{argument_name(param)} ({param.type}, {required}) — {cli_hint(param)}"
