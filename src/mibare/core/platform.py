"""The target platform a resolution is for."""

from __future__ import annotations

import platform
from dataclasses import dataclass

from mibare.core.errors import InvalidPlatformError

__all__ = ["Platform", "host_platform"]

_OSES = ("linux", "macos", "windows")
_ARCHES = ("x64", "arm64")
_HOST_OS = {"linux": "linux", "darwin": "macos", "windows": "windows"}
_HOST_ARCH = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}


@dataclass(frozen=True)
class Platform:
    """An operating system and CPU architecture, as in ``linux-x64``.

    Attributes:
        os: ``linux``, ``macos`` or ``windows``.
        arch: ``x64`` or ``arm64``.
    """

    os: str
    arch: str

    @property
    def label(self) -> str:
        """Format as ``os-arch``.

        Returns:
            str: For example ``linux-x64``.
        """
        return f"{self.os}-{self.arch}"

    @classmethod
    def parse(cls, text: str) -> Platform:
        """Read ``os-arch`` text, ignoring case.

        Args:
            text: For example ``windows-x64``.

        Returns:
            Platform: The platform.

        Raises:
            InvalidPlatformError: If ``text`` is not a known ``os-arch`` pair.
        """
        os_name, _, arch = text.strip().lower().partition("-")
        if os_name not in _OSES or arch not in _ARCHES:
            message = (
                f"Invalid platform {text!r}: expected os-arch, with os one of "
                f"{', '.join(_OSES)} and arch one of {', '.join(_ARCHES)} "
                "(for example linux-x64)."
            )
            raise InvalidPlatformError(message)
        return cls(os_name, arch)


def host_platform() -> Platform:
    """Detect the platform mibare is running on.

    Returns:
        Platform: The host platform.

    Raises:
        InvalidPlatformError: If the host is not a supported platform.
    """
    os_name = _HOST_OS.get(platform.system().lower())
    arch = _HOST_ARCH.get(platform.machine().lower())
    if os_name is None or arch is None:
        message = (
            f"Unsupported host platform {platform.system()}-{platform.machine()}; "
            "pass --platform os-arch."
        )
        raise InvalidPlatformError(message)
    return Platform(os_name, arch)
