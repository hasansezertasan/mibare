"""The GitHub adapter: the only code that talks to the GitHub API.

It reads an optional ``GITHUB_TOKEN`` to avoid unauthenticated rate limits. The
HTTP layer is a small injectable transport built on :mod:`urllib`, so no
dependency is needed and tests never touch the network.
"""

from __future__ import annotations

import base64
import binascii
import http.client
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from mibare.core.errors import GitHubUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mibare.core.repository import Repository

__all__ = [
    "GitHub",
    "GitHubApi",
    "HttpResponse",
    "RepositoryFiles",
    "Transport",
    "urllib_transport",
]

_API = "https://api.github.com"
_TIMEOUT_SECONDS = 20
_HTTP_OK = 200
_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409


@dataclass(frozen=True)
class HttpResponse:
    """An HTTP response.

    Attributes:
        status: The status code.
        body: The raw response body.
    """

    status: int
    body: bytes


@dataclass(frozen=True)
class RepositoryFiles:
    """The file listing of a repository's default branch.

    Attributes:
        paths: The repo-relative path of every file, such as ``cmd/a/main.go``.
        truncated: Whether GitHub cut the listing short (very large trees), so
            ``paths`` may be missing files.
    """

    paths: tuple[str, ...] = ()
    truncated: bool = False


class Transport(Protocol):
    """Performs a GET request; raises ``OSError`` or ``http.client`` errors."""

    def __call__(self, url: str, headers: Mapping[str, str]) -> HttpResponse:
        """Fetch ``url`` with ``headers``."""
        raise NotImplementedError


class GitHub(Protocol):
    """The interface ``resolve()`` needs from GitHub, replaceable in tests."""

    def repository_exists(self, repository: Repository) -> bool:
        """Return whether the repository exists; only a 404 means it does not."""
        raise NotImplementedError

    def latest_release_assets(self, repository: Repository) -> tuple[str, ...]:
        """Return the asset names of the latest release; empty when none."""
        raise NotImplementedError

    def list_files(self, repository: Repository) -> RepositoryFiles:
        """Return every file path in the repository, in one request."""
        raise NotImplementedError

    def primary_language(self, repository: Repository) -> str | None:
        """Return the repository's primary language, or ``None``."""
        raise NotImplementedError

    def root_file(self, repository: Repository, name: str) -> str | None:
        """Return a root file's text, or ``None`` when it is absent."""
        raise NotImplementedError


class _Reply(Protocol):
    """The parts of an HTTP reply that the transport reads."""

    status: int

    def read(self) -> bytes:
        """Return the reply body."""
        raise NotImplementedError

    def close(self) -> None:
        """Release the connection."""
        raise NotImplementedError


def _read_reply(reply: _Reply) -> HttpResponse:
    """Read an open reply into an :class:`HttpResponse`, closing it.

    Args:
        reply: The open reply.

    Returns:
        HttpResponse: The status and body.
    """
    try:
        return HttpResponse(reply.status, reply.read())
    finally:
        reply.close()


def urllib_transport(url: str, headers: Mapping[str, str]) -> HttpResponse:
    """Fetch ``url`` with :mod:`urllib`, returning error statuses as responses.

    Args:
        url: An https URL.
        headers: Request headers.

    Returns:
        HttpResponse: The status and body.
    """
    request = urllib.request.Request(url, headers=dict(headers))  # noqa: S310
    try:
        return _read_reply(
            cast("_Reply", urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS))  # noqa: S310  # pylint: disable=consider-using-with
        )
    except urllib.error.HTTPError as error:
        return HttpResponse(error.code, error.read())


