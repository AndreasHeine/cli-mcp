"""Unit tests for manifest discovery and the discovery pipeline."""

from pathlib import Path

import pytest

from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo
from cli_mcp.discovery.base import DiscoveryContext
from cli_mcp.discovery.manifest import ManifestProvider, apply_filters, manifest_path, matches, read_manifest
from cli_mcp.discovery.pipeline import discover
from cli_mcp.discovery.registry import ProviderRegistry
from cli_mcp.errors import ConfigError, DiscoveryError
from cli_mcp.models import CommandSpec, DiscoveryResult

MANIFEST = """cli-mcp:
  binary: reducer.py
  include: [reduce]
  exclude: [diff]
  tools:
    - name: reduce
      command: reduce
      description: Reduce a nodeset
      parameters:
        - name: input
          cli-name: --input
          type: string
          required: true
          description: Source file
        - name: verbose
          kind: flag
          description: Verbose output
    - name: diff
      command: diff
      description: Compare files
      destructive: true
      examples: ["reducer diff a.xml b.xml"]
"""


MANIFEST_PLAIN = """cli-mcp:
  binary: reducer.py
  tools:
    - name: reduce
      command: reduce
      description: Reduce a nodeset
    - name: diff
      command: diff
      description: Compare files
"""


def target(binary: str = "reducer.py") -> TargetInfo:
    return TargetInfo(binary=binary, resolved_path=str(Path(binary)), origin="python")


def write_manifest(tmp_path: Path, text: str = MANIFEST) -> Path:
    path = tmp_path / "cli-mcp.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def settings_with(tmp_path: Path, manifest: str | None = None, **overrides: object) -> Settings:
    settings = Settings(binary="reducer.py")
    if manifest is not None:
        settings.manifest = manifest
    for key, value in overrides.items():
        setattr(settings.discovery, key, value)
    return settings


