"""The repository mibare is asked about, and how to recognise it in text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mibare.core.errors import InvalidRepositoryError

__all__ = ["Repository", "parse_repository"]

_SEGMENT = r"[A-Za-z0-9_.-]+"
_DOT_SEGMENTS = frozenset({".", ".."})
_SHORTHAND = re.compile(rf"({_SEGMENT})/({_SEGMENT})")
_URL_TAIL = r"(?:/[^?#]*)?(?:\?[^#]*)?(?:#.*)?"  # extra path, query, fragment
_URL = re.compile(
    rf"(?:https?://)?(?:www\.)?github\.com/({_SEGMENT})/({_SEGMENT}){_URL_TAIL}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Repository:
    """A GitHub repository.

    Attributes:
        owner: The account that owns the repository.
        name: The repository name, without any ``.git`` suffix.
    """

    owner: str
    name: str

    @property
    def shorthand(self) -> str:
        """The ``owner/repo`` shorthand.

        Returns:
            str: The shorthand.
        """
        return f"{self.owner}/{self.name}"


def parse_repository(text: str) -> Repository:
    """Parse a GitHub URL or ``owner/repo`` shorthand.

    Tolerates surrounding whitespace, trailing slashes, a ``.git`` suffix, a
    ``www.`` prefix, a missing scheme, extra path segments and a query or
    fragment (both ignored).

    Args:
        text: The user's input.

    Returns:
        Repository: The repository the input names.

    Raises:
        InvalidRepositoryError: If the input does not name a GitHub repository.
    """
    cleaned = text.strip().rstrip("/")
    match = _URL.fullmatch(cleaned) or _SHORTHAND.fullmatch(cleaned)
    if match is None:
        message = (
            f"Not a GitHub repository: {text!r}. Give a github.com URL or owner/repo."
        )
        raise InvalidRepositoryError(message)
    owner, name = match.groups()
    name = name.removesuffix(".git")
    if not name or {owner, name} & _DOT_SEGMENTS:
        message = f"Not a GitHub repository: {text!r}."
        raise InvalidRepositoryError(message)
    return Repository(owner, name)
