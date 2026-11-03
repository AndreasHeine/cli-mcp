"""Tests for argv building, subprocess execution, sandboxing and the approval gate."""

import io
import sys
from pathlib import Path

import pytest

from cli_mcp.config.settings import SandboxSettings, SecuritySettings
from cli_mcp.errors import ApprovalRequired, ExecutionError, SecurityViolation
from cli_mcp.executor.approval import EXPLICIT_HINT, ApprovalGate
from cli_mcp.executor.argv import build_argv, format_value
from cli_mcp.executor.runner import TRUNCATION_NOTE, run
from cli_mcp.executor.sandbox import sandbox_argv, sandbox_available
from cli_mcp.models import CommandSpec, Parameter, ParamKind
from cli_mcp.security.policy import Decision

SPEC = CommandSpec(
    name="reduce",
    path=["reduce"],
    parameters=[
        Parameter(name="input", kind=ParamKind.OPTION, cli_name="input", required=True),
        Parameter(name="verbose", kind=ParamKind.FLAG, cli_name="verbose"),
        Parameter(name="tag", kind=ParamKind.OPTION, cli_name="tag", type="array", repeatable=True),
        Parameter(name="file", kind=ParamKind.POSITIONAL, cli_name="file", metavar="FILE"),
    ],
)


def test_format_value_renders_cli_tokens() -> None:
    assert format_value(Parameter(name="verbose"), True) == "true"
    assert format_value(Parameter(name="verbose"), False) == "false"
    assert format_value(Parameter(name="level"), 3) == "3"
    assert format_value(Parameter(name="level"), 1.5) == "1.5"
    assert format_value(Parameter(name="input"), None) == ""
    assert format_value(Parameter(name="input"), "model.xml") == "model.xml"


def test_build_argv_puts_options_before_positionals() -> None:
    argv = build_argv([sys.executable, "reducer.py"], SPEC, {"input": "model.xml", "verbose": True, "file": "out.xml"})
    assert argv == [sys.executable, "reducer.py", "reduce", "--input", "model.xml", "--verbose", "out.xml"]


def test_build_argv_skips_absent_and_false_values() -> None:
    argv = build_argv(["tool"], SPEC, {"input": "model.xml", "verbose": False, "file": None})
    assert argv == ["tool", "reduce", "--input", "model.xml"]


def test_build_argv_repeats_repeatable_options() -> None:
    argv = build_argv(["tool"], SPEC, {"input": "model.xml", "tag": ["a", "b"]})
    assert argv == ["tool", "reduce", "--input", "model.xml", "--tag", "a", "--tag", "b"]


def test_build_argv_accepts_textual_flag_values() -> None:
    assert build_argv(["tool"], SPEC, {"input": "m", "verbose": "yes"}) == ["tool", "reduce", "--input", "m", "--verbose"]
    assert build_argv(["tool"], SPEC, {"input": "m", "verbose": "off"}) == ["tool", "reduce", "--input", "m"]


def test_build_argv_expands_positional_lists() -> None:
    spec = CommandSpec(
        name="diff",
        path=["diff"],
        parameters=[
            Parameter(name="left", kind=ParamKind.POSITIONAL),
            Parameter(name="right", kind=ParamKind.POSITIONAL),
        ],
    )
    assert build_argv(["tool"], spec, {"left": "a.xml", "right": "b.xml"}) == ["tool", "diff", "a.xml", "b.xml"]


def test_sandbox_argv_wraps_the_command_in_a_container() -> None:
    argv = sandbox_argv(["git", "status"], SandboxSettings(), Path("/work"))
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in argv
    assert "--workdir" in argv and "/work" in argv
    assert "-v" in argv and str(Path("/work")) + ":/work" in argv
    assert argv[-3:] == ["alpine:3.20", "git", "status"]


def test_sandbox_argv_keeps_network_and_extra_args() -> None:
    sandbox = SandboxSettings(network=True, extra_args=["--user", "nobody"], image="alpine:3.20")
    argv = sandbox_argv(["tool"], sandbox, None)
    assert "--network=none" not in argv
    assert argv == ["docker", "run", "--rm", "--user", "nobody", "alpine:3.20", "tool"]


def test_sandbox_available_reports_missing_backend() -> None:
    assert sandbox_available("definitely-not-a-container-backend") is False
    assert sandbox_available(sys.executable) is True


def test_run_captures_output_and_exit_code() -> None:
    argv = [sys.executable, "-I", "-S", "-B", "-c", "import sys; print('hello'); print('oops', file=sys.stderr); sys.exit(3)"]
    result = run(argv, SecuritySettings())
    assert result.exit_code == 3
    assert result.stdout == "hello\n"
    assert result.stderr == "oops\n"
    assert result.argv == argv
    assert result.sandboxed is False
    assert result.truncated is False
    assert result.execution_time_ms >= 0
    payload = result.as_payload()
    assert payload["exitCode"] == 3
    assert payload["executionTimeMs"] >= 0


