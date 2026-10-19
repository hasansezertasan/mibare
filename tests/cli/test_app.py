"""Test cases for the ``mibare <repo>`` command: parsing and exit codes."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mibare.core.errors import (
    InvalidRepositoryError,
    MibareError,
    MiseNotFoundError,
    MiseTooOldError,
)
from mibare.core.repository import Repository
from mibare.core.resolve import Candidate, Resolution

if TYPE_CHECKING:
    from collections.abc import Callable

    from typer.testing import Result

REPOSITORY = Repository("BurntSushi", "ripgrep")

# ``mibare.cli`` re-exports the Typer ``app``, which shadows the module of the
# same name as an attribute, so the module is fetched explicitly.
cli = importlib.import_module("mibare.cli.app")


@pytest.fixture
def runner() -> CliRunner:
    """Fixture that provides a CLI runner for testing Typer commands."""
    return CliRunner()


def _resolving(*backends: str) -> Callable[..., Resolution]:
    """Build a stand-in for ``resolve()`` that finds ``backends``."""

    def fake(repository: str, mise: object) -> Resolution:
        del repository, mise
        return Resolution(
            REPOSITORY, "2026.10.13", tuple(Candidate(b) for b in backends)
        )

    return fake


def _failing(error: MibareError) -> Callable[..., Resolution]:
    """Build a stand-in for ``resolve()`` that raises ``error``."""

    def fake(repository: str, mise: object) -> Resolution:
        del repository, mise
        raise error

    return fake


def test_help_exits_cleanly(runner: CliRunner) -> None:
    """``--help`` renders the usage and exits 0.

    Given:
        - The mibare Typer root.
    When:
        - ``--help`` is requested.
    Then:
        - The command exits 0.
    """
    result: Result = runner.invoke(cli.app, ["--help"])

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
    result: Result = runner.invoke(cli.app, ["--help"])

    assert "mise backend" in result.output
    assert "GitHub repository" in result.output


def test_the_repository_argument_reaches_resolve(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The text after ``mibare`` is passed through unparsed.

    Given:
        - A ``resolve()`` that records what it is asked.
    When:
        - ``mibare https://github.com/BurntSushi/ripgrep.git`` runs.
    Then:
        - ``resolve()`` receives that exact text.
    """
    asked: list[str] = []

    def spy(repository: str, mise: object) -> Resolution:
        del mise
        asked.append(repository)
        return Resolution(REPOSITORY, "2026.10.13", ())

    monkeypatch.setattr(cli, "resolve", spy)

    _ = runner.invoke(cli.app, ["https://github.com/BurntSushi/ripgrep.git"])

    assert asked == ["https://github.com/BurntSushi/ripgrep.git"]


def test_a_recommendation_exits_0_and_marks_the_first_backend(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Candidates print in order with the first marked as the recommendation.

    Given:
        - A resolution with two candidates.
    When:
        - ``mibare BurntSushi/ripgrep`` runs.
    Then:
        - It exits 0 and lists both backends, the first marked recommended.
    """
    monkeypatch.setattr(
        cli, "resolve", _resolving("aqua:BurntSushi/ripgrep", "ubi:BurntSushi/ripgrep")
    )

    result: Result = runner.invoke(cli.app, ["BurntSushi/ripgrep"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert "2026.10.13" in result.output
    first = next(line for line in lines if "aqua:BurntSushi/ripgrep" in line)
    second = next(line for line in lines if "ubi:BurntSushi/ripgrep" in line)
    assert "recommended" in first
    assert "recommended" not in second
    assert lines.index(first) < lines.index(second)


def test_no_backend_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """A repository with no backend exits 1 with a message.

    Given:
        - A resolution with no candidates.
    When:
        - ``mibare sharkdp/fd`` runs.
    Then:
        - It exits 1 and says no backend was found.
    """
    monkeypatch.setattr(cli, "resolve", _resolving())

    result: Result = runner.invoke(cli.app, ["sharkdp/fd"])

    assert result.exit_code == 1
    assert "no backend found" in result.output.lower()


@pytest.mark.parametrize(
    "error",
    [
        InvalidRepositoryError("Not a GitHub repository: 'x'."),
        MiseNotFoundError(
            "mise was not found on PATH. Install it: https://mise.jdx.dev"
        ),
        MiseTooOldError("mise 2025.1.0 is too old; mibare needs mise 2026.10.13."),
    ],
)
def test_errors_exit_2_with_their_message(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, error: MibareError
) -> None:
    """Invalid input and an unusable mise exit 2 and explain why.

    Given:
        - A ``resolve()`` that raises a user-facing error.
    When:
        - ``mibare`` runs.
    Then:
        - It exits 2 and prints the error's message, without a traceback.
    """
    monkeypatch.setattr(cli, "resolve", _failing(error))

    result: Result = runner.invoke(cli.app, ["x"])

    assert result.exit_code == 2
    assert str(error) in result.output
    assert "Traceback" not in result.output


def test_a_non_github_url_exits_2(runner: CliRunner) -> None:
    """The real parsing rejects a non-GitHub URL before mise is needed.

    Given:
        - A GitLab URL.
    When:
        - ``mibare`` runs with the real ``resolve()``.
    Then:
        - It exits 2 saying the input is not a GitHub repository.
    """
    result: Result = runner.invoke(cli.app, ["https://gitlab.com/gitlab-org/cli"])

    assert result.exit_code == 2
    assert "GitHub" in result.output


@pytest.mark.parametrize("command", ["version", "info"])
def test_there_are_no_subcommands(runner: CliRunner, command: str) -> None:
    """The scaffold's ``version`` and ``info`` subcommands are gone.

    Given:
        - The single-command CLI.
    When:
        - ``mibare version`` or ``mibare info`` runs.
    Then:
        - The word is read as a repository, which it is not, so it exits 2.
    """
    result: Result = runner.invoke(cli.app, [command])

    assert result.exit_code == 2
