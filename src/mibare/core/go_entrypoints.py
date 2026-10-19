"""Go entrypoint detection: a ``package main`` at the root or under ``cmd/<name>``.

A Go repository installs with ``go:<module path>``, plus ``/cmd/<name>`` for an
entrypoint that lives in a subdirectory, so one candidate is offered per
entrypoint. A ``go.mod`` in ``cmd/<name>`` or in ``cmd`` starts a separate
module: the nearest one above the command supplies the module path, and the
command's directory relative to it is the subpath.

Only files built for the target platform count (see
:mod:`mibare.core.go_constraints`).

Reading is bounded to spare GitHub's rate limit (60 REST requests an hour
without a token). The whole repository is listed with one request, which finds
every ``.go`` file and ``cmd/<name>`` directory without per-directory
listings. Then at most :data:`MAX_FILE_READS` file reads are spent across the
whole Go step (``go.mod`` included). Each directory is searched in file-name
order with ``main.go`` first, stops at its first ``package main`` and reads at
most :data:`MAX_FILES_PER_DIR` files; the first file of every directory is read
before the second file of any, so the budget is spread evenly. When a limit
hides part of the search (the budget, the per-directory cap or a truncated
listing), the detections carry a note saying the Go search was limited, and an
entrypoint hidden behind the limit is missed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final

from mibare.core.detection import Detection
from mibare.core.go_constraints import constraint_matches, name_matches

if TYPE_CHECKING:
    from mibare.core.github import GitHub
    from mibare.core.platform import Platform
    from mibare.core.repository import Repository

__all__ = ["MAX_FILES_PER_DIR", "MAX_FILE_READS", "detect_go"]

#: The most file reads (``go.mod`` and ``.go`` files) in one Go detector run.
MAX_FILE_READS = 20
#: The most ``.go`` files read in one directory, ``main.go`` first.
MAX_FILES_PER_DIR = 3

_CMD_FILE_DEPTH = 3  # cmd/<name>/<file>.go

_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
_PACKAGE = re.compile(r"^\s*package\s+(\w+)", re.MULTILINE)
_MODULE = re.compile(r'^\s*module\s+"?([^\s"]+)"?', re.MULTILINE)


@final
class _Reader:
    """Reads repository files within the detector's shared read budget."""

    def __init__(self, repository: Repository, github: GitHub) -> None:
        """Start with the full :data:`MAX_FILE_READS` budget."""
        self._repository = repository
        self._github = github
        self._remaining = MAX_FILE_READS
        self.limits: list[str] = []
        self._modules: dict[str, str | None] = {}

    def limit(self, reason: str) -> None:
        """Record why the search was cut short, once."""
        if reason not in self.limits:
            self.limits.append(reason)

    def read(self, path: str) -> str | None:
        """Read ``path`` when budget is left.

        Returns:
            str | None: The text, or ``None`` when the file is absent or the
                budget is spent (which is recorded as a limit).
        """
        if self._remaining == 0:
            self.limit(f"it reads at most {MAX_FILE_READS} files")
            return None
        self._remaining -= 1
        return self._github.root_file(self._repository, path)

    def module(self, path: str) -> str | None:
        """Read the ``go.mod`` at ``path`` once and return its module path.

        Returns:
            str | None: The declared path, or ``None`` when the file cannot be
                read or declares none.
        """
        if path not in self._modules:
            text = self.read(path)
            self._modules[path] = None if text is None else _declared_module(text)
        return self._modules[path]

    @property
    def note(self) -> tuple[str, ...]:
        """The note to attach to detections, empty when nothing was limited."""
        if not self.limits:
            return ()
        return (f"The Go search was limited: {'; '.join(self.limits)}.",)


def _declares_main(source: str) -> bool:
    """Whether ``source``'s package clause is ``package main``.

    Returns:
        bool: ``True`` for ``package main``, ignoring comments.
    """
    match = _PACKAGE.search(_COMMENTS.sub("", source))
    return match is not None and match.group(1) == "main"


def _is_main(source: str, platform: Platform) -> bool:
    """Whether ``source`` is a ``package main`` file built for ``platform``.

    Returns:
        bool: ``True`` when its build constraint holds and it declares main.
    """
    return constraint_matches(source, platform) and _declares_main(source)


def _go_directories(paths: tuple[str, ...], platform: Platform) -> dict[str, list[str]]:
    """Group the ``.go`` files built for ``platform`` in the root and ``cmd/<name>``.

    Returns:
        dict[str, list[str]]: File names per directory (``""`` for the root),
            the root first and then ``cmd/<name>`` in name order, each with
            ``main.go`` first.
    """
    grouped: dict[str, list[str]] = {}
    for path in paths:
        parts = path.split("/")
        if not parts[-1].endswith(".go") or not name_matches(parts[-1], platform):
            continue
        if len(parts) == 1:
            grouped.setdefault("", []).append(parts[0])
        elif len(parts) == _CMD_FILE_DEPTH and parts[0] == "cmd":
            grouped.setdefault(f"cmd/{parts[1]}", []).append(parts[2])
    return {
        directory: sorted(names, key=lambda n: (n != "main.go", n))
        for directory, names in sorted(grouped.items())
    }


def _note_per_directory_cap(
    reader: _Reader, directories: dict[str, list[str]], found: set[str]
) -> None:
    """Record the per-directory cap when it hid files in a directory without a main."""
    if any(
        len(names) > MAX_FILES_PER_DIR and directory not in found
        for directory, names in directories.items()
    ):
        reader.limit(f"it reads at most {MAX_FILES_PER_DIR} files per directory")


