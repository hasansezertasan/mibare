"""Resolve a repository to a ranked list of mise backend candidates."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple

from mibare.core.assets import matching_assets
from mibare.core.ecosystems import ECOSYSTEMS, Detection, Ecosystem
from mibare.core.errors import (
    GitHubUnavailableError,
    InvalidPlatformError,
    MibareError,
    MiseError,
)
from mibare.core.platform import Platform, host_platform
from mibare.core.repository import Repository, parse_repository

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mibare.core.github import GitHub
    from mibare.core.mise import Mise

__all__ = ["SCHEMA_VERSION", "Candidate", "Exclusion", "Resolution", "resolve"]

#: Version of the shape ``Resolution.to_dict`` returns; bumped on breaking changes.
SCHEMA_VERSION = 1

#: Backends whose tool identifier is the repository's ``owner/repo``. asdf and
#: vfox are left out: their value names a plugin repository, not the tool's own.
_OWNER_REPO_BACKENDS = frozenset({"aqua", "github", "spm", "ubi"})
#: Prefixes that precede an ``owner/repo`` path, as in ``go:github.com/o/r`` and
#: ``npm:github:o/r``.
_REPOSITORY_PREFIXES = ("github.com/", "github:")


#: Positions on mise's documented preference ladder, best first.
_TIERS = (
    frozenset({"packslip"}),
    frozenset({"aqua", "github", "gitlab", "forgejo"}),
    frozenset({"http", "s3"}),
    frozenset({"cargo", "go", "npm", "pypi", "pipx", "gem", "dotnet", "spm", "conda"}),
)
_MIN_TIED = 2  # candidates needed in a tier before a tie-break matters
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
            lower is better. Defaults to the lowest tier.
        legacy: Whether the backend is a legacy backend (asdf, vfox, ubi).
        warning: Why the candidate is discouraged, or ``None``.
    """

    backend_string: str
    reasons: tuple[str, ...] = ()
    tier: int = _LOWEST_TIER
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
        each with ``backend_string``, ``recommended``, ``tier`` (int),
        ``legacy`` (bool), ``warning`` (text or ``null``), ``command`` and
        ``reasons``), ``excluded`` (each with ``backend_string`` and
        ``reason``), ``platform`` (``os-arch`` or ``null``) and ``notes`` (a
        list of text).

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
                    "backend_string": candidate.backend_string,
                    "recommended": candidate is top,
                    "tier": candidate.tier,
                    "legacy": candidate.legacy,
                    "warning": candidate.warning,
                    "command": candidate.mise_use,
                    "reasons": list(candidate.reasons),
                }
                for candidate in self.candidates
            ],
            "excluded": [
                {"backend_string": exclusion.backend_string, "reason": exclusion.reason}
                for exclusion in self.exclusions
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
    else:
        prefix = next((p for p in _REPOSITORY_PREFIXES if tool.startswith(p)), None)
        if prefix is None:
            return None
        path = tool.removeprefix(prefix)
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


def _platform_notes(target: Platform, host: Platform | None) -> tuple[str, ...]:
    """Note when the target differs from the host, or the host is unknown.

    Returns:
        tuple[str, ...]: One note, or none when the platforms are equal.
    """
    if host is None:
        note = (
            f"Target platform {target.label}; the host platform could not be "
            "detected, so registry data may not match it."
        )
        return (note,)
    if target == host:
        return ()
    note = (
        f"Target platform {target.label} differs from the host {host.label}; "
        "registry data still reflects the host."
    )
    return (note,)


@dataclass
class _Findings:
    """What the ladder's steps have found so far.

    Attributes:
        backends: Each backend string found, with the reasons it was found,
            in discovery order.
        exclusions: The backend strings a step considered and left out, each
            with the reason.
        skipped: The failure of each skipped step, by step name.
        notes: Remarks from detectors about their own search, without repeats.
    """

    backends: dict[str, list[str]] = field(default_factory=dict)
    exclusions: list[Exclusion] = field(default_factory=list)
    skipped: dict[str, MibareError] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _probe_aqua(repository: Repository, mise: Mise, findings: _Findings) -> None:
    """Add ``aqua:owner/repo`` when mise has a recipe for it.

    A failed probe is recorded as a skipped step instead of raised.
    """
    aqua = f"aqua:{repository.shorthand}"
    if aqua in findings.backends:
        return
    try:
        exists = mise.recipe_exists(aqua)
    except MiseError as error:
        findings.skipped["aqua"] = error
        return
    if exists:
        findings.backends[aqua] = ["mise can list versions for this aqua recipe"]
    else:
        reason = "mise has no aqua recipe for this repository"
        findings.exclusions.append(Exclusion(aqua, reason))


def _found_backends(repository: Repository, mise: Mise) -> _Findings:
    """Run the registry and aqua steps for ``repository``.

    Returns:
        _Findings: The backend strings found and any skipped step.
    """
    findings = _Findings()
    backends = findings.backends
    for entry in mise.registry():
        if any(_points_at(repository, backend) for backend in entry.backends):
            reason = f"listed in the mise registry as {entry.tool!r}"
            for backend in entry.backends:
                reasons = backends.setdefault(backend, [])
                if reason not in reasons:
                    reasons.append(reason)
    _probe_aqua(repository, mise, findings)
    return findings


def _github_release(
    repository: Repository, mise: Mise, github: GitHub, target: Platform
) -> tuple[list[str], str]:
    """Run the ``github:`` step: offer it when a release has a platform asset.

    Args:
        repository: The repository being resolved.
        mise: The mise adapter, for the existence probe.
        github: The GitHub adapter, for the latest release's assets.
        target: The platform the asset must be built for.

    Returns:
        tuple[list[str], str]: The reasons to offer ``github:owner/repo``, or
            no reasons and why it should not be offered.
    """
    if not mise.recipe_exists(f"github:{repository.shorthand}"):
        return [], "mise cannot list versions of this github repository"
    assets = github.latest_release_assets(repository)
    if not assets:
        return [], "the repository has no release with assets"
    matches = matching_assets(assets, target)
    if not matches:
        return [], f"the latest release has no asset for {target.label}"
    return [f"the latest release has an asset for {target.label}: {matches[0]}"], ""


def _add_github(
    findings: _Findings,
    repository: Repository,
    mise: Mise,
    github: GitHub | None,
    target: Platform,
) -> None:
    """Add the ``github:`` backend to ``findings`` when its step passes.

    A failed probe or an unreachable GitHub is recorded as a skipped step.
    """
    backend = f"github:{repository.shorthand}"
    if github is None or backend in findings.backends:
        return
    try:
        reasons, why_not = _github_release(repository, mise, github, target)
    except (GitHubUnavailableError, MiseError) as error:
        findings.skipped["github:"] = error
        return
    if reasons:
        findings.backends[backend] = reasons
    else:
        findings.exclusions.append(Exclusion(backend, why_not))


def _run_detectors(
    repository: Repository,
    github: GitHub,
    target: Platform,
    ecosystems: Sequence[Ecosystem],
) -> tuple[list[tuple[Ecosystem, Detection]], GitHubUnavailableError | None]:
    """Run each detector, surviving a GitHub failure in any of them.

    Returns:
        tuple[list[tuple[Ecosystem, Detection]], GitHubUnavailableError | None]:
            The detections that completed and the last failure, if any.
    """
    outcomes = [
        (ecosystem, _detect_one(ecosystem, repository, github, target))
        for ecosystem in ecosystems
    ]
    results = [
        (ecosystem, detection)
        for ecosystem, outcome in outcomes
        if not isinstance(outcome, GitHubUnavailableError)
        for detection in outcome
    ]
    failures = [
        outcome
        for _, outcome in outcomes
        if isinstance(outcome, GitHubUnavailableError)
    ]
    return results, failures[-1] if failures else None


def _detect_one(
    ecosystem: Ecosystem, repository: Repository, github: GitHub, target: Platform
) -> tuple[Detection, ...] | GitHubUnavailableError:
    """Run one detector, returning a GitHub failure instead of raising it.

    Returns:
        tuple[Detection, ...] | GitHubUnavailableError: The detections (one
            per entrypoint for a multi-entrypoint repository) or the failure.
    """
    try:
        detected = ecosystem.detect(repository, github, target)
    except GitHubUnavailableError as error:
        return error
    return (detected,) if isinstance(detected, Detection) else tuple(detected)


def _primary_language(
    repository: Repository, github: GitHub
) -> tuple[str | None, GitHubUnavailableError | None]:
    """Read the primary language from GitHub, tolerating a GitHub failure.

    Returns:
        tuple[str | None, GitHubUnavailableError | None]: The language, or
            ``None`` with the failure.
    """
    try:
        return github.primary_language(repository), None
    except GitHubUnavailableError as error:
        return None, error


def _offer(
    backends: dict[str, list[str]], detections: list[tuple[Ecosystem, Detection]]
) -> None:
    """Add the detected backends and the reasons their entrypoints were found."""
    for _, detection in detections:
        backends.setdefault(detection.backend_string, []).append(detection.reason)


def _add_language_packages(
    findings: _Findings,
    repository: Repository,
    github: GitHub | None,
    target: Platform,
    ecosystems: Sequence[Ecosystem],
) -> tuple[Exclusion, ...]:
    """Add the language-package backends whose ecosystem finds an entrypoint.

    A GitHub failure is recorded as a skipped step.

    Returns:
        tuple[Exclusion, ...]: The ecosystems that found nothing, with why.
    """
    if github is None:
        return ()
    results, failure = _run_detectors(repository, github, target, ecosystems)
    _offer(findings.backends, [(ecosystem, d) for ecosystem, d in results if d.found])
    for _, detection in results:
        findings.notes.extend(n for n in detection.notes if n not in findings.notes)
    undetected = tuple(
        Exclusion(d.backend_string, d.reason) for _, d in results if not d.found
    )
    if failure is not None:
        findings.skipped["language-package"] = failure
    return undetected


def _is_favoured(
    backend_string: str, ecosystems: Sequence[Ecosystem], language: str | None
) -> bool:
    """Whether ``language`` makes ``backend_string``'s ecosystem the natural fit.

    Returns:
        bool: ``True`` for a language-package backend favoured by ``language``.
    """
    backend = backend_string.partition(":")[0]
    return any(
        eco.backend == backend and eco.favoured_by(language) for eco in ecosystems
    )


def _lookup_language(
    findings: _Findings,
    repository: Repository,
    github: GitHub | None,
    ecosystems: Sequence[Ecosystem],
) -> str | None:
    """Read the primary language from GitHub when language packages compete for a tier.

    The lookup is skipped when fewer than two language-package candidates were
    found, since there is nothing to order. A GitHub failure is recorded as a
    skipped step.

    Returns:
        str | None: The language, or ``None`` when not needed or unavailable.
    """
    names = {eco.backend for eco in ecosystems}
    packages = [b for b in findings.backends if b.partition(":")[0] in names]
    if github is None or len(packages) < _MIN_TIED:
        return None
    language, failure = _primary_language(repository, github)
    if failure is not None:
        _ = findings.skipped.setdefault("language-package", failure)
    return language


def _rank(
    backends: dict[str, list[str]],
    target: Platform,
    ecosystems: Sequence[Ecosystem],
    language: str | None,
) -> tuple[tuple[Candidate, ...], tuple[Exclusion, ...]]:
    """Tier, flag and sort the backends, dropping those unusable on ``target``.

    Within a tier, the primary language's backend comes first and the rest
    follow alphabetically by backend string, so the order is deterministic.

    Returns:
        tuple[tuple[Candidate, ...], tuple[Exclusion, ...]]: The candidates,
            best first, and the exclusions.
    """
    candidates: list[Candidate] = []
    exclusions: list[Exclusion] = []
    for backend, found_reasons in backends.items():
        reasons = list(found_reasons)
        if _is_favoured(backend, ecosystems, language):
            reasons.append(f"{language} is the repository's primary language")
        candidate = _candidate(backend, reasons)
        why_not = _unusable_reason(candidate, target)
        if why_not is None:
            candidates.append(candidate)
        else:
            exclusions.append(Exclusion(backend, why_not))
    candidates.sort(
        key=lambda c: (
            c.tier,
            not _is_favoured(c.backend_string, ecosystems, language),
            c.backend_string,
        )
    )
    return tuple(candidates), tuple(exclusions)


class _Gathered(NamedTuple):
    """The outcome of the ladder's steps.

    Attributes:
        candidates: The ranked candidates, best first.
        exclusions: The backend strings considered and left out.
        skipped: The failure of each skipped step, by step name.
        notes: Remarks from detectors about their own search.
    """

    candidates: tuple[Candidate, ...]
    exclusions: tuple[Exclusion, ...]
    skipped: dict[str, MibareError]
    notes: tuple[str, ...] = ()


def _gather(
    repository: Repository,
    mise: Mise,
    github: GitHub | None,
    target: Platform,
    ecosystems: Sequence[Ecosystem],
) -> _Gathered:
    """Run the ladder's steps and rank what they found.

    Returns:
        _Gathered: The candidates, the exclusions and the skipped steps.
    """
    findings = _found_backends(repository, mise)
    _add_github(findings, repository, mise, github, target)
    undetected = _add_language_packages(
        findings, repository, github, target, ecosystems
    )
    language = _lookup_language(findings, repository, github, ecosystems)
    candidates, unusable = _rank(findings.backends, target, ecosystems, language)
    exclusions = (*findings.exclusions, *unusable, *undetected)
    return _Gathered(candidates, exclusions, findings.skipped, tuple(findings.notes))


def _notes(
    target: Platform, host: Platform | None, gathered: _Gathered
) -> tuple[str, ...]:
    """Collect the platform, skipped-step and search notes.

    Returns:
        tuple[str, ...]: The notes, in that order.
    """
    skipped = tuple(
        f"Skipped the {step} step: {why}" for step, why in gathered.skipped.items()
    )
    return (*_platform_notes(target, host), *skipped, *gathered.notes)


def _try_host_platform() -> Platform | None:
    """Detect the host platform for the host-versus-target note.

    Returns:
        Platform | None: The host, or ``None`` when it cannot be detected.
    """
    try:
        return host_platform()
    except InvalidPlatformError:
        return None


def resolve(
    repository: str,
    mise: Mise,
    platform: Platform | None = None,
    github: GitHub | None = None,
    ecosystems: Sequence[Ecosystem] = ECOSYSTEMS,
) -> Resolution:
    """Resolve ``repository`` to the mise backends that can install it.

    Args:
        repository: A GitHub URL or ``owner/repo`` shorthand.
        mise: The mise adapter.
        platform: The target platform; defaults to the host.
        github: The GitHub adapter. Without one the steps that need the GitHub
            API are left out, so ``resolve()`` stays offline.
        ecosystems: The language-package ecosystems to detect; defaults to
            the registered ones.

    Returns:
        Resolution: The ranked candidates; the first is the recommendation.
            When GitHub is unreachable or a mise probe fails, the other
            candidates are kept and the skipped steps are named in ``notes``.

        The first failure (``GitHubUnavailableError`` or ``MiseError``) is
        raised instead when a step failed and no step found a candidate, so
        the answer does not read as "no backend".

        An ``InvalidPlatformError`` is raised when no ``platform`` is given
        and the host is not a supported platform; an explicit ``platform``
        needs no host detection.
    """
    parsed = parse_repository(repository)
    if platform is None:
        target = host_platform()
        host: Platform | None = target
    else:
        host, target = _try_host_platform(), platform
    mise_version = mise.version()
    gathered = _gather(parsed, mise, github, target, ecosystems)
    candidates, exclusions, skipped, _ = gathered
    if not candidates and skipped:
        failure = next(iter(skipped.values()))
        raise failure
    notes = _notes(target, host, gathered)
    return Resolution(parsed, mise_version, candidates, exclusions, target, notes)
