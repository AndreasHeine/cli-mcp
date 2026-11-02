"""Discovery provider contract and the capabilities providers may use."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from cli_mcp.config.settings import DiscoverySettings
from cli_mcp.detect import TargetInfo, launch_for
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

    @property
    def ok(self) -> bool:
        """Return whether the invocation produced usable output."""
        if self.timed_out:
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

    def run(self, argv: list[str], timeout: float | None = None, env: dict[str, str] | None = None) -> HelpResult:
        """Run *argv* without a shell and capture its output."""
        limit = timeout if timeout is not None else self.settings.help_timeout_seconds
        environment = os.environ.copy()
        if env:
            environment.update(env)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=limit,
                cwd=str(self.cwd) if self.cwd else None,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _decode(exc.stdout)
            stderr = _decode(exc.stderr)
            return HelpResult(argv=list(argv), exit_code=-1, stdout=stdout, stderr=stderr, timed_out=True)
        except OSError as exc:
            return HelpResult(argv=list(argv), exit_code=-1, stdout="", stderr=str(exc))
        return HelpResult(
            argv=list(argv),
            exit_code=completed.returncode,
            stdout=_truncate(completed.stdout),
            stderr=_truncate(completed.stderr),
        )

    def help_for(self, target: TargetInfo, path: list[str] | None = None, suffix: str | None = None) -> HelpResult:
        """Run ``<binary> <path...> <suffix>`` with caching."""
        argv = [*launch_for(target.resolved_path), *(path or []), suffix or self.help_argv_suffix]
        key = tuple(argv)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
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


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _truncate(text: str) -> str:
    return text[:MAX_HELP_BYTES]
