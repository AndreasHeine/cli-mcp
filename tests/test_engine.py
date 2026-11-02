"""Unit tests for the discovery engine: parameters, naming and the recursive help walk."""

import sys
from pathlib import Path

import pytest

from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo, launch_for
from cli_mcp.discovery.base import DiscoveryContext, HelpResult
from cli_mcp.discovery.engine import (
    SKIP_SUBCOMMANDS,
    coerce_default,
    command_for,
    discover_from_help,
    parameters_from,
    tool_base,
)
from cli_mcp.discovery.help_parser import parse_help

ROOT_HELP = """usage: tool [OPTIONS] COMMAND

Orchestrate pipelines.

options:
  --verbose   verbose logging
  --help      show this help message and exit

commands:
  reduce      Reduce a model
  diff        Compare models
"""

REDUCE_HELP = """usage: tool reduce --input FILE

options:
  --input FILE   Source file
  --quiet        Suppress output
"""

DEEP_HELP = """usage: tool reduce nested

commands:
  nested         Deep command
"""

INNER_HELP = """usage: tool reduce nested inner

options:
  --all          Include everything
"""


def script_target(tmp_path: Path) -> TargetInfo:
    """A python script target with canned help pages in the context cache."""
    script = tmp_path / "tool.py"
    script.write_text("pass\n", encoding="utf-8")
    return TargetInfo(binary="tool", resolved_path=str(script), origin="python", framework="argparse")


def canned_context(settings: Settings, target: TargetInfo, pages: dict[str, str]) -> DiscoveryContext:
    """A context whose help invocations are answered from *pages* instead of a process."""
    context = DiscoveryContext(settings.discovery, cwd=Path(target.resolved_path).parent)
    base = launch_for(target.resolved_path)
    for path_text, text in pages.items():
        path = path_text.split() if path_text else []
        argv = [*base, *path, "--help"]
        context.cache[tuple(argv)] = HelpResult(argv=argv, exit_code=0, stdout=text, stderr="")
    return context


@pytest.mark.parametrize(
    ("type_name", "raw", "expected"),
    [
        ("boolean", "true", True),
        ("boolean", "off", False),
        ("boolean", "maybe", None),
        ("integer", "7", 7),
        ("integer", "'7'", 7),
        ("integer", "abc", None),
        ("number", "2.5", 2.5),
        ("number", "abc", None),
        ("string", "none", None),
        ("string", '"xml"', "xml"),
        ("string", "", None),
        ("string", None, None),
    ],
)
def test_coerce_default(type_name: str, raw: str | None, expected: object) -> None:
    assert coerce_default(type_name, raw) == expected


def test_parameters_from_covers_every_kind() -> None:
    parsed = parse_help(
        "usage: tool <file> [--tag TAG] [--verbose] [--level N]\n\noptions:\n  --help  show this help message\n"
        "  --tag TAG   tag value [default: main]\n  --verbose     toggle\n  --level N   level [type: integer]\n"
    )
    parameters = parameters_from(parsed)
    by_name = {parameter.name: parameter for parameter in parameters}
    assert "help" not in by_name
    assert by_name["tag"].type == "string"
    assert by_name["tag"].default == "main"
    assert by_name["verbose"].kind == "flag"
    assert by_name["verbose"].description == "toggle"
    assert by_name["level"].type == "integer"
    assert by_name["file"].kind == "positional"
    assert by_name["file"].required is True
    assert by_name["file"].description == "Positional argument file"


def test_parameters_from_names_flags_without_help_text() -> None:
    parsed = parse_help("options:\n  --dry-run\n")
    parameter = parameters_from(parsed)[0]
    assert parameter.name == "dry_run"
    assert parameter.cli_name == "dry-run"
    assert parameter.kind == "flag"
    assert parameter.description == "Toggle flag"


def test_parameters_from_option_without_description() -> None:
    parsed = parse_help("options:\n  --token TOKEN\n")
    assert parameters_from(parsed)[0].description == "Value for --token"


def test_tool_base_uses_the_file_stem() -> None:
    target = TargetInfo(binary="tool", resolved_path="C:\\tools\\reducer.py", origin="python")
    assert tool_base(target) == "reducer"
    assert tool_base(TargetInfo(binary="9pct", resolved_path="", origin="native")) == "tool_9pct"


def test_command_for_names_and_describes() -> None:
    target = TargetInfo(binary="tool", resolved_path="C:\\tools\\tool.py", origin="python")
    parsed = parse_help(REDUCE_HELP)
    spec = command_for(target, ["reduce"], parsed, "argparse")
    assert spec.name == "reduce"
    assert spec.path == ["reduce"]
    assert spec.provider == "argparse"
    assert spec.examples == ["tool reduce"]
    assert spec.has_subcommands is False

    prefixed = command_for(target, ["reduce"], parsed, "argparse", prefix="tool")
    assert prefixed.name == "tool_reduce"


