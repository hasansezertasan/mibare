"""Tests for the Rust and npm ecosystems, through ``resolve()``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mibare.core.ecosystems import CARGO, ECOSYSTEMS, NPM, PYPI
from mibare.core.platform import Platform
from mibare.core.resolve import Resolution, resolve
from tests.fakes import FakeGitHub, FakeMise

if TYPE_CHECKING:
    from collections.abc import Mapping

LINUX_X64 = Platform("linux", "x64")
TOOL = "owner/tool"
CARGO_BIN = '[package]\nname = "tool"\n\n[[bin]]\nname = "tool"\npath = "src/x.rs"\n'
CARGO_LIB = '[package]\nname = "tool"\n'
PACKAGE_BIN_OBJECT = '{"name": "tool", "bin": {"tool": "cli.js"}}'
PACKAGE_BIN_STRING = '{"name": "tool", "bin": "cli.js"}'
PYPROJECT = '[project]\nname = "tool"\n\n[project.scripts]\ntool = "tool:main"\n'


def _resolve(files: Mapping[str, str], language: str | None = None) -> Resolution:
    github = FakeGitHub(files=files, language=language)
    return resolve(TOOL, FakeMise(), LINUX_X64, github=github)


def _backends(resolution: Resolution) -> list[str]:
    return [c.backend_string for c in resolution.candidates]


def _excluded(resolution: Resolution, backend_string: str) -> str:
    """Return the single exclusion reason recorded for ``backend_string``."""
    (reason,) = (
        x.reason for x in resolution.exclusions if x.backend_string == backend_string
    )
    return reason


def test_cargo_bin_table_gives_a_cargo_candidate() -> None:
    """A ``[[bin]]`` target resolves to ``cargo:owner/repo``."""
    resolution = _resolve({"Cargo.toml": CARGO_BIN})

    top = resolution.recommendation
    assert top is not None
    assert (top.backend_string, top.tier) == ("cargo:owner/tool", 4)
    assert any("[[bin]]" in reason for reason in top.reasons)


def test_src_main_rs_gives_a_cargo_candidate() -> None:
    """A ``src/main.rs`` without a ``[[bin]]`` table is still a bin target."""
    resolution = _resolve({"Cargo.toml": CARGO_LIB, "src/main.rs": "fn main() {}"})

    assert _backends(resolution) == ["cargo:owner/tool"]
    assert any("src/main.rs" in r for r in resolution.candidates[0].reasons)


def test_library_only_crate_gives_no_cargo_candidate() -> None:
    """A crate with neither ``[[bin]]`` nor ``src/main.rs`` is excluded."""
    resolution = _resolve({"Cargo.toml": CARGO_LIB, "src/lib.rs": ""})

    assert resolution.candidates == ()
    assert "bin" in _excluded(resolution, "cargo:owner/tool")


def test_no_cargo_toml_gives_no_cargo_candidate() -> None:
    """A stray ``src/main.rs`` without a Cargo.toml is not a crate."""
    resolution = _resolve({"src/main.rs": "fn main() {}"})

    assert resolution.candidates == ()
    assert any("Cargo.toml" in x.reason for x in resolution.exclusions)


def test_malformed_cargo_toml_is_an_exclusion_with_a_reason() -> None:
    """Broken TOML does not crash."""
    resolution = _resolve({"Cargo.toml": "[package\nname ="})

    assert resolution.candidates == ()
    assert "valid TOML" in _excluded(resolution, "cargo:owner/tool")


@pytest.mark.parametrize("text", [PACKAGE_BIN_OBJECT, PACKAGE_BIN_STRING])
def test_package_json_bin_gives_an_npm_candidate(text: str) -> None:
    """A ``bin`` string or object resolves to ``npm:github:owner/repo``."""
    resolution = _resolve({"package.json": text})

    top = resolution.recommendation
    assert top is not None
    assert (top.backend_string, top.tier) == ("npm:github:owner/tool", 4)
    assert any("bin" in reason for reason in top.reasons)


@pytest.mark.parametrize(
    "text", ['{"name": "tool"}', '{"bin": ""}', '{"bin": {}}', '{"bin": 3}', "[]"]
)
def test_package_json_without_a_usable_bin_gives_no_npm_candidate(text: str) -> None:
    """No ``bin``, or an empty or wrongly typed one, is excluded."""
    resolution = _resolve({"package.json": text})

    assert resolution.candidates == ()
    assert "bin" in _excluded(resolution, "npm:github:owner/tool")


def test_malformed_package_json_is_an_exclusion_with_a_reason() -> None:
    """Broken JSON does not crash."""
    resolution = _resolve({"package.json": '{"bin": '})

    assert resolution.candidates == ()
    assert "valid JSON" in _excluded(resolution, "npm:github:owner/tool")


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("Rust", ["cargo:owner/tool", "npm:github:owner/tool", "pypi:owner/tool"]),
        (
            "TypeScript",
            ["npm:github:owner/tool", "cargo:owner/tool", "pypi:owner/tool"],
        ),
        (
            "JavaScript",
            ["npm:github:owner/tool", "cargo:owner/tool", "pypi:owner/tool"],
        ),
        ("Python", ["pypi:owner/tool", "cargo:owner/tool", "npm:github:owner/tool"]),
        (None, ["cargo:owner/tool", "npm:github:owner/tool", "pypi:owner/tool"]),
    ],
)
def test_primary_language_breaks_ties_between_real_detectors(
    language: str | None, expected: list[str]
) -> None:
    """With all three entrypoints present, the language's backend leads."""
    files = {
        "Cargo.toml": CARGO_BIN,
        "package.json": PACKAGE_BIN_OBJECT,
        "pyproject.toml": PYPROJECT,
    }

    assert _backends(_resolve(files, language)) == expected


def test_cargo_and_npm_are_registered_by_default() -> None:
    """The default registry includes both ecosystems."""
    assert {PYPI, CARGO, NPM} <= set(ECOSYSTEMS)
