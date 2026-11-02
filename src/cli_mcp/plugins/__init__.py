"""Plugin system: third-party discovery providers.

A provider implements the :class:`cli_mcp.discovery.base.DiscoveryProvider`
protocol and is registered through the ``cli_mcp.discovery`` entry-point group:

.. code-block:: toml

    [project.entry-points."cli_mcp.discovery"]
    my-framework = "my_pkg.provider:MyProvider"

Provider classes are instantiated with the current ``Settings`` when they accept
a ``settings`` parameter, otherwise with no arguments.
"""

from __future__ import annotations

from cli_mcp.config.settings import Settings
from cli_mcp.discovery.base import DiscoveryProvider
from cli_mcp.discovery.registry import ENTRY_POINT_GROUP, ProviderRegistry, plugin_providers

PROTOCOL_DOC = """DiscoveryProvider protocol:

    name: str             display name, e.g. "my-framework"
    strategy: str         "reflection", "help" or "manifest"
    frameworks: tuple     framework fingerprints this provider understands
    supports(target)      whether the provider can handle this binary
    discover(target, ctx) return a DiscoveryResult, or None to abstain
"""


def load_plugins(settings: Settings) -> list[DiscoveryProvider]:
    """Load third-party providers from the installed distributions."""
    return plugin_providers(settings)


def registry_with_plugins(settings: Settings, load_plugins: bool = True) -> ProviderRegistry:
    """Return a registry containing built-ins and any installed plugins."""
    return ProviderRegistry(settings, load_plugins=load_plugins)


__all__ = ["ENTRY_POINT_GROUP", "PROTOCOL_DOC", "load_plugins", "registry_with_plugins"]
