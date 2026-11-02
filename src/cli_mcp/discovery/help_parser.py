"""Generic help-text grammar: parse ``tool --help`` output into command metadata.

This engine backs the generic help strategy and every framework-specific
grammar provider (cobra, clap, System.CommandLine, yargs, click, argparse).
Framework providers reuse it and only add their own refinements, because the
marker vocabulary below already covers defaults, types, choices and required
flags across those frameworks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

SectionName = Literal["body", "options", "commands", "positional", "other"]

HEADER_PATTERN = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /\-]*):\s*$")
SECTION_HEADERS: dict[str, SectionName] = {
    "usage": "body",
    "usage:": "body",
    "options": "options",
    "option": "options",
    "flags": "options",
    "common flags": "options",
    "common options": "options",
    "global flags": "options",
    "global options": "options",
    "optional arguments": "options",
    "optional flags": "options",
    "direct commands": "commands",
    "default commands": "commands",
    "available commands": "commands",
    "commands": "commands",
    "subcommands": "commands",
    "additional commands": "commands",
    "arguments": "positional",
    "positionals": "positional",
    "positional arguments": "positional",
    "positional": "positional",
}

#: Bracket markers understood in option descriptions.
_MARKER_PATTERN = re.compile(r"\[([^\]]+)\]")
#: cobra spells defaults and required flags in parentheses instead of brackets.
_PAREN_MARKER = re.compile(
    r"(?P<default>\((default(?: is| value)?[:\s]+[^)]*)\))|(?P<required>\(required\))",
    re.IGNORECASE,
)
_TYPE_MARKERS = {
    "string": "string",
    "str": "string",
    "text": "string",
    "integer": "integer",
    "int": "integer",
    "number": "number",
    "float": "number",
    "double": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "array": "array",
    "list": "array",
    "duration": "string",
    "date": "string",
    "enum": "string",
}
_LONG_FLAG_PATTERN = re.compile(r"^--([A-Za-z0-9][A-Za-z0-9\-]*)(?:\[=[^\]]*\])?$")
_SHORT_FLAG_PATTERN = re.compile(r"^-([A-Za-z0-9])$")
_PLACEHOLDER_PATTERN = re.compile(r"^<([^>]+)>$")
_TYPEWORD_PATTERN = re.compile(r"^[A-Za-z]+$")


@dataclass
class ParsedOption:
    """Option/flag parsed from a help section."""

    name: str
    short: str | None = None
    metavar: str | None = None
    description: str = ""
    type: str = "string"
    default: str | None = None
    choices: list[str] | None = None
    required: bool = False
    is_flag: bool = False


@dataclass
class ParsedPositional:
    """Positional argument parsed from a help section or usage line."""

    name: str
    description: str = ""
    required: bool = True
    type: str = "string"


@dataclass
class ParsedSubcommand:
    """Subcommand advertised by a help section."""

    name: str
    description: str = ""


@dataclass
class ParsedHelp:
    """Structured view of one help page."""

    description: str = ""
    options: list[ParsedOption] = field(default_factory=list)
    positionals: list[ParsedPositional] = field(default_factory=list)
    subcommands: list[ParsedSubcommand] = field(default_factory=list)
    usage: str = ""
    required_options: set[str] = field(default_factory=set)


def _bracket_marker(token: str) -> tuple[str, str] | None:
    """Turn one bracket marker into a field/value pair, or ``None`` if it is not one."""
    lowered = token.lower()
    if lowered.startswith("default:"):
        return ("default", token.split(":", 1)[1].strip().strip('"').strip("'"))
    if lowered in {"required", "required:"} or lowered.endswith("required"):
        return ("required", "true")
    if lowered == "optional":
        return ("required", "false")
    if lowered.startswith(("choices:", "possible values:")):
        return ("choices", token.split(":", 1)[1].strip())
    if lowered.startswith("aliases:"):
        return ("aliases", token.split(":", 1)[1].strip())
    if lowered in _TYPE_MARKERS:
        return ("type", _TYPE_MARKERS[lowered])
    if lowered.startswith("type:"):
        type_name = _TYPE_MARKERS.get(token.split(":", 1)[1].strip().lower())
        return None if type_name is None else ("type", type_name)
    if lowered.startswith("env var:"):
        return ("env", token.split(":", 1)[1].strip())
    return None


def _bracket_markers(line: str, consumed: list[tuple[int, int]]) -> dict[str, str]:
    """Collect bracket markers from a line and record the spans they occupy."""
    markers: dict[str, str] = {}
    for match in _MARKER_PATTERN.finditer(line):
        marker = _bracket_marker(match.group(1).strip())
        if marker is None:
            continue
        markers[marker[0]] = marker[1]
        consumed.append(match.span())
    return markers


def _paren_markers(line: str, consumed: list[tuple[int, int]]) -> dict[str, str]:
    """Collect cobra's parenthesised default and required markers."""
    markers: dict[str, str] = {}
    for match in _PAREN_MARKER.finditer(line):
        if match.group("required"):
            markers["required"] = "true"
        else:
            markers["default"] = _paren_default(match.group("default"))
        consumed.append(match.span())
    return markers


