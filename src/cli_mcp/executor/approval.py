"""Approval gate for risky tool invocations."""

from __future__ import annotations

import json
import sys
import threading
from typing import TextIO

from cli_mcp.config.settings import SecuritySettings
from cli_mcp.errors import ApprovalRequired
from cli_mcp.security.policy import Decision

EXPLICIT_HINT = "Local terminal approval is required; client-supplied approval is not accepted."


class ApprovalGate:
    """Decides whether a risky invocation may proceed.

    Over stdio the process' stdin is the MCP protocol channel, so prompting is
    only possible when stdin is a terminal; otherwise the client has to approve
    through a trusted local terminal. Client arguments cannot grant approval.
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
        self._stdout = stdout or sys.stderr
        self._prompt_lock = threading.Lock()

    def prompt_available(self) -> bool:
        """Return whether an interactive approval prompt is possible."""
        try:
            return bool(self._stdin.isatty())
        except (ValueError, OSError):
            return False

    def approve(self, tool_name: str, argv: list[str], decision: Decision) -> None:
        """Raise :class:`ApprovalRequired` unless *decision* is approved."""
        if not decision.requires_approval:
            return
        display = json.dumps(argv, ensure_ascii=True)
        if self.settings.approval_mode == "explicit" or not self.prompt_available():
            raise ApprovalRequired(
                f"tool {tool_name!r} needs approval: {display}. {EXPLICIT_HINT}"
            )
        with self._prompt_lock:
            self._stdout.write(f"Tool Request: {display}\n")
            if decision.reason:
                self._stdout.write(f"Reason: {decision.reason}\n")
            self._stdout.write("Approve? [y/N] ")
            self._stdout.flush()
            try:
                answer = self._stdin.readline().strip().lower()
            except (OSError, ValueError) as exc:
                raise ApprovalRequired(f"could not read local approval for tool {tool_name!r}: {exc}") from exc
        if answer not in {"y", "yes"}:
            raise ApprovalRequired(f"approval denied for tool {tool_name!r} ({display})")
