"""Resolve a repository to a ranked list of mise backend candidates."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mibare.core.assets import matching_assets
from mibare.core.ecosystems import ECOSYSTEMS, Detection, Ecosystem
from mibare.core.errors import GitHubUnavailableError, MibareError, MiseError
from mibare.core.platform import Platform, host_platform
from mibare.core.repository import Repository, parse_repository

if TYPE_CHECKING:
    from collections.abc import Sequence

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


@dataclass
class _Findings:
    """What the ladder's steps have found so far.

    Attributes:
        backends: Each backend string found, with the reasons it was found,
            in discovery order.
        exclusions: The backend strings a step considered and left out, each
            with the reason.
        skipped: The failure of each skipped step, by step name.
    """

    backends: dict[str, list[str]] = field(default_factory=dict)
    exclusions: list[Exclusion] = field(default_factory=list)
    skipped: dict[str, MibareError] = field(default_factory=dict)


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
    found = findings.backends
    for entry in mise.registry():
        if any(_points_at(repository, backend) for backend in entry.backends):
            reason = f"listed in the mise registry as {entry.tool!r}"
            for backend in entry.backends:
                found.setdefault(backend, []).append(reason)
            break
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
    repository: Repository, github: GitHub, ecosystems: Sequence[Ecosystem]
) -> tuple[list[tuple[Ecosystem, Detection]], GitHubUnavailableError | None]:
    """Run each detector, surviving a GitHub failure in any of them.

    Returns:
        tuple[list[tuple[Ecosystem, Detection]], GitHubUnavailableError | None]:
            The detections that completed and the last failure, if any.
    """
    outcomes = [(eco, _detect_one(eco, repository, github)) for eco in ecosystems]
    results = [
        (eco, detection)
        for eco, o in outcomes
        if not isinstance(o, GitHubUnavailableError)
        for detection in o
    ]
    failures = [o for _, o in outcomes if isinstance(o, GitHubUnavailableError)]
    return results, failures[-1] if failures else None


def _detect_one(
    ecosystem: Ecosystem, repository: Repository, github: GitHub
) -> tuple[Detection, ...] | GitHubUnavailableError:
    """Run one detector, returning a GitHub failure instead of raising it.

    Returns:
        tuple[Detection, ...] | GitHubUnavailableError: The detections (one
            per binary for a multi-binary repository) or the failure.
    """
    try:
        detected = ecosystem.detect(repository, github)
    except GitHubUnavailableError as error:
        return error
    return (detected,) if isinstance(detected, Detection) else tuple(detected)


def _primary_language(
    repository: Repository, github: GitHub
) -> tuple[str | None, GitHubUnavailableError | None]:
    """Look up the primary language, tolerating a GitHub failure.

    Returns:
        tuple[str | None, GitHubUnavailableError | None]: The language, or
            ``None`` with the failure.
    """
    try:
        return github.primary_language(repository), None
    except GitHubUnavailableError as error:
        return None, error


def _offer(
    found: dict[str, list[str]],
    hits: list[tuple[Ecosystem, Detection]],
    language: str | None,
) -> None:
    """Add the detected backends: primary language's first, then alphabetical.

    ``found`` keeps insertion order and ranking is a stable sort by tier, so
    this order is the tie-break among language packages.
    """
    hits.sort(key=lambda hit: (not hit[0].favoured_by(language), hit[1].backend_string))
    for ecosystem, detection in hits:
        reasons = found.setdefault(detection.backend_string, [])
        reasons.append(detection.reason)
        if ecosystem.favoured_by(language):
            reasons.append(f"{language} is the repository's primary language")


def _add_language_packages(
    findings: _Findings,
    repository: Repository,
    github: GitHub | None,
    ecosystems: Sequence[Ecosystem],
) -> tuple[Exclusion, ...]:
    """Add the language-package backends whose ecosystem finds an entrypoint.

    The primary language's backend is added first and the others follow
    alphabetically by backend string, so ranking (a stable sort by tier) keeps
    that order.

    A GitHub failure is recorded as a skipped step.

    Returns:
        tuple[Exclusion, ...]: The ecosystems that found nothing, with why.
    """
    if github is None:
        return ()
    results, failure = _run_detectors(repository, github, ecosystems)
    hits = [(eco, d) for eco, d in results if d.found]
    language = None
    if len(hits) > 1:
        language, language_failure = _primary_language(repository, github)
        failure = failure or language_failure
    _offer(findings.backends, hits, language)
    misses = tuple(
        Exclusion(d.backend_string, d.reason) for _, d in results if not d.found
    )
    if failure is not None:
        findings.skipped["language-package"] = failure
    return misses


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


def _gather(
    repository: Repository,
    mise: Mise,
    github: GitHub | None,
    target: Platform,
    ecosystems: Sequence[Ecosystem],
) -> tuple[tuple[Candidate, ...], tuple[Exclusion, ...], dict[str, MibareError]]:
    """Run the ladder's steps and rank what they found.

    Returns:
        tuple: The candidates, the exclusions and the failure of each skipped
            step by step name.
    """
    findings = _found_backends(repository, mise)
    _add_github(findings, repository, mise, github, target)
    misses = _add_language_packages(findings, repository, github, ecosystems)
    candidates, unusable = _rank(findings.backends, target)
    exclusions = (*findings.exclusions, *unusable, *misses)
    return candidates, exclusions, findings.skipped


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
    """
    parsed = parse_repository(repository)
    host = host_platform()
    target = platform or host
    mise_version = mise.version()
    candidates, exclusions, skipped = _gather(parsed, mise, github, target, ecosystems)
    if not candidates and skipped:
        failure = next(iter(skipped.values()))
        raise failure
    skipped_notes = tuple(
        f"Skipped the {step} step: {why}" for step, why in skipped.items()
    )
    notes = (*_platform_notes(target, host), *skipped_notes)
    return Resolution(parsed, mise_version, candidates, exclusions, target, notes)
