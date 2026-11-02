"""Tests for JSON Schema generation, argument validation, docs and OpenAPI export."""

from typing import Any

import pytest

from cli_mcp.config.settings import ServerSettings
from cli_mcp.errors import SchemaError
from cli_mcp.models import CommandSpec, DiscoveryResult, Parameter, ParamKind
from cli_mcp.schema import (
    OPENAPI_VERSION,
    argument_name,
    build_openapi,
    cli_hint,
    coerce_choices,
    command_section,
    execution_result_schema,
    input_schema,
    parameter_schema,
    parameter_summary,
    render_docs,
    validate_arguments,
)

REDUCE = CommandSpec(
    name="reduce",
    path=["reduce"],
    description="Write a reduced copy of a nodeset file.",
    parameters=[
        Parameter(name="input", kind=ParamKind.OPTION, cli_name="input", required=True, type="string"),
        Parameter(name="strip_aliases", kind=ParamKind.FLAG, cli_name="strip-aliases", description="Drop aliases."),
        Parameter(name="level", kind=ParamKind.OPTION, cli_name="level", type="integer", default="1", choices=["1", "2", "3"]),
        Parameter(name="file", kind=ParamKind.POSITIONAL, cli_name="file", metavar="FILE", description="Target file."),
    ],
)


def test_argument_name_prefers_the_cli_name() -> None:
    assert argument_name(Parameter(name="strip_aliases", cli_name="strip-aliases")) == "strip_aliases"
    assert argument_name(Parameter(name="--out", cli_name="--out")) == "out"


def test_cli_hint_describes_each_parameter_kind() -> None:
    assert cli_hint(Parameter(name="input", kind=ParamKind.OPTION, cli_name="input")) == "CLI option: --input input"
    assert cli_hint(Parameter(name="verbose", kind=ParamKind.FLAG, cli_name="verbose")) == "CLI flag: --verbose"
    assert cli_hint(Parameter(name="file", kind=ParamKind.POSITIONAL, metavar="FILE")) == "Positional argument: FILE"


def test_parameter_schema_keeps_default_enum_and_hint() -> None:
    schema = parameter_schema(Parameter(name="level", type="integer", default="2", choices=["1", "2"], description="Depth"))
    assert schema["type"] == "integer"
    assert schema["default"] == "2"
    assert schema["enum"] == [1, 2]
    assert schema["description"].startswith("Depth")
    assert "--level" in schema["description"]


def test_parameter_schema_for_repeatable_options_uses_arrays() -> None:
    schema = parameter_schema(Parameter(name="tag", kind=ParamKind.OPTION, type="array", choices=["a", "b"], repeatable=True))
    assert schema["type"] == "array"
    assert schema["items"] == {"type": "string", "enum": ["a", "b"]}
    assert "May be passed multiple times" in schema["description"]


def test_parameter_schema_names_flags_without_help_text() -> None:
    schema = parameter_schema(Parameter(name="dry_run", kind=ParamKind.FLAG))
    assert schema["type"] == "boolean"
    assert "Toggle flag" in schema["description"]


def test_coerce_choices_narrows_numeric_enums() -> None:
    assert coerce_choices(Parameter(name="level", type="number", choices=["1", "2.5"])) == [1, 2.5]
    assert coerce_choices(Parameter(name="level", type="integer", choices=["not a number"])) == ["not a number"]
    assert coerce_choices(Parameter(name="format", type="string", choices=["xml", "json"])) == ["xml", "json"]


def test_input_schema_is_a_closed_object() -> None:
    schema = input_schema(REDUCE)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["input"]
    assert set(schema["properties"]) == {"input", "strip_aliases", "level", "file"}


def test_execution_result_schema_matches_the_tool_payload() -> None:
    schema = execution_result_schema()
    assert schema["required"] == ["stdout", "stderr", "exitCode", "executionTimeMs"]
    assert schema["properties"]["exitCode"]["type"] == "integer"
    assert schema["additionalProperties"] is False


def test_validate_arguments_normalises_dashed_keys_and_drops_none() -> None:
    validated = validate_arguments(REDUCE, {"input": "model.xml", "strip-aliases": True, "level": None})
    assert validated == {"input": "model.xml", "strip_aliases": True}


def test_validate_arguments_rejects_unknown_keys() -> None:
    with pytest.raises(SchemaError, match="unknown argument 'nope'"):
        validate_arguments(REDUCE, {"input": "model.xml", "nope": 1})


def test_validate_arguments_reports_missing_required_arguments() -> None:
    with pytest.raises(SchemaError, match="missing required argument 'input'"):
        validate_arguments(REDUCE, {})


