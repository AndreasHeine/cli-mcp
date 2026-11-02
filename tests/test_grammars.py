"""Unit tests for framework-specific grammar providers."""

from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo
from cli_mcp.discovery.base import HelpResult
from cli_mcp.discovery.engine import command_for
from cli_mcp.discovery.grammars import (
    GRAMMAR_PROVIDERS,
    ArgparseProvider,
    CobraProvider,
    CommanderProvider,
    GenericHelpProvider,
    GitProvider,
    YargsProvider,
)
from cli_mcp.discovery.help_parser import parse_help
from cli_mcp.models import CommandSpec


def target(framework: str | None = None) -> TargetInfo:
    """A target with an optional fingerprint, for provider selection tests."""
    return TargetInfo(binary="tool", resolved_path="C:\\tools\\tool.py", origin="python", framework=framework)


def test_generic_provider_supports_everything() -> None:
    provider = GenericHelpProvider(Settings(binary="tool"))
    assert provider.supports(target()) is True
    assert provider.strategy == "help"
    assert provider.name == "help"


def test_grammar_providers_activate_on_fingerprint_only() -> None:
    settings = Settings(binary="tool")
    for provider_class in GRAMMAR_PROVIDERS:
        provider = provider_class(settings)
        assert provider.supports(target()) is False
        assert provider.supports(target(provider.frameworks[0])) is True
        assert provider.supports(target("cobra")) is (provider.frameworks == ("cobra",))
        assert provider.strategy == "help"


def test_cobra_preprocess_rewrites_markers() -> None:
    provider = CobraProvider(Settings(binary="tool"))
    text = provider.preprocess('--config string   config file (default "cfg.yaml")\n--token TOKEN  api token (required)\n')
    assert '[default: cfg.yaml]' in text
    assert "[required]" in text
    parsed = parse_help("options:\n" + text)
    assert next(option for option in parsed.options if option.name == "config").default == "cfg.yaml"
    assert next(option for option in parsed.options if option.name == "token").required is True


def test_cobra_preprocess_handles_default_value_spelling() -> None:
    provider = CobraProvider(Settings(binary="tool"))
    assert "[default: 3]" in provider.preprocess("--level int (default value 3)")


def test_providers_return_none_without_help_output() -> None:
    settings = Settings(binary="tool")
    for provider_class in (*GRAMMAR_PROVIDERS, GenericHelpProvider):
        provider = provider_class(settings)
        assert provider.discover(target(), FakeContext()) is None


class FakeContext:
    """A context whose help invocations always fail."""

    settings = None
    cwd = None
    help_argv_suffix = "--help"

    def __init__(self) -> None:
        self.cache: dict[str, HelpResult] = {}

    def help_for(self, target_info, path=None, suffix=None):
        argv = [target_info.resolved_path, *(path or []), suffix or self.help_argv_suffix]
        return HelpResult(argv=argv, exit_code=1, stdout="", stderr="")


def test_refine_can_rewrite_description() -> None:
    provider = YargsProvider(Settings(binary="tool"))

    def refine(spec: CommandSpec, help_result: HelpResult) -> CommandSpec:
        return CommandSpec(**{**spec.model_dump(), "description": f"refined: {help_result.exit_code}"})

    parsed = parse_help("options:\n  --flag  toggle\n")
    spec = command_for(target("yargs"), ["bundle"], parsed, provider.name, HelpResult(argv=[], exit_code=0, stdout="x", stderr=""), refine)
    assert spec.description == "refined: 0"


def test_commander_provider_frameworks() -> None:
    assert CommanderProvider(Settings(binary="tool")).frameworks == ("commander",)
    assert ArgparseProvider(Settings(binary="tool")).frameworks == ("argparse",)


GIT_ROOT_HELP = """usage: git [-v | --version] [-h | --help] [-C <path>]

These are common Git commands used in various situations:

work on the current change
   add        Add file contents to the index
   status     Show the working tree status
"""

GIT_CHILD_HELP = """usage: git status [<options>] [--] [<pathspec>...]

    -v, --[no-]verbose    be verbose
    --[no-]porcelain[=<version>]
                          machine-readable output
"""


def test_git_preprocess_normalises_flags_and_inline_values() -> None:
    provider = GitProvider(Settings(binary="git"))
    text = provider.preprocess("    --[no-]porcelain[=<version>]\n    -v, --[no-]verbose    be verbose\n")
    assert "--porcelain <version>" in text
    assert "--verbose" in text
    parsed = parse_help(text)
    porcelain = next(option for option in parsed.options if option.name == "porcelain")
    assert porcelain.is_flag is False
    assert porcelain.type == "string"


class GitStyleContext:
    """Help runner mimicking git: ``--help`` opens a pager, ``-h`` prints usage."""

    settings = None
    cwd = None
    help_argv_suffix = "--help"

    def __init__(self) -> None:
        self.cache: dict[tuple[str, ...], HelpResult] = {}

    def help_for(self, target_info, path=None, suffix=None):
        argv = [target_info.resolved_path, *(path or []), suffix or self.help_argv_suffix]
        if not path:
            return HelpResult(argv=argv, exit_code=0, stdout=GIT_ROOT_HELP, stderr="")
        if suffix == "-h":
            return HelpResult(argv=argv, exit_code=0, stdout=GIT_CHILD_HELP, stderr="")
        return HelpResult(argv=argv, exit_code=0, stdout="", stderr="")


def test_git_provider_falls_back_to_short_help() -> None:
    provider = GitProvider(Settings(binary="git"))
    assert provider.child_suffix == "-h"
    result = provider.discover(target("git"), GitStyleContext())
    assert result is not None
    assert sorted(spec.name for spec in result.commands) == ["add", "status"]
    status = next(spec for spec in result.commands if spec.name == "status")
    names = {param.name for param in status.parameters}
    assert {"verbose", "porcelain", "pathspec"} <= names
