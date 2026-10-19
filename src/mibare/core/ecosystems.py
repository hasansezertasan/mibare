"""Language-package ecosystems: how a repository earns a ``pypi:``-style candidate.

Each ecosystem is one :class:`Ecosystem` in :data:`ECOSYSTEMS`. To add one,
write a detector with the :data:`Detector` signature and add one line to
:data:`ECOSYSTEMS`; ``resolve()`` handles the tier, the primary-language
tie-break and the reasons.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from mibare.core.detection import Detection
from mibare.core.go_entrypoints import detect_go

if sys.version_info >= (3, 11):
    import tomllib  # pyright: ignore[reportUnreachable]
else:
    import tomli as tomllib

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mibare.core.github import GitHub
    from mibare.core.platform import Platform
    from mibare.core.repository import Repository

__all__ = [
    "CARGO",
    "ECOSYSTEMS",
    "GO",
    "NPM",
    "PYPI",
    "Detection",
    "Detector",
    "Ecosystem",
]


class Detector(Protocol):
    """Looks at a repository's root manifest for an entrypoint.

    ``platform`` is the target platform, for detectors whose answer depends on
    it (Go leaves files out of a build by operating system and architecture).
    It may raise ``GitHubUnavailableError``, which ``resolve()`` turns into a
    skipped-step note.
    """

    def __call__(
        self, repository: Repository, github: GitHub, platform: Platform
    ) -> Detection | Sequence[Detection]:
        """Return the detection for ``repository``, or one per entrypoint."""
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


def _detect_python(
    repository: Repository, github: GitHub, platform: Platform
) -> Detection:
    """Look for ``[project.scripts]`` in the root ``pyproject.toml``.

    Returns:
        Detection: ``found`` when at least one script is declared.
    """
    del platform
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


def _autobins_disabled(manifest: dict[str, object]) -> bool:
    """Say whether ``Cargo.toml`` turns off bin-target auto-discovery.

    Args:
        manifest: The parsed ``Cargo.toml``, which has a ``[package]`` table.

    Returns:
        bool: ``True`` when ``[package] autobins`` is ``false``.
    """
    package = cast("dict[str, object]", manifest["package"])
    return package.get("autobins") is False


def _strings(value: object) -> list[str]:
    """Pick the string items of a TOML array.

    Returns:
        list[str]: The strings, or nothing for any other value.
    """
    if not isinstance(value, list):
        return []
    return [item for item in cast("list[object]", value) if isinstance(item, str)]


def _declared_bins(manifest: dict[str, object]) -> list[dict[str, object]]:
    """Pick the ``[[bin]]`` tables of ``Cargo.toml``.

    Returns:
        list[dict[str, object]]: The tables; empty when none are declared.
    """
    bins = manifest.get("bin")
    if not isinstance(bins, list):
        return []
    return [
        cast("dict[str, object]", table)
        for table in cast("list[object]", bins)
        if isinstance(table, dict)
    ]


def _default_features(manifest: dict[str, object]) -> set[str]:
    """Compute the features ``cargo install`` enables by default.

    Starts from ``[features].default`` and follows feature-to-feature
    references transitively. A ``pkg/feat`` entry enables the optional
    dependency ``pkg`` (so the implicit feature of that name); the weak
    ``pkg?/feat`` and ``dep:pkg`` forms do not.

    Returns:
        set[str]: The enabled feature names.
    """
    table = manifest.get("features")
    features = cast("dict[str, object]", table) if isinstance(table, dict) else {}
    enabled: set[str] = set()
    pending = _strings(features.get("default"))
    while pending:
        item = pending.pop()
        if item.startswith("dep:") or "?/" in item:
            continue
        name = item.partition("/")[0]
        if name not in enabled:
            enabled.add(name)
            pending.extend(_strings(features.get(name)))
    return enabled


def _gated_bins(
    manifest: dict[str, object], bins: list[dict[str, object]]
) -> list[str]:
    """Describe the bins whose required features the defaults leave off.

    Returns:
        list[str]: One ``name needs feature, ...`` line per skipped bin.
    """
    enabled = _default_features(manifest)
    gated: list[str] = []
    for table in bins:
        missing = [
            feature
            for feature in _strings(table.get("required-features"))
            if feature not in enabled
        ]
        if missing:
            name = table.get("name")
            label = name if isinstance(name, str) else "unnamed"
            gated.append(f"{label} requires {', '.join(missing)}")
    return gated


def _cargo_bin_detection(
    manifest: dict[str, object], repository: Repository, github: GitHub
) -> Detection:
    """Decide from a parsed ``Cargo.toml`` whether the crate has a bin target.

    Args:
        manifest: The parsed ``Cargo.toml``.
        repository: The repository being resolved.
        github: The GitHub adapter, for ``src/main.rs``.

    Returns:
        Detection: ``found`` when the crate has a bin target.
    """
    backend_string = f"cargo:{repository.shorthand}"
    bins = _declared_bins(manifest)
    gated = _gated_bins(manifest, bins)
    if bins and len(gated) < len(bins):
        return Detection(backend_string, "Cargo.toml declares a [[bin]] target")
    if _autobins_disabled(manifest) or _shadows_default_bin(manifest, bins):
        reason = _no_bin_reason(bins, gated)
        return Detection(backend_string, reason, found=False)
    if github.root_file(repository, "src/main.rs") is not None:
        return Detection(backend_string, "the crate has a src/main.rs bin target")
    reason = "Cargo.toml declares no [[bin]] target and there is no src/main.rs"
    if bins:
        reason = f"{_no_bin_reason(bins, gated)}, and there is no src/main.rs"
    return Detection(backend_string, reason, found=False)


def _shadows_default_bin(
    manifest: dict[str, object], bins: list[dict[str, object]]
) -> bool:
    """Say whether a declared bin replaces the default ``src/main.rs`` bin.

    Cargo names the default bin after the package, and a declared ``[[bin]]``
    of the same name takes its place.

    Returns:
        bool: ``True`` when a declared bin has the package's name.
    """
    package = manifest.get("package")
    name = (
        cast("dict[str, object]", package).get("name")
        if isinstance(package, dict)
        else None
    )
    return any(table.get("name") == name for table in bins)


def _no_bin_reason(bins: list[dict[str, object]], gated: list[str]) -> str:
    """Explain why the declared bins, or the lack of them, give no bin target.

    Returns:
        str: The reason, without a trailing period.
    """
    if not bins:
        return (
            "Cargo.toml sets autobins = false and declares no [[bin]] target, "
            "so src/main.rs is not a bin target"
        )
    return (
        "every [[bin]] target in Cargo.toml has required-features that "
        f"the default features do not enable ({'; '.join(gated)}), so "
        "cargo install skips it"
    )


def _detect_cargo(
    repository: Repository, github: GitHub, platform: Platform
) -> Detection:
    """Look for a ``[[bin]]`` table or a ``src/main.rs`` beside ``Cargo.toml``.

    Returns:
        Detection: ``found`` when the crate has a bin target.
    """
    del platform
    backend_string = f"cargo:{repository.shorthand}"
    text = github.root_file(repository, "Cargo.toml")
    if text is None:
        reason = "no Cargo.toml in the repository root"
        return Detection(backend_string, reason, found=False)
    try:
        manifest = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        reason = "Cargo.toml in the repository root is not valid TOML"
        return Detection(backend_string, reason, found=False)
    if not isinstance(manifest.get("package"), dict):
        reason = "the root Cargo.toml is a virtual workspace with no [package]"
        return Detection(backend_string, reason, found=False)
    return _cargo_bin_detection(manifest, repository, github)


def _detect_npm(
    repository: Repository, github: GitHub, platform: Platform
) -> Detection:
    """Look for a non-empty ``bin`` in the root ``package.json``.

    Returns:
        Detection: ``found`` when ``bin`` is a non-empty string or object.
    """
    del platform
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
GO = Ecosystem("go", frozenset({"Go"}), detect_go)

#: The registered ecosystems. Add a line here to support another one.
ECOSYSTEMS: tuple[Ecosystem, ...] = (PYPI, CARGO, NPM, GO)
