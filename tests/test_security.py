"""Unit tests for read-only rules and the access policy."""

import pytest

from cli_mcp.config.settings import SandboxSettings, SecuritySettings
from cli_mcp.errors import SecurityViolation
from cli_mcp.models import CommandSpec, Parameter, ParamKind
from cli_mcp.security.policy import AccessPolicy
from cli_mcp.security.readonly import (
    allowed_by_override,
    assess,
    binary_basename,
    is_blocked_binary,
    is_destructive_verb,
    matches_block_patterns,
    scan_argv,
)


def test_binary_basename_strips_paths_and_windows_suffixes() -> None:
    assert binary_basename("C:\\Program Files\\Git\\cmd\\git.exe") == "git"
    assert binary_basename("/usr/bin/curl") == "curl"
    assert binary_basename("reducer.py") == "reducer.py"


def test_blocked_binaries() -> None:
    assert is_blocked_binary("rm")
    assert is_blocked_binary("/bin/rm")
    assert is_blocked_binary("DELETE.BAT") is False
    assert is_blocked_binary("git") is False


def test_destructive_verbs() -> None:
    assert is_destructive_verb("push")
    assert is_destructive_verb("DELETE")
    assert is_destructive_verb("status") is False


def test_scan_argv_detects_dangerous_shapes() -> None:
    assert scan_argv(["rm", "-rf", "/tmp"]) is not None
    assert scan_argv(["dd", "if=/dev/zero", "of=/dev/sda"]) is not None
    assert scan_argv(["git", "status"]) is None


def test_assess_blocks_binaries_verbs_and_flags() -> None:
    assert assess("rm", CommandSpec(name="rm")).destructive is True
    assert assess("git", CommandSpec(name="push", path=["push"])).reason == "subcommand 'push' is a destructive verb"
    spec = CommandSpec(name="status", path=["status"], parameters=[Parameter(name="force", kind=ParamKind.FLAG)])
    assert assess("git", spec).destructive is True
    declared = CommandSpec(name="wipe", destructive=True)
    assert assess("tool", declared).destructive is True
    assert assess("git", CommandSpec(name="status", path=["status"])).destructive is False


def test_pattern_overrides() -> None:
    assert matches_block_patterns(["git", "push"], [r"\bpush\b"]) is not None
    assert matches_block_patterns(["git", "status"], [r"\bpush\b"]) is None
    assert allowed_by_override(["git", "push", "origin", "main"], [r"git push origin main"]) is True
    assert allowed_by_override(["git", "push"], [r"git pull"]) is False


def test_authorize_binary_rejects_blocked_and_unlisted() -> None:
    policy = AccessPolicy(SecuritySettings(allowlist=["git"]))
    with pytest.raises(SecurityViolation, match="never-expose list"):
        policy.authorize_binary("rm")
    with pytest.raises(SecurityViolation, match="not on the allow list"):
        policy.authorize_binary("docker")
    policy.authorize_binary("git.exe")


def test_evaluate_readonly_rejects_destructive_runs() -> None:
    policy = AccessPolicy(SecuritySettings(readonly=True))
    decision = policy.evaluate("git", CommandSpec(name="push", path=["push"]), ["git", "push"])
    assert decision.allowed is False
    assert "read-only mode" in (decision.reason or "")


def test_evaluate_readonly_rejects_dangerous_argv_even_for_benign_verbs() -> None:
    policy = AccessPolicy(SecuritySettings(readonly=True))
    decision = policy.evaluate("tool", CommandSpec(name="clean"), ["rm", "-rf", "build"])
    assert decision.allowed is False


def test_evaluate_allow_pattern_cannot_bypass_readonly() -> None:
    policy = AccessPolicy(SecuritySettings(readonly=True, allow_patterns=[r"git push origin main"]))
    decision = policy.evaluate("git", CommandSpec(name="push", path=["push"]), ["git", "push", "origin", "main"])
    assert decision.allowed is False


def test_evaluate_block_pattern_always_applies() -> None:
    policy = AccessPolicy(SecuritySettings(readonly=False, block_patterns=[r"\bdeploy\b"]))
    decision = policy.evaluate("tool", CommandSpec(name="deploy", path=["deploy"]), ["tool", "deploy"])
    assert decision.allowed is False


def test_evaluate_requires_approval_for_destructive_in_auto_mode() -> None:
    policy = AccessPolicy(SecuritySettings(readonly=False, approval=False))
    decision = policy.evaluate("git", CommandSpec(name="push", path=["push"]), ["git", "push"])
    assert decision.allowed is True
    assert decision.requires_approval is True


def test_evaluate_benign_needs_no_approval() -> None:
    policy = AccessPolicy(SecuritySettings())
    decision = policy.evaluate("git", CommandSpec(name="status", path=["status"]), ["git", "status"])
    assert decision == decision.__class__(True, False, None)


def test_authorize_execution_raises() -> None:
    policy = AccessPolicy(SecuritySettings(readonly=True, readonly_argv=[["git", "status"]]))
    with pytest.raises(SecurityViolation):
        policy.authorize_execution("git", CommandSpec(name="push", path=["push"]), ["git", "push"])
    policy.authorize_execution("git", CommandSpec(name="status", path=["status"]), ["git", "status"])


def test_assess_exposes_risk_without_arguments() -> None:
    policy = AccessPolicy(SecuritySettings(readonly=True))
    assert policy.assess("git", CommandSpec(name="purge", path=["purge"])).destructive is True


def test_summary_lists_every_active_guard() -> None:
    policy = AccessPolicy(
        SecuritySettings(
            allowlist=["git"],
            readonly=True,
            approval=True,
            approval_mode="explicit",
            sandbox=SandboxSettings(image="alpine:3.20"),
            timeout_seconds=30.0,
        )
    )
    summary = policy.summary
    assert "allow list: git" in summary
    assert "read-only" in summary
    assert "approval: explicit" in summary
    assert "sandbox: docker (alpine:3.20)" in summary
    assert "timeout 30s" in summary


def test_summary_without_restrictions() -> None:
    assert AccessPolicy(SecuritySettings()).summary == "timeout 60s"
