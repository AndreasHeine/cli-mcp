"""Tests for MCP tool adaptation, server publishing and handler behaviour."""

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from cli_mcp.config.settings import SecuritySettings, ServerSettings, Settings
from cli_mcp.errors import ApprovalRequired, SchemaError, SecurityViolation
from cli_mcp.executor.approval import ApprovalGate
from cli_mcp.mcp.server import build_server, publish_schema, tool_definitions, tool_schemas
from cli_mcp.mcp.tool_adapter import build_docs_tool, build_tool, docs_tool_name, tool_description
from cli_mcp.models import CommandSpec, DiscoveryResult, Parameter, ParamKind
from cli_mcp.security.policy import AccessPolicy

SPEC = CommandSpec(
    name="reduce",
    path=["reduce"],
    description="Write a reduced copy of a nodeset file.",
    parameters=[
        Parameter(name="input", kind=ParamKind.OPTION, cli_name="input", required=True, type="string"),
        Parameter(name="output", kind=ParamKind.OPTION, cli_name="output", required=True, type="string"),
        Parameter(name="verbose", kind=ParamKind.FLAG, cli_name="verbose", description="Include detail."),
    ],
)
PUSH = CommandSpec(name="push", path=["push"], description="Push refs.", destructive=True)


def result_for(binary: str = "reducer.py") -> DiscoveryResult:
    """Discovery result with the two specs used throughout this module."""
    return DiscoveryResult(
        binary=binary,
        resolved_path=binary,
        framework="argparse",
        commands=[SPEC, PUSH],
        strategies=["help"],
    )


def launch_for_binary(binary: str) -> list[str]:
    """The launch command for a script target, matching the MCP layer."""
    return [sys.executable, str(binary)]


def test_tool_definitions_publish_one_tool_per_command() -> None:
    settings = Settings(binary="reducer.py", security=SecuritySettings(allowlist=["reducer.py"]))
    definitions = tool_definitions(settings, result_for())
    assert [definition.name for definition in definitions] == ["reduce", "push", "reducer_docs"]
    reduce = definitions[0]
    assert reduce.schema["required"] == ["input", "output"]
    assert reduce.schema["additionalProperties"] is False
    assert "reducer.py reduce" in reduce.description


def test_tool_definitions_never_publish_client_approval() -> None:
    settings = Settings(binary="reducer.py", security=SecuritySettings(allowlist=["reducer.py"], approval=True))
    definitions = {definition.name: definition for definition in tool_definitions(settings, result_for())}
    assert "approve" not in definitions["reduce"].schema["properties"]
    assert "approve" not in definitions["push"].schema["properties"]


def test_tool_definitions_reject_binaries_outside_the_allow_list() -> None:
    settings = Settings(binary="other", security=SecuritySettings(allowlist=["reducer.py"]))
    with pytest.raises(SecurityViolation, match="not on the allow list"):
        tool_definitions(settings, result_for(binary="other"))


def test_destructive_tools_are_flagged_in_their_description() -> None:
    policy = AccessPolicy(SecuritySettings(readonly=True))
    assert "needs approval" in tool_description(PUSH, "git", policy)
    assert "needs approval" not in tool_description(SPEC, "reducer.py", policy)


def test_docs_tool_name_uses_the_stem() -> None:
    assert docs_tool_name("examples/sample-clis/reducer.py") == "reducer_docs"
    assert docs_tool_name("C:\\tools\\node sample.js") == "node_sample_docs"


async def test_build_server_publishes_pinned_schemas(tmp_path: Path) -> None:
    script = tmp_path / "reducer.py"
    script.write_text("pass\n", encoding="utf-8")
    settings = Settings(
        binary=str(script),
        security=SecuritySettings(allowlist=["reducer.py"]),
        mcp=ServerSettings(name="reducer-tools", description="Reducer tools"),
    )
    server = build_server(settings, result_for(binary=str(script)))
    published = await server.list_tools()
    assert {tool.name for tool in published} == {"reduce", "push", "reducer_docs"}
    schemas = tool_schemas(server)
    assert schemas["reduce"]["properties"]["verbose"]["type"] == "boolean"
    assert schemas["reducer_docs"] == {"type": "object", "properties": {}, "additionalProperties": False}


async def test_handler_runs_the_cli_and_returns_the_payload(tmp_path: Path) -> None:
    script = tmp_path / "reducer.py"
    script.write_text("import sys\nprint('reduced ' + sys.argv[3])\n", encoding="utf-8")
    settings = Settings(binary=str(script), security=SecuritySettings(allowlist=["reducer.py"]))
    tool = build_tool(SPEC, launch_for_binary(script), settings, AccessPolicy(settings.security), ApprovalGate(settings.security))
    payload: dict[str, Any] = json.loads(await tool.handler(input="model.xml", output="reduced.xml", verbose=None))
    assert payload["stdout"] == "reduced model.xml\n"
    assert payload["exitCode"] == 0
    assert payload["argv"] == [sys.executable, str(script), "reduce", "--input", "model.xml", "--output", "reduced.xml"]


async def test_handler_rejects_arguments_the_cli_does_not_have(tmp_path: Path) -> None:
    script = tmp_path / "reducer.py"
    script.write_text("pass\n", encoding="utf-8")
    settings = Settings(binary=str(script), security=SecuritySettings(allowlist=["reducer.py"]))
    tool = build_tool(SPEC, launch_for_binary(script), settings, AccessPolicy(settings.security), ApprovalGate(settings.security))
    with pytest.raises(SchemaError, match="unknown argument"):
        await tool.handler(input="model.xml", output="out.xml", nope=True)


