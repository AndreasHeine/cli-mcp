"""Tests for the end-to-end orchestration layer."""

import sys
from pathlib import Path

import pytest

from cli_mcp import core
from cli_mcp.core import apply_overrides, approval_mode, prepare, transport_endpoint
from cli_mcp.detect import TargetInfo
from cli_mcp.errors import BinaryNotFoundError, ConfigError, DiscoveryError

pytestmark = pytest.mark.integration


class PreparedSettingsStub:
    """Minimal settings stand-in so override plumbing stays unit-testable."""

    def __init__(self) -> None:
        from cli_mcp.config.settings import DiscoverySettings, SecuritySettings, ServerSettings

        self.security = SecuritySettings()
        self.discovery = DiscoverySettings()
        self.mcp = ServerSettings()


def test_apply_overrides_collects_server_security_and_discovery_flags() -> None:
    settings = apply_overrides(
        PreparedSettingsStub(),
        transport="http",
        host="0.0.0.0",
        port=9001,
        tool_prefix=True,
        docs=False,
        readonly=True,
        approval=True,
        approval_mode="explicit",
        allow=["git", " curl.exe "],
        timeout=15,
        strategies=["manifest"],
        include=["reduce"],
        exclude=["help"],
        max_depth=1,
        allow_reflection=True,
    )
    assert settings.mcp.transport == "http"
    assert settings.mcp.host == "0.0.0.0"
    assert settings.mcp.port == 9001
    assert settings.mcp.tool_prefix is True
    assert settings.mcp.include_docs_tool is False
    assert settings.security.readonly is True
    assert settings.security.approval is True
    assert settings.security.approval_mode == "explicit"
    assert settings.security.allowlist == ["git", "curl.exe"]
    assert settings.security.timeout_seconds == 15.0
    assert settings.discovery.strategies == ["manifest"]
    assert settings.discovery.include == ["reduce"]
    assert settings.discovery.exclude == ["help"]
    assert settings.discovery.max_depth == 1
    assert settings.discovery.allow_import_reflection is True


def test_prepare_discovers_an_argparse_script(repo_root: Path, reducer_script: Path) -> None:
    prepared = prepare(str(reducer_script), cwd=repo_root)
    assert prepared.target.origin == "python"
    assert prepared.target.framework == "argparse"
    assert sorted(prepared.result.tool_names()) == ["analyze", "diff", "reduce"]
    assert prepared.launch == [sys.executable, str(reducer_script)]
    assert prepared.binary_path == prepared.target.resolved_path


def test_prepare_recognises_a_click_script(repo_root: Path, click_script: Path) -> None:
    prepared = prepare(str(click_script), cwd=repo_root)
    assert prepared.target.framework == "click"
    assert sorted(prepared.result.tool_names()) == ["clicksample", "publish", "remove", "status"]


def test_prepare_recognises_a_typer_script(repo_root: Path, typer_script: Path) -> None:
    prepared = prepare(str(typer_script), cwd=repo_root)
    assert prepared.target.framework == "typer"
    assert prepared.result.tool_names()


def test_prepare_reads_a_node_cli(repo_root: Path, node_script: Path) -> None:
    prepared = prepare(str(node_script), cwd=repo_root)
    assert prepared.target.origin == "node"
    assert prepared.target.framework in {"commander", "click"}
    assert sorted(prepared.result.tool_names()) == ["fetch", "nodesample", "purge", "transform"]


def test_prepare_uses_git_short_help_without_opening_manual_pages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = TargetInfo(binary="git", resolved_path=str(tmp_path / "git.exe"), origin="native")

    monkeypatch.setattr(core, "resolve_binary", lambda _: target)

    def inspect_context(target, settings, context, registry):
        assert context.help_argv_suffix == "-h"
        raise RuntimeError("checked")

    monkeypatch.setattr(core, "discover", inspect_context)
    with pytest.raises(RuntimeError, match="checked"):
        prepare("git", cwd=tmp_path)


def test_prepare_applies_a_configuration_file(tmp_path: Path, reducer_script: Path) -> None:
    config = tmp_path / "cli-mcp.yaml"
    config.write_text(
        "cli-mcp:\n"
        f"  binary: {reducer_script.as_posix()}\n"
        "  mcp:\n"
        "    transport: http\n"
        "    port: 9010\n"
        "  security:\n"
        "    readonly: true\n"
        "    allowlist: [reducer.py]\n",
        encoding="utf-8",
    )
    prepared = prepare("reducer.py", config=config, cwd=tmp_path)
    assert prepared.settings.binary == reducer_script.as_posix()
    assert prepared.settings.mcp.transport == "http"
    assert prepared.settings.mcp.port == 9010
    assert prepared.settings.security.readonly is True


def test_prepare_reports_a_binary_that_is_not_installed() -> None:
    with pytest.raises(BinaryNotFoundError, match="not found"):
        prepare("definitely-not-a-binary")


def test_prepare_reports_a_cli_without_commands(tmp_path: Path) -> None:
    empty = tmp_path / "silent.py"
    empty.write_text("pass\n", encoding="utf-8")
    with pytest.raises(DiscoveryError, match="no commands found"):
        prepare(str(empty), cwd=tmp_path)


def test_prepare_requires_a_binary_when_config_omits_it(tmp_path: Path) -> None:
    config = tmp_path / "cli-mcp.yaml"
    config.write_text("cli-mcp:\n  mcp:\n    transport: stdio\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must define a binary"):
        prepare("", config=config, cwd=tmp_path)


def test_prepare_skips_plugin_loading(repo_root: Path, reducer_script: Path) -> None:
    prepared = prepare(str(reducer_script), cwd=repo_root, load_plugins=False)
    assert "reduce" in prepared.result.tool_names()


def test_transport_endpoint_follows_the_transport() -> None:
    settings = apply_overrides(PreparedSettingsStub(), transport="stdio")
    assert transport_endpoint(settings) == "stdio"
    settings = apply_overrides(PreparedSettingsStub(), transport="http", host="127.0.0.1", port=8801)
    assert transport_endpoint(settings) == "http://127.0.0.1:8801/mcp"
    settings = apply_overrides(PreparedSettingsStub(), transport="sse", port=8805)
    assert transport_endpoint(settings) == "http://127.0.0.1:8805/mcp (SSE, deprecated)"


def test_approval_mode_is_reported() -> None:
    settings = apply_overrides(PreparedSettingsStub(), approval=True, approval_mode="prompt")
    assert approval_mode(settings) == "prompt"