def test_read_manifest_reads_the_declared_block(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    document = read_manifest(settings_with(tmp_path), tmp_path)
    assert document.binary == "reducer.py"
    assert document.include == ["reduce"]
    assert document.exclude == ["diff"]
    assert [tool.name for tool in document.tools] == ["reduce", "diff"]
    reduce = document.tools[0]
    assert reduce.path == ["reduce"]
    assert reduce.provider == "manifest"
    assert [parameter.name for parameter in reduce.parameters] == ["input", "verbose"]
    assert reduce.parameters[1].kind == "flag"
    assert document.tools[1].destructive is True
    assert document.tools[1].examples == ["reducer diff a.xml b.xml"]


def test_read_manifest_accepts_a_flat_document(tmp_path: Path) -> None:
    path = tmp_path / "custom.yaml"
    path.write_text("binary: tool\nmanifest: custom.yaml\ntools:\n  - name: go\n    command: go\n", encoding="utf-8")
    document = read_manifest(Settings(binary="tool", manifest="custom.yaml"), tmp_path)
    assert [tool.name for tool in document.tools] == ["go"]


def test_manifest_path_falls_back_to_a_config_file(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    assert manifest_path(settings_with(tmp_path), tmp_path) == tmp_path / "cli-mcp.yaml"


def test_manifest_path_reports_a_missing_explicit_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        manifest_path(settings_with(tmp_path, manifest="absent.yaml"), tmp_path)


def test_manifest_path_returns_none_without_any_file(tmp_path: Path) -> None:
    assert manifest_path(settings_with(tmp_path), tmp_path) is None


def test_manifest_provider_disdeclares_no_commands(tmp_path: Path) -> None:
    provider = ManifestProvider(settings_with(tmp_path))
    assert provider.supports(target()) is True
    assert provider.name == "manifest"
    assert provider.discover(target(), DiscoveryContext(Settings(binary="tool").discovery)) is None


def test_manifest_provider_discovers(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    settings = settings_with(tmp_path)
    provider = ManifestProvider(settings)
    result = provider.discover(target(), DiscoveryContext(settings.discovery, cwd=tmp_path))
    assert result is not None
    assert result.framework == "manifest"
    assert result.tool_names() == ["reduce", "diff"]
    assert result.warnings[0].startswith("manifest:")
    assert "cli-mcp.yaml" in result.warnings[0]


def test_matches_accepts_names_and_path_tails() -> None:
    assert matches("reduce", ["reduce"], ["reduce"]) is True
    assert matches("git_commit", ["git", "commit"], ["commit"]) is True
    assert matches("git_commit", ["git", "commit"], ["git"]) is True
    assert matches("status", ["status"], ["git"]) is False


def test_apply_filters_include_then_exclude() -> None:
    commands = [CommandSpec(name="reduce"), CommandSpec(name="diff"), CommandSpec(name="analyze")]
    kept = apply_filters(commands, ["reduce", "analyze"], ["analyze"])
    assert [command.name for command in kept] == ["reduce"]


class FakeProvider:
    """A provider that returns fixed commands for a strategy."""

    def __init__(self, name: str, strategy: str, commands: list[CommandSpec], warnings: list[str] | None = None) -> None:
        self.name = name
        self.strategy = strategy
        self.frameworks = (name,)
        self.commands = commands
        self.warnings = warnings or []

    def supports(self, target_info: TargetInfo) -> bool:
        return True

    def discover(self, target_info: TargetInfo, ctx: DiscoveryContext) -> DiscoveryResult | None:
        if not self.commands:
            return None
        return DiscoveryResult(
            binary=target_info.binary,
            resolved_path=target_info.resolved_path,
            framework=self.name,
            commands=self.commands,
            strategies=[self.name],
            warnings=self.warnings,
        )


def registry_with(*providers: FakeProvider) -> ProviderRegistry:
    registry = ProviderRegistry(Settings(binary="tool"), load_plugins=False)
    registry._registrations.clear()
    for provider in providers:
        registry.register(provider, "core")
    return registry


def test_pipeline_prefers_the_first_strategy_that_yields_commands() -> None:
    registry = registry_with(
        FakeProvider("reflection", "reflection", [CommandSpec(name="reduce")]),
        FakeProvider("help", "help", [CommandSpec(name="other")]),
    )
    result = discover(target("tool"), Settings(binary="tool"), registry=registry)
    assert result.tool_names() == ["reduce"]
    assert result.framework == "reflection"
    assert result.strategies == ["reflection"]


def test_pipeline_records_provider_warnings() -> None:
    registry = registry_with(FakeProvider("help", "help", [CommandSpec(name="run")], warnings=["partial tree"]))
    result = discover(target("tool"), Settings(binary="tool"), registry=registry)
    assert result.warnings == ["partial tree"]


def test_pipeline_warns_when_no_strategy_yields_anything(tmp_path: Path) -> None:
    write_manifest(tmp_path, MANIFEST_PLAIN)
    registry = registry_with(FakeProvider("help", "help", []))
    settings = settings_with(tmp_path, strategies=["help"])
    result = discover(target(), settings, ctx=DiscoveryContext(settings.discovery, cwd=tmp_path), registry=registry)
    assert result.framework == "manifest"
    assert result.strategies == ["manifest"]
    assert "no commands discovered by strategies: help" in result.warnings


def test_pipeline_manifest_overrides_generated_tools(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    registry = registry_with(FakeProvider("help", "help", [CommandSpec(name="reduce", description="generated")]))
    settings = settings_with(tmp_path)
    result = discover(target(), settings, ctx=DiscoveryContext(settings.discovery, cwd=tmp_path), registry=registry)
    assert result.get("reduce").description == "Reduce a nodeset"
    assert "manifest overrides tool 'reduce'" in result.warnings


def test_pipeline_manifest_adds_new_tools(tmp_path: Path) -> None:
    write_manifest(tmp_path, MANIFEST_PLAIN)
    registry = registry_with(FakeProvider("help", "help", [CommandSpec(name="status", description="live")]))
    settings = settings_with(tmp_path)
    result = discover(target(), settings, ctx=DiscoveryContext(settings.discovery, cwd=tmp_path), registry=registry)
    assert sorted(result.tool_names()) == ["diff", "reduce", "status"]


def test_pipeline_filters_with_settings_and_manifest_lists(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    registry = registry_with(
        FakeProvider(
            "help",
            "help",
            [CommandSpec(name="reduce"), CommandSpec(name="status"), CommandSpec(name="diff")],
        )
    )
    settings = settings_with(tmp_path, include=["status"])
    result = discover(target(), settings, ctx=DiscoveryContext(settings.discovery, cwd=tmp_path), registry=registry)
    assert sorted(result.tool_names()) == ["reduce", "status"]
    assert any("filtered out" in warning for warning in result.warnings)


def test_pipeline_drops_duplicate_tool_names() -> None:
    registry = registry_with(
        FakeProvider(
            "help",
            "help",
            [CommandSpec(name="reduce", description="first"), CommandSpec(name="reduce", description="second")],
        )
    )
    result = discover(target("tool"), Settings(binary="tool"), registry=registry)
    assert len(result.commands) == 1
    assert result.get("reduce").description == "first"
    assert "duplicate tool name 'reduce' dropped" in result.warnings


def test_pipeline_caps_commands_and_warns() -> None:
    registry = registry_with(
        FakeProvider("help", "help", [CommandSpec(name="a"), CommandSpec(name="b"), CommandSpec(name="c")])
    )
    settings = Settings(binary="tool", discovery={"max_commands": 2})
    result = discover(target("tool"), settings, registry=registry)
    assert [command.name for command in result.commands] == ["a", "b"]
    assert any("capped at 2 commands" in warning for warning in result.warnings)


def test_pipeline_warns_on_manifest_binary_mismatch(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    registry = registry_with(FakeProvider("help", "help", [CommandSpec(name="reduce")]))
    settings = settings_with(tmp_path)
    result = discover(target("other.py"), settings, ctx=DiscoveryContext(settings.discovery, cwd=tmp_path), registry=registry)
    assert any("manifest declares binary" in warning for warning in result.warnings)


def test_pipeline_raises_when_nothing_is_found() -> None:
    registry = registry_with(FakeProvider("help", "help", []))
    settings = Settings(binary="tool", discovery={"strategies": ["help"]})
    with pytest.raises(DiscoveryError, match="no commands found"):
        discover(target("tool"), settings, registry=registry)


def test_matches_handles_empty_patterns() -> None:
    assert matches("reduce", ["reduce"], []) is False


def test_apply_filters_without_patterns_keeps_everything() -> None:
    commands = [CommandSpec(name="a")]
    assert apply_filters(commands, [], []) == commands