class GitHubApi:
    """The real adapter, which calls the GitHub REST API."""

    def __init__(
        self, transport: Transport = urllib_transport, token: str | None = None
    ) -> None:
        """Create the adapter.

        Args:
            transport: Performs the requests; replaced in tests.
            token: A GitHub token; defaults to ``GITHUB_TOKEN`` when ``None``.
        """
        self._transport: Transport = transport
        self._repositories: dict[str, object] = {}
        self._trees: dict[str, RepositoryFiles] = {}
        self._token: str | None = (
            token if token is not None else os.environ.get("GITHUB_TOKEN")
        )

    def latest_release_assets(self, repository: Repository) -> tuple[str, ...]:
        """Return the asset names of the latest release.

        Args:
            repository: The repository to look up.

        Returns:
            tuple[str, ...]: The names in release order; empty when the
                repository has no release.
        """
        body = self._get(f"/repos/{repository.shorthand}/releases/latest")
        if not isinstance(body, dict):
            return ()
        assets = cast("dict[str, object]", body).get("assets")
        if not isinstance(assets, list):
            return ()
        names = (
            cast("dict[str, object]", item).get("name")
            for item in cast("list[object]", assets)
            if isinstance(item, dict)
        )
        return tuple(name for name in names if isinstance(name, str))

    def primary_language(self, repository: Repository) -> str | None:
        """Return the repository's primary language.

        Args:
            repository: The repository to look up.

        Returns:
            str | None: The language GitHub reports, or ``None``.
        """
        body = self._repository_body(repository)
        if not isinstance(body, dict):
            return None
        language = cast("dict[str, object]", body).get("language")
        return language if isinstance(language, str) else None

    def repository_exists(self, repository: Repository) -> bool:
        """Say whether GitHub has the repository.

        The response is kept, so a later :meth:`primary_language` costs no
        further request.

        Args:
            repository: The repository to look up.

        Returns:
            bool: ``False`` only when GitHub answers 404.
        """
        return self._repository_body(repository) is not None

    def _repository_body(self, repository: Repository) -> object:
        """Fetch ``/repos/{owner}/{name}`` once per repository.

        Returns:
            object: The decoded body, or ``None`` when GitHub answers 404.
        """
        key = repository.shorthand
        if key not in self._repositories:
            self._repositories[key] = self._get(f"/repos/{key}")
        return self._repositories[key]

    def root_file(self, repository: Repository, name: str) -> str | None:
        """Return the text of a file in the repository.

        Args:
            repository: The repository to look up.
            name: The repo-relative path, such as ``pyproject.toml`` or
                ``src/main.rs``.

        Returns:
            str | None: The decoded contents, or ``None`` when the file is
                absent, is a directory or is not text.
        """
        quoted = urllib.parse.quote(name, safe="/")
        body = self._get(f"/repos/{repository.shorthand}/contents/{quoted}")
        if not isinstance(body, dict):
            return None
        fields = cast("dict[str, object]", body)
        content = fields.get("content")
        if fields.get("type") != "file" or not isinstance(content, str):
            return None
        try:
            return base64.b64decode(content).decode()
        except (binascii.Error, UnicodeDecodeError):
            return None

    def list_files(self, repository: Repository) -> RepositoryFiles:
        """List every file in the repository with one git trees request.

        The listing is kept, so the detectors that read it share one request.

        Args:
            repository: The repository to look up.

        Returns:
            RepositoryFiles: The path of every file on the default branch, and
                whether GitHub truncated the listing; empty when the
                repository has no tree.
        """
        key = repository.shorthand
        if key not in self._trees:
            self._trees[key] = self._fetch_files(repository)
        return self._trees[key]

    def _fetch_files(self, repository: Repository) -> RepositoryFiles:
        """Request the git tree of the repository's default branch.

        Returns:
            RepositoryFiles: The listing; empty when there is no tree.
        """
        # GitHub answers 409 Conflict from the git database of an empty repository.
        body = self._get(
            f"/repos/{repository.shorthand}/git/trees/HEAD?recursive=1",
            empty_statuses=(_HTTP_CONFLICT,),
        )
        if not isinstance(body, dict):
            return RepositoryFiles()
        fields = cast("dict[str, object]", body)
        tree = fields.get("tree")
        if not isinstance(tree, list):
            return RepositoryFiles()
        entries = (
            cast("dict[str, object]", item)
            for item in cast("list[object]", tree)
            if isinstance(item, dict)
        )
        paths = tuple(
            entry["path"]
            for entry in entries
            if entry.get("type") == "blob" and isinstance(entry.get("path"), str)
        )
        return RepositoryFiles(
            cast("tuple[str, ...]", paths), fields.get("truncated") is True
        )

    def _get(self, path: str, empty_statuses: tuple[int, ...] = ()) -> object:
        """GET ``path`` and decode the JSON body.

        Args:
            path: The API path, starting with ``/``.
            empty_statuses: Statuses besides 404 that mean "nothing here" for
                this request.

        Returns:
            object: The decoded JSON, or ``None`` when GitHub answers 404 or
                one of ``empty_statuses``.

        Raises:
            GitHubUnavailableError: If the answer is not readable JSON.
        """
        response = self._fetch(path, empty_statuses)
        if response.status == _HTTP_NOT_FOUND or response.status in empty_statuses:
            return None
        try:
            return cast("object", json.loads(response.body))
        except ValueError as exc:
            message = f"GitHub sent an unreadable answer for {path}."
            raise GitHubUnavailableError(message) from exc

    def _fetch(self, path: str, extra_statuses: tuple[int, ...] = ()) -> HttpResponse:
        """Request ``path``, accepting only 200, 404 and ``extra_statuses``.

        Args:
            path: The API path, starting with ``/``.
            extra_statuses: Further statuses this request accepts.

        Returns:
            HttpResponse: The response, with an accepted status.

        Raises:
            GitHubUnavailableError: If the network fails or GitHub answers
                with any other status.
        """
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mibare",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = self._transport(f"{_API}{path}", headers)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            # ValueError covers UnicodeError and urllib's "unknown url type".
            message = f"Could not reach GitHub: {exc}"
            raise GitHubUnavailableError(message) from exc
        if response.status not in {_HTTP_OK, _HTTP_NOT_FOUND, *extra_statuses}:
            message = f"GitHub answered HTTP {response.status} for {path}."
            raise GitHubUnavailableError(message)
        return response
