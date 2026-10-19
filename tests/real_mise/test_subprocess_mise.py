"""Check that ``SubprocessMise`` still matches the real ``mise`` binary.

Deselected by default; run with ``pytest -m real_mise`` (see CONTRIBUTING.md).
"""

from __future__ import annotations

import re
from functools import cache

import pytest

from mibare.core.mise import MIN_MISE_VERSION, RegistryEntry, SubprocessMise

pytestmark = pytest.mark.real_mise


@cache
def _registry() -> tuple[RegistryEntry, ...]:
    """Return the registry as listed by the real mise, fetched once.

    A plain cached function rather than a fixture: ``--dead-fixtures`` sees no
    user of a fixture whose tests are deselected by default.
    """
    return SubprocessMise().registry()


def test_version_is_detected_and_meets_the_minimum() -> None:
    """Detect a dotted version no older than the minimum."""
    version = SubprocessMise().version()

    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert tuple(int(part) for part in version.split(".")) >= MIN_MISE_VERSION


def test_registry_listing_has_the_expected_shape() -> None:
    """List many entries, each with a tool and prefixed backend strings."""
    registry = _registry()
    assert len(registry) > 100
    assert all(isinstance(entry, RegistryEntry) for entry in registry)
    assert all(entry.tool for entry in registry)
    assert all(
        entry.backends and all(":" in backend for backend in entry.backends)
        for entry in registry
    )


def test_registry_lists_a_well_known_tool_with_its_aqua_backend() -> None:
    """List ripgrep with its aqua backend."""
    by_tool = {entry.tool: entry for entry in _registry()}

    assert "aqua:BurntSushi/ripgrep" in by_tool["ripgrep"].backends


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("MISE_DISABLE_BACKENDS", "aqua"),
        ("MISE_DISABLE_TOOLS", "ripgrep"),
        ("MISE_ENABLE_TOOLS", "node"),
    ],
)
def test_user_mise_settings_do_not_change_the_registry(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    """Ignore user settings in the caller's environment."""
    monkeypatch.setenv(variable, value)

    assert SubprocessMise().registry() == _registry()


@pytest.mark.skip(
    reason="Pending the existence probe on SubprocessMise (ticket #5); enable "
    "once it lands: known-present aqua:BurntSushi/ripgrep, known-absent "
    "aqua:mibare-nonexistent/nonexistent."
)
def test_existence_probe_tells_a_present_backend_from_an_absent_one() -> None:
    """Tell a present backend from an absent one."""
    raise NotImplementedError
