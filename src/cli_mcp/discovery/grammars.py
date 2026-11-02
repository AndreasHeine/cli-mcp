"""Framework-specific help grammars.

Each provider reads the help dialect of a specific CLI framework. They reuse the
generic parser and add the few framework-specific spellings that the generic
marker vocabulary does not cover (cobra's `(default "x")`, yargs aliases, clap
possible values, System.CommandLine command sections).
"""

from __future__ import annotations

import re

from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo
from cli_mcp.discovery.base import DiscoveryContext, HelpResult
from cli_mcp.discovery.engine import discover_from_help
from cli_mcp.models import CommandSpec, DiscoveryResult

_COBRA_DEFAULT = re.compile(r"\((default(?: value)?\s+([^)]*))\)")
_COBRA_REQUIRED = re.compile(r"\((required)\)", re.IGNORECASE)


class GenericHelpProvider:
    """Strategy 2: parse ``--help`` output of any CLI, recursively."""

    name = "help"
    strategy = "help"
    frameworks: tuple[str, ...] = ()

    def __init__(self, settings: Settings) -> None:
        """Store the settings that bound the recursive help walk."""
        self.settings = settings

    def supports(self, target: TargetInfo) -> bool:
        """Report whether the generic parser can attempt any binary."""
        return True

    def discover(self, target: TargetInfo, ctx: DiscoveryContext) -> DiscoveryResult | None:
        """Discover commands with the generic grammar."""
        result = discover_from_help(target, ctx, self.settings, self.name)
        return result if result.commands else None


class _GrammarProvider:
    """Base for framework grammars that only activate on a matching fingerprint."""

    name = "grammar"
    strategy = "help"
    frameworks: tuple[str, ...] = ()
    #: Fallback help flag for subcommands whose ``--help`` prints nothing.
    child_suffix: str | None = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def supports(self, target: TargetInfo) -> bool:
        """Activate only when the fingerprint identified one of our frameworks."""
        return target.framework in self.frameworks

    def preprocess(self, text: str) -> str:
        """Normalise framework marker spellings before the generic parser runs."""
        return text

    def refine(self, spec: CommandSpec, help_result: HelpResult) -> CommandSpec:
        """Adjust the command after generic parsing."""
        return spec

    def discover(self, target: TargetInfo, ctx: DiscoveryContext) -> DiscoveryResult | None:
        """Discover commands with this framework's grammar."""
        result = discover_from_help(
            target,
            ctx,
            self.settings,
            self.name,
            preprocess=self.preprocess,
            refine=self.refine,
            child_suffix=self.child_suffix,
        )
        return result if result.commands else None


_GIT_NEGATION = re.compile(r"--\[no-\]")
_GIT_OPTION_VALUE = re.compile(r"\[=<([^>\]]*)>\]")


class GitProvider(_GrammarProvider):
    """Git's own help dialect: grouped command lists and ``--[no-]option`` flags."""

    name = "git"
    frameworks = ("git",)
    child_suffix = "-h"

    def preprocess(self, text: str) -> str:
        """Rewrite git's negated flags and inline value placeholders into plain spellings."""
        text = _GIT_NEGATION.sub("--", text)
        return _GIT_OPTION_VALUE.sub(lambda match: f" <{match.group(1)}>", text)


class CobraProvider(_GrammarProvider):
    """Go/cobra help grammar."""

    name = "cobra"
    frameworks = ("cobra",)

    def preprocess(self, text: str) -> str:
        """Rewrite cobra's ``(default "x")`` and ``(required)`` into bracket markers."""
        text = _COBRA_DEFAULT.sub(lambda match: f"[default: {match.group(2).strip().strip(chr(34))}]", text)
        return _COBRA_REQUIRED.sub("[required]", text)


class ClapProvider(_GrammarProvider):
    """Rust/clap help grammar."""

    name = "clap"
    frameworks = ("clap",)


class DotnetProvider(_GrammarProvider):
    """.NET System.CommandLine help grammar."""

    name = "dotnet"
    frameworks = ("dotnet",)


class YargsProvider(_GrammarProvider):
    """Node.js/yargs help grammar."""

    name = "yargs"
    frameworks = ("yargs",)


class CommanderProvider(_GrammarProvider):
    """Node.js/commander.js help grammar."""

    name = "commander"
    frameworks = ("commander",)


class ClickProvider(_GrammarProvider):
    """Python/click help grammar."""

    name = "click"
    frameworks = ("click",)


class TyperProvider(_GrammarProvider):
    """Python/typer help grammar."""

    name = "typer"
    frameworks = ("typer",)


class ArgparseProvider(_GrammarProvider):
    """Python/argparse help grammar."""

    name = "argparse"
    frameworks = ("argparse",)


GRAMMAR_PROVIDERS: tuple[type[_GrammarProvider], ...] = (
    GitProvider,
    CobraProvider,
    ClapProvider,
    DotnetProvider,
    YargsProvider,
    CommanderProvider,
    ClickProvider,
    TyperProvider,
    ArgparseProvider,
)
