"""Test cases for the CLI output: reasons, commands, ``--json`` and ``--verbose``."""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mibare.core.errors import MiseNotFoundError
from mibare.core.repository import Repository
from mibare.core.resolve import Candidate, Exclusion, Resolution

if TYPE_CHECKING:
    from collections.abc import Callable

    from typer.testing import Result

# ``mibare.cli`` re-exports the Typer ``app``, which shadows the module.
cli = importlib.import_module("mibare.cli.app")

REPOSITORY = Repository("BurntSushi", "ripgrep")
REASON = "listed in the mise registry as 'rg'"
CANDIDATES = (
    Candidate("aqua:BurntSushi/ripgrep", (REASON,)),
    Candidate("ubi:BurntSushi/ripgrep", (REASON,)),
)
EXCLUSIONS = (Exclusion("asdf:BurntSushi/ripgrep", "asdf cannot run on Windows"),)


@pytest.fixture
def runner() -> CliRunner:
    """Fixture that provides a CLI runner for testing Typer commands."""
    return CliRunner()


def _resolution(
    candidates: tuple[Candidate, ...] = CANDIDATES,
    exclusions: tuple[Exclusion, ...] = (),
) -> Callable[..., Resolution]:
    """Build a stand-in for ``resolve()`` returning a fixed resolution."""

    def fake(repository: str, mise: object) -> Resolution:
        del repository, mise
        return Resolution(REPOSITORY, "2026.10.13", candidates, exclusions)

    return fake


def test_each_candidate_shows_its_reasons_and_mise_use_command(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default output has a reason and a command for every candidate.

    Given:
        - A resolution with two candidates that have reasons.
    When:
        - ``mibare BurntSushi/ripgrep`` runs.
    Then:
        - Each candidate's reason and ``mise use`` command are printed.
    """
    monkeypatch.setattr(cli, "resolve", _resolution())

    result: Result = runner.invoke(cli.app, ["BurntSushi/ripgrep"])

    assert result.exit_code == 0, result.output
    assert result.output.count(REASON) == 2
    assert "mise use aqua:BurntSushi/ripgrep" in result.output
    assert "mise use ubi:BurntSushi/ripgrep" in result.output
    assert "Excluded" not in result.output


def test_verbose_lists_excluded_candidates_with_reasons(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--verbose`` explains what was left out and why.

    Given:
        - A resolution with an exclusion.
    When:
        - ``mibare --verbose BurntSushi/ripgrep`` runs.
    Then:
        - The excluded backend string appears with its reason.
    """
    monkeypatch.setattr(cli, "resolve", _resolution(exclusions=EXCLUSIONS))

    result: Result = runner.invoke(cli.app, ["--verbose", "BurntSushi/ripgrep"])

    assert result.exit_code == 0, result.output
    assert "Excluded" in result.output
    assert "asdf:BurntSushi/ripgrep" in result.output
    assert "asdf cannot run on Windows" in result.output


def test_verbose_without_exclusions_says_so(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--verbose`` states that nothing was excluded."""
    monkeypatch.setattr(cli, "resolve", _resolution())

    result: Result = runner.invoke(cli.app, ["--verbose", "BurntSushi/ripgrep"])

    assert "Excluded: none" in result.output


def test_json_output_has_the_documented_shape(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--json`` prints only the JSON form of the resolution.

    Given:
        - A resolution with candidates and an exclusion.
    When:
        - ``mibare --json BurntSushi/ripgrep`` runs.
    Then:
        - Standard output is the JSON document, with the mise version.
    """
    monkeypatch.setattr(cli, "resolve", _resolution(exclusions=EXCLUSIONS))

    result: Result = runner.invoke(cli.app, ["--json", "BurntSushi/ripgrep"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["mise_version"] == "2026.10.13"
    assert data["recommendation"] == "aqua:BurntSushi/ripgrep"
    assert data["candidates"][0]["command"] == "mise use aqua:BurntSushi/ripgrep"
    assert data["candidates"][0]["reasons"] == [REASON]
    assert data["excluded"] == [
        {
            "backend_string": "asdf:BurntSushi/ripgrep",
            "reason": "asdf cannot run on Windows",
        }
    ]


def test_json_and_text_agree_on_the_recommendation(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both formats recommend the same backend string.

    Given:
        - A resolution with two candidates.
    When:
        - It is printed as text and as JSON.
    Then:
        - The line marked recommended in the text is the JSON recommendation.
    """
    monkeypatch.setattr(cli, "resolve", _resolution())

    text = runner.invoke(cli.app, ["BurntSushi/ripgrep"]).output
    data = json.loads(runner.invoke(cli.app, ["--json", "BurntSushi/ripgrep"]).output)

    recommended = next(line for line in text.splitlines() if "(recommended)" in line)
    assert data["recommendation"] in recommended
    assert [c["backend_string"] for c in data["candidates"] if c["recommended"]] == [
        data["recommendation"]
    ]


def test_json_with_no_backend_exits_1_with_a_null_recommendation(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--json`` still prints a document when nothing is found.

    Given:
        - A resolution with no candidates.
    When:
        - ``mibare --json sharkdp/fd`` runs.
    Then:
        - It exits 1 and prints JSON whose recommendation is null.
    """
    monkeypatch.setattr(cli, "resolve", _resolution(()))

    result: Result = runner.invoke(cli.app, ["--json", "sharkdp/fd"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["recommendation"] is None
    assert data["candidates"] == []


def test_verbose_with_no_backend_still_lists_exclusions(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When everything was excluded, ``--verbose`` shows why."""
    monkeypatch.setattr(cli, "resolve", _resolution((), EXCLUSIONS))

    result: Result = runner.invoke(cli.app, ["--verbose", "sharkdp/fd"])

    assert result.exit_code == 1
    assert "asdf cannot run on Windows" in result.output


def test_json_errors_still_exit_2_with_their_message(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Errors are not JSON: they exit 2 with the usual message."""

    def failing(repository: str, mise: object) -> Resolution:
        del repository, mise
        message = "gone"
        raise MiseNotFoundError(message)

    monkeypatch.setattr(cli, "resolve", failing)

    result: Result = runner.invoke(cli.app, ["--json", "x"])

    assert result.exit_code == 2
    assert "gone" in result.output
