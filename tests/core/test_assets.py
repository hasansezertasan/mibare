"""Table-driven tests for matching release asset names to a target platform."""

from __future__ import annotations

import pytest

from mibare.core.assets import matching_assets
from mibare.core.platform import Platform

LINUX_X64 = Platform("linux", "x64")
LINUX_ARM64 = Platform("linux", "arm64")
MACOS_ARM64 = Platform("macos", "arm64")
MACOS_X64 = Platform("macos", "x64")
WINDOWS_X64 = Platform("windows", "x64")


@pytest.mark.parametrize(
    ("name", "platform", "expected"),
    [
        ("ripgrep-14.1.0-x86_64-unknown-linux-musl.tar.gz", LINUX_X64, True),
        ("ripgrep-14.1.0-x86_64-unknown-linux-musl.tar.gz", LINUX_ARM64, False),
        ("ripgrep-14.1.0-aarch64-unknown-linux-gnu.tar.gz", LINUX_ARM64, True),
        ("ripgrep-14.1.0-x86_64-apple-darwin.tar.gz", MACOS_X64, True),
        ("ripgrep-14.1.0-aarch64-apple-darwin.tar.gz", MACOS_ARM64, True),
        ("ripgrep-14.1.0-aarch64-apple-darwin.tar.gz", MACOS_X64, False),
        ("ripgrep-14.1.0-x86_64-pc-windows-msvc.zip", WINDOWS_X64, True),
        ("ripgrep-14.1.0-x86_64-pc-windows-msvc.zip", LINUX_X64, False),
        ("tool_1.0_Linux_amd64.tar.gz", LINUX_X64, True),
        ("tool_1.0_Darwin_arm64.tar.gz", MACOS_ARM64, True),
        ("tool-osx-x64.zip", MACOS_X64, True),
        ("tool-macos-arm64.zip", MACOS_ARM64, True),
        ("tool-win-x64.zip", WINDOWS_X64, True),
        ("tool-win64.zip", WINDOWS_X64, True),
        ("tool-linux64.tar.gz", LINUX_X64, True),
        ("tool-linux-x86-64.tar.gz", LINUX_X64, True),
        ("tool-linux-64bit.tar.gz", LINUX_X64, True),
        ("protoc-1.0-linux-aarch_64.zip", LINUX_ARM64, True),
        ("tool-windows-amd64.exe", WINDOWS_X64, True),
        ("tool-linux-x86.tar.gz", LINUX_X64, False),
        ("tool-linux-i386.tar.gz", LINUX_X64, False),
        ("tool-darwin-universal.tar.gz", MACOS_ARM64, True),
        ("tool-darwin-universal.tar.gz", MACOS_X64, True),
        ("tool-darwin-universal.tar.gz", LINUX_X64, False),
        ("tool-linux.tar.gz", LINUX_X64, False),
        ("tool-x64.tar.gz", LINUX_X64, False),
        ("tool-linux-x64-arm64.tar.gz", LINUX_X64, False),
        ("tool-linux-x64.tar.gz.sha256", LINUX_X64, False),
        ("tool-linux-x64.tar.gz.sig", LINUX_X64, False),
        ("tool-linux-x64.tar.gz.asc", LINUX_X64, False),
        ("tool-linux-x64.deb", LINUX_X64, False),
        ("tool-linux-x64.rpm", LINUX_X64, False),
        ("checksums-linux-x64.txt", LINUX_X64, False),
        ("TOOL-LINUX-X64.TAR.GZ", LINUX_X64, True),
        ("darwinia-linux-x64.tar.gz", MACOS_X64, False),
        ("window-x64.tar.gz", WINDOWS_X64, False),
    ],
)
def test_asset_name_matches_the_target_platform(
    name: str, platform: Platform, *, expected: bool
) -> None:
    """An asset name matches only when its OS and architecture are the target's.

    Given:
        - A release asset name and a target platform.
    When:
        - The asset names are filtered for the platform.
    Then:
        - The name is kept exactly when it names the target OS and architecture.
    """
    assert (matching_assets([name], platform) == (name,)) is expected


def test_matching_assets_keeps_input_order() -> None:
    """The matches come back in the order the release lists them."""
    names = ["b-linux-x64.tar.gz", "a-darwin-arm64.tar.gz", "a-linux-amd64.zip"]

    assert matching_assets(names, LINUX_X64) == (
        "b-linux-x64.tar.gz",
        "a-linux-amd64.zip",
    )