def test_run_truncates_large_output() -> None:
    result = run([sys.executable, "-I", "-S", "-B", "-c", "print('x' * 500)"], SecuritySettings(max_output_bytes=100))
    assert result.truncated is True
    assert result.stdout.endswith(TRUNCATION_NOTE)
    assert len(result.stdout) < 500


def test_run_reports_timeouts() -> None:
    result = run([sys.executable, "-I", "-S", "-B", "-c", "import time; print('early'); time.sleep(5)"], SecuritySettings(timeout_seconds=0.3))
    assert result.exit_code == -1
    assert "timed out after 0.3s" in result.stderr


def test_run_raises_when_the_binary_is_missing() -> None:
    with pytest.raises(ExecutionError, match="could not run"):
        run(["definitely-not-a-binary"], SecuritySettings())


def test_run_requires_an_available_sandbox_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli_mcp.executor.runner.sandbox_available", lambda backend: False)
    security = SecuritySettings(sandbox=SandboxSettings(backend="docker"))
    with pytest.raises(ExecutionError, match="is not available"):
        run(["git", "--version"], security)


def test_run_executes_inside_the_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli_mcp.executor.runner.sandbox_available", lambda backend: True)
    captured: list[list[str]] = []

    def fake_sandbox_argv(argv, sandbox, cwd):
        captured.append(sandbox_argv(argv, sandbox, cwd))
        return [sys.executable, "-I", "-S", "-B", "-c", "print('ok', end='')"]

    monkeypatch.setattr("cli_mcp.executor.runner.sandbox_argv", fake_sandbox_argv)
    result = run(["git", "status"], SecuritySettings(sandbox=SandboxSettings()), cwd=Path.cwd())
    assert result.sandboxed is True
    assert result.stdout == "ok"
    assert captured[0][:2] == ["docker", "run"]


class FakeTTY(io.StringIO):
    """A stream that reports itself as a terminal."""

    def isatty(self) -> bool:
        return True


def test_gate_lets_unrisky_commands_through() -> None:
    gate = ApprovalGate(SecuritySettings(approval=True))
    gate.approve("status", ["git", "status"], Decision(allowed=True, requires_approval=False))


def test_gate_requires_local_approval() -> None:
    gate = ApprovalGate(SecuritySettings(approval=True), stdin=io.StringIO(), stdout=io.StringIO())
    with pytest.raises(ApprovalRequired, match="Local terminal approval"):
        gate.approve("push", ["git", "push"], Decision(allowed=True, requires_approval=True))


def test_gate_prompts_on_a_terminal_and_accepts_yes() -> None:
    stdout = io.StringIO()
    gate = ApprovalGate(SecuritySettings(approval=True, approval_mode="prompt"), stdin=FakeTTY("y\n"), stdout=stdout)
    gate.approve("push", ["git", "push", "origin", "main"], Decision(allowed=True, requires_approval=True, reason="push is destructive"))
    assert 'Tool Request: ["git", "push", "origin", "main"]' in stdout.getvalue()
    assert "Reason: push is destructive" in stdout.getvalue()
    assert "Approve? [y/N]" in stdout.getvalue()


def test_gate_denies_when_the_answer_is_no() -> None:
    gate = ApprovalGate(
        SecuritySettings(approval=True, approval_mode="prompt"),
        stdin=FakeTTY("n\n"),
        stdout=io.StringIO(),
    )
    with pytest.raises(ApprovalRequired, match="approval denied for tool 'push'"):
        gate.approve("push", ["git", "push"], Decision(allowed=True, requires_approval=True))


def test_gate_refuses_without_a_terminal() -> None:
    gate = ApprovalGate(SecuritySettings(approval=True, approval_mode="prompt"), stdin=io.StringIO(), stdout=io.StringIO())
    with pytest.raises(ApprovalRequired) as raised:
        gate.approve("push", ["git", "push"], Decision(allowed=True, requires_approval=True))
    assert EXPLICIT_HINT in str(raised.value)
    assert '["git", "push"]' in str(raised.value)


def test_gate_explicit_mode_never_prompts() -> None:
    stdout = io.StringIO()
    gate = ApprovalGate(
        SecuritySettings(approval=True, approval_mode="explicit"),
        stdin=FakeTTY("y\n"),
        stdout=stdout,
    )
    with pytest.raises(ApprovalRequired):
        gate.approve("push", ["git", "push"], Decision(allowed=True, requires_approval=True))
    assert stdout.getvalue() == ""


def test_gate_survives_a_broken_stdin() -> None:
    class Closed(io.StringIO):
        def isatty(self) -> bool:
            raise ValueError("I/O operation on closed file")

    gate = ApprovalGate(SecuritySettings(approval=True), stdin=Closed(), stdout=io.StringIO())
    assert gate.prompt_available() is False
    with pytest.raises(SecurityViolation):
        gate.approve("push", ["git", "push"], Decision(allowed=True, requires_approval=True))