def test_validate_arguments_reports_none_for_required_arguments() -> None:
    with pytest.raises(SchemaError, match="missing required argument 'input'"):
        validate_arguments(REDUCE, {"input": None})


def test_validate_arguments_checks_types_and_enums() -> None:
    with pytest.raises(SchemaError, match="must be of type integer"):
        validate_arguments(REDUCE, {"input": "model.xml", "level": "2"})
    with pytest.raises(SchemaError, match="must be one of"):
        validate_arguments(REDUCE, {"input": "model.xml", "level": 9})
    assert validate_arguments(REDUCE, {"input": "model.xml", "level": 2})["level"] == 2


def test_validate_arguments_rejects_booleans_as_numbers() -> None:
    with pytest.raises(SchemaError, match="must be of type integer"):
        validate_arguments(REDUCE, {"input": "model.xml", "level": True})


def test_validate_arguments_checks_array_items() -> None:
    spec = CommandSpec(
        name="tag",
        parameters=[Parameter(name="tag", kind=ParamKind.OPTION, type="array", choices=["a", "b"])],
    )
    assert validate_arguments(spec, {"tag": ["a"]}) == {"tag": ["a"]}
    with pytest.raises(SchemaError, match="invalid items"):
        validate_arguments(spec, {"tag": ["z"]})


def test_docs_document_lists_every_tool() -> None:
    result = DiscoveryResult(binary="reducer.py", resolved_path="reducer.py", framework="argparse", commands=[REDUCE], strategies=["help"])
    docs = render_docs(result, ServerSettings(name="reducer-tools"))
    assert "# `reducer.py` as an MCP server" in docs
    assert "Server name: `reducer-tools`" in docs
    assert "Discovery framework: `argparse`" in docs
    assert "### `reduce`" in docs
    assert "CLI invocation: `reducer.py reduce`" in docs
    assert "| Argument | CLI | Type | Required | Default | Description |" in docs
    assert "reducer.py reduce" in docs


def test_docs_document_escapes_table_cells() -> None:
    spec = CommandSpec(name="odd", description="a | b", parameters=[Parameter(name="x", description="p | q\nsecond line")])
    section = "\n".join(command_section(spec, "tool"))
    assert "a | b" in section
    assert "p \\| q second line" in section


def test_docs_document_notes_destructive_and_subcommands() -> None:
    spec = CommandSpec(name="push", destructive=True, has_subcommands=True, examples=["git push origin main"])
    section = "\n".join(command_section(spec, "git"))
    assert "needs approval" in section
    assert "nested subcommands" in section
    assert "```bash" in section


def test_docs_document_reports_discovery_warnings() -> None:
    result = DiscoveryResult(binary="tool", warnings=["discovery capped at 3 commands"], commands=[CommandSpec(name="a")])
    assert "## Discovery notes" in render_docs(result)
    assert "discovery capped at 3 commands" in render_docs(result)


def test_docs_document_says_tools_without_arguments() -> None:
    section = "\n".join(command_section(CommandSpec(name="info"), "tool"))
    assert "This tool takes no arguments." in section


def test_parameter_summary_is_one_line() -> None:
    assert parameter_summary(Parameter(name="input", required=True)) == "input (string, required) — CLI option: --input input"
    assert "optional" in parameter_summary(Parameter(name="level", type="integer"))


def test_openapi_document_describes_each_tool() -> None:
    result = DiscoveryResult(binary="reducer.py", framework="argparse", commands=[REDUCE], strategies=["help"])
    document = build_openapi(result, ServerSettings(name="reducer-tools", title="Nodeset tools", transport="http"))
    assert document["openapi"] == OPENAPI_VERSION
    assert document["info"]["title"] == "Nodeset tools"
    assert document["info"]["description"]
    assert "/tools/reduce" in document["paths"]
    operation: dict[str, Any] = document["paths"]["/tools/reduce"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["required"] == ["input"]
    assert operation["responses"]["403"]["description"]
    assert document["components"]["schemas"]["ExecutionResult"]["properties"]["stdout"]["type"] == "string"
    assert document["x-cli-mcp"] == {
        "binary": "reducer.py",
        "framework": "argparse",
        "strategies": ["help"],
        "transport": "http",
        "tool_count": 1,
    }


def test_openapi_document_falls_back_to_the_binary_name() -> None:
    result = DiscoveryResult(binary="tool", commands=[CommandSpec(name="a", description="")])
    document = build_openapi(result)
    assert document["info"]["title"] == "tool"
    assert "exposed as an MCP server by cli-mcp" in document["info"]["description"]
    operation: dict[str, Any] = document["paths"]["/tools/a"]["post"]
    assert operation["description"] == "Run tool"
