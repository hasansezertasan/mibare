"""Errors mibare reports to the user as exit code 2."""

from __future__ import annotations

__all__ = [
    "GitHubUnavailableError",
    "InvalidPlatformError",
    "InvalidRepositoryError",
    "MibareError",
    "MiseError",
    "MiseNotFoundError",
    "MiseTooOldError",
    "RepositoryNotFoundError",
]


class MibareError(Exception):
    """Base class for errors with a message meant for the user."""


class InvalidRepositoryError(MibareError):
    """The input is not a GitHub URL or ``owner/repo`` shorthand."""


class InvalidPlatformError(MibareError):
    """The platform is not a known ``os-arch`` pair."""


class GitHubUnavailableError(MibareError):
    """The GitHub API could not be used: no network, a rate limit or a server error."""


class RepositoryNotFoundError(MibareError):
    """GitHub has no repository with the given owner and name."""


class MiseError(MibareError):
    """Running ``mise`` failed or its output could not be understood."""


class MiseNotFoundError(MiseError):
    """No ``mise`` binary is available."""


class MiseTooOldError(MiseError):
    """The ``mise`` binary is older than the minimum mibare supports."""
