"""Tests for Go entrypoint detection, through ``resolve()`` with fakes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mibare.core.ecosystems import GO
from mibare.core.go_entrypoints import MAX_FILE_READS, MAX_FILES_PER_DIR
from mibare.core.platform import Platform
from mibare.core.resolve import Resolution, resolve
from tests.fakes import FakeGitHub, FakeMise

if TYPE_CHECKING:
    from collections.abc import Mapping

LINUX_X64 = Platform("linux", "x64")
TOOL = "owner/tool"
GO_MOD = "module github.com/owner/tool\n\ngo 1.22\n"
MAIN = "package main\n\nfunc main() {}\n"
LIB = "package tool\n"


def _go(files: Mapping[str, str], *, language: str | None = None) -> Resolution:
    """Resolve ``owner/tool`` with fixture repository files.

    Returns:
        Resolution: The resolution.
    """
    github = FakeGitHub(files=files, language=language)
    return resolve(TOOL, FakeMise(), LINUX_X64, github=github)


def _backends(resolution: Resolution) -> list[str]:
    """List the backend strings of ``resolution`` in ranked order."""
    return [c.backend_string for c in resolution.candidates]


def test_root_package_main_gives_a_go_candidate() -> None:
    """A root ``package main`` resolves to ``go:github.com/owner/repo``."""
    resolution = _go({"go.mod": GO_MOD, "main.go": MAIN})

    assert _backends(resolution) == ["go:github.com/owner/tool"]
    top = resolution.recommendation
    assert top is not None
    assert top.tier == 4
    assert any("package main" in reason for reason in top.reasons)


def test_cmd_package_main_gets_the_subpath() -> None:
    """A ``package main`` under ``cmd/<name>`` adds that subpath."""
    files = {"go.mod": GO_MOD, "cmd/tool/main.go": MAIN, "tool.go": LIB}

    assert _backends(_go(files)) == ["go:github.com/owner/tool/cmd/tool"]


def test_several_cmd_binaries_give_one_candidate_each() -> None:
    """Every ``cmd/<name>`` binary is its own candidate."""
    files = {
        "go.mod": GO_MOD,
        "cmd/b/main.go": MAIN,
        "cmd/a/main.go": MAIN,
        "cmd/a/util.go": LIB,
        "cmd/shared/shared.go": LIB,
    }

    assert _backends(_go(files)) == [
        "go:github.com/owner/tool/cmd/a",
        "go:github.com/owner/tool/cmd/b",
    ]


def test_root_and_cmd_binaries_are_all_offered() -> None:
    """A root main and a cmd main are both candidates."""
    files = {"go.mod": GO_MOD, "main.go": MAIN, "cmd/x/main.go": MAIN}

    assert _backends(_go(files)) == [
        "go:github.com/owner/tool",
        "go:github.com/owner/tool/cmd/x",
    ]


def test_library_only_module_gives_no_go_candidate() -> None:
    """A library module is excluded with a reason."""
    resolution = _go({"go.mod": GO_MOD, "tool.go": LIB, "cmd/x/doc.go": LIB})

    assert resolution.candidates == ()
    (excluded,) = (
        x for x in resolution.exclusions if x.backend_string.startswith("go:")
    )
    assert excluded.backend_string == "go:github.com/owner/tool"
    assert "package main" in excluded.reason


def test_package_main_without_go_mod_falls_back_to_the_github_path() -> None:
    """Without a root ``go.mod`` the repository's GitHub path stands in.

    Given:
        - A root ``package main`` and a ``cmd/x`` binary, but no ``go.mod``.
    When:
        - The repository is resolved.
    Then:
        - The candidates use ``github.com/owner/repo`` and say it is a fallback.
    """
    resolution = _go({"main.go": MAIN, "cmd/x/main.go": MAIN})

    assert _backends(resolution) == [
        "go:github.com/owner/tool",
        "go:github.com/owner/tool/cmd/x",
    ]
    assert all(
        any("go.mod" in reason for reason in c.reasons) for c in resolution.candidates
    )


def test_no_go_mod_and_no_package_main_gives_no_go_candidate() -> None:
    """A repository with neither a ``go.mod`` nor a ``package main`` is not Go."""
    resolution = _go({"tool.go": LIB})

    assert resolution.candidates == ()
    assert any("go.mod" in x.reason for x in resolution.exclusions)


def test_module_path_comes_from_go_mod() -> None:
    """The backend string uses the module path declared in ``go.mod``."""
    mod = 'module "example.com/vanity/tool" // vanity\n'

    resolution = _go({"go.mod": mod, "main.go": MAIN})

    assert _backends(resolution) == ["go:example.com/vanity/tool"]


def test_missing_module_line_falls_back_to_the_repository() -> None:
    """Without a readable ``module`` line the GitHub path is used."""
    resolution = _go({"go.mod": "go 1.22\n", "main.go": MAIN})

    assert _backends(resolution) == ["go:github.com/owner/tool"]


def test_package_main_with_comments_is_detected() -> None:
    """Comments before the package clause do not hide ``package main``."""
    text = "// Command tool.\n/* block\ncomment */\n\npackage main // x\n"

    assert _backends(_go({"go.mod": GO_MOD, "main.go": text})) == [
        "go:github.com/owner/tool"
    ]


def test_only_a_bounded_number_of_files_per_directory_is_read() -> None:
    """A late ``package main`` behind many files is missed, and the note says so."""
    files = {"go.mod": GO_MOD}
    files.update({f"a{i:02}.go": LIB for i in range(25)})
    files["z.go"] = MAIN
    github = FakeGitHub(files=files)

    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=github, ecosystems=(GO,))

    assert resolution.candidates == ()
    root_reads = [n for n in github.file_reads if n.endswith(".go")]
    assert len(root_reads) == MAX_FILES_PER_DIR
    assert any("Go search was limited" in note for note in resolution.notes)


def test_main_go_is_read_before_other_files() -> None:
    """``main.go`` is tried first, so it is found with a single read."""
    files = {"go.mod": GO_MOD, "a.go": LIB, "main.go": MAIN}
    github = FakeGitHub(files=files)

    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=github, ecosystems=(GO,))

    assert _backends(resolution) == ["go:github.com/owner/tool"]
    assert github.file_reads == ["go.mod", "main.go"]
    assert resolution.notes == ()


def test_the_repository_is_listed_with_one_request() -> None:
    """Finding the Go files and ``cmd`` directories costs one listing request."""
    files = {"go.mod": GO_MOD, "cmd/a/main.go": MAIN, "cmd/b/main.go": MAIN}
    github = FakeGitHub(files=files)

    _ = resolve(TOOL, FakeMise(), LINUX_X64, github=github, ecosystems=(GO,))

    assert github.tree_calls == 1


def test_file_reads_across_the_go_step_are_capped() -> None:
    """Many ``cmd`` directories cannot exceed the read budget; the note says so."""
    files = {"go.mod": GO_MOD}
    files.update({f"cmd/c{i:02}/main.go": MAIN for i in range(30)})
    github = FakeGitHub(files=files)

    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=github, ecosystems=(GO,))

    assert len(github.file_reads) == MAX_FILE_READS
    assert len(resolution.candidates) == MAX_FILE_READS - 1
    assert any("Go search was limited" in note for note in resolution.notes)


def test_a_search_that_fits_the_budget_adds_no_note() -> None:
    """Exactly the budget's worth of work is not a limited search."""
    files = {"go.mod": GO_MOD}
    files.update({f"cmd/c{i:02}/main.go": MAIN for i in range(MAX_FILE_READS - 1)})

    resolution = _go(files)

    assert len(resolution.candidates) == MAX_FILE_READS - 1
    assert resolution.notes == ()


