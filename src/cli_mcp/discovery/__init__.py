"""Discovery package: strategies, providers, registry and pipeline."""

from __future__ import annotations

from cli_mcp.discovery.base import DiscoveryContext, DiscoveryProvider, HelpResult
from cli_mcp.discovery.engine import coerce_default, command_for, discover_from_help, parameters_from, tool_base
from cli_mcp.discovery.grammars import GRAMMAR_PROVIDERS, GenericHelpProvider
from cli_mcp.discovery.help_parser import parse_help
from cli_mcp.discovery.manifest import (
    ManifestDocument,
    ManifestProvider,
    apply_filters,
    read_manifest,
)
from cli_mcp.discovery.node_reflection import NodeReflectionProvider
from cli_mcp.discovery.pipeline import discover, merge_manifest
from cli_mcp.discovery.python_reflection import PythonReflectionProvider
from cli_mcp.discovery.registry import (
    ENTRY_POINT_GROUP,
    ProviderRegistry,
    Registration,
    plugin_providers,
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "GRAMMAR_PROVIDERS",
    "DiscoveryContext",
    "DiscoveryProvider",
    "GenericHelpProvider",
    "HelpResult",
    "ManifestDocument",
    "ManifestProvider",
    "NodeReflectionProvider",
    "ProviderRegistry",
    "PythonReflectionProvider",
    "Registration",
    "apply_filters",
    "coerce_default",
    "command_for",
    "discover",
    "discover_from_help",
    "merge_manifest",
    "parameters_from",
    "parse_help",
    "plugin_providers",
    "read_manifest",
    "tool_base",
]
