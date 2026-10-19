"""Test cases for the mibare Typer root."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mibare.cli.app import app

if TYPE_CHECKING:
    from typer.testing import Result


@pytest.fixture
def runner() -> CliRunner:
    """Fixture that provides a CLI runner for testing Typer commands."""
    return CliRunner()


def test_help_exits_cleanly(runner: CliRunner) -> None:
    """``--help`` renders the root usage and exits 0.

    Given:
        - The mibare Typer root.
    When:
        - ``--help`` is requested.
    Then:
        - The command exits 0.
    """
    result: Result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output


def test_help_describes_the_tool(runner: CliRunner) -> None:
    """``--help`` tells the user what mibare does.

    Given:
        - The mibare Typer root.
    When:
        - ``--help`` is requested.
    Then:
        - The output says it recommends a mise backend for a GitHub repository.
    """
    result: Result = runner.invoke(app, ["--help"])

    assert "mise backend" in result.output
    assert "GitHub repository" in result.output


def test_version(runner: CliRunner) -> None:
    """The `version` command runs successfully and prints the version.

    Given:
        - The application is set up with a `version` command.
    When:
        - The `version` command is invoked using the CLI runner.
    Then:
        - The command exits 0 and the output contains the version.
    """
    result: Result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.output


def test_info(runner: CliRunner) -> None:
    """The `info` command runs successfully and prints application information.

    Given:
        - The application is set up with an `info` command.
    When:
        - The `info` command is invoked using the CLI runner.
    Then:
        - The command exits 0 and the output contains the application info.
    """
    result: Result = runner.invoke(app, ["info"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("command", ["version", "info"])
@pytest.mark.usefixtures("missing_metadata")
def test_command_fails_loudly_when_metadata_missing(
    runner: CliRunner, command: str
) -> None:
    """Commands exit non-zero with an error when package metadata is missing.

    Given:
        - Package metadata cannot be resolved (broken/partial install).
    When:
        - The `version` or `info` command is invoked.
    Then:
        - The command exits with code 1 (the documented ``typer.Exit`` contract)
          instead of dumping a traceback or silently printing nothing.
    """
    result: Result = runner.invoke(app, [command])

    assert result.exit_code == 1
