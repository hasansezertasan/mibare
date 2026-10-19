"""Resolve a repository to a ranked list of mise backend candidates."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mibare.core.assets import matching_assets
from mibare.core.errors import GitHubUnavailableError
from mibare.core.platform import Platform, host_platform
from mibare.core.repository import Repository, parse_repository

if TYPE_CHECKING:
    from mibare.core.github import GitHub
    from mibare.core.mise import Mise

__all__ = ["SCHEMA_VERSION", "Candidate", "Exclusion", "Resolution", "resolve"]

#: Version of the shape ``Resolution.to_dict`` returns; bumped on breaking changes.
SCHEMA_VERSION = 1

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
        reasons: Short explanations of why it is a candidate; each resolution
            step that finds the backend string appends its own.
        tier: Position on mise's preference ladder, 1 (packslip) to 5 (plugins);
            lower is better. ``None`` until ranking assigns one.
        legacy: Whether the backend is a legacy backend (asdf, vfox, ubi).
        warning: Why the candidate is discouraged, or ``None``.
    """

    backend_string: str
    reasons: tuple[str, ...] = ()
    tier: int | None = None
    legacy: bool = False
    warning: str | None = None

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
        platform: The target platform the candidates are for.
        notes: Remarks for the user, such as a target that differs from the host.
    """

    repository: Repository
    mise_version: str
    candidates: tuple[Candidate, ...]
    exclusions: tuple[Exclusion, ...] = ()
    platform: Platform | None = None
    notes: tuple[str, ...] = ()

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
        ``null``), ``legacy`` (bool), ``warning`` (text or ``null``),
        ``command`` and ``reasons``), ``excluded`` (each with
        ``backend_string`` and ``reason``), ``platform`` (``os-arch`` or
        ``null``) and ``notes`` (a list of text).

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
                    "legacy": c.legacy,
                    "warning": c.warning,
                    "command": c.mise_use,
                    "reasons": list(c.reasons),
                }
                for c in self.candidates
            ],
            "excluded": [
                {"backend_string": x.backend_string, "reason": x.reason}
                for x in self.exclusions
            ],
            "platform": self.platform.label if self.platform else None,
            "notes": list(self.notes),
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


def _candidate(backend_string: str, reasons: list[str]) -> Candidate:
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
    return Candidate(backend_string, tuple(reasons), tier, legacy, warning)


def _unusable_reason(candidate: Candidate, platform: Platform) -> str | None:
    """Say why the candidate's backend cannot run on ``platform``.

    Returns:
        str | None: The reason for asdf on Windows, ``None`` otherwise.
    """
    if platform.os == "windows" and candidate.backend_string.startswith("asdf:"):
        return "the asdf backend is not available on Windows"
    return None


def _platform_notes(target: Platform, host: Platform) -> tuple[str, ...]:
    """Note when the target differs from the host.

    Returns:
        tuple[str, ...]: One note, or none when the platforms are equal.
    """
    if target == host:
        return ()
    note = (
        f"Target platform {target.label} differs from the host {host.label}; "
        "registry data still reflects the host."
    )
    return (note,)


def _found_backends(repository: Repository, mise: Mise) -> dict[str, list[str]]:
    """Collect the backend strings that can install ``repository``.

    Returns:
        dict[str, list[str]]: Each backend string with the reasons it was found.
    """
    found: dict[str, list[str]] = {}
    for entry in mise.registry():
        if any(_points_at(repository, backend) for backend in entry.backends):
            reason = f"listed in the mise registry as {entry.tool!r}"
            for backend in entry.backends:
                found.setdefault(backend, []).append(reason)
            break
    aqua = f"aqua:{repository.shorthand}"
    if aqua not in found and mise.recipe_exists(aqua):
        found[aqua] = ["mise can list versions for this aqua recipe"]
    return found


def _github_release(
    repository: Repository, mise: Mise, github: GitHub, target: Platform
) -> list[str]:
    """Run the ``github:`` step: offer it when a release has a platform asset.

    Args:
        repository: The repository being resolved.
        mise: The mise adapter, for the existence probe.
        github: The GitHub adapter, for the latest release's assets.
        target: The platform the asset must be built for.

    Returns:
        list[str]: The reasons to offer ``github:owner/repo``; empty when it
            should not be offered.
    """
    if not mise.recipe_exists(f"github:{repository.shorthand}"):
        return []
    matches = matching_assets(github.latest_release_assets(repository), target)
    if not matches:
        return []
    return [f"the latest release has an asset for {target.label}: {matches[0]}"]


def _add_github(
    found: dict[str, list[str]],
    repository: Repository,
    mise: Mise,
    github: GitHub | None,
    target: Platform,
) -> GitHubUnavailableError | None:
    """Add the ``github:`` backend to ``found`` when its step passes.

    Returns:
        GitHubUnavailableError | None: The failure when GitHub was unreachable,
            otherwise ``None``.
    """
    backend = f"github:{repository.shorthand}"
    if github is None or backend in found:
        return None
    try:
        reasons = _github_release(repository, mise, github, target)
    except GitHubUnavailableError as error:
        return error
    if reasons:
        found[backend] = reasons
    return None


def _rank(
    found: dict[str, list[str]], target: Platform
) -> tuple[tuple[Candidate, ...], tuple[Exclusion, ...]]:
    """Tier, flag and sort the backends, dropping those unusable on ``target``.

    Returns:
        tuple[tuple[Candidate, ...], tuple[Exclusion, ...]]: The candidates,
            best tier first with ties in discovery order, and the exclusions.
    """
    candidates: list[Candidate] = []
    exclusions: list[Exclusion] = []
    for backend, reasons in found.items():
        candidate = _candidate(backend, reasons)
        why_not = _unusable_reason(candidate, target)
        if why_not is None:
            candidates.append(candidate)
        else:
            exclusions.append(Exclusion(backend, why_not))
    candidates.sort(key=lambda c: c.tier or _LOWEST_TIER)
    return tuple(candidates), tuple(exclusions)


def resolve(
    repository: str,
    mise: Mise,
    platform: Platform | None = None,
    github: GitHub | None = None,
) -> Resolution:
    """Resolve ``repository`` to the mise backends that can install it.

    Args:
        repository: A GitHub URL or ``owner/repo`` shorthand.
        mise: The mise adapter.
        platform: The target platform; defaults to the host.
        github: The GitHub adapter. Without one the steps that need the GitHub
            API are left out, so ``resolve()`` stays offline.

    Returns:
        Resolution: The ranked candidates; the first is the recommendation.
            When GitHub is unreachable, the offline candidates are kept and
            the skipped steps are named in ``notes``.

        A ``GitHubUnavailableError`` is raised instead when GitHub is
        unreachable and no offline step found a candidate, so the answer does
        not read as "no backend".
    """
    parsed = parse_repository(repository)
    host = host_platform()
    target = platform or host
    mise_version = mise.version()
    found = _found_backends(parsed, mise)
    failure = _add_github(found, parsed, mise, github, target)
    candidates, exclusions = _rank(found, target)
    if failure is not None and not candidates:
        raise failure
    skipped = (f"Skipped the github: step: {failure}",) if failure else ()
    notes = (*_platform_notes(target, host), *skipped)
    return Resolution(parsed, mise_version, candidates, exclusions, target, notes)
