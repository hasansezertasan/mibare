"""Tests for resolving a repository to mise backends, through ``resolve()``."""

from __future__ import annotations

import json

import pytest

from mibare.core.errors import (
    GitHubUnavailableError,
    InvalidPlatformError,
    InvalidRepositoryError,
    MiseError,
    MiseNotFoundError,
    MiseTooOldError,
    RepositoryNotFoundError,
)
from mibare.core.github import GitHubApi
from mibare.core.platform import Platform
from mibare.core.resolve import Resolution, resolve
from tests.fakes import FakeGitHub, FakeMise, FakeTransport, entry

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
        "go:github.com/BurntSushi/ripgrep/cmd/rg",
        "packslip:github.com/BurntSushi/ripgrep",
        "spm:BurntSushi/ripgrep",
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
        - aqua then github (alphabetical in the tier), the language package, asdf, ubi.
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
        "aqua:eza-community/eza",
        "github:eza-community/eza",
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
        - The order is identical and breaks ties alphabetically by backend string.
    """
    registry = entry("t", "npm:github:o/r", "cargo:github.com/o/r", "aqua:o/r")

    first = _backends(resolve("o/r", FakeMise([registry])))
    second = _backends(resolve("o/r", FakeMise([registry])))

    assert first == second == ["aqua:o/r", "cargo:github.com/o/r", "npm:github:o/r"]


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


def test_a_backend_listed_twice_by_one_tool_gives_one_reason() -> None:
    """Repeating a backend in a registry entry does not repeat its reason.

    Given:
        - A registry entry listing the same backend string twice.
    When:
        - The repository is resolved.
    Then:
        - The candidate appears once with a single registry reason.
    """
    registry = entry("tool", "aqua:o/r", "aqua:o/r")

    resolution = resolve("o/r", FakeMise([registry]))

    (candidate,) = resolution.candidates
    assert candidate.backend_string == "aqua:o/r"
    assert len(candidate.reasons) == 1


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
    monkeypatch.setattr("mibare.core.resolve.host_platform", lambda: windows)
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
    monkeypatch.setattr("mibare.core.resolve.host_platform", lambda: HOST)

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
    monkeypatch.setattr("mibare.core.resolve.host_platform", lambda: HOST)

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


LINUX_X64 = Platform("linux", "x64")
TOOL = "owner/tool"
GITHUB_TOOL = "github:owner/tool"
TOOL_ASSETS = ("tool-linux-x64.tar.gz", "tool-darwin-arm64.tar.gz")


def test_github_candidate_when_the_release_has_a_platform_asset() -> None:
    """A probed repository with an asset for the target gets a github candidate.

    Given:
        - A repository mise can probe as ``github:`` and a latest release with
          a linux-x64 asset.
    When:
        - It is resolved for linux-x64.
    Then:
        - ``github:owner/tool`` is the recommendation, with a reason.
    """
    mise = FakeMise(recipes=[GITHUB_TOOL])

    resolution = resolve(TOOL, mise, LINUX_X64, github=FakeGitHub(TOOL_ASSETS))

    assert resolution.recommendation is not None
    assert resolution.recommendation.backend_string == GITHUB_TOOL
    assert resolution.recommendation.tier == 2
    assert resolution.recommendation.reasons


def test_no_github_candidate_without_an_asset_for_the_platform() -> None:
    """A release with assets only for other platforms gives no candidate."""
    mise = FakeMise(recipes=[GITHUB_TOOL])
    github = FakeGitHub(["tool-darwin-arm64.tar.gz", "tool-linux-x64.tar.gz.sha256"])

    resolution = resolve(TOOL, mise, LINUX_X64, github=github)

    assert resolution.candidates == ()


def test_no_github_candidate_when_the_probe_fails() -> None:
    """Assets alone are not enough; mise must be able to list the repository."""
    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=FakeGitHub(TOOL_ASSETS))

    assert resolution.candidates == ()


def test_github_comes_after_registry_and_aqua() -> None:
    """The github step adds its candidate after the earlier steps' candidates."""
    mise = FakeMise(recipes=["aqua:owner/tool", GITHUB_TOOL])

    resolution = resolve(TOOL, mise, LINUX_X64, github=FakeGitHub(TOOL_ASSETS))

    assert [c.backend_string for c in resolution.candidates] == [
        "aqua:owner/tool",
        GITHUB_TOOL,
    ]


def test_github_step_is_skipped_when_the_registry_already_lists_it() -> None:
    """A github backend found earlier is not looked up again."""
    mise = FakeMise([entry("tool", GITHUB_TOOL)], recipes=[GITHUB_TOOL])
    github = FakeGitHub(TOOL_ASSETS)

    resolution = resolve(TOOL, mise, LINUX_X64, github=github)

    assert [c.backend_string for c in resolution.candidates] == [GITHUB_TOOL]
    assert github.calls == 0


