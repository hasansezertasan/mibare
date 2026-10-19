"""Tests for resolving a repository to mise backends, through ``resolve()``."""

from __future__ import annotations

import pytest

from mibare.core.errors import (
    InvalidRepositoryError,
    MiseError,
    MiseNotFoundError,
    MiseTooOldError,
)
from mibare.core.resolve import resolve
from tests.fakes import FakeMise, entry

RIPGREP = entry("ripgrep", "aqua:BurntSushi/ripgrep", "ubi:BurntSushi/ripgrep")


def test_registry_backends_are_candidates_in_registry_order() -> None:
    """A repository listed in the registry resolves to its backend strings.

    Given:
        - A registry listing ripgrep with an aqua and a ubi backend.
    When:
        - ``BurntSushi/ripgrep`` is resolved.
    Then:
        - The candidates are the registry's backends in registry order, and the
          first is the recommendation.
    """
    resolution = resolve("BurntSushi/ripgrep", FakeMise([RIPGREP]))

    assert [c.backend_string for c in resolution.candidates] == [
        "aqua:BurntSushi/ripgrep",
        "ubi:BurntSushi/ripgrep",
    ]
    assert resolution.recommendation is resolution.candidates[0]


@pytest.mark.parametrize(
    "text",
    [
        "BurntSushi/ripgrep",
        "burntsushi/RIPGREP",
        "https://github.com/BurntSushi/ripgrep",
        "http://github.com/BurntSushi/ripgrep",
        "github.com/BurntSushi/ripgrep",
        "https://www.github.com/BurntSushi/ripgrep",
        "https://github.com/BurntSushi/ripgrep/",
        "https://github.com/BurntSushi/ripgrep.git",
        "https://github.com/BurntSushi/ripgrep.git/",
        "  BurntSushi/ripgrep/ ",
        "BurntSushi/ripgrep.git",
        "https://github.com/BurntSushi/ripgrep/tree/master/crates",
    ],
)
def test_url_variants_resolve_to_the_same_repository(text: str) -> None:
    """A URL, the shorthand and the tolerated variants name one repository.

    Given:
        - A registry listing ripgrep.
    When:
        - The repository is given in any tolerated form.
    Then:
        - The resolution names ``BurntSushi/ripgrep`` and finds its backends.
    """
    resolution = resolve(text, FakeMise([RIPGREP]))

    assert resolution.repository.shorthand.lower() == "burntsushi/ripgrep"
    assert resolution.recommendation is not None


@pytest.mark.parametrize(
    "text",
    [
        "https://gitlab.com/gitlab-org/cli",
        "https://example.com/BurntSushi/ripgrep",
        "https://github.com/BurntSushi",
        "ripgrep",
        "",
        "a/b/c",
        "owner/",
        "https://notgithub.com/BurntSushi/ripgrep",
    ],
)
def test_input_that_is_not_a_github_repository_is_rejected(text: str) -> None:
    """Input that does not name a GitHub repository is an error.

    Given:
        - Text that is not a GitHub URL or ``owner/repo`` shorthand.
    When:
        - It is resolved.
    Then:
        - An invalid-repository error is raised, before mise is consulted.
    """
    with pytest.raises(InvalidRepositoryError):
        resolve(text, FakeMise(error=AssertionError("mise must not be consulted")))


def test_resolution_records_the_mise_version() -> None:
    """The mise version the answer came from is part of the resolution."""
    resolution = resolve("sharkdp/fd", FakeMise(version="2027.1.0"))

    assert resolution.mise_version == "2027.1.0"


@pytest.mark.parametrize("error", [MiseNotFoundError("gone"), MiseTooOldError("old")])
def test_an_unusable_mise_stops_the_resolution(error: MiseError) -> None:
    """A missing or too-old mise is an error, not an empty answer.

    Given:
        - A mise adapter that reports it is missing or too old.
    When:
        - A repository is resolved.
    Then:
        - The adapter's error reaches the caller.
    """
    with pytest.raises(type(error)):
        resolve("sharkdp/fd", FakeMise(error=error))


def test_repository_not_in_the_registry_has_no_candidates() -> None:
    """A repository the registry does not list resolves to nothing.

    Given:
        - A registry that lists only ripgrep.
    When:
        - A different repository is resolved.
    Then:
        - There are no candidates and no recommendation.
    """
    resolution = resolve("sharkdp/fd", FakeMise([RIPGREP]))

    assert resolution.candidates == ()
    assert resolution.recommendation is None


@pytest.mark.parametrize(
    "backend",
    [
        "aqua:BurntSushi/ripgrep",
        "github:BurntSushi/ripgrep",
        "ubi:BurntSushi/ripgrep",
        "asdf:BurntSushi/ripgrep",
        "vfox:BurntSushi/ripgrep",
        "go:github.com/BurntSushi/ripgrep/cmd/rg",
        "packslip:github.com/BurntSushi/ripgrep",
        "github:BurntSushi/ripgrep[exe=rg]",
    ],
)
def test_registry_entries_pointing_at_the_repository_are_found(backend: str) -> None:
    """Any registry backend that points at the repository identifies its entry.

    Given:
        - A registry entry whose backend points at ``BurntSushi/ripgrep``.
    When:
        - ``BurntSushi/ripgrep`` is resolved.
    Then:
        - The entry's backends are the candidates.
    """
    resolution = resolve("BurntSushi/ripgrep", FakeMise([entry("rg", backend)]))

    assert [c.backend_string for c in resolution.candidates] == [backend]


@pytest.mark.parametrize(
    "backend",
    [
        "aqua:BurntSushi/ripgrep-all",
        "aqua:notBurntSushi/ripgrep",
        "pypi:ripgrep",
        "npm:@BurntSushi/ripgrep",
        "cargo:ripgrep",
        "core:ripgrep",
    ],
)
def test_registry_entries_for_other_repositories_are_ignored(backend: str) -> None:
    """A backend that merely resembles the repository does not match it.

    Given:
        - A registry entry whose backend is not the repository.
    When:
        - ``BurntSushi/ripgrep`` is resolved.
    Then:
        - There are no candidates.
    """
    resolution = resolve("BurntSushi/ripgrep", FakeMise([entry("rg", backend)]))

    assert resolution.candidates == ()