def parse_markers(line: str) -> tuple[dict[str, str], str]:
    """Pull framework markers out of a line and return them plus the clean text."""
    consumed: list[tuple[int, int]] = []
    markers = _bracket_markers(line, consumed)
    markers.update(_paren_markers(line, consumed))
    parts: list[str] = []
    previous = 0
    for start, end in sorted(consumed):
        parts.append(line[previous:start])
        previous = end
    parts.append(line[previous:])
    cleaned = " ".join(part.strip() for part in parts if part.strip())
    return markers, cleaned


def _paren_default(text: str) -> str:
    """Extract the value from cobra's ``(default "x")`` / ``(default is "x")`` marker."""
    inner = text.strip().strip("(").strip(")").strip()
    for prefix in ("default is", "default value", "default"):
        if inner.lower().startswith(prefix):
            inner = inner[len(prefix) :]
            break
    return inner.strip().strip(":=").strip().strip('"').strip("'")


_INTEGER_METAVAR_WORDS = re.compile(r"\b(count|num|number|level|max|min|n|retries|limit|index|port|pid)\b")


def _infer_type(metavar: str | None, markers: dict[str, str]) -> str:
    """Derive a JSON Schema type from markers and the metavar placeholder."""
    if "type" in markers:
        return markers["type"]
    if markers.get("choices"):
        return "string"
    if metavar:
        lowered = metavar.lower()
        if lowered in _TYPE_MARKERS:
            return _TYPE_MARKERS[lowered]
        if re.fullmatch(r"[A-Z0-9_]+", metavar):
            return "integer" if _INTEGER_METAVAR_WORDS.search(lowered) else "string"
        if any(word in lowered for word in ("bool", "flag")):
            return "boolean"
    return "string"


def _consume_flag_tokens(tokens: list[str]) -> tuple[list[str], str | None, int]:
    """Read leading ``-x`` / ``--long`` tokens and return where the description starts."""
    shorts: list[str] = []
    long_name: str | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index].rstrip(",")
        short_match = _SHORT_FLAG_PATTERN.match(token)
        long_match = _LONG_FLAG_PATTERN.match(token)
        if short_match:
            shorts.append(short_match.group(1))
            index += 1
            if index < len(tokens) and tokens[index] == ",":
                index += 1
            continue
        if long_match:
            long_name = long_match.group(1)
            index += 1
            break
        break
    return shorts, long_name, index


_BRACE_PATTERN = re.compile(r"^\{(.+)\}$")


def _consume_metavar(tokens: list[str], index: int) -> tuple[str | None, int]:
    """Read an option value placeholder such as ``--input <FILE>`` or ``--format {a,b}``."""
    if index >= len(tokens):
        return None, index
    candidate = tokens[index]
    placeholder = _PLACEHOLDER_PATTERN.match(candidate)
    if placeholder:
        return placeholder.group(1), index + 1
    brace = _BRACE_PATTERN.match(candidate)
    if brace:
        return brace.group(0), index + 1
    if (_TYPEWORD_PATTERN.match(candidate) and candidate.lower() in _TYPE_MARKERS) or candidate.isupper():
        return candidate, index + 1
    return None, index


def _parse_option_line(line: str) -> tuple[ParsedOption | None, str]:
    """Parse an option entry; return the option and any trailing description text."""
    markers, text = parse_markers(line)
    tokens = text.split()
    if not tokens:
        return None, ""

    shorts, long_name, index = _consume_flag_tokens(tokens)
    if long_name is None and not shorts:
        return None, text

    metavar, index = _consume_metavar(tokens, index)
    brace = _BRACE_PATTERN.match(metavar) if metavar else None
    choices = _split_choices(brace.group(1)) if brace else _split_choices(markers.get("choices"))

    description = " ".join(tokens[index:]).strip()
    aliases = markers.get("aliases")
    if aliases:
        description = f"{description} (aliases: {aliases})".strip()
    if not long_name:
        # Only a short flag was advertised; publish it as an option using its own name.
        long_name = shorts[0] if shorts else "arg"

    option = ParsedOption(
        name=long_name,
        short=shorts[0] if shorts else None,
        metavar=metavar,
        description=description,
        type=_infer_type(metavar, markers),
        default=markers.get("default"),
        choices=choices,
        required=markers.get("required") == "true",
        is_flag=metavar is None and choices is None and markers.get("type") != "array",
    )
    return option, description


