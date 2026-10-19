"""Tests for the language-package step of ``resolve()``: Python and tie-breaks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mibare.core.ecosystems import ECOSYSTEMS, PYPI, Detection, Ecosystem
from mibare.core.errors import GitHubUnavailableError
from mibare.core.platform import Platform
from mibare.core.resolve import Resolution, resolve
from tests.fakes import FakeGitHub, FakeMise

if TYPE_CHECKING:
    from mibare.core.github import GitHub
    from mibare.core.repository import Repository

LINUX_X64 = Platform("linux", "x64")
TOOL = "owner/tool"
PYPROJECT_WITH_SCRIPTS = (
    '[project]\nname = "tool"\n\n[project.scripts]\ntool = "tool.cli:main"\n'
)
PYPROJECT_LIBRARY = '[project]\nname = "tool"\n'


def _backends(resolution: Resolution) -> list[str]:
    """List the backend strings of ``resolution`` in ranked order."""
    return [c.backend_string for c in resolution.candidates]


def test_pyproject_scripts_give_a_pypi_candidate() -> None:
    """A root pyproject declaring scripts resolves to ``pypi:owner/repo``.

    Given:
        - A repository whose root pyproject.toml has ``[project.scripts]``.
    When:
        - It is resolved.
    Then:
        - ``pypi:owner/tool`` is the recommendation at tier 4, with a reason.
    """
    github = FakeGitHub(files={"pyproject.toml": PYPROJECT_WITH_SCRIPTS})

    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=github)

    top = resolution.recommendation
    assert top is not None
    assert (top.backend_string, top.tier) == ("pypi:owner/tool", 4)
    assert any("project.scripts" in reason for reason in top.reasons)


def test_pyproject_without_scripts_gives_no_pypi_candidate() -> None:
    """A library-only pyproject is excluded, with the reason recorded."""
    github = FakeGitHub(files={"pyproject.toml": PYPROJECT_LIBRARY})

    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=github, ecosystems=(PYPI,))

    assert resolution.candidates == ()
    (excluded,) = resolution.exclusions
    assert excluded.backend_string == "pypi:owner/tool"
    assert "project.scripts" in excluded.reason
    assert resolution.to_dict()["excluded"] == [
        {"backend_string": "pypi:owner/tool", "reason": excluded.reason}
    ]


def test_empty_scripts_table_gives_no_pypi_candidate() -> None:
    """``[project.scripts]`` with no entries declares no entrypoint."""
    text = PYPROJECT_LIBRARY + "\n[project.scripts]\n"
    github = FakeGitHub(files={"pyproject.toml": text})

    assert resolve(TOOL, FakeMise(), LINUX_X64, github=github).candidates == ()


def test_no_root_manifest_gives_no_language_package_candidate() -> None:
    """Without a root manifest there is nothing to install from."""
    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=FakeGitHub())

    assert resolution.candidates == ()
    assert any("pyproject.toml" in x.reason for x in resolution.exclusions)


def test_malformed_pyproject_is_no_candidate_with_a_visible_reason() -> None:
    """Broken TOML does not crash; it is an exclusion that says so."""
    github = FakeGitHub(files={"pyproject.toml": "[project\nscripts = ="})

    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=github, ecosystems=(PYPI,))

    assert resolution.candidates == ()
    (excluded,) = resolution.exclusions
    assert excluded.backend_string == "pypi:owner/tool"
    assert "valid TOML" in excluded.reason


def test_language_package_ranks_below_aqua() -> None:
    """The language-package tier comes after aqua."""
    mise = FakeMise(recipes=["aqua:owner/tool"])
    github = FakeGitHub(files={"pyproject.toml": PYPROJECT_WITH_SCRIPTS})

    resolution = resolve(TOOL, mise, LINUX_X64, github=github)

    assert _backends(resolution) == ["aqua:owner/tool", "pypi:owner/tool"]


def test_without_a_github_adapter_the_step_is_left_out() -> None:
    """``resolve()`` stays offline when no GitHub adapter is passed."""
    resolution = resolve(TOOL, FakeMise(), LINUX_X64)

    assert resolution.candidates == ()
    assert resolution.exclusions == ()


def test_step_failure_keeps_earlier_results_and_names_the_skipped_step() -> None:
    """A GitHub failure in the language-package step is a skipped-step note."""
    mise = FakeMise(recipes=["aqua:owner/tool"])
    github = FakeGitHub(error=GitHubUnavailableError("could not reach GitHub"))

    resolution = resolve(TOOL, mise, LINUX_X64, github=github)

    assert _backends(resolution) == ["aqua:owner/tool"]
    assert any(
        "language-package" in note and "skipped" in note.lower()
        for note in resolution.notes
    )


def test_step_failure_without_results_raises() -> None:
    """With nothing found and GitHub down, resolution raises."""
    github = FakeGitHub(error=GitHubUnavailableError("could not reach GitHub"))

    with pytest.raises(GitHubUnavailableError):
        _ = resolve(TOOL, FakeMise(), LINUX_X64, github=github)


def _fake_ecosystem(prefix: str, language: str) -> Ecosystem:
    """Build an ecosystem that always finds ``prefix:owner/repo``.

    Returns:
        Ecosystem: The fake ecosystem.
    """

    def detect(repository: Repository, github: GitHub) -> Detection:
        del github
        backend = f"{prefix}:{repository.shorthand}"
        return Detection(backend, f"fake {prefix} entrypoint")

    return Ecosystem(prefix, frozenset({language}), detect)


FAKES = (_fake_ecosystem("npm", "JavaScript"), _fake_ecosystem("cargo", "Rust"), PYPI)
ALPHABETICAL = ["cargo:owner/tool", "npm:owner/tool", "pypi:owner/tool"]


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("Rust", ALPHABETICAL),
        ("JavaScript", ["npm:owner/tool", "cargo:owner/tool", "pypi:owner/tool"]),
        ("Python", ["pypi:owner/tool", "cargo:owner/tool", "npm:owner/tool"]),
        ("python", ["pypi:owner/tool", "cargo:owner/tool", "npm:owner/tool"]),
        (None, ALPHABETICAL),
        ("Go", ALPHABETICAL),
    ],
)
def test_primary_language_backend_leads_then_alphabetical(
    language: str | None, expected: list[str]
) -> None:
    """The primary language's backend goes first; other ties are alphabetical.

    Given:
        - Three ecosystems that all find an entrypoint.
    When:
        - The repository's primary language varies.
    Then:
        - Its backend leads and the rest follow alphabetically by backend.
    """
    github = FakeGitHub(
        language=language, files={"pyproject.toml": PYPROJECT_WITH_SCRIPTS}
    )

    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=github, ecosystems=FAKES)

    assert _backends(resolution) == expected


def test_tie_break_does_not_depend_on_registration_order() -> None:
    """Reversing the registry gives the same ranking."""
    github = FakeGitHub(
        language="Rust", files={"pyproject.toml": PYPROJECT_WITH_SCRIPTS}
    )

    resolution = resolve(
        TOOL, FakeMise(), LINUX_X64, github=github, ecosystems=FAKES[::-1]
    )

    assert _backends(resolution) == ALPHABETICAL


def test_pypi_is_registered_by_default() -> None:
    """The default registry includes the Python ecosystem."""
    assert PYPI in ECOSYSTEMS
