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


def test_autobins_false_does_not_infer_a_bin_from_src_main_rs() -> None:
    """``autobins = false`` turns off discovery, so ``src/main.rs`` is no evidence."""
    manifest = '[package]\nname = "tool"\nautobins = false\n'

    resolution = _resolve({"Cargo.toml": manifest, "src/main.rs": "fn main() {}"})

    assert resolution.candidates == ()
    assert "autobins" in _excluded(resolution, "cargo:owner/tool")


def test_autobins_false_still_honors_a_declared_bin_table() -> None:
    """A manually declared ``[[bin]]`` target exists whatever ``autobins`` says."""
    manifest = '[package]\nname = "tool"\nautobins = false\n\n[[bin]]\nname = "tool"\n'

    resolution = _resolve({"Cargo.toml": manifest})

    assert _backends(resolution) == ["cargo:owner/tool"]


def test_a_manifest_without_a_package_table_does_not_disable_autobins() -> None:
    """Only ``[package] autobins = false`` turns discovery off."""
    resolution = _resolve({
        "Cargo.toml": "[workspace]\nmembers = []\n",
        "src/main.rs": "fn main() {}",
    })

    assert _backends(resolution) == ["cargo:owner/tool"]


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


def _cargo(features: str, *bins: str) -> str:
    """Build a ``Cargo.toml`` from ``[features]`` lines and ``name:gates`` bins."""
    tables = ""
    for spec in bins:
        name, _, gates = spec.partition(":")
        gate_line = f"required-features = {gates}\n" if gates else ""
        tables += f'\n[[bin]]\nname = "{name}"\npath = "src/{name}.rs"\n{gate_line}'
    return f'[package]\nname = "tool"\n\n[features]\n{features}\n{tables}'


@pytest.mark.parametrize(
    ("features", "gates"),
    [
        ('default = ["cli"]\ncli = []', '["cli"]'),
        ('default = ["full"]\nfull = ["tui"]\ntui = ["cli"]\ncli = []', '["cli"]'),
        ('default = ["a", "b"]\na = []\nb = []', '["a", "b"]'),
        ('default = ["clap/derive"]\nclap = []', '["clap"]'),
        ('default = ["clap?/derive", "cli"]\ncli = []', '["cli"]'),
        ("default = []", "[]"),
    ],
)
def test_cargo_bin_gated_by_default_features_is_installable(
    features: str, gates: str
) -> None:
    """A bin whose required features are all on by default counts."""
    resolution = _resolve({"Cargo.toml": _cargo(features, f"tool:{gates}")})

    assert _backends(resolution) == ["cargo:owner/tool"]


@pytest.mark.parametrize(
    ("features", "gates", "feature"),
    [
        ("cli = []", '["cli"]', "cli"),
        ('default = ["a"]\na = []\nb = []', '["a", "b"]', "b"),
        ('default = ["dep:clap"]\nother = []', '["clap"]', "clap"),
        ('default = ["clap?/derive"]', '["clap"]', "clap"),
        ('default = ["cycle"]\ncycle = ["cycle"]', '["gate"]', "gate"),
    ],
)
def test_cargo_bin_gated_by_a_non_default_feature_is_excluded(
    features: str, gates: str, feature: str
) -> None:
    """A bin that ``cargo install`` would skip is excluded, naming the feature."""
    resolution = _resolve({"Cargo.toml": _cargo(features, f"tool:{gates}")})

    assert resolution.candidates == ()
    reason = _excluded(resolution, "cargo:owner/tool")
    assert "required-features" in reason
    assert feature in reason


def test_cargo_installable_bin_wins_over_a_gated_one() -> None:
    """One ungated bin is enough, even beside a gated one."""
    manifest = _cargo("extra = []", 'dev:["extra"]', "tool:")

    assert _backends(_resolve({"Cargo.toml": manifest})) == ["cargo:owner/tool"]


def test_cargo_gated_bin_does_not_fall_back_to_src_main_rs() -> None:
    """A declared, gated bin is a reason to exclude even when src/main.rs exists."""
    manifest = _cargo("extra = []", 'tool:["extra"]')

    resolution = _resolve({"Cargo.toml": manifest, "src/main.rs": "fn main() {}"})

    assert resolution.candidates == ()


def test_malformed_cargo_features_are_ignored() -> None:
    """A malformed ``[features]`` or ``required-features`` never crashes detection."""
    manifest = (
        '[package]\nname = "t"\n[features]\ndefault = "cli"\ncli = 3\n'
        '[[bin]]\nname = "t"\nrequired-features = "cli"\n'
        '[[bin]]\nname = "u"\nrequired-features = [1]\n'
    )

    assert _backends(_resolve({"Cargo.toml": manifest})) == ["cargo:owner/tool"]