def test_a_truncated_file_listing_is_noted() -> None:
    """When GitHub truncates the tree, the search is flagged as incomplete."""
    github = FakeGitHub(files={"go.mod": GO_MOD, "main.go": MAIN})
    github.truncated = True

    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=github, ecosystems=(GO,))

    assert _backends(resolution) == ["go:github.com/owner/tool"]
    assert any("truncated" in note for note in resolution.notes)


def test_a_library_search_that_hits_a_limit_still_notes_it() -> None:
    """A not-found Go detection carries the limited-search note too."""
    github = FakeGitHub(files={"go.mod": GO_MOD, "a.go": LIB})
    github.truncated = True

    resolution = resolve(TOOL, FakeMise(), LINUX_X64, github=github, ecosystems=(GO,))

    assert resolution.candidates == ()
    assert any("Go search was limited" in note for note in resolution.notes)


def test_go_is_favoured_by_go_language() -> None:
    """The Go primary language puts ``go:`` ahead of ``pypi:``."""
    files = {
        "go.mod": GO_MOD,
        "main.go": MAIN,
        "pyproject.toml": '[project]\nname="t"\n[project.scripts]\nt="t:m"\n',
    }

    assert _backends(_go(files, language="Go")) == [
        "go:github.com/owner/tool",
        "pypi:owner/tool",
    ]
    assert _backends(_go(files, language="Python")) == [
        "pypi:owner/tool",
        "go:github.com/owner/tool",
    ]
