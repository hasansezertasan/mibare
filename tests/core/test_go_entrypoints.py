"""Tests for Go entrypoint detection, through ``resolve()`` with fakes."""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def test_only_a_bounded_number_of_root_files_is_read() -> None:
    """A huge root listing is capped, so a late ``package main`` is missed."""
    files = {"go.mod": GO_MOD}
    files.update({f"a{i:02}.go": LIB for i in range(25)})
    files["z.go"] = MAIN

    assert _go(files).candidates == ()


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
