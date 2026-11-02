"""``cli-mcp`` command line interface."""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from cli_mcp.config.loader import template
from cli_mcp.config.settings import ApprovalMode, Settings, TransportName
from cli_mcp.core import PreparedCli, prepare, transport_endpoint
from cli_mcp.errors import CliMcpError
from cli_mcp.mcp.server import build_server, tool_definitions
from cli_mcp.plugins import PROTOCOL_DOC, registry_with_plugins
from cli_mcp.schema.docgen import render_docs
from cli_mcp.schema.jsonschema import argument_name
from cli_mcp.schema.openapi import build_openapi
from cli_mcp.security.policy import AccessPolicy
from cli_mcp.transport import run_server

console = Console()
error_console = Console(stderr=True)

def _config_option() -> Any:
    """Fresh ``--config`` option declaration."""
    return typer.Option(None, "--config", help="Path to a cli-mcp.yaml config file")


def _binary_argument(help_text: str) -> Any:
    """Fresh ``binary`` argument; a config file may supply it instead."""
    return typer.Argument(None, help=help_text)


def _include_option() -> Any:
    """Fresh ``--include`` option declaration."""
    return typer.Option(None, "--include", help="Only expose these commands")


def _exclude_option() -> Any:
    """Fresh ``--exclude`` option declaration."""
    return typer.Option(None, "--exclude", help="Never expose these commands")


def _depth_option() -> Any:
    """Fresh ``--max-depth`` option declaration."""
    return typer.Option(None, "--max-depth", help="How deep to walk subcommands")


def _reflection_option() -> Any:
    """Fresh ``--allow-reflection`` option declaration."""
    return typer.Option(False, "--allow-reflection", help="Allow reflection, which imports the target CLI")


def _prefix_option() -> Any:
    """Fresh ``--tool-prefix`` option declaration."""
    return typer.Option(False, "--tool-prefix", help="Prefix tool names with the binary name")


def _docs_option() -> Any:
    """Fresh ``--docs`` option declaration."""
    return typer.Option(True, "--docs/--no-docs", help="Also publish a documentation tool")

DESCRIPTION = "Swagger for Command Line Tools: expose any CLI as a fully compliant MCP server."


def _fail(message: str) -> None:
    """Report a failure on stderr and exit with code 2."""
    error_console.print(f"[red]✗ {message}[/red]")
    raise typer.Exit(code=2)


def _overrides(
    *,
    transport: TransportName | None = None,
    host: str | None = None,
    port: int | None = None,
    readonly: bool | None = None,
    approval: bool | None = None,
    approval_mode: ApprovalMode | None = None,
    allow: list[str] | None = None,
    timeout: float | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    max_depth: int | None = None,
    allow_reflection: bool | None = None,
    tool_prefix: bool | None = None,
    docs: bool | None = None,
    strategies: list[str] | None = None,
) -> dict[str, object]:
    """Collect only the flags the user actually passed."""
    return {
        key: value
        for key, value in {
            "transport": transport,
            "host": host,
            "port": port,
            "readonly": readonly,
            "approval": approval,
            "approval_mode": approval_mode,
            "allow": allow,
            "timeout": timeout,
            "include": include,
            "exclude": exclude,
            "max_depth": max_depth,
            "allow_reflection": allow_reflection,
            "tool_prefix": tool_prefix,
            "docs": docs,
            "strategies": strategies,
        }.items()
        if value is not None
    }


def _prepare(binary: str | None, config: str | None, overrides: dict[str, object]) -> PreparedCli:
    """Discover the binary, turning cli-mcp errors into CLI failures."""
    try:
        return prepare(binary, config=config, overrides=overrides)
    except CliMcpError as exc:
        _fail(str(exc))
        raise typer.Exit(code=2) from exc


