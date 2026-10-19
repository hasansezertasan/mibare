"""Resolve a repository to a ranked list of mise backend candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mibare.core.repository import Repository, parse_repository

if TYPE_CHECKING:
    from mibare.core.mise import Mise

__all__ = ["Candidate", "Resolution", "resolve"]

#: Backends whose tool identifier is the repository's ``owner/repo``.
_OWNER_REPO_BACKENDS = frozenset({"aqua", "github", "ubi", "asdf", "vfox"})
_HOST_PREFIX = "github.com/"


@dataclass(frozen=True)
class Candidate:
    """A backend string that could install the tool for a repository.

    Attributes:
        backend_string: The backend and tool identifier, as in ``aqua:owner/repo``.
    """

    backend_string: str


@dataclass(frozen=True)
class Resolution:
    """The outcome of resolving a repository.

    Attributes:
        repository: The repository that was resolved.
        mise_version: The mise version whose registry the answer came from.
        candidates: The candidates, best first.
    """

    repository: Repository
    mise_version: str
    candidates: tuple[Candidate, ...]

    @property
    def recommendation(self) -> Candidate | None:
        """The top-ranked candidate, or ``None`` when there is no backend."""
        return self.candidates[0] if self.candidates else None


def _repository_of(backend_string: str) -> Repository | None:
    """Work out which repository a backend string installs from, if any.

    Args:
        backend_string: A backend string such as ``aqua:owner/repo``.

    Returns:
        Repository | None: The repository, or ``None`` when the backend string
            does not point at a GitHub repository (``pypi:ansible``).
    """
    backend, _, tool = backend_string.partition(":")
    tool = tool.split("[", 1)[0]
    if backend in _OWNER_REPO_BACKENDS:
        path = tool
    elif tool.startswith(_HOST_PREFIX):
        path = tool.removeprefix(_HOST_PREFIX)
    else:
        return None
    owner, _, rest = path.partition("/")
    name = rest.split("/", 1)[0].removesuffix(".git")
    return Repository(owner, name) if owner and name else None


def _points_at(repository: Repository, backend_string: str) -> bool:
    """Whether ``backend_string`` installs from ``repository``, ignoring case.

    Returns:
        bool: ``True`` when the backend string points at ``repository``.
    """
    target = _repository_of(backend_string)
    return (
        target is not None and target.shorthand.lower() == repository.shorthand.lower()
    )


def resolve(repository: str, mise: Mise) -> Resolution:
    """Resolve ``repository`` to the mise backends that can install it.

    Args:
        repository: A GitHub URL or ``owner/repo`` shorthand.
        mise: The mise adapter.

    Returns:
        Resolution: The ranked candidates; the first is the recommendation.
    """
    parsed = parse_repository(repository)
    mise_version = mise.version()
    for entry in mise.registry():
        if any(_points_at(parsed, backend) for backend in entry.backends):
            candidates = tuple(Candidate(b) for b in entry.backends)
            return Resolution(parsed, mise_version, candidates)
    return Resolution(parsed, mise_version, ())
