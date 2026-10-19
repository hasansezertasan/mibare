"""Tests for host platform detection."""

from __future__ import annotations

import pytest

from mibare.core.errors import InvalidPlatformError
from mibare.core.platform import Platform, host_platform


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Linux", "x86_64", Platform("linux", "x64")),
        ("Darwin", "arm64", Platform("macos", "arm64")),
        ("Windows", "AMD64", Platform("windows", "x64")),
        ("Linux", "aarch64", Platform("linux", "arm64")),
    ],
)
def test_the_host_is_read_from_the_system_and_machine(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str, expected: Platform
) -> None:
    """Python's system and machine names map to mibare's platform names."""
    monkeypatch.setattr("platform.system", lambda: system)
    monkeypatch.setattr("platform.machine", lambda: machine)

    assert host_platform() == expected


@pytest.mark.parametrize(
    ("system", "machine"), [("FreeBSD", "x86_64"), ("Linux", "riscv64")]
)
def test_an_unsupported_host_asks_for_an_explicit_platform(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str
) -> None:
    """A host mibare does not know raises and points at ``--platform``."""
    monkeypatch.setattr("platform.system", lambda: system)
    monkeypatch.setattr("platform.machine", lambda: machine)

    with pytest.raises(InvalidPlatformError, match="--platform"):
        _ = host_platform()