def _split_choices(value: str | None) -> list[str] | None:
    """Split a ``choices: a, b`` marker into a list."""
    if not value:
        return None
    cleaned = [item.strip().strip("'\"") for item in re.split(r"[,\s]+", value) if item.strip()]
    return cleaned or None


def _parse_positional_line(line: str) -> ParsedPositional | None:
    """Parse a positional entry such as ``<input>  the input file``."""
    markers, text = parse_markers(line)
    tokens = text.split()
    if not tokens:
        return None
    first = tokens[0]
    placeholder = _PLACEHOLDER_PATTERN.match(first)
    if placeholder:
        name = placeholder.group(1)
        required = True
    elif first.startswith("{"):
        name = first[1:].rstrip("}")
        required = True
    elif first.startswith("-"):
        return None
    else:
        name = first
        required = markers.get("required") != "false"
    positional = ParsedPositional(
        name=name,
        description=" ".join(tokens[1:]).strip(),
        required=required and markers.get("required") != "false",
        type=_infer_type(None, markers),
    )
    return positional


def _parse_subcommand_line(line: str) -> ParsedSubcommand | None:
    """Parse a subcommand entry such as ``reduce   Reduce a nodeset``."""
    markers, text = parse_markers(line)
    tokens = text.split()
    if not tokens:
        return None
    name = tokens[0].strip()
    if name.startswith("-") or name.startswith("<"):
        return None
    return ParsedSubcommand(name=name, description=" ".join(tokens[1:]).strip() or markers.get("aliases", ""))


def _parse_usage(line: str, result: ParsedHelp) -> None:
    """Extract required options and positional order from a usage line."""
    tokens = line.split()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        long_match = _LONG_FLAG_PATTERN.match(token)
        if long_match:
            result.required_options.add(long_match.group(1))
            index += 1
            if index < len(tokens) and (_PLACEHOLDER_PATTERN.match(tokens[index]) or tokens[index].isupper()):
                index += 1
            continue
        if _usage_optional_flag_token(token, result) or _usage_positional_token(token, result):
            index += 1
            continue
        index += 1


def _usage_optional_flag_token(token: str, result: ParsedHelp) -> bool:
    """Handle an ``[--flag]`` or ``[-h]`` token, which marks the option as optional."""
    if not token.startswith("[") or not token.endswith("]"):
        return False
    inner = token[1:-1].strip()
    if not inner:
        return True
    head = inner.split()[0]
    long_match = _LONG_FLAG_PATTERN.match(head)
    if long_match:
        result.required_options.discard(long_match.group(1))
        return True
    return head.startswith("-")


def _usage_positional_token(token: str, result: ParsedHelp) -> bool:
    """Handle a ``<name>`` or ``[name]`` token describing a positional argument."""
    placeholder = _PLACEHOLDER_PATTERN.match(token)
    if placeholder:
        name = placeholder.group(1)
        if (
            "," not in name
            and not name.startswith("{")
            and not _known_positional(result, name)
            and not _is_generic_usage_name(name)
        ):
            result.positionals.append(ParsedPositional(name=name, required=True))
        return True
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        bracketed = _PLACEHOLDER_PATTERN.match(inner)
        name = bracketed.group(1) if bracketed else inner
        if (
            name
            and not name.isupper()
            and not _known_positional(result, name)
            and not _is_generic_usage_name(name)
        ):
            result.positionals.append(ParsedPositional(name=name.split()[0], required=False))
        return True
    return False


#: Usage placeholders that stand for "any option/argument", not a real positional.
_GENERIC_USAGE_NAMES = frozenset({"options", "option", "args", "arg", "arguments", "argument", "command", "commands"})


def _is_generic_usage_name(name: str) -> bool:
    """Whether a usage placeholder is boilerplate rather than a positional argument."""
    return name.lower() in _GENERIC_USAGE_NAMES


def _known_positional(result: ParsedHelp, name: str) -> bool:
    """Return whether a positional argument is already recorded."""
    return any(positional.name == name for positional in result.positionals)


@dataclass
class _ParseState:
    """Mutable bookkeeping for the line-by-line help scan."""

    section: SectionName = "body"
    base_indent: int | None = None
    current_option: ParsedOption | None = None
    option_indent: int | None = None
    body_lines: list[str] = field(default_factory=list)


def _is_usage_continuation(stripped: str, indent: int) -> bool:
    """Whether a body line only lists usage tokens, i.e. a wrapped ``usage:`` line."""
    tokens = stripped.split()
    if not tokens:
        return False
    if all(token.startswith("[") for token in tokens):
        return True
    # An indented flag/placeholder pair is an option entry, not wrapped usage text.
    return indent < 2 and all(token.startswith(("-", "[", "<")) for token in tokens)


