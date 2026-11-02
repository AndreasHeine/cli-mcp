"""Native reflection helper executed inside the target CLI's interpreter.

Run as::

    python -m cli_mcp.discovery.introspect --target /path/to/cli.py

It imports the target module (which executes module-level code, so cli-mcp keeps
this behind ``discovery.allow_import_reflection``) and prints a JSON document
describing the commands declared by click, typer or argparse. Everything is
printed to stdout; failures are reported as JSON so the parent process can fall
back to help parsing.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
from types import ModuleType
from typing import Any


def _json_default(value: Any) -> str:
    return str(value)


def _load_module(target: str) -> ModuleType:
    """Import a script file or an importable module name."""
    if target.endswith(".py") or target.endswith(".pyw"):
        spec = importlib.util.spec_from_file_location("cli_mcp_target", target)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {target}")
        module = importlib.util.module_from_spec(spec)
        module.__name__ = "cli_mcp_target"
        spec.loader.exec_module(module)
        return module
    return importlib.import_module(target)


def _click_type(param: Any) -> tuple[str, list[str] | None]:
    """Map a click Param type onto a JSON Schema type plus choices."""
    type_obj = getattr(param, "type", None)
    choices = getattr(type_obj, "choices", None)
    name = getattr(type_obj, "name", None) or str(type_obj)
    lowered = str(name).lower()
    if "int" in lowered:
        return "integer", list(choices) if choices else None
    if "float" in lowered:
        return "number", list(choices) if choices else None
    if "bool" in lowered:
        return "boolean", list(choices) if choices else None
    return "string", list(choices) if choices else None


def _walk_click(command: Any, path: list[str], out: list[dict[str, Any]]) -> None:
    """Collect a click command and its children."""
    entry: dict[str, Any] = {
        "path": list(path),
        "description": command.help or command.short_help or "",
        "parameters": [],
        "has_subcommands": bool(getattr(command, "commands", None)),
    }
    for param in getattr(command, "params", []):
        opts = list(getattr(param, "opts", []) or [])
        secondary = list(getattr(param, "secondary_opts", []) or [])
        long_opts = [opt for opt in opts if opt.startswith("--")]
        short_opts = [opt for opt in opts if opt.startswith("-") and not opt.startswith("--")] + secondary
        has_flag_opt = any(opt.startswith("-") for opt in opts)
        type_name, choices = _click_type(param)
        default = getattr(param, "default", None)
        if callable(default):
            default = None
        entry["parameters"].append(
            {
                "name": getattr(param, "name", None) or (long_opts[0].lstrip("-") if long_opts else "arg"),
                "kind": "flag" if has_flag_opt and getattr(param, "is_flag", False) else (
                    "option" if has_flag_opt else "positional"
                ),
                "cli_name": long_opts[0].lstrip("-") if long_opts else None,
                "short": short_opts[0].lstrip("-") if short_opts else None,
                "type": type_name,
                "description": getattr(param, "help", None) or "",
                "required": bool(getattr(param, "required", False)),
                "default": default,
                "choices": choices,
                "repeatable": bool(getattr(param, "multiple", False)),
                "metavar": getattr(param, "metavar", None),
            }
        )
    out.append(entry)
    for name, child in sorted((getattr(command, "commands", {}) or {}).items()):
        _walk_click(child, [*path, name], out)


def _argparse_type(action: Any) -> str:
    """Map an argparse action's type callable onto a JSON Schema type."""
    type_callable = action.type
    if type_callable is None:
        return "string"
    if type_callable is int:
        return "integer"
    if type_callable is float:
        return "number"
    if type_callable is bool:
        return "boolean"
    if type_callable is str:
        return "string"
    return "string"


def _walk_argparse(parser: Any, path: list[str], out: list[dict[str, Any]]) -> None:
    """Collect an argparse parser and its subparsers."""
    entry: dict[str, Any] = {
        "path": list(path),
        "description": getattr(parser, "description", None) or getattr(parser, "help", "") or "",
        "parameters": [],
        "has_subcommands": False,
        "usage": getattr(parser, "usage", None),
    }
    actions = list(getattr(parser, "_actions", []))
    subparsers_action = None
    for action in actions:
        if getattr(action, "dest", None) == "help":
            continue
        if isinstance(action, argparse._SubParsersAction):
            subparsers_action = action
            continue
        option_strings = list(getattr(action, "option_strings", []))
        long_opts = [opt for opt in option_strings if opt.startswith("--")]
        short_opts = [opt for opt in option_strings if opt.startswith("-") and not opt.startswith("--")]
        nargs = getattr(action, "nargs", None)
        entry["parameters"].append(
            {
                "name": getattr(action, "dest", None) or "arg",
                "kind": "positional" if not option_strings else ("flag" if nargs == 0 else "option"),
                "cli_name": long_opts[0].lstrip("-") if long_opts else None,
                "short": short_opts[0].lstrip("-") if short_opts else None,
                "type": _argparse_type(action),
                "description": getattr(action, "help", None) or "",
                "required": bool(getattr(action, "required", False)),
                "default": getattr(action, "default", None),
                "choices": list(action.choices) if getattr(action, "choices", None) else None,
                "repeatable": False,
                "metavar": getattr(action, "metavar", None),
            }
        )
    if subparsers_action is not None:
        entry["has_subcommands"] = True
        for name, sub in sorted((getattr(subparsers_action, "choices", {}) or {}).items()):
            if isinstance(sub, argparse.ArgumentParser):
                _walk_argparse(sub, [*path, name], out)
    out.append(entry)


