"""Resolve a repository to a ranked list of mise backend candidates."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mibare.core.repository import Repository, parse_repository

if TYPE_CHECKING:
    from mibare.core.mise import Mise

__all__ = ["SCHEMA_VERSION", "Candidate", "Exclusion", "Resolution", "resolve"]

#: Version of the shape ``Resolution.to_dict`` returns; bumped on breaking changes.
SCHEMA_VERSION = 1

#: Backends whose tool identifier is the repository's ``owner/repo``.
_OWNER_REPO_BACKENDS = frozenset({"aqua", "github", "ubi", "asdf", "vfox"})
_HOST_PREFIX = "github.com/"


@dataclass(frozen=True)
class Candidate:
    """A backend string that could install the tool for a repository.

    Attributes:
        backend_string: The backend and tool identifier, as in ``aqua:owner/repo``.
        reasons: Short explanations of why it is a candidate; each resolution
            step that finds the backend string appends its own.
        tier: The position on mise's tier ladder, once ranking assigns one.
    """

    backend_string: str
    reasons: tuple[str, ...] = ()
    tier: int | None = None

    @property
    def mise_use(self) -> str:
        """A ready-to-paste ``mise use`` command for this candidate."""
        return f"mise use {shlex.quote(self.backend_string)}"


@dataclass(frozen=True)
class Exclusion:
    """A backend string that was considered and left out.

    Attributes:
        backend_string: The backend string that was excluded.
        reason: Why it was excluded.
    """

    backend_string: str
    reason: str


@dataclass(frozen=True)
class Resolution:
    """The outcome of resolving a repository.

    Attributes:
        repository: The repository that was resolved.
        mise_version: The mise version whose registry the answer came from.
        candidates: The candidates, best first.
        exclusions: The backend strings considered and left out, each with
            the reason.
    """

    repository: Repository
    mise_version: str
    candidates: tuple[Candidate, ...]
    exclusions: tuple[Exclusion, ...] = ()

    @property
    def recommendation(self) -> Candidate | None:
        """The top-ranked candidate, or ``None`` when there is no backend."""
        return self.candidates[0] if self.candidates else None

    def to_dict(self) -> dict[str, object]:
        """Return the documented, stable JSON shape of this resolution.

        The keys, in order: ``schema_version`` (int), ``repository``
        (``owner/repo``), ``mise_version``, ``recommendation`` (the first
        candidate's backend string, or ``null``), ``candidates`` (best first,
        each with ``backend_string``, ``recommended``, ``tier`` (int or
        ``null``), ``command`` and ``reasons``) and ``excluded`` (each with
        ``backend_string`` and ``reason``).

        Returns:
            dict[str, object]: A structure that ``json.dumps`` accepts.
        """
        top = self.recommendation
        return {
            "schema_version": SCHEMA_VERSION,
            "repository": self.repository.shorthand,
            "mise_version": self.mise_version,
            "recommendation": top.backend_string if top else None,
            "candidates": [
                {
                    "backend_string": c.backend_string,
                    "recommended": c is top,
                    "tier": c.tier,
                    "command": c.mise_use,
                    "reasons": list(c.reasons),
                }
                for c in self.candidates
            ],
            "excluded": [
                {"backend_string": x.backend_string, "reason": x.reason}
                for x in self.exclusions
            ],
        }


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
            reason = f"listed in the mise registry as {entry.tool!r}"
            candidates = tuple(Candidate(b, (reason,)) for b in entry.backends)
            return Resolution(parsed, mise_version, candidates)
    return Resolution(parsed, mise_version, ())
