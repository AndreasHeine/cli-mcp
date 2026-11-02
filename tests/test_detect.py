"""Unit tests for binary resolution, classification and framework fingerprinting."""

import shutil
import sys
from pathlib import Path

import pytest

from cli_mcp.detect import classify, fingerprint, launch_command, launch_for, resolve_binary
from cli_mcp.errors import BinaryNotFoundError


def test_resolve_binary_absolute_script(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    target = resolve_binary(str(script))
    assert target.origin == "python"
    assert target.is_script
    assert target.resolved_path == str(script)


def test_resolve_binary_from_path() -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    target = resolve_binary("git")
    assert target.origin == "native"
    assert target.resolved_path.lower().endswith("git.exe")


def test_resolve_binary_missing() -> None:
    with pytest.raises(BinaryNotFoundError, match="not found"):
        resolve_binary("definitely-not-a-binary-42")


def test_classify_shebangs(tmp_path: Path) -> None:
    python = tmp_path / "noext"
    python.write_text("#!/usr/bin/env python3\nprint('x')\n", encoding="utf-8")
    assert classify(python) == "python"
    node = tmp_path / "app.mjs"
    node.write_text("console.log('x')\n", encoding="utf-8")
    assert classify(node) == "node"
    shell = tmp_path / "bare"
    shell.write_text("#!/bin/sh\necho x\n", encoding="utf-8")
    assert classify(shell) == "native"
    binary = tmp_path / "plain.txt"
    binary.write_text("hello\n", encoding="utf-8")
    assert classify(binary) == "native"


def test_classify_unreadable_file_is_native(tmp_path: Path) -> None:
    assert classify(tmp_path / "ghost.exe") == "native"


def test_launch_for_scripts_and_binaries(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    assert launch_for(str(script)) == [sys.executable, str(script)]

    js = tmp_path / "tool.js"
    js.write_text("console.log('hi')\n", encoding="utf-8")
    launch = launch_for(str(js))
    assert launch[-1] == str(js)
    assert launch[0] == (shutil.which("node") or "node")

    exe = tmp_path / "tool.txt"
    exe.write_text("hello\n", encoding="utf-8")
    assert launch_for(str(exe)) == [str(exe)]


def test_launch_command_wraps_target(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    target = resolve_binary(str(script))
    assert launch_command(target) == [sys.executable, str(script)]


def test_fingerprint_full_match() -> None:
    cobra = "Available Commands:\n  run   Run the server\n\nFlags:\n  --help  help\n"
    assert fingerprint(cobra) == "cobra"


def test_fingerprint_partial_match() -> None:
    argparse_page = "usage: tool [-h]\n\noptions:\n  -h, --help  show this help message and exit\n"
    assert fingerprint(argparse_page) == "argparse"


def test_fingerprint_unknown_and_empty() -> None:
    assert fingerprint(None) is None
    assert fingerprint("") is None
    assert fingerprint("totally unknown output") is None


def test_with_help_records_framework() -> None:
    page = "usage: tool [-h]\n\noptions:\n  -h, --help\n"
    target = resolve_binary(str(Path(__file__)))
    updated = target.with_help(page)
    assert updated.root_help == page
    assert updated.framework == "argparse"
