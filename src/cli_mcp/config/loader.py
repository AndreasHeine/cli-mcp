"""Load YAML configuration and generate configuration templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from cli_mcp.config.settings import Settings
from cli_mcp.errors import ConfigError

CONFIG_FILE_NAMES: tuple[str, ...] = ("cli-mcp.yaml", "cli-mcp.yml", ".cli-mcp.yaml")


def load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping from *path*."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read configuration file {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Configuration file {path} must contain a mapping")
    return data


def unwrap(document: dict[str, Any]) -> dict[str, Any]:
    """Accept both flat config and config nested under a ``cli-mcp`` key."""
    nested = document.get("cli-mcp")
    if isinstance(nested, dict):
        merged = dict(document)
        merged.pop("cli-mcp")
        merged.update(nested)
        return merged
    return document


#: Keys that belong to the manifest document rather than to the settings model.
MANIFEST_ONLY_KEYS: tuple[str, ...] = ("tools",)


def settings_from(document: dict[str, Any], binary: str | None = None) -> Settings:
    """Build :class:`Settings` from a YAML mapping."""
    payload = dict(unwrap(document))
    for key in MANIFEST_ONLY_KEYS:
        payload.pop(key, None)
    if binary and not payload.get("binary"):
        payload["binary"] = binary
    if not payload.get("binary"):
        raise ConfigError("Configuration must define a binary (or pass one on the command line)")
    try:
        return Settings.model_validate(payload)
    except Exception as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc


def load_settings(path: Path | None = None, binary: str | None = None, cwd: Path | None = None) -> Settings:
    """Load settings from an explicit file, a discovered config file, or defaults."""
    if path is None and cwd is not None:
        path = find_config_file(cwd)
    if path is None:
        if not binary:
            raise ConfigError("No configuration file found and no binary given")
        return settings_from({}, binary=binary)
    return settings_from(load_yaml(path), binary=binary)


def find_config_file(cwd: Path) -> Path | None:
    """Find the first config file name present in *cwd*."""
    for name in CONFIG_FILE_NAMES:
        candidate = cwd / name
        if candidate.is_file():
            return candidate
    return None


def template(
    binary: str = "my-cli",
    transport: str = "stdio",
    readonly: bool = False,
    approval: bool = False,
    sandbox_image: str | None = None,
) -> str:
    """Render a commented configuration template."""
    security_lines = [
        "  security:",
        f"    readonly: {'true' if readonly else 'false'}",
        "    readonly_argv: []  # exact full argv vectors; read-only denies everything until configured",
        f"    approval: {'true' if approval else 'false'}",
        "    approval_mode: auto  # auto/prompt require a local TTY; explicit always refuses",
        "    timeout_seconds: 60",
        "    max_output_bytes: 200000",
        "    max_argv_tokens: 256",
        "    max_argv_bytes: 32768",
        "    allowlist:",
        f"      - {binary}",
    ]
    if sandbox_image:
        security_lines += [
            "    sandbox:",
            "      backend: docker",
            f"      image: {sandbox_image}",
            "      network: false",
            "      workdir_mount: false",
        ]
    lines = [
        "# cli-mcp configuration",
        "# See docs/configuration.md for every option.",
        "",
        "cli-mcp:",
        f"  binary: {binary}",
        "",
        "  mcp:",
        f"    transport: {transport}",
        "    host: 127.0.0.1",
        "    port: 8801",
        "    path: /mcp",
        "    include_docs_tool: true",
        "",
        *security_lines,
        "",
        "  discovery:",
        "    strategies: [reflection, help, manifest]",
        "    max_depth: 2",
        "    allow_import_reflection: false",
        "    # include: [reduce, diff]",
        "    # exclude: [completion, help]",
    ]
    return "\n".join(lines) + "\n"
