"""Tests for the GitHub adapter, through an injected fake HTTP transport."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

import pytest

from mibare.core.errors import GitHubUnavailableError
from mibare.core.github import GitHubApi, HttpResponse
from mibare.core.repository import Repository

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO = Repository("BurntSushi", "ripgrep")


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


def test_latest_release_assets_lists_asset_names() -> None:
    """The names of the latest release's assets are returned in order."""
    body = {"assets": [{"name": "a.zip"}, {"name": "b.tar.gz"}]}
    route = "/repos/BurntSushi/ripgrep/releases/latest"
    transport = FakeTransport({route: (200, body)})

    assert GitHubApi(transport, token=None).latest_release_assets(REPO) == (
        "a.zip",
        "b.tar.gz",
    )


def test_repository_without_a_release_has_no_assets() -> None:
    """A 404 for the latest release means no assets, not a failure."""
    assert GitHubApi(FakeTransport(), token=None).latest_release_assets(REPO) == ()


def test_primary_language_is_read_from_the_repository() -> None:
    """The repository's ``language`` field is returned."""
    transport = FakeTransport({
        "/repos/BurntSushi/ripgrep": (200, {"language": "Rust"})
    })

    assert GitHubApi(transport, token=None).primary_language(REPO) == "Rust"


@pytest.mark.parametrize("body", [{"language": None}, {}])
def test_primary_language_is_none_when_github_reports_none(
    body: dict[str, object],
) -> None:
    """A repository without a detected language gives ``None``."""
    transport = FakeTransport({"/repos/BurntSushi/ripgrep": (200, body)})

    assert GitHubApi(transport, token=None).primary_language(REPO) is None


def test_root_file_returns_decoded_contents() -> None:
    """A file in the repository root is returned as text."""
    text = "[project]\nname = 'x'\n"
    encoded = base64.encodebytes(text.encode()).decode()
    body = {"type": "file", "encoding": "base64", "content": encoded}
    path = "/repos/BurntSushi/ripgrep/contents/pyproject.toml"
    transport = FakeTransport({path: (200, body)})

    assert GitHubApi(transport, token=None).root_file(REPO, "pyproject.toml") == text


def test_root_file_is_none_when_absent_or_a_directory() -> None:
    """A missing file and a directory both give ``None``."""
    directory = "/repos/BurntSushi/ripgrep/contents/cmd"
    transport = FakeTransport({directory: (200, [{"name": "x"}])})
    api = GitHubApi(transport, token=None)

    assert api.root_file(REPO, "package.json") is None
    assert api.root_file(REPO, "cmd") is None


def test_root_file_accepts_a_repo_relative_path() -> None:
    """A nested path such as ``src/main.rs`` is read the same way."""
    encoded = base64.encodebytes(b"fn main() {}").decode()
    body = {"type": "file", "encoding": "base64", "content": encoded}
    path = "/repos/BurntSushi/ripgrep/contents/src/main.rs"
    transport = FakeTransport({path: (200, body)})

    api = GitHubApi(transport, token=None)
    assert api.root_file(REPO, "src/main.rs") == "fn main() {}"


def test_token_is_sent_when_given() -> None:
    """An explicit token becomes a bearer Authorization header."""
    transport = FakeTransport()

    _ = GitHubApi(transport, token="secret").primary_language(REPO)  # noqa: S106

    assert transport.requests[0][1]["Authorization"] == "Bearer secret"


def test_token_defaults_to_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """``GITHUB_TOKEN`` is used when no token is passed."""
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    transport = FakeTransport()

    _ = GitHubApi(transport).primary_language(REPO)

    assert transport.requests[0][1]["Authorization"] == "Bearer from-env"


def test_no_token_means_no_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a token the request is anonymous."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    transport = FakeTransport()

    _ = GitHubApi(transport).primary_language(REPO)

    assert "Authorization" not in transport.requests[0][1]


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_unusable_responses_raise_unavailable(status: int) -> None:
    """Rate limits and server errors are reported as an unavailable GitHub."""
    path = "/repos/BurntSushi/ripgrep/releases/latest"
    api = GitHubApi(FakeTransport({path: (status, {})}), token=None)

    with pytest.raises(GitHubUnavailableError):
        _ = api.latest_release_assets(REPO)


def test_network_errors_raise_unavailable() -> None:
    """A transport that cannot connect is reported as an unavailable GitHub."""
    api = GitHubApi(FakeTransport(error=OSError("offline")), token=None)

    with pytest.raises(GitHubUnavailableError, match="offline"):
        _ = api.primary_language(REPO)
