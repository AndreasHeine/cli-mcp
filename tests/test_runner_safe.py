r"""Runner regression tests using only isolated inline children and in-memory mocks.

Run without the repository's coverage-writing addopts, for example:
python -B -m pytest -p no:cacheprovider -o addopts='' tests\test_runner_safe.py
No test creates files, invokes a container, or modifies a repository.
"""

import io
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli_mcp.config.settings import SandboxSettings, SecuritySettings
from cli_mcp.errors import ExecutionError, SecurityViolation
from cli_mcp.executor import runner


def _python(code: str) -> list[str]:
    return [sys.executable, "-I", "-S", "-B", "-c", code]


def test_capture_result_api_and_nonzero_exit() -> None:
    argv = _python("import sys; print('hello'); print('oops', file=sys.stderr); sys.exit(3)")
    result = runner.run(argv, SecuritySettings(timeout_seconds=5))
    assert result.stdout == "hello\n"
    assert result.stderr == "oops\n"
    assert result.exit_code == 3
    assert result.argv == argv
    assert result.sandboxed is False
    assert result.truncated is False
    assert result.execution_time_ms >= 0
    assert result.as_payload() == {
        "stdout": "hello\n",
        "stderr": "oops\n",
        "exitCode": 3,
        "executionTimeMs": result.execution_time_ms,
        "argv": argv,
        "sandboxed": False,
        "truncated": False,
    }


@pytest.mark.parametrize("length", [0, 31, 32, 33, 65_537])
def test_exact_independent_byte_budgets(length: int) -> None:
    code = (
        f"import sys; sys.stdout.buffer.write(b'x' * {length}); "
        f"sys.stderr.buffer.write(b'y' * {length})"
    )
    result = runner.run(_python(code), SecuritySettings(max_output_bytes=32, timeout_seconds=5))
    note = runner.TRUNCATION_NOTE if length > 32 else ""
    assert result.exit_code == 0
    assert result.stdout == "x" * min(length, 32) + note
    assert result.stderr == "y" * min(length, 32) + note
    assert result.truncated is (length > 32)


def test_large_interleaved_output_is_drained_without_deadlock() -> None:
    code = (
        "import sys\n"
        "for _ in range(32):\n"
        " sys.stdout.buffer.write(b'x' * 16384); sys.stdout.buffer.flush()\n"
        " sys.stderr.buffer.write(b'y' * 16384); sys.stderr.buffer.flush()\n"
    )
    result = runner.run(_python(code), SecuritySettings(max_output_bytes=7, timeout_seconds=10))
    assert result.exit_code == 0
    assert result.stdout == "xxxxxxx" + runner.TRUNCATION_NOTE
    assert result.stderr == "yyyyyyy" + runner.TRUNCATION_NOTE
    assert result.truncated is True


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(1, "\\xc3" + runner.TRUNCATION_NOTE), (2, "é" + runner.TRUNCATION_NOTE), (3, "éX")],
)
def test_utf8_budget_counts_raw_bytes_not_characters(monkeypatch, limit: int, expected: str) -> None:
    monkeypatch.setattr(runner, "_output_encoding", lambda: "utf-8")
    code = "import sys; sys.stdout.buffer.write(b'\\xc3\\xa9X')"
    result = runner.run(_python(code), SecuritySettings(max_output_bytes=limit, timeout_seconds=5))
    assert result.stdout == expected
    assert result.stderr == ""
    assert result.exit_code == 0
    assert result.truncated is (limit < 3)


