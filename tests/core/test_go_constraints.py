"""Tests for Go file selection by file name and build constraints."""

from __future__ import annotations

import pytest

from mibare.core.go_constraints import constraint_matches, name_matches
from mibare.core.platform import Platform

LINUX_X64 = Platform("linux", "x64")
MACOS_ARM64 = Platform("macos", "arm64")
WINDOWS_X64 = Platform("windows", "x64")


@pytest.mark.parametrize(
    ("name", "platform", "expected"),
    [
        ("main.go", LINUX_X64, True),
        ("main_test.go", LINUX_X64, False),
        ("main_windows.go", LINUX_X64, False),
        ("main_windows.go", WINDOWS_X64, True),
        ("main_linux.go", LINUX_X64, True),
        ("main_darwin.go", MACOS_ARM64, True),
        ("main_darwin.go", LINUX_X64, False),
        ("main_amd64.go", LINUX_X64, True),
        ("main_arm64.go", LINUX_X64, False),
        ("main_linux_amd64.go", LINUX_X64, True),
        ("main_linux_arm64.go", LINUX_X64, False),
        ("main_windows_amd64.go", LINUX_X64, False),
        ("main_darwin_arm64.go", MACOS_ARM64, True),
        ("main_linux_test.go", LINUX_X64, False),
        ("linux.go", WINDOWS_X64, True),
        ("windows.go", LINUX_X64, True),
        ("_ignored.go", LINUX_X64, False),
        (".hidden.go", LINUX_X64, False),
        ("main_plan9.go", LINUX_X64, False),
        ("my_tool.go", LINUX_X64, True),
    ],
)
def test_file_name_suffixes_select_files_for_the_platform(
    name: str, platform: Platform, *, expected: bool
) -> None:
    """GOOS and GOARCH suffixes, ``_test`` and ``_``/``.`` prefixes decide."""
    assert name_matches(name, platform) is expected


@pytest.mark.parametrize(
    ("line", "platform", "expected"),
    [
        ("linux", LINUX_X64, True),
        ("linux", WINDOWS_X64, False),
        ("!windows", LINUX_X64, True),
        ("!windows", WINDOWS_X64, False),
        ("linux && amd64", LINUX_X64, True),
        ("linux && arm64", LINUX_X64, False),
        ("windows || linux", LINUX_X64, True),
        ("windows || darwin", LINUX_X64, False),
        ("(linux || darwin) && !arm64", LINUX_X64, True),
        ("(linux || darwin) && !arm64", MACOS_ARM64, False),
        ("!(linux && amd64)", LINUX_X64, False),
        ("!!linux", LINUX_X64, True),
        ("darwin", MACOS_ARM64, True),
        ("unix", LINUX_X64, True),
        ("unix", MACOS_ARM64, True),
        ("unix", WINDOWS_X64, False),
        ("ignore", LINUX_X64, False),
        ("customtag", LINUX_X64, False),
        ("!customtag", LINUX_X64, True),
        ("gc", LINUX_X64, True),
        ("go1.21", LINUX_X64, True),
        ("linux&&amd64", LINUX_X64, True),
    ],
)
def test_build_constraints_are_evaluated_for_the_platform(
    line: str, platform: Platform, *, expected: bool
) -> None:
    """Operators, parentheses, GOOS/GOARCH, ``unix`` and unknown tags evaluate."""
    source = f"//go:build {line}\n\npackage main\n"

    assert constraint_matches(source, platform) is expected


@pytest.mark.parametrize(
    "source",
    [
        "package main\n",
        "// Copyright.\n\npackage main\n",
        "//go:build\npackage main\n",
        "//go:build linux &&\npackage main\n",
        "//go:build (linux\npackage main\n",
        "//go:build linux amd64\npackage main\n",
        "//go:build linux )\npackage main\n",
        "//go:build @\npackage main\n",
        "//go:build (linux amd64)\npackage main\n",
        "//go:build && linux\npackage main\n",
        "// only a comment\n",
    ],
)
def test_a_missing_or_unparsable_constraint_includes_the_file(source: str) -> None:
    """No constraint, or one that does not parse, leaves the file in."""
    assert constraint_matches(source, WINDOWS_X64) is True