def _checklist(prepared: PreparedCli, tool_count: int) -> None:
    """Print the five-line checklist that announces what cli-mcp did."""
    settings = prepared.settings
    endpoint = transport_endpoint(settings)
    command_count = len(prepared.result.commands)
    strategies = ", ".join(prepared.result.strategies)
    framework = prepared.result.framework or "generic help"
    error_console.print(
        f"[green]✓[/green] Binary detected [dim]{prepared.target.binary}[/dim]",
        f"({prepared.binary_path})",
    )
    error_console.print(
        f"[green]✓[/green] Commands discovered [dim]{command_count}[/dim] via {strategies} ({framework})"
    )
    error_console.print(f"[green]✓[/green] Schemas generated [dim]{command_count}[/dim] input schemas")
    error_console.print(f"[green]✓[/green] MCP tools published [dim]{tool_count}[/dim] tools ({settings.server_name})")
    policy = AccessPolicy(settings.security).summary
    error_console.print(f"[green]✓[/green] MCP server started [dim]{endpoint}[/dim] · security: {policy}")
    for warning in prepared.result.warnings:
        error_console.print(f"[yellow]! {warning}[/yellow]")


app = typer.Typer(name="cli-mcp", help=DESCRIPTION, no_args_is_help=True, add_completion=False)


@app.command()
def expose(
    binary: str | None = _binary_argument("The CLI to expose as an MCP server"),
    config: str | None = _config_option(),
    transport: TransportName | None = typer.Option(None, "--transport", help="stdio, http, streamable-http or sse"),
    host: str | None = typer.Option(None, "--host", help="Bind host for HTTP transports"),
    port: int | None = typer.Option(None, "--port", help="Bind port for HTTP transports"),
    readonly: bool | None = typer.Option(None, "--readonly/--no-readonly", help="Reject destructive commands"),
    approval: bool | None = typer.Option(None, "--approval/--no-approval", help="Require approval before risky runs"),
    approval_mode: ApprovalMode | None = typer.Option(None, "--approval-mode", help="auto, prompt or explicit"),
    allow: list[str] | None = typer.Option(None, "--allow", help="Allow list of binaries"),
    timeout: float | None = typer.Option(None, "--timeout", help="Execution timeout in seconds"),
    include: list[str] | None = _include_option(),
    exclude: list[str] | None = _exclude_option(),
    max_depth: int | None = _depth_option(),
    allow_reflection: bool | None = _reflection_option(),
    tool_prefix: bool | None = _prefix_option(),
    docs: bool | None = _docs_option(),
) -> None:
    """Discover a CLI, publish it as MCP tools and start the server."""
    prepared = _prepare(binary, config, _overrides(
        transport=transport,
        host=host,
        port=port,
        readonly=readonly,
        approval=approval,
        approval_mode=approval_mode,
        allow=allow,
        timeout=timeout,
        include=include,
        exclude=exclude,
        max_depth=max_depth,
        allow_reflection=allow_reflection,
        tool_prefix=tool_prefix,
        docs=docs,
    ))
    server = build_server(prepared.settings, prepared.result)
    tool_count = len(prepared.result.commands) + (1 if prepared.settings.mcp.include_docs_tool else 0)
    _checklist(prepared, tool_count)
    try:
        run_server(server, prepared.settings.mcp)
    except CliMcpError as exc:
        _fail(str(exc))