def _find_mains(
    reader: _Reader, directories: dict[str, list[str]], platform: Platform
) -> set[str]:
    """Find the directories whose files declare ``package main``.

    Files are read round-robin, so every directory's first file is read before
    any directory's second.

    Returns:
        set[str]: The directories with a ``package main``.
    """
    found: set[str] = set()
    for rank in range(MAX_FILES_PER_DIR):
        for directory, names in directories.items():
            if directory in found or rank >= len(names):
                continue
            prefix = f"{directory}/" if directory else ""
            source = reader.read(f"{prefix}{names[rank]}")
            if source is not None and _is_main(source, platform):
                found.add(directory)
    _note_per_directory_cap(reader, directories, found)
    return found


def _declared_module(go_mod: str) -> str | None:
    """Return the module path a ``go.mod`` declares.

    Returns:
        str | None: The path, or ``None`` without a ``module`` line.
    """
    match = _MODULE.search(_COMMENTS.sub("", go_mod))
    return match.group(1) if match else None


def _nearest_module(directory: str, paths: frozenset[str]) -> str | None:
    """Find the nearest ancestor directory below the root that holds a ``go.mod``.

    Returns:
        str | None: ``directory`` or its closest ancestor with a ``go.mod``, or
            ``None`` when the root module is the nearest one.
    """
    parts = directory.split("/") if directory else []
    for end in range(len(parts), 0, -1):
        candidate = "/".join(parts[:end])
        if f"{candidate}/go.mod" in paths:
            return candidate
    return None


def _entrypoint(
    reader: _Reader, directory: str, paths: frozenset[str], root: tuple[str, str]
) -> tuple[str, str] | None:
    """Name the backend string and reason for the ``package main`` in ``directory``.

    A command inside a nested module crosses a module boundary: the root
    module path plus the subpath would name a package that does not exist, so
    the nearest ``go.mod`` above the command (the command's own directory or
    an ancestor such as ``cmd``) declares the path, and the command's
    directory relative to it is the subpath.

    Args:
        reader: The shared read budget.
        directory: ``""`` for the root, else ``cmd/<name>``.
        paths: Every file path in the repository.
        root: The root module path and the reason suffix that qualifies it.

    Returns:
        tuple[str, str] | None: The backend string and the reason, or ``None``
            when the nested module cannot be read or declares no path.
    """
    module, suffix = root
    boundary = _nearest_module(directory, paths)
    if boundary is not None:
        declared = reader.module(f"{boundary}/go.mod")
        if declared is None:
            return None
        relative = directory.removeprefix(boundary).strip("/")
        subpath = f"/{relative}" if relative else ""
        where = "its own module" if not relative else f"the module {declared}"
        return (
            f"go:{declared}{subpath}",
            f"{directory} declares package main in {where}",
        )
    subpath = f"/{directory}" if directory else ""
    where = directory or "the root"
    return f"go:{module}{subpath}", f"{where} declares package main{suffix}"


def _resolve_entrypoints(
    reader: _Reader,
    mains: set[str],
    paths: frozenset[str],
    root: tuple[str, str],
    *,
    bad_root: bool,
) -> list[tuple[str, str]]:
    """Resolve the backend string and reason of every command in ``mains``.

    A root ``go.mod`` without a ``module`` directive only invalidates the
    commands that belong to the root module; a nested ``go.mod`` is its own
    module root, so its commands still resolve.

    Returns:
        list[tuple[str, str]]: The backend string and reason per resolvable
            command, the root first and then ``cmd/<name>`` in name order.
    """
    owned = [
        directory
        for directory in sorted(mains, key=lambda d: (bool(d), d))
        if not bad_root or _nearest_module(directory, paths) is not None
    ]
    # Resolve every entrypoint before the caller reads the note: go.mod reads
    # can spend the budget, so the note is only complete once they have all run.
    resolved = (_entrypoint(reader, directory, paths, root) for directory in owned)
    return list(filter(None, resolved))


def detect_go(
    repository: Repository, github: GitHub, platform: Platform
) -> list[Detection]:
    """Look for ``package main`` at the root and under ``cmd/<name>``.

    The module path comes from ``go.mod``. Without a root ``go.mod`` the
    repository's GitHub path stands in for it, and the reason says so. A root
    ``go.mod`` with no ``module`` directive is an exclusion, not a fallback: it
    excludes only the commands of the root module, while commands under a
    nested ``go.mod`` still resolve.

    Returns:
        list[Detection]: One ``found`` detection per entrypoint, or a single
            exclusion when the module has none; with a bad root ``go.mod``,
            the exclusion follows any nested entrypoints.
    """
    listing = github.list_files(repository)
    reader = _Reader(repository, github)
    if listing.truncated:
        reader.limit("GitHub truncated the repository file listing")
    go_mod = (
        reader.read("go.mod")
        if "go.mod" in listing.paths or listing.truncated
        else None
    )
    fallback = f"github.com/{repository.shorthand}"
    declared = None if go_mod is None else _declared_module(go_mod)
    bad_root = go_mod is not None and declared is None
    module = fallback if declared is None else declared
    suffix = (
        ""
        if go_mod is not None
        else f" (no go.mod in the repository root; assumed {fallback})"
    )
    mains = _find_mains(reader, _go_directories(listing.paths, platform), platform)
    resolved = _resolve_entrypoints(
        reader, mains, frozenset(listing.paths), (module, suffix), bad_root=bad_root
    )
    found = [Detection(b, r, notes=reader.note) for b, r in resolved]
    if bad_root:
        reason = "go.mod has no module directive"
        return [
            *found,
            Detection(f"go:{fallback}", reason, found=False, notes=reader.note),
        ]
    if found:
        return found
    reason = "no package main in the root or under cmd/"
    if go_mod is None:
        reason = "no go.mod in the repository root and " + reason
    return [Detection(f"go:{module}", reason, found=False, notes=reader.note)]
