"""Pytest configuration shared across the test suite.

Auto-applies a per-component marker to each test based on its top-level
``tests/<dir>/`` directory, so ``pytest -m web`` (or ``-m "not web"``) selects a
component without per-test decoration. Markers are registered in pyproject.toml
``[tool.pytest.ini_options] markers``. See issue #160 / https://hasansezertasan.github.io/copier-pyproject/context/ci-topology/#per-component-markers-path-filtered-jobs-and-one-coverage-gate-per-component.

Also keeps the Markdown doctest surface to the single root ``README.md``: see
``collect_ignore_glob`` below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mibare.core.platform import Platform

# ``--doctest-glob=README.md`` (pyproject ``addopts``) matches on the *basename*,
# so without this every ``tests/**/README.md`` -- fixture notes, a subdirectory
# guide -- would also be collected as a doctest the moment it contained a ``>>>``
# line. The root README is the whole Markdown doctest surface (https://hasansezertasan.github.io/copier-pyproject/context/docs-stack/#documentation-code-examples-are-executed-not-pasted);
# prose
# under tests/ stays prose.
collect_ignore_glob = ["*.md"]


# tests/<dir> names that map to a component marker, rendered from the enabled
# components. An unmarked dir (e.g. a future one) is simply left unmarked.
# `# fmt: off` keeps this one-per-line no matter how many components are enabled:
# the generated ruff config sets skip-magic-trailing-comma, so an unguarded set
# literal would otherwise collapse or explode purely by line width.
# fmt: off
_COMPONENT_DIRS: frozenset[str] = frozenset({
    "core",
    "cli",
})
# fmt: on


def _real_mise_requested(config: pytest.Config) -> bool:
    """Say whether the ``-m`` expression names ``real_mise`` without negating it."""
    expression = str(config.getoption("markexpr") or "")
    return re.search(r"(?<!not )\breal_mise\b", expression) is not None


def _skip_real_mise_unless_requested(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip the opt-in real-mise tests unless ``-m`` asks for them.

    They are skipped here rather than deselected through ``addopts``, because any
    ``-m`` given on the command line (CI passes one) replaces an ``addopts`` ``-m``
    and would silently run them.
    """
    if _real_mise_requested(config):  # pragma: no cover - only the opt-in run
        return
    skip = pytest.mark.skip(reason="opt-in: run with `pytest -m real_mise`")
    for item in items:
        if item.get_closest_marker("real_mise"):
            item.add_marker(skip)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip opt-in tests, then mark each test with its component name."""
    _skip_real_mise_unless_requested(config, items)
    tests_root = Path(str(config.rootpath)) / "tests"
    for item in items:
        try:
            rel = item.path.relative_to(tests_root)
        except ValueError:  # pragma: no cover - defensive: items are under tests/
            continue
        component = rel.parts[0] if len(rel.parts) > 1 else "core"
        if component in _COMPONENT_DIRS:
            item.add_marker(component)


@pytest.fixture(autouse=True)
def _pin_host_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the host platform so resolution never depends on the runner's OS.

    ``resolve()`` defaults its target to the real host, and some backends (asdf)
    are excluded on a Windows target, so an unpinned host changes the candidates.
    Tests that need another host patch the same name later and win.
    """
    monkeypatch.setattr(
        "mibare.core.resolve.host_platform", lambda: Platform("linux", "x64")
    )
