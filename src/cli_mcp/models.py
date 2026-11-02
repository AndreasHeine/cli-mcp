"""Canonical discovery model shared by every provider and every inner layer.

The model is deliberately framework-agnostic: providers translate their own
metadata into :class:`CommandSpec` / :class:`Parameter`, and the schema,
executor and MCP layers only ever see these objects.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object"})

_TYPE_ALIASES: dict[str, str] = {
    "str": "string",
    "string": "string",
    "text": "string",
    "file": "string",
    "path": "string",
    "filename": "string",
    "dir": "string",
    "int": "integer",
    "integer": "integer",
    "count": "integer",
    "number": "number",
    "float": "number",
    "double": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "flag": "boolean",
    "list": "array",
    "array": "array",
    "json": "object",
    "object": "object",
}

_TOOL_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9_]+")
MAX_TOOL_NAME_LENGTH = 128


class ParamKind(StrEnum):
    """How a parameter is passed to the underlying CLI."""

    OPTION = "option"
    FLAG = "flag"
    POSITIONAL = "positional"


def normalize_identifier(value: str) -> str:
    """Return an MCP/client-safe argument name derived from a CLI flag."""
    cleaned = value.strip().strip("-").replace("-", "_")
    cleaned = _IDENTIFIER_RE.sub("_", cleaned).strip("_")
    if not cleaned:
        return "arg"
    if cleaned[0].isdigit():
        cleaned = f"arg_{cleaned}"
    return cleaned


def sanitize_tool_name(value: str) -> str:
    """Return a tool name conforming to the MCP tool-name rules."""
    cleaned = _TOOL_NAME_RE.sub("_", value.strip()).strip("._-")
    if not cleaned:
        return "tool"
    if cleaned[0].isdigit():
        cleaned = f"tool_{cleaned}"
    return cleaned[:MAX_TOOL_NAME_LENGTH]


def normalize_type(value: str | None) -> str:
    """Map framework type spellings onto JSON Schema types."""
    if not value:
        return "string"
    return _TYPE_ALIASES.get(value.strip().lower().strip("[]()"), "string")


class Parameter(BaseModel):
    """One argument, flag or positional of a discovered CLI command."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Argument name published in the MCP tool schema")
    kind: ParamKind = ParamKind.OPTION
    cli_name: str | None = Field(None, description="Original CLI flag name (dashed)")
    short: str | None = Field(None, description="Short flag alias, e.g. 'i' for -i")
    type: str = Field("string", description="JSON Schema type")
    description: str | None = None
    required: bool = False
    default: Any = None
    choices: list[str] | None = Field(None, description="Allowed values, published as enum")
    repeatable: bool = Field(False, description="Flag may be given more than once")
    metavar: str | None = Field(None, description="Placeholder shown in help output")

    @field_validator("name")
    @classmethod
    def _names(cls, value: str) -> str:
        return normalize_identifier(value)

    @field_validator("cli_name")
    @classmethod
    def _cli_names(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().lstrip("-")
        return stripped or None

    @field_validator("short")
    @classmethod
    def _shorts(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().lstrip("-")
        return stripped or None

    @field_validator("type")
    @classmethod
    def _types(cls, value: str) -> str:
        normalized = normalize_type(value)
        return normalized if normalized in JSON_TYPES else "string"

    @field_validator("choices")
    @classmethod
    def _choices(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        cleaned = [str(item) for item in value if str(item)]
        return cleaned or None

    @model_validator(mode="after")
    def _flag_type(self) -> Parameter:
        """Force the boolean schema type for a CLI toggle flag."""
        if self.kind is ParamKind.FLAG:
            self.type = "boolean"
        return self

    @property
    def cli_flag(self) -> str:
        """Long flag as it must appear on the command line."""
        return f"--{self.cli_name or self.name}"


class CommandSpec(BaseModel):
    """A discovered CLI command expressed as a candidate MCP tool."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="MCP tool name")
    path: list[str] = Field(default_factory=list, description="Subcommand path after the binary")
    description: str = ""
    parameters: list[Parameter] = Field(default_factory=list)
    provider: str = "unknown"
    examples: list[str] = Field(default_factory=list)
    destructive: bool = False
    has_subcommands: bool = False

    @field_validator("name")
    @classmethod
    def _names(cls, value: str) -> str:
        return sanitize_tool_name(value)

    @property
    def argv_path(self) -> list[str]:
        """Argument vector that selects this command (without the binary)."""
        return list(self.path)

    def invocation(self, binary: str) -> str:
        """Shell-style invocation string for this command."""
        return " ".join([binary, *self.path])

    def parameter(self, name: str) -> Parameter | None:
        """Look up a parameter by its published argument name."""
        target = normalize_identifier(name)
        return next((param for param in self.parameters if param.name == target), None)

    def ordered_positionals(self) -> list[Parameter]:
        """Positional parameters in declaration order."""
        return [param for param in self.parameters if param.kind is ParamKind.POSITIONAL]


class DiscoveryResult(BaseModel):
    """Outcome of a discovery run for one binary."""

    model_config = ConfigDict(extra="forbid")

    binary: str
    resolved_path: str | None = None
    framework: str | None = None
    commands: list[CommandSpec] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def tool_names(self) -> list[str]:
        """Names of the published tools."""
        return [command.name for command in self.commands]

    def get(self, name: str) -> CommandSpec | None:
        """Find a command by tool name."""
        return next((command for command in self.commands if command.name == name), None)

    def add_warning(self, message: str) -> None:
        """Record a non-fatal discovery problem."""
        if message not in self.warnings:
            self.warnings.append(message)
