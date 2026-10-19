"""Tests for the GitHub adapter, through an injected fake HTTP transport."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import TYPE_CHECKING

import pytest

from mibare.core.errors import GitHubUnavailableError
from mibare.core.github import GitHubApi, HttpResponse, urllib_transport
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


TREE_PATH = "/repos/BurntSushi/ripgrep/git/trees/HEAD?recursive=1"


def test_list_files_returns_every_file_path_in_one_request() -> None:
    """The recursive tree gives all blob paths; directories are left out."""
    tree = [
        {"path": "cmd", "type": "tree"},
        {"path": "cmd/a", "type": "tree"},
        {"path": "cmd/a/main.go", "type": "blob"},
        {"path": "go.mod", "type": "blob"},
        {"path": "vendor/x", "type": "commit"},
        {"type": "blob"},
    ]
    transport = FakeTransport({TREE_PATH: (200, {"tree": tree, "truncated": False})})

    files = GitHubApi(transport, token=None).list_files(REPO)

    assert files.paths == ("cmd/a/main.go", "go.mod")
    assert not files.truncated
    assert len(transport.requests) == 1


def test_list_files_reports_a_truncated_listing() -> None:
    """GitHub's ``truncated`` flag is passed on with the paths it did send."""
    tree = [{"path": "a.go", "type": "blob"}]
    transport = FakeTransport({TREE_PATH: (200, {"tree": tree, "truncated": True})})

    files = GitHubApi(transport, token=None).list_files(REPO)

    assert files.paths == ("a.go",)
    assert files.truncated


@pytest.mark.parametrize("body", [{}, {"tree": "x"}, [], {"tree": [3, "x"]}], ids=str)
def test_list_files_is_empty_for_an_unreadable_tree(body: object) -> None:
    """An unexpected body lists nothing."""
    transport = FakeTransport({TREE_PATH: (200, body)})

    files = GitHubApi(transport, token=None).list_files(REPO)

    assert files.paths == ()
    assert not files.truncated


def test_list_files_of_an_empty_repository_is_empty() -> None:
    """A 404 (no such tree) lists nothing."""
    files = GitHubApi(FakeTransport(), token=None).list_files(REPO)

    assert files.paths == ()


def test_list_files_failure_is_github_unavailable() -> None:
    """A non-404 error status raises ``GitHubUnavailableError``."""
    transport = FakeTransport({TREE_PATH: (500, {})})

    with pytest.raises(GitHubUnavailableError):
        _ = GitHubApi(transport, token=None).list_files(REPO)


def _file_body(content: object, kind: str = "file") -> dict[str, object]:
    """Build a contents-API body for a root file.

    Returns:
        dict[str, object]: The body.
    """
    return {"type": kind, "encoding": "base64", "content": content}


@pytest.mark.parametrize(
    "body",
    [
        _file_body("aGk=", kind="dir"),
        _file_body(None),
        _file_body("!!!not base64!!!"),
        _file_body(base64.b64encode(b"\xff\xfe").decode()),
    ],
    ids=["not-a-file", "no-content", "bad-base64", "not-utf8"],
)
def test_root_file_is_none_when_the_contents_are_not_text(
    body: dict[str, object],
) -> None:
    """A directory, a missing payload or undecodable bytes give ``None``."""
    path = "/repos/BurntSushi/ripgrep/contents/pyproject.toml"
    transport = FakeTransport({path: (200, body)})

    assert GitHubApi(transport, token=None).root_file(REPO, "pyproject.toml") is None


def test_a_release_without_an_assets_list_has_no_assets() -> None:
    """A release answer whose ``assets`` is not a list gives no assets."""
    route = "/repos/BurntSushi/ripgrep/releases/latest"
    transport = FakeTransport({route: (200, {"assets": "none"})})

    assert GitHubApi(transport, token=None).latest_release_assets(REPO) == ()


def test_an_unreadable_answer_raises_unavailable() -> None:
    """A 200 whose body is not JSON is reported as an unavailable GitHub."""

    def transport(url: str, headers: Mapping[str, str]) -> HttpResponse:
        del url, headers
        return HttpResponse(200, b"<html>not json</html>")

    with pytest.raises(GitHubUnavailableError, match="unreadable"):
        _ = GitHubApi(transport, token=None).primary_language(REPO)


class _Reply:
    """A stand-in for the object ``urlopen`` returns."""

    status = 200

    def __init__(self) -> None:
        """Start open, with a fixed body."""
        self.closed = False
        self.body = b"{}"

    def read(self) -> bytes:
        """Return a fixed body.

        Returns:
            bytes: The body.
        """
        return self.body

    def close(self) -> None:
        """Record the close."""
        self.closed = True


def test_the_urllib_transport_returns_the_reply_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful request returns its status and body and releases the reply."""
    reply = _Reply()
    seen: list[urllib.request.Request] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> _Reply:
        del timeout
        seen.append(request)
        return reply

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    response = urllib_transport("https://api.github.com/x", {"Accept": "a/b"})

    assert response == HttpResponse(200, b"{}")
    assert reply.closed
    assert seen[0].full_url == "https://api.github.com/x"
    assert seen[0].get_header("Accept") == "a/b"


def test_the_urllib_transport_returns_error_statuses_as_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An HTTP error status is returned, not raised, so 404 can mean absent."""
    errors: list[urllib.error.HTTPError] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> _Reply:
        del timeout
        errors.append(
            urllib.error.HTTPError(
                request.full_url, 404, "Not Found", Message(), io.BytesIO(b"nope")
            )
        )
        raise errors[0]

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    response = urllib_transport("https://api.github.com/x", {})

    errors[0].close()
    assert response == HttpResponse(404, b"nope")
