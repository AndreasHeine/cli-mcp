"""Shared fixtures for the cli-mcp test suite."""

from pathlib import Path
from typing import Any

import pytest

from cli_mcp.config.settings import DEFAULT_STRATEGIES, DiscoverySettings, SecuritySettings, ServerSettings, Settings

REPO = Path(__file__).resolve().parents[1]
SAMPLES = REPO / "examples" / "sample-clis"


@pytest.fixture()
def repo_root() -> Path:
    """Repository root, used to reach the example CLIs."""
    return REPO


@pytest.fixture()
def reducer_script() -> Path:
    """Argparse sample CLI."""
    return SAMPLES / "reducer.py"


@pytest.fixture()
def click_script() -> Path:
    """Click sample CLI."""
    return SAMPLES / "clicksample.py"


@pytest.fixture()
def typer_script() -> Path:
    """Typer sample CLI."""
    return SAMPLES / "typersample.py"


@pytest.fixture()
def node_script() -> Path:
    """Node sample CLI."""
    return SAMPLES / "nodesample.js"


@pytest.fixture()
def settings_factory():
    """Build settings for tests, with only the knobs a test cares about."""

    def build(binary: str = "demo", **overrides: Any) -> Settings:
        security = SecuritySettings(
            allowlist=list(overrides.pop("allowlist", [])),
            readonly=bool(overrides.pop("readonly", False)),
            readonly_argv=list(overrides.pop("readonly_argv", [])),
            approval=bool(overrides.pop("approval", False)),
            approval_mode=str(overrides.pop("approval_mode", "auto")),
            block_patterns=list(overrides.pop("block_patterns", [])),
            allow_patterns=list(overrides.pop("allow_patterns", [])),
            timeout_seconds=float(overrides.pop("timeout_seconds", 60.0)),
            sandbox=overrides.pop("sandbox", None),
        )
        discovery = DiscoverySettings(
            strategies=list(overrides.pop("strategies", DEFAULT_STRATEGIES)),
            include=overrides.pop("include", None),
            exclude=overrides.pop("exclude", None),
            max_depth=int(overrides.pop("max_depth", 2)),
            max_commands=int(overrides.pop("max_commands", 120)),
            allow_import_reflection=bool(overrides.pop("allow_reflection", False)),
        )
        server = ServerSettings(
            transport=str(overrides.pop("transport", "stdio")),
            host=str(overrides.pop("host", "127.0.0.1")),
            port=int(overrides.pop("port", 8801)),
            path=str(overrides.pop("path", "/mcp")),
            include_docs_tool=bool(overrides.pop("docs", True)),
            tool_prefix=bool(overrides.pop("tool_prefix", False)),
        )
        return Settings(
            binary=binary,
            security=security,
            discovery=discovery,
            mcp=server,
            manifest=overrides.pop("manifest", None),
            **overrides,
        )

    return build