def test_command_for_replaces_noise_descriptions() -> None:
    target = TargetInfo(binary="tool", resolved_path="C:\\tools\\tool.py", origin="python")
    parsed = parse_help("options:\n  --help  show this help message and exit\n")
    spec = command_for(target, ["serve"], parsed, "generic")
    assert spec.description == "Run tool serve"


def test_discover_from_help_walks_subcommands(tmp_path: Path) -> None:
    settings = Settings(binary="tool")
    target = script_target(tmp_path)
    context = canned_context(settings, target, {"": ROOT_HELP, "reduce": REDUCE_HELP, "diff": REDUCE_HELP})
    result = discover_from_help(target, context, settings, "argparse")
    assert result.tool_names() == ["tool", "diff", "reduce"]
    assert result.framework == "argparse"
    assert result.strategies == ["argparse"]
    reduce_spec = result.get("reduce")
    assert reduce_spec is not None
    assert {parameter.name for parameter in reduce_spec.parameters} == {"input", "quiet"}


def test_discover_from_help_emits_root_when_it_has_options(tmp_path: Path) -> None:
    settings = Settings(binary="tool")
    target = script_target(tmp_path)
    context = canned_context(settings, target, {"": ROOT_HELP})
    result = discover_from_help(target, context, settings, "argparse")
    assert result.tool_names() == ["tool"]
    assert result.get("tool") is not None


def test_discover_from_help_skips_root_with_only_subcommands(tmp_path: Path) -> None:
    settings = Settings(binary="tool")
    target = script_target(tmp_path)
    page = "usage: tool COMMAND\n\ncommands:\n  run   Run the pipeline\n"
    context = canned_context(settings, target, {"": page, "run": REDUCE_HELP})
    result = discover_from_help(target, context, settings, "generic")
    assert result.tool_names() == ["run"]


def test_discover_from_help_respects_max_depth(tmp_path: Path) -> None:
    settings = Settings(binary="tool")
    settings.discovery.max_depth = 1
    target = script_target(tmp_path)
    context = canned_context(settings, target, {"": ROOT_HELP, "reduce": DEEP_HELP})
    result = discover_from_help(target, context, settings, "argparse")
    assert result.tool_names() == ["tool", "reduce"]


def test_discover_from_help_walks_two_levels(tmp_path: Path) -> None:
    settings = Settings(binary="tool")
    settings.discovery.max_depth = 2
    target = script_target(tmp_path)
    context = canned_context(settings, target, {"": ROOT_HELP, "reduce": DEEP_HELP, "reduce nested": INNER_HELP})
    result = discover_from_help(target, context, settings, "argparse")
    assert result.tool_names() == ["tool", "reduce", "reduce_nested"]


def test_discover_from_help_caps_command_count(tmp_path: Path) -> None:
    settings = Settings(binary="tool")
    settings.discovery.max_commands = 1
    target = script_target(tmp_path)
    context = canned_context(settings, target, {"": ROOT_HELP, "reduce": REDUCE_HELP, "diff": REDUCE_HELP})
    result = discover_from_help(target, context, settings, "argparse")
    assert len(result.commands) == 1
    assert any("capped" in warning for warning in result.warnings)


def test_discover_from_help_warns_on_missing_child_help(tmp_path: Path) -> None:
    settings = Settings(binary="tool")
    target = script_target(tmp_path)
    context = canned_context(settings, target, {"": ROOT_HELP})
    result = discover_from_help(target, context, settings, "argparse")
    assert any("reduce" in warning for warning in result.warnings)


def test_discover_from_help_warns_without_root_help(tmp_path: Path) -> None:
    settings = Settings(binary="tool")
    target = script_target(tmp_path)
    context = DiscoveryContext(settings.discovery, cwd=tmp_path)
    result = discover_from_help(target, context, settings, "generic")
    assert result.commands == []
    assert any("no help output" in warning for warning in result.warnings)


def test_discover_from_help_applies_preprocess(tmp_path: Path) -> None:
    settings = Settings(binary="tool")
    target = script_target(tmp_path)
    cobra_root = ROOT_HELP.replace("--verbose   verbose logging", '--verbose int   level (default "3")')
    context = canned_context(settings, target, {"": cobra_root})
    result = discover_from_help(
        target,
        context,
        settings,
        "cobra",
        preprocess=lambda text: text.replace('(default "3")', "[default: 3]"),
    )
    verbose = result.get("tool").parameter("verbose")
    assert verbose is not None
    assert verbose.default == 3


def test_discover_from_help_skips_help_and_completion_subcommands(tmp_path: Path) -> None:
    settings = Settings(binary="tool")
    target = script_target(tmp_path)
    page = "usage: tool COMMAND\n\ncommands:\n  help    Show help\n  serve   Serve the API\n"
    context = canned_context(settings, target, {"": page, "serve": REDUCE_HELP})
    result = discover_from_help(target, context, settings, "generic")
    assert result.tool_names() == ["serve"]
    assert "help" in SKIP_SUBCOMMANDS


def test_launch_for_python_script_is_the_interpreter(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text("print('tool')\n", encoding="utf-8")
    assert launch_for(str(script))[0] == sys.executable