def test_a_constraint_after_a_license_comment_still_applies() -> None:
    """Line and block comments may precede the ``//go:build`` line."""
    source = (
        "// Copyright.\n/* block\ncomment */\n\n//go:build windows\n\npackage main\n"
    )

    assert constraint_matches(source, LINUX_X64) is False


def test_a_build_line_after_the_package_clause_is_not_a_constraint() -> None:
    """Only the header counts; a later ``//go:build`` comment is ignored."""
    source = "package main\n\n//go:build windows\n"

    assert constraint_matches(source, LINUX_X64) is True


def test_the_first_build_line_wins() -> None:
    """Go reads one ``//go:build`` line; extra ones are ignored."""
    source = "//go:build linux\n//go:build windows\npackage main\n"

    assert constraint_matches(source, LINUX_X64) is True


@pytest.mark.parametrize(
    ("line", "platform", "expected"),
    [
        ("linux", LINUX_X64, True),
        ("linux", WINDOWS_X64, False),
        ("!windows", LINUX_X64, True),
        ("!windows", WINDOWS_X64, False),
        ("linux darwin", MACOS_ARM64, True),
        ("linux darwin", WINDOWS_X64, False),
        ("linux,amd64", LINUX_X64, True),
        ("linux,arm64", LINUX_X64, False),
        ("linux,!arm64 windows", LINUX_X64, True),
        ("linux,arm64 windows,amd64", LINUX_X64, False),
        ("windows,amd64 linux,amd64", LINUX_X64, True),
        ("unix", MACOS_ARM64, True),
        ("ignore", LINUX_X64, False),
        ("!ignore", LINUX_X64, True),
        ("gc", LINUX_X64, True),
        ("go1.18", LINUX_X64, True),
    ],
)
def test_legacy_plus_build_lines_are_evaluated_for_the_platform(
    line: str, platform: Platform, *, expected: bool
) -> None:
    """Spaces are OR, commas are AND, ``!`` negates, tags as in ``//go:build``."""
    source = f"// +build {line}\n\npackage main\n"

    assert constraint_matches(source, platform) is expected


@pytest.mark.parametrize(
    ("lines", "platform", "expected"),
    [
        (("linux darwin", "amd64"), LINUX_X64, True),
        (("linux darwin", "arm64"), LINUX_X64, False),
        (("windows", "amd64"), LINUX_X64, False),
    ],
)
def test_multiple_plus_build_lines_are_anded(
    lines: tuple[str, ...], platform: Platform, *, expected: bool
) -> None:
    """Each ``// +build`` line must hold."""
    header = "".join(f"// +build {line}\n" for line in lines)

    assert constraint_matches(f"{header}\npackage main\n", platform) is expected


def test_go_build_wins_over_plus_build() -> None:
    """When both forms exist, the legacy line is ignored."""
    source = "//go:build linux\n// +build windows\n\npackage main\n"

    assert constraint_matches(source, LINUX_X64) is True
    assert constraint_matches(source, WINDOWS_X64) is False


def test_plus_build_after_a_license_comment_still_applies() -> None:
    """Comment lines and blank lines may precede the ``// +build`` line."""
    source = "// Copyright.\n\n// +build windows\n\npackage main\n"

    assert constraint_matches(source, LINUX_X64) is False


@pytest.mark.parametrize(
    "source",
    [
        "// +build windows\npackage main\n",
        "package main\n\n// +build windows\n",
        "/* c */\n\n// +build windows\n\npackage main\n",
        "// +build windows\n",
    ],
)
def test_plus_build_outside_the_header_is_not_a_constraint(source: str) -> None:
    """Go needs a blank line before the package clause, and only reads the header."""
    assert constraint_matches(source, LINUX_X64) is True


@pytest.mark.parametrize(
    "source",
    [
        "// +build\n\npackage main\n",
        "// +build !!linux\n\npackage main\n",
        "// +build linux,\n\npackage main\n",
        "// +build @\n\npackage main\n",
        "// +build windows\n// +build @\n\npackage main\n",
    ],
)
def test_an_unparsable_plus_build_line_includes_the_file(source: str) -> None:
    """A legacy constraint that does not parse leaves the file in."""
    assert constraint_matches(source, LINUX_X64) is True
