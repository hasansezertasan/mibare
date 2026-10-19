"""Resolve a GitHub repository to mise backends from Python."""

from mibare.core.mise import SubprocessMise
from mibare.core.resolve import resolve


def recommended_backend(repository: str) -> str | None:
    """Return the recommended backend string for a repository.

    Args:
        repository: A GitHub URL or ``owner/repo`` shorthand.

    Returns:
        str | None: The recommended backend string, or ``None`` when mise's
            registry lists no backend for the repository.
    """
    recommendation = resolve(repository, SubprocessMise()).recommendation
    return recommendation.backend_string if recommendation else None