def _typer_command(app: Any) -> Any | None:
    """Resolve a typer app to its underlying click command."""
    try:
        import typer
    except ImportError:
        return None
    try:
        return typer.main.get_command(app)
    except Exception:
        return None


def _click_classes() -> tuple[type, ...]:
    """Click command classes, or an empty tuple when click is not installed."""
    try:
        import click
    except ImportError:
        return ()
    return (click.Group, click.Command)


def _descendant_ids(command: Any) -> set[int]:
    """Identity of every click command nested inside *command*."""
    ids = set()
    for child in (getattr(command, "commands", {}) or {}).values():
        ids.add(id(child))
        ids.update(_descendant_ids(child))
    return ids


def _click_roots(values: list[Any], click_classes: tuple[type, ...]) -> list[Any]:
    """Top-level click objects: every group, plus commands no group already contains."""
    if not click_classes:
        return []
    group_class, command_class = click_classes
    groups = [value for value in values if isinstance(value, group_class)]
    covered = {id(group) for group in groups}
    for group in groups:
        covered.update(_descendant_ids(group))
    roots = list(groups)
    for value in values:
        if isinstance(value, command_class) and not isinstance(value, group_class) and id(value) not in covered:
            roots.append(value)
    return roots


def _scan_namespace(values: list[Any], click_classes: tuple[type, ...]) -> tuple[list[Any], list[Any], list[Any]]:
    """Split a module namespace into click objects, typer apps and argparse parsers."""
    typer_apps: list[Any] = []
    parsers: list[Any] = []
    for value in values:
        if isinstance(value, argparse.ArgumentParser):
            parsers.append(value)
        elif type(value).__name__ == "Typer":
            typer_apps.append(value)
    return _click_roots(values, click_classes), typer_apps, parsers


def _parser_factory(module: ModuleType) -> Any | None:
    """An argparse parser built by a module-level ``build_parser``-style factory."""
    for attr in ("build_parser", "create_parser", "get_parser"):
        factory = getattr(module, attr, None)
        if not callable(factory) or isinstance(factory, argparse.ArgumentParser):
            continue
        try:
            built = factory()
        except (TypeError, SystemExit, OSError):
            continue
        if isinstance(built, argparse.ArgumentParser):
            return built
    return None


def discover(target: str) -> dict[str, Any]:
    """Import *target* and describe the commands it declares."""
    module = _load_module(target)
    namespace = vars(module)
    values = [value for value in namespace.values() if not inspect.ismodule(value)]
    click_objects, typer_apps, parsers = _scan_namespace(values, _click_classes())
    if not parsers and not click_objects and not typer_apps:
        built = _parser_factory(module)
        if built is not None:
            parsers.append(built)

    commands: list[dict[str, Any]] = []
    framework: str | None = None

    for app in typer_apps:
        command = _typer_command(app)
        if command is not None:
            framework = "typer"
            _walk_click(command, [], commands)
    for obj in click_objects:
        if framework != "typer":
            framework = "click"
        _walk_click(obj, [], commands)
    for parser in parsers:
        if framework is None:
            framework = "argparse"
        _walk_argparse(parser, [], commands)

    return {"framework": framework, "commands": commands}


def main(argv: list[str] | None = None) -> int:
    """Entry point: emit the discovery document as JSON."""
    parser = argparse.ArgumentParser(prog="cli-mcp-introspect")
    parser.add_argument("--target", required=True, help="Script path or importable module name")
    args = parser.parse_args(argv)
    try:
        payload = discover(args.target)
    except BaseException as exc:
        print(json.dumps({"framework": None, "commands": [], "error": str(exc)}))
        return 0
    print(json.dumps(payload, default=_json_default))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
