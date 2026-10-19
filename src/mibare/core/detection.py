"""The result type of an ecosystem detector, kept apart so detectors can import it."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Detection"]


@dataclass(frozen=True)
class Detection:
    """What a detector concluded about one repository.

    Attributes:
        backend_string: The backend string considered, as in ``pypi:owner/repo``.
        reason: Why it is offered (when ``found``) or why it is left out.
        found: Whether the repository has an entrypoint for this ecosystem.
    """

    backend_string: str
    reason: str
    found: bool = field(default=True, kw_only=True)
