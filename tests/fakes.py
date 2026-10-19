"""Test doubles shared across the suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mibare.core.mise import RegistryEntry

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mibare.core.repository import Repository


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


class FakeGitHub:
    """A GitHub adapter that answers from fixtures instead of the network."""

    def __init__(
        self,
        assets: Sequence[str] = (),
        *,
        language: str | None = None,
        files: Mapping[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Set the fixture release assets, language and root files, or an error."""
        self._assets = tuple(assets)
        self._language = language
        self._files = dict(files or {})
        self._error = error
        self.calls = 0

    def latest_release_assets(self, repository: Repository) -> tuple[str, ...]:
        """Return the fixture asset names, or fail with the fixture error.

        Returns:
            tuple[str, ...]: The fixture asset names.
        """
        del repository
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._assets

    def list_dir(self, repository: Repository, path: str) -> tuple[str, ...]:
        """List the entries under ``path`` implied by the fixture file paths.

        Returns:
            tuple[str, ...]: Entry names in first-seen order; empty when none.
        """
        del repository
        if self._error is not None:
            raise self._error
        prefix = f"{path.strip('/')}/" if path.strip("/") else ""
        names = (
            name.removeprefix(prefix).split("/", 1)[0]
            for name in self._files
            if name.startswith(prefix)
        )
        return tuple(dict.fromkeys(names))

    def primary_language(self, repository: Repository) -> str | None:
        """Return the fixture language, or fail with the fixture error.

        Returns:
            str | None: The fixture language.
        """
        del repository
        if self._error is not None:
            raise self._error
        return self._language

    def root_file(self, repository: Repository, name: str) -> str | None:
        """Return a fixture root file, or fail with the fixture error.

        Returns:
            str | None: The file's text, or ``None`` when it is absent.
        """
        del repository
        if self._error is not None:
            raise self._error
        return self._files.get(name)
