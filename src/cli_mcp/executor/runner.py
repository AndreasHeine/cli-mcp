"""Subprocess execution of discovered CLI commands."""

from __future__ import annotations

import ctypes
import locale
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from cli_mcp.config.settings import SecuritySettings
from cli_mcp.detect import reject_batch_target
from cli_mcp.errors import ExecutionError
from cli_mcp.executor.sandbox import sandbox_argv, sandbox_available

TRUNCATION_NOTE = "\n[cli-mcp: output truncated]"
_READ_SIZE = 16_384
_POLL_SECONDS = 0.005
_CLEANUP_SECONDS = 0.5


@dataclass(frozen=True)
class ExecutionResult:
    """What a CLI invocation produced."""

    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    argv: list[str]
    sandboxed: bool = False
    truncated: bool = False

    def as_payload(self) -> dict[str, Any]:
        """Return the JSON payload handed to MCP clients."""
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exitCode": self.exit_code,
            "executionTimeMs": self.execution_time_ms,
            "argv": self.argv,
            "sandboxed": self.sandboxed,
            "truncated": self.truncated,
        }


def _output_encoding() -> str:
    """Use the Windows CLI OEM code page, or the POSIX locale encoding."""
    if os.name == "nt":
        return f"cp{ctypes.WinDLL('kernel32', use_last_error=True).GetOEMCP()}"
    return locale.getencoding()


