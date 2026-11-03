"""Non-invasive regressions for access control and platform-safe tool calls."""

import io
import json
import shutil
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from cli_mcp.config.settings import DiscoverySettings, SecuritySettings, Settings
from cli_mcp.detect import TargetInfo, launch_for, reject_batch_target, resolve_binary
from cli_mcp.discovery.base import MAX_HELP_BYTES, DiscoveryContext, HelpResult
from cli_mcp.discovery.engine import discover_from_help, parameters_from
from cli_mcp.discovery.help_parser import parse_help
from cli_mcp.errors import ApprovalRequired, SchemaError, SecurityViolation
from cli_mcp.executor.approval import ApprovalGate
from cli_mcp.executor.argv import build_argv
from cli_mcp.mcp.server import build_server
from cli_mcp.mcp.tool_adapter import build_tool
from cli_mcp.models import CommandSpec, DiscoveryResult, Parameter, ParamKind
from cli_mcp.security.policy import AccessPolicy
from cli_mcp.security.readonly import assess


@pytest.mark.parametrize("flag,short", [("--force", "-f"), ("--hard", None), (None, "-rf")])
def test_destructive_flag_normalization(flag: str | None, short: str | None) -> None:
    spec = CommandSpec(name="status", parameters=[Parameter(name="arg", cli_name=flag, short=short)])
    assert assess("git", spec).destructive


def test_readonly_denies_unclassified_git_writes_without_running_git() -> None:
    argv = ["git", "config", "--global", "user.name", "not-executed"]
    settings = SecuritySettings(readonly=True, allow_patterns=[".*"])
    decision = AccessPolicy(settings).evaluate("git", CommandSpec(name="config", path=["config"]), argv)
    assert not decision.allowed


def test_readonly_matches_exact_tokens_not_a_joined_string() -> None:
    allowed = ["tool", "a b", "c"]
    policy = AccessPolicy(SecuritySettings(readonly=True, readonly_argv=[allowed]))
    spec = CommandSpec(name="tool")
    assert policy.evaluate("tool", spec, allowed).allowed
    assert not policy.evaluate("tool", spec, ["tool", "a", "b c"]).allowed
    assert not policy.evaluate("tool", spec, [*allowed, "--output", "file"]).allowed


def test_readonly_does_not_override_destructive_checks() -> None:
    argv = ["git", "push"]
    policy = AccessPolicy(SecuritySettings(readonly=True, readonly_argv=[argv], allow_patterns=[".*"]))
    assert not policy.evaluate("git", CommandSpec(name="push", path=["push"]), argv).allowed


@pytest.mark.parametrize("entries", [[[]], [["tool", "\0"]]])
def test_invalid_readonly_vectors_are_rejected(entries: list[list[str]]) -> None:
    with pytest.raises(ValidationError, match="readonly_argv"):
        SecuritySettings(readonly_argv=entries)


@pytest.mark.parametrize("suffix", [".bat", ".CMD"])
def test_batch_files_are_rejected_before_launch(suffix: str, monkeypatch: pytest.MonkeyPatch) -> None:
    name = f"unsafe{suffix}"
    with pytest.raises(SecurityViolation, match="underlying executable"):
        reject_batch_target(name)
    with pytest.raises(SecurityViolation):
        launch_for(name)
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    with pytest.raises(SecurityViolation):
        resolve_binary(name)


def test_short_only_options_and_long_aliases_stay_distinct() -> None:
    short = Parameter(name="count", short="n", type="integer")
    long = Parameter(name="n", cli_name="n", short="n", type="integer")
    assert short.cli_flag == "-n"
    assert long.cli_flag == "--n"
    assert build_argv(["ping"], CommandSpec(name="ping", parameters=[short]), {"count": 1}) == ["ping", "-n", "1"]


def test_help_discovery_preserves_short_option_spelling() -> None:
    parsed = parse_help("Usage: ping [options]\n\nOptions:\n  -n COUNT  Number of probes\n")
    parameters = parameters_from(parsed)
    assert len(parameters) == 1
    assert parameters[0].cli_flag == "-n"
    assert parameters[0].type == "integer"


@pytest.mark.parametrize(
    "usage,names,required",
    [
        ("nodeset-linker analyze [OPTIONS] CONFIG", ["CONFIG"], [True]),
        ("nodeset-linker diff [OPTIONS] OLD NEW", ["OLD", "NEW"], [True, True]),
        ("tool [OPTIONS] [OUTPUT]", ["OUTPUT"], [False]),
        ("tool [OPTIONS] COMMAND [ARGS]...", [], []),
        ("tool -n NODE --config FILE OUTPUT", ["OUTPUT"], [True]),
    ],
)
def test_click_usage_positionals(usage, names, required) -> None:
    params = parameters_from(parse_help(f"Usage: {usage}\n\nOptions:\n  --help  Show help\n"))
    assert [param.name for param in params] == names
    assert [param.required for param in params] == required


def test_execution_cwd_rejects_relative_or_missing_directory() -> None:
    with pytest.raises(ValidationError, match=r"execution\.cwd"):
        Settings(binary="tool", execution={"cwd": "."})
    with pytest.raises(ValidationError, match=r"execution\.cwd"):
        Settings(binary="tool", execution={"cwd": str(Path.cwd() / "not-existing-cwd-12345")})