@app.command()
def serve(
    binary: str | None = _binary_argument("The CLI to expose as an MCP server"),
    config: str | None = _config_option(),
    transport: TransportName | None = typer.Option(None, "--transport", help="stdio, http, streamable-http or sse"),
    host: str | None = typer.Option(None, "--host", help="Bind host for HTTP transports"),
    port: int | None = typer.Option(None, "--port", help="Bind port for HTTP transports"),
    readonly: bool | None = typer.Option(None, "--readonly/--no-readonly", help="Reject destructive commands"),
    approval: bool | None = typer.Option(None, "--approval/--no-approval", help="Require approval before risky runs"),
    approval_mode: ApprovalMode | None = typer.Option(None, "--approval-mode", help="auto, prompt or explicit"),
    allow: list[str] | None = typer.Option(None, "--allow", help="Allow list of binaries"),
    include: list[str] | None = _include_option(),
    exclude: list[str] | None = _exclude_option(),
) -> None:
    """Start the MCP server without the checklist, for client configs."""
    prepared = _prepare(binary, config, _overrides(
        transport=transport,
        host=host,
        port=port,
        readonly=readonly,
        approval=approval,
        approval_mode=approval_mode,
        allow=allow,
        include=include,
        exclude=exclude,
    ))
    server = build_server(prepared.settings, prepared.result)
    try:
        run_server(server, prepared.settings.mcp)
    except CliMcpError as exc:
        _fail(str(exc))


@app.command()
def inspect(
    binary: str | None = _binary_argument("The CLI to inspect"),
    config: str | None = _config_option(),
    include: list[str] | None = _include_option(),
    exclude: list[str] | None = _exclude_option(),
    max_depth: int | None = _depth_option(),
    allow_reflection: bool | None = _reflection_option(),
    tool_prefix: bool | None = _prefix_option(),
) -> None:
    """Show the discovered commands, their arguments and the security policy."""
    prepared = _prepare(binary, config, _overrides(
        include=include,
        exclude=exclude,
        max_depth=max_depth,
        allow_reflection=allow_reflection,
        tool_prefix=tool_prefix,
    ))
    console.print(f"[bold]{prepared.target.binary}[/bold] → {prepared.binary_path}")
    console.print(
        f"framework {prepared.result.framework or 'generic'} · strategies {', '.join(prepared.result.strategies)}"
    )
    console.print(f"Security: {AccessPolicy(prepared.settings.security).summary}")
    table = Table(title=f"{len(prepared.result.commands)} MCP tools")
    table.add_column("Tool", style="cyan")
    table.add_column("CLI command")
    table.add_column("Arguments")
    table.add_column("Provider")
    for command in prepared.result.commands:
        arguments = ", ".join(argument_name(param) for param in command.parameters) or "-"
        table.add_row(command.name, command.invocation(prepared.target.binary), arguments, command.provider)
    console.print(table)
    for warning in prepared.result.warnings:
        console.print(f"[yellow]! {warning}[/yellow]")


@app.command()
def export(
    binary: str | None = _binary_argument("The CLI to document"),
    config: str | None = _config_option(),
    output: Path | None = typer.Option(None, "--output", "-o", help="Markdown file to write"),
    include: list[str] | None = _include_option(),
    exclude: list[str] | None = _exclude_option(),
) -> None:
    """Generate Markdown documentation for the discovered tools."""
    prepared = _prepare(binary, config, _overrides(include=include, exclude=exclude))
    path = output or Path("docs") / f"{prepared.settings.binary}-mcp.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_docs(prepared.result, prepared.settings.mcp), encoding="utf-8")
    console.print(f"[green]✓[/green] wrote {path} ({len(prepared.result.commands)} tools)")


@app.command("export-schema")
def export_schema(
    binary: str | None = _binary_argument("The CLI to export"),
    config: str | None = _config_option(),
    output: Path | None = typer.Option(None, "--output", "-o", help="JSON file to write"),
    include: list[str] | None = _include_option(),
    exclude: list[str] | None = _exclude_option(),
) -> None:
    """Export the MCP tool definitions with their JSON Schemas."""
    prepared = _prepare(binary, config, _overrides(include=include, exclude=exclude))
    definitions = tool_definitions(prepared.settings, prepared.result)
    payload = {
        "server": prepared.settings.server_name,
        "binary": prepared.settings.binary,
        "tools": [
            {"name": tool.name, "description": tool.description, "inputSchema": tool.schema} for tool in definitions
        ],
    }
    path = output or Path("schemas") / f"{prepared.settings.binary}-mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    console.print(f"[green]✓[/green] wrote {path} ({len(payload['tools'])} tools)")


