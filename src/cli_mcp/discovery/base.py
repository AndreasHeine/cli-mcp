"""Discovery provider contract and the capabilities providers may use."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from cli_mcp.config.settings import DiscoverySettings, SecuritySettings
from cli_mcp.detect import TargetInfo, launch_for
from cli_mcp.errors import ExecutionError
from cli_mcp.executor.runner import run
from cli_mcp.models import DiscoveryResult

MAX_HELP_BYTES = 400_000


@dataclass(frozen=True)
class HelpResult:
    """Captured output of a help invocation."""

    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    budget_exhausted: bool = False

    @property
    def ok(self) -> bool:
        """Return whether the invocation produced usable output."""
        if self.timed_out or self.budget_exhausted:
            return False
        return bool(self.stdout.strip() or self.stderr.strip())

    @property
    def text(self) -> str:
        """Help text, preferring stdout with a stderr fallback."""
        return self.stdout if self.stdout.strip() else self.stderr


@dataclass
class DiscoveryContext:
    """Runtime capabilities handed to providers: run help commands, read sources."""

    settings: DiscoverySettings
    cwd: Path | None = None
    help_argv_suffix: str = "--help"
    cache: dict[tuple[str, ...], HelpResult] = field(default_factory=dict)
    _help_calls: int = field(default=0, init=False)

    def run(self, argv: list[str], timeout: float | None = None, env: dict[str, str] | None = None) -> HelpResult:
        """Run *argv* without a shell and capture its output."""
        limit = timeout if timeout is not None else self.settings.help_timeout_seconds
        environment = os.environ.copy()
        if env:
            environment.update(env)
        try:
            completed = run(
                argv, SecuritySettings(timeout_seconds=limit, max_output_bytes=MAX_HELP_BYTES),
                self.cwd, env=environment,
            )
        except ExecutionError as exc:
            return HelpResult(argv=list(argv), exit_code=-1, stdout="", stderr=str(exc))
        return HelpResult(
            argv=list(argv),
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=completed.exit_code == -1 and "[cli-mcp] timed out after" in completed.stderr,
        )

    def help_for(self, target: TargetInfo, path: list[str] | None = None, suffix: str | None = None) -> HelpResult:
        """Run cached help queries with a shared budget checked before spawning."""
        argv = [*launch_for(target.resolved_path), *(path or []), suffix or self.help_argv_suffix]
        key = tuple(argv)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if self._help_calls >= self.settings.max_commands:
            return HelpResult(
                argv=argv,
                exit_code=-1,
                stdout="",
                stderr=f"discovery help invocation budget exhausted ({self.settings.max_commands} calls)",
                budget_exhausted=True,
            )
        self._help_calls += 1
        result = self.run(argv)
        self.cache[key] = result
        return result

    def read_source(self, target: TargetInfo, max_bytes: int = 200_000) -> str:
        """Read a script target's source, or return an empty string for binaries."""
        try:
            return Path(target.resolved_path).read_text(encoding="utf-8", errors="replace")[:max_bytes]
        except OSError:
            return ""

    def interpreter(self, origin: str) -> str | None:
        """Return the executable that can run a script target of the given origin."""
        if origin == "python":
            import sys

            return sys.executable
        if origin == "node":
            import shutil

            return shutil.which("node")
        return None


class DiscoveryProvider(Protocol):
    """A discovery strategy. Third parties implement this and register it."""

    name: str
    #: Strategy bucket this provider belongs to: "reflection", "help" or "manifest".
    strategy: str
    #: Framework fingerprints this provider understands.
    frameworks: tuple[str, ...]

    def supports(self, target: TargetInfo) -> bool:
        """Whether this provider can handle *target*."""
        ...

    def discover(self, target: TargetInfo, ctx: DiscoveryContext) -> DiscoveryResult | None:
        """Return command definitions, or ``None`` when this provider yields nothing."""
        ...
