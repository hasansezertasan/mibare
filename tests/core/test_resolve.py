"""Tests for resolving a repository to mise backends, through ``resolve()``."""

from __future__ import annotations

import json

import pytest

import mibare.core.resolve as resolve_module
from mibare.core.errors import (
    InvalidPlatformError,
    InvalidRepositoryError,
    MiseError,
    MiseNotFoundError,
    MiseTooOldError,
)
from mibare.core.platform import Platform
from mibare.core.resolve import Resolution, resolve
from tests.fakes import FakeMise, entry

HOST = Platform("macos", "arm64")
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


def _backends(resolution: Resolution) -> list[str]:
    """List the backend strings of ``resolution`` in ranked order."""
    return [c.backend_string for c in resolution.candidates]


def test_a_higher_tier_backend_outranks_a_legacy_one_listed_first() -> None:
    """Candidates follow mise's tier ladder, not the registry's order.

    Given:
        - A registry entry listing asdf, ubi, cargo, github and aqua in that order.
    When:
        - The repository is resolved.
    Then:
        - aqua and github lead, then the language package, then asdf and ubi.
    """
    registry = entry(
        "eza",
        "asdf:eza-community/eza",
        "ubi:eza-community/eza",
        "cargo:github.com/eza-community/eza",
        "github:eza-community/eza",
        "aqua:eza-community/eza",
    )

    resolution = resolve("eza-community/eza", FakeMise([registry]))

    assert _backends(resolution) == [
        "github:eza-community/eza",
        "aqua:eza-community/eza",
        "cargo:github.com/eza-community/eza",
        "asdf:eza-community/eza",
        "ubi:eza-community/eza",
    ]
    assert resolution.recommendation is resolution.candidates[0]


def test_candidates_carry_their_tier() -> None:
    """Each candidate reports its position on the ladder.

    Given:
        - Packslip, aqua, http, go and vfox backends for one repository.
    When:
        - The repository is resolved.
    Then:
        - The tiers are 1 to 5 in that order.
    """
    registry = entry(
        "tool",
        "vfox:o/r",
        "go:github.com/o/r",
        "http:o/r",
        "aqua:o/r",
        "packslip:github.com/o/r",
    )

    resolution = resolve("o/r", FakeMise([registry]))

    assert [c.tier for c in resolution.candidates] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("backend", ["asdf", "vfox", "ubi"])
def test_legacy_backends_are_flagged_with_a_warning(backend: str) -> None:
    """asdf, vfox and ubi candidates are marked legacy and say why.

    Given:
        - A registry entry with an aqua backend and a legacy backend.
    When:
        - The repository is resolved.
    Then:
        - Only the legacy candidate is flagged, and it carries a warning.
    """
    registry = entry("tool", "aqua:o/r", f"{backend}:o/r")

    modern, legacy = resolve("o/r", FakeMise([registry])).candidates

    assert (modern.legacy, modern.warning) == (False, None)
    assert legacy.legacy
    assert legacy.warning is not None
    assert backend in legacy.warning


def test_ranking_is_deterministic() -> None:
    """The same input always yields the same order.

    Given:
        - A registry entry with several backends in one tier.
    When:
        - The repository is resolved twice.
    Then:
        - The order is identical and keeps the registry's order within the tier.
    """
    registry = entry("t", "npm:github:o/r", "cargo:github.com/o/r", "aqua:o/r")

    first = _backends(resolve("o/r", FakeMise([registry])))
    second = _backends(resolve("o/r", FakeMise([registry])))

    assert first == second == ["aqua:o/r", "npm:github:o/r", "cargo:github.com/o/r"]


def test_asdf_is_excluded_for_a_windows_target() -> None:
    """The asdf backend cannot run on Windows, so it is never offered there.

    Given:
        - A registry entry with aqua, asdf and vfox backends.
    When:
        - The repository is resolved for ``windows-x64``.
    Then:
        - asdf is gone and the others remain.
    """
    registry = entry("tool", "aqua:o/r", "asdf:o/r", "vfox:o/r")

    resolution = resolve("o/r", FakeMise([registry]), Platform("windows", "x64"))

    assert _backends(resolution) == ["aqua:o/r", "vfox:o/r"]


def test_asdf_is_kept_for_a_non_windows_target() -> None:
    """The asdf backend stays a (legacy) candidate on Linux.

    Given:
        - A registry entry with aqua and asdf backends.
    When:
        - The repository is resolved for ``linux-arm64``.
    Then:
        - Both remain.
    """
    registry = entry("tool", "aqua:o/r", "asdf:o/r")

    resolution = resolve("o/r", FakeMise([registry]), Platform("linux", "arm64"))

    assert _backends(resolution) == ["aqua:o/r", "asdf:o/r"]


