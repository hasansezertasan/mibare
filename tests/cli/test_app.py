"""Test cases for the ``mibare <repo>`` command: parsing and exit codes."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mibare.core.errors import (
    GitHubUnavailableError,
    InvalidPlatformError,
    InvalidRepositoryError,
    MibareError,
    MiseNotFoundError,
    MiseTooOldError,
)
from mibare.core.github import GitHubApi
from mibare.core.mise import RegistryEntry, SubprocessMise
from mibare.core.platform import Platform
from mibare.core.repository import Repository
from mibare.core.resolve import Candidate, Resolution
from tests.fakes import FakeGitHub, FakeMise

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

    def fake(
        repository: str,
        mise: object,
        platform: Platform | None = None,
        github: object = None,
    ) -> Resolution:
        del repository, mise, platform, github
        return Resolution(
            REPOSITORY, "2026.10.13", tuple(Candidate(b) for b in backends)
        )

    return fake


def _failing(error: Exception) -> Callable[..., Resolution]:
    """Build a stand-in for ``resolve()`` that raises ``error``."""

    def fake(
        repository: str,
        mise: object,
        platform: Platform | None = None,
        github: object = None,
    ) -> Resolution:
        del repository, mise, platform, github
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

    def spy(
        repository: str,
        mise: object,
        platform: Platform | None = None,
        github: object = None,
    ) -> Resolution:
        del mise, platform, github
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


def test_platform_reaches_resolve_as_a_platform(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--platform os-arch`` is parsed and handed to ``resolve()``.

    Given:
        - A ``resolve()`` that records the platform it is asked for.
    When:
        - ``mibare --platform windows-x64`` runs.
    Then:
        - ``resolve()`` receives ``Platform("windows", "x64")``.
    """
    asked: list[Platform | None] = []

    def spy(
        repository: str,
        mise: object,
        platform: Platform | None = None,
        github: object = None,
    ) -> Resolution:
        del repository, mise, github
        asked.append(platform)
        return Resolution(REPOSITORY, "2026.10.13", ())

    monkeypatch.setattr(cli, "resolve", spy)

    _ = runner.invoke(cli.app, ["--platform", "windows-x64", "BurntSushi/ripgrep"])

    assert asked == [Platform("windows", "x64")]


