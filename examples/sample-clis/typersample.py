#!/usr/bin/env python3
"""Sample Typer CLI, for discovery through Typer reflection."""

from __future__ import annotations

from enum import Enum

import typer

app = typer.Typer(help="Inspect and convert image metadata.")


class Format(str, Enum):
    json = "json"
    yaml = "yaml"


@app.command()
def inspect(path: str, verbose: bool = typer.Option(False, "--verbose", help="Show every metadata field.")) -> None:
    """Print the metadata found in an image file."""
    typer.echo(f"inspecting {path} (verbose={verbose})")


@app.command()
def convert(
    path: str,
    output: str = typer.Option("stdout", help="Where to write the converted metadata."),
    fmt: Format = typer.Option(Format.json, "--format", help="Output format."),
    quality: int = typer.Option(90, min=1, max=100, help="Compression quality."),
) -> None:
    """Convert image metadata to another format."""
    typer.echo(f"converting {path} to {fmt.value} at quality {quality} -> {output}")


@app.command()
def purge(target: str, force: bool = typer.Option(False, "--force", help="Skip the confirmation prompt.")) -> None:
    """Delete cached metadata for a target."""
    typer.echo(f"purging {target} (force={force})")


if __name__ == "__main__":
    app()
