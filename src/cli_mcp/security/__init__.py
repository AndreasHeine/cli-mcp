"""Security package."""

from cli_mcp.security.policy import AccessPolicy, Decision
from cli_mcp.security.readonly import (
    BLOCKED_BINARIES,
    DESTRUCTIVE_FLAGS,
    DESTRUCTIVE_VERBS,
    RiskAssessment,
    assess,
    binary_basename,
    is_blocked_binary,
    is_destructive_verb,
)

__all__ = [
    "BLOCKED_BINARIES",
    "DESTRUCTIVE_FLAGS",
    "DESTRUCTIVE_VERBS",
    "AccessPolicy",
    "Decision",
    "RiskAssessment",
    "assess",
    "binary_basename",
    "is_blocked_binary",
    "is_destructive_verb",
]