#: Column-aligned command list, as ``git --help`` groups its commands without a header.
_COMMAND_LIST_PATTERN = re.compile(r"^([a-z][a-z0-9_-]{1,60})\s{2,}\S")


def _handle_body(state: _ParseState, stripped: str, indent: int, result: ParsedHelp) -> None:
    """Collect description lines, consume ``usage:`` lines and pick up command lists."""
    if stripped.lower().startswith("usage:"):
        result.usage = stripped.partition(":")[2].strip()
        _parse_usage(result.usage, result)
        return
    if _is_usage_continuation(stripped, indent):
        _parse_usage(stripped, result)
        return
    if indent >= 2 and _COMMAND_LIST_PATTERN.match(stripped):
        _record_subcommand(stripped, result)
        return
    if indent >= 2 and stripped.startswith("-"):
        option, _ = _parse_option_line(stripped)
        if option is not None:
            result.options.append(option)
            state.current_option = option
            state.option_indent = indent
            return
    if state.current_option is not None and state.option_indent is not None and indent > state.option_indent:
        _append_option_continuation(state.current_option, stripped)
        return
    state.body_lines.append(stripped)


def _append_option_continuation(option: ParsedOption, text: str) -> None:
    """Add a continuation line, and its markers, to the option being described."""
    markers, cleaned = parse_markers(text)
    if cleaned:
        option.description = f"{option.description} {cleaned}".strip()
    if option.default is None and markers.get("default"):
        option.default = markers["default"]
    if option.type == "string" and markers.get("type"):
        option.type = markers["type"]
    if markers.get("required"):
        option.required = True


def _handle_options(state: _ParseState, stripped: str, indent: int, result: ParsedHelp) -> None:
    """Parse an option entry, or append continuation text to the previous one."""
    option, description = _parse_option_line(stripped)
    if option is not None:
        result.options.append(option)
        state.current_option = option
        return
    if state.current_option is not None and (state.base_indent is None or indent > state.base_indent):
        state.current_option.description = f"{state.current_option.description} {description}".strip()


def _handle_positional(state: _ParseState, stripped: str, indent: int, result: ParsedHelp) -> None:
    """Parse positional entries, treating deeper indented lines as subcommands."""
    if state.base_indent is None:
        state.base_indent = indent
    if indent > state.base_indent:
        _record_subcommand(stripped, result)
        return
    positional = _parse_positional_line(stripped)
    if positional is not None:
        result.positionals.append(positional)


def _handle_commands(state: _ParseState, stripped: str, indent: int, result: ParsedHelp) -> None:
    """Parse entries of a ``commands:`` section."""
    if state.base_indent is None:
        state.base_indent = indent
    _record_subcommand(stripped, result)


def _record_subcommand(stripped: str, result: ParsedHelp) -> None:
    """Append a parsed subcommand when the line describes one."""
    subcommand = _parse_subcommand_line(stripped)
    if subcommand is not None:
        result.subcommands.append(subcommand)


SECTION_HANDLERS = {
    "body": _handle_body,
    "options": _handle_options,
    "positional": _handle_positional,
    "commands": _handle_commands,
}


def _apply_header(raw: str, stripped: str, state: _ParseState, result: ParsedHelp) -> bool:
    """Switch to the section a header line announces; return whether the line was consumed."""
    header_match = HEADER_PATTERN.match(raw)
    if not header_match:
        return False
    header = header_match.group(1).lower()
    section = SECTION_HEADERS.get(header)
    if section is None and not _is_section_title(header):
        return False  # prose that happens to end with a colon, e.g. git's group introductions
    state.section = section or "other"
    state.base_indent = None
    state.current_option = None
    if state.section == "body":
        result.usage = stripped.partition(":")[2].strip()
        _parse_usage(result.usage, result)
    return True


def _is_section_title(header: str) -> bool:
    """Whether an unrecognised colon-terminated line reads like a section title."""
    words = header.split()
    return len(words) <= 4 and "(" not in header and "," not in header


def parse_help(text: str) -> ParsedHelp:
    """Parse a single help page into description, options, positionals, subcommands."""
    result = ParsedHelp()
    state = _ParseState()

    for raw in text.splitlines():
        if not raw.strip():
            state.current_option = None
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()

        if _apply_header(raw, stripped, state, result):
            continue

        handler = SECTION_HANDLERS.get(state.section)
        if handler is None:
            state.current_option = None
            continue
        handler(state, stripped, indent, result)

    result.description = " ".join(state.body_lines).strip()
    for option in result.options:
        if option.name in result.required_options:
            option.required = True
    return result


def is_help_noise(description: str) -> bool:
    """Return whether a description is boilerplate help text rather than real documentation."""
    lowered = description.lower()
    return lowered.startswith(("show this message", "show help", "help for", "print usage", "usage:"))
