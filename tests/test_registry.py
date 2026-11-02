"""Unit tests for the discovery provider registry and plugin loading."""

import pytest

from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo
from cli_mcp.discovery import registry as registry_module
from cli_mcp.discovery.base import DiscoveryContext
from cli_mcp.discovery.registry import ENTRY_POINT_GROUP, ProviderRegistry, plugin_providers


class SampleProvider:
    """A minimal third-party discovery provider."""

    name = "sample"
    strategy = "reflection"
    frameworks = ("sample",)

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    def supports(self, target: TargetInfo) -> bool:
        return True

    def discover(self, target: TargetInfo, ctx: DiscoveryContext):
        return None


class NoArgumentProvider:
    """A plugin that takes no settings."""

    name = "legacy"
    strategy = "help"
    frameworks: tuple[str, ...] = ()

    def supports(self, target: TargetInfo) -> bool:
        return False

    def discover(self, target: TargetInfo, ctx: DiscoveryContext):
        return None


def target(framework: str | None = None, origin: str = "python") -> TargetInfo:
    return TargetInfo(binary="tool", resolved_path="C:\\tools\\tool.py", origin=origin, framework=framework)


def test_builtin_order_is_reflection_then_help_then_manifest() -> None:
    registry = ProviderRegistry(Settings(binary="tool"), load_plugins=False)
    names = [name for name, _strategy, _frameworks, _source in registry.describe()]
    assert names[:2] == ["reflection-python", "reflection-node"]
    assert names[-2:] == ["help", "manifest"]
    assert "cobra" in names and "clap" in names and "argparse" in names


def test_strategies_are_grouped() -> None:
    registry = ProviderRegistry(Settings(binary="tool"), load_plugins=False)
    assert registry.for_strategy("reflection", target("click")) == []
    enabled = ProviderRegistry(Settings(binary="tool", discovery={"allow_import_reflection": True}), load_plugins=False)
    assert [provider.name for provider in enabled.for_strategy("reflection", target("click"))] == ["reflection-python"]
    assert [provider.name for provider in enabled.for_strategy("reflection", target("commander", origin="node"))] == [
        "reflection-node"
    ]
    assert [provider.name for provider in registry.for_strategy("manifest", target())] == ["manifest"]
    assert registry.for_strategy("unknown-strategy", target()) == []


def test_for_target_filters_by_fingerprint() -> None:
    registry = ProviderRegistry(Settings(binary="tool"), load_plugins=False)
    python = registry.for_target(target("argparse"))
    assert [provider.name for provider in python] == ["argparse", "help", "manifest"]
    native = registry.for_target(target(None, origin="native"))
    assert [provider.name for provider in native] == ["help", "manifest"]
    assert [provider.name for provider in registry.for_target(target("cobra"))] == ["cobra", "help", "manifest"]
    enabled = ProviderRegistry(Settings(binary="tool", discovery={"allow_import_reflection": True}), load_plugins=False)
    assert [provider.name for provider in enabled.for_target(target("argparse"))] == [
        "reflection-python",
        "argparse",
        "help",
        "manifest",
    ]


def test_run_dispatches_only_supported_providers() -> None:
    registry = ProviderRegistry(Settings(binary="tool"), load_plugins=False)
    context = DiscoveryContext(Settings(binary="tool").discovery)
    assert registry.run("reflection", target(None), context) is None
    assert registry.run("manifest", target(None), context) is None


def test_register_and_describe_plugin_sources() -> None:
    registry = ProviderRegistry(Settings(binary="tool"), load_plugins=False)
    registry._registrations.clear()
    registry.register(SampleProvider(), "plugin")
    described = registry.describe()
    assert described == [("sample", "reflection", "sample", "plugin")]
    assert registry.for_target(target("sample"))[0].name == "sample"
    assert registry.registrations[-1].source == "plugin"
    assert [registration.provider.name for registration in registry.for_strategy("help", target())] == []


def test_describe_lists_frameworks_as_text() -> None:
    registry = ProviderRegistry(Settings(binary="tool"), load_plugins=False)
    rows = registry.describe()
    python = next(row for row in rows if row[0] == "reflection-python")
    assert python[1] == "reflection"
    assert "argparse" in python[2]
    assert python[3] == "core"
    assert registry.registrations[0].source == "core"


def test_plugin_providers_receive_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEntryPoint:
        name = "sample"

        def load(self) -> type:
            return SampleProvider

    monkeypatch.setattr(
        registry_module,
        "entry_points",
        lambda **kwargs: [FakeEntryPoint()] if kwargs.get("group") == ENTRY_POINT_GROUP else [],
    )
    settings = Settings(binary="tool")
    providers = plugin_providers(settings)
    assert [provider.name for provider in providers] == ["sample"]
    assert providers[0].settings is settings


def test_plugin_providers_without_settings_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEntryPoint:
        name = "legacy"

        def load(self) -> type:
            return NoArgumentProvider

    monkeypatch.setattr(registry_module, "entry_points", lambda **kwargs: [FakeEntryPoint()])
    providers = plugin_providers(Settings(binary="tool"))
    assert [provider.name for provider in providers] == ["legacy"]


def test_plugin_providers_skip_broken_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenEntryPoint:
        name = "broken"

        def load(self) -> type:
            raise RuntimeError("import failed")

    monkeypatch.setattr(registry_module, "entry_points", lambda **kwargs: [BrokenEntryPoint()])
    assert plugin_providers(Settings(binary="tool")) == []


def test_plugin_providers_accept_prebuilt_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEntryPoint:
        name = "instance"

        def load(self) -> SampleProvider:
            return SampleProvider(Settings(binary="tool"))

    monkeypatch.setattr(registry_module, "entry_points", lambda **kwargs: [FakeEntryPoint()])
    providers = plugin_providers(Settings(binary="tool"))
    assert [provider.name for provider in providers] == ["sample"]


def test_plugin_providers_survive_a_broken_entry_point_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(**kwargs: object) -> list:
        raise RuntimeError("metadata unavailable")

    monkeypatch.setattr(registry_module, "entry_points", explode)
    assert plugin_providers(Settings(binary="tool")) == []


def test_plugin_providers_skip_objects_that_are_not_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEntryPoint:
        name = "not-a-provider"

        def load(self) -> object:
            return object()

    monkeypatch.setattr(registry_module, "entry_points", lambda **kwargs: [FakeEntryPoint()])
    assert plugin_providers(Settings(binary="tool")) == []


def test_registry_loads_plugins_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEntryPoint:
        name = "sample"

        def load(self) -> type:
            return SampleProvider

    monkeypatch.setattr(registry_module, "entry_points", lambda **kwargs: [FakeEntryPoint()])
    registry = ProviderRegistry(Settings(binary="tool"))
    assert registry.registrations[-1].source == "plugin"
    assert registry.registrations[-1].provider.name == "sample"


def test_registry_ignores_other_entry_point_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_module, "entry_points", lambda **kwargs: [])
    assert plugin_providers(Settings(binary="tool")) == []
