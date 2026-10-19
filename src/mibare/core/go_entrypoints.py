"""Go entrypoint detection: a ``package main`` at the root or under ``cmd/<name>``.

A Go repository installs with ``go:<module path>``, plus ``/cmd/<name>`` for an
entrypoint that lives in a subdirectory, so one candidate is offered per
entrypoint.

Reading is bounded to spare the GitHub rate limit: a directory is searched in
file-name order (``main.go`` first), stops at the first ``package main``, and
reads at most :data:`MAX_FILES_PER_DIR` ``.go`` files. At most
:data:`MAX_CMD_DIRS` directories under ``cmd/`` are searched. An entrypoint hidden
behind that many other files or directories is missed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from mibare.core.detection import Detection

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mibare.core.github import GitHub
    from mibare.core.repository import Repository

__all__ = ["MAX_CMD_DIRS", "MAX_FILES_PER_DIR", "detect_go"]

#: The most ``.go`` files read in one directory.
MAX_FILES_PER_DIR = 20
#: The most ``cmd/<name>`` directories searched.
MAX_CMD_DIRS = 30

_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
_PACKAGE = re.compile(r"^\s*package\s+(\w+)", re.MULTILINE)
_MODULE = re.compile(r'^\s*module\s+"?([^\s"]+)"?', re.MULTILINE)


def _declares_main(source: str) -> bool:
    """Whether ``source``'s package clause is ``package main``.

    Returns:
        bool: ``True`` for ``package main``, ignoring comments.
    """
    match = _PACKAGE.search(_COMMENTS.sub("", source))
    return match is not None and match.group(1) == "main"


def _go_files(names: Sequence[str]) -> list[str]:
    """Pick the non-test ``.go`` files to read, ``main.go`` first, capped.

    Returns:
        list[str]: At most :data:`MAX_FILES_PER_DIR` file names.
    """
    files = sorted(
        (n for n in names if n.endswith(".go") and not n.endswith("_test.go")),
        key=lambda n: (n != "main.go", n),
    )
    return files[:MAX_FILES_PER_DIR]


def _has_main(repository: Repository, github: GitHub, directory: str) -> bool:
    """Whether a ``.go`` file in ``directory`` declares ``package main``.

    Returns:
        bool: ``True`` when one does.
    """
    prefix = f"{directory}/" if directory else ""
    for name in _go_files(github.list_dir(repository, directory)):
        source = github.root_file(repository, f"{prefix}{name}")
        if source is not None and _declares_main(source):
            return True
    return False


def _module_path(go_mod: str, repository: Repository) -> str:
    """Return the module path from ``go.mod``, else the GitHub path.

    Returns:
        str: The module path.
    """
    match = _MODULE.search(_COMMENTS.sub("", go_mod))
    return match.group(1) if match else f"github.com/{repository.shorthand}"


def detect_go(repository: Repository, github: GitHub) -> list[Detection]:
    """Look for ``package main`` at the root and under ``cmd/<name>``.

    The module path comes from ``go.mod``. Without a ``go.mod`` the
    repository's GitHub path stands in for it, and the reason says so.

    Returns:
        list[Detection]: One ``found`` detection per entrypoint, or a single
            exclusion when the module has none.
    """
    go_mod = github.root_file(repository, "go.mod")
    fallback = f"github.com/{repository.shorthand}"
    module = fallback if go_mod is None else _module_path(go_mod, repository)
    note = " (no go.mod in the repository root; assumed " + fallback + ")"
    found = [
        Detection(
            f"go:{module}{subpath}",
            f"{where} declares package main{note if go_mod is None else ''}",
        )
        for subpath, where in _entrypoints(repository, github)
    ]
    if found:
        return found
    reason = "no package main in the root or under cmd/"
    if go_mod is None:
        reason = "no go.mod in the repository root and " + reason
    return [Detection(f"go:{module}", reason, found=False)]


def _entrypoints(repository: Repository, github: GitHub) -> list[tuple[str, str]]:
    """Find the directories that declare ``package main``.

    Returns:
        list[tuple[str, str]]: A (module subpath, description) pair per
            entrypoint: the root first, then each ``cmd/<name>``.
    """
    entrypoints: list[tuple[str, str]] = []
    if _has_main(repository, github, ""):
        entrypoints.append(("", "the root"))
    names = github.list_dir(repository, "cmd")[:MAX_CMD_DIRS]
    entrypoints.extend(
        (f"/cmd/{name}", f"cmd/{name}")
        for name in names
        if _has_main(repository, github, f"cmd/{name}")
    )
    return entrypoints