async def test_configured_execution_cwd_is_used_without_changing_host_directory() -> None:
    original = Path.cwd()
    directory = original / "src"
    argv = [sys.executable, "-I", "-S", "-B", "-c", "import os; print(os.getcwd())"]
    settings = Settings(
        binary=sys.executable,
        execution={"cwd": str(directory)},
        security=SecuritySettings(readonly=True, readonly_argv=[argv]),
    )
    tool = build_tool(
        CommandSpec(name="cwd"), argv, settings, AccessPolicy(settings.security), ApprovalGate(settings.security)
    )
    result = json.loads(await tool.handler())
    assert Path(result["stdout"].strip()) == directory
    assert Path.cwd() == original
    from cli_mcp.schema.jsonschema import execution_result_schema

    schema = execution_result_schema()
    assert set(result) == set(schema["properties"])
    override = build_tool(
        CommandSpec(name="cwd"),
        argv,
        settings,
        AccessPolicy(settings.security),
        ApprovalGate(settings.security),
        cwd=original,
    )
    assert Path(json.loads(await override.handler())["stdout"].strip()) == original


def test_empty_readonly_allowlist_warns_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli_mcp.cli.main import _checklist, error_console
    from cli_mcp.core import PreparedCli

    messages: list[str] = []
    monkeypatch.setattr(error_console, "print", lambda *args: messages.append(str(args)))
    settings = Settings(binary=sys.executable, security=SecuritySettings(readonly=True))
    target = TargetInfo(binary=sys.executable, resolved_path=sys.executable, origin="native")
    prepared = PreparedCli(settings=settings, target=target, result=DiscoveryResult(binary=sys.executable))
    _checklist(prepared, 1)
    assert any("all executions are blocked" in message for message in messages)


def test_discovery_capture_is_bounded_and_preserves_environment() -> None:
    context = DiscoveryContext(DiscoverySettings())
    code = "import os; print(os.environ['CLI_MCP_SAFE_TEST']); print('x' * 500000)"
    result = context.run(
        [sys.executable, "-I", "-S", "-B", "-c", code],
        env={"CLI_MCP_SAFE_TEST": "in-memory"},
    )
    assert result.exit_code == 0
    assert result.stdout.startswith("in-memory\n")
    assert len(result.stdout) < MAX_HELP_BYTES + 100
    assert "output truncated" in result.stdout


def test_discovery_timeout_is_reported() -> None:
    context = DiscoveryContext(DiscoverySettings())
    result = context.run(
        [sys.executable, "-I", "-S", "-B", "-c", "import time; time.sleep(1)"],
        timeout=0.1,
    )
    assert result.timed_out
    assert result.exit_code == -1
    assert not result.ok


