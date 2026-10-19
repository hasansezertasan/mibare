"""CLI application for the project.

``mibare <repo>`` is the whole interface: one command, no subcommands. It is a
thin wrapper over :func:`mibare.core.resolve.resolve` that parses the
argument, prints the resolution and maps the outcome onto an exit code.
"""
# mypy: disable-error-code="misc"

from __future__ import annotations

from typing import Annotated

import typer

from mibare.core.errors import MibareError
from mibare.core.mise import SubprocessMise
from mibare.core.resolve import Resolution, resolve

__all__ = ["app", "main"]

EXIT_FOUND = 0
EXIT_NO_BACKEND = 1
EXIT_ERROR = 2

app = typer.Typer(
    name="mibare",
    help="Recommend which mise backend to install a GitHub repository with.",
    no_args_is_help=True,
)


def _subject(resolution: Resolution) -> str:
    """Name the repository and the mise registry the answer came from.

    Args:
        resolution: The resolution being described.

    Returns:
        str: For example ``owner/repo (mise 2026.10.13 registry)``.
    """
    mise = f"mise {resolution.mise_version}"
    return f"{resolution.repository.shorthand} ({mise} registry)"


def _render(resolution: Resolution) -> str:
    """Format a resolution for the terminal.

    Args:
        resolution: The resolution to show.

    Returns:
        str: The text to print; the recommendation is marked.
    """
    lines = [_subject(resolution)]
    for index, candidate in enumerate(resolution.candidates):
        marker = "*" if index == 0 else " "
        suffix = "  (recommended)" if index == 0 else ""
        lines.append(f"{marker} {candidate.backend_string}{suffix}")
    return "\n".join(lines)


@app.command()
def main(
    repository: Annotated[
        str, typer.Argument(help="A GitHub URL or owner/repo shorthand.")
    ],
) -> None:
    """Recommend which mise backend to install a GitHub repository with.

    Exits 0 when a backend is found, 1 when none is, and 2 on an error such as
    input that is not a GitHub repository or a missing or too-old mise.

    Example:
        mibare BurntSushi/ripgrep
        mibare https://github.com/BurntSushi/ripgrep

    Raises:
        typer.Exit: Always, with the exit code describing the outcome.
    """
    try:
        resolution = resolve(repository, SubprocessMise())
    except MibareError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=EXIT_ERROR) from None
    if resolution.recommendation is None:
        typer.echo(f"No backend found for {_subject(resolution)}.")
        raise typer.Exit(code=EXIT_NO_BACKEND)
    typer.echo(_render(resolution))
