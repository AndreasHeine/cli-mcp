#!/usr/bin/env python3
"""Sample Click CLI with a command group, for discovery through Click reflection."""

from __future__ import annotations

import click


@click.group()
@click.option("--verbose", is_flag=True, help="Show progress messages while working.")
def cli(verbose: bool) -> None:
    """Manage a small collection of build artifacts."""
    if verbose:
        click.echo("verbose mode on")


@cli.command()
@click.argument("name")
@click.option("--tag", default="latest", help="Artifact tag to publish.")
@click.option("--retries", default=3, help="How many publish attempts to make.")
def publish(name: str, tag: str, retries: int) -> None:
    """Publish an artifact under a tag."""
    click.echo(f"publishing {name} as {tag} with {retries} attempts")


@cli.command()
@click.argument("name")
@click.option("--all", "remove_all", is_flag=True, help="Remove every tag of the artifact.")
def remove(name: str, remove_all: bool) -> None:
    """Delete an artifact, optionally every tag of it."""
    click.echo(f"removing {name}{' (all tags)' if remove_all else ''}")


@cli.command()
def status() -> None:
    """List artifacts and their tags."""
    click.echo("no artifacts")


if __name__ == "__main__":
    cli()