@pytest.mark.parametrize("max_commands", [1, 3])
def test_help_process_budget_is_checked_before_spawn(
    max_commands: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    root = "usage: tool COMMAND\n\ncommands:\n" + "".join(f"  cmd{i:03d}  Child command\n" for i in range(20))

    def fake_run(self: DiscoveryContext, argv: list[str]) -> HelpResult:
        calls.append(argv)
        text = root if len(argv) == 2 else "usage: tool child\n\noptions:\n  --verbose  Toggle\n"
        return HelpResult(argv=argv, exit_code=0, stdout=text, stderr="")

    monkeypatch.setattr(DiscoveryContext, "run", fake_run)
    settings = Settings(binary=sys.executable, discovery=DiscoverySettings(max_commands=max_commands))
    context = DiscoveryContext(settings.discovery)
    target = TargetInfo(binary=sys.executable, resolved_path=sys.executable, origin="native")
    result = discover_from_help(target, context, settings, "help")
    assert len(calls) == max_commands
    assert len(context.cache) == max_commands
    assert len(result.commands) == max_commands - 1
    assert any("help invocation budget exhausted" in warning for warning in result.warnings)
    assert not context.help_for(target, ["another-child"]).ok
    assert len(calls) == max_commands


def test_help_cache_does_not_consume_shared_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(self: DiscoveryContext, argv: list[str]) -> HelpResult:
        calls.append(argv)
        return HelpResult(argv=argv, exit_code=0, stdout="help", stderr="")

    monkeypatch.setattr(DiscoveryContext, "run", fake_run)
    context = DiscoveryContext(DiscoverySettings(max_commands=2))
    target = TargetInfo(binary=sys.executable, resolved_path=sys.executable, origin="native")
    root = context.help_for(target)
    assert context.help_for(target) is root
    child = context.help_for(target, ["child"])
    assert context.help_for(target, ["child"]) is child
    blocked = context.help_for(target, ["other"])
    assert blocked.budget_exhausted
    assert not blocked.ok
    assert "budget exhausted" in blocked.stderr
    assert context.help_for(target) is root
    assert len(calls) == 2
    assert len(context.cache) == 2


def test_failed_help_and_fallback_consume_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(self: DiscoveryContext, argv: list[str]) -> HelpResult:
        calls.append(argv)
        return HelpResult(argv=argv, exit_code=1, stdout="", stderr="")

    monkeypatch.setattr(DiscoveryContext, "run", fake_run)
    settings = Settings(binary=sys.executable, discovery=DiscoverySettings(max_commands=1))
    context = DiscoveryContext(settings.discovery)
    target = TargetInfo(binary=sys.executable, resolved_path=sys.executable, origin="native")
    result = discover_from_help(target, context, settings, "help", child_suffix="-h")
    assert len(calls) == 1
    assert calls[0][-1] == "--help"
    assert result.commands == []
    assert any("budget exhausted" in warning for warning in result.warnings)


def test_tool_limit_stops_prefetching_children(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(self: DiscoveryContext, argv: list[str]) -> HelpResult:
        calls.append(argv)
        return HelpResult(
            argv=argv,
            exit_code=0,
            stdout="usage: tool COMMAND\n\noptions:\n  --verbose  Toggle\n\ncommands:\n  child  Child command\n",
            stderr="",
        )

    monkeypatch.setattr(DiscoveryContext, "run", fake_run)
    settings = Settings(binary=sys.executable, discovery=DiscoverySettings(max_commands=1))
    context = DiscoveryContext(settings.discovery)
    target = TargetInfo(binary=sys.executable, resolved_path=sys.executable, origin="native")
    result = discover_from_help(target, context, settings, "help")
    assert len(calls) == 1
    assert len(result.commands) == 1
    assert any("capped at 1 commands" in warning for warning in result.warnings)


def test_blocked_binary_is_rejected_before_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli_mcp.core import prepare

    monkeypatch.setattr("cli_mcp.core.load_settings", lambda **kwargs: Settings(binary="rm"))
    with pytest.raises(SecurityViolation, match="never-expose"):
        prepare("rm", load_plugins=False)


async def test_safe_tool_handler_uses_exact_readonly_allowlist() -> None:
    argv = [sys.executable, "-I", "-S", "-B", "-c", "print('safe-mcp')"]
    settings = Settings(binary=sys.executable, security=SecuritySettings(readonly=True, readonly_argv=[argv]))
    tool = build_tool(
        CommandSpec(name="safe"), argv, settings, AccessPolicy(settings.security), ApprovalGate(settings.security)
    )
    payload = json.loads(await tool.handler())
    assert payload["exitCode"] == 0
    assert payload["stdout"] == "safe-mcp\n"
    assert set(payload) == {"stdout", "stderr", "exitCode", "executionTimeMs", "argv", "sandboxed", "truncated"}
    with pytest.raises(SchemaError, match="unknown argument"):
        await tool.handler(approve=True)


async def test_mcp_server_dispatches_safe_command_without_transport_or_files() -> None:
    path = ["-I", "-S", "-B", "-c", "print('safe-server')"]
    settings = Settings(
        binary=sys.executable,
        security=SecuritySettings(readonly=True, readonly_argv=[[sys.executable, *path]]),
    )
    result = DiscoveryResult(
        binary=sys.executable,
        resolved_path=sys.executable,
        commands=[CommandSpec(name="safe", path=path)],
    )
    server = build_server(settings, result)
    tools = await server.list_tools()
    safe = next(tool for tool in tools if tool.name == "safe")
    assert safe.input_schema["properties"] == {}
    response = await server.call_tool("safe", {})
    assert not response.is_error
    payload = json.loads(response.content[0].text)
    assert payload["stdout"] == "safe-server\n"
    assert payload["exitCode"] == 0


async def test_cli_approve_flag_cannot_grant_gate_approval() -> None:
    settings = Settings(binary=sys.executable, security=SecuritySettings(approval=True))
    spec = CommandSpec(name="safe", parameters=[Parameter(name="approve", kind=ParamKind.FLAG)])
    gate = ApprovalGate(settings.security, stdin=io.StringIO(), stdout=io.StringIO())
    tool = build_tool(spec, [sys.executable], settings, AccessPolicy(settings.security), gate)
    with pytest.raises(ApprovalRequired, match="Local terminal approval"):
        await tool.handler(approve=True)


async def test_loopback_ping_through_tool_adapter() -> None:
    ping = shutil.which("ping")
    if ping is None:
        pytest.skip("ping is not installed")
    count_flag = "n" if sys.platform == "win32" else "c"
    argv = [ping, f"-{count_flag}", "1", "127.0.0.1"]
    security = SecuritySettings(readonly=True, readonly_argv=[argv], timeout_seconds=5)
    settings = Settings(binary=ping, security=security)
    spec = CommandSpec(
        name="ping_loopback",
        parameters=[
            Parameter(name="count", short=count_flag, type="integer", required=True, choices=["1"]),
            Parameter(name="address", kind=ParamKind.POSITIONAL, required=True, choices=["127.0.0.1"]),
        ],
    )
    tool = build_tool(spec, [ping], settings, AccessPolicy(security), ApprovalGate(security))
    result = json.loads(await tool.handler(count=1, address="127.0.0.1"))
    assert result["exitCode"] == 0
    assert "127.0.0.1" in result["stdout"], result
    assert result["argv"] == argv