@app.command("export-openapi")
def export_openapi(
    binary: str | None = _binary_argument("The CLI to export"),
    config: str | None = _config_option(),
    output: Path | None = typer.Option(None, "--output", "-o", help="OpenAPI JSON file to write"),
    include: list[str] | None = _include_option(),
    exclude: list[str] | None = _exclude_option(),
) -> None:
    """Export an OpenAPI document describing the exposed commands."""
    prepared = _prepare(binary, config, _overrides(include=include, exclude=exclude))
    document = build_openapi(prepared.result, prepared.settings.mcp)
    path = output or Path("openapi") / f"{prepared.settings.binary}-openapi.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    console.print(f"[green]✓[/green] wrote {path} ({len(document['paths'])} endpoints)")


@app.command()
def doctor(
    binary: str | None = _binary_argument("The CLI to check"),
    config: str | None = _config_option(),
    allow_reflection: bool | None = _reflection_option(),
) -> None:
    """Report discovery, security and transport readiness."""
    prepared = _prepare(binary, config, _overrides(allow_reflection=allow_reflection))
    settings = prepared.settings
    console.print("[bold]cli-mcp doctor[/bold]")
    checks: list[tuple[bool, str]] = [
        (True, f"binary resolved: {prepared.binary_path}"),
        (bool(prepared.result.commands), f"commands discovered: {len(prepared.result.commands)}"),
        (True, f"strategies: {', '.join(prepared.result.strategies)}"),
        (True, f"transport: {settings.mcp.transport} ({transport_endpoint(settings)})"),
        (True, f"security: {AccessPolicy(settings.security).summary}"),
        (True, f"sandbox: {settings.security.sandbox.backend if settings.security.sandbox else 'disabled'}"),
    ]
    for ok, message in checks:
        marker = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(f"{marker} {message}")
    for warning in prepared.result.warnings:
        console.print(f"[yellow]! {warning}[/yellow]")


@app.command()
def init(
    binary: str = typer.Argument("my-cli", help="The binary to write a config for"),
    transport: TransportName = typer.Option("stdio", "--transport", help="Transport to configure"),
    readonly: bool = typer.Option(False, "--readonly/--no-readonly", help="Enable read-only mode"),
    approval: bool = typer.Option(False, "--approval/--no-approval", help="Enable approval mode"),
    sandbox_image: str | None = typer.Option(
        None, "--sandbox-image", help="Enable container sandboxing with this image"
    ),
    output: Path = typer.Option(Path("cli-mcp.yaml"), "--output", "-o", help="Config file to write"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config"),
) -> None:
    """Write a commented cli-mcp.yaml template."""
    if output.exists() and not force:
        _fail(f"{output} already exists; pass --force to overwrite")
    text = template(binary, transport=transport, readonly=readonly, approval=approval, sandbox_image=sandbox_image)
    output.write_text(text, encoding="utf-8")
    console.print(f"[green]✓[/green] wrote {output}")


@app.command()
def providers() -> None:
    """List discovery providers, including installed plugins."""
    settings = Settings(binary="cli-mcp")
    registry = registry_with_plugins(settings)
    table = Table(title="Discovery providers")
    table.add_column("Name", style="cyan")
    table.add_column("Strategy")
    table.add_column("Frameworks")
    table.add_column("Source")
    for name, strategy, frameworks, source in registry.describe():
        table.add_row(name or "-", strategy, frameworks or "-", source)
    console.print(table)
    console.print(PROTOCOL_DOC)


def _prepare_streams() -> None:
    """Give the output streams a codec that can carry the check and cross glyphs."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(OSError, ValueError):  # pragma: no cover - a stream that cannot be reconfigured
                reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    """Console entry point."""
    _prepare_streams()
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
