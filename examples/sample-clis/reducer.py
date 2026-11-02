#!/usr/bin/env python3
"""Sample argparse CLI: an OPC UA nodeset reducer, used to exercise discovery.

Run it directly, or expose it with::

    cli-mcp expose examples/sample-clis/reducer.py
"""

from __future__ import annotations

import argparse
import json
import sys


def reduce_command(args: argparse.Namespace) -> int:
    """Read an XML nodeset and write a reduced copy."""
    with open(args.input, encoding="utf-8") as handle:
        text = handle.read()
    kept = [line for line in text.splitlines() if not line.strip().startswith("<Alias")]
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write("\n".join(kept) + "\n")
    print(json.dumps({"input": args.input, "output": args.output, "lines": len(kept)}))
    return 0


def diff_command(args: argparse.Namespace) -> int:
    """Report how many lines differ between two nodesets."""
    left = _read(args.left)
    right = _read(args.right)
    added = len(right) - len(left)
    print(json.dumps({"left": args.left, "right": args.right, "delta": added}))
    return 0 if added == 0 else 1


def analyze_command(args: argparse.Namespace) -> int:
    """Count node entries and report a summary."""
    lines = _read(args.input)
    nodes = [line for line in lines if "UaNode" in line]
    print(json.dumps({"input": args.input, "nodes": len(nodes), "format": args.format}))
    if args.verbose:
        print("verbose summary enabled")
    return 0


def _read(path: str) -> list[str]:
    with open(path, encoding="utf-8") as handle:
        return handle.read().splitlines()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reducer", description="Reduce and compare OPC UA nodeset files.")
    sub = parser.add_subparsers(dest="command", required=True)

    reduce_parser = sub.add_parser("reduce", help="Write a reduced copy of a nodeset file")
    reduce_parser.add_argument("--input", required=True, help="Source nodeset XML file")
    reduce_parser.add_argument("--output", required=True, help="Destination file for the reduced nodeset")
    reduce_parser.add_argument(
        "--format",
        choices=["xml", "json"],
        default="xml",
        help="Output format for the reduced nodeset",
    )
    reduce_parser.add_argument("--strip-aliases", action="store_true", help="Drop alias entries from the output")
    reduce_parser.set_defaults(func=reduce_command)

    diff_parser = sub.add_parser("diff", help="Compare two nodeset files")
    diff_parser.add_argument("left", help="First nodeset file")
    diff_parser.add_argument("right", help="Second nodeset file")
    diff_parser.add_argument("--quiet", action="store_true", help="Print only the line delta")
    diff_parser.set_defaults(func=diff_command)

    analyze_parser = sub.add_parser("analyze", help="Summarise a nodeset file")
    analyze_parser.add_argument("--input", required=True, help="Nodeset file to summarise")
    analyze_parser.add_argument("--format", choices=["text", "json"], default="json", help="Summary format")
    analyze_parser.add_argument("--verbose", action="store_true", help="Include the verbose summary line")
    analyze_parser.set_defaults(func=analyze_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
