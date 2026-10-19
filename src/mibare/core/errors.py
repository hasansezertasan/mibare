"""Errors mibare reports to the user as exit code 2."""

from __future__ import annotations

__all__ = [
    "InvalidRepositoryError",
    "MibareError",
    "MiseError",
    "MiseNotFoundError",
    "MiseTooOldError",
]


class MibareError(Exception):
    """Base class for errors with a message meant for the user."""


class InvalidRepositoryError(MibareError):
    """The input is not a GitHub URL or ``owner/repo`` shorthand."""


class MiseError(MibareError):
    """Running ``mise`` failed or its output could not be understood."""


class MiseNotFoundError(MiseError):
    """No ``mise`` binary is available."""


class MiseTooOldError(MiseError):
    """The ``mise`` binary is older than the minimum mibare supports."""