class _ThreadEntry(ctypes.Structure):
    """The documented Win32 THREADENTRY32 layout."""

    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class _WindowsTree:
    """Assign a suspended child to a job before allowing it to spawn children."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Thread32First": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
            "Thread32Next": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
            "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
            "PeekNamedPipe": (
                [
                    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                    ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
                ],
                wintypes.BOOL,
            ),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes = arguments
            function.restype = result
        self.job = self.api.CreateJobObjectW(None, None)
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self._assign(process.pid)
            self._resume(process.pid)
        except BaseException:
            self.close()
            raise

    def _assign(self, pid: int) -> None:
        handle = self.api.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.api.AssignProcessToJobObject(self.job, handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.api.CloseHandle(handle)

    def _resume(self, pid: int) -> None:
        snapshot = self.api.CreateToolhelp32Snapshot(0x0004, 0)  # SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = self.api.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == pid:
                    self._resume_thread(entry.th32ThreadID)
                    return
                found = self.api.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError(f"could not find suspended thread for process {pid}")
        finally:
            self.api.CloseHandle(snapshot)

    def _resume_thread(self, tid: int) -> None:
        handle = self.api.OpenThread(0x0002, False, tid)  # SUSPEND_RESUME
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if self.api.ResumeThread(handle) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.api.CloseHandle(handle)

    def stop(self) -> None:
        """Terminate only processes belonging to this invocation's job."""
        if not self.api.TerminateJobObject(self.job, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        """Terminate any remaining descendants and release the job handle."""
        try:
            self.stop()
        finally:
            self.api.CloseHandle(self.job)


class _PipeCapture:
    """Retain a byte prefix while continuously discarding excess pipe output."""

    def __init__(self, stream: IO[bytes], limit: int, tree: _WindowsTree | None) -> None:
        self.stream = stream
        self.fd = stream.fileno()
        self.limit = limit
        self.tree = tree
        self.data = bytearray()
        self.truncated = False
        self.finished = False
        if tree is None:
            os.set_blocking(self.fd, False)

    def read(self) -> bool:
        """Consume one bounded chunk without waiting for data or pipe closure."""
        if self.finished:
            return False
        size = _READ_SIZE
        if self.tree is not None:
            import msvcrt

            available = wintypes.DWORD()
            if not self.tree.api.PeekNamedPipe(
                msvcrt.get_osfhandle(self.fd), None, 0, None, ctypes.byref(available), None,
            ):
                error = ctypes.get_last_error()
                if error in (109, 232):  # BROKEN_PIPE / NO_DATA
                    self.finished = True
                    return False
                raise ctypes.WinError(error)
            if not available.value:
                return False
            size = min(size, available.value)
        try:
            chunk = os.read(self.fd, size)
        except BlockingIOError:
            return False
        if not chunk:
            self.finished = True
            return False
        remaining = self.limit - len(self.data)
        self.data.extend(chunk[:remaining])
        self.truncated |= len(chunk) > remaining
        return True

    def text(self, encoding: str) -> str:
        """Prefer strict UTF-8, then the CLI encoding with visible byte escapes."""
        try:
            text = self.data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            text = self.data.decode(encoding, errors="backslashreplace")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text + TRUNCATION_NOTE if self.truncated else text


def _capture_until(pipes: list[_PipeCapture], deadline: float) -> bool:
    """Drain both streams fairly until EOF or the monotonic deadline."""
    while not all(pipe.finished for pipe in pipes):
        if time.perf_counter() >= deadline:
            return False
        progressed = False
        for pipe in pipes:
            progressed |= pipe.read()
        if not progressed:
            time.sleep(min(_POLL_SECONDS, max(0.0, deadline - time.perf_counter())))
    return True


def _stop_process(process: subprocess.Popen[bytes], tree: _WindowsTree | None) -> None:
    """Kill the invocation's job/session, never processes selected by name."""
    if tree is not None:
        tree.stop()
    elif sys.platform != "win32":
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    elif process.poll() is None:
        process.kill()


def _finish_process(process: subprocess.Popen[bytes], tree: _WindowsTree | None) -> None:
    """Bound reaping and close pipes without reader threads or blocking joins."""
    try:
        if tree is not None:
            tree.close()
        elif process.returncode is None:
            # Do not signal a reaped POSIX PID/group: its ID could be reused.
            _stop_process(process, tree)
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        try:
            process.wait(timeout=_CLEANUP_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise ExecutionError(f"could not reap process {process.pid} after termination") from exc


def _collect_output(
    process: subprocess.Popen[bytes],
    tree: _WindowsTree | None,
    security: SecuritySettings,
    started: float,
    encoding: str,
) -> tuple[str, str, int, bool]:
    """Collect bounded streams and handle the shared process/pipe deadline."""
    assert process.stdout is not None
    assert process.stderr is not None
    pipes = [
        _PipeCapture(process.stdout, security.max_output_bytes, tree),
        _PipeCapture(process.stderr, security.max_output_bytes, tree),
    ]
    deadline = started + security.timeout_seconds
    captured = _capture_until(pipes, deadline)
    timed_out = not captured
    if captured:
        try:
            process.wait(timeout=max(0.0, deadline - time.perf_counter()))
        except subprocess.TimeoutExpired:
            timed_out = True
    if timed_out:
        _stop_process(process, tree)
        _capture_until(pipes, time.perf_counter() + _CLEANUP_SECONDS)
        for pipe in pipes:
            pipe.truncated |= not pipe.finished
    stdout, stderr = (pipe.text(encoding) for pipe in pipes)
    if timed_out:
        stderr += f"\n[cli-mcp] timed out after {security.timeout_seconds}s"
    exit_code = -1 if timed_out else process.returncode
    assert exit_code is not None
    return stdout, stderr, exit_code, any(pipe.truncated for pipe in pipes)


def run(
    argv: list[str],
    security: SecuritySettings,
    cwd: Path | None = None,
    *,
    env: dict[str, str] | None = None,
) -> ExecutionResult:
    """Run *argv* with bounded raw-byte capture per stream, including timeouts.

    Diagnostic/truncation notes are outside the byte budget. Decoding tries
    strict UTF-8, then Windows OEM/POSIX locale with visible backslash escapes
    for undecodable bytes, not silent loss or a reader-thread exception.
    Descendants holding inherited pipes count toward the same timeout; remaining
    job/session members are terminated on timeout. Windows job members are also
    terminated after successful exit; already-reaped POSIX IDs are not signaled.
    """
    reject_batch_target(argv[0])
    sandboxed = security.sandbox is not None
    if sandboxed and security.sandbox is not None:
        if not sandbox_available(security.sandbox.backend):
            raise ExecutionError(
                f"sandbox backend {security.sandbox.backend!r} is not available. "
                "Install it, or set security.sandbox.backend to podman."
            )
        argv_to_run = sandbox_argv(argv, security.sandbox, cwd)
    else:
        argv_to_run = list(argv)

    started = time.perf_counter()
    process: subprocess.Popen[bytes] | None = None
    tree: _WindowsTree | None = None
    try:
        encoding = _output_encoding()
        process = subprocess.Popen(
            argv_to_run,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
            cwd=str(cwd) if cwd else None,
            env=env,
            start_new_session=os.name != "nt",
            creationflags=0x0004 if os.name == "nt" else 0,  # CREATE_SUSPENDED
        )
        if os.name == "nt":
            tree = _WindowsTree(process)
        stdout, stderr, exit_code, truncated = _collect_output(process, tree, security, started, encoding)
    except OSError as exc:
        raise ExecutionError(f"could not run {argv_to_run[0]!r}: {exc}") from exc
    finally:
        if process is not None:
            try:
                _finish_process(process, tree)
            except OSError as exc:
                raise ExecutionError(f"could not clean up {argv_to_run[0]!r}: {exc}") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return ExecutionResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        execution_time_ms=elapsed_ms,
        argv=argv_to_run,
        sandboxed=sandboxed,
        truncated=truncated,
    )
