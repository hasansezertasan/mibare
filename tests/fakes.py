"""Test doubles shared across the suite."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mibare.core.github import HttpResponse, RepositoryFiles
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
        probe_errors: Mapping[str, Exception] | None = None,
    ) -> None:
        """Set the fixture registry, recipes and version, or errors to raise.

        ``error`` fails ``version()``; ``probe_errors`` fails the existence
        probe of the backend strings it names.
        """
        self._registry = tuple(registry)
        self._recipes = frozenset(recipes)
        self._probe_errors = dict(probe_errors or {})
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
        if backend_string in self._probe_errors:
            raise self._probe_errors[backend_string]
        return backend_string in self._recipes


def entry(tool: str, *backends: str) -> RegistryEntry:
    """Build a registry entry for ``tool`` listing ``backends`` in order.

    Returns:
        RegistryEntry: The entry.
    """
    return RegistryEntry(tool=tool, backends=backends)


class FakeTransport:
    """Answers GET requests from a table keyed by URL path."""

    def __init__(
        self,
        routes: Mapping[str, tuple[int, object]] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Set the fixture responses (status, JSON body) or an error to raise."""
        self.routes = dict(routes or {})
        self.error = error
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> HttpResponse:
        """Record the request and answer it.

        Returns:
            HttpResponse: The fixture response, or 404 when there is none.
        """
        self.requests.append((url, dict(headers)))
        if self.error is not None:
            raise self.error
        path = url.removeprefix("https://api.github.com")
        status, body = self.routes.get(path, (404, {}))
        return HttpResponse(status, json.dumps(body).encode())


class FakeGitHub:
    """A GitHub adapter that answers from fixtures instead of the network."""

    def __init__(
        self,
        assets: Sequence[str] = (),
        *,
        language: str | None = None,
        files: Mapping[str, str] | None = None,
        error: Exception | None = None,
        language_error: Exception | None = None,
    ) -> None:
        """Set the fixture release assets, language and root files, or errors.

        ``error`` fails every call except the language lookup and the existence
        check; ``language_error`` fails only ``primary_language``.

        Set ``truncated`` to mark the file listing as cut short, ``exists`` to
        ``False`` for a repository GitHub does not have, and ``exists_error``
        to fail only ``repository_exists``.
        """
        self._assets = tuple(assets)
        self._language = language
        self._files = dict(files or {})
        self._error = error
        self._language_error = language_error
        self.exists = True
        self.exists_error: Exception | None = None
        self.truncated = False
        self.calls = 0
        self.tree_calls = 0
        self.file_reads: list[str] = []

    def repository_exists(self, repository: Repository) -> bool:
        """Say whether the fixture repository exists, or fail with its error.

        Returns:
            bool: The fixture answer.
        """
        del repository
        if self.exists_error is not None:
            raise self.exists_error
        return self.exists

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

    def list_files(self, repository: Repository) -> RepositoryFiles:
        """List the fixture file paths, or fail with the fixture error.

        Returns:
            RepositoryFiles: The fixture paths, flagged truncated when asked.
        """
        del repository
        self.tree_calls += 1
        if self._error is not None:
            raise self._error
        return RepositoryFiles(tuple(sorted(self._files)), self.truncated)

    def primary_language(self, repository: Repository) -> str | None:
        """Return the fixture language, or fail with the fixture language error.

        Returns:
            str | None: The fixture language.
        """
        del repository
        if self._language_error is not None:
            raise self._language_error
        return self._language

    def root_file(self, repository: Repository, name: str) -> str | None:
        """Return a fixture root file, or fail with the fixture error.

        Returns:
            str | None: The file's text, or ``None`` when it is absent.
        """
        del repository
        if self._error is not None:
            raise self._error
        self.file_reads.append(name)
        return self._files.get(name)
