"""CLI application for the project.

``mibare <repo>`` is the whole interface: one command, no subcommands. It is a
thin wrapper over :func:`mibare.core.resolve.resolve` that parses the
argument, prints the resolution and maps the outcome onto an exit code.
"""
# mypy: disable-error-code="misc"

from __future__ import annotations

import json
from typing import Annotated

import typer

from mibare.core.errors import MibareError
from mibare.core.mise import SubprocessMise
from mibare.core.resolve import Resolution, resolve

__all__ = ["app", "main"]

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


def _render(resolution: Resolution, *, verbose: bool = False) -> str:
    """Format a resolution for the terminal.

    Args:
        resolution: The resolution to show.
        verbose: Whether to also list the excluded candidates.

    Returns:
        str: The text to print; the recommendation is marked.
    """
    if resolution.recommendation is None:
        lines = [f"No backend found for {_subject(resolution)}."]
    else:
        lines = [_subject(resolution)]
    for index, candidate in enumerate(resolution.candidates):
        marker = "*" if index == 0 else " "
        suffix = "  (recommended)" if index == 0 else ""
        lines.append(f"{marker} {candidate.backend_string}{suffix}")
        lines.extend(f"    - {reason}" for reason in candidate.reasons)
        lines.append(f"    $ {candidate.mise_use}")
    if verbose:
        if resolution.exclusions:
            lines.append("Excluded:")
            lines.extend(
                f"  {x.backend_string}: {x.reason}" for x in resolution.exclusions
            )
        else:
            lines.append("Excluded: none")
    return "\n".join(lines)


@app.command()
def main(
    repository: Annotated[
        str, typer.Argument(help="A GitHub URL or owner/repo shorthand.")
    ],
    *,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the resolution as JSON.")
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose", help="Also explain which candidates were excluded and why."
        ),
    ] = False,
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
    if json_output:
        typer.echo(json.dumps(resolution.to_dict(), indent=2))
    else:
        typer.echo(_render(resolution, verbose=verbose))
    if resolution.recommendation is None:
        raise typer.Exit(code=EXIT_NO_BACKEND)
