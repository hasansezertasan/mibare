"""Language-package ecosystems: how a repository earns a ``pypi:``-style candidate.

Each ecosystem is one :class:`Ecosystem` in :data:`ECOSYSTEMS`. To add one,
write a detector with the :data:`Detector` signature and add one line to
:data:`ECOSYSTEMS`; ``resolve()`` handles the tier, the primary-language
tie-break and the reasons.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, cast

if sys.version_info >= (3, 11):
    import tomllib  # pyright: ignore[reportUnreachable]
else:
    import tomli as tomllib

if TYPE_CHECKING:
    from mibare.core.github import GitHub
    from mibare.core.repository import Repository

__all__ = ["CARGO", "ECOSYSTEMS", "NPM", "PYPI", "Detection", "Detector", "Ecosystem"]


@dataclass(frozen=True)
class Detection:
    """What a detector concluded about one repository.

    Attributes:
        backend_string: The backend string considered, as in ``pypi:owner/repo``.
        reason: Why it is offered (when ``found``) or why it is left out.
        found: Whether the repository has an entrypoint for this ecosystem.
    """

    backend_string: str
    reason: str
    found: bool = field(default=True, kw_only=True)


class Detector(Protocol):
    """Looks at a repository's root manifest for an entrypoint.

    It may raise ``GitHubUnavailableError``, which ``resolve()`` turns into a
    skipped-step note.
    """

    def __call__(self, repository: Repository, github: GitHub) -> Detection:
        """Return the detection for ``repository``."""
        raise NotImplementedError


@dataclass(frozen=True)
class Ecosystem:
    """A language-package backend and how to detect an entrypoint for it.

    Attributes:
        backend: The backend name, such as ``pypi``.
        languages: GitHub primary-language names that favour this backend,
            compared ignoring case.
        detect: The detector.
    """

    backend: str
    languages: frozenset[str]
    detect: Detector

    def favoured_by(self, language: str | None) -> bool:
        """Whether ``language`` is one this backend is the natural fit for.

        Returns:
            bool: ``True`` when ``language`` is one of :attr:`languages`.
        """
        if language is None:
            return False
        return language.lower() in {name.lower() for name in self.languages}


def _detect_python(repository: Repository, github: GitHub) -> Detection:
    """Look for ``[project.scripts]`` in the root ``pyproject.toml``.

    Returns:
        Detection: ``found`` when at least one script is declared.
    """
    backend_string = f"pypi:{repository.shorthand}"
    text = github.root_file(repository, "pyproject.toml")
    if text is None:
        reason = "no pyproject.toml in the repository root"
        return Detection(backend_string, reason, found=False)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        reason = "pyproject.toml in the repository root is not valid TOML"
        return Detection(backend_string, reason, found=False)
    project = data.get("project")
    scripts = (
        cast("dict[str, object]", project).get("scripts")
        if isinstance(project, dict)
        else None
    )
    if not isinstance(scripts, dict) or not scripts:
        reason = "pyproject.toml declares no [project.scripts] entrypoint"
        return Detection(backend_string, reason, found=False)
    names = ", ".join(sorted(cast("dict[str, object]", scripts)))
    return Detection(
        backend_string, f"pyproject.toml declares [project.scripts]: {names}"
    )


def _detect_cargo(repository: Repository, github: GitHub) -> Detection:
    """Look for a ``[[bin]]`` table or a ``src/main.rs`` beside ``Cargo.toml``.

    Returns:
        Detection: ``found`` when the crate has a bin target.
    """
    backend_string = f"cargo:{repository.shorthand}"
    text = github.root_file(repository, "Cargo.toml")
    if text is None:
        reason = "no Cargo.toml in the repository root"
        return Detection(backend_string, reason, found=False)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        reason = "Cargo.toml in the repository root is not valid TOML"
        return Detection(backend_string, reason, found=False)
    bins = data.get("bin")
    if isinstance(bins, list) and bins:
        return Detection(backend_string, "Cargo.toml declares a [[bin]] target")
    if github.root_file(repository, "src/main.rs") is not None:
        return Detection(backend_string, "the crate has a src/main.rs bin target")
    reason = "Cargo.toml declares no [[bin]] target and there is no src/main.rs"
    return Detection(backend_string, reason, found=False)


def _detect_npm(repository: Repository, github: GitHub) -> Detection:
    """Look for a non-empty ``bin`` in the root ``package.json``.

    Returns:
        Detection: ``found`` when ``bin`` is a non-empty string or object.
    """
    backend_string = f"npm:github:{repository.shorthand}"
    text = github.root_file(repository, "package.json")
    if text is None:
        reason = "no package.json in the repository root"
        return Detection(backend_string, reason, found=False)
    try:
        data = cast("object", json.loads(text))
    except ValueError:
        reason = "package.json in the repository root is not valid JSON"
        return Detection(backend_string, reason, found=False)
    bin_field = (
        cast("dict[str, object]", data).get("bin") if isinstance(data, dict) else None
    )
    if isinstance(bin_field, (str, dict)) and bin_field:
        return Detection(backend_string, "package.json declares a bin entrypoint")
    reason = "package.json declares no bin entrypoint"
    return Detection(backend_string, reason, found=False)


PYPI = Ecosystem("pypi", frozenset({"Python"}), _detect_python)
CARGO = Ecosystem("cargo", frozenset({"Rust"}), _detect_cargo)
NPM = Ecosystem("npm", frozenset({"JavaScript", "TypeScript"}), _detect_npm)

#: The registered ecosystems. Add a line here to support another one.
ECOSYSTEMS: tuple[Ecosystem, ...] = (PYPI, CARGO, NPM)
