"""Approval gate for risky tool invocations."""

from __future__ import annotations

import sys
from typing import TextIO

from cli_mcp.config.settings import SecuritySettings
from cli_mcp.errors import ApprovalRequired
from cli_mcp.security.policy import Decision

EXPLICIT_HINT = "Pass `approve: true` in the tool arguments to approve this execution."


class ApprovalGate:
    """Decides whether a risky invocation may proceed.

    Over stdio the process' stdin is the MCP protocol channel, so prompting is
    only possible when stdin is a terminal; otherwise the client has to approve
    explicitly with the ``approve`` argument.
    """

    def __init__(
        self,
        settings: SecuritySettings,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        """Bind the gate to the security settings and the streams it prompts on."""
        self.settings = settings
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout

    def prompt_available(self) -> bool:
        """Return whether an interactive approval prompt is possible."""
        try:
            return bool(self._stdin.isatty())
        except (ValueError, OSError):
            return False

    def approve(self, tool_name: str, argv: list[str], decision: Decision, approved: bool = False) -> None:
        """Raise :class:`ApprovalRequired` unless *decision* is approved."""
        if not decision.requires_approval:
            return
        if approved:
            return
        if self.settings.approval_mode == "explicit" or not self.prompt_available():
            raise ApprovalRequired(
                f"tool {tool_name!r} needs approval: {' '.join(argv)}. {EXPLICIT_HINT}"
            )
        self._stdout.write(f"Tool Request: {' '.join(argv)}\n")
        if decision.reason:
            self._stdout.write(f"Reason: {decision.reason}\n")
        self._stdout.write("Approve? [y/N] ")
        self._stdout.flush()
        answer = self._stdin.readline().strip().lower()
        if answer not in {"y", "yes"}:
            raise ApprovalRequired(f"approval denied for tool {tool_name!r} ({' '.join(argv)})")
