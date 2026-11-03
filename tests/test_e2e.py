"""End-to-end tests that expose real command line tools through MCP.

These run against binaries installed on the machine, so they are marked
``e2e`` and skipped when the binary is missing.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from cli_mcp.core import PreparedCli, prepare
from cli_mcp.mcp.server import build_server, tool_schemas
from cli_mcp.security.policy import AccessPolicy

pytestmark = [pytest.mark.e2e, pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")]


def init_repo(tmp_path: Path) -> Path:
    """Create an empty git repository to run read-only commands inside."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    return repo


def prepare_git(cwd: Path) -> tuple[PreparedCli, MCPServer]:
    """Expose git in read-only mode with the commands used by these tests."""
    prepared = prepare(
        "git",
        cwd=cwd,
        overrides={"include": ["status", "diff", "push"], "readonly": True, "docs": False},
    )
    prepared.settings.security.readonly_argv = [[*prepared.launch, "status", "--verbose"]]
    server = build_server(prepared.settings, prepared.result, cwd=cwd)
    return prepared, server


async def test_git_commands_become_mcp_tools(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    prepared, server = prepare_git(repo)
    names = {tool.name for tool in await server.list_tools()}
    assert {"status", "diff", "push"} <= names
    assert prepared.result.framework == "git"
    status_schema = tool_schemas(server)["status"]
    assert status_schema["additionalProperties"] is False
    assert status_schema["properties"]["verbose"]["type"] == "boolean"


async def test_git_status_runs_and_reports_the_execution_result(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    _, server = prepare_git(repo)
    result = await server.call_tool("status", {"verbose": True})
    payload = json.loads(result.content[0].text)
    assert payload["exitCode"] == 0
    assert payload["stderr"] == ""
    assert "On branch" in payload["stdout"]
    assert payload["executionTimeMs"] >= 0


async def test_read_only_mode_rejects_git_push_without_running_it(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    prepared, server = prepare_git(repo)
    policy = AccessPolicy(prepared.settings.security)
    decision = policy.evaluate("git", prepared.result.get("push"), ["git", "push", "origin", "main"])
    assert decision.allowed is False
    assert "read-only" in (decision.reason or "")
    # The handler consults the policy before the process is spawned, so git never runs.
    with pytest.raises(ToolError, match="push"):
        await server.call_tool("push", {})


async def test_allow_pattern_cannot_lift_the_read_only_block(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    prepared, _ = prepare_git(repo)
    prepared.settings.security.allow_patterns = ["git push"]
    policy = AccessPolicy(prepared.settings.security)
    decision = policy.evaluate("git", prepared.result.get("push"), ["git", "push", "origin", "main"])
    assert decision.allowed is False
    assert decision.requires_approval is False
