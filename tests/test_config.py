"""Unit tests for YAML configuration loading and templates."""

from pathlib import Path

import pytest

from cli_mcp.config.loader import (
    CONFIG_FILE_NAMES,
    find_config_file,
    load_settings,
    load_yaml,
    settings_from,
    template,
    unwrap,
)
from cli_mcp.config.settings import Settings
from cli_mcp.errors import ConfigError


def test_load_yaml_reads_mapping(tmp_path: Path) -> None:
    path = tmp_path / "cli-mcp.yaml"
    path.write_text("binary: git\nsecurity:\n  readonly: true\n", encoding="utf-8")
    assert load_yaml(path) == {"binary": "git", "security": {"readonly": True}}


def test_load_yaml_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Cannot read configuration file"):
        load_yaml(tmp_path / "absent.yaml")


def test_load_yaml_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("binary: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_yaml(path)


def test_load_yaml_empty_and_non_mapping(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("# nothing\n", encoding="utf-8")
    assert load_yaml(empty) == {}
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("just a string", encoding="utf-8")
    with pytest.raises(ConfigError, match="must contain a mapping"):
        load_yaml(scalar)


def test_unwrap_merges_nested_block() -> None:
    document = {"cli-mcp": {"binary": "git", "mcp": {"transport": "http"}}, "other": 1}
    merged = unwrap(document)
    assert merged["binary"] == "git"
    assert merged["mcp"] == {"transport": "http"}
    assert merged["other"] == 1
    assert unwrap({"binary": "git"}) == {"binary": "git"}


def test_settings_from_drops_manifest_only_keys() -> None:
    settings = settings_from({"binary": "git", "tools": [{"name": "status"}]})
    assert settings.binary == "git"


def test_settings_from_rejects_unknown_keys() -> None:
    with pytest.raises(ConfigError, match="Invalid configuration"):
        settings_from({"binary": "git", "nonsense": 1})


def test_settings_from_requires_binary() -> None:
    with pytest.raises(ConfigError, match="must define a binary"):
        settings_from({})


def test_settings_from_cli_binary_wins_only_when_absent() -> None:
    assert settings_from({}, binary="git").binary == "git"
    assert settings_from({"binary": "docker"}, binary="git").binary == "docker"


def test_load_settings_from_explicit_file(tmp_path: Path) -> None:
    path = tmp_path / "custom.yaml"
    path.write_text("cli-mcp:\n  binary: git\n  mcp:\n    transport: streamable-http\n    port: 9000\n", encoding="utf-8")
    settings = load_settings(path=path)
    assert settings.mcp.transport == "streamable-http"
    assert settings.mcp.port == 9000


def test_load_settings_discovers_config_file(tmp_path: Path) -> None:
    (tmp_path / "cli-mcp.yml").write_text("binary: curl.exe\n", encoding="utf-8")
    assert load_settings(cwd=tmp_path).binary == "curl.exe"


def test_load_settings_defaults_without_file(tmp_path: Path) -> None:
    settings = load_settings(cwd=tmp_path, binary="git")
    assert settings.binary == "git"
    assert settings.mcp.transport == "stdio"


def test_load_settings_without_anything_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="No configuration file found"):
        load_settings(cwd=tmp_path)


def test_find_config_file_prefers_first_name(tmp_path: Path) -> None:
    (tmp_path / ".cli-mcp.yaml").write_text("binary: git\n", encoding="utf-8")
    assert find_config_file(tmp_path) == tmp_path / ".cli-mcp.yaml"
    assert CONFIG_FILE_NAMES[0] == "cli-mcp.yaml"
    assert find_config_file(tmp_path / "nowhere") is None


def test_template_round_trips_through_the_loader(tmp_path: Path) -> None:
    text = template("my-cli", transport="http", readonly=True, approval=True, sandbox_image="alpine:3.20")
    path = tmp_path / "cli-mcp.yaml"
    path.write_text(text, encoding="utf-8")
    settings = load_settings(path=path)
    assert settings.security.readonly is True
    assert settings.security.approval is True
    assert settings.security.sandbox is not None
    assert settings.security.sandbox.image == "alpine:3.20"
    assert "strategies: [reflection, help, manifest]" in text


def test_settings_server_name_defaults_to_binary() -> None:
    assert Settings(binary="git").server_name == "git"
