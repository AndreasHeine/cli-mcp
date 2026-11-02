"""Tests for the ``cli-mcp`` command line interface."""

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cli_mcp.config.loader import load_yaml, settings_from

cli_module = importlib.import_module("cli_mcp.cli.main")
runner = CliRunner()

pytestmark = pytest.mark.integration


def captured(result: Any) -> str:
    """Everything the CLI printed, stdout and stderr together."""
    parts = [result.stdout]
    stderr = getattr(result, "stderr", None)
    if stderr:
        parts.append(stderr)
    return "".join(parts)


def test_init_writes_a_readable_template(tmp_path: Path) -> None:
    output = tmp_path / "cli-mcp.yaml"
    result = runner.invoke(cli_module.app, ["init", "git", "--readonly", "--approval", "--output", str(output)])
    assert result.exit_code == 0
    assert "wrote" in result.stdout
    document = load_yaml(output)
    settings = settings_from(document)
    assert settings.binary == "git"
    assert settings.security.readonly is True
    assert settings.security.approval is True


def test_init_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    output = tmp_path / "cli-mcp.yaml"
    output.write_text("cli-mcp:\n  binary: git\n", encoding="utf-8")
    result = runner.invoke(cli_module.app, ["init", "git", "--output", str(output)])
    assert result.exit_code == 2
    assert "already exists" in captured(result)


def test_init_force_overwrites_and_records_sandbox(tmp_path: Path) -> None:
    output = tmp_path / "cli-mcp.yaml"
    output.write_text("cli-mcp:\n  binary: old\n", encoding="utf-8")
    result = runner.invoke(
        cli_module.app,
        ["init", "curl.exe", "--force", "--sandbox-image", "alpine:3.20", "--transport", "http", "--output", str(output)],
    )
    assert result.exit_code == 0
    settings = settings_from(load_yaml(output))
    assert settings.binary == "curl.exe"
    assert settings.mcp.transport == "http"
    assert settings.security.sandbox is not None
    assert settings.security.sandbox.image == "alpine:3.20"


def test_inspect_lists_discovered_commands(repo_root: Path, reducer_script: Path) -> None:
    result = runner.invoke(cli_module.app, ["inspect", str(reducer_script)])
    assert result.exit_code == 0
    output = captured(result)
    assert "framework argparse" in output
    assert "MCP tools" in output
    assert "reduce" in output
    assert "Security:" in output


def test_export_writes_markdown(tmp_path: Path, repo_root: Path, reducer_script: Path) -> None:
    output = tmp_path / "reducer.md"
    result = runner.invoke(cli_module.app, ["export", str(reducer_script), "--output", str(output)])
    assert result.exit_code == 0
    assert "wrote" in result.stdout
    text = output.read_text(encoding="utf-8")
    assert "as an MCP server" in text
    assert "### `reduce`" in text
    assert "CLI invocation: `reducer.py reduce" in text


def test_export_schema_writes_mcp_tool_definitions(tmp_path: Path, repo_root: Path, reducer_script: Path) -> None:
    output = tmp_path / "tools.json"
    result = runner.invoke(cli_module.app, ["export-schema", str(reducer_script), "--output", str(output)])
    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    names = {tool["name"] for tool in payload["tools"]}
    assert {"reduce", "reducer_docs"} <= names
    reduce = next(tool for tool in payload["tools"] if tool["name"] == "reduce")
    assert reduce["inputSchema"]["properties"]["input"]["type"] == "string"
    assert reduce["inputSchema"]["additionalProperties"] is False


def test_export_openapi_writes_an_api_document(tmp_path: Path, repo_root: Path, reducer_script: Path) -> None:
    output = tmp_path / "openapi.json"
    result = runner.invoke(cli_module.app, ["export-openapi", str(reducer_script), "--output", str(output)])
    assert result.exit_code == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["openapi"] == "3.1.0"
    assert "/tools/reduce" in document["paths"]


def test_doctor_reports_readiness(repo_root: Path, reducer_script: Path) -> None:
    result = runner.invoke(cli_module.app, ["doctor", str(reducer_script)])
    assert result.exit_code == 0
    output = captured(result)
    assert "cli-mcp doctor" in output
    assert "binary resolved" in output
    assert "commands discovered" in output
    assert "transport: stdio" in output


def test_providers_lists_core_and_plugin_providers() -> None:
    result = runner.invoke(cli_module.app, ["providers"])
    assert result.exit_code == 0
    output = captured(result)
    assert "Discovery providers" in output
    for name in ("help", "manifest", "reflection-python", "argparse"):
        assert name in output
    assert "DiscoveryProvider" in output


def test_expose_prints_the_checklist_and_starts_the_server(
    monkeypatch: pytest.MonkeyPatch,
    repo_root: Path,
    reducer_script: Path,
) -> None:
    started: list[str] = []
    monkeypatch.setattr(cli_module, "run_server", lambda server, settings: started.append(settings.transport))
    result = runner.invoke(cli_module.app, ["expose", str(reducer_script)])
    assert result.exit_code == 0
    output = captured(result)
    for line in ("Binary detected", "Commands discovered", "Schemas generated", "MCP tools published", "MCP server started"):
        assert line in output
    assert started == ["stdio"]


def test_expose_applies_security_flags(monkeypatch: pytest.MonkeyPatch, repo_root: Path, reducer_script: Path) -> None:
    seen: list[str] = []
    monkeypatch.setattr(cli_module, "run_server", lambda server, settings: seen.append(settings.transport))
    result = runner.invoke(
        cli_module.app,
        ["expose", str(reducer_script), "--readonly", "--approval", "--transport", "http", "--port", "9050", "--include", "reduce"],
    )
    assert result.exit_code == 0
    output = captured(result)
    assert "read-only" in output
    assert "approval:" in output
    assert "http://127.0.0.1:9050/mcp" in output


def test_expose_reports_a_missing_binary() -> None:
    result = runner.invoke(cli_module.app, ["expose", "definitely-not-a-binary"])
    assert result.exit_code == 2
    output = captured(result)
    assert "✗" in output
    assert "not found" in output


def test_serve_starts_the_server_without_a_checklist(monkeypatch: pytest.MonkeyPatch, repo_root: Path, reducer_script: Path) -> None:
    started: list[str] = []
    monkeypatch.setattr(cli_module, "run_server", lambda server, settings: started.append(settings.transport))
    result = runner.invoke(cli_module.app, ["serve", str(reducer_script)])
    assert result.exit_code == 0
    assert started == ["stdio"]
    assert "MCP server started" not in captured(result)


def test_help_describes_the_project() -> None:
    result = runner.invoke(cli_module.app, ["--help"])
    assert "Usage" in captured(result)
