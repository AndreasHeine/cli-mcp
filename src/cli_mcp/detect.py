"""Binary resolution and CLI framework fingerprinting.

Resolution answers *where* the binary is; fingerprinting answers *which
framework* produced its help output, so the matching grammar provider can be
picked before the generic parser is used.
"""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from typing import Literal

from cli_mcp.errors import BinaryNotFoundError, SecurityViolation

Origin = Literal["native", "python", "node"]

_PY_SUFFIXES = {".py", ".pyw"}
_NODE_SUFFIXES = {".js", ".mjs", ".cjs"}

#: Markers that identify a framework from its help output, in the casing each
#: framework emits. The framework with the most matched markers wins.
_FINGERPRINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("git", ("usage: git", "These are common Git commands", "git help")),
    ("cobra", ("Available Commands:", "Flags:", "(default")),
    ("clap", ("Commands:", "Options:", "possible values:", "[default:")),
    ("dotnet", ("Direct commands:", "Show help and usage", "Usage:")),
    ("typer", ("Usage:", "Options:", "--install-completion", "--show-completion")),
    ("click", ("Usage:", "Options:", "Commands:", "Show this message and exit.")),
    ("yargs", ("Options:", "[string]", "[boolean]", "[required]")),
    ("commander", ("Usage:", "[options]", "[command]", "Commands:")),
    ("argparse", ("usage:", "options:", "-h, --help", "positional arguments:")),
)

_MIN_FINGERPRINT_SCORE = 2
_ANSI_SEQUENCE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    """Remove ANSI CSI sequences before interpreting help text."""
    return _ANSI_SEQUENCE.sub("", text)


def executable_stem(path: str) -> str:
    """Extract a display name from Windows or POSIX paths on either platform."""
    return PureWindowsPath(path).stem if "\\" in path else Path(path).stem


@dataclass(frozen=True)
class TargetInfo:
    """What cli-mcp knows about the binary it is about to expose."""

    binary: str
    resolved_path: str
    origin: Origin
    framework: str | None = None
    root_help: str | None = None

    @property
    def is_script(self) -> bool:
        """Whether the target is an interpretable script rather than a native binary."""
        return self.origin != "native"

    def with_help(self, help_text: str | None) -> TargetInfo:
        """Return a copy carrying the root help text and its fingerprint."""
        return replace(self, root_help=help_text, framework=self.framework or fingerprint(help_text))


def classify(resolved_path: Path) -> Origin:
    """Detect whether the target is a native binary, a Python script or a Node script."""
    suffix = resolved_path.suffix.lower()
    if suffix in _PY_SUFFIXES:
        return "python"
    if suffix in _NODE_SUFFIXES:
        return "node"
    try:
        first_line = resolved_path.open("rb").readline()
    except OSError:
        return "native"
    if not first_line.startswith(b"#!"):
        return "native"
    shebang = first_line.decode("utf-8", errors="replace").strip().lower()
    if "python" in shebang:
        return "python"
    if "node" in shebang:
        return "node"
    return "native"


def reject_batch_target(path: str) -> None:
    """Reject Windows batch files, which can invoke a shell despite shell=False."""
    if Path(path).suffix.lower() in {".bat", ".cmd"}:
        raise SecurityViolation("Windows .bat/.cmd targets are not supported; use the underlying executable")


def resolve_binary(binary: str) -> TargetInfo:
    """Locate *binary* as a path or on ``PATH`` and classify it."""
    candidate = Path(binary)
    if candidate.is_file():
        resolved: Path | None = candidate
    else:
        found = shutil.which(binary)
        resolved = Path(found) if found else None
    if resolved is None:
        raise BinaryNotFoundError(
            f"binary {binary!r} not found. Install it, pass an absolute path, or add it to PATH."
        )
    reject_batch_target(str(resolved))
    return TargetInfo(binary=binary, resolved_path=str(resolved), origin=classify(resolved))


def launch_for(path: str) -> list[str]:
    """Command that runs *path*: an interpreter prefix when it is a script."""
    reject_batch_target(path)
    origin = classify(Path(path))
    if origin == "python":
        return [sys.executable, path]
    if origin == "node":
        return [shutil.which("node") or "node", path]
    return [path]


def launch_command(target: TargetInfo) -> list[str]:
    """Command line for *target*, without subcommand arguments."""
    return launch_for(target.resolved_path)


def fingerprint(help_text: str | None) -> str | None:
    """Identify the CLI framework from help output, if a known one matches."""
    if not help_text:
        return None
    help_text = strip_ansi(help_text)
    best_framework: str | None = None
    best_score = 0
    for framework, markers in _FINGERPRINTS:
        score = sum(1 for marker in markers if marker in help_text)
        if score > best_score:
            best_framework = framework
            best_score = score
    return best_framework if best_score >= _MIN_FINGERPRINT_SCORE else None
