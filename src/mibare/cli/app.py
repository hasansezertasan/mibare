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
from mibare.core.github import GitHubApi
from mibare.core.mise import SubprocessMise
from mibare.core.platform import Platform
from mibare.core.resolve import Candidate, Resolution, resolve

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
        lines.extend(_candidate_lines(candidate, recommended=index == 0))
    lines.extend(f"note: {note}" for note in resolution.notes)
    if verbose:
        lines.extend(_exclusion_lines(resolution))
    return "\n".join(lines)


def _candidate_lines(candidate: Candidate, *, recommended: bool) -> list[str]:
    """Format one candidate: backend string, tier, reasons, warning, command.

    Returns:
        list[str]: The lines to print.
    """
    marker = "*" if recommended else " "
    suffix = "  (recommended)" if recommended else ""
    tier = f"  [tier {candidate.tier}]"
    lines = [f"{marker} {candidate.backend_string}{tier}{suffix}"]
    lines.extend(f"    - {reason}" for reason in candidate.reasons)
    if candidate.warning:
        lines.append(f"    warning: {candidate.warning}")
    lines.append(f"    $ {candidate.mise_use}")
    return lines


def _exclusion_lines(resolution: Resolution) -> list[str]:
    """Format the excluded candidates for ``--verbose``.

    Returns:
        list[str]: The lines to print.
    """
    if not resolution.exclusions:
        return ["Excluded: none"]
    return ["Excluded:"] + [
        f"  {x.backend_string}: {x.reason}" for x in resolution.exclusions
    ]


@app.command()
def main(
    repository: Annotated[
        str, typer.Argument(help="A GitHub URL or owner/repo shorthand.")
    ],
    *,
    platform: Annotated[
        str | None,
        typer.Option(
            help="Target platform as os-arch, such as linux-x64; defaults to the host."
        ),
    ] = None,
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
        target = Platform.parse(platform) if platform is not None else None
        resolution = resolve(repository, SubprocessMise(), target, github=GitHubApi())
    except MibareError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=EXIT_ERROR) from None
    if json_output:
        typer.echo(json.dumps(resolution.to_dict(), indent=2))
    else:
        typer.echo(_render(resolution, verbose=verbose))
    if resolution.recommendation is None:
        raise typer.Exit(code=EXIT_NO_BACKEND)
