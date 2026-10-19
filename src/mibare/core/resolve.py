"""Resolve a repository to a ranked list of mise backend candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mibare.core.platform import Platform, host_platform
from mibare.core.repository import Repository, parse_repository

if TYPE_CHECKING:
    from mibare.core.mise import Mise

__all__ = ["Candidate", "Resolution", "resolve"]

#: Backends whose tool identifier is the repository's ``owner/repo``.
_OWNER_REPO_BACKENDS = frozenset({"aqua", "github", "ubi", "asdf", "vfox"})
_HOST_PREFIX = "github.com/"


#: Positions on mise's documented preference ladder, best first.
_TIERS = (
    frozenset({"packslip"}),
    frozenset({"aqua", "github", "gitlab", "forgejo"}),
    frozenset({"http", "s3"}),
    frozenset({"cargo", "go", "npm", "pypi", "pipx", "gem", "dotnet", "spm", "conda"}),
)
_LOWEST_TIER = len(_TIERS) + 1  # plugins and anything unknown
_LEGACY_BACKENDS = frozenset({"asdf", "vfox", "ubi"})
_LEGACY_WARNING = "{} is a legacy backend that mise discourages; prefer another."


@dataclass(frozen=True)
class Candidate:
    """A backend string that could install the tool for a repository.

    Attributes:
        backend_string: The backend and tool identifier, as in ``aqua:owner/repo``.
        tier: Position on mise's preference ladder, 1 (packslip) to 5 (plugins);
            lower is better. Defaults to the lowest.
        legacy: Whether the backend is a legacy backend (asdf, vfox, ubi).
        warning: Why the candidate is discouraged, or ``None``.
    """

    backend_string: str
    tier: int = _LOWEST_TIER
    legacy: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class Resolution:
    """The outcome of resolving a repository.

    Attributes:
        repository: The repository that was resolved.
        mise_version: The mise version whose registry the answer came from.
        candidates: The candidates, best first.
        platform: The target platform the candidates are for.
        notes: Remarks for the user, such as a target that differs from the host.
    """

    repository: Repository
    mise_version: str
    candidates: tuple[Candidate, ...]
    platform: Platform | None = None
    notes: tuple[str, ...] = ()

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


def _candidate(backend_string: str) -> Candidate:
    """Build a candidate, placing it on the tier ladder and flagging legacy.

    Returns:
        Candidate: The candidate for ``backend_string``.
    """
    backend = backend_string.partition(":")[0]
    tier = next(
        (rank for rank, tier in enumerate(_TIERS, 1) if backend in tier), _LOWEST_TIER
    )
    legacy = backend in _LEGACY_BACKENDS
    warning = _LEGACY_WARNING.format(backend) if legacy else None
    return Candidate(backend_string, tier, legacy, warning)


def _usable_on(candidate: Candidate, platform: Platform) -> bool:
    """Whether the candidate's backend can run on ``platform``.

    Returns:
        bool: ``False`` for asdf on Windows, ``True`` otherwise.
    """
    is_asdf = candidate.backend_string.startswith("asdf:")
    return not (platform.os == "windows" and is_asdf)


def resolve(
    repository: str, mise: Mise, platform: Platform | None = None
) -> Resolution:
    """Resolve ``repository`` to the mise backends that can install it.

    Args:
        repository: A GitHub URL or ``owner/repo`` shorthand.
        mise: The mise adapter.
        platform: The target platform; defaults to the host.

    Returns:
        Resolution: The ranked candidates; the first is the recommendation.
    """
    parsed = parse_repository(repository)
    host = host_platform()
    target = platform or host
    notes: tuple[str, ...] = ()
    if target != host:
        note = (
            f"Target platform {target.label} differs from the host {host.label}; "
            "registry data still reflects the host."
        )
        notes = (note,)
    mise_version = mise.version()
    backends: list[str] = []
    for entry in mise.registry():
        if any(_points_at(parsed, backend) for backend in entry.backends):
            backends.extend(entry.backends)
            break
    aqua = f"aqua:{parsed.shorthand}"
    if aqua not in backends and mise.recipe_exists(aqua):
        backends.append(aqua)
    ranked = sorted(
        (_candidate(b) for b in dict.fromkeys(backends)), key=lambda c: c.tier
    )
    candidates = tuple(c for c in ranked if _usable_on(c, target))
    return Resolution(parsed, mise_version, candidates, target, notes)
