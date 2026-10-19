"""Tests for the configuration module.

These tests assert only the public ``Settings`` behavior shared by both the
pydantic-settings and stdlib backends, so they hold regardless of the
``include_pydantic_settings`` choice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mibare.__metadata__ import PROJECT_NAME
from mibare.core.config import Settings

if TYPE_CHECKING:
    import pytest

# Mirror the prefix the implementation derives from the project name.
ENV_PREFIX = f"{PROJECT_NAME.upper().replace('-', '_')}_"


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings expose the documented defaults when no env vars are set."""
    monkeypatch.delenv(f"{ENV_PREFIX}LOG_LEVEL", raising=False)

    assert Settings().log_level == "INFO"


def test_log_level_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The log level is read from the prefixed environment variable."""
    monkeypatch.setenv(f"{ENV_PREFIX}LOG_LEVEL", "DEBUG")

    assert Settings().log_level == "DEBUG"
