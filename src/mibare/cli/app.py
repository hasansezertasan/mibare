"""CLI application for the project.

The ``mibare`` command is the single Typer root. Every enabled
component other than the primary (CLI > GUI > TUI > web > MCP > worker) is hung
off it as a lazily-imported subcommand — ``mibare interactive``
(TUI), ``mibare web``, ``mibare mcp``, ... — rather
than a separate ``mibare-<name>`` console script (see https://hasansezertasan.github.io/copier-pyproject/context/components/#secondary-components-are-subcommands-of-one-console-root-not-separate-scripts).
"""
# mypy: disable-error-code="misc"

from __future__ import annotations

import typer

from mibare.__metadata__ import PROJECT_NAME
from mibare.core import app as service
from mibare.core.logging_setup import get_logger

__all__ = ["app", "info", "show_version"]

logger = get_logger()

app = typer.Typer(
    name="mibare",
    help="Recommend which mise backend to install a GitHub repository with.",
    no_args_is_help=True,
)


@app.command(name="version")
def show_version() -> None:
    """Show the current version number of mibare.

    Show the version number:
        mibare version

    Example output:
        0.1.0

    Raises:
        typer.Exit: If the package metadata cannot be found.
    """
    try:
        resolved = service.version()
    except service.MetadataUnavailableError:
        # An uninstalled or partial package is an expected, user-facing error, so
        # log without the traceback that logging.exception would add.
        logger.error("Package metadata not found for %s", PROJECT_NAME)  # noqa: TRY400
        typer.echo(
            f"Error: Package '{PROJECT_NAME}' metadata not found. Is the package installed correctly?",  # noqa: E501
            err=True,
        )
        raise typer.Exit(code=1) from None
    logger.info("Command `version` called.")
    typer.echo(resolved)
    logger.info("Version displayed successfully.")


@app.command()
def info() -> None:
    """Display information about the mibare application.

    Show application information:
        mibare info

    Example output:
        Application Version: 0.1.0
        Python Version: 3.12.0 (CPython)
        Platform: Darwin

    Raises:
        typer.Exit: If the package metadata cannot be found.
    """
    try:
        payload = service.info()
    except service.MetadataUnavailableError:
        # An uninstalled or partial package is an expected, user-facing error, so
        # log without the traceback that logging.exception would add.
        logger.error("Package metadata not found for %s", PROJECT_NAME)  # noqa: TRY400
        typer.echo(
            f"Error: Package '{PROJECT_NAME}' metadata not found. Is the package installed correctly?",  # noqa: E501
            err=True,
        )
        raise typer.Exit(code=1) from None
    logger.info("Command `info` called.")
    python = f"{payload['python_version']} ({payload['python_implementation']})"
    typer.echo(f"Application Version: {payload['application_version']}")
    typer.echo(f"Python Version: {python}")
    typer.echo(f"Platform: {payload['platform']}")
    logger.info("Application information displayed successfully.")