def test_the_target_defaults_to_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a platform the host is the target and no note is added.

    Given:
        - A host that is Windows.
    When:
        - A repository is resolved without a platform.
    Then:
        - The target is the host, asdf is excluded, and there are no notes.
    """
    windows = Platform("windows", "arm64")
    monkeypatch.setattr(resolve_module, "host_platform", lambda: windows)
    registry = entry("tool", "aqua:o/r", "asdf:o/r")

    resolution = resolve("o/r", FakeMise([registry]))

    assert resolution.platform == windows
    assert _backends(resolution) == ["aqua:o/r"]
    assert resolution.notes == ()


def test_a_target_that_differs_from_the_host_is_noted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The output says when registry data reflects another platform.

    Given:
        - A macOS host and a ``windows-x64`` target.
    When:
        - A repository is resolved.
    Then:
        - A note names both platforms and says the registry reflects the host.
    """
    monkeypatch.setattr(resolve_module, "host_platform", lambda: HOST)

    resolution = resolve("o/r", FakeMise(), Platform("windows", "x64"))

    (note,) = resolution.notes
    assert "windows-x64" in note
    assert "macos-arm64" in note
    assert "registry" in note


def test_a_target_equal_to_the_host_adds_no_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naming the host platform explicitly changes nothing.

    Given:
        - A target equal to the host.
    When:
        - A repository is resolved.
    Then:
        - There are no notes.
    """
    monkeypatch.setattr(resolve_module, "host_platform", lambda: HOST)

    assert resolve("o/r", FakeMise(), HOST).notes == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("linux-x64", Platform("linux", "x64")),
        ("macos-arm64", Platform("macos", "arm64")),
        ("WINDOWS-X64", Platform("windows", "x64")),
    ],
)
def test_platform_parses_os_arch(text: str, expected: Platform) -> None:
    """``os-arch`` text becomes a platform, ignoring case."""
    assert Platform.parse(text) == expected
    assert expected.label == text.lower()


@pytest.mark.parametrize(
    "text", ["", "linux", "linux-", "-x64", "plan9-x64", "linux-mips", "linux-x64-x"]
)
def test_platform_rejects_anything_but_a_known_os_arch(text: str) -> None:
    """An unknown OS, an unknown arch or the wrong shape is an error."""
    with pytest.raises(InvalidPlatformError, match="os-arch"):
        Platform.parse(text)


def test_registry_candidates_carry_reasons_and_a_mise_use_command() -> None:
    """Each candidate explains itself and gives a ready-to-paste command.

    Given:
        - A registry entry named ``rg`` listing two backends.
    When:
        - ``BurntSushi/ripgrep`` is resolved.
    Then:
        - Every candidate has a reason naming the registry entry and a
          ``mise use`` command for its backend string.
    """
    resolution = resolve("BurntSushi/ripgrep", FakeMise([RIPGREP]))

    assert [c.mise_use for c in resolution.candidates] == [
        "mise use aqua:BurntSushi/ripgrep",
        "mise use ubi:BurntSushi/ripgrep",
    ]
    assert all(
        any("registry" in reason and "ripgrep" in reason for reason in c.reasons)
        for c in resolution.candidates
    )


def test_mise_use_quotes_backend_strings_for_the_shell() -> None:
    """A backend string with options is quoted so it pastes safely.

    Given:
        - A registry backend with a bracketed option.
    When:
        - It is resolved.
    Then:
        - The command quotes the backend string.
    """
    backend = "github:BurntSushi/ripgrep[exe=rg]"
    resolution = resolve("BurntSushi/ripgrep", FakeMise([entry("rg", backend)]))

    assert resolution.candidates[0].mise_use == f"mise use '{backend}'"


def test_a_resolution_with_no_exclusions_reports_none() -> None:
    """The registry step excludes nothing, so the exclusion list is empty."""
    resolution = resolve("BurntSushi/ripgrep", FakeMise([RIPGREP]))

    assert resolution.exclusions == ()


def test_to_dict_has_a_stable_shape() -> None:
    """The dict form is the documented JSON shape.

    Given:
        - A resolved repository with two candidates.
    When:
        - It is converted to a dict.
    Then:
        - It has exactly the documented keys, including the mise version, and
          the recommendation is the first candidate.
    """
    resolution = resolve("BurntSushi/ripgrep", FakeMise([RIPGREP]))
    data = json.loads(json.dumps(resolution.to_dict()))

    assert list(data) == [
        "schema_version",
        "repository",
        "mise_version",
        "recommendation",
        "candidates",
        "excluded",
        "platform",
        "notes",
    ]
    assert data["schema_version"] == 1
    assert data["repository"] == "BurntSushi/ripgrep"
    assert data["mise_version"] == "2026.10.13"
    assert data["recommendation"] == "aqua:BurntSushi/ripgrep"
    candidates = data["candidates"]
    assert isinstance(candidates, list)
    assert list(candidates[0]) == [
        "backend_string",
        "recommended",
        "tier",
        "legacy",
        "warning",
        "command",
        "reasons",
    ]
    assert [c["recommended"] for c in candidates] == [True, False]
    assert candidates[1]["command"] == "mise use ubi:BurntSushi/ripgrep"
    assert [c["tier"] for c in candidates] == [2, 5]
    assert [c["legacy"] for c in candidates] == [False, True]
    assert candidates[0]["warning"] is None
    assert "ubi" in str(candidates[1]["warning"])
    assert data["excluded"] == []
    assert data["notes"] == []


def test_a_windows_asdf_exclusion_is_recorded_with_its_reason() -> None:
    """Dropping asdf for a Windows target is explained, not silent.

    Given:
        - A registry entry with aqua and asdf backends.
    When:
        - It is resolved for ``windows-x64`` and converted to a dict.
    Then:
        - ``excluded`` names asdf with a reason mentioning Windows.
    """
    registry = entry("tool", "aqua:o/r", "asdf:o/r")

    resolution = resolve("o/r", FakeMise([registry]), Platform("windows", "x64"))

    (excluded,) = resolution.exclusions
    assert excluded.backend_string == "asdf:o/r"
    assert "Windows" in excluded.reason
    assert resolution.to_dict()["excluded"] == [
        {"backend_string": "asdf:o/r", "reason": excluded.reason}
    ]


def test_to_dict_without_a_backend_has_a_null_recommendation() -> None:
    """No backend found gives a null recommendation and no candidates."""
    data = resolve("sharkdp/fd", FakeMise([RIPGREP])).to_dict()
    assert isinstance(data["candidates"], list)

    assert data["recommendation"] is None
    assert data["candidates"] == []


def test_aqua_recipe_without_a_registry_entry_is_a_candidate() -> None:
    """A repository with an aqua recipe but no registry entry resolves to aqua.

    Given:
        - A registry that lacks the repository and an aqua recipe for it.
    When:
        - ``sharkdp/fd`` is resolved.
    Then:
        - ``aqua:sharkdp/fd`` is the only candidate and the recommendation.
    """
    resolution = resolve("sharkdp/fd", FakeMise([RIPGREP], recipes=["aqua:sharkdp/fd"]))

    assert [c.backend_string for c in resolution.candidates] == ["aqua:sharkdp/fd"]
    assert resolution.recommendation is resolution.candidates[0]
    assert resolution.candidates[0].reasons
    assert resolution.candidates[0].mise_use == "mise use aqua:sharkdp/fd"


def test_no_aqua_recipe_means_no_aqua_candidate() -> None:
    """A repository without an aqua recipe gets no aqua candidate.

    Given:
        - A registry without the repository and a recipe for another one.
    When:
        - ``sharkdp/fd`` is resolved.
    Then:
        - There are no candidates.
    """
    resolution = resolve("sharkdp/fd", FakeMise(recipes=["aqua:BurntSushi/ripgrep"]))

    assert resolution.candidates == ()


def test_a_backend_found_by_registry_and_aqua_appears_once() -> None:
    """The same backend string from two steps collapses into one candidate.

    Given:
        - A registry entry listing aqua and ubi, and an aqua recipe.
    When:
        - ``BurntSushi/ripgrep`` is resolved.
    Then:
        - ``aqua:BurntSushi/ripgrep`` appears once, in its registry position.
    """
    resolution = resolve(
        "BurntSushi/ripgrep", FakeMise([RIPGREP], recipes=["aqua:BurntSushi/ripgrep"])
    )

    assert [c.backend_string for c in resolution.candidates] == [
        "aqua:BurntSushi/ripgrep",
        "ubi:BurntSushi/ripgrep",
    ]


def test_aqua_recipe_is_added_and_outranks_a_legacy_registry_backend() -> None:
    """A registry entry without aqua still gets the aqua recipe, ranked by tier.

    Given:
        - A registry entry listing only ubi, and an aqua recipe.
    When:
        - ``BurntSushi/ripgrep`` is resolved.
    Then:
        - The aqua candidate ranks ahead of the legacy ubi backend.
    """
    resolution = resolve(
        "BurntSushi/ripgrep",
        FakeMise(
            [entry("ripgrep", "ubi:BurntSushi/ripgrep")],
            recipes=["aqua:BurntSushi/ripgrep"],
        ),
    )

    assert [c.backend_string for c in resolution.candidates] == [
        "aqua:BurntSushi/ripgrep",
        "ubi:BurntSushi/ripgrep",
    ]
