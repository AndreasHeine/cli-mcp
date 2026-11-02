"""Subprocess execution of discovered CLI commands."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cli_mcp.config.settings import SecuritySettings
from cli_mcp.errors import ExecutionError
from cli_mcp.executor.sandbox import sandbox_argv, sandbox_available

TRUNCATION_NOTE = "\n[cli-mcp: output truncated]"


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


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """Cap *text* at *limit* characters, reporting whether it was cut."""
    if len(text) <= limit:
        return text, False
    return text[:limit] + TRUNCATION_NOTE, True


def run(argv: list[str], security: SecuritySettings, cwd: Path | None = None) -> ExecutionResult:
    """Run *argv* and capture stdout, stderr, exit code and wall-clock time."""
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
    try:
        completed = subprocess.run(
            argv_to_run,
            capture_output=True,
            text=True,
            timeout=security.timeout_seconds,
            cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        partial_stdout = _as_text(exc.stdout)
        partial_stderr = _as_text(exc.stderr)
        return ExecutionResult(
            stdout=partial_stdout,
            stderr=f"{partial_stderr}\n[cli-mcp] timed out after {security.timeout_seconds}s",
            exit_code=-1,
            execution_time_ms=elapsed_ms,
            argv=argv_to_run,
            sandboxed=sandboxed,
            truncated=False,
        )
    except OSError as exc:
        raise ExecutionError(f"could not run {argv_to_run[0]!r}: {exc}") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    stdout, stdout_cut = _truncate(completed.stdout or "", security.max_output_bytes)
    stderr, stderr_cut = _truncate(completed.stderr or "", security.max_output_bytes)
    return ExecutionResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=completed.returncode,
        execution_time_ms=elapsed_ms,
        argv=argv_to_run,
        sandboxed=sandboxed,
        truncated=stdout_cut or stderr_cut,
    )


def _as_text(value: str | bytes | None) -> str:
    """Best-effort decoding of partially captured output."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