def test_undecodable_bytes_have_visible_backslash_escapes(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_output_encoding", lambda: "utf-8")
    code = "import sys; sys.stdout.buffer.write(b'\\xffA'); sys.stderr.buffer.write(b'\\xfeB')"
    result = runner.run(_python(code), SecuritySettings(timeout_seconds=5))
    assert result.stdout == "\\xffA"
    assert result.stderr == "\\xfeB"
    assert result.exit_code == 0
    assert result.truncated is False


def test_valid_utf8_takes_precedence_over_windows_oem_fallback(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_output_encoding", lambda: "cp850")
    code = (
        "import sys; sys.stdout.buffer.write(b'Gr\\xc3\\xbc\\xc3\\x9fe'); "
        "sys.stderr.buffer.write(b'\\xe2\\x82\\xac')"
    )
    result = runner.run(_python(code), SecuritySettings(timeout_seconds=5))
    assert result.stdout == "Grüße"
    assert result.stderr == "€"
    assert result.exit_code == 0
    assert result.truncated is False


def test_invalid_utf8_uses_fallback_with_visible_undecodable_bytes(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_output_encoding", lambda: "ascii")
    code = "import sys; sys.stdout.buffer.write(b'A\\xffB'); sys.stderr.buffer.write(b'C\\xfeD')"
    result = runner.run(_python(code), SecuritySettings(timeout_seconds=5))
    assert result.stdout == "A\\xffB"
    assert result.stderr == "C\\xfeD"
    assert result.exit_code == 0
    assert result.truncated is False


def test_oem_bytes_and_universal_newlines(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_output_encoding", lambda: "cp850")
    code = "import sys; sys.stdout.buffer.write(b'Gr\\x81\\xe1e\\r\\nnext\\rline\\n')"
    result = runner.run(_python(code), SecuritySettings(timeout_seconds=5))
    assert result.stdout == "Grüße\nnext\nline\n"
    assert result.exit_code == 0
    assert result.truncated is False


def test_windows_encoding_uses_oem_not_ansi(monkeypatch) -> None:
    library = SimpleNamespace(GetOEMCP=lambda: 850)
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    loader = Mock(return_value=library)
    monkeypatch.setattr(runner.ctypes, "WinDLL", loader, raising=False)
    assert runner._output_encoding() == "cp850"
    loader.assert_called_once_with("kernel32", use_last_error=True)


def test_posix_encoding_uses_locale(monkeypatch) -> None:
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(runner.locale, "getencoding", lambda: "UTF-8")
    assert runner._output_encoding() == "UTF-8"


def test_environment_is_forwarded_to_isolated_child() -> None:
    env = dict(os.environ, CLI_MCP_SAFE_TEST="forwarded")
    result = runner.run(
        _python("import os; print(os.environ['CLI_MCP_SAFE_TEST'])"),
        SecuritySettings(timeout_seconds=5),
        env=env,
    )
    assert result.exit_code == 0
    assert result.stdout == "forwarded\n"


def test_timeout_keeps_bounded_partial_output_on_both_streams() -> None:
    code = (
        "import sys, time; "
        "sys.stdout.buffer.write(b'x' * 100000); sys.stdout.buffer.flush(); "
        "sys.stderr.buffer.write(b'y' * 100000); sys.stderr.buffer.flush(); time.sleep(10)"
    )
    result = runner.run(_python(code), SecuritySettings(max_output_bytes=17, timeout_seconds=1))
    assert result.exit_code == -1
    assert result.stdout == "x" * 17 + runner.TRUNCATION_NOTE
    assert result.stderr == "y" * 17 + runner.TRUNCATION_NOTE + "\n[cli-mcp] timed out after 1.0s"
    assert result.truncated is True
    assert result.execution_time_ms < 5000


def test_timeout_after_child_closes_pipes_still_waits_for_exit() -> None:
    code = "import os, time; os.close(1); os.close(2); time.sleep(10)"
    result = runner.run(_python(code), SecuritySettings(timeout_seconds=0.5))
    assert result.exit_code == -1
    assert result.stdout == ""
    assert result.stderr == "\n[cli-mcp] timed out after 0.5s"
    assert result.truncated is False
    assert result.execution_time_ms < 5000


def test_pipe_retention_is_bounded_through_all_discarded_chunks(monkeypatch) -> None:
    stream = Mock()
    stream.fileno.return_value = 123
    sizes = []
    chunks = iter(b"x" * runner._READ_SIZE for _ in range(256))
    monkeypatch.setattr(runner.os, "set_blocking", Mock())

    def read(fd, size):
        assert fd == 123
        sizes.append(size)
        return next(chunks, b"")

    monkeypatch.setattr(runner.os, "read", read)
    pipe = runner._PipeCapture(stream, 19, None)
    while not pipe.finished:
        pipe.read()
        assert len(pipe.data) <= 19
    assert pipe.data == b"x" * 19
    assert pipe.truncated is True
    assert sizes == [runner._READ_SIZE] * 257
    assert pipe.text("ascii") == "x" * 19 + runner.TRUNCATION_NOTE


def test_pipe_nonblocking_empty_read_is_not_eof(monkeypatch) -> None:
    stream = Mock()
    stream.fileno.return_value = 123
    monkeypatch.setattr(runner.os, "set_blocking", Mock())
    read = Mock(side_effect=[BlockingIOError(), b"a", b""])
    monkeypatch.setattr(runner.os, "read", read)
    pipe = runner._PipeCapture(stream, 1, None)
    assert pipe.read() is False
    assert pipe.finished is False
    assert pipe.read() is True
    assert pipe.read() is False
    assert pipe.finished is True
    assert pipe.data == b"a"
    assert pipe.truncated is False


def _mock_invocation(monkeypatch):
    process = Mock(pid=123, returncode=0)
    process.stdout = io.BytesIO()
    process.stderr = io.BytesIO()
    process.wait.return_value = 0
    process.poll.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    tree = Mock()
    monkeypatch.setattr(runner, "_WindowsTree", Mock(return_value=tree))
    monkeypatch.setattr(runner, "_output_encoding", lambda: "utf-8")
    captures = []

    def capture(stream, limit, tree):
        pipe = SimpleNamespace(
            finished=True,
            truncated=False,
            text=lambda encoding: "ok" if stream is process.stdout else "",
        )
        captures.append(pipe)
        return pipe

    monkeypatch.setattr(runner, "_PipeCapture", capture)
    monkeypatch.setattr(runner, "_capture_until", Mock(return_value=True))
    stop = Mock()
    monkeypatch.setattr(runner, "_stop_process", stop)
    return process, popen, captures, stop, tree


def test_sandbox_wrapper_and_env_are_passed_to_binary_popen(monkeypatch) -> None:
    process, popen, _, _, _ = _mock_invocation(monkeypatch)
    monkeypatch.setattr(runner, "sandbox_available", lambda backend: True)
    monkeypatch.setattr(runner, "sandbox_argv", lambda argv, sandbox, cwd: ["mock-container", *argv])
    env = {"KEY": "value"}
    result = runner.run(["tool", "status"], SecuritySettings(sandbox=SandboxSettings()), env=env)
    assert result.stdout == "ok"
    assert result.sandboxed is True
    assert result.argv == ["mock-container", "tool", "status"]
    assert popen.call_args.args == (result.argv,)
    kwargs = popen.call_args.kwargs
    assert kwargs["stdout"] == subprocess.PIPE
    assert kwargs["stderr"] == subprocess.PIPE
    assert kwargs["text"] is False
    assert kwargs["bufsize"] == 0
    assert kwargs["env"] is env
    assert kwargs["start_new_session"] is (os.name != "nt")
    assert kwargs["creationflags"] == (0x0004 if os.name == "nt" else 0)
    assert process.stdout.closed and process.stderr.closed


def test_inherited_open_pipe_timeout_has_bounded_cleanup(monkeypatch) -> None:
    process, _, captures, stop, _ = _mock_invocation(monkeypatch)
    deadlines = []

    def never_eof(pipes, deadline):
        deadlines.append(deadline)
        for pipe in pipes:
            pipe.finished = False
        return False

    monkeypatch.setattr(runner, "_capture_until", never_eof)
    result = runner.run(["mock-tool"], SecuritySettings(timeout_seconds=0.2))
    assert result.exit_code == -1
    assert "timed out after 0.2s" in result.stderr
    assert result.truncated is True
    assert all(pipe.truncated for pipe in captures)
    assert len(deadlines) == 2
    assert stop.call_args_list[0].args[0] is process
    assert process.stdout.closed and process.stderr.closed
    process.wait.assert_called_once_with(timeout=runner._CLEANUP_SECONDS)


def test_reaping_timeout_never_uses_an_unbounded_wait(monkeypatch) -> None:
    process, _, _, _, _ = _mock_invocation(monkeypatch)
    process.wait.side_effect = subprocess.TimeoutExpired(["mock-tool"], 0.2)
    with pytest.raises(ExecutionError, match="could not reap process 123"):
        runner.run(["mock-tool"], SecuritySettings(timeout_seconds=0.2))
    assert len(process.wait.call_args_list) == 2
    assert all(call.kwargs["timeout"] >= 0 for call in process.wait.call_args_list)
    assert process.wait.call_args_list[-1].kwargs["timeout"] == runner._CLEANUP_SECONDS
    assert process.stdout.closed and process.stderr.closed


def test_capture_error_still_closes_pipes_and_reaps(monkeypatch) -> None:
    process, _, _, _, _ = _mock_invocation(monkeypatch)
    monkeypatch.setattr(runner, "_capture_until", Mock(side_effect=OSError("pipe failure")))
    with pytest.raises(ExecutionError, match="pipe failure"):
        runner.run(["mock-tool"], SecuritySettings())
    assert process.stdout.closed and process.stderr.closed
    process.wait.assert_called_once_with(timeout=runner._CLEANUP_SECONDS)


def test_windows_job_setup_failure_kills_suspended_child(monkeypatch) -> None:
    process, _, _, stop, _ = _mock_invocation(monkeypatch)
    process.returncode = None
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(runner, "_WindowsTree", Mock(side_effect=OSError("job assignment denied")))
    with pytest.raises(ExecutionError, match="job assignment denied"):
        runner.run(["mock-tool"], SecuritySettings())
    stop.assert_called_once_with(process, None)
    assert process.stdout.closed and process.stderr.closed
    process.wait.assert_called_once_with(timeout=runner._CLEANUP_SECONDS)


@pytest.mark.parametrize("target", ["unsafe.cmd", "unsafe.BAT", r"C:\tools\unsafe.CmD"])
def test_batch_target_is_rejected_before_popen_or_sandbox_probe(monkeypatch, target) -> None:
    popen = Mock(side_effect=AssertionError("must not spawn"))
    probe = Mock(side_effect=AssertionError("must not probe"))
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner, "sandbox_available", probe)
    with pytest.raises(SecurityViolation):
        runner.run([target], SecuritySettings(sandbox=SandboxSettings()))
    popen.assert_not_called()
    probe.assert_not_called()


def test_spawn_error_is_wrapped_without_launching_anything(monkeypatch) -> None:
    monkeypatch.setattr(runner.subprocess, "Popen", Mock(side_effect=OSError("not found")))
    with pytest.raises(ExecutionError, match=r"could not run.*not found"):
        runner.run(["mock-tool"], SecuritySettings())


def test_posix_stop_targets_only_started_process_group(monkeypatch) -> None:
    killpg = Mock()
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="posix", killpg=killpg))
    monkeypatch.setattr(runner, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(runner, "signal", SimpleNamespace(SIGKILL=9))
    process = Mock(pid=123)
    runner._stop_process(process, None)
    killpg.assert_called_once_with(123, 9)
    process.kill.assert_not_called()


def test_windows_stop_targets_job_not_names(monkeypatch) -> None:
    process = Mock(pid=123)
    tree = Mock()
    runner._stop_process(process, tree)
    tree.stop.assert_called_once_with()
    process.kill.assert_not_called()


def test_windows_suspended_child_without_job_is_killed_by_handle(monkeypatch) -> None:
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(runner, "sys", SimpleNamespace(platform="win32"))
    process = Mock(pid=123)
    process.poll.return_value = None
    runner._stop_process(process, None)
    process.kill.assert_called_once_with()


def test_cleanup_does_not_signal_a_reaped_posix_process_group(monkeypatch) -> None:
    process = Mock(pid=123, returncode=0)
    process.stdout = io.BytesIO()
    process.stderr = io.BytesIO()
    stop = Mock(side_effect=AssertionError("reaped PID must not be signaled"))
    monkeypatch.setattr(runner, "_stop_process", stop)
    runner._finish_process(process, None)
    stop.assert_not_called()
    assert process.stdout.closed and process.stderr.closed
    process.wait.assert_called_once_with(timeout=runner._CLEANUP_SECONDS)


def _windows_api(monkeypatch):
    api = SimpleNamespace(
        **{
            name: Mock(return_value=1)
            for name in (
                "CreateJobObjectW", "OpenProcess", "AssignProcessToJobObject",
                "TerminateJobObject", "CloseHandle", "CreateToolhelp32Snapshot",
                "Thread32First", "Thread32Next", "OpenThread", "ResumeThread", "PeekNamedPipe",
            )
        }
    )
    monkeypatch.setattr(runner.ctypes, "WinDLL", Mock(return_value=api), raising=False)
    monkeypatch.setattr(runner.ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(runner.ctypes, "WinError", lambda error: OSError(error, "Win32 failure"), raising=False)

    def first(snapshot, entry):
        entry._obj.th32OwnerProcessID = 123
        entry._obj.th32ThreadID = 456
        return True

    api.Thread32First.side_effect = first
    return api


def test_windows_job_assignment_precedes_resume_and_closes_handles(monkeypatch) -> None:
    api = _windows_api(monkeypatch)
    events = []
    api.AssignProcessToJobObject.side_effect = lambda *args: events.append("assign") or True
    api.ResumeThread.side_effect = lambda *args: events.append("resume") or 1
    tree = runner._WindowsTree(Mock(pid=123))
    assert events == ["assign", "resume"]
    api.OpenProcess.assert_called_once_with(0x0101, False, 123)
    api.OpenThread.assert_called_once_with(0x0002, False, 456)
    tree.close()
    api.TerminateJobObject.assert_called_once_with(tree.job, 1)
    assert api.CloseHandle.call_count == 4  # process, thread, snapshot, job


def test_windows_job_assignment_failure_never_resumes(monkeypatch) -> None:
    api = _windows_api(monkeypatch)
    api.AssignProcessToJobObject.return_value = False
    with pytest.raises(OSError, match="Win32 failure"):
        runner._WindowsTree(Mock(pid=123))
    api.ResumeThread.assert_not_called()
    api.TerminateJobObject.assert_called_once()
    assert api.CloseHandle.call_count == 2


def test_windows_pipe_peek_bounds_reads_and_handles_broken_pipe(monkeypatch) -> None:
    api = _windows_api(monkeypatch)
    available = iter([50_000, 0, None])

    def peek(handle, buffer, size, read, count, left):
        assert handle == 789
        amount = next(available)
        if amount is None:
            return False
        count._obj.value = amount
        return True

    api.PeekNamedPipe.side_effect = peek
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda fd: 789))
    monkeypatch.setattr(runner.ctypes, "get_last_error", lambda: 109, raising=False)
    read = Mock(return_value=b"x" * runner._READ_SIZE)
    monkeypatch.setattr(runner.os, "read", read)
    stream = Mock()
    stream.fileno.return_value = 123
    pipe = runner._PipeCapture(stream, 3, SimpleNamespace(api=api))
    assert pipe.read() is True
    assert pipe.read() is False
    assert pipe.finished is False
    assert pipe.read() is False
    assert pipe.finished is True
    assert pipe.data == b"xxx"
    assert pipe.truncated is True
    read.assert_called_once_with(123, runner._READ_SIZE)


def test_windows_unexpected_pipe_error_is_not_silently_swallowed(monkeypatch) -> None:
    api = _windows_api(monkeypatch)
    api.PeekNamedPipe.return_value = False
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda fd: 789))
    stream = Mock()
    stream.fileno.return_value = 123
    pipe = runner._PipeCapture(stream, 3, SimpleNamespace(api=api))
    with pytest.raises(OSError, match="Win32 failure"):
        pipe.read()