def test_without_a_github_adapter_the_step_is_left_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``resolve()`` stays offline when no GitHub adapter is passed.

    The step is left out silently: no candidate, no skipped-step note.
    """
    monkeypatch.setattr("mibare.core.resolve.host_platform", lambda: LINUX_X64)

    resolution = resolve(TOOL, FakeMise(recipes=[GITHUB_TOOL]), LINUX_X64)

    assert resolution.candidates == ()
    assert resolution.notes == ()


def test_network_failure_keeps_offline_results_and_names_skipped_steps() -> None:
    """Offline candidates survive a GitHub failure, with a note on what was skipped.

    Given:
        - An aqua recipe and a probeable github repository, with GitHub down.
    When:
        - The repository is resolved.
    Then:
        - The aqua candidate is returned and a note names the skipped step.
    """
    mise = FakeMise(recipes=["aqua:owner/tool", GITHUB_TOOL])
    github = FakeGitHub(error=GitHubUnavailableError("could not reach GitHub"))

    resolution = resolve(TOOL, mise, LINUX_X64, github=github)

    assert [c.backend_string for c in resolution.candidates] == ["aqua:owner/tool"]
    assert any(
        "github:" in note and "skipped" in note.lower() for note in resolution.notes
    )
    assert resolution.to_dict()["notes"] == list(resolution.notes)


def test_network_failure_without_results_raises() -> None:
    """With nothing usable and GitHub down, resolution fails instead of 'no backend'."""
    mise = FakeMise(recipes=[GITHUB_TOOL])
    github = FakeGitHub(error=GitHubUnavailableError("could not reach GitHub"))

    with pytest.raises(GitHubUnavailableError, match="could not reach GitHub"):
        _ = resolve(TOOL, mise, LINUX_X64, github=github)


def test_a_failed_aqua_probe_is_skipped_and_the_other_steps_survive() -> None:
    """A mise failure on the aqua probe is a skipped step, not an absent recipe.

    Given:
        - A registry backend for the repository and an aqua probe that fails.
    When:
        - The repository is resolved.
    Then:
        - The registry candidate is kept and a note names the aqua step.
    """
    mise = FakeMise(
        [entry("tool", "github:owner/tool")],
        probe_errors={"aqua:owner/tool": MiseError("network down")},
    )

    resolution = resolve(TOOL, mise, LINUX_X64)

    assert [c.backend_string for c in resolution.candidates] == ["github:owner/tool"]
    assert "Skipped the aqua step: network down" in resolution.notes


def test_a_failed_github_probe_is_skipped_and_keeps_earlier_results() -> None:
    """A mise failure on the github: probe is a skipped step."""
    mise = FakeMise(
        recipes=["aqua:owner/tool"],
        probe_errors={GITHUB_TOOL: MiseError("rate limited")},
    )

    resolution = resolve(TOOL, mise, LINUX_X64, github=FakeGitHub())

    assert [c.backend_string for c in resolution.candidates] == ["aqua:owner/tool"]
    assert "Skipped the github: step: rate limited" in resolution.notes


def test_failed_probes_with_no_candidates_raise_instead_of_no_backend() -> None:
    """With nothing usable and a probe failing, resolution fails (exit 2)."""
    mise = FakeMise(probe_errors={"aqua:owner/tool": MiseError("network down")})

    with pytest.raises(MiseError, match="network down"):
        _ = resolve(TOOL, mise, LINUX_X64)


def _excluded(resolution: Resolution) -> dict[str, str]:
    """Map each excluded backend string to its reason.

    Returns:
        dict[str, str]: The exclusions by backend string.
    """
    return {x.backend_string: x.reason for x in resolution.exclusions}


def test_a_missing_aqua_recipe_is_explained_as_an_exclusion() -> None:
    """Explain why aqua is not a candidate when mise has no recipe for it."""
    resolution = resolve(TOOL, FakeMise(), LINUX_X64)

    reason = _excluded(resolution)["aqua:owner/tool"]
    assert "recipe" in reason
    assert resolution.to_dict()["excluded"] == [
        {"backend_string": "aqua:owner/tool", "reason": reason}
    ]


def test_an_aqua_backend_found_by_the_registry_is_not_excluded() -> None:
    """Do not report aqua as excluded when the registry already lists it."""
    resolution = resolve(TOOL, FakeMise([entry("tool", "aqua:owner/tool")]))

    assert "aqua:owner/tool" not in _excluded(resolution)


def test_a_github_repository_mise_cannot_list_is_explained() -> None:
    """Explain why github: is not a candidate when the mise probe finds nothing."""
    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=FakeGitHub(TOOL_ASSETS))

    assert "mise" in _excluded(resolution)[GITHUB_TOOL]


def test_a_release_without_an_asset_for_the_platform_is_explained() -> None:
    """Name the platform the latest release has no asset for."""
    mise = FakeMise(recipes=[GITHUB_TOOL])
    github = FakeGitHub(["tool-darwin-arm64.tar.gz"])

    resolution = resolve(TOOL, mise, LINUX_X64, github=github)

    assert "linux-x64" in _excluded(resolution)[GITHUB_TOOL]


def test_a_repository_without_a_release_is_explained() -> None:
    """Explain a github: exclusion when there is no release to take assets from."""
    mise = FakeMise(recipes=[GITHUB_TOOL])

    resolution = resolve(TOOL, mise, LINUX_X64, github=FakeGitHub())

    assert "release" in _excluded(resolution)[GITHUB_TOOL]


def test_every_registry_entry_for_the_repository_contributes_its_backends() -> None:
    """A repository listed under several registry tools keeps all their backends.

    Given:
        - Two registry tools that both list ``o/r`` and add different backends.
    When:
        - ``o/r`` is resolved.
    Then:
        - The candidates are the union of both entries' backends, each once,
          and a shared backend carries a reason from each tool.
    """
    registry = [
        entry("tool-a", "aqua:o/r", "ubi:o/r"),
        entry("tool-b", "github:o/r", "aqua:o/r"),
    ]

    resolution = resolve("o/r", FakeMise(registry))

    assert sorted(_backends(resolution)) == ["aqua:o/r", "github:o/r", "ubi:o/r"]
    shared = next(c for c in resolution.candidates if c.backend_string == "aqua:o/r")
    assert [r for r in shared.reasons if "'tool-" in r] == [
        "listed in the mise registry as 'tool-a'",
        "listed in the mise registry as 'tool-b'",
    ]


@pytest.mark.parametrize(
    "backend", ["asdf:BurntSushi/ripgrep", "vfox:BurntSushi/ripgrep"]
)
def test_plugin_repositories_are_not_the_tools_repository(backend: str) -> None:
    """An asdf or vfox value names a plugin repository, not the tool's own.

    Given:
        - A registry entry whose only backend is an asdf or vfox plugin
          repository that happens to be ``BurntSushi/ripgrep``.
    When:
        - ``BurntSushi/ripgrep`` is resolved.
    Then:
        - The entry is not matched and there are no candidates.
    """
    resolution = resolve("BurntSushi/ripgrep", FakeMise([entry("rg", backend)]))

    assert resolution.candidates == ()


def test_an_npm_github_backend_identifies_its_repository() -> None:
    """``npm:github:owner/repo`` installs from the repository it names."""
    backend = "npm:github:BurntSushi/ripgrep"

    resolution = resolve("BurntSushi/ripgrep", FakeMise([entry("rg", backend)]))

    assert _backends(resolution) == [backend]


def test_ties_within_a_tier_break_alphabetically_for_registry_candidates() -> None:
    """Equal-tier candidates are ordered by backend string, not registry order.

    Given:
        - A registry entry listing github before aqua and npm before cargo.
    When:
        - The repository is resolved.
    Then:
        - aqua precedes github in tier 2 and cargo precedes npm in tier 4.
    """
    registry = entry(
        "t", "github:o/r", "npm:github:o/r", "cargo:github.com/o/r", "aqua:o/r"
    )

    resolution = resolve("o/r", FakeMise([registry]))

    assert _backends(resolution) == [
        "aqua:o/r",
        "github:o/r",
        "cargo:github.com/o/r",
        "npm:github:o/r",
    ]


def test_the_primary_language_leads_among_registry_language_packages() -> None:
    """A registry language package matching the primary language wins its tier.

    Given:
        - A registry entry listing cargo and pypi backends, and a Python
          repository.
    When:
        - The repository is resolved with a GitHub adapter.
    Then:
        - The pypi backend precedes the alphabetically earlier cargo one.
    """
    registry = entry("t", "aqua:o/r", "cargo:github.com/o/r", "pypi:o-r")
    github = FakeGitHub(language="Python")

    resolution = resolve("o/r", FakeMise([registry]), LINUX_X64, github=github)

    assert _backends(resolution) == ["aqua:o/r", "pypi:o-r", "cargo:github.com/o/r"]


def _unsupported_host() -> Platform:
    """Fail like ``host_platform()`` does on an unsupported host.

    Raises:
        InvalidPlatformError: Always.
    """
    message = "Unsupported host platform Plan9-mips; pass --platform os-arch."
    raise InvalidPlatformError(message)


def test_an_explicit_platform_is_honored_on_an_unsupported_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve for the given platform when the host cannot be detected.

    Given:
        - A host that is not a supported platform.
    When:
        - A repository is resolved with an explicit platform.
    Then:
        - It resolves for that platform and notes that the host is unknown.
    """
    monkeypatch.setattr("mibare.core.resolve.host_platform", _unsupported_host)

    resolution = resolve("BurntSushi/ripgrep", FakeMise([RIPGREP]), LINUX_X64)

    assert resolution.platform == LINUX_X64
    assert resolution.recommendation is not None
    assert any("host" in note and "detect" in note for note in resolution.notes)


