"""Test doubles shared across the suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mibare.core.mise import RegistryEntry

if TYPE_CHECKING:
    from collections.abc import Sequence


class FakeMise:
    """A mise adapter that answers from fixtures instead of running ``mise``."""

    def __init__(
        self,
        registry: Sequence[RegistryEntry] = (),
        *,
        recipes: Sequence[str] = (),
        version: str = "2026.10.13",
        error: Exception | None = None,
    ) -> None:
        """Set the fixture registry, recipes and version, or a ``version`` error."""
        self._registry = tuple(registry)
        self._recipes = frozenset(recipes)
        self._version = version
        self._error = error

    def version(self) -> str:
        """Return the fixture version, or fail with the fixture error.

        Returns:
            str: The fixture version.
        """
        if self._error is not None:
            raise self._error
        return self._version

    def registry(self) -> tuple[RegistryEntry, ...]:
        """Return the fixture registry.

        Returns:
            tuple[RegistryEntry, ...]: The fixture entries.
        """
        return self._registry

    def recipe_exists(self, backend_string: str) -> bool:
        """Say whether a fixture recipe exists for ``backend_string``.

        Returns:
            bool: ``True`` when it is one of the fixture recipes.
        """
        return backend_string in self._recipes


def entry(tool: str, *backends: str) -> RegistryEntry:
    """Build a registry entry for ``tool`` listing ``backends`` in order.

    Returns:
        RegistryEntry: The entry.
    """
    return RegistryEntry(tool=tool, backends=backends)
