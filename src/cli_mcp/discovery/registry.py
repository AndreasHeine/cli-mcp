"""Provider registry: built-in providers plus third-party plugins."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Literal, cast

from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo
from cli_mcp.discovery.base import DiscoveryContext, DiscoveryProvider
from cli_mcp.discovery.grammars import GRAMMAR_PROVIDERS, GenericHelpProvider
from cli_mcp.discovery.manifest import ManifestProvider
from cli_mcp.discovery.node_reflection import NodeReflectionProvider
from cli_mcp.discovery.python_reflection import PythonReflectionProvider
from cli_mcp.models import DiscoveryResult

ENTRY_POINT_GROUP = "cli_mcp.discovery"
ProviderSource = Literal["core", "plugin"]


@dataclass(frozen=True)
class Registration:
    """A provider together with where it came from."""

    provider: DiscoveryProvider
    source: ProviderSource


class ProviderRegistry:
    """The provider set used by one discovery run."""

    def __init__(self, settings: Settings, *, load_plugins: bool = True) -> None:
        """Register the built-in providers, plus installed plugins when asked."""
        self.settings = settings
        self._registrations: list[Registration] = []
        for provider in _builtin_providers(settings):
            self._registrations.append(Registration(provider=provider, source="core"))
        if load_plugins:
            for provider in plugin_providers(settings):
                self._registrations.append(Registration(provider=provider, source="plugin"))

    def register(self, provider: DiscoveryProvider, source: ProviderSource = "plugin") -> None:
        """Add a provider programmatically, for tests and embedders."""
        self._registrations.append(Registration(provider=provider, source=source))

    @property
    def registrations(self) -> list[Registration]:
        """Return every registered provider in priority order."""
        return list(self._registrations)

    def for_target(self, target: TargetInfo) -> list[DiscoveryProvider]:
        """Return the providers that accept *target*, plugins last so built-ins win."""
        return [
            registration.provider for registration in self._registrations if registration.provider.supports(target)
        ]

    def for_strategy(self, strategy: str, target: TargetInfo) -> list[DiscoveryProvider]:
        """Return the providers that accept *target* and implement *strategy*."""
        return [provider for provider in self.for_target(target) if provider.strategy == strategy]

    def describe(self) -> list[tuple[str, str, str, ProviderSource]]:
        """Build the rows shown by ``cli-mcp providers``: name, strategy, frameworks, source."""
        return [
            (
                registration.provider.name,
                registration.provider.strategy,
                ", ".join(registration.provider.frameworks),
                registration.source,
            )
            for registration in self._registrations
        ]

    def run(self, strategy: str, target: TargetInfo, ctx: DiscoveryContext) -> DiscoveryResult | None:
        """Try every provider for *strategy* and return the first non-empty result."""
        for provider in self.for_strategy(strategy, target):
            result = provider.discover(target, ctx)
            if result is not None and result.commands:
                return result
        return None


def _builtin_providers(settings: Settings) -> list[DiscoveryProvider]:
    """Built-ins ordered so specific grammars beat the generic parser."""
    return [
        PythonReflectionProvider(settings),
        NodeReflectionProvider(settings),
        *(provider(settings) for provider in GRAMMAR_PROVIDERS),
        GenericHelpProvider(settings),
        ManifestProvider(settings),
    ]


def plugin_providers(settings: Settings) -> list[DiscoveryProvider]:
    """Load providers from the ``cli_mcp.discovery`` entry-point group."""
    providers: list[DiscoveryProvider] = []
    try:
        found = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        return providers
    for entry_point in found:
        try:
            loaded = entry_point.load()
        except Exception:
            continue
        provider = _instantiate(loaded, settings)
        if provider is not None:
            providers.append(provider)
    return providers


def _instantiate(loaded: object, settings: Settings) -> DiscoveryProvider | None:
    """Turn an entry-point target into a provider instance."""
    if isinstance(loaded, type):
        parameters = inspect.signature(loaded).parameters
        try:
            instance = loaded(settings) if "settings" in parameters else loaded()
        except Exception:
            return None
        return cast("DiscoveryProvider", instance)
    if loaded is None or not hasattr(loaded, "supports") or not hasattr(loaded, "discover"):
        return None
    return cast("DiscoveryProvider", loaded)
