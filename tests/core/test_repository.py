"""Tests for reading a repository from user input."""

from __future__ import annotations

import pytest

from mibare.core.errors import InvalidRepositoryError
from mibare.core.repository import Repository, parse_repository


@pytest.mark.parametrize(
    "text",
    [
        "BurntSushi/ripgrep",
        "https://github.com/BurntSushi/ripgrep/",
        "github.com/BurntSushi/ripgrep.git",
    ],
)
def test_shorthand_and_urls_name_the_same_repository(text: str) -> None:
    """Shorthand, URLs and ``.git`` URLs all parse to one repository."""
    assert parse_repository(text) == Repository("BurntSushi", "ripgrep")


@pytest.mark.parametrize("text", ["ripgrep", "https://example.com/a/b", "owner/.git"])
def test_text_that_names_no_repository_is_rejected(text: str) -> None:
    """Input that is not a GitHub repository, or has an empty name, raises."""
    with pytest.raises(InvalidRepositoryError, match="Not a GitHub repository"):
        _ = parse_repository(text)
