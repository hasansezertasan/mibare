"""Tests for the subprocess mise adapter, with the process runner replaced."""

from __future__ import annotations

import json
import subprocess  # noqa: S404
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mibare.core.errors import MiseError, MiseNotFoundError, MiseTooOldError
from mibare.core.mise import (
    MIN_MISE_VERSION,
    RegistryEntry,
    SubprocessMise,
    run_process,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REGISTRY_JSON = json.dumps([
    {
        "short": "ripgrep",
        "backends": ["aqua:BurntSushi/ripgrep", "ubi:BurntSushi/ripgrep"],
    },
    {"short": "fd", "backends": ["aqua:sharkdp/fd"], "bins": ["fd"]},
])


class FakeRunner:
    """Records each ``mise`` invocation and answers from canned output."""

    def __init__(
        self,
        *,
        version: str = "2026.10.13 macos-arm64 (2026-10-17)",
        registry: str = REGISTRY_JSON,
        returncode: int = 0,
        stderr: str = "",
        error: Exception | None = None,
    ) -> None:
        """Set the canned answers, or an error to raise instead."""
        self.calls: list[tuple[tuple[str, ...], dict[str, str], Path]] = []
        self.homes_existed: list[bool] = []
        self._version = version
        self._registry = registry
        self._returncode = returncode
        self._stderr = stderr
        self._error = error

    def __call__(
        self, args: Sequence[str], env: Mapping[str, str], cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        """Record the call and answer it.

        Returns:
            subprocess.CompletedProcess[str]: The canned process.
        """
        self.calls.append((tuple(args), dict(env), cwd))
        self.homes_existed.append(Path(env["HOME"]).is_dir())
        if self._error is not None:
            raise self._error
        stdout = self._version if "--version" in args else self._registry
        return subprocess.CompletedProcess(
            list(args), self._returncode, stdout, self._stderr
        )


def test_run_process_runs_with_exactly_the_given_environment(tmp_path: Path) -> None:
    """The default runner hands the process only the environment it is given.

    Given:
        - A user environment containing a variable the caller did not pass on.
    When:
        - A command is run with a different, explicit environment.
    Then:
        - The command sees the explicit variable, not the user's, and runs in
          the requested directory.
    """
    script = "import os; print(os.environ.get('MIBARE_A'), os.environ.get('PATH'))"

    done = run_process([sys.executable, "-c", script], {"MIBARE_A": "1"}, tmp_path)

    assert done.stdout.split() == ["1", "None"]


def test_run_process_reports_a_missing_executable() -> None:
    """An executable that is not on ``PATH`` raises ``FileNotFoundError``."""
    with pytest.raises(FileNotFoundError):
        _ = run_process(["mibare-no-such-program"], {}, Path.cwd())


def test_registry_lists_entries_in_registry_order() -> None:
    """The registry is parsed from ``mise registry --json`` output.

    Given:
        - Mise answering with two registry entries.
    When:
        - The registry is requested.
    Then:
        - Both entries come back with their backend strings, in order.
    """
    adapter = SubprocessMise(run=FakeRunner())

    assert adapter.registry() == (
        RegistryEntry("ripgrep", ("aqua:BurntSushi/ripgrep", "ubi:BurntSushi/ripgrep")),
        RegistryEntry("fd", ("aqua:sharkdp/fd",)),
    )


def test_version_is_the_number_mise_reports() -> None:
    """The recorded version is the bare version number.

    Given:
        - Mise reporting its version with a platform and build date.
    When:
        - The version is requested.
    Then:
        - Only the version number is returned.
    """
    assert SubprocessMise(run=FakeRunner()).version() == "2026.10.13"


def test_mise_runs_in_an_isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """User settings never reach mise; only a token is passed through.

    Given:
        - A user environment with ``MISE_DISABLE_BACKENDS``, a config path, a
          home directory and a ``GITHUB_TOKEN``.
    When:
        - The registry is requested.
    Then:
        - Mise ran with no config, a temporary home, the token and nothing else
          from the user's environment.
    """
    monkeypatch.setenv("MISE_DISABLE_BACKENDS", "aqua")
    monkeypatch.setenv("MISE_CONFIG_FILE", "/home/user/mise.toml")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    runner = FakeRunner()

    _ = SubprocessMise(run=runner).registry()

    assert runner.calls[-1][0] == ("mise", "registry", "--json")
    assert all(runner.homes_existed)
    for _, env, cwd in runner.calls:
        assert env == {
            "HOME": env["HOME"],
            "MISE_NO_CONFIG": "1",
            "GITHUB_TOKEN": "secret",
        }
        assert env["HOME"] != str(Path.home())
        assert cwd == Path(env["HOME"])
        assert not Path(env["HOME"]).exists()


def test_no_token_is_passed_when_the_user_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset ``GITHUB_TOKEN`` is not invented.

    Given:
        - A user environment without ``GITHUB_TOKEN``.
    When:
        - The registry is requested.
    Then:
        - Mise's environment has no ``GITHUB_TOKEN``.
    """
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    runner = FakeRunner()

    _ = SubprocessMise(run=runner).registry()

    assert "GITHUB_TOKEN" not in runner.calls[0][1]


def test_missing_mise_is_reported_with_an_install_hint() -> None:
    """A missing binary is an error that says how to install mise.

    Given:
        - No ``mise`` binary on the system.
    When:
        - The version is requested.
    Then:
        - The error says mise was not found and points at the install guide.
    """
    adapter = SubprocessMise(run=FakeRunner(error=FileNotFoundError("mise")))

    with pytest.raises(MiseNotFoundError, match=r"mise\.jdx\.dev"):
        _ = adapter.version()


def test_too_old_mise_is_reported_with_the_minimum_version() -> None:
    """A mise below the minimum is an error naming the minimum version.

    Given:
        - A mise older than the minimum supported version.
    When:
        - The version is requested.
    Then:
        - The error names the version found and the minimum required.
    """
    adapter = SubprocessMise(
        run=FakeRunner(version="2026.10.12 linux-x64 (2026-10-16)")
    )

    with pytest.raises(MiseTooOldError, match=r"2026\.10\.12.*2026\.10\.13"):
        _ = adapter.version()


def test_minimum_version_is_accepted() -> None:
    """The minimum version itself is supported."""
    assert MIN_MISE_VERSION == (2026, 10, 13)
    assert (
        SubprocessMise(run=FakeRunner(version="2026.10.13")).version() == "2026.10.13"
    )
    assert SubprocessMise(run=FakeRunner(version="2027.1.0 x")).version() == "2027.1.0"


def test_too_old_mise_stops_before_reading_the_registry() -> None:
    """An old mise's registry is never trusted.

    Given:
        - A mise older than the minimum.
    When:
        - The registry is requested.
    Then:
        - The too-old error is raised and the registry command never ran.
    """
    runner = FakeRunner(version="2025.1.0")

    with pytest.raises(MiseTooOldError):
        _ = SubprocessMise(run=runner).registry()

    assert all("registry" not in args for args, _, _ in runner.calls)


@pytest.mark.parametrize(
    "runner",
    [
        FakeRunner(version="not a version"),
        FakeRunner(returncode=1, stderr="boom"),
        FakeRunner(registry="not json"),
        FakeRunner(registry='{"short": "x"}'),
        FakeRunner(registry='[{"short": "x"}]'),
        FakeRunner(error=subprocess.TimeoutExpired("mise", 60)),
        FakeRunner(error=PermissionError("denied")),
    ],
    ids=[
        "bad-version",
        "nonzero-exit",
        "bad-json",
        "not-a-list",
        "no-backends",
        "timeout",
        "not-executable",
    ],
)
def test_unusable_mise_output_is_a_mise_error(runner: FakeRunner) -> None:
    """Anything unexpected from mise is reported as a mise error.

    Given:
        - Mise failing, timing out or answering with output mibare can't read.
    When:
        - The registry is requested.
    Then:
        - A ``MiseError`` is raised rather than a raw exception.
    """
    with pytest.raises(MiseError):
        _ = SubprocessMise(run=runner).registry()


class ProbeRunner(FakeRunner):
    """Answers ``mise ls-remote`` with a canned exit code and stderr."""

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        """Set the probe's exit code and stderr."""
        super().__init__()
        self._probe = (returncode, stderr)

    def __call__(
        self, args: Sequence[str], env: Mapping[str, str], cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        """Answer a probe from the canned result, anything else as usual.

        Returns:
            subprocess.CompletedProcess[str]: The canned process.
        """
        done = super().__call__(args, env, cwd)
        if "ls-remote" not in args:
            return done
        return subprocess.CompletedProcess(
            list(args), self._probe[0], "", self._probe[1]
        )


ABSENT_AQUA = (
    "mise ERROR unable to fetch versions for aqua:o/r: registry not available: "
    "no aqua-registry found for o/r"
)
ABSENT_GITHUB = (
    "mise ERROR GitHub repository o/r not found (404 from mise-versions.jdx.dev, "
    "which mise asks before api.github.com)."
)


@pytest.mark.parametrize(
    ("backend_string", "stderr"),
    [("aqua:o/r", ABSENT_AQUA), ("github:o/r", ABSENT_GITHUB)],
)
def test_a_recipe_mise_reports_as_not_found_is_absent(
    backend_string: str, stderr: str
) -> None:
    """Read mise's not-found errors as an absent recipe, not a failure."""
    mise = SubprocessMise(run=ProbeRunner(1, stderr))

    assert not mise.recipe_exists(backend_string)


def test_a_recipe_that_lists_versions_exists() -> None:
    """Read exit code 0 as an existing recipe."""
    assert SubprocessMise(run=ProbeRunner()).recipe_exists("aqua:o/r")


@pytest.mark.parametrize(
    "stderr",
    [
        "mise ERROR tunnel error: failed to create underlying connection",
        "mise ERROR HTTP 403 rate limit exceeded",
        "",
    ],
)
def test_any_other_probe_failure_is_a_mise_error_not_an_absent_recipe(
    stderr: str,
) -> None:
    """Report a network or rate-limit failure instead of calling it absent."""
    mise = SubprocessMise(run=ProbeRunner(1, stderr))

    with pytest.raises(MiseError):
        _ = mise.recipe_exists("aqua:o/r")
