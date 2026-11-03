"""Access policy: the single place that decides whether a command may run."""

from __future__ import annotations

from dataclasses import dataclass

from cli_mcp.config.settings import SecuritySettings
from cli_mcp.errors import SecurityViolation
from cli_mcp.models import CommandSpec
from cli_mcp.security.readonly import (
    RiskAssessment,
    allowed_by_override,
    assess,
    binary_basename,
    is_blocked_binary,
    matches_block_patterns,
    scan_argv,
)


@dataclass(frozen=True)
class Decision:
    """Result of evaluating a request against the policy."""

    allowed: bool
    requires_approval: bool
    reason: str | None = None


class AccessPolicy:
    """Enforce the allow list, read-only mode and approval requirements."""

    def __init__(self, settings: SecuritySettings) -> None:
        """Bind the policy to its security settings."""
        self.settings = settings

    def authorize_binary(self, binary: str) -> None:
        """Reject binaries that are never allowed or not on the allow list."""
        name = binary_basename(binary)
        if is_blocked_binary(binary):
            raise SecurityViolation(f"binary {binary!r} is on the never-expose list")
        if self.settings.allowlist and name not in self.settings.allowlist:
            raise SecurityViolation(
                f"binary {binary!r} is not on the allow list ({', '.join(self.settings.allowlist)})"
            )

    def evaluate(self, binary: str, spec: CommandSpec, argv: list[str]) -> Decision:
        """Decide whether *argv* for *spec* may run, and whether approval is needed."""
        assessment: RiskAssessment = assess(binary, spec)
        blocked_reason = matches_block_patterns(argv, self.settings.block_patterns)
        override = not self.settings.readonly and allowed_by_override(argv, self.settings.allow_patterns)
        if blocked_reason and not override:
            return Decision(False, False, blocked_reason)

        dangerous = scan_argv(argv)
        if dangerous and self.settings.readonly:
            return Decision(False, False, f"read-only mode: {dangerous}")

        if self.settings.readonly and assessment.destructive:
            return Decision(False, False, f"read-only mode: {assessment.reason}")

        if self.settings.readonly and argv not in self.settings.readonly_argv:
            return Decision(False, False, "read-only mode: exact invocation is not in security.readonly_argv")

        requires_approval = self.settings.approval or assessment.destructive
        return Decision(True, requires_approval, None)

    def assess(self, binary: str, spec: CommandSpec) -> RiskAssessment:
        """Risk classification of a command, before arguments are built."""
        return assess(binary, spec)

    def authorize_execution(self, binary: str, spec: CommandSpec, argv: list[str]) -> None:
        """Raise :class:`SecurityViolation` when the request is not allowed."""
        decision = self.evaluate(binary, spec, argv)
        if not decision.allowed:
            raise SecurityViolation(decision.reason or "command rejected by security policy")

    @property
    def summary(self) -> str:
        """Human-readable description of the active policy."""
        parts = []
        if self.settings.allowlist:
            parts.append(f"allow list: {', '.join(self.settings.allowlist)}")
        if self.settings.readonly:
            parts.append(f"read-only ({len(self.settings.readonly_argv)} exact invocations)")
        if self.settings.approval:
            parts.append(f"approval: {self.settings.approval_mode}")
        if self.settings.sandbox:
            parts.append(f"sandbox: {self.settings.sandbox.backend} ({self.settings.sandbox.image})")
        parts.append(f"timeout {self.settings.timeout_seconds:g}s")
        return "; ".join(parts) or "no restrictions"
