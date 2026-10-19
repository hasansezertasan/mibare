"""Language-package ecosystems: how a repository earns a ``pypi:``-style candidate.

Each ecosystem is one :class:`Ecosystem` in :data:`ECOSYSTEMS`. To add one,
write a detector with the :data:`Detector` signature and add one line to
:data:`ECOSYSTEMS`; ``resolve()`` handles the tier, the primary-language
tie-break and the reasons.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from mibare.core.detection import Detection
from mibare.core.go_entrypoints import detect_go

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mibare.core.github import GitHub
    from mibare.core.platform import Platform
    from mibare.core.repository import Repository

_SRC_BIN_FILE_DEPTH = 3  # src/bin/<name>.rs
_SRC_BIN_DIR_DEPTH = 4  # src/bin/<name>/main.rs
_TRUNCATED_NOTE = (
    "The Cargo search was limited: GitHub truncated the repository file "
    "listing, so a src/bin target may have been missed."
)

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


def _src_bin_names(
    repository: Repository, github: GitHub, declared: set[str]
) -> tuple[list[str], bool]:
    """Find the bins Cargo auto-discovers under ``src/bin``.

    Cargo builds ``src/bin/<name>.rs`` and ``src/bin/<name>/main.rs`` as bins,
    except where a declared ``[[bin]]`` of the same name takes their place. The
    repository listing is the one the Go step uses, and the GitHub adapter
    keeps it, so reading it here costs no second request.

    Args:
        repository: The repository being resolved.
        github: The GitHub adapter, for the file listing.
        declared: The names of the declared ``[[bin]]`` tables.

    Returns:
        tuple[list[str], bool]: The discovered bin names, sorted, and whether
            GitHub truncated the listing.
    """
    listing = github.list_files(repository)
    names: set[str] = set()
    for path in listing.paths:
        parts = path.split("/")
        if parts[:2] != ["src", "bin"]:
            continue
        if len(parts) == _SRC_BIN_FILE_DEPTH and parts[2].endswith(".rs"):
            names.add(parts[2].removesuffix(".rs"))
        elif len(parts) == _SRC_BIN_DIR_DEPTH and parts[3] == "main.rs":
            names.add(parts[2])
    names.discard("")
    return sorted(names - declared), listing.truncated


def _declared_names(bins: list[dict[str, object]]) -> set[str]:
    """Pick the names of the declared ``[[bin]]`` tables.

    Returns:
        set[str]: The names that are strings.
    """
    return {name for table in bins if isinstance(name := table.get("name"), str)}


def _cargo_bin_detection(
    manifest: dict[str, object], repository: Repository, github: GitHub
) -> Detection:
    """Decide from a parsed ``Cargo.toml`` whether the crate has a bin target.

    Args:
        manifest: The parsed ``Cargo.toml``.
        repository: The repository being resolved.
        github: The GitHub adapter, for ``src/main.rs`` and the file listing.

    Returns:
        Detection: ``found`` when the crate has a bin target.
    """
    backend_string = f"cargo:{repository.shorthand}"
    bins = _declared_bins(manifest)
    gated = _gated_bins(manifest, bins)
    if bins and len(gated) < len(bins):
        return Detection(backend_string, "Cargo.toml declares a [[bin]] target")
    if _autobins_disabled(manifest):
        return Detection(backend_string, _no_bin_reason(bins, gated), found=False)
    shadowed = _shadows_default_bin(manifest, bins)
    if not shadowed and github.root_file(repository, "src/main.rs") is not None:
        return Detection(backend_string, "the crate has a src/main.rs bin target")
    names, truncated = _src_bin_names(repository, github, _declared_names(bins))
    if names:
        reason = f"the crate has a src/bin target: {', '.join(names)}"
        return Detection(backend_string, reason)
    reason = _nothing_found_reason(bins, gated, shadowed=shadowed)
    notes = (_TRUNCATED_NOTE,) if truncated else ()
    return Detection(backend_string, reason, found=False, notes=notes)


def _nothing_found_reason(
    bins: list[dict[str, object]], gated: list[str], *, shadowed: bool
) -> str:
    """Explain why auto-discovery found no bin target either.

    Returns:
        str: The reason, without a trailing period.
    """
    reason = (
        _no_bin_reason(bins, gated) if bins else "Cargo.toml declares no [[bin]] target"
    )
    if shadowed:
        return reason
    return f"{reason}, and there is no src/main.rs or src/bin target"


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
            "so src/main.rs and src/bin are not bin targets"
        )
    return (
        "every [[bin]] target in Cargo.toml has required-features that "
        f"the default features do not enable ({'; '.join(gated)}), so "
        "cargo install skips it"
    )


def _detect_cargo(
    repository: Repository, github: GitHub, platform: Platform
) -> Detection:
    """Look for a ``[[bin]]`` table, ``src/main.rs`` or ``src/bin`` bin target.

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


#: mibare's platform names as ``process.platform`` and ``process.arch`` spell them.
_NPM_OS = {"linux": "linux", "macos": "darwin", "windows": "win32"}
_NPM_CPU = {"x64": "x64", "arm64": "arm64"}


def _npm_allows(value: object, actual: str) -> bool:
    """Apply an npm ``os`` or ``cpu`` list to one value, as npm does.

    Returns:
        bool: ``False`` when the list has allow entries and none match, or a
            ``!`` entry matches; ``True`` otherwise, and for a list that is not
            made of strings.
    """
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in cast("list[object]", value)
    ):
        return True
    entries = cast("list[str]", value)
    allowed = [entry for entry in entries if not entry.startswith("!")]
    denied = {entry[1:] for entry in entries if entry.startswith("!")}
    return actual not in denied and (not allowed or actual in allowed)


def _npm_excluded_by(manifest: dict[str, object], platform: Platform) -> str | None:
    """Find the ``package.json`` field that rules the target platform out.

    Returns:
        str | None: The reason naming the field and target, or ``None`` when
            ``os`` and ``cpu`` permit the target.
    """
    checks = (
        ("os", _NPM_OS[platform.os], platform.os),
        ("cpu", _NPM_CPU[platform.arch], platform.arch),
    )
    for field_name, actual, label in checks:
        if not _npm_allows(manifest.get(field_name), actual):
            return f'package.json "{field_name}" does not allow {label}'
    return None


def _detect_npm(
    repository: Repository, github: GitHub, platform: Platform
) -> Detection:
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
        excluded = _npm_excluded_by(cast("dict[str, object]", data), platform)
        if excluded is not None:
            return Detection(backend_string, excluded, found=False)
        return Detection(backend_string, "package.json declares a bin entrypoint")
    reason = "package.json declares no bin entrypoint"
    return Detection(backend_string, reason, found=False)


PYPI = Ecosystem("pypi", frozenset({"Python"}), _detect_python)
CARGO = Ecosystem("cargo", frozenset({"Rust"}), _detect_cargo)
NPM = Ecosystem("npm", frozenset({"JavaScript", "TypeScript"}), _detect_npm)
GO = Ecosystem("go", frozenset({"Go"}), detect_go)

#: The registered ecosystems. Add a line here to support another one.
ECOSYSTEMS: tuple[Ecosystem, ...] = (PYPI, CARGO, NPM, GO)