async def test_handler_rejects_missing_required_arguments(tmp_path: Path) -> None:
    script = tmp_path / "reducer.py"
    script.write_text("pass\n", encoding="utf-8")
    settings = Settings(binary=str(script), security=SecuritySettings(allowlist=["reducer.py"]))
    tool = build_tool(SPEC, launch_for_binary(script), settings, AccessPolicy(settings.security), ApprovalGate(settings.security))
    with pytest.raises(SchemaError, match="missing required argument"):
        await tool.handler(input=None, output="out.xml")


async def test_handler_enforces_argv_limits_before_approval() -> None:
    security = SecuritySettings(approval=True, max_argv_bytes=32)
    settings = Settings(binary="reducer.py", security=security)
    tool = build_tool(
        SPEC,
        ["reducer.py"],
        settings,
        AccessPolicy(security),
        ApprovalGate(security, stdin=io.StringIO(), stdout=io.StringIO()),
    )
    with pytest.raises(SecurityViolation, match="bytes; limit is 32"):
        await tool.handler(input="x" * 40, output="out.xml")


async def test_read_only_mode_blocks_destructive_tools(tmp_path: Path) -> None:
    script = tmp_path / "git.py"
    script.write_text("pass\n", encoding="utf-8")
    settings = Settings(binary=str(script), security=SecuritySettings(allowlist=["git.py"], readonly=True))
    tool = build_tool(PUSH, launch_for_binary(script), settings, AccessPolicy(settings.security), ApprovalGate(settings.security))
    with pytest.raises(SecurityViolation, match="read-only mode"):
        await tool.handler()


async def test_approval_mode_rejects_client_approval() -> None:
    settings = Settings(binary=sys.executable, security=SecuritySettings(approval=True))
    gate = ApprovalGate(settings.security, stdin=io.StringIO(), stdout=io.StringIO())
    tool = build_tool(
        SPEC, [sys.executable, "-I", "-S", "-B", "-c", "print('ok')"],
        settings, AccessPolicy(settings.security), gate,
    )
    with pytest.raises(ApprovalRequired, match="needs approval"):
        await tool.handler(input="model.xml", output="out.xml")
    with pytest.raises(SchemaError, match="unknown argument"):
        await tool.handler(input="model.xml", output="out.xml", approve=True)


async def test_server_call_tool_returns_text_content(tmp_path: Path) -> None:
    script = tmp_path / "reducer.py"
    script.write_text("print('done')\n", encoding="utf-8")
    settings = Settings(binary=str(script), security=SecuritySettings(allowlist=["reducer.py"]))
    server = build_server(settings, result_for(binary=str(script)))
    result = await server.call_tool("reduce", {"input": "model.xml", "output": "out.xml"})
    assert result.is_error is False
    assert json.loads(result.content[0].text)["stdout"] == "done\n"


async def test_server_reports_handler_errors(tmp_path: Path) -> None:
    script = tmp_path / "reducer.py"
    script.write_text("pass\n", encoding="utf-8")
    settings = Settings(binary=str(script), security=SecuritySettings(allowlist=["reducer.py"]))
    server = build_server(settings, result_for(binary=str(script)))
    with pytest.raises(ToolError, match="output"):
        await server.call_tool("reduce", {"input": "model.xml"})


async def test_docs_tool_returns_generated_markdown(tmp_path: Path) -> None:
    script = tmp_path / "reducer.py"
    script.write_text("pass\n", encoding="utf-8")
    settings = Settings(
        binary=str(script),
        security=SecuritySettings(allowlist=["reducer.py"]),
        mcp=ServerSettings(name="reducer-tools"),
    )
    server = build_server(settings, result_for(binary=str(script)))
    result = await server.call_tool("reducer_docs", {})
    assert result.content[0].text.startswith("# `reducer.py` as an MCP server")
    assert "Server name: `reducer-tools`" in result.content[0].text
    assert "### `reduce`" in result.content[0].text


def test_publish_schema_reports_missing_tools() -> None:
    settings = Settings(binary="reducer.py", security=SecuritySettings(allowlist=["reducer.py"]))
    server = build_server(settings, DiscoveryResult(binary="reducer.py", commands=[SPEC]))
    with pytest.raises(SchemaError, match="is not published on the server"):
        publish_schema(server, "ghost", {"type": "object"})


async def test_docs_tool_can_be_disabled(tmp_path: Path) -> None:
    script = tmp_path / "reducer.py"
    script.write_text("pass\n", encoding="utf-8")
    settings = Settings(
        binary=str(script),
        security=SecuritySettings(allowlist=["reducer.py"]),
        mcp=ServerSettings(include_docs_tool=False),
    )
    server = build_server(settings, result_for(binary=str(script)))
    assert {tool.name for tool in await server.list_tools()} == {"reduce", "push"}


def test_docs_tool_definition_is_argument_free() -> None:
    tool = build_docs_tool("# docs", "tool_docs")
    assert tool.schema["properties"] == {}
    assert inspect_signature(tool) == []


def inspect_signature(tool: Any) -> list[str]:
    """Parameter names of a tool handler's synthesised signature."""
    return [name for name in tool.handler.__signature__.parameters]