def test_no_platform_on_an_unsupported_host_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an explicit platform the host must be detectable."""
    monkeypatch.setattr("mibare.core.resolve.host_platform", _unsupported_host)

    with pytest.raises(InvalidPlatformError, match="pass --platform"):
        _ = resolve("BurntSushi/ripgrep", FakeMise([RIPGREP]))


PACKAGE_BIN = '{"name": "tool", "bin": "cli.js"}'


@pytest.mark.parametrize(
    ("registered", "recipes", "github_files"),
    [
        ("aqua:Owner/Tool", ["aqua:owner/tool"], {}),
        ("github:Owner/Tool", ["github:owner/tool"], {}),
        ("npm:github:Owner/Tool", [], {"package.json": PACKAGE_BIN}),
        (
            "go:github.com/Owner/Tool",
            [],
            {"go.mod": "module github.com/owner/tool\n", "main.go": "package main\n"},
        ),
    ],
    ids=["aqua", "github", "npm", "go"],
)
def test_backends_are_deduplicated_ignoring_the_case_of_owner_and_repo(
    registered: str, recipes: list[str], github_files: dict[str, str]
) -> None:
    """A step re-finding a registry backend in another case adds no candidate.

    Given:
        - A registry entry spelling the repository ``Owner/Tool``.
    When:
        - ``owner/tool`` is resolved and a later step finds the same backend.
    Then:
        - One candidate remains, with the registry's spelling.
    """
    mise = FakeMise([entry("tool", registered)], recipes=recipes)
    github = FakeGitHub(TOOL_ASSETS, files=github_files)

    resolution = resolve(TOOL, mise, LINUX_X64, github=github)

    assert [c.backend_string for c in resolution.candidates] == [registered]


def test_a_repository_that_does_not_exist_is_an_error() -> None:
    """A definite 404 for the repository is an error, not 'no backend'.

    Given:
        - A GitHub adapter that reports the repository does not exist.
    When:
        - The repository is resolved, even with a registry entry for it.
    Then:
        - ``RepositoryNotFoundError`` says the repository was not found.
    """
    github = FakeGitHub()
    github.exists = False

    with pytest.raises(
        RepositoryNotFoundError,
        match="repository BurntSushi/ripgrep was not found on GitHub",
    ):
        _ = resolve("BurntSushi/ripgrep", FakeMise([RIPGREP]), HOST, github=github)


def test_a_failed_existence_check_keeps_the_offline_candidates() -> None:
    """A network error is not a 404: registry and aqua candidates survive it.

    Given:
        - A registry entry and an aqua recipe, with the existence check failing.
    When:
        - The repository is resolved.
    Then:
        - The candidates are kept and nothing is raised.
    """
    mise = FakeMise([RIPGREP], recipes=["aqua:BurntSushi/ripgrep"])
    github = FakeGitHub()
    github.exists_error = GitHubUnavailableError("could not reach GitHub")

    resolution = resolve("BurntSushi/ripgrep", mise, HOST, github=github)

    assert [c.backend_string for c in resolution.candidates] == [
        "aqua:BurntSushi/ripgrep",
        "ubi:BurntSushi/ripgrep",
    ]


def test_the_existence_check_is_not_made_without_a_github_adapter() -> None:
    """``resolve()`` stays offline by default: a repository is never checked."""
    resolution = resolve("owner/doesnotexist", FakeMise(), HOST)

    assert resolution.candidates == ()


def test_resolving_through_the_real_adapter_reports_a_missing_repository() -> None:
    """A fake transport answering 404 for the repository makes it an error."""
    transport = FakeTransport()

    with pytest.raises(RepositoryNotFoundError, match="owner/doesnotexist"):
        _ = resolve(
            "owner/doesnotexist",
            FakeMise(),
            HOST,
            github=GitHubApi(transport, token=None),
        )
    assert [url for url, _ in transport.requests] == [
        "https://api.github.com/repos/owner/doesnotexist"
    ]