def test_without_platform_resolve_uses_the_host_default(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``--platform`` leaves the choice to ``resolve()``'s host default."""
    asked: list[Platform | None] = []

    def spy(
        repository: str,
        mise: object,
        platform: Platform | None = None,
        github: object = None,
    ) -> Resolution:
        del repository, mise, github
        asked.append(platform)
        return Resolution(REPOSITORY, "2026.10.13", ())

    monkeypatch.setattr(cli, "resolve", spy)

    _ = runner.invoke(cli.app, ["BurntSushi/ripgrep"])

    assert asked == [None]


@pytest.mark.parametrize("value", ["windows", "plan9-x64", "linux-mips", ""])
def test_an_invalid_platform_exits_2_with_a_clear_message(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """A bad ``--platform`` is an error before anything resolves.

    Given:
        - A ``resolve()`` that must not be called.
    When:
        - ``mibare --platform <value>`` runs.
    Then:
        - It exits 2 and explains the expected ``os-arch`` form.
    """
    monkeypatch.setattr(cli, "resolve", _failing(AssertionError("must not run")))

    result: Result = runner.invoke(cli.app, ["--platform", value, "BurntSushi/ripgrep"])

    assert result.exit_code == 2
    assert "os-arch" in result.output
    assert "Traceback" not in result.output


def test_warnings_and_notes_are_shown(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy warnings and platform notes reach the terminal.

    Given:
        - A resolution with a legacy candidate and a platform note.
    When:
        - ``mibare`` runs.
    Then:
        - Both texts appear in the output.
    """

    def fake(
        repository: str,
        mise: object,
        platform: Platform | None = None,
        github: object = None,
    ) -> Resolution:
        del repository, mise, platform, github
        candidate = Candidate(
            "ubi:BurntSushi/ripgrep", tier=5, legacy=True, warning="ubi is legacy."
        )
        return Resolution(
            REPOSITORY, "2026.10.13", (candidate,), notes=("Target differs.",)
        )

    monkeypatch.setattr(cli, "resolve", fake)

    result: Result = runner.invoke(cli.app, ["BurntSushi/ripgrep"])

    assert "ubi is legacy." in result.output
    assert "Target differs." in result.output


def test_the_cli_builds_the_real_adapters(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``resolve()`` receives a real mise adapter and a real GitHub adapter.

    Given:
        - A ``resolve()`` that records the adapters it is given.
    When:
        - ``mibare`` runs.
    Then:
        - The adapters are a ``SubprocessMise`` and a ``GitHubApi``.
    """
    seen: list[object] = []

    def spy(
        repository: str,
        mise: object,
        platform: Platform | None = None,
        github: object = None,
    ) -> Resolution:
        del repository, platform
        seen.extend([mise, github])
        return Resolution(REPOSITORY, "2026.10.13", ())

    monkeypatch.setattr(cli, "resolve", spy)

    _ = runner.invoke(cli.app, ["BurntSushi/ripgrep"])

    assert [type(adapter) for adapter in seen] == [SubprocessMise, GitHubApi]


def test_an_unusable_network_with_no_results_exits_2(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GitHub failure that leaves no results is an error, not 'no backend'."""
    error = GitHubUnavailableError("could not reach GitHub")
    monkeypatch.setattr(cli, "resolve", _failing(error))

    result: Result = runner.invoke(cli.app, ["BurntSushi/ripgrep"])

    assert result.exit_code == 2
    assert "could not reach GitHub" in result.output


def test_an_unexpected_exception_exits_2_not_1(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash is not 'no backend found': it exits 2 with a short message.

    Given:
        - A ``resolve()`` that raises an exception mibare does not expect.
    When:
        - ``mibare`` runs, without and with ``--verbose``.
    Then:
        - Both exit 2 with no traceback; only ``--verbose`` shows the detail.
    """
    monkeypatch.setattr(cli, "resolve", _failing(RuntimeError("boom 42")))

    quiet: Result = runner.invoke(cli.app, ["BurntSushi/ripgrep"])
    verbose: Result = runner.invoke(cli.app, ["--verbose", "BurntSushi/ripgrep"])

    assert quiet.exit_code == 2
    assert "unexpected error" in quiet.output.lower()
    assert "boom 42" not in quiet.output
    assert verbose.exit_code == 2
    assert "RuntimeError" in verbose.output
    assert "boom 42" in verbose.output
    assert "Traceback" not in quiet.output + verbose.output


def _unsupported_host() -> Platform:
    """Fail like ``host_platform()`` does on an unsupported host.

    Raises:
        InvalidPlatformError: Always.
    """
    message = "Unsupported host platform Plan9-mips; pass --platform os-arch."
    raise InvalidPlatformError(message)


def test_platform_flag_works_on_an_unsupported_host(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--platform`` is the documented way out of an unsupported host.

    Given:
        - A host that is not a supported platform and fake adapters.
    When:
        - ``mibare --platform linux-x64`` runs, and then without the flag.
    Then:
        - With the flag it recommends a backend; without it, it exits 2.
    """
    registry = [RegistryEntry("rg", ("aqua:BurntSushi/ripgrep",))]
    monkeypatch.setattr("mibare.core.resolve.host_platform", _unsupported_host)
    monkeypatch.setattr(cli, "SubprocessMise", lambda: FakeMise(registry))
    monkeypatch.setattr(cli, "GitHubApi", FakeGitHub)

    flagged: Result = runner.invoke(
        cli.app, ["--platform", "linux-x64", "BurntSushi/ripgrep"]
    )
    bare: Result = runner.invoke(cli.app, ["BurntSushi/ripgrep"])

    assert flagged.exit_code == 0, flagged.output
    assert "aqua:BurntSushi/ripgrep" in flagged.output
    assert bare.exit_code == 2
    assert "pass --platform" in bare.output
