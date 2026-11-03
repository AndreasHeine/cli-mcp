"""Read-only rules: which binaries and verbs are considered dangerous.

The tables are intentionally explicit and overridable from configuration
(``security.block_patterns`` adds checks, ``security.allow_patterns`` re-admits
rules that would otherwise reject a legitimate command).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cli_mcp.models import CommandSpec

#: Binaries that must never be exposed as tools.
BLOCKED_BINARIES: frozenset[str] = frozenset(
    {
        "rm",
        "rmdir",
        "del",
        "erase",
        "rd",
        "mkfs",
        "format",
        "diskpart",
        "dd",
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
        "init",
        "sudo",
        "su",
        "runas",
        "kill",
        "killall",
        "pkill",
        "chmod",
        "chown",
        "reg",
        "netsh",
        "iptables",
        "systemctl",
        "sc",
    }
)

#: Subcommand verbs that mutate state and are rejected in read-only mode.
DESTRUCTIVE_VERBS: frozenset[str] = frozenset(
    {
        "rm",
        "del",
        "delete",
        "remove",
        "destroy",
        "purge",
        "prune",
        "drop",
        "uninstall",
        "shutdown",
        "reboot",
        "reset",
        "clean",
        "push",
        "apply",
        "destroy-all",
        "deregister",
        "kill",
        "stop",
        "rm-rf",
    }
)

#: Flags that turn a benign command into a destructive one.
DESTRUCTIVE_FLAGS: frozenset[str] = frozenset(
    {
        "--force",
        "-f",
        "--hard",
        "--no-preserve-root",
        "--destroy",
        "--dangerously",
        "--yes-all",
        "-rf",
        "-fr",
        "--recurse-remove",
    }
)

#: Regexes matched against the fully assembled argv.
DANGEROUS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\brm\s+-[a-z]*[rf]",
        r"\brm\b",
        r"\bdd\b.*of=",
        r"\bmkfs\b",
        r"\bformat\b",
        r"\bdiskpart\b",
        r"\bshutdown\b",
        r"\breboot\b",
        r"of=/dev/(sd|hd|nvme)",
        r"\bdel\b\s+[a-z]:",
        r"\bchmod\b\s+-[a-z]*R",
    )
)


@dataclass(frozen=True)
class RiskAssessment:
    """Why a command is considered risky, if it is."""

    destructive: bool
    reason: str | None = None


def binary_basename(name: str) -> str:
    """Strip paths and Windows extensions so allow lists can use plain names."""
    cleaned = name.replace("\\", "/").split("/")[-1]
    if cleaned.lower().endswith((".exe", ".cmd", ".bat", ".com")):
        cleaned = cleaned[:-4]
    return cleaned.lower()


def is_blocked_binary(name: str) -> bool:
    """Whether the binary itself is on the never-expose list."""
    return binary_basename(name) in BLOCKED_BINARIES


def is_destructive_verb(verb: str) -> bool:
    """Whether a subcommand verb mutates state."""
    return verb.lower().strip() in DESTRUCTIVE_VERBS


def scan_argv(argv: list[str]) -> str | None:
    """Return a reason if the assembled argv matches a dangerous pattern."""
    joined = " ".join(argv)
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(joined):
            return f"matches dangerous pattern {pattern.pattern}"
    return None


def assess(binary: str, spec: CommandSpec) -> RiskAssessment:
    """Classify a discovered command for read-only and approval decisions."""
    if is_blocked_binary(binary):
        return RiskAssessment(True, f"binary {binary} is on the never-expose list")
    for verb in spec.path:
        if is_destructive_verb(verb):
            return RiskAssessment(True, f"subcommand {verb!r} is a destructive verb")
    for param in spec.parameters:
        flag = param.cli_flag.lower()
        short = f"-{param.short}".lower() if param.short else ""
        if flag in DESTRUCTIVE_FLAGS or short in DESTRUCTIVE_FLAGS:
            return RiskAssessment(True, f"parameter {param.cli_flag} is a destructive flag")
    if spec.destructive:
        return RiskAssessment(True, "the manifest marked this command as destructive")
    return RiskAssessment(False, None)


def allowed_by_override(argv: list[str], allow_patterns: list[str]) -> bool:
    """Whether a user-supplied allow pattern re-admits the command."""
    joined = " ".join(argv)
    return any(re.search(pattern, joined, re.IGNORECASE) for pattern in allow_patterns)


def matches_block_patterns(argv: list[str], block_patterns: list[str]) -> str | None:
    """Return a reason if a user-supplied block pattern matches."""
    joined = " ".join(argv)
    for pattern in block_patterns:
        if re.search(pattern, joined, re.IGNORECASE):
            return f"matches security.block_patterns entry {pattern!r}"
    return None
