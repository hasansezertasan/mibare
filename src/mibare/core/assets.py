"""Match release asset names to a target platform.

The matcher is deliberately simple and deterministic. A name is lower-cased and
split into tokens at every character that is not a letter or digit, after a few
multi-part spellings are joined (``x86_64``, ``x86-64``, ``aarch_64``,
``64bit``). An asset matches when:

* its tokens name the target OS, and no other OS;
* its tokens name the target architecture, and no other one (a macOS asset
  tagged ``universal`` or ``universal2`` counts for either architecture);
* it is not a checksum, signature, metadata or system package file.

Both an OS and an architecture are required, so ``tool-linux.tar.gz`` does not
match. Accepted spellings:

* linux: ``linux``, ``linux64``
* macos: ``macos``, ``macosx``, ``darwin``, ``osx``, ``apple``, ``mac``
* windows: ``windows``, ``win``, ``win32``, ``win64``
* x64: ``x64``, ``x86_64``, ``amd64``, ``64bit``, ``linux64``, ``win64``
* arm64: ``arm64``, ``aarch64``, ``armv8``
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mibare.core.platform import Platform

__all__ = ["matching_assets"]

_OS_TOKENS = {
    "linux": {"linux", "linux64"},
    "macos": {"macos", "macosx", "darwin", "osx", "apple", "mac"},
    "windows": {"windows", "win", "win32", "win64"},
}
_ARCH_TOKENS = {
    "x64": {"x64", "amd64", "linux64", "win64"},
    "arm64": {"arm64", "aarch64", "armv8"},
}
_UNIVERSAL = {"universal", "universal2"}
_IGNORED_SUFFIXES = (
    ".sha256",
    ".sha256sum",
    ".sha512",
    ".sha1",
    ".md5",
    ".sig",
    ".asc",
    ".pem",
    ".minisig",
    ".sbom",
    ".json",
    ".jsonl",
    ".txt",
    ".md",
    ".deb",
    ".rpm",
    ".apk",
)
_JOINED_SPELLINGS = (
    (re.compile(r"x86[-_]64"), "x64"),
    (re.compile(r"aarch[-_]64"), "aarch64"),
    (re.compile(r"(?<![a-z0-9])64[-_]?bit"), "x64"),
)


def _tokens(name: str) -> set[str]:
    """Split an asset name into lower-case tokens, joining split spellings.

    Returns:
        set[str]: The tokens of ``name``.
    """
    text = name.lower()
    for pattern, replacement in _JOINED_SPELLINGS:
        text = pattern.sub(replacement, text)
    return {token for token in re.split(r"[^a-z0-9]+", text) if token}


def _names(tokens: set[str], table: dict[str, set[str]]) -> set[str]:
    """Say which keys of ``table`` have an alias among ``tokens``.

    Returns:
        set[str]: The matched keys.
    """
    return {key for key, aliases in table.items() if tokens & aliases}


def _matches(name: str, platform: Platform) -> bool:
    """Say whether one asset name is a download for ``platform``.

    Returns:
        bool: ``True`` when the name matches under the rules in the module doc.
    """
    if name.lower().endswith(_IGNORED_SUFFIXES):
        return False
    tokens = _tokens(name)
    if _names(tokens, _OS_TOKENS) != {platform.os}:
        return False
    arches = _names(tokens, _ARCH_TOKENS)
    if platform.os == "macos" and tokens & _UNIVERSAL and not arches:
        return True
    return arches == {platform.arch}


def matching_assets(names: Iterable[str], platform: Platform) -> tuple[str, ...]:
    """Pick the asset names that are downloads for ``platform``.

    Args:
        names: Release asset names.
        platform: The target platform.

    Returns:
        tuple[str, ...]: The matching names, in the order given.
    """
    return tuple(name for name in names if _matches(name, platform))
