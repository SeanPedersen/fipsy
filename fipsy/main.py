"""Fipsy CLI — IPFS content sharing and discovery."""

import click

from fipsy.commands import add, index, pin, publish, scan


@click.group()
def cli() -> None:
    """Share and discover content on your local IPFS network."""


cli.add_command(scan)
cli.add_command(index)
cli.add_command(add)
cli.add_command(publish)
cli.add_command(pin)
