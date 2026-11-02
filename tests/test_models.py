"""Unit tests for the canonical discovery model."""

import pytest

from cli_mcp.models import (
    CommandSpec,
    DiscoveryResult,
    Parameter,
    ParamKind,
    normalize_identifier,
    normalize_type,
    sanitize_tool_name,
)


def test_normalize_identifier_cleans_flags() -> None:
    assert normalize_identifier("--strip-aliases") == "strip_aliases"
    assert normalize_identifier("-i") == "i"
    assert normalize_identifier("9pct") == "arg_9pct"
    assert normalize_identifier("--") == "arg"
    assert normalize_identifier("  ") == "arg"


def test_sanitize_tool_name_follows_mcp_rules() -> None:
    assert sanitize_tool_name("git commit") == "git_commit"
    assert sanitize_tool_name("reducer.py") == "reducer.py"
    assert sanitize_tool_name("C:\\tools\\reducer.py") == "C_tools_reducer.py"
    assert sanitize_tool_name("9pct") == "tool_9pct"
    assert sanitize_tool_name("!!!") == "tool"
    assert len(sanitize_tool_name("x" * 300)) == 128
    assert all(character.isalnum() or character in "._-" for character in sanitize_tool_name("a b/c"))


def test_normalize_type_maps_framework_spellings() -> None:
    assert normalize_type(None) == "string"
    assert normalize_type("int") == "integer"
    assert normalize_type("BOOLEAN") == "boolean"
    assert normalize_type("[string]") == "string"
    assert normalize_type("weird") == "string"


def test_parameter_validators_normalise_names() -> None:
    param = Parameter(name="--out-dir", cli_name="--out-dir", short="-o", type="int", choices=[""])
    assert param.name == "out_dir"
    assert param.cli_name == "out-dir"
    assert param.short == "o"
    assert param.type == "integer"
    assert param.choices is None
    assert param.cli_flag == "--out-dir"


def test_parameter_without_cli_name_uses_argument_name() -> None:
    assert Parameter(name="verbose", kind=ParamKind.FLAG).cli_flag == "--verbose"


def test_flags_are_always_boolean_toggles() -> None:
    assert Parameter(name="verbose", kind=ParamKind.FLAG, type="string").type == "boolean"
    assert Parameter(name="level", kind=ParamKind.OPTION, type="string").type == "string"


def test_command_spec_exposes_argv_and_lookup() -> None:
    spec = CommandSpec(
        name="reduce",
        path=["reduce"],
        parameters=[
            Parameter(name="input", kind=ParamKind.OPTION, required=True),
            Parameter(name="left", kind=ParamKind.POSITIONAL),
            Parameter(name="right", kind=ParamKind.POSITIONAL),
        ],
    )
    assert spec.argv_path == ["reduce"]
    assert spec.invocation("reducer.py") == "reducer.py reduce"
    assert spec.parameter("--input") is not None
    assert spec.parameter("missing") is None
    assert [param.name for param in spec.ordered_positionals()] == ["left", "right"]


def test_command_spec_drops_invalid_names() -> None:
    assert CommandSpec(name="git commit").name == "git_commit"


def test_discovery_result_helpers() -> None:
    result = DiscoveryResult(binary="git", commands=[CommandSpec(name="status", path=["status"])])
    assert result.tool_names() == ["status"]
    assert result.get("status") is not None
    assert result.get("nope") is None
    result.add_warning("careful")
    result.add_warning("careful")
    assert result.warnings == ["careful"]


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValueError):
        Parameter(name="input", nope=1)
